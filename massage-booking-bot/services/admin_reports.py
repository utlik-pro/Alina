"""Authenticated, read-only operational reports."""
import hmac
from fastapi import APIRouter, HTTPException, Query, Request, Response
from config import config
from database.db import get_db
from services.operations_report import load_funnel_report, reconciliation_report
from services.yclients_service import YClientsService

router = APIRouter(prefix='/admin')


def authorize(request):
    supplied = request.headers.get('X-Admin-Secret') or request.headers.get('X-Manychat-Secret') or ''
    allowed = (config.WEBHOOK_SECRET, config.MANYCHAT_WEBHOOK_SECRET)
    if not supplied or not any(value and hmac.compare_digest(supplied, value) for value in allowed):
        raise HTTPException(status_code=403, detail='forbidden')


def testers():
    return [v.strip() for v in (config.IG_TEST_SUBSCRIBERS or '').split(',') if v.strip()]


@router.get('/funnel-report')
async def funnel_report(request: Request, response: Response, hours: int = Query(24, ge=1, le=168)):
    authorize(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        return await load_funnel_report(get_db(), hours=hours, tester_ids=testers())
    except Exception:
        # A DB outage is not an empty day or a 0% conversion.
        raise HTTPException(status_code=503, detail='Report data unavailable') from None


@router.get('/reconciliation')
async def calendar_report(request: Request, response: Response, limit: int = Query(20, ge=1, le=50),
                          offset: int = Query(0, ge=0, le=100000)):
    authorize(request)
    response.headers["Cache-Control"] = "no-store"
    calendar = YClientsService()
    try:
        return await reconciliation_report(get_db(), calendar, limit=limit, offset=offset, tester_ids=testers())
    except Exception:
        raise HTTPException(status_code=503, detail='Reconciliation data unavailable') from None
    finally:
        await calendar.close()
