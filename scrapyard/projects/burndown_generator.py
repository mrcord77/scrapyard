"""
burndown_generator — ** Generates burndown charts for project management by analyzing task progress over time, enabling teams to visualize work completion and forecast project timelines. This module provides reusable, dat

### PART-META-JSON
{
  "name": "burndown_generator",
  "layer": "projects",
  "purpose": "Generates burndown charts for project management by analyzing task progress over time, enabling teams to visualize work completion and forecast project timelines. This module provides reusable, dat.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: generate_burndown_data(project_id, start_date, end_date); get_burndown_chart(project_id, start_date, end_date); BurndownData(...).",
  "outputs": "Returns: generate_burndown_data -> List[Dict[str, Any]]; get_burndown_chart -> PlotlyFigure.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.projects.burndown_generator`.",
  "example": "from scrapyard.projects.burndown_generator import *",
  "import_path": "scrapyard.projects.burndown_generator"
}
### END-PART-META
"""
from sqlalchemy import Float, DateTime, select, ForeignKey, Index, UniqueConstraint, String, create_engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from scrapyard.database.base_model import IntPKModel, Base
from datetime import datetime, date, timezone
from typing import List, Dict, Any
import os
import tempfile

# Module-level sessionmaker (unbound until configured)
Session = sessionmaker()

# Optional plotly import for type hints and runtime
try:
    from plotly.graph_objs import Figure as PlotlyFigure
    _PLOTLY_AVAILABLE = True
except ImportError:
    PlotlyFigure = Any
    _PLOTLY_AVAILABLE = False


class BurndownData(IntPKModel):
    __tablename__ = 'burndown_data'
    
    project_id: Mapped[int] = mapped_column(ForeignKey('burndown_generator_projects.id'), index=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ideal_work: Mapped[float] = mapped_column(Float, nullable=False)
    actual_work: Mapped[float] = mapped_column(Float, nullable=False)
    remaining_work: Mapped[float] = mapped_column(Float, nullable=False)
    
    __table_args__ = (
        Index('idx_project_date', 'project_id', 'date'),
        UniqueConstraint('project_id', 'date')
    )


def generate_burndown_data(project_id: int, start_date: date, end_date: date) -> List[Dict[str, Any]]:
    start_dt = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc)
    
    with Session() as session:
        query = select(BurndownData).where(
            BurndownData.project_id == project_id,
            BurndownData.date >= start_dt,
            BurndownData.date <= end_dt
        ).order_by(BurndownData.date)
        
        results = session.execute(query).scalars().all()
        
        return [
            {
                'date': row.date,
                'ideal_work': row.ideal_work,
                'actual_work': row.actual_work,
                'remaining_work': row.remaining_work
            }
            for row in results
        ]


def get_burndown_chart(project_id: int, start_date: date, end_date: date) -> PlotlyFigure:
    data = generate_burndown_data(project_id, start_date, end_date)
    
    if _PLOTLY_AVAILABLE:
        from plotly.graph_objs import Scatter, Figure
        
        fig = Figure()
        if data:
            dates = [d['date'] for d in data]
            ideal_work = [item['ideal_work'] for item in data]
            actual_work = [item['actual_work'] for item in data]
            remaining_work = [item['remaining_work'] for item in data]
            
            fig.add_trace(Scatter(x=dates, y=ideal_work, mode='lines', name='Ideal'))
            fig.add_trace(Scatter(x=dates, y=actual_work, mode='lines', name='Actual'))
            fig.add_trace(Scatter(x=dates, y=remaining_work, mode='lines', name='Remaining'))
        
        return fig
    else:
        # Mock implementation for environments without plotly
        class MockTrace:
            pass
        
        class MockFigure:
            def __init__(self):
                self.data: List[Any] = []
            
            def add_trace(self, trace: Any) -> None:
                self.data.append(trace)
        
        fig = MockFigure()
        if data:
            fig.add_trace(MockTrace())
            fig.add_trace(MockTrace())
            fig.add_trace(MockTrace())
        
        return fig


def _selftest():
    # Define minimal Project model to satisfy foreign key constraint
    class Project(IntPKModel):
        __tablename__ = 'burndown_generator_projects'
        name: Mapped[str] = mapped_column(String(100), default="Test Project")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = os.path.join(tmp_dir, 'test.db')
        engine = create_engine(f'sqlite:///{db_path}')
        Base.metadata.create_all(engine)
        Session.configure(bind=engine)
        
        session = Session()
        try:
            # Create a project first to satisfy FK
            project = Project(name="Test Project")
            session.add(project)
            session.commit()
            
            project_id = project.id
            for day in range(1, 32):
                dt = datetime(2023, 1, day, tzinfo=timezone.utc)
                ideal = float(100 - (day - 1))
                actual = float(day - 1)
                remaining = ideal - actual
                
                session.add(BurndownData(
                    project_id=project_id,
                    date=dt,
                    ideal_work=ideal,
                    actual_work=actual,
                    remaining_work=remaining
                ))
            session.commit()
            
            data = generate_burndown_data(project_id, date(2023, 1, 1), date(2023, 1, 31))
            assert len(data) == 31
            assert isinstance(data, list)
            assert all(isinstance(d, dict) for d in data)
            assert all('date' in d and 'ideal_work' in d and 'actual_work' in d and 'remaining_work' in d for d in data)
            
            chart = get_burndown_chart(project_id, date(2023, 1, 1), date(2023, 1, 31))
            assert chart is not None
            assert hasattr(chart, 'data')
            assert len(chart.data) == 3
            
        finally:
            session.close()
            Session.configure(bind=None)
            engine.dispose()


if __name__ == "__main__":
    _selftest()
