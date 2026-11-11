"""Claude tool-calling coordinator with durable checkpoints and bounded recovery."""
import asyncio
import json
from datetime import datetime, timezone
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from .agents import assigned_questions
from .claude import AgentError
from .memory import Journal
from .models import Challenges, Questions, ResearchReview
from .tools import build_tools, memory_search_tool
from pydantic import ValidationError
from langsmith import tracing_context


class FlowState(TypedDict, total=False):
    decisions: int
    next_node: str
    call: dict
    reason: str
    question: str


def apply_event(data: dict, event: dict):
    kind = event.get("type")
    if kind == "case":
        key = "a" if event["role"] == "Affirmative" else "n"
        data[key], data[key + "Sources"] = event["case"], event["sources"]
    elif kind in {"questions", "challenges"}:
        data[kind] = {side: event[side] for side in ("affirmative", "negative")}
    elif kind == "answers":
        data["aa" if event["role"] == "Affirmative" else "na"] = event["answers"]
    elif kind == "rebuttal":
        data["ar" if event["role"] == "Affirmative" else "nr"] = event["rebuttal"]
    elif kind == "research":
        data["review"] = {key: event[key] for key in ("claims", "summary", "sources")}
    elif kind == "verdict":
        data.update(winner=event["winner"], scores=event["scores"], why=event["why"],
                    improve=event["improve"], questionFeedback=event["question_feedback"], rubricVersion=2)


class Coordinator:
    def __init__(self, runner, memory, journal: Journal, *, retry_delay=0.5):
        self.runner, self.client = runner, runner.client
        self.memory, self.journal = memory, journal
        self.retry_delay = retry_delay

    def available(self, state):
        done = state["outputs"]
        result = []
        for name in ("build_affirmative", "build_negative"):
            if name not in done:
                result.append(name)
        if all(name in done for name in ("build_affirmative", "build_negative")):
            for name in ("ask_questions", "challenge_cases"):
                if name not in done:
                    result.append(name)
        if state.get("debater"):
            side = state["debater"]["side"].lower()
            result = [name for name in result if name != f"build_{side}"]
        if all(name in done for name in ("ask_questions", "challenge_cases")):
            for name in ("answer_affirmative", "answer_negative"):
                if name not in done and (not state.get("debater") or name != f"answer_{side}"):
                    result.append(name)
        if all(name in done for name in ("answer_affirmative", "answer_negative")) and "review_sources" not in done:
            result.append("review_sources")
        if "review_sources" in done and "judge_debate" not in done:
            result.append("judge_debate")
        if "judge_debate" in done and "save_debate" not in done:
            result.append("save_debate")
        return result + ["handoff_to_human"]

    def transcript(self, state):
        outputs = state["outputs"]
        data = {"resolution": state["resolution"], "human_context": state.get("human_input", ""),
                "affirmative": outputs["build_affirmative"]["case"],
                "negative": outputs["build_negative"]["case"]}
        for name, key in (("ask_questions", "questions"), ("challenge_cases", "challenges")):
            if name in outputs:
                data[key] = outputs[name]
        for name, side in (("answer_affirmative", "affirmative"), ("answer_negative", "negative")):
            if name in outputs:
                data[side + "_answers"] = outputs[name]["answers"]
                data[side + "_rebuttal"] = outputs[name]["rebuttal"]
        return data

    def record(self, state):
        data = {"resolution": state["resolution"]}
        if state.get("debater"):
            data["debater"] = state["debater"]
        for event in state["events"]:
            apply_event(data, event)
        return {"id": state["id"], "date": state["created_at"], "live": True,
                "complete": True, "model": self.client.settings.model,
                "notes": "", "data": data, "coordinatorId": state["id"]}

    async def execute(self, name, state, emit):
        def output(event):
            state["events"].append(event)
            emit(event)
        if name.startswith("build_"):
            agent = self.runner.affirmative if name == "build_affirmative" else self.runner.negative
            emit({"type": "progress", "role": agent.side})
            result = await agent.build_case(state["resolution"], human_context=state.get("human_input", ""))
            value = {**result.value.model_dump(), "sources": [s.model_dump() for s in result.sources]}
            output({"type": "case", "role": agent.side, **value})
            return value
        if name == "ask_questions":
            emit({"type": "progress", "role": "Questioner"})
            value = (await self.runner.questioner.ask(self.transcript(state))).model_dump()
            output({"type": "questions", **value})
            return value
        if name == "challenge_cases":
            emit({"type": "progress", "role": "Rebuttal"})
            value = (await self.runner.rebuttal.challenge(self.transcript(state))).model_dump()
            output({"type": "challenges", **value})
            return value
        if name.startswith("answer_"):
            agent = self.runner.affirmative if name == "answer_affirmative" else self.runner.negative
            emit({"type": "progress", "role": agent.side + " answers and rebuttal"})
            transcript = self.transcript(state)
            if state.get("debater"):
                human_side = state["debater"]["side"].lower()
                # Both debaters write their responses using the opening cases and questions.
                transcript.pop(human_side + "_answers", None)
                transcript.pop(human_side + "_rebuttal", None)
            response, answers = await agent.respond(transcript,
                Questions.model_validate(state["outputs"]["ask_questions"]),
                Challenges.model_validate(state["outputs"]["challenge_cases"]))
            output({"type": "answers", "role": agent.side, "answers": answers})
            output({"type": "rebuttal", "role": agent.side, "rebuttal": response.rebuttal})
            return {"answers": answers, "rebuttal": response.rebuttal}
        if name == "review_sources":
            emit({"type": "progress", "role": "Researcher"})
            result = await self.runner.researcher.review(self.transcript(state))
            value = {**result.value.model_dump(), "sources": [s.model_dump() for s in result.sources]}
            output({"type": "research", **value})
            return value
        if name == "judge_debate":
            emit({"type": "progress", "role": "Judge"})
            audit = {k: v for k, v in state["outputs"]["review_sources"].items() if k != "sources"}
            value = (await self.runner.judge.evaluate(self.transcript(state), ResearchReview.model_validate(audit))).model_dump()
            output({"type": "verdict", **value, "rubricVersion": 2})
            return value
        if name == "save_debate":
            await asyncio.to_thread(self.memory.save, self.record(state))
            return {"saved": True, "id": state["id"]}
        raise AgentError("Unknown coordinator tool.")

    def handoff(self, state, emit, reason, question):
        state["status"] = "needs_human"
        state["handoff"] = {"reason": reason, "question": question}
        self.journal.put(state)
        emit({"type": "handoff", "session_id": state["id"], **state["handoff"]})

    def human_turn(self, state, submission, emit):
        debater = state.get("debater")
        if not debater:
            return False
        role = debater["side"]
        side = role.lower()
        outputs = state["outputs"]
        opening_key, response_key = f"build_{side}", f"answer_{side}"
        if opening_key not in outputs:
            phase, questions = "opening", []
        elif response_key not in outputs and {"ask_questions", "challenge_cases"} <= outputs.keys():
            phase = "response"
            questions = assigned_questions(role, Questions.model_validate(outputs["ask_questions"]),
                                           Challenges.model_validate(outputs["challenge_cases"]))
        else:
            return False

        if not submission or submission.phase != phase:
            state["status"] = "needs_human"
            self.journal.put(state)
            emit({"type": "human_turn", "phase": phase, "questions": questions})
            return True

        if phase == "opening":
            value = {"case": submission.case, "sources": []}
            outputs[opening_key] = value
            events = [{"type": "case", "role": role, **value}]
        else:
            answers = [{**question, "answer": answer} for question, answer in zip(questions, submission.answers, strict=True)]
            outputs[response_key] = {"answers": answers, "rebuttal": submission.rebuttal}
            events = [{"type": "answers", "role": role, "answers": answers},
                      {"type": "rebuttal", "role": role, "rebuttal": submission.rebuttal}]
        state["events"].extend(events)
        self.journal.put(state)
        for event in events:
            emit(event)
        return False

    async def run(self, resolution, emit, *, session_id=None, human_input="", force_new=False, debater=None, submission=None):
        if not session_id:
            emit({"type": "coordinator", "action": "search_memory", "message": "Checking previous debates before starting agents."})
            try:
                with tracing_context(enabled=False):
                    matches = await memory_search_tool(self.memory).ainvoke({"resolution": resolution})
            except Exception:
                if not force_new:
                    raise AgentError("Debate memory could not be checked. Choose a fresh run explicitly or repair memory first.") from None
                matches = []
            if matches and not force_new:
                raise AgentError("A previous debate is available. Start again to choose the saved debate or a fresh run.")
        state = self.journal.get(session_id) if session_id else None
        if session_id and not state:
            raise AgentError("This saved checkpoint could not be found.")
        if state and state["resolution"] != resolution:
            raise AgentError("Resume the checkpoint with its original resolution.")
        if state and state["status"] == "complete":
            raise AgentError("This debate is complete. Open it from debate memory.")
        if state:
            emit({"type": "session", "session_id": state["id"], "debater": state.get("debater")})
            emit({"type": "replay_start"})
            for event in state["events"]:
                emit(event)
            emit({"type": "replay_end"})
            if human_input:
                state["human_input"] = (state.get("human_input", "") + "\n" + human_input).strip()
                state["messages"].append({"role": "user", "content": "Human clarification: " + human_input})
            state["attempts"] = {}
        else:
            state = {"id": str(uuid4()), "resolution": resolution,
                "created_at": datetime.now(timezone.utc).isoformat(), "status": "running",
                "outputs": {}, "events": [], "attempts": {}, "trace": [], "human_input": "",
                "messages": [{"role": "user", "content": json.dumps({"resolution": resolution,
                    "request": "Complete and save this debate. Memory was checked before this run."})}]}
            if debater:
                state["debater"] = debater
        state["status"] = "running"
        state.pop("handoff", None)
        self.journal.put(state)
        if not session_id:
            emit({"type": "session", "session_id": state["id"], "debater": state.get("debater")})
        graph = self.build_graph(state, emit, submission)
        try:
            with tracing_context(enabled=False):
                await graph.ainvoke({"decisions": 0}, config={"recursion_limit": 100})
        except asyncio.CancelledError:
            if state["messages"] and state["messages"][-1]["role"] == "assistant":
                pending = [block for block in state["messages"][-1]["content"] if block.get("type") == "tool_use"]
                state["messages"].append({"role": "user", "content": [{"type": "tool_result",
                    "tool_use_id": block["id"], "content": "Interrupted before a checkpoint; this tool may be retried.",
                    "is_error": True} for block in pending]})
            state["status"] = "interrupted"
            self.journal.put(state)
            raise

    def build_graph(self, state, emit, submission=None):
        """Route LangChain tools through LangGraph while retaining the session journal."""
        registry = build_tools(self, state, emit)

        async def human_turn(flow: FlowState):
            if flow["decisions"] >= 30:
                return {"next_node": "pause", "reason": "The coordinator reached its step budget.",
                        "question": "Review the completed steps and resume if you want to continue."}
            return {"next_node": END if self.human_turn(state, submission, emit) else "plan"}

        async def plan(flow: FlowState):
            decisions = flow["decisions"] + 1
            available = self.available(state)
            snapshot = {"available_tools": available, "completed": list(state["outputs"]),
                        "failures": state["attempts"], "max_attempts_per_tool": 3,
                        "resolution": state["resolution"], "human_input": state.get("human_input", ""),
                        "research_summary": state["outputs"].get("review_sources", {}).get("summary"),
                        "verdict": state["outputs"].get("judge_debate", {}).get("winner")}
            messages = state["messages"] + [{"role": "user", "content": "Current checkpoint: " + json.dumps(snapshot)}]
            try:
                choice = await self.client.choose_tool(snapshot, list(registry.values()), messages)
                call = choice["call"]
                name, arguments = call["name"], call.get("input", {})
                if name not in available or not isinstance(arguments, dict) or not isinstance(arguments.get("explanation"), str):
                    raise AgentError("The coordinator selected a tool outside the allowed next steps.", retryable=True)
                try:
                    registry[name].args_schema.model_validate(arguments)
                except ValidationError:
                    raise AgentError("The coordinator supplied invalid tool arguments.", retryable=True) from None
            except AgentError as error:
                count = state["attempts"].get("coordinator", 0) + 1
                state["attempts"]["coordinator"] = count
                self.journal.put(state)
                if error.retryable and count < 3:
                    emit({"type": "coordinator", "action": "retry", "message": "Retrying the coordinator's next-step decision."})
                    await asyncio.sleep(self.retry_delay * count)
                    return {"next_node": "human_turn", "decisions": decisions}
                return {"next_node": "pause", "decisions": decisions, "reason": str(error),
                        "question": "Please check API access or clarify the resolution, then resume."}
            state["messages"] = messages + [{"role": "assistant", "content": choice["content"]}]
            emit({"type": "coordinator", "action": name, "message": arguments["explanation"][:350]})
            state["trace"].append({"tool": name, "call_id": call["id"]})
            return {"next_node": name, "call": call, "decisions": decisions}

        async def run_tool(flow: FlowState):
            call = flow["call"]
            name, arguments = call["name"], call["input"]
            if name == "handoff_to_human":
                with tracing_context(enabled=False):
                    handoff = await registry[name].ainvoke(arguments)
                question = handoff["question"]
                state["messages"].append({"role": "user", "content": [{"type": "tool_result",
                    "tool_use_id": call["id"], "content": "Paused for a human response."}]})
                return {"next_node": "pause", "reason": arguments["explanation"], "question": question}
            try:
                # Roll back partial emissions if a tool fails before returning a checkpoint.
                before = len(state["events"])
                with tracing_context(enabled=False):
                    value = await registry[name].ainvoke(arguments)
                state["outputs"][name] = value
                result = {"ok": True, "tool": name, "completed": list(state["outputs"])}
            except Exception as error:
                del state["events"][before:]
                safe = str(error) if isinstance(error, AgentError) else "The local tool could not complete."
                count = state["attempts"].get(name, 0) + 1
                state["attempts"][name] = count
                retryable = error.retryable if isinstance(error, AgentError) else name == "save_debate"
                result = {"ok": False, "tool": name, "error": safe, "attempt": count}
                state["messages"].append({"role": "user", "content": [{"type": "tool_result",
                    "tool_use_id": call["id"], "content": json.dumps(result), "is_error": True}]})
                self.journal.put(state)
                if not retryable or count >= 3:
                    return {"next_node": "pause", "reason": safe,
                            "question": "Fix the reported issue or add clarification, then resume from this checkpoint."}
                emit({"type": "coordinator", "action": "retry", "message": f"Recovering from a failed {name.replace('_', ' ')} step (attempt {count}/3)."})
                await asyncio.sleep(self.retry_delay * count)
                return {"next_node": "human_turn"}
            state["messages"].append({"role": "user", "content": [{"type": "tool_result",
                "tool_use_id": call["id"], "content": json.dumps(result), "is_error": False}]})
            self.journal.put(state)
            if name == "save_debate":
                state["status"] = "complete"
                self.journal.put(state)
                emit({"type": "memory_saved", "id": state["id"]})
                emit({"type": "complete", "model": self.client.settings.model})
                return {"next_node": END}
            return {"next_node": "human_turn"}

        async def pause(flow: FlowState):
            self.handoff(state, emit, flow["reason"], flow["question"])
            return {}

        def next_node(flow: FlowState):
            return flow["next_node"]

        graph = StateGraph(FlowState)
        graph.add_node("human_turn", human_turn)
        graph.add_node("plan", plan)
        graph.add_node("pause", pause)
        graph.add_edge(START, "human_turn")
        graph.add_conditional_edges("human_turn", next_node, ["plan", "pause", END])
        graph.add_conditional_edges("plan", next_node, [*registry, "human_turn", "pause"])
        for name in registry:
            graph.add_node(name, run_tool)
            destinations = ["pause"] if name == "handoff_to_human" else ["human_turn", "pause"]
            if name == "save_debate":
                destinations.append(END)
            graph.add_conditional_edges(name, next_node, destinations)
        graph.add_edge("pause", END)
        return graph.compile()
