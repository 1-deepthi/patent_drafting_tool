from abc import ABC, abstractmethod


class AIGenerationError(Exception):
    """Raised by a provider when generation fails — caught by the caller in
    draft_service.generate_section, which records it as a Failed AIOutput
    row rather than letting the request 500."""


class AIProvider(ABC):
    """Provider Interface abstraction (spec item: 'AI Service Layer /
    Provider Interface abstraction, swappable later'). Anything that can
    turn a text prompt into generated text can implement this — Gemini
    today, a different model later, without touching draft_service.py or
    the API layer at all.
    """

    #: Short identifier stored on AIOutput.ai_provider for audit purposes.
    name: str

    @abstractmethod
    async def generate(self, *, prompt: str) -> tuple[str, int | None, int | None]:
        """Returns (generated_text, input_tokens, output_tokens). Token
        counts are best-effort — return None where a provider doesn't
        report them. Raise AIGenerationError on failure."""
        raise NotImplementedError
