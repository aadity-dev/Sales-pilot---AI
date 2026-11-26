from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class LeadCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    company: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)


class ChatRequest(BaseModel):
    lead_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=5000)
    call_id: str | None = None
    language: str = "en-IN"


class CallCreate(BaseModel):
    lead_id: str
    language: str = "en-IN"


class AppointmentCreate(BaseModel):
    lead_id: str
    start_time: datetime
    duration_minutes: int = Field(default=30, ge=15, le=120)
    notes: str = Field(default="", max_length=1000)
    idempotency_key: str | None = Field(default=None, max_length=128)


class AppointmentCancel(BaseModel):
    reason: str = Field(default="Cancelled by user", max_length=300)


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2500)
    voice: str | None = Field(default=None, max_length=80)
    language: str = Field(default="en-IN", max_length=20)


class GeminiConfigRequest(BaseModel):
    api_key: str = Field(default="", max_length=256)
    model: str = Field(default="gemini-2.5-flash", min_length=1, max_length=80)


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
