import hmac
import json
from urllib.parse import urlparse

import requests


def _validation_diagnostics(result):
    if not isinstance(result, dict):
        return ""

    details = {}
    error_code = result.get("error_code")
    if isinstance(error_code, str):
        details["error_code"] = error_code[:100]

    message = result.get("message")
    if isinstance(message, str):
        details["message"] = message[:300]

    errors = result.get("errors")
    invalid_fields = []
    if isinstance(errors, list):
        for error in errors[:20]:
            if not isinstance(error, dict):
                continue
            field = next(
                (
                    error[key]
                    for key in ("field", "path", "parameter", "param")
                    if isinstance(error.get(key), str)
                ),
                None,
            )
            if field:
                invalid_fields.append(field[:200])
    elif isinstance(errors, dict):
        invalid_fields = [str(field)[:200] for field in list(errors)[:20]]

    if invalid_fields:
        details["invalid_fields"] = invalid_fields

    if not details:
        return ""
    return json.dumps(details, ensure_ascii=True, separators=(",", ":"))


class XenditError(RuntimeError):
    """Raised when Xendit cannot create a usable payment session."""


def create_payment_session(secret_key, payload):
    if not secret_key:
        raise XenditError("Xendit is not configured. Set XENDIT_SECRET_KEY.")

    try:
        response = requests.post(
            "https://api.xendit.co/sessions",
            auth=(secret_key, ""),
            json=payload,
            timeout=20,
        )
    except requests.RequestException as error:
        raise XenditError("Could not reach Xendit to create a payment session.") from error

    try:
        result = response.json()
    except ValueError as error:
        raise XenditError("Xendit returned an unreadable payment-session response.") from error

    if response.status_code not in {200, 201}:
        error_code = result.get("error_code") if isinstance(result, dict) else None
        detail = f" ({error_code})" if error_code else ""
        diagnostics = _validation_diagnostics(result)
        if diagnostics:
            detail = f"{detail} diagnostics={diagnostics}"
        raise XenditError(
            f"Xendit rejected the payment-session request with HTTP "
            f"{response.status_code}{detail}."
        )

    if not isinstance(result, dict):
        raise XenditError("Xendit returned an invalid payment-session response.")

    session_id = result.get("payment_session_id")
    checkout_url = result.get("payment_link_url")
    if (
        not isinstance(session_id, str)
        or not session_id
        or not isinstance(checkout_url, str)
    ):
        raise XenditError("Xendit did not return a valid hosted checkout link.")

    parsed_url = urlparse(checkout_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise XenditError("Xendit did not return a valid hosted checkout link.")

    return result


def verify_callback_token(provided_token, expected_token):
    if not isinstance(provided_token, str) or not isinstance(expected_token, str):
        return False
    if not provided_token or not expected_token:
        return False
    return hmac.compare_digest(
        provided_token.encode("utf-8"),
        expected_token.encode("utf-8"),
    )
