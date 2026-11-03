"""Provider-agnostic LLM client with validated, structured output.

The rules this module enforces:

* The model's reply is DATA, not text: every call declares a Pydantic schema,
  and nothing that fails validation ever reaches business logic.
* Failures are bounded and visible: one corrective retry, then the fallback
  provider, then a logged failure for human review. No silent guessing.
* Every call is accounted for: tokens, cost, latency and prompt version are
  recorded, so each workflow's spend is measurable per prompt iteration.

Written as a portfolio sample; the same structure runs in my production
systems against OpenAI/Anthropic APIs.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

TSchema = TypeVar("TSchema", bound=BaseModel)


class LLMProvider(Protocol):
    """Minimal provider interface; real implementations wrap OpenAI/Anthropic SDKs."""

    name: str

    def complete(self, prompt: str) -> "RawCompletion":
        """Return the raw model output for a prompt. May raise ProviderError."""
        ...


@dataclass(frozen=True)
class RawCompletion:
    text: str
    input_tokens: int
    output_tokens: int


class ProviderError(RuntimeError):
    """Transport/provider-level failure (timeouts, rate limits, 5xx)."""


class LLMResultError(RuntimeError):
    """Raised when no provider produced schema-valid output within budget."""


@dataclass(frozen=True)
class PromptTemplate:
    """A versioned prompt. Version travels with every logged call, so output
    quality can be compared across prompt iterations instead of guessed at."""

    id: str
    version: int
    template: str

    def render(self, **params: str) -> str:
        return self.template.format(**params)


@dataclass
class CallRecord:
    """Audit row for one logical call (including retries and fallbacks)."""

    prompt_id: str
    prompt_version: int
    provider: str
    attempts: int
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    outcome: str = "ok"  # ok | validation_failed | provider_failed
    error: str | None = None


@dataclass
class StructuredLLMClient:
    """Wraps a primary and optional fallback provider behind schema validation."""

    primary: LLMProvider
    fallback: LLMProvider | None = None
    max_validation_retries: int = 1
    records: list[CallRecord] = field(default_factory=list)

    def complete(
        self,
        prompt: PromptTemplate,
        schema: type[TSchema],
        **params: str,
    ) -> TSchema:
        """Run the prompt and return schema-validated output.

        Order of attempts: primary, primary with a corrective prompt on
        validation failure, then the fallback provider. Anything beyond that
        raises LLMResultError — the caller routes it to human review.
        """
        rendered = prompt.render(**params) + self._format_instruction(schema)
        providers = [self.primary] + ([self.fallback] if self.fallback else [])
        last_error: Exception | None = None

        for provider in providers:
            record = CallRecord(prompt.id, prompt.version, provider.name, attempts=0)
            started = time.monotonic()
            try:
                result = self._attempt_with_repair(provider, rendered, schema, record)
                record.outcome = "ok"
                return result
            except ValidationError as exc:
                record.outcome = "validation_failed"
                record.error = str(exc)
                last_error = exc
            except ProviderError as exc:
                record.outcome = "provider_failed"
                record.error = str(exc)
                last_error = exc
            finally:
                record.duration_ms = int((time.monotonic() - started) * 1000)
                self.records.append(record)
                logger.info(
                    "llm_call prompt=%s v%d provider=%s outcome=%s attempts=%d tokens=%d/%d",
                    record.prompt_id, record.prompt_version, record.provider,
                    record.outcome, record.attempts,
                    record.input_tokens, record.output_tokens,
                )

        raise LLMResultError(
            f"no valid output for prompt {prompt.id} v{prompt.version}"
        ) from last_error

    def _attempt_with_repair(
        self,
        provider: LLMProvider,
        rendered: str,
        schema: type[TSchema],
        record: CallRecord,
    ) -> TSchema:
        prompt_text = rendered
        for attempt in range(1 + self.max_validation_retries):
            record.attempts = attempt + 1
            completion = provider.complete(prompt_text)
            record.input_tokens += completion.input_tokens
            record.output_tokens += completion.output_tokens
            try:
                return self._parse(completion.text, schema)
            except ValidationError as exc:
                if attempt >= self.max_validation_retries:
                    raise
                # Corrective retry: show the model its own output and the
                # validation errors. One shot — repair loops don't converge.
                prompt_text = (
                    f"{rendered}\n\nYour previous reply was:\n{completion.text}\n\n"
                    f"It failed validation with:\n{exc}\n\n"
                    "Reply again with ONLY corrected JSON."
                )
        raise AssertionError("unreachable")

    @staticmethod
    def _parse(text: str, schema: type[TSchema]) -> TSchema:
        # Models wrap JSON in prose or code fences despite instructions;
        # extract the outermost JSON object before validating.
        start, end = text.find("{"), text.rfind("}")
        candidate = text[start : end + 1] if start != -1 and end > start else text
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValidationError.from_exception_data(
                "json_decode", [{"type": "json_invalid", "loc": ("__root__",),
                                 "input": candidate, "ctx": {"error": str(exc)}}]
            ) from exc
        return schema.model_validate(payload)

    @staticmethod
    def _format_instruction(schema: type[BaseModel]) -> str:
        return (
            "\n\nReply with ONLY a JSON object matching this schema:\n"
            + json.dumps(schema.model_json_schema(), indent=2)
        )
