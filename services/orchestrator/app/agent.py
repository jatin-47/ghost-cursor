"""Google ADK Agent Definition and Mock Provider.

Defines the Ghost Cursor agent with fixed frontend action tools
and a mock provider for local testing without GCP credentials.
"""

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Frontend Action Tool Functions
# ---------------------------------------------------------------------------
def navigate(target_page: str, explanation: str) -> dict:
    """Navigate to another page within the application."""
    return {"action": "navigate", "target_page": target_page, "explanation": explanation}


def click(target_id: str, explanation: str) -> dict:
    """Click a registered button, link, or tab."""
    return {"action": "click", "target_id": target_id, "explanation": explanation}


def fill_input(target_id: str, value: str, explanation: str) -> dict:
    """Type or set a value in a registered input or textarea."""
    return {"action": "fill_input", "target_id": target_id, "value": value, "explanation": explanation}


def select_option(target_id: str, option: str, explanation: str) -> dict:
    """Select an option from a dropdown."""
    return {"action": "select_option", "target_id": target_id, "option": option, "explanation": explanation}


def toggle_switch(target_id: str, state: bool, explanation: str) -> dict:
    """Toggle a switch or checkbox to true or false."""
    return {"action": "toggle_switch", "target_id": target_id, "state": state, "explanation": explanation}


def guided_tour(steps: List[Dict[str, str]]) -> dict:
    """Run an interactive guided tour spotlighting elements with explanations."""
    return {"action": "guided_tour", "steps": steps}


def ask_clarification(question: str, options: List[str]) -> dict:
    """Ask the user a clarifying question before proceeding."""
    return {"action": "ask_clarification", "question": question, "options": options}


# All frontend tool functions
FRONTEND_TOOLS = [navigate, click, fill_input, select_option, toggle_switch, guided_tour, ask_clarification]


from dataclasses import dataclass, field
import copy

@dataclass
class GhostAgent:
    """Represents a configured Ghost Cursor agent instance."""
    name: str
    model: str
    instruction: str
    tools: List[Any]
    brain_content: str = ""
    available_targets: List[str] = field(default_factory=list)
    current_context: Dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)


FRONTEND_ACTION_TOOLS = [
    {
        "name": "navigate",
        "description": "Navigate to another page within the application",
        "parameters": {
            "type": "object",
            "properties": {
                "target_page": {"type": "string", "description": "Page identifier or path to navigate to"},
                "explanation": {"type": "string", "description": "Why this navigation is needed"},
            },
            "required": ["target_page", "explanation"],
        },
    },
    {
        "name": "click",
        "description": "Click a registered button, link, or tab",
        "parameters": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "description": "Logical target ID"},
                "explanation": {"type": "string", "description": "Why this click is needed"},
            },
            "required": ["target_id", "explanation"],
        },
    },
    {
        "name": "fill_input",
        "description": "Type or set a value in a registered input or textarea",
        "parameters": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "description": "Logical target ID"},
                "value": {"type": "string", "description": "Value to type or enter"},
                "explanation": {"type": "string", "description": "Why this input is needed"},
            },
            "required": ["target_id", "value", "explanation"],
        },
    },
    {
        "name": "select_option",
        "description": "Select an option from a dropdown or select element",
        "parameters": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "description": "Logical target ID"},
                "option": {"type": "string", "description": "Option value to select"},
                "explanation": {"type": "string", "description": "Why this selection is needed"},
            },
            "required": ["target_id", "option", "explanation"],
        },
    },
    {
        "name": "toggle_switch",
        "description": "Toggle a switch or checkbox to true or false",
        "parameters": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "description": "Logical target ID"},
                "state": {"type": "boolean", "description": "Desired state (true/false)"},
                "explanation": {"type": "string", "description": "Why this toggle is needed"},
            },
            "required": ["target_id", "state", "explanation"],
        },
    },
    {
        "name": "guided_tour",
        "description": "Run an interactive guided tour spotlighting elements with explanations",
        "parameters": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "target_id": {"type": "string"},
                            "message": {"type": "string"},
                        },
                        "required": ["target_id", "message"],
                    },
                },
            },
            "required": ["steps"],
        },
    },
    {
        "name": "ask_clarification",
        "description": "Ask the user a clarifying question before proceeding",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "maxLength": 1000},
                "options": {"type": "array", "items": {"type": "string", "maxLength": 200}, "maxItems": 10},
            },
            "required": ["question", "options"],
        },
    },
]


def _format_targets(targets: list) -> str:
    if not targets:
        return "No targets registered on current page."
    lines = []
    for target in targets:
        if isinstance(target, str):
            lines.append(f"  - {target}")
        elif isinstance(target, dict):
            name = target.get("name", target.get("id", "unknown"))
            desc = target.get("description", "")
            lines.append(f"  - {name}" + (f" ({desc})" if desc else ""))
    return "\n".join(lines) if lines else "No targets registered."


def create_ghost_agent(
    brain_content: str,
    available_targets: list,
    current_context: dict,
    customer_backend_tools: Optional[list] = None,
) -> GhostAgent:
    """Build the Ghost Cursor agent representation."""
    instruction = f"""You are Ghost Cursor, an autonomous UI co-pilot.
You assist users by invoking frontend action tools to operate the web interface,
or querying backend knowledge tools for customer database/business context.

### BUSINESS KNOWLEDGE:
{brain_content}

### REGISTERED AVAILABLE UI TARGETS:
{_format_targets(available_targets)}

### LIVE CLIENT CONTEXT:
Current Page: {current_context.get('page', 'unknown')}
Values on Screen: {current_context.get('values', {})}

### RULES:
1. Only use target IDs that are explicitly registered.
2. If an action requires moving to another page first, invoke 'navigate' before interacting with page targets.
3. If user intent is ambiguous or missing required fields, invoke 'ask_clarification'.
4. Query customer backend tools whenever domain data is needed before taking action.
5. Only return ONE tool invocation type per response turn.
"""
    tools = copy.deepcopy(FRONTEND_ACTION_TOOLS)
    if customer_backend_tools:
        for t in customer_backend_tools:
            if hasattr(t, "model_dump"):
                tools.append(t.model_dump())
            elif hasattr(t, "dict"):
                tools.append(t.dict())
            else:
                tools.append(t)

    return GhostAgent(
        name="ghost_cursor_orchestrator",
        model="gemini-2.0-flash",
        instruction=instruction,
        tools=tools,
        brain_content=brain_content or "",
        available_targets=available_targets or [],
        current_context=current_context or {},
    )


def create_adk_agent(
    brain_content: str,
    available_targets: list,
    current_context: dict,
    customer_backend_tools: Optional[list] = None,
    model: Any = "gemini-2.0-flash",
) -> Any:
    """Instantiate Google ADK Agent with long-running tools."""
    from google.adk.agents.llm_agent import LlmAgent
    from .llm.adk import build_adk_tools

    ghost_agent = create_ghost_agent(
        brain_content=brain_content,
        available_targets=available_targets,
        current_context=current_context,
        customer_backend_tools=customer_backend_tools,
    )
    adk_tools = build_adk_tools(ghost_agent.tools)

    return LlmAgent(
        name=ghost_agent.name,
        model=model,
        instruction=lambda _ctx: ghost_agent.instruction,
        tools=adk_tools,
    )


class MockAgentProvider:
    """Deterministic mock agent that recognizes common patterns.

    Returns structured tool calls matching expected patterns
    for local testing without real GCP/Gemini credentials.
    """

    def _match_patterns(
        self,
        message: str,
        context: dict,
        targets: list,
        client_config: Optional[Any] = None,
        history: Optional[list] = None,
        original_message: Optional[str] = None,
    ) -> dict:
        """Pattern-match user messages to generate realistic tool call responses."""
        from .guardrails import is_out_of_scope, get_guardrail_rejection

        app_name = "this application"
        refusal_msg = None
        if client_config:
            if hasattr(client_config, "app_name"):
                app_name = client_config.app_name or "this application"
                refusal_msg = client_config.get_refusal_message()
            elif isinstance(client_config, dict):
                app_name = client_config.get("appName") or client_config.get("app_name") or "this application"
                refusal_msg = client_config.get("outOfScopeMessage") or client_config.get("out_of_scope_message")

        # --- Guardrail check for out-of-scope queries ---
        if is_out_of_scope(message):
            return get_guardrail_rejection(refusal_msg)

        msg = message.lower().strip()
        orig = (original_message or "").lower().strip()
        page = context.get("page", "")

        # --- Clarification answer: Checkout shipping address ---
        if ("checkout" in orig or "address" in orig) and ("123" in msg or "main" in msg or "saved" in msg or "address" in msg or "new" in msg):
            actions = []
            if page != "checkout":
                actions.append({
                    "id": "act_1",
                    "tool": "navigate",
                    "parameters": {"target_page": "checkout", "explanation": "Navigating to checkout page."},
                })
            act_offset = len(actions) + 1
            actions.extend([
                {"id": f"act_{act_offset}", "tool": "fill_input", "parameters": {"target_id": "checkout.address.street", "value": "123 Main St", "explanation": "Filling in street address."}},
                {"id": f"act_{act_offset+1}", "tool": "fill_input", "parameters": {"target_id": "checkout.address.city", "value": "New York", "explanation": "Filling in city."}},
                {"id": f"act_{act_offset+2}", "tool": "fill_input", "parameters": {"target_id": "checkout.address.state", "value": "NY", "explanation": "Filling in state."}},
                {"id": f"act_{act_offset+3}", "tool": "fill_input", "parameters": {"target_id": "checkout.address.zip", "value": "10001", "explanation": "Filling in zip code."}},
            ])
            return {
                "reply": "I'll fill in the shipping address for you.",
                "actions": actions,
                "status": "awaiting_actions",
            }

        # --- Clarification answer: Order tracking selection ---
        if ("order" in orig or "track" in orig) and "sh-" in msg:
            import re
            order_match = re.search(r"(SH-\d+|order\s*#?\s*\d+)", msg, re.IGNORECASE)
            if order_match:
                return {
                    "reply": f"Let me look up {order_match.group(1)} for you.",
                    "toolCalls": [{"id": "tc_1", "tool": "lookup_order", "parameters": {"order_id": order_match.group(1)}}],
                    "actions": [],
                    "status": "awaiting_tools",
                }

        # --- Dark mode / Light mode / theme ---
        if any(kw in msg for kw in ["dark mode", "dark theme", "switch theme", "appearance", "light mode", "light theme", "light"]):
            actions = []
            is_dark = "dark" in msg
            if "light" in msg:
                is_dark = False
            theme_name = "Dark" if is_dark else "Light"
            if page != "settings":
                actions.append({
                    "id": "act_1",
                    "tool": "navigate",
                    "parameters": {"target_page": "settings", "explanation": f"Navigating to Settings to change appearance to {theme_name} Mode."},
                })
            actions.append({
                "id": "act_2" if actions else "act_1",
                "tool": "toggle_switch",
                "parameters": {"target_id": "settings.theme_toggle", "state": is_dark, "explanation": f"Switching the appearance to {theme_name} Mode."},
            })
            return {
                "reply": f"I'll switch the appearance to {theme_name} Mode for you.",
                "actions": actions,
                "status": "awaiting_actions",
            }

        # --- Add to cart ---
        if "add" in msg and "cart" in msg:
            actions = []
            # Extract size
            import re
            size_match = re.search(r"size\s*(\d+\.?\d*)", msg)
            size = size_match.group(1) if size_match else "10"

            # Extract product
            product_page = "products/air-max-90"  # default
            if "jordan" in msg:
                product_page = "products/air-jordan-1"
            elif "ultra" in msg or "boost" in msg:
                product_page = "products/ultra-boost"
            elif "550" in msg or "new balance" in msg:
                product_page = "products/nb-550"
            elif "chuck" in msg or "converse" in msg:
                product_page = "products/chuck-taylor"
            elif "dunk" in msg:
                product_page = "products/dunk-low"

            if not page.startswith("product"):
                actions.append({
                    "id": "act_1",
                    "tool": "navigate",
                    "parameters": {"target_page": product_page, "explanation": f"Navigating to the product page."},
                })

            act_offset = len(actions) + 1
            actions.append({
                "id": f"act_{act_offset}",
                "tool": "click",
                "parameters": {"target_id": f"product.size.{size}", "explanation": f"Selecting size {size}."},
            })
            actions.append({
                "id": f"act_{act_offset + 1}",
                "tool": "click",
                "parameters": {"target_id": "product.add_to_cart_btn", "explanation": "Adding the item to your cart."},
            })
            return {
                "reply": f"I'll add this item in size {size} to your cart.",
                "actions": actions,
                "status": "awaiting_actions",
            }

        # --- Checkout ---
        if "checkout" in msg:
            return {
                "reply": None,
                "questions": [{"question": "Which shipping address should I use?", "options": ["123 Main St, New York, NY 10001 (saved)", "Enter a new address"]}],
                "actions": [],
                "status": "awaiting_answer",
            }

        # --- Order tracking ---
        if "order" in msg and ("track" in msg or "where" in msg or "status" in msg):
            import re
            order_match = re.search(r"(SH-\d+|order\s*#?\s*\d+)", msg, re.IGNORECASE)
            if order_match:
                return {
                    "reply": f"Let me look up {order_match.group(1)} for you.",
                    "toolCalls": [{"id": "tc_1", "tool": "lookup_order", "parameters": {"order_id": order_match.group(1)}}],
                    "actions": [],
                    "status": "awaiting_tools",
                }
            return {
                "reply": None,
                "questions": [{"question": "Which order would you like to track?", "options": ["SH-1024", "SH-1025", "SH-1026"]}],
                "actions": [],
                "status": "awaiting_answer",
            }

        # --- Guided tour ---
        is_tour_query = (
            "tour" in msg
            or "walkthrough" in msg
            or "show me around" in msg
            or "guide me" in msg
            or ("guide" in msg and ("how" in msg or "show" in msg or "app" in msg or "store" in msg or "site" in msg))
            or ("how" in msg and ("track" in msg or "return" in msg or "find" in msg or "order" in msg))
        )
        if is_tour_query:
            if "order" in msg or "return" in msg or page == "orders":
                return {
                    "reply": "Let me show you how to track orders and returns! Follow this guided tour.",
                    "actions": [{
                        "id": "act_1",
                        "tool": "guided_tour",
                        "parameters": {"steps": [
                            {"target_id": "nav.orders", "message": "First, click on Orders in the navigation bar.", "page": "/orders"},
                            {"target_id": "orders.item.SH-1024", "message": "Here is your most recent order — SH-1024 with status and progress timeline.", "page": "/orders"},
                            {"target_id": "orders.tracking_link", "message": "Click this link to see real-time carrier tracking details and return options.", "page": "/orders"},
                        ]},
                    }],
                    "status": "awaiting_actions",
                }
            elif "setting" in msg or "theme" in msg or page == "settings":
                return {
                    "reply": "Here is a guided tour of the Settings page!",
                    "actions": [{
                        "id": "act_1",
                        "tool": "guided_tour",
                        "parameters": {"steps": [
                            {"target_id": "nav.settings", "message": "Settings can be reached from the top navigation bar.", "page": "/settings"},
                            {"target_id": "settings.theme_toggle", "message": "Toggle between Light and Dark mode appearance.", "page": "/settings"},
                            {"target_id": "settings.notif_email", "message": "Customize your notification channels (Email, SMS, and Push).", "page": "/settings"},
                            {"target_id": "settings.saved_address", "message": "Review and update your default shipping address.", "page": "/settings"},
                        ]},
                    }],
                    "status": "awaiting_actions",
                }
            elif "cart" in msg or page == "cart":
                return {
                    "reply": "Here is a guided tour of your shopping cart!",
                    "actions": [{
                        "id": "act_1",
                        "tool": "guided_tour",
                        "parameters": {"steps": [
                            {"target_id": "nav.cart", "message": "Access your cart anytime from the navigation header.", "page": "/cart"},
                            {"target_id": "cart.promo_code", "message": "Enter discount coupon codes like SAVE20 or FREESHIP.", "page": "/cart"},
                            {"target_id": "cart.apply_promo", "message": "Click Apply Promo to instantly discount your total.", "page": "/cart"},
                            {"target_id": "cart.checkout_btn", "message": "Click checkout when ready to proceed to shipping and payment.", "page": "/cart"},
                        ]},
                    }],
                    "status": "awaiting_actions",
                }
            elif "checkout" in msg or page == "checkout":
                return {
                    "reply": "Let me walk you through the checkout process!",
                    "actions": [{
                        "id": "act_1",
                        "tool": "guided_tour",
                        "parameters": {"steps": [
                            {"target_id": "checkout.address.street", "message": "Provide your delivery street address.", "page": "/checkout"},
                            {"target_id": "checkout.address.city", "message": "Enter your delivery city, state, and postal code.", "page": "/checkout"},
                            {"target_id": "checkout.place_order", "message": "Review order totals and click Place Order to finalize.", "page": "/checkout"},
                        ]},
                    }],
                    "status": "awaiting_actions",
                }
            elif "product" in msg or page in ("products", "product"):
                return {
                    "reply": "Here is a guided tour of this product page!",
                    "actions": [{
                        "id": "act_1",
                        "tool": "guided_tour",
                        "parameters": {"steps": [
                            {"target_id": "product.title", "message": "View product title, style details, and current price."},
                            {"target_id": "product.size.10", "message": "Select your shoe size from real-time available stock."},
                            {"target_id": "product.add_to_cart_btn", "message": "Click Add to Cart to add this item to your bag."},
                        ]},
                    }],
                    "status": "awaiting_actions",
                }
            else:
                return {
                    "reply": "Welcome to ShopHive! Let me give you a quick guided tour of our store.",
                    "actions": [{
                        "id": "act_1",
                        "tool": "guided_tour",
                        "parameters": {"steps": [
                            {"target_id": "catalog.product.air-max-90", "message": "Footwear Catalog: Browse sneakers and click any pair to choose sizes.", "page": "/"},
                            {"target_id": "nav.cart", "message": "Shopping Cart: Review your items, apply promo codes, and checkout.", "page": "/"},
                            {"target_id": "nav.orders", "message": "Orders & Tracking: Track live package shipments and manage returns.", "page": "/"},
                            {"target_id": "nav.settings", "message": "Settings: Switch to Dark Mode and customize notification preferences.", "page": "/"},
                        ]},
                    }],
                    "status": "awaiting_actions",
                }

        # --- Stock / sizes ---
        if "size" in msg or "stock" in msg or "available" in msg:
            values = context.get("values", {})
            return {
                "reply": "Based on the current page, here are the available sizes: 7, 7.5, 8, 8.5, 9, 9.5, 10, 10.5, 11, 11.5, 12, 13. Would you like me to add one to your cart?",
                "actions": [],
                "status": "completed",
            }

        # --- Fill form ---
        if "fill" in msg or "address" in msg:
            actions = []
            if page != "checkout":
                actions.append({
                    "id": "act_1",
                    "tool": "navigate",
                    "parameters": {"target_page": "checkout", "explanation": "Navigating to checkout page."},
                })
            act_offset = len(actions) + 1
            actions.extend([
                {"id": f"act_{act_offset}", "tool": "fill_input", "parameters": {"target_id": "checkout.address.street", "value": "123 Main St", "explanation": "Filling in street address."}},
                {"id": f"act_{act_offset+1}", "tool": "fill_input", "parameters": {"target_id": "checkout.address.city", "value": "New York", "explanation": "Filling in city."}},
                {"id": f"act_{act_offset+2}", "tool": "fill_input", "parameters": {"target_id": "checkout.address.state", "value": "NY", "explanation": "Filling in state."}},
                {"id": f"act_{act_offset+3}", "tool": "fill_input", "parameters": {"target_id": "checkout.address.zip", "value": "10001", "explanation": "Filling in zip code."}},
            ])
            return {
                "reply": "I'll fill in the shipping address for you.",
                "actions": actions,
                "status": "awaiting_actions",
            }

        # --- Default: contextual text reply ---
        page_descriptions = {
            "dashboard": "You're on the ShopHive home page. I can see the product catalog with sneakers and sportswear. Would you like me to help you find something specific or add items to your cart?",
            "products": "You're viewing a product detail page. I can see the available sizes and pricing. Would you like me to add this item to your cart?",
            "cart": "You're on the cart page. I can see your cart items and totals. Would you like to proceed to checkout or apply a promo code?",
            "checkout": "You're on the checkout page. I can help fill in your shipping address and complete the order.",
            "orders": "You're viewing your order history. I can help you track a specific order or show you how returns work.",
            "settings": "You're on the settings page. I can help you change your theme, notification preferences, or update your shipping address.",
        }
        generic_default = (
            f"I'm Ghost Cursor, your AI co-pilot for {app_name}! I can help you navigate, "
            "perform actions, and answer questions. Just tell me what you'd like to do."
        )
        default_reply = page_descriptions.get(page, generic_default) if app_name == "ShopHive" else generic_default
        return {
            "reply": default_reply,
            "actions": [],
            "status": "completed",
        }

    async def generate(
        self,
        message: str,
        context: dict,
        brain: str,
        targets: list,
        tools: list,
        client_config: Optional[Any] = None,
        history: Optional[list] = None,
        original_message: Optional[str] = None,
    ) -> dict:
        """Generate a mock agent response based on pattern matching."""
        result = self._match_patterns(message, context, targets, client_config, history, original_message)

        # Ensure all required fields
        return {
            "reply": result.get("reply"),
            "questions": result.get("questions", []),
            "actions": result.get("actions", []),
            "toolCalls": result.get("toolCalls", []),
            "status": result.get("status", "completed"),
        }

    async def continue_with_results(self, run_state: dict, results: list) -> dict:
        """Continue generation after receiving tool/action results."""
        # For tool results, generate a summary reply
        all_ok = all(r.get("ok", False) for r in results)
        if all_ok:
            is_tour = any("tour" in str(r.get("output", "")).lower() for r in results) or any(
                a.get("tool") == "guided_tour" for a in run_state.get("plan", {}).get("actions", [])
            )
            if is_tour:
                reply = "Tour completed! Let me know if you would like to explore anything else or perform any actions."
            else:
                outputs = [r.get("output", "") for r in results if r.get("output") and str(r.get("output")).lower() != "completed"]
                if outputs:
                    reply = f"Here's what I found: {'; '.join(str(o) for o in outputs)}"
                else:
                    reply = "Done! All actions completed successfully."
        else:
            errors = [r.get("error", "Unknown error") for r in results if not r.get("ok")]
            reply = f"Some actions couldn't be completed: {'; '.join(errors)}"

        return {
            "reply": reply,
            "questions": [],
            "actions": [],
            "toolCalls": [],
            "status": "completed",
        }

    async def generate_suggestions(
        self,
        page: str,
        brain: str,
        targets: list,
        count: int = 3,
        client_config: Optional[Any] = None,
    ) -> list[str]:
        """Generate contextual suggested questions for quick prompt chips."""
        page_lower = page.lower()
        if "product" in page_lower:
            return [
                "Take a guided tour of this product",
                "What sizes are available in stock?",
                "Can you add this item to my cart in size 10?",
            ][:count]
        elif "cart" in page_lower:
            return [
                "Take a guided tour of cart",
                "Can you apply promo code SAVE20?",
                "Take me to checkout",
            ][:count]
        elif "checkout" in page_lower:
            return [
                "Take a guided tour of checkout",
                "Fill in my shipping address",
                "Is shipping free for this order?",
            ][:count]
        elif "orders" in page_lower:
            return [
                "Show me how to track returns",
                "Where is my order SH-1024?",
                "How long does refund processing take?",
            ][:count]
        elif "settings" in page_lower:
            return [
                "Take a guided tour of settings",
                "Switch appearance to Dark Mode",
                "How do I update notification preferences?",
            ][:count]
        else:
            return [
                "Take a guided tour",
                "Show me popular running shoes",
                "Do you offer free shipping?",
            ][:count]


