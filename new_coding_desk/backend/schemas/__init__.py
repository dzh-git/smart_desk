"""
Unified API response schema and shared Pydantic models.

Per API_SPEC §1:
    Success: {"success": true, "message": "OK", "data": {...}}
    Failure: {"success": false, "message": "...", "data": null, "error_code": "..."}
"""
from __future__ import annotations

from typing import Any, Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Unified API response envelope."""
    success: bool = True
    message: str = "OK"
    data: T | None = None
    error_code: str | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def ok(cls, data: T | None = None, message: str = "OK") -> "ApiResponse[T]":
        return cls(success=True, message=message, data=data)

    @classmethod
    def fail(
        cls,
        message: str,
        error_code: str,
        data: T | None = None,
    ) -> "ApiResponse[T]":
        return cls(success=False, message=message, data=data, error_code=error_code)


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response."""
    items: list[T]
    total: int
    offset: int = 0
    limit: int = 200
