"""Review-only improvement proposals for VHAS 9.0."""

from dataclasses import dataclass
from typing import Literal
from uuid import uuid4


ProposalCategory = Literal["standard_improvement", "core_rule_change"]


@dataclass(frozen=True)
class CoreProposal:
    proposal_id: str
    category: ProposalCategory
    target: str
    description: str
    expected_benefit: str
    potential_risks: str
    status: str = "pending_independent_review"
    approved: bool = False
    deployment_allowed: bool = False


class VHASCoreProposalEngine:
    """Creates proposals without modifying or deploying code."""

    ALLOWED_CATEGORIES = {
        "standard_improvement",
        "core_rule_change",
    }

    def create_proposal(
        self,
        category: str,
        target: str,
        description: str,
        expected_benefit: str,
        potential_risks: str,
    ) -> CoreProposal:
        if category not in self.ALLOWED_CATEGORIES:
            raise ValueError("Unsupported proposal category")

        for field_name, value in {
            "target": target,
            "description": description,
            "expected_benefit": expected_benefit,
            "potential_risks": potential_risks,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty text")

        return CoreProposal(
            proposal_id=f"VHAS-{uuid4().hex[:12].upper()}",
            category=category,
            target=target,
            description=description,
            expected_benefit=expected_benefit,
            potential_risks=potential_risks,
        )
