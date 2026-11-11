import json

import httpx2 as httpx
import anthropic
from functools import cached_property
from langchain_anthropic import ChatAnthropic
from pydantic import PrivateAttr
import pytest

from forum.claude import AgentError, ClaudeClient, provider_schema, sources_from
from forum.config import Settings
from forum.models import OpeningCase, Verdict


class MockChatAnthropic(ChatAnthropic):
    """Exercise LangChain's real request/response adapter against a mock HTTP service."""
    _test_http: object = PrivateAttr()

    @cached_property
    def _async_client(self):
        return anthropic.AsyncAnthropic(api_key=self.anthropic_api_key.get_secret_value(),
                                        http_client=self._test_http, max_retries=0, timeout=180)


def client_for(settings, http):
    model = MockChatAnthropic(model=settings.model, api_key=settings.api_key,
                              max_retries=0, output_config={"effort": "low"})
    model._test_http = http
    return ClaudeClient(settings, model=model)


def transport(handler):
    def wrapped(request):
        response = handler(request)
        if response.status_code == 200:
            data = {"id": "msg_test", "type": "message", "role": "assistant",
                    "model": "claude-sonnet-5", "stop_reason": "end_turn", "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 1}, **response.json()}
            return httpx.Response(200, json=data)
        return response
    return httpx.MockTransport(wrapped)


@pytest.mark.asyncio
async def test_search_is_separate_from_structured_generation_and_preserves_sources():
    requests = []
    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.headers["authorization"] == "Bearer test-secret"
        if "tools" in body:
            assert "format" not in body["output_config"]
            return httpx.Response(200, json={"stop_reason": "end_turn", "content": [
                {"type": "web_search_tool_result", "tool_use_id": "search_1", "content": [{"type": "web_search_result",
                    "url": "https://example.edu/study", "title": "Study", "encrypted_content": "original", "page_age": None}]},
                {"type": "text", "text": "Evidence is mixed."}]})
        assert "example.edu/study" in body["messages"][0]["content"]
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps({"case": ["Claim", "Evidence", "Other", "Reason"]})}]})
    async with httpx.AsyncClient(transport=transport(handle)) as http:
        client = client_for(Settings(api_key="test-secret"), http)
        result = await client.call("Build a case", OpeningCase, {"resolution": "A resolution"}, search=True)
    assert len(requests) == 2
    assert result.sources[0].url == "https://example.edu/study"
    assert result.value.case[0] == "Claim"


@pytest.mark.asyncio
async def test_paused_search_preserves_encrypted_tool_blocks():
    count = 0
    block = {"type": "web_search_tool_result", "tool_use_id": "search_1", "content": [{"type": "web_search_result",
        "url": "https://example.edu/study", "title": "Study", "encrypted_content": "original"}]}
    def handle(request):
        nonlocal count
        count += 1
        body = json.loads(request.content)
        if count == 1:
            return httpx.Response(200, json={"stop_reason": "pause_turn", "content": [block]})
        if count == 2:
            assert body["messages"][-1]["content"][0]["content"][0]["encrypted_content"] == "original"
            return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": "Research."}]})
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text",
            "text": json.dumps({"case": ["Title", "Reason", "Title", "Reason"]})}]})
    async with httpx.AsyncClient(transport=transport(handle)) as http:
        await client_for(Settings(api_key="test"), http).call("Case", OpeningCase, {}, search=True)
    assert count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload,expected", [
    (401, {"type": "authentication_error", "message": "private details"}, "rejected"),
    (400, {"type": "invalid_request_error", "message": "credit balance exhausted"}, "credits"),
    (429, {"type": "rate_limit_error", "message": "private details"}, "rate limited"),
])
async def test_provider_errors_are_actionable_and_redacted(status, payload, expected):
    async with httpx.AsyncClient(transport=transport(
        lambda request: httpx.Response(status, json={"error": payload}))) as http:
        with pytest.raises(AgentError) as error:
            await client_for(Settings(api_key="test-secret"), http).call("Build a case", OpeningCase, {"resolution": "A test resolution"})
    assert expected in str(error.value)
    assert "private details" not in str(error.value)
    assert "test-secret" not in str(error.value)


def test_schema_copy_and_safe_source_extraction():
    schema = Verdict.model_json_schema()
    transformed = provider_schema(schema)
    assert "maxItems" not in transformed["properties"]["scores"]
    assert "maxItems" in schema["properties"]["scores"]
    result = sources_from({"content": [{"type": "web_search_result", "url": "javascript:alert(1)"},
        {"type": "web_search_result", "url": "https://example.edu", "title": "Study", "encrypted_content": "original", "page_age": None},
        {"type": "text", "text": "Invented https://fabricated.invalid"}]})
    assert [source.url for source in result] == ["https://example.edu"]
    assert "test-secret" not in repr(Settings(api_key="test-secret"))


@pytest.mark.asyncio
async def test_coordinator_uses_actual_tool_calls_and_rejects_text_only_plans():
    tool = {"name": "build_affirmative", "description": "Build a case",
            "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}
    def handle(request):
        body = json.loads(request.content)
        assert body["tools"] == [tool]
        assert body["tool_choice"]["disable_parallel_tool_use"] is True
        return httpx.Response(200, json={"content": [{"type": "tool_use", "id": "call_1",
            "name": "build_affirmative", "input": {"explanation": "Start the affirmative case"}}]})
    async with httpx.AsyncClient(transport=transport(handle)) as http:
        result = await client_for(Settings(api_key="test"), http).choose_tool({}, [tool], [{"role": "user", "content": "Choose a tool"}])
        assert result["call"]["name"] == "build_affirmative"
    async with httpx.AsyncClient(transport=transport(lambda request: httpx.Response(200, json={"content": [{"type": "text", "text": "A plan only"}]}))) as http:
        with pytest.raises(AgentError, match="valid next tool"):
            await client_for(Settings(api_key="test"), http).choose_tool({}, [tool], [])
