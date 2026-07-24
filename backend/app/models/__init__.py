"""Importing every model module here ensures Base.metadata is aware of all
24 tables before Alembic's autogenerate (or Base.metadata.create_all)
inspects it. Import order follows the dependency order in
schema-reference.pdf."""

from app.models.user import User  # noqa: F401
from app.models.role import Role, Permission, UserRole, RolePermission  # noqa: F401
from app.models.team import Team, TeamMember  # noqa: F401
from app.models.patent import PatentApplication, PatentAssignment  # noqa: F401
from app.models.legal_party import Applicant, Inventor  # noqa: F401
from app.models.questionnaire import Questionnaire, QuestionnaireVersion  # noqa: F401
from app.models.ai_output import AIOutput  # noqa: F401
from app.models.template import Template  # noqa: F401
from app.models.document import Document, DocumentVersion, DocumentGenerationJob  # noqa: F401
from app.models.file import File  # noqa: F401
from app.models.collaboration import (  # noqa: F401
    Comment,
    Notification,
    AuditLog,
    CalendarEvent,
    ReportPermission,
)

__all__ = [
    "User", "Role", "Permission", "UserRole", "RolePermission",
    "Team", "TeamMember",
    "PatentApplication", "PatentAssignment",
    "Applicant", "Inventor",
    "Questionnaire", "QuestionnaireVersion",
    "AIOutput",
    "Template",
    "Document", "DocumentVersion", "DocumentGenerationJob",
    "File",
    "Comment", "Notification", "AuditLog", "CalendarEvent", "ReportPermission",
]
