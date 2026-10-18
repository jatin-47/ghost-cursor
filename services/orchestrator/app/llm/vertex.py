"""
Vertex AI Base Client & Response Parsing
=========================================
Base client abstraction, error definitions, and response parsing for Vertex AI / ADK.
"""

from __future__ import annotations

import copy
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from ..agent import GhostAgent
from ..models.contracts import HostedRunResponse, ToolCallRequest, ClarifyQuestion

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Raised when an LLM provider encounters an error communicating with the model."""
    pass


def heuristic_summary(messages: List[Dict[str, str]]) -> Tuple[str, str]:
    """Heuristic fallback for conversation title and summary based on user requests."""
    user_msgs = [
        (m.get("text") or m.get("content") or "").strip()
        for m in messages
        if (m.get("role") or "").lower() == "user"
    ]
    user_msgs = [m for m in user_msgs if m]
    if not user_msgs:
        return "New Conversation", "New Conversation"

    words = user_msgs[0].split()
    title = " ".join(words[:6]) if words else "New Conversation"
    summary = "; ".join(user_msgs)[:200]
    return title, summary


class BaseVertexClient(ABC):
    """Abstract Vertex AI client interface."""

    @abstractmethod
    async def generate_content(
        self,
        agent: GhostAgent,
        user_message: str,
        run_context: Dict[str, Any],
        transcript: Optional[List[Dict[str, Any]]] = None,
    ) -> HostedRunResponse:
        pass

    async def summarize(self, messages: List[Dict[str, str]]) -> Tuple[str, str]:
        """Generate title and summary for a conversation transcript."""
        return heuristic_summary(messages)


def parse_model_response(
    response: Any,
    run_context: Dict[str, Any],
) -> HostedRunResponse:
    """Parse Gemini / ADK model response into HostedRunResponse using discrete plan rules."""
    run_id = str(run_context.get("run_id") or run_context.get("runId") or uuid.uuid4())
    revision = run_context.get("revision", 0)

    try:
        candidates = getattr(response, "candidates", None)
        if candidates:
            candidate = candidates[0]
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) if content else []

            function_calls = []
            text_parts = []

            for part in (parts or []):
                fc = getattr(part, "function_call", None)
                text = getattr(part, "text", None)
                if fc:
                    tool_name = getattr(fc, "name", None) or getattr(fc, "tool", "")
                    args = getattr(fc, "args", None)
                    if args is None:
                        args = getattr(fc, "parameters", {})
                    if hasattr(args, "model_dump"):
                        params = args.model_dump()
                    else:
                        params = dict(args) if args else {}
                    function_calls.append({
                        "id": getattr(fc, "id", None) or str(uuid.uuid4()),
                        "tool": tool_name,
                        "parameters": params,
                    })
                if text:
                    text_parts.append(text)

            reply = " ".join(text_parts) if text_parts else ""

            if function_calls:
                frontend_tools = {
                    "navigate",
                    "click",
                    "fill_input",
                    "toggle_switch",
                    "guided_tour",
                    "select_option",
                }
                clarification_tools = {"ask_clarification"}

                has_frontend = any(fc["tool"] in frontend_tools for fc in function_calls)
                has_clarification = any(fc["tool"] in clarification_tools for fc in function_calls)
                has_backend = any(
                    fc["tool"] not in frontend_tools and fc["tool"] not in clarification_tools
                    for fc in function_calls
                )

                if (has_frontend and has_backend) or (
                    has_clarification and (has_frontend or has_backend or len(function_calls) > 1)
                ):
                    logger.warning("Mixed function calls in model response")
                    return HostedRunResponse(
                        protocolVersion="1",
                        runId=run_id,
                        revision=revision,
                        status="failed",
                        reply="I couldn't produce a valid plan. Please rephrase.",
                    )

                if has_clarification:
                    clarify_call = next(fc for fc in function_calls if fc["tool"] in clarification_tools)
                    params = clarify_call["parameters"]
                    return HostedRunResponse(
                        protocolVersion="1",
                        runId=run_id,
                        revision=revision,
                        status="awaiting_answer",
                        reply=reply or params.get("question", "I need more information."),
                        questions=[
                            ClarifyQuestion(
                                question=params.get("question", ""),
                                options=params.get("options", []),
                            )
                        ],
                    )
                elif has_frontend:
                    actions = []
                    for idx, fc in enumerate(function_calls):
                        if fc["tool"] in frontend_tools:
                            act_dict = {
                                "type": fc["tool"],
                                "tool": fc["tool"],
                                "id": f"act_{idx + 1}",
                                **fc["parameters"],
                            }
                            actions.append(act_dict)
                    return HostedRunResponse(
                        protocolVersion="1",
                        runId=run_id,
                        revision=revision,
                        status="awaiting_actions",
                        reply=reply or "I'll help you with that. Here's what I plan to do:",
                        actions=actions,
                    )
                elif has_backend:
                    tool_calls = [
                        ToolCallRequest(
                            id=fc["id"] or f"tc_{i+1}",
                            tool=fc["tool"],
                            parameters=fc["parameters"],
                        )
                        for i, fc in enumerate(function_calls)
                        if fc["tool"] not in frontend_tools and fc["tool"] not in clarification_tools
                    ]
                    return HostedRunResponse(
                        protocolVersion="1",
                        runId=run_id,
                        revision=revision,
                        status="awaiting_tools",
                        reply=reply or "Let me look that up for you...",
                        toolCalls=tool_calls,
                    )

            # Plain text response
            return HostedRunResponse(
                protocolVersion="1",
                runId=run_id,
                revision=revision,
                status="completed",
                reply=reply or "I'm not sure how to help with that.",
            )

    except Exception as e:
        logger.error(f"Failed to parse model response: {e}")

    return HostedRunResponse(
        protocolVersion="1",
        runId=run_id,
        revision=revision,
        status="failed",
        reply="I encountered an error processing the response.",
    )

