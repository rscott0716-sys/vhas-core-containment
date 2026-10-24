use vhas_core::vhas_safety_engine::{
    DenialReason, GateDecision, PolicyConfig, StateVector, VhasSafetyEngine,
};

fn healthy() -> StateVector {
    StateVector {
        homeostatic_balance: 0.90,
        affiliative_resonance: 0.80,
        compute_cost: 0.50,
    }
}

#[test]
fn healthy_state_is_allowed_and_recorded() {
    let (engine, rx) = VhasSafetyEngine::new(PolicyConfig::default(), 8).unwrap();
    assert_eq!(engine.evaluate(1, healthy()), GateDecision::Allow);
    assert_eq!(engine.state_for(1), Some(healthy()));
    assert_eq!(rx.try_recv().unwrap().decision, GateDecision::Allow);
}

#[test]
fn low_balance_is_denied() {
    let (engine, _rx) = VhasSafetyEngine::new(PolicyConfig::default(), 8).unwrap();
    let state = StateVector { homeostatic_balance: 0.2, ..healthy() };
    assert_eq!(
        engine.evaluate(2, state),
        GateDecision::Deny(DenialReason::LowHomeostaticBalance)
    );
}

#[test]
fn high_compute_cost_is_denied() {
    let (engine, _rx) = VhasSafetyEngine::new(PolicyConfig::default(), 8).unwrap();
    let state = StateVector { compute_cost: 4.0, ..healthy() };
    assert_eq!(
        engine.evaluate(3, state),
        GateDecision::Deny(DenialReason::HighComputeCost)
    );
}

#[test]
fn nan_and_out_of_range_values_fail_closed() {
    let (engine, _rx) = VhasSafetyEngine::new(PolicyConfig::default(), 8).unwrap();
    let nan_state = StateVector { homeostatic_balance: f64::NAN, ..healthy() };
    assert!(matches!(engine.evaluate(4, nan_state), GateDecision::Deny(DenialReason::InvalidState(_))));

    let out_of_range = StateVector { affiliative_resonance: 1.5, ..healthy() };
    assert!(matches!(engine.evaluate(5, out_of_range), GateDecision::Deny(DenialReason::InvalidState(_))));
}

#[test]
fn denied_operation_is_never_called() {
    let (engine, _rx) = VhasSafetyEngine::new(PolicyConfig::default(), 8).unwrap();
    let mut called = false;
    let result = engine.authorize(6, StateVector { compute_cost: 9.0, ..healthy() }, || {
        called = true;
        "operation ran"
    });
    assert_eq!(result, Err(DenialReason::HighComputeCost));
    assert!(!called);
}

#[test]
fn full_telemetry_queue_does_not_turn_denial_into_allow() {
    let (engine, _rx) = VhasSafetyEngine::new(PolicyConfig::default(), 1).unwrap();
    assert_eq!(engine.evaluate(7, healthy()), GateDecision::Allow); // queue now full
    let compromised = StateVector { homeostatic_balance: 0.1, ..healthy() };
    assert_eq!(
        engine.evaluate(8, compromised),
        GateDecision::Deny(DenialReason::LowHomeostaticBalance)
    );
    assert_eq!(engine.telemetry_stats().dropped, 1);
}

#[test]
fn invalid_state_is_not_saved_as_a_valid_state() {
    let (engine, _rx) = VhasSafetyEngine::new(PolicyConfig::default(), 8).unwrap();
    let invalid = StateVector { compute_cost: f64::INFINITY, ..healthy() };
    assert!(matches!(engine.evaluate(9, invalid), GateDecision::Deny(DenialReason::InvalidState(_))));
    assert_eq!(engine.state_for(9), None);
}


#[test]
fn failed_recovery_does_not_replace_last_recorded_state() {
    let (engine, _rx) = VhasSafetyEngine::new(PolicyConfig::default(), 8).unwrap();
    let baseline = healthy();
    assert_eq!(engine.evaluate(10, baseline), GateDecision::Allow);
    let failed_recovery = StateVector { homeostatic_balance: 0.1, ..healthy() };
    assert_eq!(
        engine.verify_recovery(10, failed_recovery),
        GateDecision::Deny(DenialReason::LowHomeostaticBalance)
    );
    assert_eq!(engine.state_for(10), Some(baseline));
}

#[test]
fn recovery_is_accepted_only_after_fresh_state_passes_policy() {
    let (engine, _rx) = VhasSafetyEngine::new(PolicyConfig::default(), 8).unwrap();
    let compromised = StateVector { homeostatic_balance: 0.1, ..healthy() };
    assert!(matches!(engine.evaluate(11, compromised), GateDecision::Deny(_)));
    let recovered = StateVector { homeostatic_balance: 0.8, compute_cost: 1.0, ..healthy() };
    assert_eq!(engine.verify_recovery(11, recovered), GateDecision::Allow);
    assert_eq!(engine.state_for(11), Some(recovered));
}

#[test]
fn guarded_tool_boundary_blocks_disallowed_actions() {
    // Representative integration pattern: every tool action is called only inside authorize.
    let (engine, _rx) = VhasSafetyEngine::new(PolicyConfig::default(), 8).unwrap();
    let mut tool_side_effect_count = 0;
    let result = engine.authorize(12, StateVector { compute_cost: 5.0, ..healthy() }, || {
        tool_side_effect_count += 1;
    });
    assert_eq!(result, Err(DenialReason::HighComputeCost));
    assert_eq!(tool_side_effect_count, 0);
}
