"""
Database access.

Idempotency is enforced by the database itself:
    UNIQUE(client_id, app_id)  +  INSERT ... ON CONFLICT (client_id, app_id) DO UPDATE
Re-running the collector updates rows in place and can never create duplicates.
The same statement works on SQLite and PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, create_engine, delete, event, func, inspect, select
from sqlalchemy.orm import sessionmaker

from app_collector.models import AppUsageRecord, Base, CollectorRun, utcnow

# Columns refreshed on re-run. created_at is deliberately NOT here.
_UPDATE_ON_CONFLICT = ("app_name", "classification", "risk_score", "users", "raw_notes", "notes_truncated")


class Database:
    def __init__(self, url: str) -> None:
        kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        self.engine = create_engine(url, **kwargs)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", _sqlite_pragmas)
            from sqlalchemy.dialects.sqlite import insert
        else:
            from sqlalchemy.dialects.postgresql import insert
        self._insert = insert
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)
        # create_all never changes an existing table: stop early if one is outdated.
        inspector = inspect(self.engine)
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            missing = sorted(c.name for c in table.columns if c.name not in existing)
            if missing:
                raise RuntimeError(
                    f"Database is from an older version (table '{table.name}' is missing {missing}). "
                    f"Delete {self.engine.url.database} and run again."
                )

    # ------------------------------------------------------------------ write
    def upsert_records(self, rows: list[dict]) -> tuple[int, int]:
        """Insert-or-update one client's rows. Returns (inserted, updated)."""
        if not rows:
            return 0, 0
        client_ids = {r["client_id"] for r in rows}
        if len(client_ids) != 1:
            raise ValueError("upsert_records expects rows for exactly one client")
        client_id = client_ids.pop()
        rows = list({r["app_id"]: r for r in rows}.values())  # same app twice in a page: keep last
        now = utcnow()

        with self.Session.begin() as session:
            already_there = set(session.scalars(
                select(AppUsageRecord.app_id).where(
                    AppUsageRecord.client_id == client_id,
                    AppUsageRecord.app_id.in_([r["app_id"] for r in rows]),
                )
            ))
            stmt = self._insert(AppUsageRecord).values(
                [{**r, "created_at": now, "updated_at": now, "times_collected": 1} for r in rows]
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["client_id", "app_id"],
                set_={
                    **{col: stmt.excluded[col] for col in _UPDATE_ON_CONFLICT},
                    "updated_at": now,
                    "times_collected": AppUsageRecord.times_collected + 1,
                },
            )
            session.execute(stmt)

        updated = len(already_there)
        return len(rows) - updated, updated

    def delete_records(self, client_id: str | None = None) -> int:
        with self.Session.begin() as session:
            stmt = delete(AppUsageRecord)
            if client_id:
                stmt = stmt.where(AppUsageRecord.client_id == client_id)
            return session.execute(stmt).rowcount or 0

    def save_run(self, run: dict) -> None:
        with self.Session.begin() as session:
            session.merge(CollectorRun(
                id=run["id"], mode=run["mode"], status=run["status"],
                started_at=_dt(run["started_at"]), finished_at=_dt(run.get("finished_at")),
                summary=run.get("summary"), error=run.get("error"),
            ))

    def fail_interrupted_runs(self) -> int:
        """A run still 'running' at startup was cut off by a restart."""
        with self.Session.begin() as session:
            runs = session.scalars(select(CollectorRun).where(CollectorRun.status == "running")).all()
            for run in runs:
                run.status, run.error, run.finished_at = "failed", "server stopped during the run", utcnow()
            return len(runs)

    # ------------------------------------------------------------------- read
    def list_records(self, client_id: str | None = None, classification: str | None = None) -> list[dict]:
        stmt = select(AppUsageRecord).order_by(AppUsageRecord.client_id, AppUsageRecord.app_id)
        if client_id:
            stmt = stmt.where(AppUsageRecord.client_id == client_id)
        if classification:
            stmt = stmt.where(AppUsageRecord.classification == classification)
        with self.Session() as session:
            return [r.to_dict() for r in session.scalars(stmt)]

    def count_records(self, client_id: str | None = None) -> int:
        stmt = select(func.count()).select_from(AppUsageRecord)
        if client_id:
            stmt = stmt.where(AppUsageRecord.client_id == client_id)
        with self.Session() as session:
            return session.scalar(stmt) or 0

    def list_runs(self, limit: int = 20) -> list[dict]:
        stmt = select(CollectorRun).order_by(CollectorRun.started_at.desc()).limit(limit)
        with self.Session() as session:
            return [r.to_dict() for r in session.scalars(stmt)]

    def summary_by_client(self) -> list[dict]:
        """One GROUP BY query. Equivalent SQL:

        SELECT client_id, COUNT(*) AS apps,
               SUM(CASE WHEN classification = 'sanctioned' THEN 1 ELSE 0 END) AS sanctioned,
               SUM(CASE WHEN classification = 'unsanctioned' THEN 1 ELSE 0 END) AS unsanctioned,
               SUM(CASE WHEN risk_score IS NULL THEN 1 ELSE 0 END) AS missing_risk,
               SUM(CASE WHEN notes_truncated THEN 1 ELSE 0 END) AS truncated,
               ROUND(AVG(risk_score), 1) AS avg_risk,      -- AVG ignores NULLs
               SUM(users) AS users
        FROM app_usage_records GROUP BY client_id ORDER BY client_id;
        """
        r = AppUsageRecord
        stmt = (
            select(
                r.client_id,
                func.count().label("apps"),
                func.sum(case((r.classification == "sanctioned", 1), else_=0)).label("sanctioned"),
                func.sum(case((r.classification == "unsanctioned", 1), else_=0)).label("unsanctioned"),
                func.sum(case((r.risk_score.is_(None), 1), else_=0)).label("missing_risk"),
                func.sum(case((r.notes_truncated.is_(True), 1), else_=0)).label("truncated"),
                func.avg(r.risk_score).label("avg_risk"),
                func.coalesce(func.sum(r.users), 0).label("users"),
            )
            .group_by(r.client_id)
            .order_by(r.client_id)
        )
        with self.Session() as session:
            return [
                {
                    "client_id": row.client_id,
                    "apps": row.apps,
                    "sanctioned": row.sanctioned or 0,
                    "unsanctioned": row.unsanctioned or 0,
                    "missing_risk": row.missing_risk or 0,
                    "truncated": row.truncated or 0,
                    "avg_risk": round(float(row.avg_risk), 1) if row.avg_risk is not None else None,
                    "users": int(row.users or 0),
                }
                for row in session.execute(stmt)
            ]


def _sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")  # readers (e.g. DBeaver) don't block the collector
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.close()


def _dt(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value
