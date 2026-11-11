"""Orchestrate the six roles and emit browser-compatible incremental events."""
import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from .agents import (AffirmativeAgent, JudgeAgent, NegativeAgent, QuestionerAgent,
                     RebuttalAgent, ResearcherAgent)
from .claude import ClaudeClient


async def parallel(*coroutines: Coroutine) -> list[Any]:
    """Run siblings together, cancelling them all if one fails or is cancelled."""
    tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


class DebateRunner:
    def __init__(self, client: ClaudeClient):
        self.client = client
        self.affirmative = AffirmativeAgent(client)
        self.negative = NegativeAgent(client)
        self.questioner = QuestionerAgent(client)
        self.rebuttal = RebuttalAgent(client)
        self.researcher = ResearcherAgent(client)
        self.judge = JudgeAgent(client)

    async def run(self, resolution: str, emit: Callable[[dict], None]) -> None:
        async def opening(agent):
            emit({"type": "progress", "role": agent.side})
            result = await agent.build_case(resolution)
            emit({"type": "case", "role": agent.side, "case": result.value.case,
                  "sources": [source.model_dump() for source in result.sources]})
            return result.value.case

        affirmative, negative = await parallel(opening(self.affirmative), opening(self.negative))
        transcript = {"resolution": resolution, "affirmative": affirmative, "negative": negative}

        async def questioning():
            emit({"type": "progress", "role": "Questioner"})
            result = await self.questioner.ask(transcript)
            emit({"type": "questions", **result.model_dump()})
            return result

        async def challenging():
            emit({"type": "progress", "role": "Rebuttal"})
            result = await self.rebuttal.challenge(transcript)
            emit({"type": "challenges", **result.model_dump()})
            return result

        questions, challenges = await parallel(questioning(), challenging())

        async def responding(agent):
            emit({"type": "progress", "role": agent.side + " answers and rebuttal"})
            response, answers = await agent.respond(transcript, questions, challenges)
            emit({"type": "answers", "role": agent.side, "answers": answers})
            emit({"type": "rebuttal", "role": agent.side, "rebuttal": response.rebuttal})
            return response, answers

        (a_response, a_answers), (n_response, n_answers) = await parallel(
            responding(self.affirmative), responding(self.negative))
        full = {**transcript, "questions": questions.model_dump(),
                "challenges": challenges.model_dump(), "affirmative_answers": a_answers,
                "negative_answers": n_answers, "affirmative_rebuttal": a_response.rebuttal,
                "negative_rebuttal": n_response.rebuttal}
        emit({"type": "progress", "role": "Researcher"})
        research = await self.researcher.review(full)
        emit({"type": "research", **research.value.model_dump(),
              "sources": [source.model_dump() for source in research.sources]})
        emit({"type": "progress", "role": "Judge"})
        verdict = await self.judge.evaluate(full, research.value)
        emit({"type": "verdict", **verdict.model_dump(), "rubricVersion": 2})
        emit({"type": "complete", "model": self.client.settings.model})
