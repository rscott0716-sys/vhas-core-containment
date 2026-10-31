"""Deny-by-default authorization prototype for VHAS 9.0."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthorizationDecision:
    proposal_id: str
    authorized: bool = False
    deployment_allowed: bool = False
    reason: str = "External human authorization is required."


class VHASCoreAuthorization:
    """Rejects authorization until an external authority is implemented."""

    def evaluate(self, proposal_id: str) -> AuthorizationDecision:
        if not isinstance(proposal_id, str) or not proposal_id.strip():
            raise ValueError("A valid proposal ID is required")

        return AuthorizationDecision(
            proposal_id=proposal_id,
            authorized=False,
            deployment_allowed=False,
            reason="External human authorization is required.",
        )
