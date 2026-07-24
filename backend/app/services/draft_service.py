"""Phase 6 — AI drafting (workflow item 8). Generates content SECTION BY
SECTION, per ai_output.py's docstring, from the latest submitted
QuestionnaireVersion snapshot (never the live, possibly-mid-edit
Questionnaire row). Each generation call appends a new AIOutput row rather
than overwriting — full regeneration history is kept, mirroring the
Questionnaire versioning convention already established in Phase 5.

Turning this generated text into an actual filed Document (templates,
formats, watermarking, background jobs) is Phase 7's job, not this one.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIOutput, PatentApplication, QuestionnaireVersion
from app.services.ai import AIGenerationError, AIProvider

# Jurisdiction-agnostic section set (see handover open item on jurisdiction
# still being undecided) — deliberately avoids office-specific headings like
# "Field of the Invention" that vary by patent office.
SECTION_TYPES: tuple[str, ...] = (
    "ABSTRACT",
    "BACKGROUND",
    "SUMMARY",
    "DESCRIPTION",
    "CLAIMS",
)

_SECTION_INSTRUCTIONS: dict[str, str] = {
    "ABSTRACT": (
        "Write a concise patent ABSTRACT (under 150 words) summarizing the invention, "
        "its core mechanism, and the problem it solves."
    ),
    "BACKGROUND": (
        "Write a patent BACKGROUND section explaining the problem being solved, the "
        "shortcomings of existing approaches, and the need for this invention."
    ),
    "SUMMARY": (
        "Write a patent SUMMARY section describing the invention at a high level: what "
        "it is, what it does, and its key advantages."
    ),
    "DESCRIPTION": (
        "Write a DETAILED DESCRIPTION section explaining exactly how the invention is "
        "implemented and how it operates, in enough technical depth to support the claims."
    ),
    "CLAIMS": (
        "Draft a numbered set of patent CLAIMS (starting with one independent claim, "
        "followed by dependent claims) covering the novel elements of the invention."
    ),
}


class DraftGenerationNotAllowed(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


async def latest_completed_questionnaire_version(
    db: AsyncSession, *, patent_application_id: int
) -> QuestionnaireVersion | None:
    result = await db.execute(
        select(QuestionnaireVersion)
        .where(QuestionnaireVersion.patent_application_id == patent_application_id)
        .order_by(QuestionnaireVersion.version_number.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def build_prompt(
    *, section_type: str, patent: PatentApplication, qv: QuestionnaireVersion
) -> str:
    instruction = _SECTION_INSTRUCTIONS[section_type]
    lines = [
        f"SECTION: {section_type}",
        instruction,
        "",
        f"Invention title: {patent.invention_title}",
        f"Invention type: {qv.invention_type or 'Not specified'}",
        f"Problem statement: {qv.problem_statement or ''}",
        f"Proposed solution: {qv.proposed_solution or ''}",
        f"Novelty description: {qv.novelty_description or ''}",
        f"Technical description: {qv.technical_description or ''}",
    ]
    if qv.advantages:
        lines.append(f"Advantages: {qv.advantages}")
    if qv.prior_art:
        lines.append(f"Known prior art: {qv.prior_art}")
    return "\n".join(lines)


async def next_ai_output_version(
    db: AsyncSession, *, questionnaire_version_id: int, section_type: str
) -> int:
    result = await db.execute(
        select(AIOutput.version_number)
        .where(
            AIOutput.questionnaire_version_id == questionnaire_version_id,
            AIOutput.section_type == section_type,
        )
        .order_by(AIOutput.version_number.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    return (latest or 0) + 1


async def latest_outputs_by_section(
    db: AsyncSession, *, questionnaire_version_id: int
) -> dict[str, AIOutput]:
    """Latest AIOutput row (any status) per section_type for one
    questionnaire version — what the frontend's summary view shows."""
    result = await db.execute(
        select(AIOutput)
        .where(AIOutput.questionnaire_version_id == questionnaire_version_id)
        .order_by(AIOutput.section_type, AIOutput.version_number.desc())
    )
    latest: dict[str, AIOutput] = {}
    for row in result.scalars().all():
        if row.section_type not in latest:
            latest[row.section_type] = row
    return latest


async def can_generate(db: AsyncSession, *, patent: PatentApplication) -> QuestionnaireVersion:
    """Raises DraftGenerationNotAllowed with a human reason, or returns the
    QuestionnaireVersion to generate against."""
    if patent.application_status != "Under Review":
        raise DraftGenerationNotAllowed(
            "AI drafting is only available once the assigned Patent Agent has accepted "
            f"the application (current status: {patent.application_status})"
        )
    qv = await latest_completed_questionnaire_version(
        db, patent_application_id=patent.id
    )
    if qv is None:
        raise DraftGenerationNotAllowed(
            "No submitted questionnaire found for this application yet"
        )
    return qv


async def generate_section(
    db: AsyncSession,
    *,
    patent: PatentApplication,
    qv: QuestionnaireVersion,
    section_type: str,
    provider: AIProvider,
) -> AIOutput:
    if section_type not in SECTION_TYPES:
        raise ValueError(f"Unknown section_type: {section_type}")

    version_number = await next_ai_output_version(
        db, questionnaire_version_id=qv.id, section_type=section_type
    )
    prompt = build_prompt(section_type=section_type, patent=patent, qv=qv)

    output = AIOutput(
        patent_application_id=patent.id,
        questionnaire_version_id=qv.id,
        section_type=section_type,
        version_number=version_number,
        ai_provider=provider.name,
        ai_model=getattr(provider, "model_name", provider.name),
        prompt_text=prompt,
        processing_status="Processing",
    )
    db.add(output)
    await db.flush()

    try:
        text, input_tokens, output_tokens = await provider.generate(prompt=prompt)
        output.ai_response = text
        output.input_tokens = input_tokens
        output.output_tokens = output_tokens
        output.processing_status = "Completed"
    except AIGenerationError as exc:
        output.processing_status = "Failed"
        output.ai_response = f"Generation failed: {exc}"

    await db.commit()
    await db.refresh(output)
    return output


async def generate_sections(
    db: AsyncSession,
    *,
    patent: PatentApplication,
    qv: QuestionnaireVersion,
    section_types: list[str],
    provider: AIProvider,
) -> list[AIOutput]:
    return [
        await generate_section(
            db, patent=patent, qv=qv, section_type=st, provider=provider
        )
        for st in section_types
    ]
