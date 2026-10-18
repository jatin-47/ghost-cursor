"""Run State Machine — manages multi-turn AI run lifecycle.

Handles creation, deduplication, continuation, revision tracking,
expiry, and optimistic concurrency for agent runs.
"""

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from .models import CreateRunRequest, ContinueRunRequest, RunResponse
from .storage.base import RunStore


RUN_EXPIRY_MINUTES = 30
MAX_CONTINUATION_TURNS = 12


@dataclass
class RunState:
    """Internal state for a single agent run."""
    id: str
    tenant: str
    subject: str
    request_id: str
    status: str = "pending"
    revision: int = -1  # -1 = pending initial planning
    plan: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    original_message: str = ""
    brain: str = ""
    context: dict = field(default_factory=dict)
    tools: list = field(default_factory=list)
    turn_count: int = 0
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    start_digest: str = ""
    latest_event_id: Optional[str] = None
    latest_event_digest: Optional[str] = None
    latest_event_result: Optional[dict] = None

    def __post_init__(self):
        if self.expires_at == 0.0:
            self.expires_at = self.created_at + (RUN_EXPIRY_MINUTES * 60)

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed", "cancelled")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "tenant": self.tenant, "subject": self.subject,
            "request_id": self.request_id, "status": self.status,
            "revision": self.revision, "plan": self.plan,
            "history": self.history[-20:],  # bounded history
            "original_message": self.original_message,
            "brain": self.brain, "context": self.context,
            "tools": self.tools, "turn_count": self.turn_count,
            "created_at": self.created_at, "expires_at": self.expires_at,
            "start_digest": self.start_digest,
            "latest_event_id": self.latest_event_id,
            "latest_event_digest": self.latest_event_digest,
            "latest_event_result": self.latest_event_result,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RunState":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _digest(data: Any) -> str:
    """Create a stable SHA-256 digest of JSON-serializable data."""
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16]


class RunManager:
    """Manages the lifecycle of agent runs."""

    def __init__(self, store: RunStore, provider):
        self.store = store
        self.provider = provider

    async def create_run(self, tenant: str, subject: str, req: CreateRunRequest) -> RunResponse:
        """Create a new run or return existing for deduplication."""
        request_id = str(req.requestId)
        start_digest = _digest({"message": req.message, "context": req.context.model_dump() if req.context else {}})

        # Check for existing run with same request_id (deduplication)
        existing = await self.store.get_run_by_request_id(tenant, subject, request_id)
        if existing:
            run = RunState.from_dict(existing)
            if run.start_digest == start_digest:
                # Identical request — return existing result
                return self._build_response(run)
            else:
                # Changed payload under same requestId
                raise HTTPException(status_code=409, detail="Conflict: changed payload under same requestId.")

        # Create new run
        run_id = str(uuid.uuid4())
        ctx_dict = req.context.model_dump() if req.context else {}
        ctx_dict.setdefault("run_id", run_id)
        ctx_dict.setdefault("subject", subject)
        run = RunState(
            id=run_id,
            tenant=tenant,
            subject=subject,
            request_id=request_id,
            original_message=req.message,
            brain=req.brain or "",
            context=ctx_dict,
            tools=[t.model_dump() if hasattr(t, 'model_dump') else t for t in (req.tools or [])],
            start_digest=start_digest,
        )

        # Run initial planning
        try:
            from .tenant_config import get_tenant_config, extract_brain_config
            # Approach C: Extract client configuration directly from customer's Brain document
            brain_cfg = extract_brain_config(run.brain)
            req_overrides = req.clientConfig.model_dump(exclude_none=True) if getattr(req, "clientConfig", None) else {}
            effective_config = {**brain_cfg, **req_overrides}
            tenant_cfg = get_tenant_config(tenant, effective_config)


            agent_result = await self.provider.generate(
                message=req.message,
                context=run.context,
                brain=run.brain,
                targets=run.context.get("availableTargets", []),
                tools=run.tools,
                client_config=tenant_cfg,
            )
            run.plan = agent_result
            run.status = agent_result.get("status", "completed")
            run.revision = 0
            run.history.append({"role": "user", "content": req.message})
            if agent_result.get("reply"):
                run.history.append({"role": "assistant", "content": agent_result["reply"]})
        except Exception as e:
            run.status = "failed"
            run.revision = 0
            run.plan = {"reply": f"I encountered an error processing your request. Please try again.", "actions": [], "questions": [], "toolCalls": []}

        await self.store.save_run(run.to_dict())
        return self._build_response(run)

    async def continue_run(
        self, run_id: str, tenant: str, subject: str, req: ContinueRunRequest
    ) -> RunResponse:
        """Continue an existing run with results, answers, or cancellation."""
        run_data = await self.store.get_run(run_id, tenant, subject)
        if not run_data:
            raise HTTPException(status_code=404, detail="Run not found.")

        run = RunState.from_dict(run_data)

        # Check expiry
        if run.is_expired:
            raise HTTPException(status_code=410, detail="Run has expired.")

        # Check terminal state
        if run.is_terminal:
            raise HTTPException(status_code=409, detail=f"Run is already {run.status}.")

        # Check revision match
        if req.revision != run.revision:
            raise HTTPException(status_code=409, detail=f"Revision mismatch: expected {run.revision}, got {req.revision}.")

        # Check turn limit
        if run.turn_count >= MAX_CONTINUATION_TURNS:
            if req.kind != "cancel":
                raise HTTPException(status_code=409, detail="Turn limit reached. Only cancellation is permitted.")

        # Identical event replay
        event_id = str(req.eventId)
        event_digest = _digest({"kind": req.kind, "results": [r.model_dump() for r in (req.results or [])], "answer": req.answer})
        if run.latest_event_id == event_id:
            if run.latest_event_digest == event_digest:
                return self._build_response(run)
            else:
                raise HTTPException(status_code=409, detail="Conflicting replay: same eventId with different payload.")

        # Validate continuation kind matches expected status
        expected_kinds = {
            "awaiting_actions": ["actions", "action_results", "cancel"],
            "awaiting_answer": ["answer", "cancel"],
            "awaiting_tools": ["tools", "cancel"],
        }
        allowed = expected_kinds.get(run.status, ["cancel"])
        if req.kind not in allowed:
            raise HTTPException(
                status_code=409,
                detail=f"Invalid continuation kind '{req.kind}' for status '{run.status}'. Expected: {allowed}",
            )

        # Handle cancellation
        if req.kind == "cancel":
            run.status = "cancelled"
            run.revision += 1
            run.latest_event_id = event_id
            run.latest_event_digest = event_digest
            await self.store.save_run(run.to_dict())
            return self._build_response(run)

        # Handle answer
        if req.kind == "answer":
            if not req.answer or not req.answer.strip():
                raise HTTPException(status_code=400, detail="Answer text required.")
            run.history.append({"role": "user", "content": req.answer})
            # Re-plan with the answer
            try:
                from .tenant_config import get_tenant_config, extract_brain_config
                brain_cfg = extract_brain_config(run.brain)
                req_overrides = req.clientConfig.model_dump(exclude_none=True) if getattr(req, "clientConfig", None) else {}
                effective_config = {**brain_cfg, **req_overrides}
                tenant_cfg = get_tenant_config(tenant, effective_config)

                agent_result = await self.provider.generate(
                    message=req.answer,
                    context=req.context.model_dump() if req.context else run.context,
                    brain=run.brain,
                    targets=(req.context.model_dump() if req.context else run.context).get("availableTargets", []),
                    tools=run.tools,
                    client_config=tenant_cfg,
                    history=list(run.history),
                    original_message=run.original_message,
                )
                run.plan = agent_result
                run.status = agent_result.get("status", "completed")
                if agent_result.get("reply"):
                    run.history.append({"role": "assistant", "content": agent_result["reply"]})
            except Exception:
                run.status = "failed"
                run.plan = {"reply": "I encountered an error. Please try again.", "actions": [], "questions": [], "toolCalls": []}

        # Handle action/tool results
        if req.kind in ("actions", "tools", "action_results"):
            results = [r.model_dump() for r in (req.results or [])]

            # Validate result IDs match pending operations
            pending_ids = set()
            if req.kind in ("actions", "action_results"):
                pending_ids = {a["id"] for a in run.plan.get("actions", [])}
            elif req.kind == "tools":
                pending_ids = {t["id"] for t in run.plan.get("toolCalls", [])}

            result_ids = {r["id"] for r in results}
            if pending_ids and result_ids != pending_ids:
                raise HTTPException(status_code=409, detail=f"Result IDs must match pending operations. Expected: {pending_ids}, got: {result_ids}")

            # Check for failures
            any_failed = any(not r.get("ok", False) for r in results)
            if any_failed:
                run.status = "failed"
                errors = [r.get("error", "Unknown") for r in results if not r.get("ok")]
                run.plan = {"reply": f"Some operations failed: {'; '.join(errors)}", "actions": [], "questions": [], "toolCalls": []}
            else:
                # Continue with results
                try:
                    from .tenant_config import get_tenant_config, extract_brain_config
                    brain_cfg = extract_brain_config(run.brain)
                    req_overrides = req.clientConfig.model_dump(exclude_none=True) if getattr(req, "clientConfig", None) else {}
                    effective_config = {**brain_cfg, **req_overrides}
                    tenant_cfg = get_tenant_config(tenant, effective_config)

                    agent_result = await self.provider.continue_with_results(
                        run.to_dict(), results, client_config=tenant_cfg
                    )
                    run.plan = agent_result
                    run.status = agent_result.get("status", "completed")
                    if agent_result.get("reply"):
                        run.history.append({"role": "assistant", "content": agent_result["reply"]})
                except Exception:
                    # Commit receipts but fail the run
                    run.status = "failed"
                    run.plan = {"reply": "Actions were applied but replanning failed.", "actions": [], "questions": [], "toolCalls": []}

        # Update state
        run.revision += 1
        run.turn_count += 1
        run.latest_event_id = event_id
        run.latest_event_digest = event_digest
        run.latest_event_result = self._build_response_dict(run)

        if req.context:
            run.context = req.context.model_dump()

        await self.store.save_run(run.to_dict())
        return self._build_response(run)

    def _build_response(self, run: RunState) -> RunResponse:
        """Build a RunResponse from current run state."""
        plan = run.plan or {}
        return RunResponse(
            protocolVersion="1",
            runId=run.id,
            revision=run.revision,
            status=run.status,
            reply=plan.get("reply"),
            questions=plan.get("questions", []),
            actions=plan.get("actions", []),
            toolCalls=plan.get("toolCalls", []),
        )

    def _build_response_dict(self, run: RunState) -> dict:
        """Build response as dict for storage."""
        resp = self._build_response(run)
        return resp.model_dump()

