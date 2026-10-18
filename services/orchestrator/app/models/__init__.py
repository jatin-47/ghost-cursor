"""
Ghost Cursor Protocol Models
=============================
Pydantic v2 models for the Ghost Cursor wire protocol (version "1").

All request/response shapes, validation rules, and discrete-plan
constraints are defined here.
"""

from __future__ import annotations

import re
import uuid
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    model_validator,
    field_validator,
)

from .contracts import (
    HostedRunResponse,
    ToolCallRequest,
    ClarifyQuestion,
    validate_actions,
    validate_logical_id,
)

# ---------------------------------------------------------------------------
# Regex patterns for ID validation
# ---------------------------------------------------------------------------

LOGICAL_ID_RE = re.compile(r"^[a-zA-Z0-9_.:\-]+$")
SUBJECT_RE = re.compile(r"^[a-zA-Z0-9_.:@\-]+$")

PROTOCOL_VERSION = "1"


def _validate_logical_id(value: str, field_name: str = "id") -> str:
    """Validate a logical ID against the allowed pattern."""
    if not value or len(value) > 120:
        raise ValueError(f"{field_name} must be 1-120 characters")
    if not LOGICAL_ID_RE.match(value):
        raise ValueError(
            f"{field_name} must match ^[a-zA-Z0-9_.:-]+$, got '{value}'"
        )
    return value


def _validate_subject(value: str) -> str:
    """Validate a subject string against the allowed pattern."""
    if not value or len(value) > 120:
        raise ValueError("subject must be 1-120 characters")
    if not SUBJECT_RE.match(value):
        raise ValueError(
            f"subject must match ^[a-zA-Z0-9_.:@-]+$, got '{value}'"
        )
    return value


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RunStatus(str, Enum):
    """Possible statuses of a Ghost Cursor run."""

    AWAITING_TOOLS = "awaiting_tools"
    AWAITING_ACTIONS = "awaiting_actions"
    AWAITING_ANSWER = "awaiting_answer"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContinueKind(str, Enum):
    """The kind of continuation the client is sending."""

    TOOLS = "tools"
    ACTIONS = "actions"
    ACTION_RESULTS = "action_results"
    ANSWER = "answer"
    CANCEL = "cancel"


# ---------------------------------------------------------------------------
# Shared / Embedded Models
# ---------------------------------------------------------------------------


class GhostContext(BaseModel):
    """
    Context snapshot sent by the SDK describing the current UI state.
    """

    page: str = Field(..., min_length=1, max_length=2000, description="Current page identifier or URL")
    values: dict[str, str | int | float | bool] = Field(
        default_factory=dict,
        description="Key-value pairs of current UI state values",
    )
    availableTargets: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="List of interactable target element IDs (max 100)",
    )

    @field_validator("availableTargets")
    @classmethod
    def validate_targets(cls, v: list[str]) -> list[str]:
        """Each target must be a valid logical ID."""
        for target in v:
            _validate_logical_id(target, "availableTargets item")
        return v


class ToolDeclaration(BaseModel):
    """
    Declaration of a customer-backend tool that the agent can call.
    """

    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("parameters", "inputSchema", "input_schema"),
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_input_schema(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "parameters" not in data or not data["parameters"]:
                if "inputSchema" in data and data["inputSchema"]:
                    data["parameters"] = data["inputSchema"]
                elif "input_schema" in data and data["input_schema"]:
                    data["parameters"] = data["input_schema"]
        return data

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_logical_id(v, "tool name")


class ActionItem(BaseModel):
    """A single frontend action the agent wants to perform."""

    id: str = Field(..., min_length=1, max_length=120)
    tool: str = Field(..., min_length=1, max_length=120)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return _validate_logical_id(v, "action id")

    @field_validator("tool")
    @classmethod
    def validate_tool(cls, v: str) -> str:
        return _validate_logical_id(v, "action tool")


class QuestionItem(BaseModel):
    """A clarification question the agent wants to ask the user."""

    question: str = Field(..., min_length=1, max_length=1000)
    options: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Suggested answer options (max 10, each max 200 chars)",
    )

    @field_validator("options")
    @classmethod
    def validate_options(cls, v: list[str]) -> list[str]:
        for opt in v:
            if len(opt) > 200:
                raise ValueError(f"Option too long ({len(opt)} > 200 chars)")
        return v


class ToolCallItem(BaseModel):
    """A backend tool call the agent wants to invoke."""

    id: str = Field(..., min_length=1, max_length=120)
    tool: str = Field(..., min_length=1, max_length=120)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return _validate_logical_id(v, "toolCall id")

    @field_validator("tool")
    @classmethod
    def validate_tool(cls, v: str) -> str:
        return _validate_logical_id(v, "toolCall tool")


class ResultItem(BaseModel):
    """Result of executing an action or tool call, sent by the client."""

    id: str = Field(..., min_length=1, max_length=120)
    ok: bool = True
    output: Optional[Any] = None
    error: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def normalize_ok(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "ok" not in data and "success" in data:
                data["ok"] = bool(data["success"])
        return data

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return _validate_logical_id(v, "result id")

    @field_validator("output")
    @classmethod
    def truncate_output(cls, v: Any) -> Any:
        """Enforce 16,000-char limit on stringified output."""
        if v is not None:
            s = str(v)
            if len(s) > 16_000:
                raise ValueError(
                    f"Tool output too large ({len(s)} > 16000 chars)"
                )
        return v


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------


class ClientConfig(BaseModel):
    """
    Client-specific configuration overrides (optional).
    Allows frontends to customize the application name, type, and guardrail messaging.
    """

    appName: Optional[str] = Field(default=None, max_length=120, description="Display name of the host application")
    appType: Optional[str] = Field(default=None, max_length=120, description="Category/type (e.g. CRM, dashboard, store, banking)")
    outOfScopeMessage: Optional[str] = Field(default=None, max_length=1000, description="Custom out-of-scope refusal message")


class CreateRunRequest(BaseModel):
    """
    POST /v1/runs — create a new reasoning run.
    """

    protocolVersion: Literal["1"] = PROTOCOL_VERSION
    requestId: uuid.UUID = Field(..., description="Client-generated idempotency key")
    message: str = Field(..., min_length=1, max_length=6000, description="User's message")
    context: GhostContext
    brain: str = Field(
        ...,
        min_length=1,
        max_length=32_000,
        description="Brain document content (max 32000 chars)",
    )
    capabilities: list[str] = Field(default_factory=list)
    tools: list[ToolDeclaration] = Field(default_factory=list)
    clientConfig: Optional[ClientConfig] = Field(default=None, description="Optional client-level configuration overrides")


class ContinueRunRequest(BaseModel):
    """
    POST /v1/runs/{run_id}/continue — continue an existing run.
    """

    protocolVersion: Literal["1"] = PROTOCOL_VERSION
    eventId: uuid.UUID = Field(..., description="Unique event identifier for dedup")
    revision: int = Field(..., ge=0, description="Expected current revision (optimistic concurrency)")
    kind: ContinueKind
    results: list[ResultItem] = Field(
        default_factory=list,
        max_length=12,
        description="Results from tool calls / actions (max 12)",
    )
    answer: Optional[str] = Field(
        default=None,
        max_length=6000,
        description="User's answer to a clarification question",
    )
    context: Optional[GhostContext] = Field(
        default=None,
        description="Updated context snapshot (optional)",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_kind(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("kind") == "action_results":
                data["kind"] = "actions"
        return data

    @model_validator(mode="after")
    def validate_kind_payload(self) -> "ContinueRunRequest":
        """Validate that the payload matches the declared kind."""
        if self.kind in (ContinueKind.TOOLS, ContinueKind.ACTIONS, ContinueKind.ACTION_RESULTS):
            if not self.results:
                raise ValueError(
                    f"kind='{self.kind.value}' requires non-empty results"
                )
        if self.kind == ContinueKind.ANSWER:
            if self.answer is None:
                raise ValueError("kind='answer' requires an answer string")
        return self


# ---------------------------------------------------------------------------
# Response Model
# ---------------------------------------------------------------------------


class RunResponse(BaseModel):
    """
    Response body for run creation and continuation.
    """

    protocolVersion: Literal["1"] = PROTOCOL_VERSION
    runId: str = Field(..., description="Server-assigned run identifier")
    revision: int = Field(..., ge=0)
    status: RunStatus
    reply: Optional[str] = Field(default=None, description="Agent's text reply")
    questions: list[QuestionItem] = Field(default_factory=list)
    actions: list[ActionItem] = Field(default_factory=list)
    toolCalls: list[ToolCallItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_discrete_plan(self) -> "RunResponse":
        """
        Enforce discrete plan rule: at most ONE of questions, actions,
        or toolCalls may be non-empty in a single response.
        """
        non_empty = sum([
            bool(self.questions),
            bool(self.actions),
            bool(self.toolCalls),
        ])
        if non_empty > 1:
            raise ValueError(
                "Discrete plan violation: only ONE of questions, actions, "
                "or toolCalls may be non-empty in a single response"
            )
        return self


# ---------------------------------------------------------------------------
# Error Response
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """Standard error response body."""

    error: str
    code: str = "INTERNAL_ERROR"
    retryable: bool = False


# ---------------------------------------------------------------------------
# Suggestions Models (Contextual Quick Prompts)
# ---------------------------------------------------------------------------


class SuggestionsRequest(BaseModel):
    """
    POST /v1/suggestions — retrieve page-contextual suggested questions.
    """

    protocolVersion: Literal["1"] = PROTOCOL_VERSION
    page: str = Field(..., min_length=1, max_length=2000, description="Current page identifier")
    brain: str = Field(..., min_length=1, max_length=32_000, description="Brain context for current page")
    availableTargets: list[str] = Field(default_factory=list, max_length=100)
    count: int = Field(default=3, ge=1, le=5, description="Number of suggestions to generate (2-3 recommended)")
    clientConfig: Optional[ClientConfig] = Field(default=None)


class SuggestionsResponse(BaseModel):
    """
    Response containing suggested questions for the user.
    """

    protocolVersion: Literal["1"] = PROTOCOL_VERSION
    page: str
    suggestions: list[str] = Field(default_factory=list, max_length=5)

