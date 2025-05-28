import aiohttp
import asyncio
import logging
from typing import List, Dict, Optional
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import os
from dotenv import load_dotenv

# load env vars if any
load_dotenv()

# setup logging
logger = structlog.get_logger()

class CloudResourceScanner:
    def __init__(self, base_url: str, api_key: str, max_concurrent_requests: int = 5, max_requests_per_second: float = 0.8):
        self.base_url = base_url
        self.api_key = api_key
        self.max_concurrent_requests = max_concurrent_requests
        self.session: Optional[aiohttp.ClientSession] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._rate_limit_lock = asyncio.Lock()
        self._last_request_time = 0
        self._min_request_interval = 1.0 / max_requests_per_second  # wait time between requests

    async def initialize(self) -> 'CloudResourceScanner':
        # setup session and semaphore
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(headers={"api-key": self.api_key})
        if not self._semaphore:
            self._semaphore = asyncio.Semaphore(self.max_concurrent_requests)
        logger.info("scanner_initialized", base_url=self.base_url, max_rps=1.0/self._min_request_interval)
        return self

    async def close(self) -> None:
        # cleanup session
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
        logger.info("scanner_closed")

    @retry(
        retry=retry_if_exception_type((aiohttp.ClientResponseError, aiohttp.ServerDisconnectedError)),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(5),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )
    async def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        # main request handler with rate limiting and retries
        logger.info("http_request_start", endpoint=endpoint, params=params)
        
        # rate limiting - make sure we don't hit limits
        async with self._rate_limit_lock:
            current_time = asyncio.get_event_loop().time()
            time_since_last = current_time - self._last_request_time
            if time_since_last < self._min_request_interval:
                sleep_time = self._min_request_interval - time_since_last
                logger.debug("rate_limiting_sleep", sleep_time=sleep_time)
                await asyncio.sleep(sleep_time)
            self._last_request_time = asyncio.get_event_loop().time()

        if not self.session or self.session.closed:
            await self.initialize()

        async with self._semaphore:
            try:
                async with self.session.get(f"{self.base_url}{endpoint}", params=params) as response:
                    logger.info("http_response", endpoint=endpoint, status=response.status)
                    
                    if response.status == 429:
                        logger.warning("rate_limit_exceeded", endpoint=endpoint, retry_after=response.headers.get('Retry-After'))
                    elif response.status == 401:
                        logger.error("authentication_failed", endpoint=endpoint)
                    elif response.status == 404:
                        logger.warning("resource_not_found", endpoint=endpoint)
                    
                    response.raise_for_status()
                    result = await response.json()
                    logger.info("http_request_success", endpoint=endpoint, response_size=len(str(result)))
                    return result
                    
            except aiohttp.ClientResponseError as e:
                logger.warning("http_error", endpoint=endpoint, status=e.status, message=str(e))
                if e.status in [401, 404]:
                    # don't retry these - they won't get better
                    raise
                else:
                    # let tenacity handle retries
                    raise
            except aiohttp.ServerDisconnectedError as e:
                logger.warning("server_disconnected", endpoint=endpoint, error=str(e))
                raise

    async def check_health(self) -> bool:
        # basic health check
        try:
            response = await self._make_request("/health")
            is_healthy = response.get("status") == "healthy"
            logger.info("health_check_result", healthy=is_healthy)
            return is_healthy
        except Exception as e:
            logger.error("health_check_failed", error=str(e))
            return False

    async def list_resources(self, page: int = 1, limit: int = 10) -> Dict:
        # get paginated resource list
        logger.info("listing_resources", page=page, limit=limit)
        return await self._make_request("/resources", params={"page": page, "limit": limit})

    async def get_resource(self, resource_id: str) -> Dict:
        # fetch single resource by id
        logger.info("fetching_resource", resource_id=resource_id)
        return await self._make_request(f"/resources/{resource_id}")

    async def scan_all_resources(self) -> List[Dict]:
        # get everything across all pages
        logger.info("starting_full_scan")
        
        # get first page to see how many total pages
        first_page = await self.list_resources(page=1)
        total_pages = first_page["total_pages"]
        
        all_resources = first_page["resources"]
        logger.info("scan_progress", current_resources=len(all_resources), total_pages=total_pages)
        
        if total_pages > 1:
            # fetch remaining pages concurrently but controlled
            async def fetch_page(page_num):
                try:
                    result = await self.list_resources(page=page_num)
                    logger.debug("page_fetched", page=page_num, resources=len(result.get("resources", [])))
                    return result
                except Exception as e:
                    logger.error("page_fetch_error", page=page_num, error=str(e))
                    return None

            # batch requests to avoid overwhelming server
            for i in range(2, total_pages + 1, min(3, self.max_concurrent_requests)):
                page_numbers = range(i, min(i + 3, total_pages + 1))
                logger.info("fetching_page_batch", pages=list(page_numbers))
                tasks = [fetch_page(page) for page in page_numbers]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for result in results:
                    if isinstance(result, dict) and "resources" in result:
                        all_resources.extend(result["resources"])

        logger.info("scan_completed", total_resources=len(all_resources), total_pages=total_pages)
        return all_resources

    async def get_sensitive_resources(self) -> List[Dict]:
        # filter for resources with sensitive data flag
        logger.info("scanning_for_sensitive_data")
        all_resources = await self.scan_all_resources()
        sensitive_resources = [r for r in all_resources if r.get("sensitive_data", False)]
        logger.info("sensitive_scan_completed", 
                   sensitive_count=len(sensitive_resources), 
                   total_scanned=len(all_resources),
                   sensitive_percentage=round(len(sensitive_resources)/len(all_resources)*100, 1) if all_resources else 0)
        return sensitive_resources 