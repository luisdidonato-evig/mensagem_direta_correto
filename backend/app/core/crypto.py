import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings, get_settings


@lru_cache
def _fernet(pii_hash_secret: str) -> Fernet:
    """Derive a Fernet key from the app secret.

    Not a real secret manager (see PLANEJAMENTO.md §11) — this only protects
    the WABA access token against a raw DB dump/backup leak, not against
    someone who also has this app's config. Good enough for mock/dev; a real
    deployment should swap this for KMS/Vault-backed encryption.
    """
    digest = hashlib.sha256(pii_hash_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(value: str, settings: Settings | None = None) -> str:
    fernet = _fernet((settings or get_settings()).pii_hash_secret)
    return fernet.encrypt(value.encode()).decode()


def decrypt_token(value: str, settings: Settings | None = None) -> str | None:
    fernet = _fernet((settings or get_settings()).pii_hash_secret)
    try:
        return fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        return None
