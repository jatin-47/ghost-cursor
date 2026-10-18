"""
Ghost Cursor Canonical Contracts & Action Validation
====================================================
Data contracts and strict schema validation for frontend actions
and hosted API responses.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import re
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator, field_validator

logger = logging.getLogger(__name__)

ProtocolVersion = Literal["1"]
RunStatusLiteral = Literal[
    "awaiting_tools",
    "awaiting_actions",
    "awaiting_answer",
    "completed",
    "failed",
    "cancelled",
]

MAX_MESSAGE_LENGTH = 6000
MAX_BRAIN_LENGTH = 32000
MAX_OPTIONS = 10
MAX_SCALAR_LENGTH = 1000

LOGICAL_ID_RE = re.compile(r"^[a-zA-Z0-9_.:\-]+$")


def validate_logical_id(value: str) -> str:
    """Validate a logical target ID against allowed characters."""
    if not value or not isinstance(value, str):
        raise ValueError("Logical ID must be a non-empty string")
    if len(value) > 120:
        raise ValueError("Logical ID must be <= 120 characters")
    if not LOGICAL_ID_RE.match(value):
        raise ValueError(f"Logical ID contains invalid characters: {value}")
    return value


class ClarifyQuestion(BaseModel):
    """Clarifying question for the user."""
    question: str = Field(..., min_length=1, max_length=1000)
    options: List[str] = Field(default_factory=list)

    @field_validator("options")
    @classmethod
    def validate_options(cls, v: List[str]) -> List[str]:
        if len(v) > MAX_OPTIONS:
            raise ValueError(f"At most {MAX_OPTIONS} options")
        for opt in v:
            if len(opt) > 200:
                raise ValueError("Option must be at most 200 characters")
        return v


class ToolCallRequest(BaseModel):
    """Backend tool call request from the agent."""
    id: str
    tool: str
    parameters: Dict[str, Any] = Field(default_factory=dict)


class HostedRunResponse(BaseModel):
    """Response from hosted API / ADK provider."""
    protocolVersion: ProtocolVersion = "1"
    runId: str
    revision: int = 0
    status: str
    reply: str
    questions: Optional[List[ClarifyQuestion]] = None
    actions: Optional[List[Dict[str, Any]]] = None
    toolCalls: Optional[List[ToolCallRequest]] = None

    @model_validator(mode="after")
    def validate_discrete_plan(self):
        """Only ONE of questions, actions, or toolCalls may be non-empty."""
        non_empty = 0
        if self.questions and len(self.questions) > 0:
            non_empty += 1
        if self.actions and len(self.actions) > 0:
            non_empty += 1
        if self.toolCalls and len(self.toolCalls) > 0:
            non_empty += 1
        if non_empty > 1:
            raise ValueError("Only ONE of questions, actions, or toolCalls may be non-empty")
        return self


ACTION_TYPES = {
    "navigate",
    "click",
    "fill_input",
    "select_option",
    "toggle_switch",
    "guided_tour",
}


def validate_actions(actions: Any) -> List[Dict[str, Any]]:
    """
    Validate frontend action plan against strict schema.
    Raises ValueError on any violation.
    """
    if actions is None:
        return []
    if not isinstance(actions, list):
        raise ValueError("Actions must be a list")
    if len(actions) > 12:
        raise ValueError("A plan can have at most 12 actions")

    validated: List[Dict[str, Any]] = []
    for idx, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ValueError(f"Action at index {idx} must be a dictionary")

        action_type = action.get("type") or action.get("tool")
        if not action_type or not isinstance(action_type, str):
            raise ValueError(f"Action at index {idx} missing valid 'type'")

        allowed_keys = {"type", "tool", "id", "explanation"}

        if action_type == "navigate":
            allowed_keys.add("target_page")
            allowed_keys.add("path")
            target_page = action.get("target_page") or action.get("path")
            if not target_page or not isinstance(target_page, str):
                raise ValueError("navigate target_page must be a non-empty string")
            if len(target_page) > 200:
                raise ValueError("navigate target_page must be <= 200 characters")
            if ("://" in target_page or target_page.startswith("//")
                    or re.match(r"^[a-z][a-z0-9+.-]*:", target_page, re.IGNORECASE)):
                raise ValueError("navigate target_page must be an in-app page, not a URL")

        elif action_type == "click":
            allowed_keys.add("target_id")
            if "target_id" not in action:
                raise ValueError("click action missing 'target_id'")
            target_id = action["target_id"]
            if not isinstance(target_id, str):
                raise ValueError("click target_id must be a string")
            validate_logical_id(target_id)

        elif action_type == "fill_input":
            allowed_keys.add("target_id")
            allowed_keys.add("value")
            if "target_id" not in action:
                raise ValueError("fill_input action missing 'target_id'")
            target_id = action["target_id"]
            if not isinstance(target_id, str):
                raise ValueError("fill_input target_id must be a string")
            validate_logical_id(target_id)
            if "value" not in action:
                raise ValueError("fill_input action missing 'value'")
            value = action["value"]
            if isinstance(value, (list, dict, set, tuple)) or not isinstance(value, (str, int, float, bool)):
                raise ValueError("fill_input value must be a scalar")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("fill_input float value must be finite")
            if isinstance(value, str) and len(value) > MAX_SCALAR_LENGTH:
                raise ValueError(f"fill_input string value exceeds {MAX_SCALAR_LENGTH} characters")

        elif action_type == "select_option":
            allowed_keys.add("target_id")
            allowed_keys.add("option")
            if "target_id" not in action:
                raise ValueError("select_option action missing 'target_id'")
            target_id = action["target_id"]
            if not isinstance(target_id, str):
                raise ValueError("select_option target_id must be a string")
            validate_logical_id(target_id)
            if "option" not in action:
                raise ValueError("select_option action missing 'option'")
            option = action["option"]
            if not isinstance(option, str) or not option or len(option) > 200:
                raise ValueError("select_option option must be a non-empty string <= 200 characters")

        elif action_type == "toggle_switch":
            allowed_keys.add("target_id")
            allowed_keys.add("state")
            if "target_id" not in action:
                raise ValueError("toggle_switch action missing 'target_id'")
            target_id = action["target_id"]
            if not isinstance(target_id, str):
                raise ValueError("toggle_switch target_id must be a string")
            validate_logical_id(target_id)
            if "state" not in action:
                raise ValueError("toggle_switch action missing 'state'")
            state = action["state"]
            if not isinstance(state, bool):
                raise ValueError("toggle_switch state must be a boolean")

        elif action_type == "guided_tour":
            allowed_keys.add("steps")
            if "steps" not in action:
                raise ValueError("guided_tour action missing 'steps'")
            steps = action["steps"]
            if not isinstance(steps, list) or not (1 <= len(steps) <= 10):
                raise ValueError("guided_tour steps must be a list of 1 to 10 steps")
            for s_idx, step in enumerate(steps):
                if not isinstance(step, dict):
                    raise ValueError(f"guided_tour step at index {s_idx} must be a dict")
                if "target_id" not in step:
                    raise ValueError(f"guided_tour step at index {s_idx} missing 'target_id'")
                s_tid = step["target_id"]
                if not isinstance(s_tid, str):
                    raise ValueError("guided_tour step target_id must be a string")
                validate_logical_id(s_tid)
                if "message" not in step:
                    raise ValueError(f"guided_tour step at index {s_idx} missing 'message'")
                msg = step["message"]
                if not isinstance(msg, str) or not msg or len(msg) > 500:
                    raise ValueError("guided_tour step message must be a string <= 500 characters")
        else:
            raise ValueError(f"Unknown action type: {action_type}")

        if "explanation" in action:
            exp = action["explanation"]
            if exp is not None and (not isinstance(exp, str) or len(exp) > 500):
                raise ValueError("explanation must be a string <= 500 characters")

        if "id" in action:
            act_id = action["id"]
            if act_id is not None and (not isinstance(act_id, str) or len(act_id) > 120):
                raise ValueError("action id must be a string <= 120 characters")

        # Normalize action dict so 'type' is always present
        normalized_action = dict(action)
        normalized_action["type"] = action_type
        validated.append(normalized_action)

    return validated

