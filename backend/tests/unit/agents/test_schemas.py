import pytest
from pydantic import ValidationError

from agentdrops.agents.schemas import ClarifyWithUser, StarterSuggestions


def test_clarify_with_user_accepts_two_to_five_suggestions_when_clarifying() -> None:
    for count in (2, 5):
        ClarifyWithUser(
            need_clarification=True,
            question="Which region?",
            verification="",
            suggestions=[f"Option {i}" for i in range(count)],
        )


def test_clarify_with_user_rejects_too_few_suggestions_when_clarifying() -> None:
    with pytest.raises(ValidationError):
        ClarifyWithUser(
            need_clarification=True,
            question="Which region?",
            verification="",
            suggestions=["Only one"],
        )


def test_clarify_with_user_rejects_too_many_suggestions_when_clarifying() -> None:
    with pytest.raises(ValidationError):
        ClarifyWithUser(
            need_clarification=True,
            question="Which region?",
            verification="",
            suggestions=[f"Option {i}" for i in range(6)],
        )


def test_clarify_with_user_accepts_empty_suggestions_when_not_clarifying() -> None:
    ClarifyWithUser(
        need_clarification=False, question="", verification="Got it.", suggestions=[]
    )


def test_clarify_with_user_rejects_suggestions_when_not_clarifying() -> None:
    with pytest.raises(ValidationError):
        ClarifyWithUser(
            need_clarification=False,
            question="",
            verification="Got it.",
            suggestions=["Shouldn't be here"],
        )


def test_starter_suggestions_accepts_exactly_three_prompts() -> None:
    StarterSuggestions(prompts=["A", "B", "C"])


def test_starter_suggestions_rejects_fewer_than_three_prompts() -> None:
    with pytest.raises(ValidationError):
        StarterSuggestions(prompts=["A", "B"])


def test_starter_suggestions_rejects_more_than_three_prompts() -> None:
    with pytest.raises(ValidationError):
        StarterSuggestions(prompts=["A", "B", "C", "D"])
