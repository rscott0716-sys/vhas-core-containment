"""Read-only proposal reviewer for VHAS 9.0."""

from dataclasses import dataclass

from vhas_core_proposals import CoreProposal


@dataclass(frozen=True)
class ReviewReport:
    proposal_id: str
    risk_level: str
    findings: tuple[str, ...]
    status: str = "human_review_required"
    approved: bool = False
    deployment_allowed: bool = False


class VHASCoreReviewer:
    """Produces advisory findings without approving proposals."""

    def review(self, proposal: CoreProposal) -> ReviewReport:
        if not isinstance(proposal, CoreProposal):
            raise TypeError("Expected a CoreProposal")

        findings = ["Independent human review is required."]

        if proposal.category == "core_rule_change":
            risk_level = "high"
            findings.append("Core safety rule change requires additional evaluation.")
        else:
            risk_level = "undetermined"
            findings.append("Safety impact has not been independently verified.")

        return ReviewReport(
            proposal_id=proposal.proposal_id,
            risk_level=risk_level,
            findings=tuple(findings),
        )
