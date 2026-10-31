"""Review-only adapter for signed VHAS HCP approvals."""

import hashlib
import json
from dataclasses import asdict, dataclass

from vhas_core_proposals import CoreProposal
from vhas_hcp_verifier import HCPApproval, HCPVerifier


@dataclass(frozen=True)
class HCPReviewDecision:
    proposal_id: str
    review_allowed: bool = False
    approved: bool = False
    deployment_allowed: bool = False
    reason: str = "Independent human review is required."


def canonical_proposal_bytes(proposal):
    if not isinstance(proposal, CoreProposal):
        raise TypeError("Expected a CoreProposal")

    return json.dumps(
        asdict(proposal),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


class HCPReviewAdapter:
    def __init__(self, verifier):
        if not isinstance(verifier, HCPVerifier):
            raise TypeError("Expected an HCPVerifier")
        self.verifier = verifier

    def evaluate(self, proposal, approval, signature):
        proposal_id = (
            proposal.proposal_id
            if isinstance(proposal, CoreProposal)
            and isinstance(proposal.proposal_id, str)
            else ""
        )

        denied = HCPReviewDecision(proposal_id=proposal_id)

        if not isinstance(proposal, CoreProposal):
            return denied

        if not isinstance(approval, HCPApproval):
            return denied

        if (
            not isinstance(proposal.proposal_id, str)
            or not proposal.proposal_id.strip()
            or approval.proposal_id != proposal.proposal_id
        ):
            return denied

        try:
            proposal_bytes = canonical_proposal_bytes(proposal)
        except (TypeError, ValueError, OverflowError):
            return denied

        if approval.proposal_sha256 != hashlib.sha256(
            proposal_bytes
        ).hexdigest():
            return denied

        verification = self.verifier.verify(
            approval,
            signature,
            proposal.proposal_id,
            proposal_bytes,
        )

        if not verification.review_allowed:
            return denied

        return HCPReviewDecision(
            proposal_id=proposal.proposal_id,
            review_allowed=True,
            approved=False,
            deployment_allowed=False,
            reason="Signed permission to review this proposal verified.",
        )
