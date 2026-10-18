"""
Gemini Provider on Vertex AI
=============================
Production Gemini 2.0 provider using the modern google-genai SDK with Vertex AI.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from ..agent import GhostAgent
from ..models.contracts import HostedRunResponse
from .vertex import BaseVertexClient, ProviderError, parse_model_response

logger = logging.getLogger(__name__)


def _is_clean_start(turn: Dict[str, Any]) -> bool:
    return turn.get("role") == "user" and not any("function_response" in p for p in turn.get("parts", []))


def prune_transcript(transcript: List[Dict[str, Any]], max_parts: int = 40) -> List[Dict[str, Any]]:
    """
    Keep at most the last max_parts parts across turns,
    ensuring the first message has role 'user'.
    """
    while transcript and sum(len(t.get("parts", [])) for t in transcript) > max_parts:
        if len(transcript) == 1:
            transcript[0]["parts"] = transcript[0]["parts"][-max_parts:]
            break
        transcript.pop(0)

    while transcript and not _is_clean_start(transcript[0]):
        transcript.pop(0)

    return transcript


class GeminiProvider(BaseVertexClient):
    """Production Gemini 2.0 provider on Vertex AI via google-genai SDK."""

    def __init__(
        self,
        project: Optional[str] = None,
        location: str = "us-central1",
        model: str = "gemini-2.0-flash",
    ):
        self.project = project
        self.location = location
        self.model = model

    def _parse_response(self, response: Any, run_context: Dict[str, Any]) -> HostedRunResponse:
        return parse_model_response(response, run_context)

    async def generate_content(
        self,
        agent: GhostAgent,
        user_message: str,
        run_context: Dict[str, Any],
        transcript: Optional[List[Dict[str, Any]]] = None,
    ) -> HostedRunResponse:
        from google import genai
        from google.genai import types

        client = genai.Client(vertexai=True, project=self.project, location=self.location)
        if transcript is None:
            transcript = run_context.get("transcript", [])

        func_decls = []
        for tool in agent.tools:
            t_name = tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", "")
            t_desc = tool.get("description", "") if isinstance(tool, dict) else getattr(tool, "description", "")
            t_params = tool.get("parameters", {}) if isinstance(tool, dict) else getattr(tool, "parameters", {})
            func_decls.append(
                types.FunctionDeclaration(
                    name=t_name,
                    description=t_desc,
                    parameters=t_params,
                )
            )

        tools = [types.Tool(function_declarations=func_decls)] if func_decls else None
        instruction = agent.instruction if isinstance(agent.instruction, str) else agent.instruction(None)

        config = types.GenerateContentConfig(
            system_instruction=instruction,
            tools=tools,
            temperature=0.2,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        try:
            response = await client.aio.models.generate_content(
                model=self.model,
                contents=transcript,
                config=config,
            )
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            raise ProviderError(f"Gemini provider error: {e}") from e

        model_parts = []
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) if content else []
            for part in (parts or []):
                fc = getattr(part, "function_call", None)
                text = getattr(part, "text", None)
                if fc:
                    fc_name = getattr(fc, "name", None) or getattr(fc, "tool", "")
                    fc_args = getattr(fc, "args", None)
                    if fc_args is None:
                        fc_args = {}
                    elif hasattr(fc_args, "model_dump"):
                        fc_args = fc_args.model_dump()
                    else:
                        fc_args = dict(fc_args)
                    model_parts.append({
                        "function_call": {
                            "name": fc_name,
                            "args": fc_args,
                        }
                    })
                if text:
                    model_parts.append({"text": text})

        if model_parts and transcript is not None:
            transcript.append({
                "role": "model",
                "parts": model_parts,
            })
            prune_transcript(transcript, max_parts=40)

        return parse_model_response(response, run_context)

    async def summarize(self, messages: List[Dict[str, str]]) -> Tuple[str, str]:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(vertexai=True, project=self.project, location=self.location)
            convo_text = "\n".join([f"{m.get('role', 'user')}: {m.get('text', '')}" for m in messages])
            prompt = (
                f"Conversation:\n{convo_text}\n\n"
                'Return JSON {"title": <=6 words, "summary": <=2 sentences}:'
            )
            config = types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            )
            response = await client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )
            text = getattr(response, "text", "") or ""
            data = json.loads(text)
            if isinstance(data, dict):
                title = data.get("title")
                summary = data.get("summary")
                if (
                    isinstance(title, str)
                    and isinstance(summary, str)
                    and len(title) <= 60
                    and len(summary) <= 300
                ):
                    return title.strip(), summary.strip()
        except Exception as e:
            logger.warning("Gemini summarization failed, falling back to heuristic: %s", type(e).__name__)

        return await super().summarize(messages)

