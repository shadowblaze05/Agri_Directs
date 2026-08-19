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

__all__ = ["reliability_status"]
