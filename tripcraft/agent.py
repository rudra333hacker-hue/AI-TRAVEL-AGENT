import json
import re
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
    MAX_ROUNDS = 12

    def __init__(self, llm, tools, session):
        self.llm = llm
        self.tools = tools
        self.session = session

    async def chat_stream(self, user_message: str) -> AsyncGenerator[StreamEvent, None]:
        # 1. Add user message to session history
        self.session.add_message({"role": "user", "content": user_message})

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
        for round_num in range(1, self.MAX_ROUNDS + 1):
            try:
                tools_def = self.tools.definitions if self.tools.definitions else None
                response = await self.llm.complete(
                    messages=self.session.full_messages(),
                    tools=tools_def,
                )
            except Exception as e:
                yield StreamEvent("error", {"message": f"LLM completion error: {str(e)}"})
                yield StreamEvent("done", {
                    "session_id": self.session.id,
                    "rounds": round_num,
                    "tools_called": round_num - 1,
                })
                return

            msg = response.choices[0].message

            # 3. Add assistant message to session history
            self.session.add_message(self._serialize(msg))

            # 4. Final text response (no tool calls or model decided to end)
            if not msg.tool_calls:
                yield StreamEvent("content", {"text": msg.content or ""})
                yield StreamEvent("done", {
                    "session_id": self.session.id,
                    "rounds": round_num,
                    "tools_called": round_num - 1,
                })
                return

            # 5. Process tool calls
            tc = msg.tool_calls[0]
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except Exception as parse_err:
                args = {}
                yield StreamEvent("error", {"message": f"Failed to parse tool args for '{name}': {parse_err}"})

            yield StreamEvent("tool_call", {
                "name": name, 
                "args": args, 
                "step": round_num
            })

            # Validate arguments
            validation_error = _validate_args(name, args, self.session.messages)
            if validation_error:
                result = {"error": validation_error}
            else:
                result = await self.tools.execute(name, args)

            yield StreamEvent("tool_result", {
                "name": name,
                "summary": _summarize(name, result),
                "step": round_num,
            })

            # Append tool result to history
            self.session.add_message({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

        # Safeguard if loop limit reached
        yield StreamEvent("error", {"message": "Reached maximum reasoning depth."})
        yield StreamEvent("done", {
            "session_id": self.session.id,
            "rounds": self.MAX_ROUNDS,
            "tools_called": self.MAX_ROUNDS,
        })

    @staticmethod
    def _serialize(msg) -> dict:
        d = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
            ]
        return d


def _validate_args(name: str, args: dict, messages: list) -> str | None:
    """Validate tool arguments — prevent past dates and fabricated origins."""

    # 1. Date validation — reject dates before 2026
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

    # 2. Extract user messages for context
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    user_text = " ".join(user_msgs).lower()

    # 3. Origin validation for transport/flights
    if name in ["search_flights", "search_transportation"]:
        origin = args.get("origin", "")
        if origin:
            words = [w for w in re.findall(r"\b\w+\b", origin.lower()) if len(w) > 2]
            if not words or not any(w in user_text for w in words):
                return (
                    "Validation Error: Starting location is missing or fabricated. "
                    "The user has not specified where they are starting/departing from. "
                    "Please stop and ask the user: 'Where will you be starting your trip from?'"
                )

    return None


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

    elif name == "geocode":
        return f"{result.get('name', '?')}, {result.get('country', '?')} ({result.get('latitude')}, {result.get('longitude')})"

    elif name == "search_web":
        count = result.get("result_count", 0)
        return f"Found {count} web results for '{result.get('query', '?')}'"

    return "Done"