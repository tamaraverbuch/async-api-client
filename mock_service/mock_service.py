from fastapi import FastAPI, HTTPException, Header, Query, Response
from typing import Optional
import random
import time
from datetime import datetime

app = FastAPI()

# fake database with 100 resources
RESOURCES = [
    {
        "id": f"res_{i}",
        "type": random.choice(["storage", "compute", "network", "database"]),
        "name": f"resource_{i}",
        "metadata": {
            "region": random.choice(["us-east-1", "us-west-2", "eu-west-1"]),
            "created_at": "2024-01-01"
        },
        "sensitive_data": random.choice([True, False])
    }
    for i in range(1, 101)  # 100 sample resources
]

# config
VALID_API_KEY = "valid_api_key"
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW = 60  # seconds

# rate limiting tracking
request_history = {}

def check_api_key(api_key: str = Header(None)):
    if api_key != VALID_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key

def check_rate_limit(api_key: str):
    current_time = time.time()
    if api_key not in request_history:
        request_history[api_key] = []
    
    # clean up old requests
    request_history[api_key] = [t for t in request_history[api_key] 
                               if current_time - t < RATE_LIMIT_WINDOW]
    
    if len(request_history[api_key]) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    request_history[api_key].append(current_time)

def simulate_latency_and_errors():
    # add random delay
    time.sleep(random.uniform(0.1, 0.5))
    
    # random 500 errors 5% of the time
    if random.random() < 0.05:
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/resources")
async def list_resources(
    response: Response,
    api_key: str = Header(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100)
):
    # check auth
    check_api_key(api_key)
    
    # check rate limit
    check_rate_limit(api_key)
    
    # simulate real api behavior
    simulate_latency_and_errors()
    
    # pagination math
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    total_items = len(RESOURCES)
    total_pages = (total_items + limit - 1) // limit
    
    # make sure page exists
    if page > total_pages:
        raise HTTPException(status_code=404, detail="Page not found")
    
    # slice the data
    paginated_resources = RESOURCES[start_idx:end_idx]
    
    return {
        "resources": paginated_resources,
        "page": page,
        "total_pages": total_pages,
        "total_items": total_items
    }

@app.get("/resources/{resource_id}")
async def get_resource(
    resource_id: str,
    response: Response,
    api_key: str = Header(None)
):
    # check auth
    check_api_key(api_key)
    
    # check rate limit
    check_rate_limit(api_key)
    
    # simulate real api behavior
    simulate_latency_and_errors()
    
    # find the resource
    resource = next(
        (r for r in RESOURCES if r["id"] == resource_id),
        None
    )
    
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    
    return resource

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 