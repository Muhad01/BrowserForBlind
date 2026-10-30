"""Unit tests for GeminiClient fallback, error handling, and structured parsing (NFR-REL-01, NFR-OPS-02)."""
from typing import Any

import pytest
from google.genai.errors import APIError

from core.agent.llm import (
    GeminiClient,
    LLMBadOutput,
    LLMUnavailable,
    Proposal,
)
from core.agent.model_pool import ModelPool
from core.agent.schema import ElementMeta, PageObservation


class MockResponse:
    def __init__(self, text: str):
        self.text = text


class MockGenAIClient:
    def __init__(self, responses: dict[str, list[Any]]):
        self.responses = responses
        self.call_history: list[str] = []
        self.aio = self

    @property
    def models(self):
        return self

    async def generate_content(self, model: str, contents: str, config: Any):
        self.call_history.append(model)
        queue = self.responses.get(model, [])
        if not queue:
            raise RuntimeError(f"No mock response configured for {model}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def sample_obs() -> PageObservation:
    return PageObservation(
        url="https://en.wikipedia.org",
        title="Wikipedia, the free encyclopedia",
        elements=[
            ElementMeta(index=1, tag="input", text="", role="search box", placeholder="Search Wikipedia"),
            ElementMeta(index=2, tag="button", text="Search", role="button"),
        ],
    )


@pytest.mark.asyncio
async def test_fallback_on_429_rate_limit(sample_obs):
    # Model A hits 429 rate limit -> falls back to Model B which succeeds
    pool = ModelPool(["model-a", "model-b"])
    err_429 = APIError(429, {"error": {"message": "Resource has been exhausted: per minute"}})
    valid_json = '{"action": "click", "target": "2", "value": "", "reason": "Proceed", "requires_confirmation": false}'

    mock_client = MockGenAIClient({
        "model-a": [err_429],
        "model-b": [MockResponse(valid_json)],
    })

    client = GeminiClient(pool=pool, client=mock_client)
    proposal = await client.propose("Search wiki", [], sample_obs)

    assert isinstance(proposal, Proposal)
    assert proposal.action.action == "click"
    assert proposal.action.target == "2"
    assert proposal.model == "model-b"
    assert mock_client.call_history == ["model-a", "model-b"]
    # Model A should now be in cooldown
    assert "model-a" not in pool.available()


@pytest.mark.asyncio
async def test_fallback_on_503_server_error(sample_obs):
    # Model A hits 503 unavailable -> falls back to Model B which succeeds
    pool = ModelPool(["model-a", "model-b"])
    err_503 = APIError(503, {"error": {"message": "The service is temporarily unavailable"}})
    valid_json = '{"action": "navigate", "target": "https://example.com", "value": "", "reason": "Go", "requires_confirmation": false}'

    mock_client = MockGenAIClient({
        "model-a": [err_503],
        "model-b": [MockResponse(valid_json)],
    })

    client = GeminiClient(pool=pool, client=mock_client)
    proposal = await client.propose("Navigate", [], sample_obs)

    assert proposal.action.action == "navigate"
    assert proposal.model == "model-b"
    assert "model-a" not in pool.available()


@pytest.mark.asyncio
async def test_fallback_on_404_client_error_permanent_skip(sample_obs):
    # Model A hits 404 (wrong model name) -> permanent skip -> falls back to Model B
    pool = ModelPool(["model-a", "model-b"])
    err_404 = APIError(404, {"error": {"message": "models/model-a not found"}})
    valid_json = '{"action": "stop", "target": "", "value": "Finished", "reason": "All done", "requires_confirmation": false}'

    mock_client = MockGenAIClient({
        "model-a": [err_404],
        "model-b": [MockResponse(valid_json)],
    })

    client = GeminiClient(pool=pool, client=mock_client)
    proposal = await client.propose("Stop task", [], sample_obs)

    assert proposal.model == "model-b"
    assert pool.available() == ["model-b"]


@pytest.mark.asyncio
async def test_bad_json_retries_same_model_then_raises(sample_obs):
    # Bad JSON output should retry the SAME model once, then raise LLMBadOutput without falling through
    pool = ModelPool(["model-a", "model-b"])
    bad_json = "This is not valid json at all"

    mock_client = MockGenAIClient({
        "model-a": [MockResponse(bad_json), MockResponse(bad_json)],
        "model-b": [MockResponse('{"action": "stop", "value": "Never reached"}')],
    })

    client = GeminiClient(pool=pool, client=mock_client)
    with pytest.raises(LLMBadOutput) as exc_info:
        await client.propose("Do something", [], sample_obs)

    assert "Failed to parse LLM structured output" in str(exc_info.value)
    # Model B was never called!
    assert mock_client.call_history == ["model-a", "model-a"]


@pytest.mark.asyncio
async def test_all_models_unavailable_raises_with_reasons(sample_obs):
    pool = ModelPool(["model-a", "model-b"])
    err_503 = APIError(503, {"error": {"message": "Service unavailable"}})
    err_429 = APIError(429, {"error": {"message": "Rate limit exceeded"}})

    mock_client = MockGenAIClient({
        "model-a": [err_503],
        "model-b": [err_429],
    })

    client = GeminiClient(pool=pool, client=mock_client)
    with pytest.raises(LLMUnavailable) as exc_info:
        await client.propose("Goal", [], sample_obs)

    err_msg = str(exc_info.value)
    assert "all models unavailable" in err_msg
    assert "model-a" in err_msg
    assert "model-b" in err_msg

