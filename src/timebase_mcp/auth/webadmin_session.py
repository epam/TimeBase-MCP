from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import dh, padding, rsa

from timebase_mcp.errors import TimeBaseOperationError


def _integer_bytes(value: int) -> bytes:
    # Java BigInteger.toByteArray includes a leading zero for positive high-bit values.
    return value.to_bytes((value.bit_length() + 8) // 8, "big")


def _decoded(data: dict[str, object], name: str, maximum: int) -> bytes:
    value = data.get(name)
    if not isinstance(value, str) or len(value) > maximum * 2:
        raise ValueError("Invalid session field")
    result = base64.b64decode(value, validate=True)
    if not result or len(result) > maximum:
        raise ValueError("Invalid session field")
    return result


@dataclass
class WebAdminSession:
    session_id: str = field(repr=False)
    secret: bytes = field(repr=False)
    idle_seconds: float
    expires_at: float
    nonce: int = 0

    @classmethod
    def acquire(
        cls,
        key: str,
        private_path: str,
        post: Callable[[str, dict[str, str]], dict[str, object]],
    ) -> WebAdminSession:
        try:
            with Path(private_path).expanduser().open("rb") as source:
                pem = source.read(65537)
            if len(pem) > 65536:
                raise ValueError("Private key exceeds limit")
            private = serialization.load_pem_private_key(pem, password=None)
            if not isinstance(private, rsa.RSAPrivateKey) or private.key_size < 2048:
                raise ValueError("RSA key of at least 2048 bits required")
        except (OSError, ValueError, TypeError, UnsupportedAlgorithm) as exc:
            raise TimeBaseOperationError(
                "WebAdmin session private key must be a readable, unencrypted RSA PEM file of at least 2048 bits."
            ) from exc

        try:
            attempt = post("/attempt", {"api_key_id": key})
            session_id = attempt.get("session_id")
            if (
                not isinstance(session_id, str)
                or not session_id
                or len(session_id) > 256
                or not session_id.isascii()
                or any(ord(c) < 33 or ord(c) > 126 for c in session_id)
            ):
                raise ValueError("Invalid session ID")
            modulus = int.from_bytes(
                _decoded(attempt, "dh_modulus", 1025), "big", signed=True
            )
            base = int.from_bytes(
                _decoded(attempt, "dh_base", 1025), "big", signed=True
            )
            if not 2048 <= modulus.bit_length() <= 8192 or not 1 < base < modulus - 1:
                raise ValueError("Invalid DH parameters")
            parameters = dh.DHParameterNumbers(modulus, base)
            ephemeral = parameters.parameters().generate_private_key()
            challenge = _decoded(attempt, "challenge", 16384)
            signature = private.sign(challenge, padding.PKCS1v15(), hashes.SHA256())
            response = post(
                "/confirm",
                {
                    "session_id": session_id,
                    "signature": base64.b64encode(signature).decode("ascii"),
                    "dh_key": base64.b64encode(
                        _integer_bytes(ephemeral.public_key().public_numbers().y)
                    ).decode("ascii"),
                },
            )
            remote = int.from_bytes(
                _decoded(response, "dh_key", 1025), "big", signed=True
            )
            if not 1 < remote < modulus - 1:
                raise ValueError("Invalid DH public key")
            shared = ephemeral.exchange(
                dh.DHPublicNumbers(remote, parameters).public_key()
            )
            ttl = response.get("keepalive_timeout")
            if type(ttl) is not int or not 1000 <= ttl <= 86400000:
                raise ValueError("Invalid session timeout")
            idle = ttl / 1000
            return cls(
                session_id,
                _integer_bytes(int.from_bytes(shared, "big")),
                idle,
                time.monotonic() + idle * 0.9,
            )
        except (ValueError, TypeError, OverflowError, UnsupportedAlgorithm) as exc:
            raise TimeBaseOperationError(
                "WebAdmin session handshake returned an invalid response."
            ) from exc

    def headers(self, payload: str) -> dict[str, str]:
        self.nonce += 1
        signed = (
            payload
            + f"X-Deltix-Nonce={self.nonce}&X-Deltix-Session-Id={self.session_id}"
        )
        signature = base64.b64encode(
            hmac.new(self.secret, signed.encode("utf-8"), hashlib.sha384).digest()
        ).decode("ascii")
        return {
            "X-Deltix-Session-Id": self.session_id,
            "X-Deltix-Nonce": str(self.nonce),
            "X-Deltix-Signature": signature,
        }
