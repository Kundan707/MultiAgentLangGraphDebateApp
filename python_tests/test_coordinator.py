import copy

import pytest
from fastapi.testclient import TestClient

from forum.app import create_app
from forum.claude import AgentError
from forum.config import Settings
from forum.coordinator import Coordinator
from forum.debate import DebateRunner
from forum.memory import Journal
from forum.models import OpeningCase
from python_tests.test_debate import FakeClient


class FakeMemory:
    def __init__(self):
        self.records = {}
        self.searches = 0
        self.fail_save = 0

    def search(self, resolution):
        self.searches += 1
        return [{"id": record["id"], "resolution": resolution, "date": record["date"],
                 "winner": record["data"]["winner"], "exact": True, "similarity": 1.0}
                for record in self.records.values() if record["data"]["resolution"] == resolution]

    def save(self, record):
        if self.fail_save:
            self.fail_save -= 1
            raise OSError("private local disk detail")
        self.records[record["id"]] = copy.deepcopy(record)

    def get(self, session_id):
        return self.records.get(session_id)

    def close(self):
        pass


class PlannerClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.decisions = []
        self.pause_after = None
        self.failed_once = False
        self.fail_case = False
        self.fixed = False
        self.illegal = False

    async def choose_tool(self, state, tools, messages):
        if self.illegal:
            name = "run_arbitrary_shell"
        elif self.pause_after and len(state["completed"]) >= self.pause_after:
            name = "handoff_to_human"
            self.pause_after = None
        else:
            name = state["available_tools"][0]
        self.decisions.append(name)
        call = {"type": "tool_use", "id": "call_" + str(len(self.decisions)), "name": name,
                "input": {"explanation": "Next useful action"}}
        if name == "handoff_to_human":
            call["input"]["question"] = "Which school age group should the debate focus on?"
        return {"call": call, "content": [call]}

    async def call(self, prompt, schema, inputs, *, search=False):
        if schema is OpeningCase and "Negative" in prompt and not self.fixed:
            if self.fail_case:
                raise AgentError("Account needs attention")
            if not self.failed_once:
                self.failed_once = True
                raise AgentError("Temporary network issue", retryable=True)
        return await super().call(prompt, schema, inputs, search=search)


@pytest.mark.asyncio
async def test_tool_loop_recovers_and_saves_actual_completed_record(tmp_path):
    client, memory, journal = PlannerClient(), FakeMemory(), Journal(tmp_path)
    events = []
    memory.fail_save = 1
    await Coordinator(DebateRunner(client), memory, journal, retry_delay=0).run("Schools should ban phones.", events.append)
    assert events[-1]["type"] == "complete"
    assert client.decisions.count("build_affirmative") == 1
    assert client.decisions.count("build_negative") == 2
    assert client.decisions.count("save_debate") == 2
    session_id = next(event["session_id"] for event in events if event["type"] == "session")
    state = journal.get(session_id)
    assert state["status"] == "complete"
    assert memory.records[session_id]["data"]["questionFeedback"]["negative"] == "R2 evaded"
    assert memory.searches >= 1
    assert any(event.get("action") == "retry" for event in events)


@pytest.mark.asyncio
async def test_human_handoff_and_resume_skip_completed_work(tmp_path):
    client, memory, journal = PlannerClient(), FakeMemory(), Journal(tmp_path)
    client.fixed = True
    client.pause_after = 2
    controller = Coordinator(DebateRunner(client), memory, journal, retry_delay=0)
    events = []
    await controller.run("Schools should ban phones.", events.append)
    assert events[-1]["type"] == "handoff"
    session_id = events[-1]["session_id"]
    assert journal.get(session_id)["status"] == "needs_human"
    resumed = []
    await controller.run("Schools should ban phones.", resumed.append, session_id=session_id,
                         human_input="Focus on high school students.")
    assert resumed[-1]["type"] == "complete"
    assert client.decisions.count("build_affirmative") == client.decisions.count("build_negative") == 1
    assert journal.get(session_id)["human_input"] == "Focus on high school students."
    assert any(event["type"] == "replay_end" for event in resumed)


@pytest.mark.asyncio
async def test_nonrecoverable_errors_and_illegal_tools_handoff(tmp_path):
    for illegal in (False, True):
        client, memory = PlannerClient(), FakeMemory()
        client.fail_case, client.illegal = True, illegal
        events = []
        await Coordinator(DebateRunner(client), memory, Journal(tmp_path / str(illegal)), retry_delay=0).run("Schools should ban phones.", events.append)
        assert events[-1]["type"] == "handoff"
        assert not memory.records
        if illegal:
            assert len(client.calls) == 0
            assert len(client.decisions) == 3


def test_saved_match_prompts_before_any_model_call_and_force_new_works(tmp_path):
    import json
    from python_tests.test_memory import record
    memory, client = FakeMemory(), PlannerClient()
    saved = record()
    memory.save(saved)
    app = create_app(Settings(api_key="test"), DebateRunner(client), memory=memory,
                     journal=Journal(tmp_path), enable_coordinator=True)
    headers = {"origin": "http://localhost:8000", "content-type": "application/json"}
    with TestClient(app, base_url="http://localhost:8000") as http:
        check = http.post("/api/debates/check", headers=headers, json={"resolution": saved["data"]["resolution"]})
        assert check.json()["matches"][0]["id"] == saved["id"]
        response = http.post("/api/debate", headers=headers, json={"resolution": saved["data"]["resolution"]})
        assert response.status_code == 409
        assert not client.calls and not client.decisions
        assert http.get("/api/debates/" + saved["id"]).json()["complete"] is True
        fresh = http.post("/api/debate", headers=headers, json={"resolution": saved["data"]["resolution"], "force_new": True})
        events = [json.loads(line) for line in fresh.text.splitlines()]
        assert events[-1]["type"] == "complete"
        assert len(memory.records) == 2


@pytest.mark.asyncio
async def test_direct_controller_also_checks_memory_before_any_model_calls(tmp_path):
    from python_tests.test_memory import record
    client, memory = PlannerClient(), FakeMemory()
    saved = record()
    memory.save(saved)
    with pytest.raises(AgentError, match="previous debate"):
        await Coordinator(DebateRunner(client), memory, Journal(tmp_path)).run(saved["data"]["resolution"], lambda event: None)
    assert not client.calls and not client.decisions


@pytest.mark.asyncio
async def test_interruption_persists_valid_tool_history_and_resumes_without_repeating_case(tmp_path):
    import asyncio
    client, memory, journal = PlannerClient(), FakeMemory(), Journal(tmp_path)
    client.fixed = True
    normal = client.call
    blocked = asyncio.Event()
    waiting = True
    async def call(prompt, schema, inputs, *, search=False):
        if waiting and schema is OpeningCase and "Negative" in prompt:
            blocked.set()
            await asyncio.sleep(60)
        return await normal(prompt, schema, inputs, search=search)
    client.call = call
    coordinator = Coordinator(DebateRunner(client), memory, journal, retry_delay=0)
    events = []
    task = asyncio.create_task(coordinator.run("Schools should ban phones.", events.append))
    await blocked.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    session_id = next(event["session_id"] for event in events if event["type"] == "session")
    state = journal.get(session_id)
    assert state["status"] == "interrupted"
    assert state["messages"][-1]["content"][0]["type"] == "tool_result"
    waiting = False
    resumed = []
    await coordinator.run("Schools should ban phones.", resumed.append, session_id=session_id)
    assert resumed[-1]["type"] == "complete"
    assert client.decisions.count("build_affirmative") == 1


@pytest.mark.parametrize("side", ["Affirmative", "Negative"])
def test_human_debater_submits_both_turns_and_receives_judged_saved_debate(tmp_path, side):
    import json
    from forum.models import SideResponse, Verdict

    client, memory = PlannerClient(), FakeMemory()
    client.fixed = True
    journal = Journal(tmp_path)
    app = create_app(Settings(api_key="test"), DebateRunner(client), memory=memory,
                     journal=journal, enable_coordinator=True)
    origin = "http://localhost:8000"
    resolution = "Schools should ban smartphones during class."
    human = {"name": "Alex", "side": side}
    opening = ["Human claim", "Human evidence", "Second human claim", "Human reasoning"]
    answers = ["Human Q1", "Human Q2", "Human R1", "Human R2"]

    with TestClient(app, base_url=origin, headers={"origin": origin}) as http:
        def submit(**payload):
            response = http.post("/api/debate", json={"resolution": resolution, **payload})
            assert response.status_code == 200, response.text
            return [json.loads(line) for line in response.text.splitlines()]

        first = submit(debater=human)
        session_id = next(event["session_id"] for event in first if event["type"] == "session")
        assert first[-1]["phase"] == "opening"
        assert not client.calls
        invalid = http.post("/api/debate", json={"resolution": resolution, "session_id": session_id,
                            "submission": {"phase": "opening", "case": ["   "] * 4}})
        assert invalid.status_code == 400
        assert submit(session_id=session_id)[-1]["phase"] == "opening"

        second = submit(session_id=session_id, submission={"phase": "opening", "case": opening})
        assert [q["id"] for q in second[-1]["questions"]] == ["Q1", "Q2", "R1", "R2"]
        assert second[-1]["phase"] == "response"
        assert not memory.records
        assert submit(session_id=session_id, submission={"phase": "opening", "case": ["Stale"] * 4})[-1]["phase"] == "response"

        final = submit(session_id=session_id, submission={"phase": "response", "answers": answers,
                                                          "rebuttal": "Human rebuttal"})
        assert final[-1]["type"] == "complete"
        verdict = next(event for event in final if event["type"] == "verdict")
        assert verdict["why"] == "Reason"
        saved = http.get("/api/debates/" + session_id).json()["data"]
        assert saved["debater"] == human
        assert saved["a" if side == "Affirmative" else "n"] == opening

    human_side = side.lower()
    assert f"build_{human_side}" not in client.decisions
    assert f"answer_{human_side}" not in client.decisions
    opponent = next(inputs for schema, inputs, _ in client.calls if schema is SideResponse)
    assert human_side + "_answers" not in opponent
    judge = next(inputs for schema, inputs, _ in client.calls if schema is Verdict)
    assert judge[human_side] == opening
    assert [answer["answer"] for answer in judge[human_side + "_answers"]] == answers
    assert judge[human_side + "_rebuttal"] == "Human rebuttal"
