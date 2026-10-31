"""Experimental, review-only Human Cooperation Protocol verifier."""

import hashlib
import json
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class HCPApproval:
    approval_id: str
    proposal_id: str
    proposal_sha256: str
    action_scope: str
    issued_at: int
    expires_at: int
    authority_key_id: str
    nonce: str


@dataclass(frozen=True)
class HCPDecision:
    review_allowed: bool = False
    deployment_allowed: bool = False
    reason: str = "Authorization denied."


def canonical_bytes(approval):
    return json.dumps(
        asdict(approval),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


class HCPVerifier:
    def __init__(self, trusted_public_key, authority_key_id, state_db, *, clock=None):
        self.trusted_public_key = Path(trusted_public_key)
        self.authority_key_id = authority_key_id
        self.state_db = Path(state_db)
        self._clock = time.time if clock is None else clock
        if not callable(self._clock):
            raise ValueError('Clock must be callable.')
        if not self.trusted_public_key.is_file():
            raise ValueError("Trusted public key is unavailable.")

        self.state_db.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.state_db) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS used_approvals "
                "(approval_id TEXT PRIMARY KEY, nonce TEXT UNIQUE NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS revoked_approvals "
                "(approval_id TEXT PRIMARY KEY)"
            )

    def revoke(self, approval_id):
        if not isinstance(approval_id, str) or not approval_id.strip():
            raise ValueError("A valid approval ID is required.")

        with sqlite3.connect(self.state_db, timeout=5) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO revoked_approvals (approval_id) "
                "VALUES (?)",
                (approval_id,),
            )

    def verify(self, approval, signature, proposal_id, proposal_bytes):
        denied = HCPDecision()

        if not isinstance(approval, HCPApproval):
            return denied

        fields = (
            approval.approval_id,
            approval.proposal_id,
            approval.proposal_sha256,
            approval.action_scope,
            approval.authority_key_id,
            approval.nonce,
        )

        if any(
            not isinstance(value, str) or not value.strip()
            for value in fields
        ):
            return denied

        if (
            len(approval.proposal_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in approval.proposal_sha256
            )
        ):
            return denied

        if approval.authority_key_id != self.authority_key_id:
            return denied

        if approval.action_scope != "review_only":
            return denied

        if (
            not isinstance(proposal_id, str)
            or not proposal_id.strip()
            or approval.proposal_id != proposal_id
        ):
            return denied

        if not isinstance(proposal_bytes, bytes):
            return denied

        if approval.proposal_sha256 != hashlib.sha256(
            proposal_bytes
        ).hexdigest():
            return denied

        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (approval.issued_at, approval.expires_at)
        ):
            return denied

        try:
            now = self._clock()
        except Exception:
            return denied

        if (
            isinstance(now, bool)
            or not isinstance(now, (int, float))
            or not __import__("math").isfinite(now)
        ):
            return denied

        if not approval.issued_at <= now < approval.expires_at:
            return denied

        if not isinstance(signature, bytes) or len(signature) != 64:
            return denied

        try:
            with tempfile.TemporaryDirectory(prefix="hcp-verify-") as temp:
                message = Path(temp) / "approval.json"
                signature_file = Path(temp) / "approval.sig"

                message.write_bytes(canonical_bytes(approval))
                signature_file.write_bytes(signature)

                result = subprocess.run(
                    [
                        "openssl", "pkeyutl", "-verify", "-rawin",
                        "-pubin", "-inkey", str(
                            self.trusted_public_key.resolve()
                        ),
                        "-in", str(message),
                        "-sigfile", str(signature_file),
                    ],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )

                if result.returncode != 0:
                    return denied

            with sqlite3.connect(self.state_db, timeout=5) as connection:
                try:
                    # Keep revocation check and replay insertion atomic.
                    connection.execute("BEGIN IMMEDIATE")

                    revoked = connection.execute(
                        "SELECT 1 FROM revoked_approvals "
                        "WHERE approval_id = ?",
                        (approval.approval_id,),
                    ).fetchone()

                    if revoked is not None:
                        return denied

                    connection.execute(
                        "INSERT INTO used_approvals (approval_id, nonce) "
                        "VALUES (?, ?)",
                        (approval.approval_id, approval.nonce),
                    )
                    connection.commit()

                except sqlite3.IntegrityError:
                    return denied

        except (OSError, subprocess.SubprocessError, sqlite3.Error):
            return denied

        return HCPDecision(
            review_allowed=True,
            deployment_allowed=False,
            reason="Signed approval accepted for review only.",
        )
