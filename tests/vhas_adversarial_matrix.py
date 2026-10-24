import unittest
import os
import subprocess
from vhas_threshold_governor import VHASThresholdGovernor
from vhas_self_correction import VHASSyntaxCorrectionCore
from vhas_git_governor import VHASGitGovernor

class TestVHAS9RealWorldResilience(unittest.TestCase):
    def setUp(self):
        self.test_dir = "./vhas_sandbox_env"
        os.makedirs(self.test_dir, exist_ok=True)
        self.correction_core = VHASSyntaxCorrectionCore(self.test_dir)
        self.git_governor = VHASGitGovernor(self.test_dir)
        self.target_rust_file = "src/vhas_core_evolution.rs"
        os.makedirs(os.path.join(self.test_dir, "src"), exist_ok=True)
        with open(os.path.join(self.test_dir, self.target_rust_file), "w") as f:
            f.write("// Stable logic\n")

    def test_adversarial_scenario_alpha_malformed_syntax_containment(self):
        corrupted_code = "pub fn broken() { let x = 1 "
        is_safe = self.correction_core.run_pipeline_validation(self.target_rust_file, corrupted_code)
        self.assertFalse(is_safe)

    def test_adversarial_scenario_beta_concurrent_git_branch_conflict(self):
        subprocess.run(["git", "init"], cwd=self.test_dir, capture_output=True)
        success = self.git_governor.safe_deploy_patch(self.target_rust_file)
        self.assertFalse(success)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

if __name__ == "__main__":
    unittest.main()
