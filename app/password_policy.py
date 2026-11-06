
import re

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

_COMMON_PASSWORDS = frozenset(
    {
        "123456",
        "1234567",
        "12345678",
        "123456789",
        "1234567890",
        "121212",
        "111111",
        "000000",
        "654321",
        "qwerty",
        "qwerty123",
        "password",
        "password1",
        "password123",
        "passw0rd",
        "admin",
        "admin123",
        "letmein",
        "welcome",
        "welcome1",
        "iloveyou",
        "abc123",
        "monkey",
        "dragon",
        "sunshine",
        "princess",
        "football",
        "baseball",
        "login",
        "changeme",
        "default",
        "secret",
        "trustno1",
    }
)
_COMMON_FRAGMENTS = (
    "password",
    "passw0rd",
    "qwerty",
    "letmein",
    "welcome",
    "iloveyou",
    "admin",
    "monkey",
    "dragon",
    "sunshine",
    "princess",
    "football",
    "baseball",
    "changeme",
    "default",
    "secret",
    "trustno1",
    "abc123",
)
_SEQUENTIAL_PATTERNS = (
    "0123456789",
    "9876543210",
    "abcdefghijklmnopqrstuvwxyz",
    "zyxwvutsrqponmlkjihgfedcba",
    "qwertyuiop",
    "poiuytrewq",
    "asdfghjkl",
    "lkjhgfdsa",
    "zxcvbnm",
    "mnbvcxz",
    "abcdefghijklmnopqrstuvwxyz",
)


def password_policy_error(password):
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be no more than {MAX_PASSWORD_LENGTH} characters long."
    if not any(character.isdigit() for character in password):
        return "Password must include at least one number."

    normalized = re.sub(r"[^a-z0-9]", "", password.lower())
    if normalized in _COMMON_PASSWORDS or any(
        fragment in normalized for fragment in _COMMON_FRAGMENTS
    ):
        return "Choose a password that is not common or easy to guess."
    if any(
        pattern[index : index + 4] in normalized
        for pattern in _SEQUENTIAL_PATTERNS
        for index in range(len(pattern) - 3)
    ):
        return "Password must not contain common keyboard or sequential patterns."
    if re.search(r"(.)\1{3,}", normalized):
        return "Password must not contain four or more repeated characters in a row."

    return None
