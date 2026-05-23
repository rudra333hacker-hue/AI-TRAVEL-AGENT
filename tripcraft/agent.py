import json
from dataclasses import dataclass
from typing import AsyncGenerator

@dataclass
class StreamEvent:
    type: str       # thinking | tool_call | tool_result | content | error | done
    data: dict

    def json(self) -> str:
        return json.dumps(self.data, ensure_ascii=False)

class TripCraftAgent:
    MAX_ROUNDS = 10

    def __init__(self, llm, tools, session):
        self.llm = llm
        self.tools = tools
        self.session = session

    async def chat_stream(self, user_message: str) -> AsyncGenerator[StreamEvent, None]:
        # 1. Add user message to session history
        self.session.add_message({"role": "user", "content": user_message})

        yield StreamEvent("thinking", {"step": 0, "status": "Understanding your request..."})

        for round_num in range(1, self.MAX_ROUNDS + 1):
            try:
                # 2. Get completion from NIM (async, non-blocking)
                # If we have no tools available, definitions will be empty list, which is handled
                tools_def = self.tools.definitions if self.tools.definitions else None
                response = await self.llm.complete(
                    messages=self.session.full_messages(),
                    tools=tools_def,
                )
            except Exception as e:
                yield StreamEvent("error", {"message": f"NVIDIA NIM completion error: {str(e)}"})
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

            # 5. Process tool calls (NVIDIA NIM only supports single tool-calls at once)
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

            # Call tool function (all tools are async)
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


def _summarize(name: str, result: dict) -> str:
    """Human-readable one-liner for the SSE stream (not the full JSON)."""
    if "error" in result:
        return f"Error: {result['error']}"

    elif name == "search_flights":
        flights = result.get("flights", [])
        if flights:
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
        
    return "Done"