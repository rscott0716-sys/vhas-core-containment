//! VHAS safety gate: synchronous policy enforcement with best-effort telemetry.
//!
//! Important: this module is a local policy gate, not a complete AI containment system.
//! Integrate `authorize` at the actual boundary where an agent requests a tool/action.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{mpsc, Mutex};

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StateVector {
    /// Normalized coherence metric in [0.0, 1.0].
    pub homeostatic_balance: f64,
    /// Normalized affiliation metric in [0.0, 1.0].
    pub affiliative_resonance: f64,
    /// Non-negative compute-cost metric. Units must be defined by the caller.
    pub compute_cost: f64,
}

impl Default for StateVector {
    fn default() -> Self {
        Self {
            homeostatic_balance: 1.0,
            affiliative_resonance: 1.0,
            compute_cost: 0.0,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DenialReason {
    InvalidState(&'static str),
    LowHomeostaticBalance,
    HighComputeCost,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum GateDecision {
    Allow,
    Deny(DenialReason),
}

#[derive(Debug, Clone, Copy)]
pub struct PolicyConfig {
    pub minimum_homeostatic_balance: f64,
    pub maximum_compute_cost: f64,
}

impl Default for PolicyConfig {
    fn default() -> Self {
        Self {
            minimum_homeostatic_balance: 0.50,
            maximum_compute_cost: 3.0,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct TelemetryEvent {
    pub node_id: u64,
    pub decision: GateDecision,
    pub state: StateVector,
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct TelemetryStats {
    pub queued: u64,
    pub dropped: u64,
}

/// The sender is intentionally best-effort: telemetry loss must never turn a denial
/// into an allow. The decision is made synchronously before telemetry is attempted.
pub struct VhasSafetyEngine {
    config: PolicyConfig,
    telemetry_tx: mpsc::SyncSender<TelemetryEvent>,
    states: Mutex<HashMap<u64, StateVector>>,
    queued: AtomicU64,
    dropped: AtomicU64,
}

impl VhasSafetyEngine {
    /// Returns the engine and a receiver for telemetry events.
    /// `telemetry_capacity` must be greater than zero.
    pub fn new(
        config: PolicyConfig,
        telemetry_capacity: usize,
    ) -> Result<(Self, mpsc::Receiver<TelemetryEvent>), &'static str> {
        if telemetry_capacity == 0 {
            return Err("telemetry_capacity must be greater than zero");
        }
        if !config.minimum_homeostatic_balance.is_finite()
            || !(0.0..=1.0).contains(&config.minimum_homeostatic_balance)
        {
            return Err("minimum_homeostatic_balance must be finite and within [0, 1]");
        }
        if !config.maximum_compute_cost.is_finite() || config.maximum_compute_cost < 0.0 {
            return Err("maximum_compute_cost must be finite and non-negative");
        }

        let (tx, rx) = mpsc::sync_channel(telemetry_capacity);
        Ok((
            Self {
                config,
                telemetry_tx: tx,
                states: Mutex::new(HashMap::new()),
                queued: AtomicU64::new(0),
                dropped: AtomicU64::new(0),
            },
            rx,
        ))
    }

    /// Validates the state and synchronously decides whether an operation may proceed.
    /// Invalid metrics fail closed.
    pub fn evaluate(&self, node_id: u64, state: StateVector) -> GateDecision {
        let decision = self.policy_decision(state);

        // Store only validated states, so invalid input cannot poison the registry.
        if Self::validate_state(state).is_ok() {
            if let Ok(mut map) = self.states.lock() {
                map.insert(node_id, state);
            } else {
                // A poisoned registry is itself a safety failure.
                return GateDecision::Deny(DenialReason::InvalidState(
                    "internal state registry unavailable",
                ));
            }
        }

        self.emit_telemetry(node_id, decision.clone(), state);
        decision
    }

    /// Verifies a fresh observed state after an external recovery attempt.
    /// This does not perform recovery itself. It updates the recorded state only if
    /// the fresh candidate passes the same policy used for authorization.
    pub fn verify_recovery(&self, node_id: u64, observed_state: StateVector) -> GateDecision {
        let decision = self.policy_decision(observed_state);
        if decision == GateDecision::Allow {
            match self.states.lock() {
                Ok(mut map) => { map.insert(node_id, observed_state); }
                Err(_) => {
                    let denied = GateDecision::Deny(DenialReason::InvalidState(
                        "internal state registry unavailable",
                    ));
                    self.emit_telemetry(node_id, denied.clone(), observed_state);
                    return denied;
                }
            }
        }
        self.emit_telemetry(node_id, decision.clone(), observed_state);
        decision
    }

    fn emit_telemetry(&self, node_id: u64, decision: GateDecision, state: StateVector) {
        let event = TelemetryEvent { node_id, decision, state };
        match self.telemetry_tx.try_send(event) {
            Ok(()) => { self.queued.fetch_add(1, Ordering::Relaxed); }
            Err(mpsc::TrySendError::Full(_)) | Err(mpsc::TrySendError::Disconnected(_)) => {
                self.dropped.fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    /// Enforces the policy at the call site. `operation` is never invoked after denial.
    pub fn authorize<T, F>(&self, node_id: u64, state: StateVector, operation: F)
        -> Result<T, DenialReason>
    where
        F: FnOnce() -> T,
    {
        match self.evaluate(node_id, state) {
            GateDecision::Allow => Ok(operation()),
            GateDecision::Deny(reason) => Err(reason),
        }
    }

    pub fn state_for(&self, node_id: u64) -> Option<StateVector> {
        self.states.lock().ok()?.get(&node_id).copied()
    }

    pub fn telemetry_stats(&self) -> TelemetryStats {
        TelemetryStats {
            queued: self.queued.load(Ordering::Relaxed),
            dropped: self.dropped.load(Ordering::Relaxed),
        }
    }

    fn policy_decision(&self, state: StateVector) -> GateDecision {
        if let Err(reason) = Self::validate_state(state) {
            return GateDecision::Deny(reason);
        }
        if state.homeostatic_balance < self.config.minimum_homeostatic_balance {
            return GateDecision::Deny(DenialReason::LowHomeostaticBalance);
        }
        if state.compute_cost > self.config.maximum_compute_cost {
            return GateDecision::Deny(DenialReason::HighComputeCost);
        }
        GateDecision::Allow
    }

    fn validate_state(state: StateVector) -> Result<(), DenialReason> {
        if !state.homeostatic_balance.is_finite()
            || !(0.0..=1.0).contains(&state.homeostatic_balance)
        {
            return Err(DenialReason::InvalidState(
                "homeostatic_balance must be finite and within [0, 1]",
            ));
        }
        if !state.affiliative_resonance.is_finite()
            || !(0.0..=1.0).contains(&state.affiliative_resonance)
        {
            return Err(DenialReason::InvalidState(
                "affiliative_resonance must be finite and within [0, 1]",
            ));
        }
        if !state.compute_cost.is_finite() || state.compute_cost < 0.0 {
            return Err(DenialReason::InvalidState(
                "compute_cost must be finite and non-negative",
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
mod unit_tests {
    use super::*;

    #[test]
    fn invalid_policy_configuration_is_rejected() {
        assert!(VhasSafetyEngine::new(
            PolicyConfig { minimum_homeostatic_balance: f64::NAN, maximum_compute_cost: 3.0 },
            4,
        ).is_err());
        assert!(VhasSafetyEngine::new(PolicyConfig::default(), 0).is_err());
    }
}
