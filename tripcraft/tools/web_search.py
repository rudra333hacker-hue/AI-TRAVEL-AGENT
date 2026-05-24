import asyncio
import logging
from typing import Dict, Any

logger = logging.getLogger("tripcraft")

async def search_web(query: str, max_results: int = 5) -> dict:
    """Search the web for real-time information. Use this to look up actual bus/train operators, prices, schedules, local transport options, or any current data.
    
    Args:
        query (str): The search query, e.g. 'bus from Mumbai to Goa price 2026' or 'Delhi to Jaipur train schedule'.
        max_results (int): Number of search results to return (1-10). Default is 5.
        
    Returns:
        dict: A dictionary containing query, results, result_count, summary, and optional errors/warnings.
    """
    try:
        max_results = min(max(1, int(max_results)), 10)
    except (ValueError, TypeError):
        max_results = 5

    try:
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

        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(_do_search, query, max_results),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            return {
                "query": query,
                "results": [],
                "result_count": 0,
                "summary": f"Web search for '{query}' timed out. Use your knowledge to provide the best answer.",
                "warning": "Web search timed out after 15 seconds.",
            }

        if not results:
            return {
                "query": query,
                "results": [],
                "result_count": 0,
                "summary": f"No web results found for '{query}'. Use your knowledge to provide the best answer.",
                "message": "No results found. Try a different search query.",
            }

        # Build a synthesized summary from titles + snippets
        summary_parts = []
        for r in results[:5]:
            title = r.get("title", "").strip()
            snippet = r.get("snippet", "").strip()
            if title and snippet:
                summary_parts.append(f"• {title}: {snippet}")
            elif snippet:
                summary_parts.append(f"• {snippet}")
        
        summary = "\n".join(summary_parts) if summary_parts else f"Found {len(results)} results but no clear summary."

        return {
            "query": query,
            "results": results,
            "result_count": len(results),
            "summary": summary,
        }

    except ImportError:
        logger.error("duckduckgo_search package not installed.")
        return {
            "query": query,
            "results": [],
            "result_count": 0,
            "summary": f"Web search unavailable. Use your knowledge to answer about '{query}'.",
            "warning": "Web search is currently unavailable on the server due to missing dependencies.",
            "error": "duckduckgo_search not installed."
        }
    except Exception as e:
        logger.error(f"Web search error: {e}")
        return {
            "query": query,
            "results": [],
            "result_count": 0,
            "summary": f"Web search failed for '{query}'. Use your knowledge to provide the best answer.",
            "warning": f"DuckDuckGo search failed: {str(e)}.",
            "error": str(e)
        }
