"""
Database tables (SQLAlchemy 2.0).

app_usage_records : one row per (client_id, app_id)  <- the idempotency key
collector_runs    : one row per collector run
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, TypeDecorator, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class UTCDateTime(TypeDecorator):
    """SQLite stores no timezone; always hand back UTC-aware datetimes."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return ensure_utc(value) if value is not None else None

    def process_result_value(self, value, dialect):
        return ensure_utc(value) if value is not None else None


class Base(DeclarativeBase):
    pass


class AppUsageRecord(Base):
    __tablename__ = "app_usage_records"
    __table_args__ = (UniqueConstraint("client_id", "app_id", name="uq_client_app"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(50), index=True)
    app_id: Mapped[str] = mapped_column(String(100))
    app_name: Mapped[str] = mapped_column(String(255))
    classification: Mapped[str] = mapped_column(String(20))  # sanctioned | unsanctioned
    risk_score: Mapped[int | None] = mapped_column(Integer)  # NULL = API sent no score
    users: Mapped[int | None] = mapped_column(Integer)
    raw_notes: Mapped[str | None] = mapped_column(Text)  # cleaned, max 500 chars
    notes_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    times_collected: Mapped[int] = mapped_column(Integer, default=1)  # goes up on every re-run
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "client_id": self.client_id,
            "app_id": self.app_id,
            "app_name": self.app_name,
            "classification": self.classification,
            "risk_score": self.risk_score,
            "users": self.users,
            "raw_notes": self.raw_notes,
            "notes_truncated": self.notes_truncated,
            "times_collected": self.times_collected,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CollectorRun(Base):
    __tablename__ = "collector_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20))  # running | completed | partial | failed
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    summary: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "mode": self.mode,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "summary": self.summary,
            "error": self.error,
        }
