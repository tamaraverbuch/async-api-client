import pytest
import aiohttp
import asyncio
from tenacity import RetryError
from tests.conftest import handle_rate_limit_skip

@pytest.mark.asyncio
async def test_health_check(scanner):
    # basic health endpoint test
    is_healthy = await scanner.check_health()
    assert is_healthy is True

@pytest.mark.asyncio
async def test_list_resources(scanner):
    # check pagination works
    result = await scanner.list_resources(page=1, limit=10)
    assert "resources" in result
    assert "total_pages" in result
    assert "page" in result
    assert len(result["resources"]) <= 10

@pytest.mark.asyncio
async def test_get_resource(scanner):
    # get single resource by id
    # need to get a valid id first
    resources = await scanner.list_resources()
    resource_id = resources["resources"][0]["id"]
    
    # now fetch that specific one
    resource = await scanner.get_resource(resource_id)
    assert resource["id"] == resource_id
    assert "type" in resource
    assert "name" in resource
    assert "metadata" in resource

@pytest.mark.asyncio
async def test_scan_all_resources(scanner):
    # full scan across all pages
    resources = await scanner.scan_all_resources()
    assert len(resources) > 0
    assert all(isinstance(r, dict) for r in resources)
    assert all("id" in r for r in resources)

@pytest.mark.asyncio
@pytest.mark.rate_sensitive
async def test_get_sensitive_resources(scanner_factory):
    # filter for sensitive data only
    scanner = await scanner_factory(max_requests_per_second=0.3)
    try:
        await asyncio.sleep(2)  # extra delay
        sensitive_resources = await scanner.get_sensitive_resources()
        assert all(r["sensitive_data"] for r in sensitive_resources)
    except Exception as e:
        handle_rate_limit_skip(e, "test_get_sensitive_resources")
        raise
    finally:
        await scanner.close()

@pytest.mark.asyncio
async def test_invalid_api_key(scanner_factory):
    # make sure bad auth fails properly
    scanner = await scanner_factory(api_key="invalid_key")
    try:
        with pytest.raises(aiohttp.ClientResponseError) as exc_info:
            await scanner.list_resources()
        assert exc_info.value.status == 401
    finally:
        await scanner.close()

@pytest.mark.asyncio
@pytest.mark.rate_sensitive
async def test_resource_not_found(scanner_factory):
    # 404 handling for bad resource ids
    scanner = await scanner_factory(max_requests_per_second=0.3)
    try:
        await asyncio.sleep(2)
        with pytest.raises(aiohttp.ClientResponseError) as exc_info:
            await scanner.get_resource("non_existent_id")
        assert exc_info.value.status == 404
    except Exception as e:
        handle_rate_limit_skip(e, "test_resource_not_found")
        raise
    finally:
        await scanner.close()

@pytest.mark.asyncio
@pytest.mark.rate_sensitive
@pytest.mark.slow
async def test_pagination_limits(scanner_factory):
    # test min/max page sizes
    scanner = await scanner_factory(max_requests_per_second=0.2)
    try:
        await asyncio.sleep(3)
        
        # min page size
        result = await scanner.list_resources(limit=1)
        assert len(result["resources"]) == 1

        # wait a bit
        await asyncio.sleep(3)
        
        # max page size
        result = await scanner.list_resources(limit=100)
        assert len(result["resources"]) <= 100
    except Exception as e:
        handle_rate_limit_skip(e, "test_pagination_limits")
        raise
    finally:
        await scanner.close()

@pytest.mark.asyncio
@pytest.mark.rate_sensitive
@pytest.mark.slow
async def test_concurrent_requests(scanner_factory):
    # concurrency test with low limits
    scanner = await scanner_factory(max_requests_per_second=0.2)
    try:
        await asyncio.sleep(3)
        
        # keep concurrency low to avoid overwhelming server
        scanner.max_concurrent_requests = 2
        resources = await scanner.scan_all_resources()
        assert len(resources) > 0
    except Exception as e:
        handle_rate_limit_skip(e, "test_concurrent_requests")
        raise
    finally:
        await scanner.close()

@pytest.mark.asyncio
@pytest.mark.rate_sensitive
async def test_rate_limiting(scanner_factory):
    scanner = await scanner_factory()
    
    try:
        # 15 requests quickly
        # should handle rate limits with retries
        tasks = [scanner.list_resources() for _ in range(15)]
        results = await asyncio.gather(*tasks)
        
        # all should eventually succeed
        assert len(results) == 15, f"Expected 15 results, got {len(results)}"
        assert all("resources" in result for result in results), "All requests should return valid resource data"
        
        # if we get here, rate limiting + retry logic worked
        
    finally:
        await scanner.close() 