"""Unauthenticated endpoints: health + the web account-deletion page Google Play requires
(Play Console > App content > Data safety > 'Delete account URL')."""

from __future__ import annotations

from html import escape

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.redis_client import get_redis

router = APIRouter(tags=["public"])


@router.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}


@router.get("/readyz", include_in_schema=False)
async def readyz(db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT 1"))
    redis_ok = True
    try:
        await get_redis().ping()
    except Exception:  # noqa: BLE001
        redis_ok = False  # degraded, not down: leaderboard falls back to Postgres
    return {"db": True, "redis": redis_ok}


@router.get("/account-deletion", response_class=HTMLResponse, include_in_schema=False)
async def account_deletion_page():
    s = get_settings()
    app, mail = escape(s.app_name), escape(s.support_email)
    return f"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{app} – حذف الحساب / Delete account</title>
<style>body{{font-family:system-ui,sans-serif;max-width:680px;margin:2rem auto;padding:0 1rem;line-height:1.7}}
section[dir=ltr]{{border-top:1px solid #ddd;margin-top:2rem;padding-top:1rem}}</style></head><body>
<h1>حذف حسابك في {app}</h1>
<ol><li>افتح التطبيق ← الملف الشخصي ← الإعدادات.</li><li>اضغط «حذف حسابي وبياناتي» وأكّد.</li></ol>
<p>لو مش قادر تفتح التطبيق، ابعت إيميل لـ <a href="mailto:{mail}?subject=Delete%20account">{mail}</a> من نفس الإيميل المسجّل بيه، وهنحذف الحساب خلال 7 أيام.</p>
<p><b>اللي بيتحذف فورًا وبشكل نهائي:</b> الحساب، الاسم المستعار، النادي، النقاط، المستوى، العملات، الشارات، الجولات، التوقعات، ونتائج الترتيب. مفيش أي بيانات بنحتفظ بيها بعد الحذف.</p>
<section dir="ltr" lang="en"><h1>Delete your {app} account</h1>
<ol><li>Open the app → Profile → Settings.</li><li>Tap “Delete my account &amp; data” and confirm.</li></ol>
<p>Can't access the app? Email <a href="mailto:{mail}?subject=Delete%20account">{mail}</a> from your registered address; we delete within 7 days.</p>
<p><b>Deleted immediately and permanently:</b> account, nickname, club, points, level, coins, badges, game rounds, predictions, leaderboard history. Nothing is kept after deletion.</p>
</section>
</body></html>"""
