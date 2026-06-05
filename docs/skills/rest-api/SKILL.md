---
name: rest-api-testing
description: Test, debug, and document REST APIs using the http_request tool. Covers authentication, request chaining, assertions, and generating API docs.
version: "1.0"
trigger_keywords:
  - api
  - REST
  - http
  - endpoint
  - curl
  - POST
  - headers
  - authentication
  - bearer token
  - json api
  - swagger
  - openapi
tools_required:
  - http_request
  - db_execute
  - db_query
  - json_query
  - write_file
---

# REST API Testing and Integration

Use the `http_request` tool for any HTTP method with full control over headers, body, and authentication.

## Basic Requests

```
# GET
http_request("GET", "https://api.example.com/users")

# GET with query params (encode in URL)
http_request("GET", "https://api.example.com/users?page=1&limit=20")

# POST JSON
http_request("POST", "https://api.example.com/users",
    body={"name": "Alice", "email": "alice@example.com"})

# PUT (update)
http_request("PUT", "https://api.example.com/users/123",
    body={"name": "Alice Updated"})

# DELETE
http_request("DELETE", "https://api.example.com/users/123")
```

## Authentication

```
# Bearer token (most common)
http_request("GET", "https://api.example.com/profile",
    headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiIs..."})

# API Key header
http_request("GET", "https://api.example.com/data",
    headers={"X-API-Key": "your-api-key", "Accept": "application/json"})

# Basic auth (encode manually)
import base64
credentials = base64.b64encode(b"user:password").decode()
http_request("GET", "https://api.example.com/",
    headers={"Authorization": f"Basic {credentials}"})
```

## Request Chaining (Login → Use Token)

```
# Step 1: Login
login_resp = http_request("POST", "https://api.example.com/auth/login",
    body={"username": "admin", "password": "secret"})

# Step 2: Extract token from response
token = login_resp["body_json"]["access_token"]

# Step 3: Use token in subsequent requests
users = http_request("GET", "https://api.example.com/admin/users",
    headers={"Authorization": f"Bearer {token}"})
```

## Storing Results in SQLite

```
# Create an API test log table
db_execute(
    "CREATE TABLE IF NOT EXISTS api_tests (ts TEXT, endpoint TEXT, status INTEGER, ok INTEGER, response_ms REAL)",
    db_name="api_testing"
)

# Log a test result
db_execute(
    "INSERT INTO api_tests VALUES (datetime('now'), ?, ?, ?, ?)",
    params=["GET /users", 200, 1, 145.3],
    db_name="api_testing"
)

# View test history
db_query("SELECT * FROM api_tests ORDER BY ts DESC LIMIT 20", db_name="api_testing")
```

## Asserting Response Quality

```python
# In run_python — write assertions for API responses
response = {
    "status": 200,
    "body_json": {"users": [{"id": 1, "name": "Alice"}], "total": 1}
}

assert response["status"] == 200, f"Expected 200, got {response['status']}"
assert "users" in response["body_json"], "Missing 'users' key"
assert len(response["body_json"]["users"]) > 0, "Empty users list"
print("✓ All assertions passed")
```

## Extracting Data with JMESPath

```
# Extract specific fields from API response JSON
json_query('{"users": [{"id": 1, "name": "Alice", "active": true}]}',
           "users[?active].name")
# → ["Alice"]

# Nested extraction
json_query("api_response.json", "data.items[*].{id: id, title: title}")
```

## Generating API Documentation

When asked to document an API, follow this pattern:

```markdown
## GET /users

**Description:** List all users

**Headers:**
| Header | Required | Description |
|---|---|---|
| Authorization | ✓ | Bearer <token> |
| Accept | ✗ | application/json |

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| page | integer | 1 | Page number |
| limit | integer | 20 | Items per page |

**Response 200:**
```json
{
  "users": [{"id": 1, "name": "Alice", "email": "alice@example.com"}],
  "total": 100,
  "page": 1
}
```

**Response 401:** Unauthorized — invalid or missing token
```

## Common Status Codes
| Code | Meaning | Action |
|---|---|---|
| 200 | OK | Success |
| 201 | Created | Resource created (POST) |
| 400 | Bad Request | Check request body/params |
| 401 | Unauthorized | Check auth headers/token |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Check endpoint URL |
| 422 | Unprocessable | Validation error — check body |
| 429 | Rate Limited | Add delay between requests |
| 500 | Server Error | Server-side issue |
