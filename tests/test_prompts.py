"""Invariants for the system prompt shared by chat and agent model calls."""

from __future__ import annotations

from shared.prompts import TRIP_PLANNING_SYSTEM_PROMPT


def test_travel_history_check_runs_after_the_initial_itinerary() -> None:
    """The history search must not block planning: the plan is emitted first,
    then the planned places are checked against the user's past trips."""
    prompt = " ".join(TRIP_PLANNING_SYSTEM_PROMPT.split())
    assert "after the initial itinerary is out" in prompt


def test_prompt_keeps_the_labeling_rules() -> None:
    assert "Never fabricate" in TRIP_PLANNING_SYSTEM_PROMPT
    assert "Markdown" in TRIP_PLANNING_SYSTEM_PROMPT
