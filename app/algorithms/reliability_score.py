"""Reliability scoring algorithm helpers."""

def reliability_status(score):
    """Return the display label for a reliability score."""
    if score is None:
        return "Not Yet Rated"
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Fair"
    return "Needs Improvement"


def seller_reliability_status(score):
    """Return the seller-rating label for a 1-5 average buyer rating."""
    if score is None:
        return "Not Yet Rated"
    if score >= 4:
        return "High Reliability"
    if score >= 3:
        return "Medium Reliability"
    return "Low Reliability"


__all__ = ["reliability_status", "seller_reliability_status"]
