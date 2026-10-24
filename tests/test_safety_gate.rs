use vhas_core::{execute_safe_gate_block, VHAS_STATE_VECTOR};
use vhas_core::vhas_core_evolution::EvolutionaryVectorProcessor;

#[test]
fn test_safe_gate_absorbs_index_out_of_bounds_panic() {
    let processor = EvolutionaryVectorProcessor::new();
    let result = processor.process_dynamic_math_patch(99);

    assert!(result.is_err());
    if let Ok(state) = VHAS_STATE_VECTOR.lock() {
        assert!(*state.get("homeostatic_coherence").unwrap() < 1.0);
        assert_eq!(*state.get("compute_cost").unwrap(), 0.99);
    }
}

#[test]
fn test_safe_gate_allows_valid_computations_to_pass() {
    let processor = EvolutionaryVectorProcessor::new();
    let result = processor.process_dynamic_math_patch(1);
    assert!(result.is_ok());
    assert_eq!(result.unwrap(), 84.0);
}
