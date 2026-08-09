"""
report_generator — Reusable tools for generating structured project reports, task summaries, and milestone overviews. It supports dynamic report templates and multiple export formats (JSON, CSV, plain text).

### PART-META-JSON
{
  "name": "report_generator",
  "layer": "projects",
  "purpose": "Generates structured project reports, task summaries, and milestone overviews with dynamic report templates and JSON/CSV/text export. Uses the canonical projects-layer models: Tasks/Projects owned by scrapyard.projects.task_manager and Milestone/ProjectMilestone owned by scrapyard.projects.milestone_tracker (defines only its own ReportTemplate and Report tables).",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model", "scrapyard.projects.task_manager", "scrapyard.projects.milestone_tracker"],
  "inputs": "project_id, ReportType enum, export format string; an engine bound via configure_session().",
  "outputs": "Rendered report strings persisted as Report rows; export bytes in JSON/CSV/text.",
  "files_created": [],
  "security_notes": "No authorization checks: reports expose project, task and milestone data for any project_id passed in, so enforce project access control in the calling layer. Template rendering uses str.format on stored templates - a malicious template cannot execute code but can probe the provided context keys; templates fall back to structured output on formatting errors.",
  "ai_usage": "Import what you need from `scrapyard.projects.report_generator`.",
  "example": "from scrapyard.projects.report_generator import *",
  "import_path": "scrapyard.projects.report_generator"
}
### END-PART-META
"""
import logging
import os
import json
import csv
import io
import tempfile
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any

from sqlalchemy import (
    String, Integer, Text, DateTime, JSON, select, create_engine
)
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel

# Canonical-owner pattern: task_manager owns Tasks/Projects, milestone_tracker
# owns Milestone/ProjectMilestone. This part imports them instead of
# re-declaring duplicate task/project/milestone tables.
from scrapyard.projects.task_manager import Tasks as Task, Projects as Project
from scrapyard.projects.milestone_tracker import Milestone, ProjectMilestone

logger = logging.getLogger(__name__)


class ReportType(Enum):
    STATUS = "status"
    TASK_SUMMARY = "task_summary"
    MILESTONE_OVERVIEW = "milestone_overview"


# Module-level session management (configured at runtime)
_session_factory: Optional[Any] = None


def configure_session(engine):
    """Configure the module to use the given engine for database operations."""
    global _session_factory
    _session_factory = sessionmaker(bind=engine)
    logger.debug("Session configured for report_generator")


def _get_session() -> Session:
    """Get a new session from the configured factory."""
    if _session_factory is None:
        raise RuntimeError("Report generator session not configured. Call configure_session(engine) first.")
    return _session_factory()


# ORM Models
class ReportTemplate(IntPKModel):
    __tablename__ = "report_templates"
    
    report_type: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    template_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    format: Mapped[str] = mapped_column(String(20), default="html")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc), 
        onupdate=lambda: datetime.now(timezone.utc)
    )


class Report(IntPKModel):
    __tablename__ = "report_generator_reports"
    
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)


# Public API
def get_report_template(report_type: ReportType) -> ReportTemplate:
    """Retrieve report template by type."""
    session = _get_session()
    stmt = select(ReportTemplate).where(ReportTemplate.report_type == report_type.value)
    result = session.execute(stmt).scalar_one_or_none()
    if result is None:
        raise ValueError(f"ReportTemplate not found for type: {report_type.value}")
    return result


def generate_project_report(project_id: int, report_type: ReportType) -> str:
    """Generate a structured report for the given project."""
    session = _get_session()
    
    # Retrieve template
    template = session.execute(
        select(ReportTemplate).where(ReportTemplate.report_type == report_type.value)
    ).scalar_one_or_none()
    
    if template is None:
        raise ValueError(f"No template configured for report type: {report_type.value}")
    
    # Fetch project data
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError(f"Project {project_id} not found")
    
    tasks = session.execute(
        select(Task).where(Task.project_id == project_id)
    ).scalars().all()
    
    milestones = session.execute(
        select(Milestone)
        .join(ProjectMilestone, Milestone.id == ProjectMilestone.milestone_id)
        .where(ProjectMilestone.project_id == project_id)
    ).scalars().all()
    
    # Build context for template rendering
    context = {
        "project_id": project.id,
        "project_name": project.name,
        "project_status": project.status,
        "task_count": len(tasks),
        "milestone_count": len(milestones),
        "tasks_list": "\n".join([f"- {t.title} [{t.status}]" for t in tasks]),
        "milestones_list": "\n".join([f"- {m.title}" for m in milestones]),
    }
    
    # Simple template rendering
    try:
        content = template.template_content.format(**context)
    except (KeyError, ValueError):
        # Fallback to structured generation if template formatting fails
        lines = [
            f"Report: {report_type.value}",
            f"Project: {project.name} (ID: {project.id})",
            f"Status: {project.status}",
            f"",
            f"Tasks ({len(tasks)}):",
        ]
        for t in tasks:
            lines.append(f"  - {t.title}: {t.status}")
        lines.append("")
        lines.append(f"Milestones ({len(milestones)}):")
        for m in milestones:
            lines.append(f"  - {m.title}")
        content = "\n".join(lines)
    
    # Persist report
    report = Report(
        project_id=project_id,
        report_type=report_type.value,
        content=content,
        metadata_json={
            "template_id": template.id,
            "task_count": len(tasks),
            "milestone_count": len(milestones)
        }
    )
    session.add(report)
    session.commit()
    
    return content


def export_task_summary(project_id: int, format: str) -> bytes:
    """Export task summary for a project in the specified format."""
    session = _get_session()
    
    tasks = session.execute(
        select(Task).where(Task.project_id == project_id)
    ).scalars().all()
    
    fmt = format.lower()
    
    if fmt == "json":
        data = [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "due_date": t.due_date.isoformat() if t.due_date else None
            }
            for t in tasks
        ]
        return json.dumps(data, indent=2).encode("utf-8")
    
    elif fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "title", "status", "due_date"])
        for t in tasks:
            writer.writerow([
                t.id, 
                t.title, 
                t.status, 
                t.due_date.isoformat() if t.due_date else ""
            ])
        return output.getvalue().encode("utf-8")
    
    else:
        # Default text format
        lines = [f"Task Summary for Project {project_id}", "=" * 40]
        for t in tasks:
            due = f" (Due: {t.due_date.date()})" if t.due_date else ""
            lines.append(f"[{t.status}] {t.title}{due}")
        return "\n".join(lines).encode("utf-8")


def _selftest() -> bool:
    """Self-contained test suite for offline validation."""
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_report_generator.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        # Create schema
        IntPKModel.metadata.create_all(engine)
        configure_session(engine)
        
        session = _get_session()
        
        try:
            # Setup test data
            templates = [
                ReportTemplate(
                    report_type=ReportType.STATUS.value,
                    template_content="Status Report for {project_name}: {project_status}",
                    format="text"
                ),
                ReportTemplate(
                    report_type=ReportType.TASK_SUMMARY.value,
                    template_content="Task Summary for {project_name}\nTasks: {task_count}\n{tasks_list}",
                    format="text"
                ),
                ReportTemplate(
                    report_type=ReportType.MILESTONE_OVERVIEW.value,
                    template_content="Milestones for {project_name}: {milestone_count}",
                    format="text"
                ),
            ]
            session.add_all(templates)
            
            project = Project(name="Scrapyard Alpha", status="active")
            session.add(project)
            session.flush()  # Get ID
            
            tasks = [
                Task(project_id=project.id, title="Collect Parts", status="completed"),
                Task(project_id=project.id, title="Sort Inventory", status="in_progress"),
                Task(project_id=project.id, title="Update Database", status="pending"),
            ]
            session.add_all(tasks)
            
            # Milestones via the canonical owner's link table.
            for ms_title in ("Phase 1 Complete", "Phase 2 Review"):
                milestone = Milestone(title=ms_title)
                session.add(milestone)
                session.flush()
                session.add(
                    ProjectMilestone(milestone_id=milestone.id, project_id=project.id)
                )

            session.commit()
            
            # Test 1: Template retrieval
            tpl = get_report_template(ReportType.STATUS)
            assert tpl.report_type == ReportType.STATUS.value
            assert "{project_name}" in tpl.template_content
            
            # Test 2: Report generation (string return and ORM persistence)
            report_str = generate_project_report(project.id, ReportType.TASK_SUMMARY)
            assert isinstance(report_str, str)
            assert "Scrapyard Alpha" in report_str
            assert "Collect Parts" in report_str
            assert "3" in report_str or "completed" in report_str  # task count or status
            
            # Verify ORM storage
            stmt = select(Report).where(Report.project_id == project.id)
            stored = session.execute(stmt).scalars().all()
            assert len(stored) == 1
            assert stored[0].content == report_str
            
            # Test 3: Export formats
            json_data = export_task_summary(project.id, "json")
            assert isinstance(json_data, bytes)
            parsed = json.loads(json_data)
            assert len(parsed) == 3
            assert parsed[0]["title"] == "Collect Parts"
            
            csv_data = export_task_summary(project.id, "csv")
            assert isinstance(csv_data, bytes)
            assert b"Collect Parts" in csv_data
            assert b"in_progress" in csv_data
            
            text_data = export_task_summary(project.id, "text")
            assert isinstance(text_data, bytes)
            assert b"Sort Inventory" in text_data
            
            # Test 4: Milestone report generation
            ms_report = generate_project_report(project.id, ReportType.MILESTONE_OVERVIEW)
            assert "Phase 1" in ms_report or "2" in ms_report
            
            logger.info("_selftest completed successfully")
            return True
            
        finally:
            session.close()
            engine.dispose()
            # Ensure sqlite connection is closed (handled by engine dispose)
    
    return False


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(1 if _selftest() is False else 0)
