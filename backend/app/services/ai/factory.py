from app.core.config import settings
from app.services.ai.base import AIProvider
from app.services.ai.gemini_provider import GeminiAIProvider
from app.services.ai.stub_provider import StubAIProvider


def get_ai_provider() -> AIProvider:
    if settings.ai_provider == "gemini":
        return GeminiAIProvider()
    return StubAIProvider()
