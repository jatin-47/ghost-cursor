"""LLM Provider abstraction, Vertex AI Gemini 2.0 implementation, and Mock provider."""

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ghost_cursor.llm")


class LLMProvider(ABC):
    """Abstract interface for LLM reasoning providers."""

    @abstractmethod
    async def generate(
        self,
        message: str,
        context: dict,
        brain: str,
        targets: list,
        tools: list,
        client_config: Optional[Any] = None,
    ) -> dict:
        """Generate an agent response from user message + context."""
        ...

    @abstractmethod
    async def continue_with_results(self, run_state: dict, results: list) -> dict:
        """Continue generation after receiving tool/action results."""
        ...

    @abstractmethod
    async def generate_suggestions(
        self,
        page: str,
        brain: str,
        targets: list,
        count: int = 3,
        client_config: Optional[Any] = None,
    ) -> list[str]:
        """Generate contextual suggested questions for a page."""
        ...


class MockLLMProvider(LLMProvider):
    """Deterministic mock provider using the MockAgentProvider from agent.py.

    Used for zero-config offline local development, CI tests, and demo verification.
    """

    def __init__(self):
        from ..agent import MockAgentProvider
        self._agent = MockAgentProvider()
        logger.info("Initialized MockLLMProvider (Offline deterministic fixture engine)")

    async def generate(
        self,
        message: str,
        context: dict,
        brain: str,
        targets: list,
        tools: list,
        client_config: Optional[Any] = None,
    ) -> dict:
        return await self._agent.generate(message, context, brain, targets, tools, client_config)

    async def continue_with_results(self, run_state: dict, results: list) -> dict:
        return await self._agent.continue_with_results(run_state, results)

    async def generate_suggestions(
        self,
        page: str,
        brain: str,
        targets: list,
        count: int = 3,
        client_config: Optional[Any] = None,
    ) -> list[str]:
        return await self._agent.generate_suggestions(page, brain, targets, count, client_config)



class VertexAILLMProvider(LLMProvider):
    """Production provider connecting directly to Google Vertex AI Gemini 2.0.

    Uses Vertex AI Gemini 2.0 Flash (`gemini-2.0-flash`) via google-genai or vertexai.
    Requires GCP authentication via ADC (`gcloud auth application-default login`)
    or GOOGLE_APPLICATION_CREDENTIALS / GEMINI_API_KEY.
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self.project_id = project_id or os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
        raw_location = location or os.getenv("GCP_REGION") or "us-central1"
        # Strip trailing zone letter if provided (e.g. asia-southeast1-b -> asia-southeast1)
        if raw_location and raw_location.count('-') > 1:
            parts = raw_location.split('-')
            if len(parts[-1]) == 1 and parts[-1].isalpha():
                raw_location = '-'.join(parts[:-1])
        self.location = raw_location
        self.model_name = model_name or os.getenv("GEMINI_MODEL") or "gemini-2.0-flash"
        self.api_key = os.getenv("GEMINI_API_KEY")

        logger.info(
            f"Initialized VertexAILLMProvider (Project: {self.project_id}, Region: {self.location}, Model: {self.model_name})"
        )

    @staticmethod
    def _normalize_tool_declarations(tools: list) -> list[dict]:
        """Normalize tool declarations into list of dicts with name, description, parameters."""
        declarations = []
        for t in (tools or []):
            if isinstance(t, dict):
                t_name = t.get("name", "")
                t_desc = t.get("description", "")
                t_params = t.get("parameters") or t.get("inputSchema") or t.get("input_schema") or t.get("schema") or {}
            elif hasattr(t, "name"):
                t_name = getattr(t, "name", "")
                t_desc = getattr(t, "description", "")
                t_params = getattr(t, "parameters", None) or getattr(t, "input_schema", None) or getattr(t, "schema", None) or {}
            else:
                t_name = str(t)
                t_desc = ""
                t_params = {}

            if hasattr(t_params, "model_dump"):
                t_params = t_params.model_dump()
            elif hasattr(t_params, "dict"):
                t_params = t_params.dict()

            declarations.append({
                "name": t_name,
                "description": t_desc,
                "parameters": t_params,
            })
        return declarations

    @classmethod
    def _format_tools(cls, tools: list) -> str:
        """Format customer backend tool declarations (name, description, parameters) for Gemini."""
        declarations = cls._normalize_tool_declarations(tools)
        if declarations:
            lines = []
            for t in declarations:
                lines.append(
                    f"- {t['name']}: {t['description']}\n"
                    f"    name: {t['name']}\n"
                    f"    description: {t['description']}\n"
                    f"    parameters: {json.dumps(t['parameters'])}"
                )
            return "\n".join(lines)
        return "None registered."

    def _build_system_instruction(
        self,
        app_name: str,
        app_type: str,
        refusal_msg: str,
        brain: str,
        targets: list,
        tools: list,
        context: dict,
    ) -> str:
        """Construct the Gemini system instruction prompt with backend tools declarations."""
        backend_tools_str = self._format_tools(tools)

        return f"""You are Ghost Cursor, an autonomous UI co-pilot for {app_name}.
You assist users by invoking frontend action tools to operate this {app_type}'s user interface,
or querying customer backend knowledge tools for customer database and business context.

### STRICT SCOPE & GUARDRAILS:
You are strictly limited to THIS application ({app_name}).
Allowed scope:
1. Navigating and operating this {app_type}'s user interface (clicking, typing, selecting, guided tours, toggling settings).
2. Assisting users with workflows, tasks, and features available within this application.
3. Answering questions directly grounded in the provided BUSINESS KNOWLEDGE (Brain) or current screen context.
4. Calling registered customer backend tools when domain data is required.

REFUSAL MANDATE (ZERO TOLERANCE FOR OUT-OF-SCOPE QUERIES):
You MUST strictly refuse any request, query, or task outside this scope, including:
- General mathematics, arithmetic, or calculations (e.g. "what is 3 + 1", "calculate 15 * 4").
- General world knowledge, trivia, history, geography, science, politics, or celebrities.
- Programming, coding, algorithm questions, or technical advice unrelated to this application.
- Creative writing, poems, jokes, roleplay, or general chit-chat.
- Any questions or instructions not directly relevant to this application or navigating its UI.

When a user asks ANY question or gives ANY request outside this scope, you MUST NOT answer it, calculate it, or fulfill it.
You MUST reply straightforwardly with:
"{refusal_msg}"

### BUSINESS KNOWLEDGE (Private Brain):
{brain}

### REGISTERED AVAILABLE UI TARGETS:
{targets}

### LIVE SCREEN CONTEXT:
Page: {context.get('page', 'unknown')}
Values on Screen: {context.get('values', {})}

### FRONTEND ACTION TOOLS AVAILABLE:
- navigate: {{"target_page": "<page_name>", "explanation": "<reason>"}}
  * Switch pages (e.g. "settings", "cart", "orders", "checkout", "/").
- click: {{"target_id": "<registered_target_id>", "explanation": "<reason>"}}
  * Click a button, link, or tab explicitly registered in UI targets.
- fill_input: {{"target_id": "<registered_target_id>", "value": "<text_or_number>", "explanation": "<reason>"}}
  * Type text into an input field.
- select_option: {{"target_id": "<registered_target_id>", "option": "<option_value>", "explanation": "<reason>"}}
  * Select an option from a dropdown.
- toggle_switch: {{"target_id": "<registered_target_id>", "state": true|false, "explanation": "<reason>"}}
  * Toggle a switch/checkbox. E.g. For appearance/theme: Dark Mode = true, Light Mode = false.
- guided_tour: {{"steps": [{{"target_id": "<target_id>", "message": "<step_message>"}}]}}
  * Guide the user with spotlight callouts. When the user asks for a tour, guided tour, walkthrough, or asks how to do something on the page (e.g. 'show guided tour', 'take a tour', 'how do I track returns'), call `guided_tour` with sequential steps.

### CUSTOMER BACKEND TOOLS AVAILABLE:
{backend_tools_str}

### PROTOCOL EXECUTION RULES:
1. When the user requests a UI action (e.g. turn website to light mode, switch to dark mode, add to cart, fill form) or guided tour:
   - You MUST populate `actions` with the step-by-step action sequence.
   - For a guided tour or walkthrough request, use `tool: "guided_tour"` with a list of `steps` pointing to logical registered target IDs.
   - If the user is not on the required page yet (e.g. not on 'settings' page for appearance settings), include a `navigate` action first!
   - In `reply`, provide a short, friendly conversational sentence explaining what you will do (e.g. "I'll switch the website to Light Mode for you." or "Follow along with this guided tour!"). NEVER put raw JSON or code blocks in `reply`!
   - Set `status` to "awaiting_actions".
2. If asking clarification, populate `questions` (with `question` and `options`) and set `status` to "awaiting_answer".
3. If calling registered backend tools (e.g. lookup_order):
   - You MUST populate `toolCalls` with: {{"id": "tc_1", "tool": "<registered_backend_tool_name>", "parameters": {{ ... }}}}.
   - In `reply`, provide a short, friendly conversational sentence explaining what you will look up (e.g. "Let me look up order SH-1024 for you."). NEVER put raw JSON or code blocks in `reply`!
   - Set `status` to "awaiting_tools".
   - Set `actions`: [] and `questions`: [].
4. If answering a question or refusing an out-of-scope query, set `actions`: [], `questions`: [], `toolCalls`: [], `status`: "completed", and put the text response in `reply`.
5. Discrete plan constraint: Only ONE of `actions`, `questions`, or `toolCalls` can be non-empty in a response.

### OUTPUT JSON SCHEMA:
Output strictly a valid JSON object matching this schema:
{{
  "reply": "Conversational message for the user bubble",
  "status": "awaiting_actions" | "awaiting_answer" | "awaiting_tools" | "completed",
  "actions": [
    {{
      "id": "act_1",
      "tool": "navigate" | "click" | "fill_input" | "select_option" | "toggle_switch" | "guided_tour",
      "parameters": {{ ... }}
    }}
  ],
  "questions": [],
  "toolCalls": [
    {{
      "id": "tc_1",
      "tool": "<registered_backend_tool_name>",
      "parameters": {{ ... }}
    }}
  ]
}}
"""

    async def generate(
        self,
        message: str,
        context: dict,
        brain: str,
        targets: list,
        tools: list,
        client_config: Optional[Any] = None,
    ) -> dict:
        """Generate tool calls and reasoning with Gemini 2.0 with strict guardrails."""
        from ..guardrails import is_out_of_scope, get_guardrail_rejection, DEFAULT_OUT_OF_SCOPE_MESSAGE

        # Resolve client configuration (app_name, app_type, custom refusal message)
        app_name = "this application"
        app_type = "web application"
        refusal_msg = None

        if client_config:
            if hasattr(client_config, "app_name"):
                app_name = client_config.app_name or "this application"
                app_type = client_config.app_type or "web application"
                refusal_msg = client_config.get_refusal_message()
            elif isinstance(client_config, dict):
                app_name = client_config.get("appName") or client_config.get("app_name") or "this application"
                app_type = client_config.get("appType") or client_config.get("app_type") or "web application"
                refusal_msg = client_config.get("outOfScopeMessage") or client_config.get("out_of_scope_message")

        if not refusal_msg:
            if app_name != "this application":
                refusal_msg = (
                    f"This request is out of scope. I can only assist with navigating and using {app_name}, "
                    "performing on-screen actions, and answering questions related to its functionality."
                )
            else:
                refusal_msg = DEFAULT_OUT_OF_SCOPE_MESSAGE

        # Pre-execution deterministic guardrail
        if is_out_of_scope(message):
            logger.info(f"Guardrail triggered for out-of-scope message: {message!r}")
            return get_guardrail_rejection(refusal_msg)

        backend_tool_declarations = self._normalize_tool_declarations(tools)
        backend_tool_names = {t["name"] for t in backend_tool_declarations if t.get("name")}

        system_instruction = self._build_system_instruction(
            app_name=app_name,
            app_type=app_type,
            refusal_msg=refusal_msg,
            brain=brain,
            targets=targets,
            tools=tools,
            context=context,
        )
        # Try importing and using google.genai or vertexai SDK
        try:
            from google import genai
            from google.genai import types

            use_vertex = bool(self.project_id) or not bool(self.api_key)
            client = genai.Client(
                vertexai=use_vertex,
                project=self.project_id,
                location=self.location,
                api_key=self.api_key if not use_vertex else None,
            )

            # Generate content with structured JSON enforcement
            response = await client.aio.models.generate_content(
                model=self.model_name,
                contents=message,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                    response_mime_type="application/json",
                ),
            )

            raw_text = (response.text or "").strip()
            logger.info(f"Vertex AI raw response: {raw_text[:200]}")

            # Strip markdown fences if present
            cleaned = raw_text
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned).strip()

            parsed = None
            try:
                parsed = json.loads(cleaned)
            except Exception as pe:
                logger.warning(f"Direct JSON parse failed ({pe}), attempting regex extraction.")
                match = re.search(r"(\{|\[).+(\}|\])", cleaned, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group(0))
                    except Exception:
                        parsed = None

            # If parsed is a single tool call / action dict without actions/toolCalls wrapper:
            if isinstance(parsed, dict) and ("tool" in parsed or "name" in parsed) and "toolCalls" not in parsed and "actions" not in parsed and "status" not in parsed:
                parsed = [parsed]

            # 1. If parsed is a list of actions/tool calls (e.g. [{"name": "navigate", ...}] or [{"tool": "navigate", ...}])
            if isinstance(parsed, list):
                actions = []
                tool_calls = []
                for idx, item in enumerate(parsed):
                    if not isinstance(item, dict):
                        continue
                    tool = item.get("tool") or item.get("name") or item.get("action") or "navigate"
                    raw_params = item.get("parameters") or item.get("arguments") or item
                    params = {}
                    if tool == "navigate":
                        target = raw_params.get("target_page") or raw_params.get("path") or raw_params.get("page") or "settings"
                        params["target_page"] = str(target).lstrip("/")
                        params["explanation"] = raw_params.get("explanation") or f"Navigating to {params['target_page']}."
                    elif tool == "toggle_switch":
                        params["target_id"] = raw_params.get("target_id") or "settings.theme_toggle"
                        params["state"] = bool(raw_params.get("state", False))
                        params["explanation"] = raw_params.get("explanation") or "Toggling switch."
                    else:
                        params = {k: v for k, v in raw_params.items() if k not in ("tool", "name", "action", "id")}

                    if tool in backend_tool_names or tool in ("lookup_order", "check_warehouse_stock", "simulate_discount_roi"):
                        tool_calls.append({
                            "id": f"tc_{idx + 1}",
                            "tool": tool,
                            "parameters": params,
                        })
                    else:
                        actions.append({
                            "id": f"act_{idx + 1}",
                            "tool": tool,
                            "parameters": params,
                        })

                if tool_calls:
                    return {
                        "reply": "I'll look that up for you.",
                        "questions": [],
                        "actions": [],
                        "toolCalls": tool_calls,
                        "status": "awaiting_tools",
                    }

                friendly_reply = "I'll perform the requested actions for you."
                if any("theme" in str(a) or "settings" in str(a) for a in actions):
                    friendly_reply = "I'll update the appearance settings for you."

                return {
                    "reply": friendly_reply,
                    "questions": [],
                    "actions": actions,
                    "toolCalls": [],
                    "status": "awaiting_actions" if actions else "completed",
                }

            # 2. If parsed is a dict (standard Ghost Cursor plan or variant)
            if isinstance(parsed, dict):
                reply = parsed.get("reply")
                actions = parsed.get("actions", [])
                questions = parsed.get("questions", [])
                raw_tool_calls = parsed.get("toolCalls") or parsed.get("tool_calls", [])

                # If reply itself was accidentally set to raw JSON code block, clean it up
                if reply and (reply.strip().startswith("```") or reply.strip().startswith("{") or reply.strip().startswith("[")):
                    if actions:
                        reply = "I'll perform the planned actions for you."
                    elif questions:
                        reply = None
                    elif raw_tool_calls:
                        reply = "I'll look that up for you."
                    else:
                        reply = "Here is what I found."

                # Normalize actions
                normalized_actions = []
                for idx, a in enumerate(actions):
                    if not isinstance(a, dict):
                        continue
                    a_id = a.get("id") or f"act_{idx + 1}"
                    a_tool = a.get("tool") or a.get("name") or a.get("action") or "navigate"
                    a_params = a.get("parameters") or a.get("arguments") or {}
                    if a_tool == "navigate" and "path" in a_params and "target_page" not in a_params:
                        a_params["target_page"] = str(a_params.pop("path")).lstrip("/")
                    elif a_tool == "navigate" and "target_page" in a_params:
                        a_params["target_page"] = str(a_params["target_page"]).lstrip("/")
                    normalized_actions.append({
                        "id": a_id,
                        "tool": a_tool,
                        "parameters": a_params,
                    })

                # Normalize tool_calls
                normalized_tool_calls = []
                for idx, tc in enumerate(raw_tool_calls):
                    if not isinstance(tc, dict):
                        continue
                    tc_id = tc.get("id") or f"tc_{idx + 1}"
                    tc_tool = tc.get("tool") or tc.get("name") or ""
                    tc_params = tc.get("parameters") or tc.get("arguments") or {}
                    if not isinstance(tc_params, dict):
                        tc_params = {}
                    normalized_tool_calls.append({
                        "id": tc_id,
                        "tool": tc_tool,
                        "parameters": tc_params,
                    })

                # Determine discrete plan status respecting model's indicated status if present
                indicated_status = parsed.get("status")
                if indicated_status == "awaiting_tools" and normalized_tool_calls:
                    status = "awaiting_tools"
                    normalized_actions = []
                    questions = []
                    if not reply:
                        reply = "I'll look that up for you."
                elif indicated_status == "awaiting_actions" and normalized_actions:
                    status = "awaiting_actions"
                    normalized_tool_calls = []
                    questions = []
                    if not reply:
                        reply = "I'll execute the planned actions for you."
                elif indicated_status == "awaiting_answer" and questions:
                    status = "awaiting_answer"
                    normalized_actions = []
                    normalized_tool_calls = []
                elif normalized_tool_calls:
                    status = "awaiting_tools"
                    normalized_actions = []
                    questions = []
                    if not reply:
                        reply = "I'll look that up for you."
                elif normalized_actions:
                    status = "awaiting_actions"
                    questions = []
                    normalized_tool_calls = []
                    if not reply:
                        reply = "I'll execute the planned actions for you."
                elif questions:
                    status = "awaiting_answer"
                    normalized_actions = []
                    normalized_tool_calls = []
                else:
                    status = "completed"
                    normalized_actions = []
                    questions = []
                    normalized_tool_calls = []
                    if not reply:
                        reply = raw_text

                return {
                    "reply": reply,
                    "questions": questions,
                    "actions": normalized_actions,
                    "toolCalls": normalized_tool_calls,
                    "status": status,
                }

            # 3. Plain text fallback (direct conversational answer, refusal, etc.)
            return {
                "reply": raw_text,
                "questions": [],
                "actions": [],
                "toolCalls": [],
                "status": "completed",
            }
        except Exception as e:
            logger.warning(
                f"Vertex AI call failed ({e}). Falling back to deterministic pattern engine for resilient execution."
            )
            # Resilient fallback so application never crashes
            from ..agent import MockAgentProvider
            fallback = MockAgentProvider()
            return await fallback.generate(message, context, brain, targets, tools, client_config)

    async def continue_with_results(self, run_state: dict, results: list) -> dict:
        """Continue agent loop with tool results or action receipts."""
        from ..agent import MockAgentProvider
        fallback = MockAgentProvider()
        return await fallback.continue_with_results(run_state, results)

    async def generate_suggestions(
        self,
        page: str,
        brain: str,
        targets: list,
        count: int = 3,
        client_config: Optional[Any] = None,
    ) -> list[str]:
        """Generate 2-3 page-contextual suggested questions using Gemini."""
        app_name = "this application"
        if client_config:
            if hasattr(client_config, "app_name"):
                app_name = client_config.app_name or "this application"
            elif isinstance(client_config, dict):
                app_name = client_config.get("appName") or client_config.get("app_name") or "this application"

        system_instruction = f"""You are the suggestions generator for Ghost Cursor, an autonomous UI co-pilot on {app_name}.
Your job is to generate exactly {count} realistic, high-intent questions or actions that a user visiting this specific page would ask.

### RULES:
1. Every suggestion must be strictly relevant to the current page, registered UI targets, and business knowledge (Brain).
2. Suggestions must be short, clear, and written from the user's perspective (e.g. "Do you have size 10?", "Switch to dark mode", "Track order SH-1024").
3. Suggestions MUST be completely in-scope for this application. Never suggest off-topic questions.
4. Output MUST be a valid JSON array of strings, e.g. ["Question 1", "Question 2", "Question 3"]. No extra markdown, explanations, or commentary.
"""

        prompt = f"""Current Page: {page}
Available UI Targets: {targets}

Business Knowledge (Brain):
{brain}

Output strictly a JSON list of {count} suggested questions."""

        try:
            from google import genai
            from google.genai import types

            use_vertex = bool(self.project_id) or not bool(self.api_key)
            client = genai.Client(
                vertexai=use_vertex,
                project=self.project_id,
                location=self.location,
                api_key=self.api_key if not use_vertex else None,
            )

            response = await client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )
            raw = (response.text or "").strip()
            import json
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(q).strip() for q in parsed if str(q).strip()][:count]
            elif isinstance(parsed, dict) and "suggestions" in parsed:
                return [str(q).strip() for q in parsed["suggestions"]][:count]
        except Exception as e:
            logger.warning(f"Failed to generate suggestions via Gemini ({e}). Falling back to pattern generator.")

        from ..agent import MockAgentProvider
        fallback = MockAgentProvider()
        return await fallback.generate_suggestions(page, brain, targets, count, client_config)



def get_llm_provider() -> LLMProvider:
    """Factory creating the configured LLM provider based on environment variables.

    Set LLM_PROVIDER=vertex to enable live Google Cloud Vertex AI calls.
    Defaults to MockLLMProvider for zero-config offline runs.
    """
    provider_type = os.getenv("LLM_PROVIDER", "mock").lower()
    logger.info(f"LLM Provider selected: {provider_type}")
    if provider_type in ("vertex", "vertexai", "gemini", "gcp"):
        return VertexAILLMProvider()
    
    return MockLLMProvider()
