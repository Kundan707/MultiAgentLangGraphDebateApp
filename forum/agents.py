"""The six debate roles. Edit these prompts to change each agent's behavior."""
from .claude import AgentResult, ClaudeClient
from .models import (Challenges, OpeningCase, Questions, ResearchReview,
                     SideResponse, Verdict)


def assigned_questions(side: str, questions: Questions, challenges: Challenges) -> list[dict]:
    return [
        {"id": f"{prefix}{i+1}", "question": question.question}
        for prefix, group in (("Q", questions), ("R", challenges))
        for i, question in enumerate(getattr(group, side.lower()))
    ]


class CaseAgent:
    side: str

    def __init__(self, client: ClaudeClient):
        self.client = client

    async def build_case(self, resolution: str, *, human_context: str = "") -> AgentResult[OpeningCase]:
        position = "for" if self.side == "Affirmative" else "against"
        return await self.client.call(
            f"You are the {self.side}. Build the strongest case {position} the resolution. "
            "Use web research. Return exactly four strings in case: claim 1 title, "
            "claim 1 reasoning with evidence and URLs, claim 2 title, claim 2 reasoning "
            "with evidence and URLs. Label unsupported claims clearly.",
            OpeningCase, {"resolution": resolution, "human_context": human_context}, search=True)

    async def respond(self, transcript: dict, questions: Questions,
                      challenges: Challenges) -> tuple[SideResponse, list[dict]]:
        assigned = assigned_questions(self.side, questions, challenges)
        result = await self.client.call(
            f"You are the {self.side}. Answer ALL FOUR assigned questions using IDs "
            "Q1, Q2, R1, R2 exactly once each. Be direct, address the criticism, and "
            "admit evidence gaps instead of inventing facts. Keep each answer under "
            "80 words. Then give a rebuttal under 150 words addressing the strongest "
            "opposing argument and the Rebuttal agent's challenges. The Judge scores "
            "answer quality separately.", SideResponse,
            {**transcript, "questions": questions.model_dump(),
             "challenges": challenges.model_dump(), "assigned_questions": assigned})
        answers = {answer.id: answer.answer for answer in result.value.answers}
        return result.value, [{**question, "answer": answers[question["id"]]} for question in assigned]


class AffirmativeAgent(CaseAgent):
    side = "Affirmative"


class NegativeAgent(CaseAgent):
    side = "Negative"


class QuestionerAgent:
    def __init__(self, client: ClaudeClient):
        self.client = client

    async def ask(self, transcript: dict) -> Questions:
        result = await self.client.call(
            "You are the Questioner. Ask exactly TWO fair, specific questions for "
            "the Affirmative and TWO for the Negative about this resolution and "
            "their actual opening cases. Probe definitions, causal reasoning, "
            "evidence, implementation, and tradeoffs. Explain each question's purpose. "
            "Keep questions answerable, neutral, and under 45 words. Do not invent facts.",
            Questions, transcript)
        return result.value


class RebuttalAgent:
    def __init__(self, client: ClaudeClient):
        self.client = client

    async def challenge(self, transcript: dict) -> Challenges:
        result = await self.client.call(
            "You are the Rebuttal agent. Identify exactly TWO specific weaknesses "
            "in EACH side's actual case. For each, state a weakness, a fair "
            "counterargument, and a pointed follow-up question that side must answer. "
            "Ground challenges in the resolution and transcript; distinguish "
            "uncertainty from facts and avoid invented evidence. Each field under 55 words.",
            Challenges, transcript)
        return result.value


class ResearcherAgent:
    def __init__(self, client: ClaudeClient):
        self.client = client

    async def review(self, transcript: dict) -> AgentResult[ResearchReview]:
        result = await self.client.call(
            "You are the Researcher. Audit between ONE and SIX of the most "
            "consequential empirical claims from the cases, answers, and rebuttals. "
            "Use web search. Cite source_urls from search results only. Explain "
            "limitations, mixed findings, and relevance. Mark claims Needs a source "
            "when evidence is absent. Do not rate value judgments as empirical facts.",
            ResearchReview, transcript, search=True)
        allowed = {source.url for source in result.sources}
        for claim in result.value.claims:
            claim.source_urls = [url for url in claim.source_urls if url in allowed]
            if not claim.source_urls:
                claim.status = "Needs a source"
        return result


class JudgeAgent:
    def __init__(self, client: ClaudeClient):
        self.client = client

    async def evaluate(self, transcript: dict, research: ResearchReview) -> Verdict:
        result = await self.client.call(
            "You are an impartial Judge. Evaluate only this actual debate and "
            "source audit. Apply the same standards to both sides regardless of authorship. "
            "Score FOUR criteria per side, each 0–25: reasoning and "
            "feasibility, evidence quality, rebuttal effectiveness, and question "
            "handling. Return exactly EIGHT scores in this order: affirmative "
            "reasoning, evidence, rebuttal, question handling; negative reasoning, "
            "evidence, rebuttal, question handling. Question handling rewards direct, "
            "relevant, supported answers and honest acknowledgment of uncertainty. "
            "Penalize evasion and unresolved challenges. In question_feedback, cite "
            "specific Q/R IDs and explain the effect on each side's score. Explain "
            "which arguments changed the result. Penalize unsupported factual claims. "
            "Winner must match score totals; ties are allowed.",
            Verdict, {**transcript, "research": research.model_dump()})
        return result.value
