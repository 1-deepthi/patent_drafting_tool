"""AI drafting with a stub-first provider (ADR-004).

`AI_PROVIDER=stub` (the default) never touches the network and always returns
a clearly labelled draft. `AI_PROVIDER=gemini` plus `GEMINI_API_KEY` uses the
Gemini REST API through httpx. Generated text is a drafting aid, never legal
advice.
"""
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

DRAFT_WARNING = (
    "DRAFT ONLY — this text was generated as a drafting aid and is not legal "
    "advice. A qualified patent professional must review and edit it before "
    "any filing."
)

SECTION_TYPES = ("ABSTRACT", "BACKGROUND", "SUMMARY", "DESCRIPTION", "CLAIMS")
SECTION_LABELS = {
    "ABSTRACT": "Abstract",
    "BACKGROUND": "Background",
    "SUMMARY": "Summary",
    "DESCRIPTION": "Detailed Description",
    "CLAIMS": "Claims",
}

# A draft output lands in one Firestore document (1 MiB cap). Leaving the
# provider's response unbounded would let one call exceed the document limit.
MAX_OUTPUT_CHARS = 60_000


class AIGenerationError(RuntimeError):
    pass


def _value(questionnaire: dict, field: str, fallback: str = "Not provided.") -> str:
    value = questionnaire.get(field)
    return str(value).strip() if value not in (None, "") else fallback


def _stub_text(patent: dict, questionnaire: dict, section: str) -> str:
    title = patent.get("invention_title") or "Untitled invention"
    problem = _value(questionnaire, "problem_statement")
    solution = _value(questionnaire, "proposed_solution")
    novelty = _value(questionnaire, "novelty_description")
    technical = _value(questionnaire, "technical_description")
    advantages = _value(questionnaire, "advantages", "No advantages recorded.")
    keywords = _value(questionnaire, "keywords", "No keywords recorded.")

    bodies = {
        "ABSTRACT": (
            f"A {questionnaire.get('invention_type') or 'technical'} invention titled "
            f"\"{title}\". {solution} The disclosed approach addresses: {problem}"
        ),
        "BACKGROUND": (
            f"Existing approaches to the problem addressed by \"{title}\" have "
            f"limitations. {problem} There remains a need for an improved solution."
        ),
        "SUMMARY": (
            f"Disclosed is {title}. In one aspect, {solution} The described "
            f"implementation is distinguished by: {novelty}"
        ),
        "DESCRIPTION": (
            f"Detailed description of \"{title}\".\n\n"
            f"Technical implementation: {technical}\n\n"
            f"Novelty: {novelty}\n\n"
            f"Advantages: {advantages}\n\n"
            f"Keywords: {keywords}"
        ),
        "CLAIMS": (
            f"1. A method for {title.lower()}, comprising the steps described in "
            f"the technical description.\n\n"
            f"2. The method of claim 1, wherein the implementation includes: "
            f"{novelty}\n\n"
            f"3. A system configured to perform the method of claim 1."
        ),
    }
    body = bodies.get(section, bodies["DESCRIPTION"])
    return f"{body}\n\n{DRAFT_WARNING}"


def _gemini_text(patent: dict, questionnaire: dict, section: str) -> str:
    if not settings.gemini_api_key:
        raise AIGenerationError(
            "AI_PROVIDER=gemini requires GEMINI_API_KEY to be set."
        )
    prompt = (
        "You are assisting a patent professional with a first draft. "
        "Return plain text only, no markdown. Always end with this exact "
        f"warning: {DRAFT_WARNING}\n\n"
        f"Section: {SECTION_LABELS.get(section, section)}\n"
        f"Invention title: {patent.get('invention_title')}\n"
        f"Invention type: {questionnaire.get('invention_type')}\n"
        f"Problem statement: {questionnaire.get('problem_statement')}\n"
        f"Proposed solution: {questionnaire.get('proposed_solution')}\n"
        f"Novelty: {questionnaire.get('novelty_description')}\n"
        f"Technical description: {questionnaire.get('technical_description')}\n"
        f"Advantages: {questionnaire.get('advantages')}\n"
        f"Prior art: {questionnaire.get('prior_art')}\n"
        f"Keywords: {questionnaire.get('keywords')}\n"
    )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent"
    )
    try:
        response = httpx.post(
            url,
            # The key goes in a header, never the query string: httpx puts the
            # full URL in HTTPStatusError, which would leak the key into API
            # responses and logs.
            headers={"x-goog-api-key": settings.gemini_api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"].strip()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Gemini request failed with HTTP %s", exc.response.status_code
        )
        raise AIGenerationError(
            f"Gemini request failed with HTTP {exc.response.status_code}."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - provider errors become API 502s
        # Do not interpolate the exception: httpx error strings can contain the
        # request URL, and provider responses can echo request details.
        logger.warning("Gemini request failed: %s", type(exc).__name__)
        raise AIGenerationError(
            "Gemini request failed. Check the API key and model configuration."
        ) from exc
    if DRAFT_WARNING not in text:
        text = f"{text}\n\n{DRAFT_WARNING}"
    return text


def generate_section(
    patent: dict, questionnaire: dict, section: str
) -> tuple[str, str, str | None]:
    """Return (text, provider, model) for one section."""
    if section not in SECTION_TYPES:
        raise AIGenerationError(f"Unknown section type: {section}")
    provider = (settings.ai_provider or "stub").lower()
    if provider == "gemini" and settings.gemini_api_key:
        text, used_provider, model = (
            _gemini_text(patent, questionnaire, section),
            "gemini",
            settings.gemini_model,
        )
    else:
        text, used_provider, model = (
            _stub_text(patent, questionnaire, section),
            "stub",
            None,
        )
    if len(text) > MAX_OUTPUT_CHARS:
        raise AIGenerationError(
            "The generated draft exceeded the maximum length. Shorten the "
            "questionnaire or regenerate one section at a time."
        )
    return text, used_provider, model
