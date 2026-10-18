import pytest

from app.password_policy import password_policy_error


@pytest.mark.parametrize(
    "password",
    [
        "121212",
        "123456",
        "123123123123",
        "River!123123123Moon",
        "qwerty",
        "Qwerty!River82",
        "River!1234Moon",
        "Riverrrr!7Moon",
    ],
)
def test_password_policy_rejects_weak_passwords(password):
    assert password_policy_error(password) is not None


@pytest.mark.parametrize(
    ("password", "identifiers"),
    [
        ("River!Harvest7Moon", ()),
        ("River.Harvest7Moon", ()),
        ("Green!Market8Sun", ("farmer-one", "farmer@example.test")),
    ],
)
def test_password_policy_accepts_strong_passwords(password, identifiers):
    assert password_policy_error(password, identifiers) is None


def test_password_policy_rejects_password_containing_account_identifier():
    assert password_policy_error(
        "Farmer!Harvest7Moon",
        ("farmer-one", "farmer@example.test"),
    ) == "Password must not contain your username or email address."


def test_password_policy_enforces_maximum_length():
    password = "Aa1!" + "x" * 125

    assert password_policy_error(password) == (
        "Password must be no more than 128 characters long."
    )


def test_whitespace_does_not_satisfy_symbol_requirement():
    assert password_policy_error("River Harvest7Moon") == (
        "Password must include uppercase and lowercase letters, a number, and a symbol."
    )
