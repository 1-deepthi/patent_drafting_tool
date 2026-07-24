from app.services.ai.base import AIProvider


class StubAIProvider(AIProvider):
    """Deterministic, offline-safe placeholder generator. Used whenever
    settings.ai_provider == "stub" (the default) — lets the whole drafting
    flow (endpoints, versioning, gating, frontend) be built and verified
    without a Gemini API key or network access to Google's API, which this
    sandbox doesn't have. Swap to GeminiAIProvider by setting
    AI_PROVIDER=gemini and GEMINI_API_KEY once real calls are wanted.
    """

    name = "stub-provider"

    async def generate(self, *, prompt: str) -> tuple[str, int | None, int | None]:
        # Pull the "SECTION:" line back out of the prompt so the output at
        # least looks section-specific during manual testing/demos.
        first_line = next((line for line in prompt.splitlines() if line.strip()), "")
        body = (
            f"[Stub AI output — no real model was called]\n\n"
            f"This placeholder stands in for what {first_line.strip() or 'the requested section'} "
            f"would contain, generated from the submitted questionnaire. Configure "
            f"AI_PROVIDER=gemini with a GEMINI_API_KEY to produce real drafted text here."
        )
        input_tokens = len(prompt.split())
        output_tokens = len(body.split())
        return body, input_tokens, output_tokens
