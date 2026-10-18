"""Ghost Cursor Backend SDK — Gateway Proxy.

Main integration class that customers use to connect their backend
to Ghost Cursor Cloud. Handles brain loading, tool registration,
request proxying, and response filtering.
"""

import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import httpx

from .brain_loader import BrainLoader
from .models import PublicResponse

logger = logging.getLogger("ghost_cursor.proxy")

TOOL_OUTPUT_LIMIT = 16_000
REQUEST_TIMEOUT = 210  # seconds
MAX_TOOL_ROUNDS = 4
MAX_TOOL_CALLS_PER_ROUND = 4
CANARY = "GHOST_BRAIN_SERVER_ONLY_CANARY_2026"


class RegisteredTool:
    """A customer-registered read-only backend tool."""

    def __init__(self, name: str, description: str, schema: Any, handler: Callable, read_only: bool = True):
        self.name = name
        self.description = description
        self.schema = schema
        self.handler = handler
        self.read_only = read_only

    def to_declaration(self) -> dict:
        """Convert to tool declaration for Ghost Cursor Cloud."""
        schema_dict = {}
        if hasattr(self.schema, "model_json_schema"):
            schema_dict = self.schema.model_json_schema()
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": schema_dict,
            "readOnly": self.read_only,
        }


class GhostCursorBackend:
    """Main customer backend integration class.

    Usage:
        ghost = GhostCursorBackend(
            api_key="your-api-key",
            tenant_id="your_tenant",
            brain_dir="./brain",
        )

        @ghost.register_tool(name="lookup_order", description="...", schema=OrderQuery)
        async def lookup_order(params, context):
            return await db.query(...)

        # In your route handler:
        result = await ghost.handle_turn(payload, user_id, current_page)
    """

    def __init__(
        self,
        api_key: str,
        tenant_id: str,
        brain_dir: str = "./brain",
        service_url: str = "http://localhost:8080",
    ):
        self.api_key = api_key
        self.tenant_id = tenant_id
        self.brain_loader = BrainLoader(brain_dir)
        self.service_url = service_url.rstrip("/")
        self._tools: Dict[str, RegisteredTool] = {}
        self._chat_store = None
        self._http = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)

    def attach_chat_store(self, store) -> None:
        """Attach a SQLAlchemyChatStore for customer-owned chat history."""
        self._chat_store = store

    def register_tool(self, name: str, description: str, schema: Any, read_only: bool = True):
        """Decorator to register a read-only backend tool.

        Args:
            name: Unique tool identifier
            description: Human-readable description for the AI agent
            schema: Pydantic model class for input validation
            read_only: Must be True for baseline tools
        """
        if not read_only:
            raise ValueError("Only read-only tools are supported in the baseline.")

        def decorator(func):
            self._tools[name] = RegisteredTool(
                name=name,
                description=description,
                schema=schema,
                handler=func,
                read_only=read_only,
            )
            logger.info(f"Registered tool: {name}")
            return func

        return decorator

    async def handle_turn(self, payload: dict, user_id: str, current_page: str = "") -> dict:
        """Handle a user turn: load brain, proxy to Cloud, execute tools, filter response.

        Args:
            payload: Browser request payload (message, context, etc.)
            user_id: Authenticated user ID from customer session
            current_page: Current logical page for brain resolution

        Returns:
            Public-safe response envelope (no brain internals or tool details)
        """
        message = payload.get("message", "")
        context = payload.get("context", {})
        run_id = payload.get("runId")
        command = payload.get("command", "start")

        if command == "continue":
            return await self._handle_continue(payload, user_id)

        # --- Start a new run ---
        # 1. Load brain context
        brain_content = await self.brain_loader.load_context(current_page or context.get("page", ""))

        # 2. Build tool declarations
        tool_declarations = [t.to_declaration() for t in self._tools.values()]

        # 3. Create run request
        request_body = {
            "protocolVersion": "1",
            "requestId": str(uuid.uuid4()),
            "message": message[:6000],
            "context": context,
            "brain": brain_content[:32000],
            "capabilities": [],
            "tools": tool_declarations,
        }

        # 4. POST to Ghost Cursor Cloud
        response = await self._post_to_cloud("/v1/runs", request_body, user_id)

        # 5. Handle tool execution loop
        response = await self._tool_loop(response, user_id)

        # 6. Filter and return public response
        return self._filter_response(response)

    async def _handle_continue(self, payload: dict, user_id: str) -> dict:
        """Handle continuation (action results, answers, cancellation)."""
        run_id = payload.get("runId", "")
        raw_kind = payload.get("kind", "actions")
        if raw_kind in ("action_results", "actions"):
            kind = "actions"
        else:
            kind = raw_kind

        raw_results = payload.get("results", [])
        normalized_results = []
        for r in raw_results:
            if isinstance(r, dict):
                ok = r.get("ok") if "ok" in r else r.get("success", True)
                normalized_results.append({
                    "id": r.get("id"),
                    "ok": bool(ok),
                    "output": r.get("output"),
                    "error": r.get("error"),
                })

        body = {
            "protocolVersion": "1",
            "eventId": payload.get("eventId", str(uuid.uuid4())),
            "revision": payload.get("revision", 0),
            "kind": kind,
            "results": normalized_results,
        }
        if payload.get("answer"):
            body["answer"] = payload["answer"]
        if payload.get("context"):
            body["context"] = payload["context"]

        response = await self._post_to_cloud(f"/v1/runs/{run_id}/continue", body, user_id)
        response = await self._tool_loop(response, user_id)
        return self._filter_response(response)

    async def get_suggestions(
        self,
        current_page: str,
        available_targets: Optional[list] = None,
        count: int = 3,
        user_id: str = "anonymous",
    ) -> list[str]:
        """Fetch page-contextual suggested questions for quick prompt chips."""
        brain_content = await self.brain_loader.load_context(current_page)
        body = {
            "protocolVersion": "1",
            "page": current_page or "dashboard",
            "brain": brain_content[:32000],
            "availableTargets": available_targets or [],
            "count": count,
        }
        res = await self._post_to_cloud("/v1/suggestions", body, user_id)
        return res.get("suggestions", [])


    async def _post_to_cloud(self, path: str, body: dict, subject: str) -> dict:
        """Make authenticated request to Ghost Cursor Cloud."""
        url = f"{self.service_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Ghost-Subject": subject,
            "Content-Type": "application/json",
        }
        try:
            resp = await self._http.post(url, json=body, headers=headers)
            if resp.status_code >= 400:
                error_detail = resp.text[:500]
                logger.error(f"Cloud returned {resp.status_code}: {error_detail}")
                return {
                    "protocolVersion": "1",
                    "runId": "",
                    "revision": 0,
                    "status": "failed",
                    "reply": "I'm having trouble connecting to the AI service. Please try again.",
                    "questions": [],
                    "actions": [],
                    "toolCalls": [],
                }
            return resp.json()
        except Exception as e:
            logger.error(f"Cloud request failed: {e}")
            return {
                "protocolVersion": "1",
                "runId": "",
                "revision": 0,
                "status": "failed",
                "reply": "Connection to the AI service failed. Please try again.",
                "questions": [],
                "actions": [],
                "toolCalls": [],
            }


    async def _tool_loop(self, response: dict, user_id: str) -> dict:
        """Execute local tools if the Cloud returns awaiting_tools status."""
        rounds = 0
        while response.get("status") == "awaiting_tools" and rounds < MAX_TOOL_ROUNDS:
            tool_calls = response.get("toolCalls", [])
            if not tool_calls:
                break

            results = []
            for tc in tool_calls[:MAX_TOOL_CALLS_PER_ROUND]:
                tool_name = tc.get("tool", "")
                tool_params = tc.get("parameters", {})
                tool_id = tc.get("id", str(uuid.uuid4()))

                registered = self._tools.get(tool_name)
                if not registered:
                    results.append({"id": tool_id, "ok": False, "error": f"Unknown tool: {tool_name}"})
                    continue

                try:
                    # Validate and parse parameters
                    if registered.schema and hasattr(registered.schema, "model_validate"):
                        parsed_params = registered.schema.model_validate(tool_params)
                    else:
                        parsed_params = tool_params

                    # Execute tool with user context
                    output = await registered.handler(parsed_params, {"user_id": user_id})

                    # Bound output
                    output_str = json.dumps(output, default=str)
                    if len(output_str) > TOOL_OUTPUT_LIMIT:
                        output_str = output_str[:TOOL_OUTPUT_LIMIT]
                        output = json.loads(output_str + "}")

                    results.append({"id": tool_id, "ok": True, "output": output})
                except Exception as e:
                    logger.error(f"Tool {tool_name} failed: {e}")
                    results.append({"id": tool_id, "ok": False, "error": str(e)[:500]})

            # Continue the run with tool results
            run_id = response.get("runId", "")
            body = {
                "protocolVersion": "1",
                "eventId": str(uuid.uuid4()),
                "revision": response.get("revision", 0),
                "kind": "tools",
                "results": results,
            }
            response = await self._post_to_cloud(f"/v1/runs/{run_id}/continue", body, user_id)
            rounds += 1

        return response

    def _filter_response(self, response: dict) -> dict:
        """Filter response for browser safety — strip internals, check canary."""
        # Build public-safe envelope
        public = {
            "protocolVersion": response.get("protocolVersion", "1"),
            "runId": response.get("runId", ""),
            "revision": response.get("revision", 0),
            "status": response.get("status", "failed"),
            "reply": response.get("reply"),
            "questions": response.get("questions", []),
            "actions": response.get("actions", []),
        }

        # NEVER expose toolCalls to browser
        # NEVER expose awaiting_tools status to browser
        if public["status"] == "awaiting_tools":
            public["status"] = "failed"
            public["reply"] = "An internal error occurred."

        # Canary leak detection
        response_str = json.dumps(public, default=str)
        if CANARY in response_str:
            logger.critical("CANARY LEAK DETECTED — blocking response")
            return {
                "protocolVersion": "1",
                "runId": public.get("runId", ""),
                "revision": public.get("revision", 0),
                "status": "failed",
                "reply": "An internal error occurred. Please try again.",
                "questions": [],
                "actions": [],
            }

        return public

    async def close(self):
        """Cleanup HTTP client."""
        await self._http.aclose()

