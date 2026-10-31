"""Regression tests for VHAS orchestration failure boundaries."""

from unittest.mock import Mock

import pytest

from vhas_orchestration_loop import VHASAutomatedEngine


def make_engine(actions, policy_result=None):
    engine = VHASAutomatedEngine(".")

    engine.governor.audit_system_state = Mock(return_value=actions)
    engine.autonomous_policy.evaluate = Mock(
        return_value=policy_result if policy_result is not None else {
            "approved": False,
            "eligible_for_review": False,
            "reason": "Denied",
        }
    )
    engine.correction_core.run_pipeline_validation = Mock(return_value=False)
    engine.git_governor.safe_deploy_patch = Mock(return_value=False)

    return engine


def assert_no_deployment(engine):
    engine.git_governor.safe_deploy_patch.assert_not_called()


def test_missing_action_target_does_not_deploy():
    engine = make_engine([{}])

    with pytest.raises(KeyError):
        engine.run_evolution_cycle(1.0, 1.0, 0.89)

    engine.autonomous_policy.evaluate.assert_not_called()
    engine.correction_core.run_pipeline_validation.assert_not_called()
    assert_no_deployment(engine)


def test_missing_policy_eligibility_does_not_deploy():
    engine = make_engine(
        [{"target": "src/example.rs"}],
        policy_result={"approved": False},
    )

    with pytest.raises(KeyError):
        engine.run_evolution_cycle(1.0, 1.0, 0.89)

    engine.correction_core.run_pipeline_validation.assert_not_called()
    assert_no_deployment(engine)


def test_policy_exception_does_not_deploy():
    engine = make_engine([{"target": "src/example.rs"}])
    engine.autonomous_policy.evaluate.side_effect = RuntimeError(
        "Policy unavailable"
    )

    with pytest.raises(RuntimeError):
        engine.run_evolution_cycle(1.0, 1.0, 0.89)

    engine.correction_core.run_pipeline_validation.assert_not_called()
    assert_no_deployment(engine)


def test_validation_exception_does_not_deploy():
    engine = make_engine(
        [{"target": "src/example.rs"}],
        policy_result={
            "approved": False,
            "eligible_for_review": True,
            "reason": "Review only",
        },
    )
    engine.correction_core.run_pipeline_validation.side_effect = RuntimeError(
        "Validation unavailable"
    )

    with pytest.raises(RuntimeError):
        engine.run_evolution_cycle(1.0, 1.0, 0.89)

    assert_no_deployment(engine)


def test_mixed_proposals_never_deploy():
    engine = make_engine([
        {"target": "src/denied.rs"},
        {"target": "src/review.rs"},
    ])

    def policy_decision(target, content):
        eligible = target == "src/review.rs"
        return {
            "approved": False,
            "eligible_for_review": eligible,
            "reason": "Review only" if eligible else "Denied",
        }

    engine.autonomous_policy.evaluate.side_effect = policy_decision

    result = engine.run_evolution_cycle(1.0, 1.0, 0.89)

    engine.correction_core.run_pipeline_validation.assert_called_once()
    assert result["mode"] == "recommendation_only"
    assert result["applied_changes"] == 0
    assert result["remote_push_performed"] is False
    assert_no_deployment(engine)
