"""Unit tests for RunManager state machine and invariants."""

import asyncio
import uuid
import pytest
from app.models import CreateRunRequest, ContinueRunRequest, GhostContext, ResultItem
from app.run_manager import RunManager, RunState
from app.storage.memory import MemoryRunStore
from app.llm.provider import MockLLMProvider


@pytest.fixture
def run_manager():
    store = MemoryRunStore()
    provider = MockLLMProvider()
    return RunManager(store=store, provider=provider)


@pytest.mark.asyncio
async def test_create_run_and_deduplication(run_manager):
    req_id = uuid.uuid4()
    req = CreateRunRequest(
        protocolVersion="1",
        requestId=req_id,
        message="Turn on dark mode",
        context=GhostContext(page="dashboard", values={}, availableTargets=["settings.theme_toggle"]),
        brain="Test brain context",
    )

    # 1. Create run
    resp1 = await run_manager.create_run("shophive_demo", "user_123", req)
    assert resp1.protocolVersion == "1"
    assert resp1.status in ("awaiting_actions", "completed")
    assert resp1.revision == 0
    assert resp1.runId

    # 2. Identical replay returns existing run
    resp2 = await run_manager.create_run("shophive_demo", "user_123", req)
    assert resp2.runId == resp1.runId
    assert resp2.revision == resp1.revision

    # 3. Changed payload with same requestId produces 409
    from fastapi import HTTPException
    req_altered = CreateRunRequest(
        protocolVersion="1",
        requestId=req_id,
        message="Add sneakers to cart instead",
        context=GhostContext(page="dashboard", values={}, availableTargets=[]),
        brain="Test brain context",
    )
    with pytest.raises(HTTPException) as exc:
        await run_manager.create_run("shophive_demo", "user_123", req_altered)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_continuation_lifecycle(run_manager):
    req = CreateRunRequest(
        protocolVersion="1",
        requestId=uuid.uuid4(),
        message="Turn appearance to dark mode",
        context=GhostContext(page="dashboard"),
        brain="Test brain context",
    )
    resp = await run_manager.create_run("shophive_demo", "user_123", req)
    assert resp.status == "awaiting_actions"
    assert len(resp.actions) > 0

    action_ids = [a.id for a in resp.actions]
    results = [ResultItem(id=aid, ok=True, output="completed") for aid in action_ids]

    # 1. Continue with exact revision
    cont_req = ContinueRunRequest(
        protocolVersion="1",
        eventId=uuid.uuid4(),
        revision=resp.revision,
        kind="actions",
        results=results,
    )
    cont_resp = await run_manager.continue_run(resp.runId, "shophive_demo", "user_123", cont_req)
    assert cont_resp.status == "completed"
    assert cont_resp.revision == resp.revision + 1


@pytest.mark.asyncio
async def test_revision_mismatch_rejection(run_manager):
    req = CreateRunRequest(
        protocolVersion="1",
        requestId=uuid.uuid4(),
        message="Turn appearance to dark mode",
        context=GhostContext(page="dashboard"),
        brain="Test brain context",
    )
    resp = await run_manager.create_run("shophive_demo", "user_123", req)

    from fastapi import HTTPException
    cont_req = ContinueRunRequest(
        protocolVersion="1",
        eventId=uuid.uuid4(),
        revision=999,  # Mismatched revision
        kind="actions",
        results=[ResultItem(id="act_1", ok=True)],
    )
    with pytest.raises(HTTPException) as exc:
        await run_manager.continue_run(resp.runId, "shophive_demo", "user_123", cont_req)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_expired_run_returns_410(run_manager):
    req = CreateRunRequest(
        protocolVersion="1",
        requestId=uuid.uuid4(),
        message="Hello",
        context=GhostContext(page="dashboard"),
        brain="Test brain context",
    )
    resp = await run_manager.create_run("shophive_demo", "user_123", req)

    # Force expiration in store
    raw_data = await run_manager.store.get_run(resp.runId, "shophive_demo", "user_123")
    raw_data["expires_at"] = 1.0  # Expired in past
    await run_manager.store.save_run(raw_data)

    from fastapi import HTTPException
    cont_req = ContinueRunRequest(
        protocolVersion="1",
        eventId=uuid.uuid4(),
        revision=resp.revision,
        kind="cancel",
    )
    with pytest.raises(HTTPException) as exc:
        await run_manager.continue_run(resp.runId, "shophive_demo", "user_123", cont_req)
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_guided_tour_creation_and_completion_with_action_results(run_manager):
    """Verify guided tour creation, step structure, and completion via action_results."""
    req = CreateRunRequest(
        protocolVersion="1",
        requestId=uuid.uuid4(),
        message="Take a guided tour",
        context=GhostContext(page="dashboard", values={}, availableTargets=[]),
        brain="Test brain context",
    )
    resp = await run_manager.create_run("shophive_demo", "user_123", req)
    assert resp.status == "awaiting_actions"
    assert len(resp.actions) == 1
    assert resp.actions[0].tool == "guided_tour"
    assert "steps" in resp.actions[0].parameters
    assert len(resp.actions[0].parameters["steps"]) >= 3

    # Continue run using the frontend SDK's action_results kind
    cont_req = ContinueRunRequest(
        protocolVersion="1",
        eventId=uuid.uuid4(),
        revision=resp.revision,
        kind="action_results",
        results=[ResultItem(id=resp.actions[0].id, ok=True, output="Tour completed")],
    )
    resp2 = await run_manager.continue_run(resp.runId, "shophive_demo", "user_123", cont_req)
    assert resp2.status == "completed"
    assert "Tour completed" in resp2.reply


@pytest.mark.asyncio
async def test_guided_tour_page_aware_steps(run_manager):
    """Verify page-specific guided tours and suggestions."""
    # 1. Orders page returns tour
    req_orders = CreateRunRequest(
        protocolVersion="1",
        requestId=uuid.uuid4(),
        message="How do I track my return?",
        context=GhostContext(page="orders", values={}, availableTargets=[]),
        brain="Test brain context",
    )
    resp_orders = await run_manager.create_run("shophive_demo", "user_123", req_orders)
    assert resp_orders.status == "awaiting_actions"
    assert resp_orders.actions[0].tool == "guided_tour"
    assert any("order" in s["target_id"] for s in resp_orders.actions[0].parameters["steps"])

    # 2. Settings page tour
    req_settings = CreateRunRequest(
        protocolVersion="1",
        requestId=uuid.uuid4(),
        message="Show me around settings",
        context=GhostContext(page="settings", values={}, availableTargets=[]),
        brain="Test brain context",
    )
    resp_settings = await run_manager.create_run("shophive_demo", "user_123", req_settings)
    assert resp_settings.status == "awaiting_actions"
    assert resp_settings.actions[0].tool == "guided_tour"
    assert any("theme_toggle" in s["target_id"] for s in resp_settings.actions[0].parameters["steps"])

    # 3. Suggestion chips on dashboard include guided tour
    suggestions = await run_manager.provider.generate_suggestions(page="dashboard", brain="", targets=[])
    assert "Take a guided tour" in suggestions


@pytest.mark.asyncio
async def test_question_item_handles_numeric_and_many_options():
    """Verify QuestionItem supports float/int shoe sizes and truncates over 25 options."""
    from app.models import QuestionItem
    shoe_sizes = [7, 7.5, 8, 8.5, 9, 9.5, 10, 10.5, 11, 11.5, 12, 12.5, 13]
    item = QuestionItem(question="What size would you like?", options=shoe_sizes)
    assert len(item.options) == 13
    assert item.options[0] == "7"
    assert item.options[1] == "7.5"
    assert item.options[-1] == "13"

    # Truncation beyond 25
    large_list = list(range(35))
    item2 = QuestionItem(question="Pick a number", options=large_list)
    assert len(item2.options) == 25


@pytest.mark.asyncio
async def test_action_item_unpacks_root_parameters():
    """Verify ActionItem extracts parameters specified at root level."""
    from app.models import ActionItem
    raw = {"id": "act_1", "tool": "click", "target_id": "product.size.10", "explanation": "Select size 10"}
    item = ActionItem(**raw)
    assert item.id == "act_1"
    assert item.tool == "click"
    assert item.parameters == {"target_id": "product.size.10", "explanation": "Select size 10"}


@pytest.mark.asyncio
async def test_continuation_with_clarification_question(run_manager):
    """Verify continuing a run when the model asks for clarification with 13 shoe sizes."""
    from unittest.mock import AsyncMock
    shoe_sizes = [7, 7.5, 8, 8.5, 9, 9.5, 10, 10.5, 11, 11.5, 12, 12.5, 13]
    clarification_plan = {
        "reply": "Please select a size for the Air Max 90:",
        "status": "awaiting_answer",
        "questions": [{"question": "What size would you like?", "options": shoe_sizes}],
        "actions": [],
        "toolCalls": [],
    }

    # Create run on product page
    req = CreateRunRequest(
        protocolVersion="1",
        requestId=uuid.uuid4(),
        message="I want to order Air Max 90",
        context=GhostContext(page="/product/air-max-90", availableTargets=[f"product.size.{s}" for s in shoe_sizes] + ["product.add_to_cart_btn"]),
        brain="Test brain context",
    )
    resp = await run_manager.create_run("shophive_demo", "user_123", req)

    # Mock continue_with_results to return the clarification question with 13 sizes
    run_manager.provider.continue_with_results = AsyncMock(return_value=clarification_plan)

    cont_req = ContinueRunRequest(
        protocolVersion="1",
        eventId=uuid.uuid4(),
        revision=resp.revision,
        kind="actions",
        results=[ResultItem(id="act_1", ok=True)],
        context=GhostContext(page="/product/air-max-90", availableTargets=[f"product.size.{s}" for s in shoe_sizes] + ["product.add_to_cart_btn"]),
    )
    # Give the run an initial action so pending_ids match
    run = await run_manager.store.get_run(resp.runId, "shophive_demo", "user_123")
    run["plan"] = {"actions": [{"id": "act_1", "tool": "click", "parameters": {}}]}
    run["status"] = "awaiting_actions"
    await run_manager.store.save_run(run)

    cont_resp = await run_manager.continue_run(resp.runId, "shophive_demo", "user_123", cont_req)
    assert cont_resp.status == "awaiting_answer"
    assert len(cont_resp.questions) == 1
    assert len(cont_resp.questions[0].options) == 13
    assert cont_resp.questions[0].options[0] == "7"
    assert cont_resp.questions[0].options[1] == "7.5"


@pytest.mark.asyncio
async def test_build_response_resilient_fallback(run_manager):
    """Verify _build_response catches invalid models and safely falls back without 500 error."""
    req = CreateRunRequest(
        protocolVersion="1",
        requestId=uuid.uuid4(),
        message="Test fallback",
        context=GhostContext(page="dashboard"),
        brain="Test brain context",
    )
    resp = await run_manager.create_run("shophive_demo", "user_123", req)
    run_data = await run_manager.store.get_run(resp.runId, "shophive_demo", "user_123")
    run_state = RunState.from_dict(run_data)

    # Corrupt the plan with invalid data
    run_state.plan = {
        "reply": "Test reply",
        "actions": [{"invalid": "action without tool or id"}],
    }
    response = run_manager._build_response(run_state)
    assert response.status == "completed"
    assert response.runId == run_state.id
    assert response.reply == "Test reply"



