"""
notification_service — Send timely notifications for expense events via customizable templates, ensuring users are informed of submission, approval, and reimbursement statuses.

### PART-META-JSON
{
  "name": "notification_service",
  "layer": "expenses",
  "purpose": "Send timely notifications for expense events via customizable templates, ensuring users are informed of submission, approval, and reimbursement statuses.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "NotificationService(session).notify_user(user, message, event_type='user_notification', context=None); send_approval_reminder(request); render_template(template, context). ORM models (UserModel, Notification, NotificationTemplateModel) are canonical; User/ApprovalRequest dataclasses are thin API carriers.",
  "outputs": "Notification rows persisted per event; notify_user renders the event's NotificationTemplateModel (subject/body placeholder substitution) when one exists, falling back to the raw message.",
  "files_created": [],
  "security_notes": "Template rendering is plain {placeholder} string substitution - no eval/format-spec gadgets; context values are stringified, and unknown placeholders stay verbatim. Delivery is a log-only placeholder (no network); when wiring email/SMS, do not log message bodies at info level in production - they may contain expense amounts and user PII (this module currently logs rendered bodies for the offline path).",
  "ai_usage": "Import what you need from `scrapyard.expenses.notification_service`.",
  "example": "from scrapyard.expenses.notification_service import *",
  "import_path": "scrapyard.expenses.notification_service"
}
### END-PART-META
"""

from sqlalchemy import String, Boolean, DateTime, func, ForeignKey, create_engine
from sqlalchemy.orm import mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from dataclasses import dataclass
from typing import Optional, Dict, Any
import os, logging, tempfile

logger = logging.getLogger(__name__)


@dataclass
class User:
    """Thin API carrier for callers that don't hold a UserModel row."""
    id: int
    name: str = ""
    email: str = ""


@dataclass
class ApprovalRequest:
    """Thin API carrier for approval-reminder calls."""
    id: int
    user_id: int
    request_type: str
    status: str


# SQLAlchemy models are the canonical representations for persisted concepts.
class UserModel(IntPKModel):
    __tablename__ = 'user'
    username = mapped_column(String(50), nullable=False, default="")
    email = mapped_column(String(100), nullable=False, default="")


class Notification(IntPKModel):
    __tablename__ = 'notification_service_notification'
    user_id = mapped_column(ForeignKey('user.id'), index=True)
    event_type = mapped_column(String(50), nullable=False, index=True)
    status = mapped_column(Boolean, default=False)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), onupdate=func.now())


class NotificationTemplateModel(IntPKModel):
    __tablename__ = 'notification_service_notification_template'
    event_type = mapped_column(String(50), nullable=False, index=True)
    subject = mapped_column(String(255), nullable=False)
    body = mapped_column(String(1000), nullable=False)


class NotificationService:
    def __init__(self, session: Session):
        self.session = session

    def _find_template(self, event_type: str) -> Optional[NotificationTemplateModel]:
        return (
            self.session.query(NotificationTemplateModel)
            .filter_by(event_type=event_type)
            .first()
        )

    def notify_user(self, user: User, message: str,
                    event_type: str = "user_notification",
                    context: Optional[Dict[str, Any]] = None) -> bool:
        """Send a notification to a user and persist it.

        If a NotificationTemplateModel exists for `event_type`, its subject/body
        are rendered through the template engine with the user fields, the raw
        message, and any extra context; otherwise the raw message is delivered.
        """
        try:
            render_context: Dict[str, Any] = {
                "user_id": user.id,
                "username": user.name,
                "email": user.email,
                "message": message,
            }
            if context:
                render_context.update(context)

            template = self._find_template(event_type)
            if template is not None:
                subject, body = self.render_template(template, render_context)
            else:
                subject, body = f"Notification for user {user.id}", message

            # Persist notification record
            notification = Notification(
                user_id=user.id,
                event_type=event_type,
                status=True
            )
            self.session.add(notification)
            self.session.commit()

            # Log the rendered content (simulating delivery)
            logger.info(f"Notification sent to user {user.id}: [{subject}] {body}")
            return True
        except Exception as e:
            self.session.rollback()
            logger.error(f"Failed to send user notification: {e}")
            return False

    def send_approval_reminder(self, request: ApprovalRequest) -> bool:
        """Send approval reminder and persist to database"""
        try:
            # Persist notification record
            notification = Notification(
                user_id=request.user_id,
                event_type="approval_reminder",
                status=True
            )
            self.session.add(notification)
            
            # Update request status
            request.status = "REMINDER_SENT"
            self.session.commit()
            
            logger.info(f"Approval reminder sent for request {request.id}")
            return True
        except Exception as e:
            self.session.rollback()
            logger.error(f"Failed to send approval reminder: {e}")
            return False

    def render_template(self, template: NotificationTemplateModel, context: Dict[str, Any]) -> tuple:
        """Render a template with {placeholder} substitution.

        Accepts the canonical NotificationTemplateModel (subject/body); legacy
        objects exposing subject_template/body_template still work.
        """
        subject = getattr(template, "subject", None)
        if subject is None:
            subject = getattr(template, "subject_template")
        body = getattr(template, "body", None)
        if body is None:
            body = getattr(template, "body_template")

        for key, value in context.items():
            placeholder = f"{{{key}}}"
            subject = subject.replace(placeholder, str(value))
            body = body.replace(placeholder, str(value))

        return subject, body


def _selftest():
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    db_path = os.path.join(temp_dir.name, 'test.db')
    
    engine = None
    session = None
    
    try:
        # Create SQLAlchemy engine and session
        engine = create_engine(f'sqlite:///{db_path}')
        SessionLocal = sessionmaker(bind=engine)
        
        # Create all tables (User and Notification)
        IntPKModel.metadata.create_all(engine)
        
        session = SessionLocal()
        
        # Create test user in database (required for FK constraint)
        test_user_model = UserModel(id=1, username="testuser", email="test@example.com")
        session.add(test_user_model)
        session.commit()
        
        # Initialize service
        service = NotificationService(session)
        
        # Test User dataclass for API
        user_api = User(id=1, name="Test User", email="test@example.com")

        # Test notify_user - returns success/failure status and persists
        message = "Your expense has been approved."
        result = service.notify_user(user_api, message)
        assert result == True, "notify_user should return True"

        # Verify notification was created and persisted correctly
        notifications = session.query(Notification).filter_by(user_id=1).all()
        assert len(notifications) == 1, "Notification should be persisted in database"
        assert notifications[0].event_type == "user_notification"
        assert notifications[0].status == True

        # Test notify_user WITH a stored template: the template engine must be used
        tpl_row = NotificationTemplateModel(
            event_type="expense_submitted",
            subject="Expense update for {username}",
            body="Hi {username}: {message}",
        )
        session.add(tpl_row)
        session.commit()

        handler_records = []

        class _Capture(logging.Handler):
            def emit(self, record):
                handler_records.append(record.getMessage())

        cap = _Capture()
        prev_level = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(cap)
        try:
            result = service.notify_user(user_api, "Submitted for review.",
                                         event_type="expense_submitted")
        finally:
            logger.removeHandler(cap)
            logger.setLevel(prev_level)
        assert result == True
        rendered = [m for m in handler_records if "Expense update for Test User" in m]
        assert rendered, "notify_user must render the stored template"
        assert "Hi Test User: Submitted for review." in rendered[0]
        templated = session.query(Notification).filter_by(event_type="expense_submitted").all()
        assert len(templated) == 1, "Templated notification should be persisted"
        
        # Test send_approval_reminder - triggers correctly and persists
        approval_request = ApprovalRequest(
            id=2, 
            user_id=1, 
            request_type="expense", 
            status="PENDING"
        )
        result = service.send_approval_reminder(approval_request)
        assert result == True, "send_approval_reminder should return True"
        assert approval_request.status == "REMINDER_SENT", "Request status should be updated to REMINDER_SENT"
        
        # Verify reminder notification was persisted
        reminders = session.query(Notification).filter_by(event_type="approval_reminder").all()
        assert len(reminders) == 1, "Reminder notification should be persisted"
        
        # Test template rendering with placeholder substitution (canonical ORM model)
        template = NotificationTemplateModel(
            event_type="expense_approved",
            subject="Expense #{request_id} Approved",
            body="Dear {username}, your expense of ${amount} has been approved."
        )
        subject, body = service.render_template(template, {
            "request_id": 123,
            "username": "testuser", 
            "amount": "50.00"
        })
        assert "123" in subject, "Template should substitute request_id in subject"
        assert "testuser" in body, "Template should substitute username in body"
        assert "50.00" in body, "Template should substitute amount in body"
        
        # Test that all models validate with type hints (implicitly tested by successful instantiation)
        # Test logging is used (implicitly tested - no print statements)
        # Test no exceptions raised (if we get here, no exceptions)
        
        logger.info("All notification service tests passed")
        
    finally:
        if session:
            session.close()
        if engine:
            engine.dispose()
        temp_dir.cleanup()


if __name__ == "__main__":
    _selftest()
