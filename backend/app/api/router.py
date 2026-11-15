from fastapi import APIRouter

from app.api import admin, alerts, announcements, companies, digest, events, financials, health, market_data, portfolio, research

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(admin.router)
api_router.include_router(companies.router)
api_router.include_router(market_data.router)
api_router.include_router(announcements.router)
api_router.include_router(digest.router)
api_router.include_router(alerts.router)
api_router.include_router(financials.router)
api_router.include_router(research.router)
api_router.include_router(events.router)
api_router.include_router(portfolio.router)
