"""Language-agnostic trip contracts as Pydantic models."""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class TripRequest(BaseModel):
    """User-specified destination and dates (no hard-coded region requirement)."""

    destination: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    days: Optional[int] = Field(default=None, ge=1, description="Alternative to start/end dates")
    budget: Optional[float] = Field(default=None, ge=0)
    interests: list[str] = Field(default_factory=list)
    origin: Optional[str] = None  # optional; form default only
    avoid_visited: bool = False
    user_id: Optional[str] = None


class StayCandidate(BaseModel):
    name: str
    location: str
    nightly_cost: Optional[float] = None
    source_url: Optional[str] = None
    notes: Optional[str] = None


class TransportLeg(BaseModel):
    from_place: str
    to_place: str
    mode: str = "unknown"
    duration_minutes: Optional[float] = None
    cost: Optional[float] = None
    source_url: Optional[str] = None


class DayPlan(BaseModel):
    day_index: int
    stays: list[StayCandidate] = Field(default_factory=list)
    transports: list[TransportLeg] = Field(default_factory=list)
    pois: list[str] = Field(default_factory=list)
    estimated_cost: Optional[float] = None


class Itinerary(BaseModel):
    request: TripRequest
    days: list[DayPlan] = Field(default_factory=list)
    total_estimated_cost: Optional[float] = None
    used_travel_history: bool = False
    notes: list[str] = Field(default_factory=list)
