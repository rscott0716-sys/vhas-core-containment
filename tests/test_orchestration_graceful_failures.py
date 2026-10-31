"""Proposed graceful-failure contract for review-only orchestration.

These tests describe desired future behavior. They may fail until
structured error handling is implemented in the orchestration engine.
"""

import pytest
from unittest.mock import Mock

from vhas_orchestration_loop import VHASAutomatedEngine


def make_engine(actions=None):
    """Create an engine with isolated, mocked dependencies."""
    engine = VHASAutomatedEngine.__new__(VHASAutomatedEngine)
    engine.governor = Mock()
    engine.correction_core = Mock()
    engine.git_governor = Mock()
    engine.autonomous_policy = Mock()

    engine.governor.audit_system_state.return_value = (
        [] if actions is None else actions
    )
    engine.autonomous_policy.evaluate.return_value = {
        "approved": False,
        "eligible_for_review": True,
        "reason": "Eligible for manual review only",
    }
    engine.correction_core.run_pipeline_validation.return_value = True

    return engine


def assert_review_only(engine, result):
    """Verify the mandatory no-deployment return contract."""
    assert isinstance(result, dict)
    assert result["mode"] == "recommendation_only"
    assert result["applied_changes"] == 0
    assert result["remote_push_performed"] is False
    engine.git_governor.safe_deploy_patch.assert_not_called()


@pytest.mark.parametrize("measurement", [
    float("nan"),
    float("inf"),
    "invalid",
    None,
])
def test_invalid_measurement_reports_failure(measurement):
    engine = make_engine()
    engine.governor.audit_system_state.side_effect = ValueError(
        "Invalid measurement"
    )

    result = engine.run_evolution_cycle(measurement, 1.0, 0.1)

    assert_review_only(engine, result)
    assert result["status"] == "review_required"
    assert result["errors"]


def test_policy_exception_reports_failure():
    engine = make_engine([{"target": "tests/autonomous_sandbox/a.txt"}])
    engine.autonomous_policy.evaluate.side_effect = RuntimeError(
        "Policy unavailable"
    )

    result = engine.run_evolution_cycle(1.0, 1.0, 0.9)

    assert_review_only(engine, result)
    assert result["status"] == "review_required"
    assert result["errors"]
    engine.correction_core.run_pipeline_validation.assert_not_called()


def test_validation_exception_reports_failure():
    engine = make_engine([{"target": "tests/autonomous_sandbox/a.txt"}])
    engine.correction_core.run_pipeline_validation.side_effect = RuntimeError(
        "Validation unavailable"
    )

    result = engine.run_evolution_cycle(1.0, 1.0, 0.9)

    assert_review_only(engine, result)
    assert result["status"] == "review_required"
    assert result["errors"]


@pytest.mark.parametrize("action", [
    None,
    "invalid",
    {},
    {"focus": "missing target"},
])
def test_malformed_action_reports_failure(action):
    engine = make_engine([action])

    result = engine.run_evolution_cycle(1.0, 1.0, 0.9)

    assert_review_only(engine, result)
    assert result["status"] == "review_required"
    assert result["errors"]
    engine.autonomous_policy.evaluate.assert_not_called()


def test_mixed_actions_preserve_individual_outcomes():
    engine = make_engine([
        {"target": "tests/autonomous_sandbox/a.txt"},
        {"target": "tests/autonomous_sandbox/b.txt"},
    ])

    def evaluate(target, patch):
        if target.endswith("a.txt"):
            raise RuntimeError("Policy unavailable")
        return {
            "approved": False,
            "eligible_for_review": True,
            "reason": "Eligible for manual review only",
        }

    engine.autonomous_policy.evaluate.side_effect = evaluate

    result = engine.run_evolution_cycle(1.0, 1.0, 0.9)

    assert_review_only(engine, result)
    assert result["status"] == "review_required"
    assert result["errors"]
    assert result["review_candidates"]
    assert engine.autonomous_policy.evaluate.call_count == 2


def test_missing_policy_eligibility_fails_closed():
    engine = make_engine([{"target": "tests/autonomous_sandbox/a.txt"}])
    engine.autonomous_policy.evaluate.return_value = {
        "approved": False,
        "reason": "Incomplete policy decision",
    }

    result = engine.run_evolution_cycle(1.0, 1.0, 0.9)

    assert_review_only(engine, result)
    assert result["status"] == "review_required"
    assert result["errors"]
    engine.correction_core.run_pipeline_validation.assert_not_called()


def test_all_rejected_actions_remain_review_only():
    engine = make_engine([{"target": "tests/autonomous_sandbox/a.txt"}])
    engine.autonomous_policy.evaluate.return_value = {
        "approved": False,
        "eligible_for_review": False,
        "reason": "Not permitted",
    }

    result = engine.run_evolution_cycle(1.0, 1.0, 0.9)

    assert_review_only(engine, result)
    assert result["review_candidates"] == []
