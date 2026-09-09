"""Market-analysis service compatibility boundary."""

from .market_intelligence import analyze_market_intelligence


def build_market_analysis(records):
    """Backwards-compatible alias for the service-driven analysis layer."""
    return analyze_market_intelligence(records)


__all__ = ["build_market_analysis", "analyze_market_intelligence"]
