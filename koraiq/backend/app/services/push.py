"""FCM topic pushes. Clients subscribe to `<topic>_<lang>` (e.g. kickoff_ar) so each push is localized
with zero per-user fan-out on our side."""

from __future__ import annotations

import logging

from starlette.concurrency import run_in_threadpool

from app.security.auth import firebase_app

log = logging.getLogger(__name__)


async def send_topic(topic: str, titles: dict[str, str], bodies: dict[str, str], data: dict[str, str] | None = None) -> None:
    if firebase_app() is None:
        log.info("FCM not configured; skip push topic=%s", topic)
        return
    from firebase_admin import messaging

    for lang in ("ar", "en"):
        msg = messaging.Message(
            topic=f"{topic}_{lang}",
            notification=messaging.Notification(title=titles[lang], body=bodies[lang]),
            data=data or {},
            android=messaging.AndroidConfig(priority="high", ttl=3600),
        )
        try:
            await run_in_threadpool(messaging.send, msg, False, firebase_app())
        except Exception:  # noqa: BLE001
            log.warning("FCM send failed topic=%s_%s", topic, lang, exc_info=True)
