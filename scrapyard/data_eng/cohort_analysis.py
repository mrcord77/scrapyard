"""
cohort_analysis — ** The `scrapyard.data_eng.cohort_analysis` module provides tools to analyze user behavior by cohort, enabling insights into retention, engagement, and trend patterns over time. It builds on a datafra

### PART-META-JSON
{
  "name": "cohort_analysis",
  "layer": "data_eng",
  "purpose": "Provides tools to analyze user behavior by cohort, enabling insights into retention, engagement, and trend patterns over time. It builds on a datafra.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: create_cohort_table(session, activity_df); analyze_cohort_retention(session, cohort_id, window_days); Cohort(...); UserActivity(...).",
  "outputs": "Returns: create_cohort_table -> None; analyze_cohort_retention -> pd.DataFrame.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.data_eng.cohort_analysis`.",
  "example": "from scrapyard.data_eng.cohort_analysis import *",
  "import_path": "scrapyard.data_eng.cohort_analysis"
}
### END-PART-META
"""
import logging
import os
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, create_engine, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class Cohort(IntPKModel):
    __tablename__ = "cohorts"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("idx_cohorts_start_date", "start_date"),)


class UserActivity(IntPKModel):
    __tablename__ = "user_activity"

    cohort_id: Mapped[int] = mapped_column(
        ForeignKey("cohorts.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    activity_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    activity_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)


def create_cohort_table(session: Session, activity_df: pd.DataFrame) -> None:
    """
    Creates a cohort entry and populates user_activity from the DataFrame.
    
    Expects DataFrame with at least columns: 'user_id', 'activity_date'.
    Optional column: 'activity_type'.
    """
    if activity_df.empty:
        logger.warning("Empty DataFrame provided to create_cohort_table, skipping")
        return

    required_cols = {"user_id", "activity_date"}
    if not required_cols.issubset(activity_df.columns):
        missing = required_cols - set(activity_df.columns)
        raise ValueError(f"Missing required columns: {missing}")

    df = activity_df.copy()
    df["activity_date"] = pd.to_datetime(df["activity_date"])

    earliest_date = df["activity_date"].min()
    cohort_name = f"cohort_{earliest_date.strftime('%Y%m%d_%H%M%S')}"

    cohort = Cohort(
        name=cohort_name,
        start_date=earliest_date,
        description=f"Cohort starting {earliest_date.isoformat()}",
    )
    session.add(cohort)
    session.flush()  # Get cohort.id

    activities = []
    for _, row in df.iterrows():
        activity = UserActivity(
            cohort_id=cohort.id,
            user_id=str(row["user_id"]),
            activity_date=row["activity_date"],
            activity_type=(
                str(row["activity_type"])
                if "activity_type" in df.columns and pd.notna(row.get("activity_type"))
                else None
            ),
        )
        activities.append(activity)

    session.add_all(activities)
    session.commit()
    logger.info(f"Created cohort {cohort.id} with {len(activities)} activities")


def analyze_cohort_retention(
    session: Session, cohort_id: int, window_days: int
) -> pd.DataFrame:
    """
    Analyze retention metrics for a specific cohort over a time window.
    
    Returns DataFrame with columns:
    - period: Days since first activity (0 to window_days)
    - user_count: Number of unique active users on that day
    - retention_rate: Percentage of total cohort users retained (0-100)
    """
    stmt = select(UserActivity).where(UserActivity.cohort_id == cohort_id)
    activities = session.execute(stmt).scalars().all()

    if not activities:
        logger.warning(f"No activities found for cohort {cohort_id}")
        return pd.DataFrame(columns=["period", "user_count", "retention_rate"])

    df = pd.DataFrame(
        [
            {"user_id": act.user_id, "activity_date": act.activity_date}
            for act in activities
        ]
    )

    user_first = df.groupby("user_id")["activity_date"].min().reset_index()
    user_first.columns = ["user_id", "first_date"]

    df = df.merge(user_first, on="user_id")
    df["day_diff"] = (df["activity_date"] - df["first_date"]).dt.days

    df = df[df["day_diff"] <= window_days]

    retention = df.groupby("day_diff")["user_id"].nunique().reset_index()
    retention.columns = ["period", "user_count"]

    total_users = user_first["user_id"].nunique()
    retention["retention_rate"] = (retention["user_count"] / total_users * 100).round(2)

    all_periods = pd.DataFrame({"period": range(window_days + 1)})
    retention = all_periods.merge(retention, on="period", how="left")
    retention["user_count"] = retention["user_count"].fillna(0).astype(int)
    retention["retention_rate"] = retention["retention_rate"].fillna(0.0)

    return retention


def _selftest() -> None:
    """Self-contained test for cohort analysis functionality."""
    logger.info("Starting cohort_analysis selftest")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_cohort.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)

        Cohort.metadata.create_all(engine)

        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        try:
            base_date = datetime(2024, 1, 15, tzinfo=timezone.utc)
            test_data = pd.DataFrame(
                {
                    "user_id": [
                        "user_a",  # Day 0
                        "user_a",  # Day 1
                        "user_a",  # Day 3
                        "user_b",  # Day 0
                        "user_b",  # Day 2
                        "user_c",  # Day 0
                    ],
                    "activity_date": [
                        base_date,
                        base_date + timedelta(days=1),
                        base_date + timedelta(days=3),
                        base_date,
                        base_date + timedelta(days=2),
                        base_date,
                    ],
                    "activity_type": [
                        "signup",
                        "login",
                        "purchase",
                        "signup",
                        "login",
                        "signup",
                    ],
                }
            )

            create_cohort_table(session, test_data)

            cohort = session.execute(select(Cohort)).scalar_one()
            assert cohort is not None, "Cohort was not created"
            cohort_id = cohort.id

            activity_count = session.execute(
                select(func.count()).select_from(UserActivity)
            ).scalar()
            assert activity_count == 6, f"Expected 6 activities, got {activity_count}"

            result_df = analyze_cohort_retention(session, cohort_id, window_days=5)

            assert isinstance(result_df, pd.DataFrame), "Result must be a DataFrame"
            assert not result_df.empty, "Result DataFrame should not be empty"
            assert list(result_df.columns) == [
                "period",
                "user_count",
                "retention_rate",
            ], f"Unexpected columns: {list(result_df.columns)}"

            day_0 = result_df[result_df["period"] == 0].iloc[0]
            assert day_0["user_count"] == 3, f"Day 0 should have 3 users, got {day_0['user_count']}"
            assert day_0["retention_rate"] == 100.0, "Day 0 retention should be 100%"

            day_1 = result_df[result_df["period"] == 1].iloc[0]
            assert day_1["user_count"] == 1, f"Day 1 should have 1 user, got {day_1['user_count']}"

            day_2 = result_df[result_df["period"] == 2].iloc[0]
            assert day_2["user_count"] == 1, f"Day 2 should have 1 user, got {day_2['user_count']}"

            day_3 = result_df[result_df["period"] == 3].iloc[0]
            assert day_3["user_count"] == 1, f"Day 3 should have 1 user, got {day_3['user_count']}"

            day_4 = result_df[result_df["period"] == 4].iloc[0]
            assert day_4["user_count"] == 0, f"Day 4 should have 0 users, got {day_4['user_count']}"

            logger.info("cohort_analysis selftest completed successfully")

        except Exception as e:
            logger.error(f"Selftest failed: {e}")
            raise
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
