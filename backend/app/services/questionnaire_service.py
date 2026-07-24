from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PatentApplication, Questionnaire, QuestionnaireVersion
from app.models.questionnaire import QUESTIONNAIRE_TEXT_FIELDS
from app.services.legal_party_service import list_applicants, list_inventors

# ASSUMPTION (flag if wrong): the minimum fields required to submit the
# questionnaire for review. advantages/prior_art/keywords/has_existing_drawings
# stay optional — useful detail, not blocking.
REQUIRED_FOR_SUBMIT = (
    "invention_type", "problem_statement", "proposed_solution",
    "novelty_description", "technical_description",
)

# completion_percentage is computed over every text field plus invention_type
_COMPLETION_FIELDS = (*QUESTIONNAIRE_TEXT_FIELDS, "invention_type")


def _is_filled(value) -> bool:
    return value is not None and str(value).strip() != ""


def compute_completion(q: Questionnaire) -> Decimal:
    filled = sum(1 for f in _COMPLETION_FIELDS if _is_filled(getattr(q, f)))
    pct = (filled / len(_COMPLETION_FIELDS)) * 100
    return Decimal(str(round(pct, 2)))


def missing_required_fields(q: Questionnaire) -> list[str]:
    return [f for f in REQUIRED_FOR_SUBMIT if not _is_filled(getattr(q, f))]


async def get_or_create_questionnaire(
    db: AsyncSession, *, patent: PatentApplication
) -> Questionnaire:
    result = await db.execute(
        select(Questionnaire).where(Questionnaire.patent_application_id == patent.id)
    )
    q = result.scalar_one_or_none()
    if q is not None:
        return q

    q = Questionnaire(
        patent_application_id=patent.id,
        questionnaire_status="Not Started",
        completion_percentage=Decimal("0.00"),
    )
    db.add(q)
    await db.flush()
    return q


def apply_update(q: Questionnaire, payload: dict) -> None:
    for field, value in payload.items():
        setattr(q, field, value)
    q.completion_percentage = compute_completion(q)
    if q.questionnaire_status == "Completed":
        # Editing after a prior submission reopens it — a fresh submit is
        # required to re-snapshot as a new version.
        q.questionnaire_status = "In Progress"
    elif q.completion_percentage > 0:
        q.questionnaire_status = "In Progress"
    else:
        q.questionnaire_status = "Not Started"


async def next_version_number(db: AsyncSession, *, questionnaire_id: int) -> int:
    result = await db.execute(
        select(QuestionnaireVersion.version_number)
        .where(QuestionnaireVersion.questionnaire_id == questionnaire_id)
        .order_by(QuestionnaireVersion.version_number.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    return (latest or 0) + 1


async def snapshot_version(
    db: AsyncSession,
    *,
    q: Questionnaire,
    created_by: int,
    change_reason: str | None = None,
) -> QuestionnaireVersion:
    """Permanent snapshot, never deleted or overwritten — one row per
    submit/resubmit cycle, per spec item 7's comment/version history rule."""
    version_number = await next_version_number(db, questionnaire_id=q.id)
    version = QuestionnaireVersion(
        questionnaire_id=q.id,
        patent_application_id=q.patent_application_id,
        version_number=version_number,
        version_status="Submitted",
        invention_type=q.invention_type,
        problem_statement=q.problem_statement,
        proposed_solution=q.proposed_solution,
        novelty_description=q.novelty_description,
        technical_description=q.technical_description,
        advantages=q.advantages,
        prior_art=q.prior_art,
        keywords=q.keywords,
        change_reason=change_reason,
        created_by=created_by,
    )
    db.add(version)
    await db.flush()
    return version


async def list_versions(db: AsyncSession, *, questionnaire_id: int) -> list[QuestionnaireVersion]:
    result = await db.execute(
        select(QuestionnaireVersion)
        .where(QuestionnaireVersion.questionnaire_id == questionnaire_id)
        .order_by(QuestionnaireVersion.version_number.desc())
    )
    return list(result.scalars().all())


async def basic_info_complete(db: AsyncSession, *, patent: PatentApplication) -> list[str]:
    """Used by patents.py's submit endpoint to gate Draft -> Submitted (NEW
    Phase 5 decision — flag if submit should NOT require this).
    Returns a list of human-readable problems; empty list means ready."""
    problems: list[str] = []
    applicants = await list_applicants(db, patent_application_id=patent.id)
    if not applicants:
        problems.append("at least one Applicant is required")
    elif not any(a.is_primary for a in applicants):
        problems.append("one Applicant must be marked primary")

    inventors = await list_inventors(db, patent_application_id=patent.id)
    if not inventors:
        problems.append("at least one Inventor is required")

    if patent.questionnaire_status != "Completed":
        problems.append("the questionnaire must be completed")

    return problems
