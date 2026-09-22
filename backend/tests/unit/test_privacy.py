from app.core.privacy import hash_phone, normalize_phone


def test_phone_normalization_and_hash_are_stable() -> None:
    assert normalize_phone("+55 (11) 99999-0001") == "5511999990001"
    assert hash_phone("+55 (11) 99999-0001") == hash_phone("5511999990001")
