"""Tests for StructuredLLMClient — run with pytest, no network required."""

from dataclasses import dataclass, field

import pytest
from pydantic import BaseModel

from llm_client import (
    LLMResultError,
    PromptTemplate,
    ProviderError,
    RawCompletion,
    StructuredLLMClient,
)


class LeadScore(BaseModel):
    category: str
    score: int


PROMPT = PromptTemplate(id="lead_score", version=3, template="Score this lead: {lead}")

VALID_JSON = '{"category": "Hot", "score": 87}'


@dataclass
class FakeProvider:
    """Scripted provider: yields queued replies, then raises if exhausted."""

    name: str
    replies: list[str] = field(default_factory=list)
    failures: int = 0  # provider-level failures before replies start
    calls: int = 0

    def complete(self, prompt: str) -> RawCompletion:
        self.calls += 1
        if self.failures > 0:
            self.failures -= 1
            raise ProviderError("rate limited")
        if not self.replies:
            raise ProviderError("no scripted reply")
        return RawCompletion(text=self.replies.pop(0), input_tokens=100, output_tokens=20)


def test_valid_output_first_try():
    client = StructuredLLMClient(primary=FakeProvider("p", [VALID_JSON]))
    result = client.complete(PROMPT, LeadScore, lead="ACME Corp")
    assert result == LeadScore(category="Hot", score=87)
    assert client.records[-1].outcome == "ok"
    assert client.records[-1].attempts == 1


def test_json_wrapped_in_prose_is_extracted():
    wrapped = f"Sure! Here is the JSON you asked for:\n```json\n{VALID_JSON}\n```"
    client = StructuredLLMClient(primary=FakeProvider("p", [wrapped]))
    assert client.complete(PROMPT, LeadScore, lead="x").score == 87


def test_corrective_retry_repairs_malformed_output():
    provider = FakeProvider("p", ['{"category": "Hot"}', VALID_JSON])  # first misses "score"
    client = StructuredLLMClient(primary=provider)
    result = client.complete(PROMPT, LeadScore, lead="x")
    assert result.score == 87
    assert provider.calls == 2
    assert client.records[-1].attempts == 2


def test_fallback_provider_used_when_primary_never_validates():
    primary = FakeProvider("primary", ["not json", "still not json"])
    fallback = FakeProvider("fallback", [VALID_JSON])
    client = StructuredLLMClient(primary=primary, fallback=fallback)
    assert client.complete(PROMPT, LeadScore, lead="x").category == "Hot"
    outcomes = [r.outcome for r in client.records]
    assert outcomes == ["validation_failed", "ok"]


def test_exhausted_attempts_raise_for_human_review():
    client = StructuredLLMClient(
        primary=FakeProvider("primary", ["nope", "nope"]),
        fallback=FakeProvider("fallback", ["also nope", "also nope"]),
    )
    with pytest.raises(LLMResultError):
        client.complete(PROMPT, LeadScore, lead="x")
    assert all(r.outcome == "validation_failed" for r in client.records)


def test_provider_failure_falls_through_to_fallback():
    client = StructuredLLMClient(
        primary=FakeProvider("primary", failures=99),
        fallback=FakeProvider("fallback", [VALID_JSON]),
    )
    assert client.complete(PROMPT, LeadScore, lead="x").score == 87
    assert client.records[0].outcome == "provider_failed"


def test_usage_is_recorded_per_call():
    client = StructuredLLMClient(primary=FakeProvider("p", [VALID_JSON]))
    client.complete(PROMPT, LeadScore, lead="x")
    record = client.records[0]
    assert record.prompt_id == "lead_score"
    assert record.prompt_version == 3
    assert record.input_tokens == 100
    assert record.output_tokens == 20
    assert record.duration_ms >= 0
