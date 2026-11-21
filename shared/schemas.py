"""Language-agnostic trip contracts as Pydantic models."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


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

    @field_validator("destination")
    @classmethod
    def destination_must_not_be_blank(cls, value: str) -> str:
        destination = value.strip()
        if not destination:
            raise ValueError("destination must not be blank")
        return destination


class EstimateTransportRequest(BaseModel):
    """Transport estimate request between two places."""

    destination: Optional[str] = None
    origin: Optional[str] = None
    from_place: str
    to_place: str
    days: Optional[int] = None
    budget: Optional[float] = None
    interests: list[str] = Field(default_factory=list)


class StayCandidate(BaseModel):
    name: str
    location: str
    nightly_cost: Optional[float] = None
    source_url: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    currency: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    amenities: list[str] = Field(default_factory=list)
    property_type: Optional[str] = None
    coordinates: Optional[dict[str, float]] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    cancellation_policy: Optional[str] = None


class TransportLeg(BaseModel):
    from_place: str
    to_place: str
    mode: str = "unknown"
    duration_minutes: Optional[float] = None
    cost: Optional[float] = None
    currency: Optional[str] = None
    source_url: Optional[str] = None
    notes: Optional[str] = None


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
    currency: Optional[str] = None
    used_travel_history: bool = False
    notes: list[str] = Field(default_factory=list)


class PlanReviseRequest(BaseModel):
    """Revise loop input: the previous plan plus the updated trip constraints."""

    itinerary: Itinerary
    request: TripRequest


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    conversation: list[dict[str, str]] = Field(default_factory=list)
    conversation_id: Optional[str] = None
    user_id: str = Field(default="local-user", min_length=1, max_length=200)
    request_id: Optional[str] = Field(default=None, max_length=100)
    plan_context: Optional[dict[str, Any]] = None
    custom: Optional[bool] = None


class ChatStopRequest(BaseModel):
    """Request to cooperatively stop an in-flight streaming chat turn."""

    request_id: str = Field(min_length=1, max_length=100)


class TripPlanUpdate(BaseModel):
    """User-edited budget fields persisted onto the latest trip-plan event."""

    mode: Optional[str] = Field(default=None, max_length=20)
    budget: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=12)
    budget_items: list[dict[str, Any]] = Field(default_factory=list)
    days: list[dict[str, Any]] = Field(default_factory=list)
    # Optional trip start (arrival) date, YYYY-MM-DD. An empty string clears it.
    start_date: Optional[str] = Field(default=None, max_length=10)


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

