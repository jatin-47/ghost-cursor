"""Tests for Gemini backend tools declarations in VertexAILLMProvider."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.llm.provider import VertexAILLMProvider
from app.models import ToolDeclaration, CreateRunRequest, GhostContext
from app.run_manager import RunManager
from app.storage.memory import MemoryRunStore


def test_normalize_tool_declarations_dict_and_models():
    """Verify tool declarations from dicts and Pydantic models are normalized."""
    tools = [
        {
            "name": "lookup_order",
            "description": "Checks order status and shipment tracking",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        },
        ToolDeclaration(
            name="check_warehouse_stock",
            description="Checks warehouse inventory count",
            parameters={
                "type": "object",
                "properties": {"sku": {"type": "string"}, "size": {"type": "string"}},
                "required": ["sku", "size"],
            },
        ),
    ]

    normalized = VertexAILLMProvider._normalize_tool_declarations(tools)
    assert len(normalized) == 2
    assert normalized[0]["name"] == "lookup_order"
    assert normalized[0]["description"] == "Checks order status and shipment tracking"
    assert normalized[0]["parameters"]["required"] == ["order_id"]

    assert normalized[1]["name"] == "check_warehouse_stock"
    assert normalized[1]["description"] == "Checks warehouse inventory count"
    assert normalized[1]["parameters"]["required"] == ["sku", "size"]


def test_build_system_instruction_includes_tool_declarations():
    """Verify backend tools (name, description, parameters) are added to the Gemini system prompt."""
    provider = VertexAILLMProvider(project_id="test-proj")
    tools = [
        {
            "name": "lookup_order",
            "description": "Checks order status, shipment tracking, and items for the authenticated user",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "Order ID to lookup, e.g. 'SH-1024'",
                    }
                },
                "required": ["order_id"],
            },
        }
    ]

    prompt = provider._build_system_instruction(
        app_name="ShopHive",
        app_type="e-commerce store",
        refusal_msg="Out of scope refusal",
        brain="Platform knowledge",
        targets=["orders.tracking_link"],
        tools=tools,
        context={"page": "orders"},
    )

    # 1. Assert backend tools section exists
    assert "CUSTOMER BACKEND TOOLS AVAILABLE" in prompt

    # 2. Assert tool name, description, parameters are included
    assert "lookup_order" in prompt
    assert "name: lookup_order" in prompt
    assert "description: Checks order status, shipment tracking, and items for the authenticated user" in prompt
    assert "parameters:" in prompt
    assert "order_id" in prompt

    # 3. Assert instructions for toolCalls return format
    assert "toolCalls" in prompt
    assert "awaiting_tools" in prompt
    assert '"id": "tc_1"' in prompt


@pytest.mark.asyncio
async def test_vertex_provider_parses_tool_calls_dict():
    """Verify VertexAILLMProvider correctly parses toolCalls from Gemini response."""
    provider = VertexAILLMProvider(project_id="test-proj")

    gemini_json_response = json.dumps({
        "reply": "Let me look up order SH-1024 for you.",
        "status": "awaiting_tools",
        "actions": [],
        "questions": [],
        "toolCalls": [
            {
                "id": "tc_1",
                "tool": "lookup_order",
                "parameters": {"order_id": "SH-1024"},
            }
        ],
    })

    # Mock client and response
    mock_resp = MagicMock()
    mock_resp.text = gemini_json_response

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch("google.genai.Client", return_value=mock_client):
        result = await provider.generate(
            message="Where is my order SH-1024?",
            context={"page": "orders"},
            brain="ShopHive orders info",
            targets=[],
            tools=[{"name": "lookup_order", "description": "Lookup order", "parameters": {}}],
        )

    assert result["status"] == "awaiting_tools"
    assert result["reply"] == "Let me look up order SH-1024 for you."
    assert len(result["toolCalls"]) == 1
    assert result["toolCalls"][0]["tool"] == "lookup_order"
    assert result["toolCalls"][0]["parameters"] == {"order_id": "SH-1024"}
    assert result["actions"] == []
    assert result["questions"] == []


@pytest.mark.asyncio
async def test_vertex_provider_normalizes_snake_case_tool_calls():
    """Verify tool_calls with name and arguments are normalized to toolCalls with tool and parameters."""
    provider = VertexAILLMProvider(project_id="test-proj")

    gemini_json_response = json.dumps({
        "reply": "Checking stock now.",
        "tool_calls": [
            {
                "name": "check_warehouse_stock",
                "arguments": {"sku": "NK-AM90-01", "size": "10"},
            }
        ],
    })

    mock_resp = MagicMock()
    mock_resp.text = gemini_json_response

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch("google.genai.Client", return_value=mock_client):
        result = await provider.generate(
            message="Do you have size 10 in stock?",
            context={"page": "products"},
            brain="ShopHive products",
            targets=[],
            tools=[{"name": "check_warehouse_stock", "description": "Check stock", "parameters": {}}],
        )

    assert result["status"] == "awaiting_tools"
    assert len(result["toolCalls"]) == 1
    assert result["toolCalls"][0]["id"] == "tc_1"
    assert result["toolCalls"][0]["tool"] == "check_warehouse_stock"
    assert result["toolCalls"][0]["parameters"] == {"sku": "NK-AM90-01", "size": "10"}


@pytest.mark.asyncio
async def test_vertex_provider_parses_tool_call_list():
    """Verify parsed tool call list with backend tool is mapped to status awaiting_tools."""
    provider = VertexAILLMProvider(project_id="test-proj")

    gemini_list_response = json.dumps([
        {
            "tool": "lookup_order",
            "parameters": {"order_id": "SH-1024"},
        }
    ])

    mock_resp = MagicMock()
    mock_resp.text = gemini_list_response

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch("google.genai.Client", return_value=mock_client):
        result = await provider.generate(
            message="Track SH-1024",
            context={"page": "orders"},
            brain="ShopHive",
            targets=[],
            tools=[{"name": "lookup_order", "description": "Lookup order", "parameters": {}}],
        )

    assert result["status"] == "awaiting_tools"
    assert len(result["toolCalls"]) == 1
    assert result["toolCalls"][0]["tool"] == "lookup_order"
    assert result["toolCalls"][0]["parameters"] == {"order_id": "SH-1024"}


def test_build_continue_prompt_includes_message_history_and_results():
    """Verify _build_continue_prompt constructs prompt with original message, history, and results."""
    original_message = "Where is my order SH-1024?"
    history = [
        {"role": "user", "content": "Where is my order SH-1024?"},
        {"role": "assistant", "content": "Looking up SH-1024..."},
    ]
    results = [
        {"id": "tc_1", "ok": True, "output": {"status": "Shipped", "eta": "2 days"}},
    ]

    prompt = VertexAILLMProvider._build_continue_prompt(original_message, history, results)
    assert "### ORIGINAL USER REQUEST:" in prompt
    assert original_message in prompt
    assert "### RUN CONVERSATION HISTORY:" in prompt
    assert "Looking up SH-1024..." in prompt
    assert "### TOOL / ACTION EXECUTION RESULTS:" in prompt
    assert "tc_1" in prompt
    assert "Shipped" in prompt


@pytest.mark.asyncio
async def test_vertex_provider_continue_with_results_calls_gemini():
    """Verify continue_with_results calls Gemini with prompt containing original message, history, results and returns normal plan JSON."""
    provider = VertexAILLMProvider(project_id="test-proj")

    gemini_plan_response = json.dumps({
        "reply": "Your order SH-1024 is currently In Transit and arriving in 2 business days.",
        "status": "completed",
        "actions": [],
        "questions": [],
        "toolCalls": [],
    })

    mock_resp = MagicMock()
    mock_resp.text = gemini_plan_response

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    run_state = {
        "id": "run-101",
        "tenant": "shophive_demo",
        "original_message": "Where is my order SH-1024?",
        "history": [
            {"role": "user", "content": "Where is my order SH-1024?"},
            {"role": "assistant", "content": "Let me look up SH-1024 for you."},
        ],
        "brain": "ShopHive orders platform",
        "context": {"page": "orders", "availableTargets": []},
        "tools": [{"name": "lookup_order", "description": "Look up order", "parameters": {}}],
    }

    results = [
        {
            "id": "tc_1",
            "ok": True,
            "output": {"order_id": "SH-1024", "status": "In Transit", "estimated_delivery": "2 days"},
        }
    ]

    with patch("google.genai.Client", return_value=mock_client):
        plan = await provider.continue_with_results(run_state, results)

    # 1. Verify Gemini was called
    assert mock_client.aio.models.generate_content.called
    call_args, call_kwargs = mock_client.aio.models.generate_content.call_args
    sent_contents = call_kwargs["contents"]
    assert "Where is my order SH-1024?" in sent_contents
    assert "tc_1" in sent_contents
    assert "In Transit" in sent_contents

    # 2. Verify normal plan JSON is returned
    assert plan["status"] == "completed"
    assert "In Transit" in plan["reply"]
    assert plan["actions"] == []
    assert plan["questions"] == []
    assert plan["toolCalls"] == []


@pytest.mark.asyncio
async def test_vertex_provider_continue_with_results_fallback_on_error():
    """Verify continue_with_results falls back to mock provider if Gemini call fails."""
    provider = VertexAILLMProvider(project_id="test-proj")

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("GCP Quota Exceeded"))

    run_state = {
        "id": "run-102",
        "tenant": "shophive_demo",
        "original_message": "Where is my order SH-1024?",
        "history": [],
        "brain": "ShopHive",
        "context": {},
        "tools": [],
    }

    results = [{"id": "tc_1", "ok": True, "output": "Order delivered"}]

    with patch("google.genai.Client", return_value=mock_client):
        plan = await provider.continue_with_results(run_state, results)

    # Deterministic fallback handles it safely
    assert plan["status"] == "completed"
    assert "Order delivered" in plan["reply"]


@pytest.mark.asyncio
async def test_run_manager_replan_passes_original_message_history_client_config():
    """Verify run_manager passes original_message, history, and client_config when re-planning after a clarification answer."""
    import uuid
    from app.models import ContinueRunRequest

    store = MemoryRunStore()
    mock_provider = MagicMock()
    mock_provider.generate = AsyncMock(return_value={
        "reply": "Which shipping address should I use?",
        "status": "awaiting_answer",
        "questions": [{"question": "Which address?", "options": ["123 Main St"]}],
        "actions": [],
        "toolCalls": [],
    })
    manager = RunManager(store=store, provider=mock_provider)

    # 1. Create run
    req = CreateRunRequest(
        protocolVersion="1",
        requestId=uuid.uuid4(),
        message="Checkout my cart",
        context=GhostContext(page="cart"),
        brain="Platform knowledge",
    )
    resp = await manager.create_run("shophive_demo", "user_1", req)
    assert resp.status == "awaiting_answer"

    # 2. Reset mock to capture re-planning call
    mock_provider.generate.reset_mock()
    mock_provider.generate.return_value = {
        "reply": "Filling address now",
        "status": "awaiting_actions",
        "actions": [{"id": "act_1", "tool": "fill_input", "parameters": {}}],
        "questions": [],
        "toolCalls": [],
    }

    # 3. Continue with answer
    cont_req = ContinueRunRequest(
        protocolVersion="1",
        eventId=uuid.uuid4(),
        revision=resp.revision,
        kind="answer",
        answer="123 Main St, New York, NY 10001",
    )
    cont_resp = await manager.continue_run(resp.runId, "shophive_demo", "user_1", cont_req)

    # 4. Verify generate was called with original_message, history, and client_config
    assert mock_provider.generate.called
    call_kwargs = mock_provider.generate.call_args.kwargs
    assert call_kwargs["message"] == "123 Main St, New York, NY 10001"
    assert call_kwargs["original_message"] == "Checkout my cart"
    assert len(call_kwargs["history"]) >= 2
    assert call_kwargs["history"][-1]["content"] == "123 Main St, New York, NY 10001"
    assert call_kwargs["client_config"] is not None

    assert cont_resp.status == "awaiting_actions"


def test_gateway_style_tool_declaration_keeps_parameters_in_gemini_prompt():
    """Verify ToolDeclaration accepts inputSchema from Python gateway and keeps its parameters in Gemini prompt."""
    from app.models import ToolDeclaration, CreateRunRequest, GhostContext
    from app.llm.provider import VertexAILLMProvider

    # Gateway-style declaration produced by RegisteredTool.to_declaration() in packages/sdk-server-python
    gateway_tool_payload = {
        "name": "lookup_order",
        "description": "Checks order status, shipment tracking, and items for the authenticated user",
        "inputSchema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "Order ID to lookup, e.g. 'SH-1024' or 'ORD-20241001-A7X'",
                    "title": "Order Id",
                }
            },
            "required": ["order_id"],
            "title": "OrderQuery",
        },
        "readOnly": True,
    }

    # 1. ToolDeclaration model accepts inputSchema key and populates parameters
    tool_decl = ToolDeclaration.model_validate(gateway_tool_payload)
    assert tool_decl.name == "lookup_order"
    assert tool_decl.parameters["type"] == "object"
    assert "order_id" in tool_decl.parameters["properties"]
    assert tool_decl.parameters["required"] == ["order_id"]

    # 2. When submitted in CreateRunRequest, parameters are retained
    run_req = CreateRunRequest(
        protocolVersion="1",
        requestId="22222222-2222-2222-2222-222222222222",
        message="Where is order SH-1024?",
        context=GhostContext(page="orders"),
        brain="Platform knowledge",
        tools=[gateway_tool_payload],
    )
    assert len(run_req.tools) == 1
    assert run_req.tools[0].name == "lookup_order"
    assert "order_id" in run_req.tools[0].parameters["properties"]

    # 3. Serialized tools passed to VertexAILLMProvider keep parameters in Gemini prompt
    provider = VertexAILLMProvider(project_id="test-proj")
    tools_for_provider = [t.model_dump() for t in run_req.tools]
    prompt = provider._build_system_instruction(
        app_name="ShopHive",
        app_type="e-commerce store",
        refusal_msg="Out of scope refusal",
        brain="ShopHive platform brain",
        targets=["orders.tracking_link"],
        tools=tools_for_provider,
        context={"page": "orders"},
    )

    # 4. Assert tool parameters are present in the Gemini prompt
    assert "lookup_order" in prompt
    assert "parameters:" in prompt
    assert "order_id" in prompt
    assert "ORD-20241001-A7X" in prompt
    assert "OrderQuery" in prompt


def test_format_tools_shows_name_and_description_only_once():
    """Verify _format_tools shows each tool's name and description only once."""
    tools = [
        {
            "name": "lookup_order",
            "description": "Checks order status and shipment tracking",
            "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}},
        },
        {
            "name": "get_loyalty_points",
            "description": "Retrieves user reward points",
            "parameters": {},
        },
    ]

    formatted = VertexAILLMProvider._format_tools(tools)

    # 1. Name is shown only once per tool
    assert formatted.count("lookup_order") == 1
    assert formatted.count("get_loyalty_points") == 1

    # 2. Description is shown only once per tool
    assert formatted.count("Checks order status and shipment tracking") == 1
    assert formatted.count("Retrieves user reward points") == 1

    # 3. Formatted structure is valid
    assert "- name: lookup_order" in formatted
    assert "  description: Checks order status and shipment tracking" in formatted
    assert "  parameters:" in formatted
    assert "- name: get_loyalty_points" in formatted


@pytest.mark.asyncio
async def test_vertex_provider_drops_empty_tool_name_in_tool_calls():
    """Verify toolCalls with empty tool name are dropped."""
    provider = VertexAILLMProvider(project_id="test-proj")

    gemini_json_response = json.dumps({
        "reply": "Looking up your order.",
        "status": "awaiting_tools",
        "toolCalls": [
            {"id": "tc_1", "tool": "", "parameters": {}},
            {"id": "tc_2", "name": "   ", "parameters": {}},
            {"id": "tc_3", "tool": "lookup_order", "parameters": {"order_id": "SH-1024"}},
        ],
    })

    mock_resp = MagicMock()
    mock_resp.text = gemini_json_response

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch("google.genai.Client", return_value=mock_client):
        result = await provider.generate(
            message="Track SH-1024",
            context={"page": "orders"},
            brain="ShopHive orders",
            targets=[],
            tools=[{"name": "lookup_order", "description": "Lookup order", "parameters": {}}],
        )

    assert result["status"] == "awaiting_tools"
    assert len(result["toolCalls"]) == 1
    assert result["toolCalls"][0]["tool"] == "lookup_order"
    assert result["toolCalls"][0]["parameters"] == {"order_id": "SH-1024"}


@pytest.mark.asyncio
async def test_vertex_provider_drops_undeclared_tool_name_in_tool_calls():
    """Verify toolCalls with undeclared tool name are dropped."""
    provider = VertexAILLMProvider(project_id="test-proj")

    gemini_json_response = json.dumps({
        "reply": "Executing tools.",
        "status": "awaiting_tools",
        "toolCalls": [
            {"id": "tc_1", "tool": "undeclared_custom_tool", "parameters": {"foo": "bar"}},
            {"id": "tc_2", "tool": "lookup_order", "parameters": {"order_id": "SH-1024"}},
        ],
    })

    mock_resp = MagicMock()
    mock_resp.text = gemini_json_response

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch("google.genai.Client", return_value=mock_client):
        result = await provider.generate(
            message="Track SH-1024",
            context={"page": "orders"},
            brain="ShopHive orders",
            targets=[],
            tools=[{"name": "lookup_order", "description": "Lookup order", "parameters": {}}],
        )

    assert result["status"] == "awaiting_tools"
    assert len(result["toolCalls"]) == 1
    assert result["toolCalls"][0]["tool"] == "lookup_order"


@pytest.mark.asyncio
async def test_vertex_provider_removes_hardcoded_shophive_tool_names():
    """Verify hardcoded ShopHive tool names are NOT accepted if undeclared."""
    provider = VertexAILLMProvider(project_id="test-proj")

    # Model attempts to call check_warehouse_stock and simulate_discount_roi, but only lookup_order is declared
    gemini_json_response = json.dumps({
        "reply": "Checking inventory and discount.",
        "status": "awaiting_tools",
        "toolCalls": [
            {"id": "tc_1", "tool": "check_warehouse_stock", "parameters": {"sku": "SKU-99"}},
            {"id": "tc_2", "tool": "simulate_discount_roi", "parameters": {"promo_code": "SAVE20"}},
            {"id": "tc_3", "tool": "lookup_order", "parameters": {"order_id": "SH-1024"}},
        ],
    })

    mock_resp = MagicMock()
    mock_resp.text = gemini_json_response

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch("google.genai.Client", return_value=mock_client):
        result = await provider.generate(
            message="Track SH-1024 and check stock",
            context={"page": "orders"},
            brain="ShopHive orders",
            targets=[],
            tools=[{"name": "lookup_order", "description": "Lookup order", "parameters": {}}],
        )

    # Only lookup_order was declared, so check_warehouse_stock and simulate_discount_roi are dropped
    assert result["status"] == "awaiting_tools"
    assert len(result["toolCalls"]) == 1
    assert result["toolCalls"][0]["tool"] == "lookup_order"

    # If NO tools are declared, all of them are dropped and status falls back to completed
    with patch("google.genai.Client", return_value=mock_client):
        result_empty = await provider.generate(
            message="Track SH-1024 and check stock",
            context={"page": "orders"},
            brain="ShopHive orders",
            targets=[],
            tools=[],
        )

    assert result_empty["status"] == "completed"
    assert len(result_empty["toolCalls"]) == 0


@pytest.mark.asyncio
async def test_vertex_provider_parses_list_drops_empty_and_undeclared_tools():
    """Verify parsed tool call list drops empty and undeclared tool names without hardcoded fallbacks."""
    provider = VertexAILLMProvider(project_id="test-proj")

    gemini_list_response = json.dumps([
        {"tool": "", "parameters": {}},
        {"tool": "check_warehouse_stock", "parameters": {"sku": "SKU-1"}},
        {"tool": "lookup_order", "parameters": {"order_id": "SH-1024"}},
    ])

    mock_resp = MagicMock()
    mock_resp.text = gemini_list_response

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch("google.genai.Client", return_value=mock_client):
        result = await provider.generate(
            message="Track SH-1024",
            context={"page": "orders"},
            brain="ShopHive",
            targets=[],
            tools=[{"name": "lookup_order", "description": "Lookup order", "parameters": {}}],
        )

    assert result["status"] == "awaiting_tools"
    assert len(result["toolCalls"]) == 1
    assert result["toolCalls"][0]["tool"] == "lookup_order"
    assert result["toolCalls"][0]["id"] == "tc_1"




