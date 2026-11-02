"""Language-agnostic trip contracts as Pydantic models."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

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
    currency: Optional[str] = None
    rating: Optional[float] = None
    amenities: list[str] = Field(default_factory=list)


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


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    conversation: list[dict[str, str]] = Field(default_factory=list)
    conversation_id: Optional[str] = None
    user_id: str = Field(default="local-user", min_length=1, max_length=200)


class ChatEvent(BaseModel):
    type: str
    label: str
    detail: Optional[str] = None
    status: str = "completed"
    data: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    text: str
    reasoning: str = ""
    stub: bool = False
    model: str
    conversation_id: str
    events: list[ChatEvent] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    id: str
    title: str
    updated_at: str


class ConversationResponse(ConversationSummary):
    messages: list[dict[str, str]] = Field(default_factory=list)
    events: list[ChatEvent] = Field(default_factory=list)


class ModelSettingsUpdate(BaseModel):
    endpoint_url: str = Field(default="", max_length=2000)
    model: str = Field(min_length=1, max_length=200)
    api_key: Optional[str] = Field(default=None, max_length=2000)


class ModelSettingsResponse(BaseModel):
    endpoint_url: str
    model: str
    api_key_configured: bool


class WebSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class TravelHistoryEntry(BaseModel):
    id: int
    user_id: str
    country: Optional[str] = None
    city: Optional[str] = None
    location: str
    visited_at: str


class TravelHistoryCreate(BaseModel):
    user_id: str = Field(default="local-user", min_length=1, max_length=200)
    country: Optional[str] = Field(default=None, max_length=120)
    city: Optional[str] = Field(default=None, max_length=120)
    location: str = Field(min_length=1, max_length=240)

