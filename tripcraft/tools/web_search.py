import asyncio
import logging

logger = logging.getLogger("tripcraft")

DEFINITION = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "Search the web for real-time information. Use this to look up actual bus/train operators, prices, schedules, local transport options, or any current data you need for trip planning.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query, e.g. 'bus from Mumbai to Goa price 2025' or 'Delhi to Jaipur train schedule and fare'"
                },
                "max_results": {
                    "type": "integer",
                    "default": 5,
                    "description": "Number of search results to return (1-10)"
                },
            },
            "required": ["query"],
        },
    },
}


async def search_web(query: str, max_results: int = 5) -> dict:
    """Search the web using DuckDuckGo. Free, no API key required."""
    try:
        max_results = min(max(1, int(max_results)), 10)

        from duckduckgo_search import DDGS

        def _do_search(q: str, max_res: int) -> list:
            """Synchronous DuckDuckGo search — runs in thread pool."""
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(q, max_results=max_res):
                    results.append({
                        "title": r.get("title", ""),
                        "snippet": r.get("body", ""),
                        "url": r.get("href", ""),
                    })
            return results

        results = await asyncio.to_thread(_do_search, query, max_results)

        if not results:
            return {
                "query": query,
                "results": [],
                "message": "No results found. Try a different search query.",
            }

        return {
            "query": query,
            "results": results,
            "result_count": len(results),
        }

    except ImportError:
        logger.error("duckduckgo_search package not installed. Run: pip install duckduckgo_search")
        return {
            "query": query,
            "results": [],
            "error": "Web search is not available. Please install duckduckgo_search package.",
        }
    except Exception as e:
        logger.error(f"Web search error: {e}")
        return {
            "query": query,
            "results": [],
            "error": f"Web search failed: {str(e)}. Suggest the user search manually.",
        }
