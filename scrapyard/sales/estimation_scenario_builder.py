"""
estimation_scenario_builder - Build and compare estimation scenarios (parameter sets) for cost modeling.

### PART-META-JSON
{
  "name": "estimation_scenario_builder",
  "layer": "sales",
  "purpose": "Build and compare estimation scenarios (parameter sets) for cost modeling.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "create_scenario(name, parameters); compare_scenarios([scenarios]).",
  "outputs": "EstimationScenario dataclasses, persisted EstimationScenarioModel/ScenarioMapping rows, ComparisonResult diffs.",
  "files_created": [],
  "security_notes": "Scenario parameters are stored as structured data and never evaluated as code. Comparison math is float-based - treat outputs as estimates, not ledger amounts.",
  "ai_usage": "Import what you need from `scrapyard.sales.estimation_scenario_builder`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.sales.estimation_scenario_builder import create_scenario",
  "import_path": "scrapyard.sales.estimation_scenario_builder"
}
### END-PART-META
"""

from sqlalchemy import (
    create_engine,
    select,
    String,
    Integer,
    DateTime,
    JSON,
    func,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import sessionmaker, Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import os
import logging
import tempfile

logger = logging.getLogger(__name__)

Session = sessionmaker()
Base = IntPKModel


@dataclass
class EstimationScenario:
    name: str
    parameters: Dict[str, Any]
    id: Optional[int] = None


@dataclass
class ComparisonResult:
    scenario_a: EstimationScenario
    scenario_b: EstimationScenario
    metrics: Dict[str, float]


class EstimationScenarioModel(Base):
    __tablename__ = "estimation_scenario"
    name: Mapped[str] = mapped_column(String, nullable=False)
    parameters_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("idx_estimation_scenario_name", "name"),)


class ScenarioMapping(Base):
    __tablename__ = "scenario_estimate_mapping"
    estimate_id: Mapped[int] = mapped_column(Integer, nullable=False)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("estimation_scenario.id"), nullable=False
    )

    __table_args__ = (
        Index("idx_scenario_estimate_mapping_estimate", "estimate_id"),
        UniqueConstraint(
            "estimate_id", "scenario_id", name="uq_est_id_scen_id"
        ),
    )


def _validate_scenario_inputs(name: Any, parameters: Any) -> None:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be a dictionary")


def create_scenario(name: str, parameters: Dict[str, Any]) -> EstimationScenario:
    _validate_scenario_inputs(name, parameters)

    with Session() as session:
        record = EstimationScenarioModel(name=name, parameters_json=parameters)
        session.add(record)
        session.commit()
        scenario_id = record.id

    logger.info("Created scenario %r with id %s", name, scenario_id)
    return EstimationScenario(name=name, parameters=parameters, id=scenario_id)


def compare_scenarios(scenarios: List[EstimationScenario]) -> ComparisonResult:
    if len(scenarios) != 2:
        raise ValueError("Exactly two scenarios must be provided for comparison")

    scenario_a, scenario_b = scenarios
    if not isinstance(scenario_a, EstimationScenario) or not isinstance(
        scenario_b, EstimationScenario
    ):
        raise TypeError("All scenarios must be EstimationScenario instances")

    def numeric_sum(params: Dict[str, Any]) -> float:
        return sum(
            float(value)
            for value in params.values()
            if isinstance(value, (int, float))
        )

    sum_a = numeric_sum(scenario_a.parameters)
    sum_b = numeric_sum(scenario_b.parameters)

    difference = sum_a - sum_b
    metrics: Dict[str, float] = {
        "difference": float(difference),
        "absolute_difference": float(abs(difference)),
    }
    if sum_b != 0:
        metrics["relative_difference"] = float(difference / sum_b)

    result = ComparisonResult(
        scenario_a=scenario_a, scenario_b=scenario_b, metrics=metrics
    )
    logger.info("Compared scenarios: %s", result)
    return result


def apply_scenario_to_estimate(
    scenario: EstimationScenario, estimate_id: int
) -> None:
    if not isinstance(scenario, EstimationScenario):
        raise TypeError("scenario must be an EstimationScenario instance")
    if scenario.id is None:
        raise ValueError("Scenario must be persisted before applying to an estimate")
    if not isinstance(estimate_id, int):
        raise TypeError("estimate_id must be an int")

    with Session() as session:
        mapping = ScenarioMapping(
            estimate_id=estimate_id, scenario_id=scenario.id
        )
        session.add(mapping)
        session.commit()

    logger.info(
        "Applied scenario %s to estimate %s", scenario.id, estimate_id
    )


def _selftest() -> None:
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    engine = None

    try:
        db_path = os.path.join(temp_dir.name, "test.db")
        db_url = "sqlite:///" + db_path.replace(os.sep, "/")
        engine = create_engine(db_url, echo=False)

        Session.configure(bind=engine)

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE estimates (id INTEGER PRIMARY KEY)"
            )
            connection.exec_driver_sql(
                "INSERT INTO estimates (id) VALUES (1), (2)"
            )

        Base.metadata.create_all(engine)

        scenario1 = create_scenario(
            name="Scenario 1", parameters={"param1": 50, "param2": 75}
        )
        assert scenario1.id is not None
        logger.info("Created Scenario: %s", scenario1)

        scenario2 = create_scenario(
            name="Scenario 2", parameters={"param1": 60, "param2": 85}
        )
        assert scenario2.id is not None
        logger.info("Created Scenario: %s", scenario2)

        apply_scenario_to_estimate(scenario=scenario1, estimate_id=1)
        apply_scenario_to_estimate(scenario=scenario2, estimate_id=2)

        with Session() as session:
            rows = session.execute(
                select(
                    ScenarioMapping.estimate_id, ScenarioMapping.scenario_id
                ).order_by(ScenarioMapping.estimate_id)
            ).all()
            mapping_pairs = [(row.estimate_id, row.scenario_id) for row in rows]

        assert mapping_pairs == [
            (1, scenario1.id),
            (2, scenario2.id),
        ], f"Unexpected mapping pairs: {mapping_pairs}"

        comparison_result = compare_scenarios([scenario1, scenario2])
        logger.info("Comparison Result: %s", comparison_result)
        assert comparison_result.scenario_a == scenario1
        assert comparison_result.scenario_b == scenario2
        assert comparison_result.metrics["difference"] == -20.0

        try:
            compare_scenarios([scenario1])
            raise AssertionError("Expected ValueError for single scenario")
        except ValueError:
            pass

        try:
            apply_scenario_to_estimate(
                EstimationScenario(name="Unsaved", parameters={}), 1
            )
            raise AssertionError("Expected ValueError for unsaved scenario")
        except ValueError:
            pass

        try:
            create_scenario(name="", parameters={"param1": 1})
            raise AssertionError("Expected ValueError for empty name")
        except ValueError:
            pass

        try:
            create_scenario(name="Bad", parameters="not-a-dict")  # type: ignore[arg-type]
            raise AssertionError("Expected ValueError for non-dict parameters")
        except ValueError:
            pass

        logger.info("estimation_scenario_builder _selftest passed")
    finally:
        Session.configure(bind=None)
        if engine is not None:
            engine.dispose()
        temp_dir.cleanup()


if __name__ == "__main__":
    _selftest()
