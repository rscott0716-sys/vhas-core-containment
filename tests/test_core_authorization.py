import pytest

from vhas_core_authorization import VHASCoreAuthorization


def test_valid_proposal_is_not_authorized():
    decision = VHASCoreAuthorization().evaluate("VHAS-TEST-001")

    assert decision.authorized is False
    assert decision.deployment_allowed is False


def test_human_authorization_is_required():
    decision = VHASCoreAuthorization().evaluate("VHAS-TEST-002")

    assert decision.reason == "External human authorization is required."


@pytest.mark.parametrize("proposal_id", ["", "   ", None, 123])
def test_invalid_proposal_id_is_rejected(proposal_id):
    with pytest.raises(ValueError):
        VHASCoreAuthorization().evaluate(proposal_id)
