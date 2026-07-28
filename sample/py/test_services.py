from services import get_user


def test_get_user():
    assert get_user(1) is not None
