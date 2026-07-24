from __future__ import annotations

from pydantic import BaseModel, Field


class OverrideRequest(BaseModel):
    override_score: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=5)


class DecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected|modified)$")
    reason: str | None = None


class AgentStartRequest(BaseModel):
    policy_id: str


class AgentMessageRequest(BaseModel):
    session_id: str
    policy_id: str
    message: str
