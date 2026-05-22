import asyncio
import httpx
import logging

logger = logging.getLogger("tripcraft")

async def request_with_retry(
    method: str,
    url: str,
    retries: int = 3,
    backoff_factor: float = 1.5,
    **kwargs
) -> httpx.Response:
    """
    Make an HTTP request with retry logic for transient errors (429, 5xx, or network issues).
    Uses backoff_factor to increase delay exponentially between retries.
    """
    delay = 1.0
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient() as client:
                # Set default timeout if not provided
                if "timeout" not in kwargs:
                    kwargs["timeout"] = 10.0
                
                response = await client.request(method, url, **kwargs)
                
                # Check for rate limits or server errors
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    response.raise_for_status()
                
                return response
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            last_exc = e
            if attempt == retries:
                logger.error(f"HTTP request failed after {retries} attempts: {e}")
                if isinstance(e, httpx.HTTPStatusError):
                    return e.response
                raise e
            
            wait_time = delay * (backoff_factor ** (attempt - 1))
            logger.warning(f"Request failed: {e}. Retrying in {wait_time:.2f}s... (Attempt {attempt}/{retries})")
            await asyncio.sleep(wait_time)
            
    if last_exc:
        raise last_exc
    raise RuntimeError("Request failed with unknown error")
