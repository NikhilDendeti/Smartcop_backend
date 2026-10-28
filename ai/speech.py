"""Speech to text and text to speech, behind one interface like the language models.

Audio is sent to the vendor and is never stored here. Every call is logged (without content) as an
AIRun so cost and failures are visible next to the model calls."""

import logging
import time

import openai
from django.conf import settings

from ai.models import AIRun

logger = logging.getLogger(__name__)

VOICES = {"en": "onyx", "hi": "alloy", "te": "nova"}


class SpeechUnavailable(Exception):
    """The speech service could not be reached or is not configured; the caller should fall back."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class SpeechProvider:
    name = ""

    def transcribe(self, audio: bytes, filename: str, content_type: str, language: str, timeout: float) -> str:
        raise NotImplementedError

    def synthesize(self, text: str, language: str, timeout: float) -> bytes:
        raise NotImplementedError


class OpenAISpeech(SpeechProvider):
    name = "openai"

    def __init__(self, client=None):
        self._client = client

    def _get_client(self):
        if self._client is None:
            if not settings.OPENAI_API_KEY:
                raise SpeechUnavailable("not_configured")
            self._client = openai.OpenAI(api_key=settings.OPENAI_API_KEY, max_retries=0)
        return self._client

    def _guard(self, call):
        try:
            return call()
        except openai.APITimeoutError:
            raise SpeechUnavailable("timeout") from None
        except openai.RateLimitError:
            raise SpeechUnavailable("rate_limited") from None
        except (openai.AuthenticationError, openai.PermissionDeniedError):
            raise SpeechUnavailable("auth") from None
        except openai.APIConnectionError:
            raise SpeechUnavailable("unavailable") from None
        except openai.APIStatusError as error:
            raise SpeechUnavailable("unavailable" if error.status_code >= 500 else "bad_request") from None

    def transcribe(self, audio, filename, content_type, language, timeout):
        client = self._get_client()
        result = self._guard(
            lambda: client.audio.transcriptions.create(
                model=settings.SPEECH_STT_MODEL, file=(filename, audio, content_type), language=language, timeout=timeout
            )
        )
        return (getattr(result, "text", "") or "").strip()

    def synthesize(self, text, language, timeout):
        client = self._get_client()
        response = self._guard(
            lambda: client.audio.speech.create(
                model=settings.SPEECH_TTS_MODEL, voice=VOICES.get(language, "alloy"), input=text, timeout=timeout
            )
        )
        return response.content if hasattr(response, "content") else response.read()


_factories = {"openai": OpenAISpeech}
_instances: dict[str, SpeechProvider] = {}


def get_speech_provider() -> SpeechProvider:
    name = settings.SPEECH_PROVIDER
    if name not in _factories:
        raise SpeechUnavailable("not_configured")
    if name not in _instances:
        _instances[name] = _factories[name]()
    return _instances[name]


def register_speech_provider(name, factory):
    """Add or replace a provider; used by tests and to plug in another vendor."""
    _factories[name] = factory
    _instances.pop(name, None)


def reset_speech_providers():
    _instances.clear()


def _log(task, provider, model, status, started, error_type=""):
    AIRun.objects.create(
        task=task, provider=provider, model=model, status=status, error_type=error_type,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def run_speech(task, call):
    """Run one speech call with timing, logging and a uniform failure. `call(provider, timeout)`."""
    started = time.perf_counter()
    model = settings.SPEECH_STT_MODEL if task == "transcribe" else settings.SPEECH_TTS_MODEL
    try:
        provider = get_speech_provider()
        result = call(provider, settings.SPEECH_TIMEOUT_SECONDS)
    except SpeechUnavailable as error:
        logger.warning("Speech call failed: task=%s reason=%s", task, error.reason)
        _log(task, settings.SPEECH_PROVIDER, model, "timeout" if error.reason == "timeout" else "error", started, error.reason)
        raise
    _log(task, provider.name, model, "success", started)
    return result
