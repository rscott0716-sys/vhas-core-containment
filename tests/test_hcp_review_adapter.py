"""Tests for the review-only HCP proposal adapter."""

import hashlib
import subprocess
from dataclasses import replace

from vhas_core_proposals import VHASCoreProposalEngine
from vhas_hcp_review_adapter import (
    HCPReviewAdapter,
    canonical_proposal_bytes,
)
from vhas_hcp_verifier import HCPApproval, HCPVerifier, canonical_bytes


def openssl(*args):
    subprocess.run(
        ["openssl", *map(str, args)],
        capture_output=True,
        check=True,
    )


def make_signed_review(tmp_path):
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    message = tmp_path / "approval.json"
    signature_file = tmp_path / "approval.sig"

    openssl("genpkey", "-algorithm", "ED25519", "-out", private)
    openssl("pkey", "-in", private, "-pubout", "-out", public)

    proposal = VHASCoreProposalEngine().create_proposal(
        category="standard_improvement",
        target="tests/autonomous_sandbox/example.txt",
        description="Improve documentation clarity.",
        expected_benefit="Easier independent review.",
        potential_risks="Documentation could be incomplete.",
    )

    proposal_bytes = canonical_proposal_bytes(proposal)

    approval = HCPApproval(
        approval_id="HCP-ADAPTER-238",
        proposal_id=proposal.proposal_id,
        proposal_sha256=hashlib.sha256(proposal_bytes).hexdigest(),
        action_scope="review_only",
        issued_at=1000,
        expires_at=2000,
        authority_key_id="TRUSTED-TEST-KEY",
        nonce="ADAPTER-238-NONCE",
    )

    message.write_bytes(canonical_bytes(approval))

    openssl(
        "pkeyutl", "-sign", "-rawin",
        "-inkey", private,
        "-in", message,
        "-out", signature_file,
    )

    verifier = HCPVerifier(
        public,
        "TRUSTED-TEST-KEY",
        tmp_path / "state.sqlite",
        clock=lambda: 1500,
    )

    return (
        HCPReviewAdapter(verifier),
        proposal,
        approval,
        signature_file.read_bytes(),
    )


def test_valid_signed_approval_permits_review_only(tmp_path):
    adapter, proposal, approval, signature = make_signed_review(tmp_path)

    decision = adapter.evaluate(proposal, approval, signature)

    assert decision.proposal_id == proposal.proposal_id
    assert decision.review_allowed is True
    assert decision.approved is False
    assert decision.deployment_allowed is False

    assert proposal.approved is False
    assert proposal.deployment_allowed is False


def test_changed_proposal_is_rejected(tmp_path):
    adapter, proposal, approval, signature = make_signed_review(tmp_path)

    altered = replace(
        proposal,
        description="Different proposal contents.",
    )

    decision = adapter.evaluate(altered, approval, signature)

    assert decision.review_allowed is False
    assert decision.approved is False
    assert decision.deployment_allowed is False


def test_mismatched_proposal_id_is_rejected(tmp_path):
    adapter, proposal, approval, signature = make_signed_review(tmp_path)

    altered = replace(proposal, proposal_id="VHAS-WRONG-ID")

    decision = adapter.evaluate(altered, approval, signature)

    assert decision.review_allowed is False
    assert decision.deployment_allowed is False


def test_signed_approval_cannot_be_replayed(tmp_path):
    adapter, proposal, approval, signature = make_signed_review(tmp_path)

    first = adapter.evaluate(proposal, approval, signature)
    second = adapter.evaluate(proposal, approval, signature)

    assert first.review_allowed is True
    assert second.review_allowed is False
    assert first.deployment_allowed is False
    assert second.deployment_allowed is False


def test_core_rule_change_still_cannot_deploy(tmp_path):
    adapter, proposal, _, _ = make_signed_review(tmp_path)

    core_proposal = replace(
        proposal,
        category="core_rule_change",
    )

    decision = adapter.evaluate(
        core_proposal,
        None,
        b"",
    )

    assert decision.review_allowed is False
    assert decision.approved is False
    assert decision.deployment_allowed is False


def test_signed_core_review_cannot_grant_authorization(tmp_path):
    """Signed review permission must never imply deployment authority."""
    from dataclasses import replace

    from vhas_core_authorization import VHASCoreAuthorization
    from vhas_core_reviewer import VHASCoreReviewer

    adapter, proposal, approval, signature = make_signed_review(tmp_path)

    # Change the proposal into a core safety rule review request.
    core_proposal = replace(
        proposal,
        category="core_rule_change",
    )

    # Recreate the approval's proposal hash for the core proposal.
    core_bytes = canonical_proposal_bytes(core_proposal)

    core_approval = replace(
        approval,
        proposal_sha256=hashlib.sha256(core_bytes).hexdigest(),
    )

    # Sign the updated approval using a fresh temporary test key.
    private = tmp_path / "boundary-private.pem"
    public = tmp_path / "boundary-public.pem"
    message = tmp_path / "boundary-approval.json"
    signature_file = tmp_path / "boundary-signature.bin"

    openssl("genpkey", "-algorithm", "ED25519", "-out", private)
    openssl("pkey", "-in", private, "-pubout", "-out", public)

    message.write_bytes(canonical_bytes(core_approval))

    openssl(
        "pkeyutl", "-sign", "-rawin",
        "-inkey", private,
        "-in", message,
        "-out", signature_file,
    )

    # Use an isolated verifier for the updated signed approval.
    verifier = HCPVerifier(
        public,
        "TRUSTED-TEST-KEY",
        tmp_path / "boundary-state.sqlite",
        clock=lambda: 1500,
    )

    core_adapter = HCPReviewAdapter(verifier)

    review_permission = core_adapter.evaluate(
        core_proposal,
        core_approval,
        signature_file.read_bytes(),
    )

    advisory_report = VHASCoreReviewer().review(core_proposal)

    authorization = VHASCoreAuthorization().evaluate(
        core_proposal.proposal_id
    )

    assert review_permission.review_allowed is True
    assert review_permission.approved is False
    assert review_permission.deployment_allowed is False

    assert advisory_report.risk_level == "high"
    assert advisory_report.approved is False
    assert advisory_report.deployment_allowed is False

    assert authorization.authorized is False
    assert authorization.deployment_allowed is False

    assert core_proposal.approved is False
    assert core_proposal.deployment_allowed is False
