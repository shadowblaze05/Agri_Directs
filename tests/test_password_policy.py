import pytest

from app.password_policy import password_policy_error


@pytest.mark.parametrize(
    "password",
    [
        "Farmer1",
        "Farmername",
    ],
)
def test_password_policy_rejects_weak_passwords(password):
    assert password_policy_error(password) is not None


@pytest.mark.parametrize(
    ("password", "error"),
    [
        ("password1", "Choose a password that is not common or easy to guess."),
        ("12345678", "Choose a password that is not common or easy to guess."),
        ("Qwerty123", "Choose a password that is not common or easy to guess."),
        (
            "Farmer1234",
            "Password must not contain common keyboard or sequential patterns.",
        ),
    ],
)
def test_password_policy_rejects_common_and_sequential_passwords(password, error):
    assert password_policy_error(password) == error


@pytest.mark.parametrize("password", ["Farmer12", "Juanito8", "River Harvest7Moon"])
def test_password_policy_accepts_names_with_eight_characters_and_a_number(password):
    assert password_policy_error(password) is None


def test_password_policy_requires_a_number():
    assert password_policy_error("FarmerName") == (
        "Password must include at least one number."
    )


def test_password_policy_enforces_maximum_length():
    password = "A1" + "x" * 127

    assert password_policy_error(password) == (
        "Password must be no more than 128 characters long."
    )
