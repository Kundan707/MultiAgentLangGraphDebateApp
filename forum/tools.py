"""Typed LangChain tools. Session state is captured by the application, not the model."""
import asyncio

from langchain.tools import tool

from .claude import AgentError


def memory_search_tool(memory):
    @tool
    async def search_debate_memory(resolution: str) -> list[dict]:
        """Find completed debates semantically related to a student's resolution."""
        return await asyncio.to_thread(memory.search, resolution)
    return search_debate_memory


def build_tools(coordinator, state: dict, emit):
    async def execute(name: str):
        if name not in coordinator.available(state):
            raise AgentError("This tool's prerequisites are not satisfied.")
        return await coordinator.execute(name, state, emit)

    @tool
    async def build_affirmative(explanation: str) -> dict:
        """Build the Affirmative opening case with web evidence. Run once per debate."""
        return await execute("build_affirmative")

    @tool
    async def build_negative(explanation: str) -> dict:
        """Build the Negative opening case with web evidence. Run once per debate."""
        return await execute("build_negative")

    @tool
    async def ask_questions(explanation: str) -> dict:
        """After both cases, ask Questioner questions for both sides."""
        return await execute("ask_questions")

    @tool
    async def challenge_cases(explanation: str) -> dict:
        """After both cases, identify Rebuttal challenges for both sides."""
        return await execute("challenge_cases")

    @tool
    async def answer_affirmative(explanation: str) -> dict:
        """After questions and challenges, answer and rebut as Affirmative."""
        return await execute("answer_affirmative")

    @tool
    async def answer_negative(explanation: str) -> dict:
        """After questions and challenges, answer and rebut as Negative."""
        return await execute("answer_negative")

    @tool
    async def review_sources(explanation: str) -> dict:
        """After both answers, independently audit empirical claims with web search."""
        return await execute("review_sources")

    @tool
    async def judge_debate(explanation: str) -> dict:
        """After the audit, judge all four criteria including question handling."""
        return await execute("judge_debate")

    @tool
    async def save_debate(explanation: str) -> dict:
        """After a valid verdict, persist the completed debate in vector memory."""
        return await execute("save_debate")

    @tool
    async def handoff_to_human(explanation: str, question: str) -> dict:
        """Pause for student clarification, account configuration, or repeated failure."""
        return {"reason": explanation, "question": question}

    return {action.name: action for action in (
        build_affirmative, build_negative, ask_questions, challenge_cases,
        answer_affirmative, answer_negative, review_sources, judge_debate,
        save_debate, handoff_to_human)}
