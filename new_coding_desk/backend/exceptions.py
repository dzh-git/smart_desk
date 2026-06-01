"""
Business exceptions for the service layer.

Raised by Services, caught by Routers to produce ApiResponse errors.
"""
from __future__ import annotations


class BusinessError(Exception):
    """Base business exception with error_code for API responses."""

    def __init__(self, message: str, error_code: str) -> None:
        self.message = message
        self.error_code = error_code
        super().__init__(message)


class NotFoundError(BusinessError):
    """Resource not found."""

    def __init__(self, message: str, error_code: str) -> None:
        super().__init__(message, error_code)


class ConflictError(BusinessError):
    """Business rule conflict (e.g., duplicate active meeting)."""

    def __init__(self, message: str, error_code: str) -> None:
        super().__init__(message, error_code)


class ValidationError(BusinessError):
    """Business validation failure (e.g., invalid state transition)."""

    def __init__(self, message: str, error_code: str) -> None:
        super().__init__(message, error_code)
