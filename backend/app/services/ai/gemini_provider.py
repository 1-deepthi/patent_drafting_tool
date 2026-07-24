import httpx
from loguru import logger

from app.core.config import settings
from app.services.ai.base import AIGenerationError, AIProvider

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiAIProvider(AIProvider):
    """Calls Google's Generative Language API directly over REST (no extra
    SDK dependency — httpx is already a project dependency). Requires
    settings.gemini_api_key.

    NOT LIVE-VERIFIED: this sandbox's network egress allowlist doesn't
    include generativelanguage.googleapis.com, so this code has been
    reviewed carefully against the documented API shape but never actually
    executed against a live Gemini endpoint. Test against a real key/network
    before relying on it in production.
    """

    name = "gemini"

    async def generate(self, *, prompt: str) -> tuple[str, int | None, int | None]:
        if not settings.gemini_api_key:
            raise AIGenerationError("GEMINI_API_KEY is not configured")

        url = _ENDPOINT.format(model=settings.gemini_model)
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    url,
                    params={"key": settings.gemini_api_key},
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.error("Gemini request failed: {}", exc)
            raise AIGenerationError(f"Gemini request failed: {exc}") from exc

        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise AIGenerationError(f"Unexpected Gemini response shape: {data}") from exc

        usage = data.get("usageMetadata", {})
        input_tokens = usage.get("promptTokenCount")
        output_tokens = usage.get("candidatesTokenCount")
        return text, input_tokens, output_tokens
