# Async API Client

Async Python API client with rate limiting and retry logic

## Running it

```bash
docker-compose up --build test-runner
```

Local dev:
```bash
cd mock_service && python mock_service.py
pytest
```

## What's in here

- scanner.py - main async client
- mock_service/ - fake API for testing  
- tests/ - test suite (91% coverage)

Rate limiting, async, concurrent requests. 

