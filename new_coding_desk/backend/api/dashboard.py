"""
Dashboard API — admin overview.

Per API_SPEC §3:
    GET /api/dashboard  → DashboardService
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
