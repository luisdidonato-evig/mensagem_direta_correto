import hashlib
import hmac

from app.api.v1.webhooks import verify_signature


def test_accepts_valid_meta_signature() -> None:
    body = b'{"object":"whatsapp_business_account"}'
    secret = "test-secret"
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert verify_signature(body, signature, secret)


def test_rejects_missing_or_invalid_signature() -> None:
    assert not verify_signature(b"{}", None, "secret")
    assert not verify_signature(b"{}", "sha256=invalid", "secret")
