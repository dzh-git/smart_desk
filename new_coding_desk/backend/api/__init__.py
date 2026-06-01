"""
API router layer — HTTP endpoint definitions.

Per system_architecture §4.1:
    - Parameter validation (Pydantic)
    - Call Service layer
    - Return ApiResponse
    - NO database access
    - NO WebSocket access
    - NO business logic
"""
