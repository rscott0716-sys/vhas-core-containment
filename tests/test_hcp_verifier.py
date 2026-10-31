"""Tests for experimental HCP review-only verification."""

import hashlib
import subprocess
from dataclasses import replace

from vhas_hcp_verifier import HCPApproval, HCPVerifier, canonical_bytes


def openssl(*args):
    subprocess.run(
        ["openssl", *map(str, args)],
        capture_output=True,
        check=True,
    )


def test_hcp_review_only_authorization(tmp_path):
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    message = tmp_path / "approval.json"
    signature_file = tmp_path / "approval.sig"
    database = tmp_path / "replay.sqlite"

    openssl("genpkey", "-algorithm", "ED25519", "-out", private)
    openssl("pkey", "-in", private, "-pubout", "-out", public)

    proposal = b"Harmless VHAS review proposal"

    approval = HCPApproval(
        approval_id="HCP-TEST-228",
        proposal_id="VHAS-TEST-228",
        proposal_sha256=hashlib.sha256(proposal).hexdigest(),
        action_scope="review_only",
        issued_at=1000,
        expires_at=2000,
        authority_key_id="TRUSTED-TEST-KEY",
        nonce="UNIQUE-TEST-NONCE",
    )

    message.write_bytes(canonical_bytes(approval))

    openssl(
        "pkeyutl", "-sign", "-rawin",
        "-inkey", private,
        "-in", message,
        "-out", signature_file,
    )

    signature = signature_file.read_bytes()

    verifier = HCPVerifier(public, "TRUSTED-TEST-KEY", database, clock=lambda: 1500)

    def check(candidate, data=proposal):
        return verifier.verify(
            candidate,
            signature,
            "VHAS-TEST-228",
            data,
        )

    assert not check(approval, b"modified proposal").review_allowed
    assert not HCPVerifier(
        public, "TRUSTED-TEST-KEY", tmp_path / "expired.sqlite",
        clock=lambda: 2001,
    ).verify(
        approval, signature, "VHAS-TEST-228", proposal
    ).review_allowed
    assert not check(
        replace(approval, action_scope="deploy")
    ).review_allowed

    accepted = check(approval)
    assert accepted.review_allowed is True
    assert accepted.deployment_allowed is False

    assert not check(approval).review_allowed

    restarted = HCPVerifier(public, "TRUSTED-TEST-KEY", database, clock=lambda: 1500)
    assert not restarted.verify(
        approval, signature, "VHAS-TEST-228", proposal
    ).review_allowed

    verifier.revoke(approval.approval_id)
    assert not check(approval).review_allowed

    restarted_after_revocation = HCPVerifier(
        public, "TRUSTED-TEST-KEY", database
    )
    assert not restarted_after_revocation.verify(
        approval, signature, "VHAS-TEST-228", proposal
    ).review_allowed


def test_hcp_rejects_untrusted_signer(tmp_path):
    trusted_private = tmp_path / "trusted.pem"
    trusted_public = tmp_path / "trusted.pub"
    unknown_private = tmp_path / "unknown.pem"
    message = tmp_path / "approval.json"
    signature_file = tmp_path / "unknown.sig"

    openssl("genpkey", "-algorithm", "ED25519", "-out", trusted_private)
    openssl(
        "pkey", "-in", trusted_private,
        "-pubout", "-out", trusted_public,
    )
    openssl("genpkey", "-algorithm", "ED25519", "-out", unknown_private)

    proposal = b"Review-only test"
    approval = HCPApproval(
        "HCP-UNKNOWN", "VHAS-UNKNOWN",
        hashlib.sha256(proposal).hexdigest(),
        "review_only", 1000, 2000,
        "TRUSTED-TEST-KEY", "UNKNOWN-NONCE",
    )

    message.write_bytes(canonical_bytes(approval))
    openssl(
        "pkeyutl", "-sign", "-rawin",
        "-inkey", unknown_private,
        "-in", message,
        "-out", signature_file,
    )

    verifier = HCPVerifier(
        trusted_public,
        "TRUSTED-TEST-KEY",
        tmp_path / "state.sqlite",
        clock=lambda: 1500,
    )

    decision = verifier.verify(
        approval,
        signature_file.read_bytes(),
        "VHAS-UNKNOWN",
        proposal,
    )

    assert decision.review_allowed is False
    assert decision.deployment_allowed is False


def test_hcp_revocation_persists_before_first_use(tmp_path):
    import sqlite3

    public = tmp_path / "public.pem"
    database = tmp_path / "state.sqlite"

    # No signature verification occurs in this test.
    public.write_text("TEST PLACEHOLDER", encoding="utf-8")

    first = HCPVerifier(public, "TEST-KEY", database)
    first.revoke("HCP-PRE-REVOKED")

    restarted = HCPVerifier(public, "TEST-KEY", database)

    with sqlite3.connect(database) as connection:
        result = connection.execute(
            "SELECT 1 FROM revoked_approvals WHERE approval_id = ?",
            ("HCP-PRE-REVOKED",),
        ).fetchone()

    assert result is not None
    assert restarted.state_db == database


def test_hcp_rejects_invalid_revocation_id(tmp_path):
    import pytest

    public = tmp_path / "public.pem"
    public.write_text("TEST PLACEHOLDER", encoding="utf-8")

    verifier = HCPVerifier(
        public, "TEST-KEY", tmp_path / "state.sqlite"
    )

    for invalid in ("", "   ", None, 123):
        with pytest.raises(ValueError):
            verifier.revoke(invalid)


def test_hcp_clock_cannot_be_overridden_by_caller(tmp_path):
    import inspect

    parameters = inspect.signature(HCPVerifier.verify).parameters

    assert "now" not in parameters


def test_hcp_rejects_malformed_fields(tmp_path):
    from dataclasses import replace

    public = tmp_path / "public.pem"
    public.write_text("TEST PLACEHOLDER", encoding="utf-8")

    verifier = HCPVerifier(
        public, "TEST-KEY", tmp_path / "state.sqlite",
        clock=lambda: 1500,
    )

    proposal = b"Harmless input test"
    valid = HCPApproval(
        "HCP-MALFORMED",
        "VHAS-MALFORMED",
        hashlib.sha256(proposal).hexdigest(),
        "review_only",
        1000,
        2000,
        "TEST-KEY",
        "NONCE-MALFORMED",
    )

    malformed_cases = [
        replace(valid, proposal_sha256={"invalid": True}),
        replace(valid, action_scope=["review_only"]),
        replace(valid, issued_at="1000"),
        replace(valid, expires_at=True),
        replace(valid, authority_key_id={"unexpected": 1}),
        replace(valid, nonce={"nested": {"set"}}),
    ]

    for candidate in malformed_cases:
        decision = verifier.verify(
            candidate, b"x" * 64, valid.proposal_id, proposal
        )
        assert decision.review_allowed is False
        assert decision.deployment_allowed is False


def test_hcp_rejects_invalid_clock_values(tmp_path):
    public = tmp_path / "public.pem"
    public.write_text("TEST PLACEHOLDER", encoding="utf-8")

    proposal = b"Harmless clock test"
    approval = HCPApproval(
        "HCP-CLOCK", "VHAS-CLOCK",
        hashlib.sha256(proposal).hexdigest(),
        "review_only", 1000, 2000, "TEST-KEY", "CLOCK-NONCE",
    )

    for value in (float("nan"), float("inf"), True, "1500"):
        verifier = HCPVerifier(
            public, "TEST-KEY",
            tmp_path / f"clock-{str(value)}.sqlite",
            clock=lambda value=value: value,
        )

        decision = verifier.verify(
            approval, b"x" * 64, approval.proposal_id, proposal
        )

        assert decision.review_allowed is False
        assert decision.deployment_allowed is False
