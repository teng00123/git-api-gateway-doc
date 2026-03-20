# Gateway Documentation Format Specification

## Standard Structure

### Header Section
```
# API Gateway Documentation
Generated from git diff - [count] interfaces found

Date: [YYYY-MM-DD HH:MM]
Branch: [branch-name]
Commit Range: [start_commit]..[end_commit]
```

### Interface Summary Table
```
## Interface Summary
| Method | Path | Function | File | Status |
|--------|------|----------|------|--------|
| GET | `/api/users` | getUserList | src/UserController.java | Added |
| POST | `/api/users` | createUser | src/UserController.java | Modified |
```

### Detailed Documentation
```
## Detailed Interface Documentation

### 1. GET /api/users
- **Function**: getUserList
- **File**: src/UserController.java
- **Status**: Added
- **Description**: Retrieve paginated list of users
- **Parameters**:
  - page (int, optional): Page number, default 1
  - size (int, optional): Items per page, default 20
- **Request Body**: None
- **Response**: 
  ```json
  {
    "code": 200,
    "data": {
      "users": [...],
      "total": 100,
      "page": 1
    }
  }
  ```
- **Authentication**: Bearer token required
- **Error Codes**:
  - 401: Unauthorized
  - 500: Internal server error
```

## Field Definitions

- **Method**: HTTP method (GET, POST, PUT, DELETE, PATCH)
- **Path**: Full API endpoint path
- **Function**: Controller method name
- **File**: Source file path
- **Status**: Added, Modified, or Deleted
- **Description**: Brief functional description
- **Parameters**: Query parameters, path variables
- **Request Body**: JSON schema or description
- **Response**: Success response format
- **Authentication**: Required auth method
- **Error Codes**: Possible error responses