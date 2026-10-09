import base64
import hashlib
import hmac
import json
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone


class TokenError(Exception):
    pass


def create_access_token(user) -> tuple[str, dict]:
    now = timezone.now()
    lifetime = getattr(settings, "JWT_ACCESS_TOKEN_LIFETIME", timedelta(hours=1))
    payload = {
        "sub": str(user.pk),
        "username": user.get_username(),
        "email": user.email,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "jti": secrets.token_hex(16),
        "typ": "access",
    }
    token = _encode(payload)
    return token, payload


def decode_access_token(token: str) -> dict:
    try:
        header_segment, payload_segment, signature_segment = token.split(".")
    except ValueError as exc:
        raise TokenError("Invalid token format.") from exc

    signing_input = f"{header_segment}.{payload_segment}".encode()
    expected_signature = _sign(signing_input)
    actual_signature = _b64decode(signature_segment)
    if not hmac.compare_digest(actual_signature, expected_signature):
        raise TokenError("Invalid token signature.")

    try:
        header = json.loads(_b64decode(header_segment))
        payload = json.loads(_b64decode(payload_segment))
    except (ValueError, TypeError) as exc:
        raise TokenError("Invalid token payload.") from exc

    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise TokenError("Unsupported token header.")
    if payload.get("typ") != "access":
        raise TokenError("Invalid token type.")

    expires_at = payload.get("exp")
    if not isinstance(expires_at, int):
        raise TokenError("Token expiry is missing.")
    if expires_at <= int(timezone.now().timestamp()):
        raise TokenError("Token has expired.")
    if not payload.get("sub") or not payload.get("jti"):
        raise TokenError("Token subject is missing.")

    return payload


def _encode(payload: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_segment = _b64encode(_json_bytes(header))
    payload_segment = _b64encode(_json_bytes(payload))
    signature_segment = _b64encode(_sign(f"{header_segment}.{payload_segment}".encode()))
    return f"{header_segment}.{payload_segment}.{signature_segment}"


def _json_bytes(value: dict) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _sign(value: bytes) -> bytes:
    secret = settings.SECRET_KEY.encode()
    return hmac.new(secret, value, hashlib.sha256).digest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise TokenError("Invalid token encoding.") from exc
