import json
import re
import asyncio
from dataclasses import dataclass
from typing import AsyncGenerator

from tripcraft.intake import should_ask_tier1

@dataclass
class StreamEvent:
    type: str       # thinking | tool_call | tool_result | content | error | done
    data: dict

    def json(self) -> str:
        return json.dumps(self.data, ensure_ascii=False)

class TripCraftAgent:
    MAX_ROUNDS = 8

    def __init__(self, llm, tools, session):
        self.llm = llm
        self.tools = tools
        self.session = session

    async def chat_stream(self, user_message: str, images: list[str] | None = None) -> AsyncGenerator[StreamEvent, None]:
        # ── Raw JSON Dump Parsing ──
        try:
            parsed = json.loads(user_message)
            if isinstance(parsed, (dict, list)):
                user_message = f"User uploaded raw JSON context:\n```json\n{json.dumps(parsed, indent=2, ensure_ascii=False)}\n```"
        except Exception:
            pass

        # ── Multimodal Content Structuring ──
        if images:
            content_list = [{"type": "text", "text": user_message}]
            for img in images:
                content_list.append({
                    "type": "image_url",
                    "image_url": {"url": self._format_image_url(img)}
                })
            user_payload = {"role": "user", "content": content_list}
        else:
            user_payload = {"role": "user", "content": user_message}

        # 1. Add user message to session history
        self.session.add_message(user_payload)

        yield StreamEvent("thinking", {"step": 0, "status": "Understanding your request..."})

        # ── PHASE 1: Deterministic Tier 1 Intake Enforcement ──────────────────
        # Before calling the LLM at all, check if mandatory intake data is missing.
        # This ensures the agent always asks the right questions regardless of model.
        should_intercept, tier1_question = should_ask_tier1(self.session.messages)
        if should_intercept and tier1_question:
            yield StreamEvent("content", {"text": tier1_question})
            yield StreamEvent("done", {
                "session_id": self.session.id,
                "rounds": 0,
                "tools_called": 0,
            })
            # Add the question to history so the LLM has context
            self.session.add_message({"role": "assistant", "content": tier1_question})
            return

        # ── PHASE 2: Normal LLM ReAct loop ────────────────────────────────────
        total_tools_called = 0
        for round_num in range(1, self.MAX_ROUNDS + 1):
            try:
                tools_def = self.tools.definitions if self.tools.definitions else None

                # Callback that emits a thinking event during retry waits
                # Use default-arg capture to avoid late-binding closure issues in a loop
                retry_events: list = []
                async def on_retry(attempt, wait_time, reason,
                                   _events=retry_events, _rn=round_num):
                    msg = f"⏳ {reason.capitalize()} — retrying in {wait_time:.0f}s (attempt {attempt}/4)..."
                    _events.append(StreamEvent("thinking", {"status": msg, "step": _rn}))

                response = await self.llm.complete(
                    messages=self.session.full_messages(),
                    tools=tools_def,
                    on_retry=on_retry,
                )
                # Flush any retry-status thinking events
                for ev in retry_events:
                    yield ev

            except Exception as e:
                err_str = str(e)
                # Friendly message for rate limit vs other errors
                if "429" in err_str or "too many requests" in err_str.lower() or "rate limit" in err_str.lower():
                    friendly = (
                        "⚠️ **Too many requests** — the AI provider is currently rate-limiting us. "
                        "Please wait a moment and try again. Your session is still active."
                    )
                elif "timeout" in err_str.lower() or "timed out" in err_str.lower():
                    friendly = (
                        "⏱️ **Request timed out** — the AI took too long to respond. "
                        "Please try again, or simplify your query."
                    )
                elif "api key" in err_str.lower() or "401" in err_str or "403" in err_str:
                    friendly = (
                        "🔑 **Authentication error** — the API key may be invalid or expired. "
                        "Please check the server configuration."
                    )
                else:
                    friendly = (
                        f"❌ **Something went wrong** — the AI could not process your request right now. "
                        f"Please try again in a moment."
                    )
                yield StreamEvent("content", {"text": friendly})
                yield StreamEvent("done", {
                    "session_id": self.session.id,
                    "rounds": round_num,
                    "tools_called": total_tools_called,
                })
                return

            msg = response.choices[0].message

            # 3. Add assistant message to session history
            self.session.add_message(self._serialize(msg))

            # 4. Final text response (no tool calls or model decided to end)
            if not msg.tool_calls:
                text = msg.content or ""
                # Backend fallback: if LLM didn't generate follow-up chips, append them
                if "(followup:" not in text:
                    text = _append_fallback_chips(text, self.session.messages)
                yield StreamEvent("content", {"text": text})
                yield StreamEvent("done", {
                    "session_id": self.session.id,
                    "rounds": round_num,
                    "tools_called": total_tools_called,
                })
                return

            # 5. Process ALL tool calls concurrently in parallel
            async def run_single_tool(tc):
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except Exception as parse_err:
                    args = {}
                    return tc.id, name, {"error": f"Failed to parse tool args: {parse_err}"}, args

                # Validate arguments
                validation_error = _validate_args(name, args, self.session.messages)
                if validation_error:
                    result = {"error": validation_error}
                else:
                    result = await self.tools.execute(name, args)

                # Enrich empty results
                result = _enrich_empty_result(name, result, args)
                return tc.id, name, result, args

            # Stream tool calls
            for tc in msg.tool_calls:
                total_tools_called += 1
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}
                yield StreamEvent("tool_call", {
                    "name": tc.function.name,
                    "args": args,
                    "step": round_num
                })

            # Gather execution concurrently
            tool_execution_results = await asyncio.gather(*(run_single_tool(tc) for tc in msg.tool_calls))

            # Stream results and add to message history
            for tc_id, name, result, args in tool_execution_results:
                yield StreamEvent("tool_result", {
                    "name": name,
                    "summary": _summarize(name, result),
                    "step": round_num,
                })
                self.session.add_message({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

        # Safeguard if loop limit reached
        yield StreamEvent("content", {
            "text": (
                "⚠️ **I needed more steps than expected** to plan your trip. "
                "Please try rephrasing your request, or ask me to focus on one part at a time "
                "(e.g. \"Just show me transport options\" or \"Find hotels only\")."
            )
        })
        yield StreamEvent("done", {
            "session_id": self.session.id,
            "rounds": self.MAX_ROUNDS,
            "tools_called": total_tools_called,
        })

    @staticmethod
    def _serialize(msg) -> dict:
        d = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        return d

    @staticmethod
    def _format_image_url(img_str: str) -> str:
        if img_str.startswith(("http://", "https://")):
            return img_str
        if img_str.startswith("data:image/"):
            return img_str
        return f"data:image/jpeg;base64,{img_str}"


def _validate_args(name: str, args: dict, messages: list) -> str | None:
    """Validate tool arguments — prevent past dates."""

    # Date validation — reject dates before 2026
    date_params = ["check_in", "check_out", "departure_date", "return_date"]
    for param in date_params:
        if param in args and args[param]:
            val = str(args[param])
            match = re.match(r"^(\d{4})-\d{2}-\d{2}$", val)
            if match:
                year = int(match.group(1))
                if year < 2026:
                    return (
                        f"Validation Error: The year in {param} '{val}' is {year}, "
                        f"which is in the past. The current year is 2026. "
                        f"Please use dates in 2026 or later."
                    )

    return None


def _enrich_empty_result(name: str, result: dict, args: dict) -> dict:
    """If a tool returned empty/sparse results, add a hint enforcing truthfulness and transparent estimates."""
    if "error" in result:
        result["_hint"] = (
            f"The {name} tool encountered a live API error: {result.get('error')}. "
            f"Please be completely honest and transparent with the user: explicitly state that the live "
            f"tool query failed or is currently unavailable, and provide your best general travel knowledge "
            f"estimates instead, clearly labeling them as estimated fallback recommendations."
        )
        return result

    empty_checks = {
        "search_flights": lambda r: not r.get("flights"),
        "search_hotels": lambda r: not r.get("hotels"),
        "search_places": lambda r: not r.get("places"),
        "search_transportation": lambda r: not r.get("options"),
        "search_web": lambda r: r.get("result_count", 0) == 0,
    }

    check = empty_checks.get(name)
    if check and check(result):
        query_info = ", ".join(f"{k}={v}" for k, v in args.items() if v) if args else name
        result["_hint"] = (
            f"No live results were returned for {query_info}. "
            f"Be completely truthful and straightforward: explicitly inform the user that live/real-time "
            f"data was not found, and provide typical estimates, recommendations, or suggestions from your "
            f"general knowledge, making sure to explicitly label them as general estimates."
        )

    return result


def _summarize(name: str, result: dict) -> str:
    """Human-readable one-liner for the SSE stream."""
    if "error" in result:
        return f"Error: {result['error']}"

    elif name == "search_flights":
        flights = result.get("flights", [])
        if flights:
            # Prefer INR prices if available
            inr_prices = [f.get("price_inr") for f in flights if f.get("price_inr")]
            if inr_prices:
                return f"{len(flights)} flights found (₹{min(inr_prices):,.0f}–₹{max(inr_prices):,.0f})"
            prices = [f["price"] for f in flights if "price" in f]
            if prices:
                return f"{len(flights)} flights found (${min(prices):,.2f}–${max(prices):,.2f})"
            return f"{len(flights)} flights found"
        return "No flights found"
        
    elif name == "search_transportation":
        options = result.get("options", [])
        if options:
            return f"Found {len(options)} transport modes (dist: {result.get('distance_km')} km)"
        return "No transportation options found"
        
    elif name == "search_hotels":
        hotels = result.get("hotels", [])
        if hotels:
            inr_prices = [h.get("price_inr") for h in hotels if h.get("price_inr")]
            if inr_prices:
                return f"{len(hotels)} hotels found (₹{min(inr_prices):,.0f}–₹{max(inr_prices):,.0f}/night)"
            prices = [h["price_per_night"] for h in hotels if "price_per_night" in h]
            if prices:
                return f"{len(hotels)} hotels found (${min(prices):,.2f}–${max(prices):,.2f}/night)"
            return f"{len(hotels)} hotels found"
        return "No hotels found"
        
    elif name == "get_weather_forecast":
        return result.get("summary", "Weather data retrieved")
        
    elif name == "search_places":
        places = result.get("places", [])
        return f"{len(places)} locations/attractions found"

    elif name == "search_web":
        count = result.get("result_count", 0)
        return f"Found {count} web results for '{result.get('query', '?')}'"

    return "Done"


def _append_fallback_chips(text: str, messages: list[dict]) -> str:
    """
    If the LLM response doesn't include follow-up chip syntax, append
    context-appropriate chips based on what the user has provided.
    Uses the intake extractor to figure out what's still missing.
    """
    from tripcraft.intake import extract_tier1_from_messages

    state = extract_tier1_from_messages(messages)
    missing = state.missing_fields

    chips = []

    if "origin" in missing:
        chips.append("[📍 Where should I start from?](followup:I'll be starting from Mumbai)")
    if "destination" in missing and not state._has_vibe:
        chips.append("[🌍 Suggest a destination](followup:I want to go to Goa)")
    if "dates" in missing:
        chips.append("[📅 Pick dates for me](followup:Plan for June, 4 days)")
    if "group_size" in missing:
        chips.append("[👥 I'm traveling solo](followup:I'm traveling solo)")
    if "budget" in missing:
        chips.append("[💰 Budget ₹10,000](followup:My budget is ₹10,000)")

    # Generic chips if nothing specific is missing
    if not chips:
        chips = [
            "[🍽️ Tell me about the food](followup:What are the best local dishes and restaurants there?)",
            "[💰 Break down the budget](followup:Give me a detailed cost breakdown)",
            "[🏨 Show me more hotels](followup:Show me more hotel options in different price ranges)",
        ]

    # Don't add chips if text is very short (like an error or one-liner)
    if len(text.strip()) < 30:
        return text

    # Append chips after a separator — only if they're not already present
    chip_section = "\n\n---\n" + "\n".join(chips)
    return text + chip_section