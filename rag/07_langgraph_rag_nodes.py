"""Graph nodes — pure functions over `ChatState`.

Each node takes the current state and returns the subset of
keys it populates. LangGraph merges partial updates into the
running state and routes edges based on the `needs_web` flag
that `decide_node` sets.

Node responsibilities are narrow by design:

- `retrieve_node`  — docs RAG.
- `decide_node`    — should we hit the web for this turn?
- `web_search_node` — run the configured web search.
- `compose_node`    — LLM call that emits the assistant's text.

The LLM call is injected as a callable so the service + tests
can swap in a real provider / a `MockProvider` without touching
the graph.

docs-ref: docs/modules/assistant/chat/index.md#langgraph-flow
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.llm.provider import LLMProvider, Message
from app.modules.assistant.chat.graph.state import ChatState
from app.modules.assistant.chat.services.retriever import (
    DocsRetriever,
    RetrievedSnippet,
)
from app.modules.assistant.chat.services.web_search import (
    WebResult,
    WebSearchProvider,
)


def retrieve_node(state: ChatState, retriever: DocsRetriever) -> ChatState:
    """Populate `snippets` from the docs collection."""
    question = state["question"]
    snippets = retriever.retrieve(question)
    return {"snippets": snippets}


def decide_node(
    state: ChatState,
    *,
    recency_keywords: tuple[str, ...],
    poor_match_threshold: float,
) -> ChatState:
    """Flag the turn as web-needed when RAG can't cover it.

    Three signals trigger a web call:

    1. RAG returned zero snippets — nothing local to ground on.
    2. The top snippet's cosine distance exceeds `poor_match_threshold` —
       retrieval matched but not well enough. Chroma returns distance
       (lower = closer), so higher values indicate worse matches.
    3. The question carries a "freshness" keyword — even a
       good RAG hit is likely stale for time-sensitive asks.
       Keywords are loaded from config and cover multiple languages.
    """
    snippets: list[RetrievedSnippet] = state.get("snippets", [])
    question_lower = state["question"].lower()
    carries_recency = any(keyword in question_lower for keyword in recency_keywords)
    no_snippets = len(snippets) == 0
    poor_top_match = bool(snippets) and snippets[0].score > poor_match_threshold
    return {"needs_web": no_snippets or poor_top_match or carries_recency}


def decide_edge(state: ChatState) -> str:
    """Conditional-edge function — return the next node's name."""
    return "web_search" if state.get("needs_web") else "compose"


def web_search_node(
    state: ChatState, provider: WebSearchProvider, *, max_results: int
) -> ChatState:
    """Run the web search and stash results. Failures degrade to `[]`."""
    question = state["question"]
    results = provider.search(question, max_results=max_results)
    return {"web_results": results}


def compose_node(
    state: ChatState,
    system_prompt_header: str,
    llm: LLMProvider,
    max_snippet_chars: int,
) -> ChatState:
    """Build the system prompt, call the LLM, emit the assistant text."""
    snippets = _trim_snippets(state.get("snippets", []), max_snippet_chars)
    web_results = state.get("web_results", [])
    system_prompt = _compose_system_prompt(system_prompt_header, snippets, web_results)

    messages = [Message(role="system", content=system_prompt)]
    for entry in state["history"]:
        messages.append(Message(role=entry.role, content=entry.content))

    result = llm.complete(messages)
    # Overwrite `snippets` with the trimmed subset so the final
    # state reflects what the LLM actually saw — callers read
    # this to render the citation strip.
    return {"reply_content": result.content, "snippets": snippets}


def _trim_snippets(snippets: list[RetrievedSnippet], max_chars: int) -> list[RetrievedSnippet]:
    """Drop snippets from the tail until the combined text fits."""
    running = 0
    out: list[RetrievedSnippet] = []
    for snippet in snippets:
        if running + len(snippet.text) > max_chars and out:
            break
        out.append(snippet)
        running += len(snippet.text)
    return out


def _compose_system_prompt(
    header: str,
    snippets: list[RetrievedSnippet],
    web_results: list[WebResult],
) -> str:
    """Assemble the final system prompt with doc + web context."""
    parts = [header]
    if snippets:
        parts.append("Documentation snippets (most relevant first):")
        for index, snippet in enumerate(snippets, start=1):
            heading = snippet.heading_path or "(document root)"
            parts.append(
                f"[doc {index}] source={snippet.source} · heading={heading}\n" f"{snippet.text}"
            )
    else:
        parts.append("No documentation snippets matched the question.")

    if web_results:
        parts.append("Web search results:")
        for index, result in enumerate(web_results, start=1):
            parts.append(f"[web {index}] {result.title} ({result.url})\n" f"{result.snippet}")

    return "\n\n".join(parts)


RetrieveCallable = Callable[[ChatState], ChatState]
WebSearchCallable = Callable[[ChatState], ChatState]
ComposeCallable = Callable[[ChatState], ChatState]
