import pytest
import pytest_asyncio
import asyncio
import os
import aiohttp
from tenacity import RetryError
from scanner import CloudResourceScanner

@pytest.fixture
def base_url():
    # use env var or default to docker-compose service name
    return os.getenv("BASE_URL", "http://mock-service:8000")

@pytest.fixture
def api_key():
    return "valid_api_key"

def handle_rate_limit_skip(e: Exception, test_name: str):
    # helper to skip tests when hitting rate limits
    if isinstance(e, RetryError):
        cause = e.last_attempt.exception()
        if isinstance(cause, aiohttp.ClientResponseError) and cause.status == 429:
            pytest.skip(f"{test_name} skipped due to rate limiting")
    elif isinstance(e, aiohttp.ClientResponseError) and e.status == 429:
        pytest.skip(f"{test_name} skipped due to rate limiting")

@pytest_asyncio.fixture
async def scanner_factory(base_url):
    # factory to create scanners and clean them up
    created_scanners = []
    
    async def _create_scanner(api_key="valid_api_key", max_requests_per_second=0.5):
        scanner = CloudResourceScanner(
            base_url=base_url, 
            api_key=api_key,
            max_requests_per_second=max_requests_per_second
        )
        await scanner.initialize()
        created_scanners.append(scanner)
        return scanner
    
    yield _create_scanner
    
    # cleanup all the scanners we made
    for scanner in created_scanners:
        try:
            await scanner.close()
        except Exception:
            pass

@pytest_asyncio.fixture
async def scanner(scanner_factory):
    # basic scanner for simple tests
    return await scanner_factory()

@pytest.fixture(autouse=True)
def global_test_throttle():
    # wait between tests to avoid hitting rate limits
    import time
    time.sleep(1.5)

# pytest config stuff
def pytest_addoption(parser):
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )

def pytest_configure(config):
    config.addinivalue_line("markers", "rate_sensitive: mark test as sensitive to rate limiting")
    config.addinivalue_line("markers", "slow: mark test as slow to run")

def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        # --runslow given, run everything
        return
    skip_slow = pytest.mark.skip(reason="need --runslow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow) 