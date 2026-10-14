"""Retention policy for registrations waiting on email verification."""


def purge_expired_pending_accounts():
    """Pending registrations are retained; only their email codes expire.

    Kept as a compatibility no-op for older callers.
    """
    return 0
