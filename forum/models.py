"""Validated contracts shared by the six agents and the browser event stream."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, model_validator

NonEmpty = Annotated[str, Field(min_length=1)]
Side = Literal["Affirmative", "Negative"]
Score = Annotated[int, Field(ge=0, le=25)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OpeningCase(Contract):
    case: list[NonEmpty] = Field(min_length=4, max_length=4,
        description="Exactly [claim1 title, claim1 reasoning, claim2 title, claim2 reasoning].")


class Question(Contract):
    question: NonEmpty
    purpose: NonEmpty


class Questions(Contract):
    affirmative: list[Question] = Field(min_length=2, max_length=2)
    negative: list[Question] = Field(min_length=2, max_length=2)


class Challenge(Contract):
    question: NonEmpty
    weakness: NonEmpty
    counterargument: NonEmpty


class Challenges(Contract):
    affirmative: list[Challenge] = Field(min_length=2, max_length=2)
    negative: list[Challenge] = Field(min_length=2, max_length=2)


class Answer(Contract):
    id: Literal["Q1", "Q2", "R1", "R2"]
    answer: NonEmpty


class SideResponse(Contract):
    answers: list[Answer] = Field(min_length=4, max_length=4)
    rebuttal: NonEmpty

    @model_validator(mode="after")
    def all_questions_answered(self) -> "SideResponse":
        if {answer.id for answer in self.answers} != {"Q1", "Q2", "R1", "R2"}:
            raise ValueError("Each assigned question must be answered exactly once")
        return self


class Source(Contract):
    url: str
    title: str


class Claim(Contract):
    claim: NonEmpty
    side: Literal["Affirmative", "Negative", "Both"]
    status: Literal["Supported", "Mixed evidence", "Needs a source"]
    explanation: NonEmpty
    source_urls: list[str]


class ResearchReview(Contract):
    claims: list[Claim] = Field(min_length=1, max_length=6)
    summary: NonEmpty


class QuestionFeedback(Contract):
    affirmative: NonEmpty
    negative: NonEmpty


class Verdict(Contract):
    winner: Literal["Affirmative", "Negative", "Tie"]
    why: NonEmpty
    improve: NonEmpty
    question_feedback: QuestionFeedback
    scores: list[Score] = Field(min_length=8, max_length=8,
        description="Each side: reasoning, evidence, rebuttal, question handling; 0–25 each.")

    @model_validator(mode="after")
    def winner_agrees_with_scores(self) -> "Verdict":
        affirmative, negative = sum(self.scores[:4]), sum(self.scores[4:])
        expected = "Tie" if affirmative == negative else "Affirmative" if affirmative > negative else "Negative"
        if self.winner != expected:
            raise ValueError("The verdict and score totals disagree")
        return self

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Argument = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
HumanAnswer = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1500)]


class HumanDebater(Contract):
    name: Name
    side: Side


class HumanOpening(Contract):
    phase: Literal["opening"]
    case: list[Argument] = Field(min_length=4, max_length=4)


class HumanResponse(Contract):
    phase: Literal["response"]
    answers: list[HumanAnswer] = Field(min_length=4, max_length=4)
    rebuttal: Argument


HUMAN_TURN = TypeAdapter(Annotated[HumanOpening | HumanResponse, Field(discriminator="phase")])
