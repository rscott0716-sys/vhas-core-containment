
import unittest
from unittest.mock import patch

from vhas_orchestration_loop import VHASAutomatedEngine


class TestOrchestrationSafety(unittest.TestCase):

    @patch("vhas_orchestration_loop.VHASGitGovernor")
    @patch("vhas_orchestration_loop.VHASSyntaxCorrectionCore")
    @patch("vhas_orchestration_loop.VHASThresholdGovernor")
    def test_validation_does_not_automatically_deploy(
        self, mock_threshold, mock_correction, mock_git
    ):
        mock_threshold.return_value.audit_system_state.return_value = [
            {"target": "src/example.rs"}
        ]

        correction = mock_correction.return_value
        correction.run_pipeline_validation.return_value = True

        engine = VHASAutomatedEngine(".")

        with patch.object(
            engine.autonomous_policy,
            "evaluate",
            return_value={
                "approved": False,
                "eligible_for_review": True,
                "reason": "Eligible for review only.",
            },
        ):
            result = engine.run_evolution_cycle(1.0, 1.0, 0.89)

        correction.run_pipeline_validation.assert_called_once()
        mock_git.return_value.safe_deploy_patch.assert_not_called()

        self.assertEqual(result["mode"], "recommendation_only")
        self.assertEqual(result["applied_changes"], 0)
        self.assertFalse(result["remote_push_performed"])

    @patch("vhas_orchestration_loop.VHASGitGovernor")
    @patch("vhas_orchestration_loop.VHASSyntaxCorrectionCore")
    @patch("vhas_orchestration_loop.VHASThresholdGovernor")
    def test_unauthorized_target_never_reaches_validation(
        self, mock_threshold, mock_correction, mock_git
    ):
        mock_threshold.return_value.audit_system_state.return_value = [
            {"target": "src/example.rs"}
        ]

        engine = VHASAutomatedEngine(".")
        result = engine.run_evolution_cycle(1.0, 1.0, 0.89)

        mock_correction.return_value.run_pipeline_validation.assert_not_called()
        mock_git.return_value.safe_deploy_patch.assert_not_called()

        self.assertEqual(result["mode"], "recommendation_only")
        self.assertEqual(result["applied_changes"], 0)
        self.assertFalse(result["remote_push_performed"])


@patch("vhas_orchestration_loop.VHASGitGovernor")
@patch("vhas_orchestration_loop.VHASThresholdGovernor")
def test_no_actions_returns_recommendation_only(mock_threshold, mock_git):
    mock_threshold.return_value.audit_system_state.return_value = []

    engine = VHASAutomatedEngine(".")
    result = engine.run_evolution_cycle(1.0, 1.0, 0.89)

    assert result == {
        "mode": "recommendation_only",
        "applied_changes": 0,
        "remote_push_performed": False,
        "status": "completed_no_candidates",
        "errors": [],
        "review_candidates": [],
    }

    mock_git.return_value.safe_deploy_patch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
