# LLM orchestration — code sample

A provider-agnostic LLM client showing how I make model output safe for
business logic in production. Written as a self-contained sample; the same
structure runs in my production systems against the OpenAI and Anthropic APIs.

The rules it enforces:

- **Model output is data, not text** — every call declares a Pydantic schema,
  and nothing that fails validation reaches business logic.
- **Failures are bounded and visible** — one corrective retry (the model sees
  its own output and the validation errors), then a fallback provider, then a
  logged failure routed to human review. No silent guessing.
- **Every call is accounted for** — tokens, latency, outcome and prompt
  version recorded per call, so each workflow's cost and quality can be
  tracked across prompt iterations.

| File | What it shows |
|---|---|
| `llm_client.py` | Versioned prompt templates, schema-forced output, corrective-retry logic, provider fallback, JSON extraction from prose-wrapped replies, per-call audit records |
| `test_llm_client.py` | 7 tests, no network needed: happy path, prose-wrapped JSON, repair retry, fallback provider, exhausted-attempts error, provider failure, usage accounting |

Run: `pip install pydantic pytest && pytest` — all tests pass offline against
a scripted fake provider.
