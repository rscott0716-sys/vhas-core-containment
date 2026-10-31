"""Isolated failure-boundary regressions for review-only HCP verification."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import sqlite3
import subprocess
from threading import Barrier
from unittest.mock import patch

import pytest

from vhas_hcp_verifier import HCPApproval, HCPVerifier, canonical_bytes


def _openssl(*args):
    subprocess.run(["openssl", *map(str, args)], capture_output=True, check=True, timeout=15)


def _keys(tmp_path):
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    _openssl("genpkey", "-algorithm", "ED25519", "-out", private)
    _openssl("pkey", "-in", private, "-pubout", "-out", public)
    return private, public


def _signed(tmp_path, private, name="one", nonce=None):
    proposal = b"Harmless review-only boundary test"
    approval = HCPApproval(
        approval_id=f"HCP-{name}", proposal_id=f"VHAS-{name}",
        proposal_sha256=hashlib.sha256(proposal).hexdigest(),
        action_scope="review_only", issued_at=1000, expires_at=2000,
        authority_key_id="TEST-KEY", nonce=nonce or f"NONCE-{name}",
    )
    message = tmp_path / f"{name}.json"
    signature_file = tmp_path / f"{name}.sig"
    message.write_bytes(canonical_bytes(approval))
    _openssl("pkeyutl", "-sign", "-rawin", "-inkey", private,
             "-in", message, "-out", signature_file)
    return approval, signature_file.read_bytes(), proposal


def _verify(verifier, signed):
    approval, signature, proposal = signed
    return verifier.verify(approval, signature, approval.proposal_id, proposal)


def _verifier(tmp_path, public):
    return HCPVerifier(public, "TEST-KEY", tmp_path / "state.sqlite", clock=lambda: 1500)


def _parallel(verifier, approvals):
    gate = Barrier(len(approvals) + 1, timeout=10)

    def worker(signed):
        gate.wait(timeout=10)
        return _verify(verifier, signed)

    with ThreadPoolExecutor(max_workers=len(approvals)) as executor:
        futures = [executor.submit(worker, signed) for signed in approvals]
        gate.wait(timeout=10)
        return [future.result(timeout=30) for future in futures]


def _assert_review_only(decisions, expected_successes):
    assert sum(decision.review_allowed is True for decision in decisions) == expected_successes
    assert all(decision.deployment_allowed is False for decision in decisions)


def test_n1_concurrent_replay_same_approval(tmp_path):
    private, public = _keys(tmp_path)
    verifier = _verifier(tmp_path, public)
    signed = _signed(tmp_path, private)
    decisions = _parallel(verifier, [signed, signed])
    _assert_review_only(decisions, 1)
    assert _verify(verifier, signed).review_allowed is False


def test_n2_concurrent_approvals_with_shared_nonce(tmp_path):
    private, public = _keys(tmp_path)
    verifier = _verifier(tmp_path, public)
    first = _signed(tmp_path, private, "first", nonce="SHARED-NONCE")
    second = _signed(tmp_path, private, "second", nonce="SHARED-NONCE")
    decisions = _parallel(verifier, [first, second])
    _assert_review_only(decisions, 1)
    with sqlite3.connect(verifier.state_db) as connection:
        rows = connection.execute(
            "SELECT COUNT(*) FROM used_approvals WHERE nonce = ?", ("SHARED-NONCE",)
        ).fetchone()[0]
    assert rows == 1


def test_n3_sqlite_verification_failure_denies_review(tmp_path):
    private, public = _keys(tmp_path)
    verifier = _verifier(tmp_path, public)
    signed = _signed(tmp_path, private)
    original_connect = sqlite3.connect

    def fail_connection(*args, **kwargs):
        raise sqlite3.OperationalError("simulated database outage")

    with patch("vhas_hcp_verifier.sqlite3.connect", side_effect=fail_connection):
        decision = _verify(verifier, signed)
    _assert_review_only([decision], 0)
    with original_connect(verifier.state_db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM used_approvals").fetchone()[0] == 0


def test_n4_sqlite_lock_contention_denies_review(tmp_path):
    private, public = _keys(tmp_path)
    verifier = _verifier(tmp_path, public)
    signed = _signed(tmp_path, private)
    lock = sqlite3.connect(verifier.state_db, timeout=1)
    try:
        lock.execute("BEGIN IMMEDIATE")
        # The lock stays held until the verification call has finished.
        decision = _verify(verifier, signed)
        _assert_review_only([decision], 0)
    finally:
        lock.rollback()
        lock.close()
    with sqlite3.connect(verifier.state_db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM used_approvals").fetchone()[0] == 0


def test_n5_openssl_verification_timeout_denies_review(tmp_path):
    private, public = _keys(tmp_path)
    verifier = _verifier(tmp_path, public)
    signed = _signed(tmp_path, private)
    with patch("vhas_hcp_verifier.subprocess.run", side_effect=subprocess.TimeoutExpired("openssl", 15)):
        decision = _verify(verifier, signed)
    _assert_review_only([decision], 0)
    with sqlite3.connect(verifier.state_db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM used_approvals").fetchone()[0] == 0


def test_n6_openssl_key_initialization_timeout_rejected(tmp_path):
    _, public = _keys(tmp_path)
    database = tmp_path / "uninitialized.sqlite"
    with patch("vhas_hcp_verifier.subprocess.run", side_effect=subprocess.TimeoutExpired("openssl", 15)):
        with pytest.raises(ValueError, match="Trusted public key validation failed"):
            HCPVerifier(public, "TEST-KEY", database, clock=lambda: 1500)
    assert not database.exists()
