import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from forum.claude import AgentError, AgentResult
from forum.debate import DebateRunner, parallel
from forum.models import (Challenges, OpeningCase, Questions, ResearchReview,
                          SideResponse, Source, Verdict)


class FakeClient:
    settings = SimpleNamespace(model="test-claude")

    def __init__(self):
        self.calls = []

    async def call(self, prompt, schema, inputs, *, search=False):
        self.calls.append((schema, inputs, search))
        if schema is OpeningCase:
            value = OpeningCase(case=["Claim", "Evidence", "Second claim", "Reason"])
        elif schema in {Questions, Challenges}:
            assert inputs["affirmative"] and inputs["negative"]
            item = {"question": "What evidence supports this?", **(
                {"purpose": "Test support"} if schema is Questions else
                {"weakness": "Uncertain causality", "counterargument": "Alternative cause"})}
            value = schema.model_validate({"affirmative": [item, item], "negative": [item, item]})
        elif schema is SideResponse:
            assert inputs["questions"] and inputs["challenges"]
            value = SideResponse.model_validate({"answers": [
                {"id": question["id"], "answer": "A direct answer"}
                for question in inputs["assigned_questions"]], "rebuttal": "A focused rebuttal"})
        elif schema is ResearchReview:
            assert len(inputs["affirmative_answers"]) == len(inputs["negative_answers"]) == 4
            value = ResearchReview.model_validate({"claims": [{"claim": "An empirical claim",
                "side": "Both", "status": "Supported", "explanation": "Unverified",
                "source_urls": ["https://fabricated.invalid/study"]}], "summary": "Audit"})
        else:
            assert schema is Verdict
            assert inputs["research"]["claims"][0]["status"] == "Needs a source"
            assert "question handling" in prompt.lower()
            value = Verdict.model_validate({"winner": "Affirmative", "why": "Reason",
                "improve": "Advice", "question_feedback": {"affirmative": "Q1 answered",
                "negative": "R2 evaded"}, "scores": [22, 21, 20, 23, 20, 18, 19, 20]})
        return AgentResult(value, [Source(url="https://example.edu/study", title="Study")])


@pytest.mark.asyncio
async def test_six_role_sequence_and_real_transcript_handoffs():
    events = []
    client = FakeClient()
    await DebateRunner(client).run("Schools should ban phones.", events.append)
    assert len([event for event in events if event["type"] == "case"]) == 2
    assert [event["role"] for event in events if event["type"] == "answers"] == ["Affirmative", "Negative"]
    for event in events:
        if event["type"] == "answers":
            assert [answer["id"] for answer in event["answers"]] == ["Q1", "Q2", "R1", "R2"]
    research = next(event for event in events if event["type"] == "research")
    assert research["claims"][0]["source_urls"] == []
    assert research["claims"][0]["status"] == "Needs a source"
    verdict = next(event for event in events if event["type"] == "verdict")
    assert verdict["rubricVersion"] == 2
    assert verdict["question_feedback"]["negative"] == "R2 evaded"
    assert events[-1] == {"type": "complete", "model": "test-claude"}
    assert sum(search for _, _, search in client.calls) == 3


def test_contracts_reject_duplicate_answers_and_invalid_judging():
    with pytest.raises(ValidationError):
        SideResponse.model_validate({"answers": [{"id": "Q1", "answer": "Answer"}] * 4,
                                     "rebuttal": "Reply"})
    verdict = {"winner": "Negative", "why": "Reason", "improve": "Advice",
               "question_feedback": {"affirmative": "Q1", "negative": "R1"},
               "scores": [22, 21, 20, 23, 20, 18, 19, 20]}
    with pytest.raises(ValidationError, match="disagree"):
        Verdict.model_validate(verdict)
    verdict["winner"] = "Affirmative"
    verdict["scores"][0] = 26
    with pytest.raises(ValidationError):
        Verdict.model_validate(verdict)


@pytest.mark.asyncio
async def test_parallel_failure_cancels_sibling_work():
    started = asyncio.Event()
    cancelled = asyncio.Event()
    async def slow():
        started.set()
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()
    async def failed():
        await started.wait()
        raise AgentError("Failed role")
    with pytest.raises(AgentError, match="Failed role"):
        await parallel(slow(), failed())
    assert cancelled.is_set()
