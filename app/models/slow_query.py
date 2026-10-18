from sqlalchemy import DateTime, Float, Integer, String, Text

from .base import Column, Model


class SlowQueryStat(Model):
    __tablename__ = "slow_query_stats"

    fingerprint = Column(String(64), primary_key=True)
    statement = Column(Text, nullable=False)
    call_count = Column(Integer, nullable=False, default=0)
    total_time_ms = Column(Float, nullable=False, default=0)
    max_time_ms = Column(Float, nullable=False, default=0)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
