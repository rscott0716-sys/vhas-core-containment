use std::panic::{catch_unwind, AssertUnwindSafe};
use std::collections::HashMap;
use std::sync::Mutex;

lazy_static::lazy_static! {
    pub static ref VHAS_STATE_VECTOR: Mutex<HashMap<String, f64>> = {
        let mut m = HashMap::new();
        m.insert("homeostatic_coherence".to_string(), 1.0);
        m.insert("affiliative_resonance".to_string(), 1.0);
        m.insert("compute_cost".to_string(), 0.10);
        Mutex::new(m)
    };
}

pub fn execute_safe_gate_block<F, R>(evolution_patch_block: F) -> Result<R, String>
where
    F: FnOnce() -> R + std::panic::UnwindSafe,
{
    let execution_result = catch_unwind(AssertUnwindSafe(evolution_patch_block));
    match execution_result {
        Ok(success_output) => Ok(success_output),
        Err(panic_payload) => {
            let error_msg = if let Some(s) = panic_payload.downcast_ref::<&str>() {
                s.to_string()
            } else if let Some(s) = panic_payload.downcast_ref::<String>() {
                s.clone()
            } else {
                "Unknown execution panic payload intercepted within micro-kernel block.".to_string()
            };

            if let Ok(mut state) = VHAS_STATE_VECTOR.lock() {
                if let Some(coherence) = state.get_mut("homeostatic_coherence") { *coherence *= 0.50; }
                if let Some(compute) = state.get_mut("compute_cost") { *compute = 0.99; }
            }
            Err(error_msg)
        }
    }
}
