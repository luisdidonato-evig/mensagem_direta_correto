import hashlib
import hmac

from app.core.config import get_settings


def normalize_phone(phone: str) -> str:
    return "".join(character for character in phone if character.isdigit())


def hash_phone(phone: str) -> str:
    settings = get_settings()
    return hmac.new(
        settings.pii_hash_secret.encode(),
        normalize_phone(phone).encode(),
        hashlib.sha256,
    ).hexdigest()
