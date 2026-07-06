"""Crystal Lab Bot — FastAPI webhook app for Render deployment.

Handles:
- Telegram Bot webhook (aiogram)
- ManyChat External Request webhook (future)
- Health check endpoint
"""

import asyncio
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Request, Response, BackgroundTasks
from loguru import logger

# Deduplication cache: message_id → timestamp (processed within last 5 min).
# OrderedDict so we can evict oldest entries when hitting the size cap —
# prevents unbounded memory growth and keeps TTL-cleanup O(log n) amortized.
_processed_message_ids: "OrderedDict[str, float]" = OrderedDict()
_DEDUP_TTL = 300  # 5 minutes
_DEDUP_MAX_ENTRIES = 5000


def _dedup_seen(message_id: str, now_ts: float) -> bool:
    """Return True if message_id was processed recently; otherwise record it.

    Evicts expired entries (oldest-first) and caps total size. Safe under
    asyncio single-thread assumptions — no locks needed.
    """
    if not message_id:
        return False
    # Evict expired from the oldest end.
    while _processed_message_ids:
        oldest_id, oldest_ts = next(iter(_processed_message_ids.items()))
        if now_ts - oldest_ts > _DEDUP_TTL:
            _processed_message_ids.popitem(last=False)
        else:
            break
    # Cap size.
    while len(_processed_message_ids) >= _DEDUP_MAX_ENTRIES:
        _processed_message_ids.popitem(last=False)
    if message_id in _processed_message_ids:
        # Refresh position so genuine repeats don't get evicted mid-storm.
        _processed_message_ids.move_to_end(message_id)
        return True
    _processed_message_ids[message_id] = now_ts
    return False

# Wappi message buffering: phone → {"messages": [text,...], "timer": Task, "sender_name": str}
# Per PRD 4.1 rule 6: wait 7s to collect multi-part messages before responding
_wappi_buffer: dict[str, dict] = {}
_WAPPI_BUFFER_DELAY = 7.0  # seconds

# Reset/clear commands (WhatsApp + Telegram). The team kept typing "/clean"
# (not "/clear"); both + bare/RU variants are accepted.
_RESET_COMMANDS = frozenset({
    "/clear", "/clean", "/reset", "/start", "/new",
    "reset", "clear", "clean", "restart", "new chat",
    "очистить", "сброс", "сбросить", "очисти", "начать заново",
})


def _is_reset_command(text: str) -> bool:
    """True if a raw message is a reset command (tolerant of trailing !./space)."""
    if not text:
        return False
    return text.strip().lower().rstrip("!. ") in _RESET_COMMANDS


_NAILS_KW = ("manicure", "pedicure", "mani ", "mani+", "pedi", "nail", "gelish",
             "маникюр", "педикюр", "ногт")
_MASSAGE_KW = ("massage", "body", "lymphatic", "cupping", "deep tissue",
               "facial", "face", "prenatal", "postpartum", "массаж", "лицо")


def _detect_service_category(text: str) -> Optional[str]:
    """Rough service category from a message: 'nails' | 'massage' | None.

    Used to persist context.booking_data['service_type'] on the Wappi path so
    slot injection shows the RIGHT specialists (a manicure client was being
    shown massage-therapist availability because service_type was never set).
    """
    t = (text or "").lower()
    if any(k in t for k in _NAILS_KW):
        return "nails"
    if any(k in t for k in _MASSAGE_KW):
        return "massage"
    return None

from config import config
from bot import router, booking_agent
from database import (
    init_db, ClientService, MessageService, BookingService, DialogSessionService,
    PackageService, WaitingListService,
)
from dialog_context import dialog_manager
from services.notifications import NotificationService
from services.follow_up import FollowUpService
from services.scheduler import ReminderScheduler
from services.message_buffer import init_buffer, MessageBuffer
from services.yclients_service import YClientsService
from services.wappi_client import WappiClient, parse_incoming_message
from agents.tools import BookingCall, CancelCall, RescheduleCall, AgentActions

# ── Global instances ─────────────────────────────────────────────────
bot_instance: Bot = None
dp: Dispatcher = None
wappi_client: WappiClient = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup and shutdown logic."""
    global bot_instance, dp

    # Validate config
    if not config.validate():
        raise RuntimeError("Invalid configuration")

    # Initialize bot and dispatcher
    bot_instance = Bot(token=config.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    # Initialize message buffer
    import bot as bot_module
    bot_module.msg_buffer = await init_buffer(config.REDIS_URL)

    # Initialize database
    logger.info("Initializing database...")
    db = init_db(config.DATABASE_URL)
    await db.create_tables()

    bot_module.client_service = ClientService(db)
    bot_module.message_service = MessageService(db)
    bot_module.booking_service = BookingService(db)
    bot_module.dialog_session_service = DialogSessionService(db)
    bot_module.package_service = PackageService(db)
    bot_module.waiting_list_service = WaitingListService(db)
    logger.info("✅ Database services initialized")

    # Notification service
    if config.ADMIN_GROUP_CHAT_ID:
        bot_module.notification_service = NotificationService(
            bot_instance, config.ADMIN_GROUP_CHAT_ID
        )
        logger.info(f"✅ Notifications enabled for group {config.ADMIN_GROUP_CHAT_ID}")

    # Follow-up service. Contexts are keyed "wappi_<phone>" for WhatsApp and
    # a numeric chat_id for Telegram — route each to the right channel.
    # (Previously every follow-up did int(user_id), which raised ValueError
    # on "wappi_..." and silently dropped ALL WhatsApp nudges → the client's
    # "offers tomorrow then goes silent" complaint.)
    async def _send_follow_up(user_id: str, text: str):
        try:
            if str(user_id).startswith("wappi_"):
                phone = str(user_id)[len("wappi_"):]
                if wappi_client:
                    await wappi_client.send_message(phone, text)
                else:
                    logger.error(f"Follow-up: no wappi_client for {user_id}")
                return
            await bot_instance.send_message(chat_id=int(user_id), text=text)
        except Exception as e:
            logger.error(f"Failed to send follow-up to {user_id}: {e}")

    async def _send_photo(user_id: str, photo_path: str, caption: str):
        try:
            if str(user_id).startswith("wappi_"):
                # Wappi client sends text only — deliver the caption.
                await _send_follow_up(user_id, caption)
                return
            from aiogram.types import FSInputFile
            photo = FSInputFile(photo_path)
            await bot_instance.send_photo(chat_id=int(user_id), photo=photo, caption=caption)
        except Exception as e:
            logger.error(f"Failed to send photo to {user_id}: {e}")
            await _send_follow_up(user_id, caption)

    bot_module.follow_up_service = FollowUpService(
        send_message=_send_follow_up,
        notification_service=bot_module.notification_service,
        send_photo=_send_photo,
    )
    await bot_module.follow_up_service.start(check_interval=60)

    # YClients service
    if not config.MOCK_YCLIENTS and config.YCLIENTS_PARTNER_TOKEN and config.YCLIENTS_USER_TOKEN:
        bot_module.yclients_service = YClientsService()
        try:
            staff = await bot_module.yclients_service.get_staff()
            logger.info(f"✅ YClients connected: {len(staff)} staff members")
        except Exception as e:
            logger.error(f"❌ YClients connection failed: {e}")
            bot_module.yclients_service = None

    # Wappi WhatsApp client
    global wappi_client
    if config.WAPPI_TOKEN and config.WAPPI_PROFILE_ID:
        wappi_client = WappiClient()
        logger.info("✅ Wappi WhatsApp client initialized")
    else:
        logger.info("⚠️ Wappi not configured (WAPPI_TOKEN / WAPPI_PROFILE_ID missing)")

    # Reminder scheduler (FR-3.1 day-before confirmations, FR-4 post-session).
    # Sends WhatsApp via Wappi; falls back to Telegram if Wappi is absent.
    async def _scheduler_send(phone: str, text: str):
        if wappi_client:
            await wappi_client.send_message(phone, text)
        else:
            # Telegram fallback (dev): phone is "wappi_<n>" stripped → not a
            # chat id, so only attempt when it's numeric.
            try:
                await bot_instance.send_message(chat_id=int(phone), text=text)
            except Exception as e:
                logger.warning(f"Scheduler Telegram fallback failed for {phone}: {e}")

    bot_module.reminder_scheduler = ReminderScheduler(
        booking_service=bot_module.booking_service,
        send_message=_scheduler_send,
        package_service=bot_module.package_service,
        notification_service=bot_module.notification_service,
        check_interval=900,
    )
    await bot_module.reminder_scheduler.start()

    # Set Telegram webhook
    import os
    base_url = config.RENDER_EXTERNAL_URL
    if not base_url:
        # Fallback: construct from RENDER_EXTERNAL_HOSTNAME or service name
        hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
        if hostname:
            base_url = f"https://{hostname}"
        else:
            base_url = "https://crystal-lab-bot.onrender.com"
    webhook_url = f"{base_url}/webhook/telegram"
    await bot_instance.set_webhook(
        url=webhook_url,
        secret_token=config.WEBHOOK_SECRET,
        drop_pending_updates=False,
    )
    logger.info(f"✅ Telegram webhook set: {webhook_url}")
    logger.info("🤖 Crystal Lab Bot started in WEBHOOK mode (Render)")

    yield

    # Shutdown — do NOT delete webhook, new instance will re-set it on startup
    logger.info("Shutting down...")
    if getattr(bot_module, "reminder_scheduler", None):
        await bot_module.reminder_scheduler.stop()
    if bot_module.follow_up_service:
        await bot_module.follow_up_service.stop()
    if bot_module.msg_buffer:
        await bot_module.msg_buffer.close()
    if wappi_client:
        await wappi_client.close()
    await bot_instance.session.close()
    await db.close()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def health():
    """Health check for Render."""
    return {"status": "ok", "bot": "Crystal Lab", "mode": "webhook"}


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Receive Telegram updates via webhook."""
    # Verify secret token
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if config.WEBHOOK_SECRET and secret != config.WEBHOOK_SECRET:
        logger.warning("Invalid webhook secret token")
        return Response(status_code=403)

    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot_instance})
    await dp.feed_update(bot=bot_instance, update=update)
    return Response(status_code=200)


async def _buffer_and_process_wappi(phone: str, text: str, sender_name: str):
    """Buffer incoming Wappi messages — wait 7s, then process combined.

    If a new message arrives within 7s, restart the timer (PRD 4.1 rule 6).
    """
    entry = _wappi_buffer.setdefault(phone, {"messages": [], "timer": None, "sender_name": sender_name})
    entry["messages"].append(text)
    if sender_name and not entry.get("sender_name"):
        entry["sender_name"] = sender_name

    # Cancel existing timer if any (reset 7s window)
    if entry.get("timer") and not entry["timer"].done():
        entry["timer"].cancel()

    async def _flush():
        try:
            await asyncio.sleep(_WAPPI_BUFFER_DELAY)
            buf = _wappi_buffer.pop(phone, None)
            if not buf:
                return
            combined = "\n".join(buf["messages"])
            logger.info(f"Wappi buffer [{phone}]: flushing {len(buf['messages'])} messages")
            await _process_wappi_message(phone, combined, buf["sender_name"])
        except asyncio.CancelledError:
            pass  # new message arrived, will be handled by new timer
        except Exception as e:
            logger.error(f"Wappi buffer flush error: {e}", exc_info=True)

    entry["timer"] = asyncio.create_task(_flush())


async def _maybe_create_booking(
    user_id: str,
    telegram_id: str,
    phone: str,
    sender_name: str,
    context,
    response_text: str,
    booking_call: Optional[BookingCall] = None,
):
    """Create DB + YClients records from a structured BookingCall.

    Flow:
    - If booking_call is None but the bot sent a ✅ confirmation — that's
      a phantom confirmation (model forgot to call the tool). Alert the
      admin and DO NOT create anything.
    - If booking_call is None and there's no ✅ — nothing to do.
    - If booking_call is present — validate, persist locally, create in
      YClients, notify admin.

    All the old regex date/time parsing is gone; structured fields from
    the tool call are the only source of truth.
    """
    import re as _re
    import bot as bot_module
    from datetime import datetime, timedelta, timezone as _tz

    uae_tz = _tz(timedelta(hours=4))
    now_uae = datetime.now(uae_tz).replace(tzinfo=None)

    # Detect phantom confirmation: ✅ + a confirmation cue but no tool call.
    # Broadened beyond "booked" — the model also confirms with "all set",
    # "confirmed", "scheduled", "see you", which previously escaped both the
    # creation AND the admin alert (silent false confirmation to the client).
    text_low = response_text.lower()
    has_confirm_marker = (
        "✅" in response_text
        and _re.search(
            r"\b(?:booked|confirmed|all set|scheduled|see you|you'?re all set)\b",
            text_low,
        ) is not None
    )
    if has_confirm_marker:
        # Filter out negated forms ("not yet booked", "will be booked"…)
        negation_re = _re.compile(
            r"(?:not\s+yet|won'?t\s+be|will\s+be|going\s+to\s+be|"
            r"cannot\s+be|can'?t\s+be|is\s+not|isn'?t|aren'?t|"
            r"would\s+be|should\s+be|could\s+be|maybe|might)\s+booked",
            _re.IGNORECASE,
        )
        if negation_re.search(text_low):
            has_confirm_marker = False

    if booking_call is None:
        if has_confirm_marker:
            logger.error(
                f"Wappi: ✅ confirmation WITHOUT book_appointment tool call — "
                f"phantom booking ignored. response={response_text[:200]!r}"
            )
            if bot_module.notification_service:
                try:
                    await bot_module.notification_service.send_booking_failed(
                        telegram_id=telegram_id,
                        reason=(
                            "Bot sent ✅ confirmation but did NOT call "
                            "book_appointment tool. No record created. "
                            f"Bot said: {response_text[:200]}"
                        ),
                    )
                except Exception:
                    pass
        return

    # Anti-duplicate guard: suppress ONLY an EXACT repeat of the booking we
    # just created (the model re-calls the tool when the client writes
    # "thanks"/emoji). A DIFFERENT service/date/time is a legitimate SECOND
    # booking (another day, "book my sister too") and must go through — the
    # old guard blocked ALL bookings once state=='completed', so the client
    # was stuck until /clear ("booked once then glitches").
    _new_sig = (booking_call.service, booking_call.date, booking_call.time)
    if getattr(context, "last_booking_sig", None) == _new_sig:
        logger.warning(
            f"Wappi: suppressing exact-duplicate book_appointment {_new_sig}"
        )
        return

    # Parse structured date/time into a datetime.
    try:
        booking_date = datetime.strptime(
            f"{booking_call.date} {booking_call.time}", "%Y-%m-%d %H:%M"
        )
    except ValueError as e:
        logger.error(
            f"Wappi: BookingCall has malformed date/time — "
            f"date={booking_call.date!r} time={booking_call.time!r} err={e}"
        )
        if bot_module.notification_service:
            try:
                await bot_module.notification_service.send_booking_failed(
                    telegram_id=telegram_id,
                    reason=(
                        f"book_appointment tool returned malformed "
                        f"date/time: {booking_call.date} {booking_call.time}"
                    ),
                )
            except Exception:
                pass
        return

    # Sanity window: not in the past (1h grace), not >60 days future.
    if booking_date < now_uae - timedelta(hours=1):
        logger.error(
            f"Wappi: BookingCall date in the past: {booking_date.isoformat()} "
            f"(now={now_uae.isoformat()})"
        )
        if bot_module.notification_service:
            try:
                await bot_module.notification_service.send_booking_failed(
                    telegram_id=telegram_id,
                    reason=f"Tool date is in the past: {booking_date.isoformat()}",
                )
            except Exception:
                pass
        return
    if booking_date > now_uae + timedelta(days=60):
        logger.error(
            f"Wappi: BookingCall date too far in future: {booking_date.isoformat()}"
        )
        if bot_module.notification_service:
            try:
                await bot_module.notification_service.send_booking_failed(
                    telegram_id=telegram_id,
                    reason=f"Tool date >60 days out: {booking_date.isoformat()}",
                )
            except Exception:
                pass
        return

    # Save in local DB
    try:
        client = await bot_module.client_service.get_or_create_client(telegram_id)
        if not client.phone:
            await bot_module.client_service.update_client(telegram_id, phone=phone)
        if booking_call.client_name and not client.name:
            await bot_module.client_service.update_client(
                telegram_id, name=booking_call.client_name
            )

        booking = await bot_module.booking_service.create_booking(
            telegram_id=telegram_id,
            service_name=booking_call.service,
            duration=booking_call.duration_minutes,
            base_price=booking_call.base_price_aed,
            booking_date=booking_date,
            payment_method=booking_call.payment_method,
        )
        await bot_module.booking_service.update_booking_status(booking.id, "confirmed")
        dialog_manager.update_state(user_id, "completed")
        # Remember this exact booking so a re-call on "thanks" is suppressed,
        # but a different service/date/time is allowed as a 2nd booking.
        context.last_booking_sig = _new_sig
        logger.info(
            f"✅ Wappi booking {booking.id} saved "
            f"({booking_call.service} {booking_call.date} {booking_call.time} "
            f"{booking_call.area})"
        )
    except Exception as e:
        logger.error(f"Wappi DB booking error: {e}", exc_info=True)
        return

    # Create in YClients
    if bot_module.yclients_service and not config.MOCK_YCLIENTS:
        try:
            import os as _os
            yc_service_id = await bot_module.yclients_service.find_service_id(
                booking_call.service,
                duration_minutes=booking_call.duration_minutes,
            )
            if yc_service_id is None:
                logger.error(
                    f"YClients: couldn't map service {booking_call.service!r} "
                    f"({booking_call.duration_minutes}min) to any catalog entry"
                )
                if bot_module.notification_service:
                    try:
                        await bot_module.notification_service.send_booking_failed(
                            telegram_id=telegram_id,
                            reason=(
                                f"Local booking created but YClients sync failed: "
                                f"service {booking_call.service!r} "
                                f"({booking_call.duration_minutes}min) not in catalog. "
                                f"Admin must add the YClients record manually."
                            ),
                        )
                    except Exception:
                        pass
            # Staff resolution priority:
            #   1. master_id from tool call — the model picked a concrete therapist
            #   2. master_name from tool call, filtered by area
            #   3. any non-admin staff in the client's area
            # Never falls back to an unfiltered default: sending an
            # Al-Ain therapist to an Abu-Dhabi client (or vice versa)
            # means a 90-minute misrouted drive and a missed appointment.
            yc_staff_id = booking_call.master_id
            if not yc_staff_id:
                yc_staff_id = await bot_module.yclients_service.find_staff_id(
                    name=booking_call.master_name,
                    area=booking_call.area,
                )
            if not yc_staff_id:
                logger.error(
                    f"YClients: no staff found for area={booking_call.area!r} "
                    f"master_name={booking_call.master_name!r}. "
                    f"Skipping YClients record creation."
                )
                if bot_module.notification_service:
                    try:
                        await bot_module.notification_service.send_booking_failed(
                            telegram_id=telegram_id,
                            reason=(
                                f"Couldn't find a therapist in {booking_call.area} "
                                f"for {booking_call.master_name or 'any'}. "
                                f"Local booking #{booking.id} saved but NOT "
                                f"synced to YClients. Admin must assign manually."
                            ),
                        )
                    except Exception:
                        pass

            fresh_client = await bot_module.client_service.get_or_create_client(telegram_id)
            client_name = (
                booking_call.client_name
                or fresh_client.name
                or sender_name
                or "WhatsApp Client"
            )
            client_phone = booking_call.client_phone or fresh_client.phone or phone

            if yc_service_id and yc_staff_id:
                _is_test = _os.getenv("YCLIENTS_TEST_BOOKINGS", "false").lower() == "true"
                yc_result = await bot_module.yclients_service.create_booking(
                    staff_id=yc_staff_id,
                    service_ids=[yc_service_id],
                    date=booking_call.date,
                    time=booking_call.time,
                    client_name=client_name,
                    client_phone=client_phone,
                    comment=(
                        f"WhatsApp (Wappi) bot booking #{booking.id}. "
                        f"Area: {booking_call.area}. "
                        + (f"Notes: {booking_call.notes}. " if booking_call.notes else "")
                        + (f"Address: {booking_call.address}." if booking_call.address else "")
                    ),
                    is_test=_is_test,
                    duration_minutes=booking_call.duration_minutes,
                )
                if yc_result:
                    logger.info(
                        f"✅ YClients booking created from WhatsApp: "
                        f"#{yc_result.get('id', '?')}"
                    )
                else:
                    logger.warning("⚠️ YClients booking creation failed")
            else:
                logger.warning(
                    f"⚠️ YClients: service_id={yc_service_id}, "
                    f"staff_id={yc_staff_id} — skipping"
                )
        except Exception as e:
            logger.error(f"❌ YClients booking error from WhatsApp: {e}")

    # Notify admin
    if bot_module.notification_service:
        try:
            fresh_client = await bot_module.client_service.get_or_create_client(telegram_id)
            await bot_module.notification_service.send_booking_confirmed(fresh_client, booking)
        except Exception as e:
            logger.error(f"Wappi: failed to notify admin: {e}")


async def _admin_text(message: str):
    """Post a plain HTML message to the admin group (best-effort)."""
    import bot as bot_module
    ns = bot_module.notification_service
    if not ns or not ns.group_chat_id:
        return
    try:
        await ns.bot.send_message(chat_id=ns.group_chat_id, text=message, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to post admin text: {e}")


async def _handle_cancellation(telegram_id: str, phone: str, call: "CancelCall"):
    """Cancel the client's active booking locally + apply penalty rules.

    YClients records are NOT auto-modified (safety rule) — admin is asked
    to update YClients manually.
    """
    import bot as bot_module
    from services.cancellation import calculate_penalty
    from services.scheduler import now_uae

    # Two-phase guard: only cancel + apply penalty when the model explicitly
    # marked the client's intent as confirmed. A soft/ambiguous "maybe cancel"
    # must never charge money or free a slot.
    if not call.confirmed:
        logger.info(f"Cancel tool called WITHOUT confirmation for {telegram_id} — ignoring")
        return

    b = await bot_module.booking_service.get_latest_active_booking(telegram_id)
    if not b:
        logger.info(f"Cancel requested but no active booking for {telegram_id}")
        await _admin_text(
            f"❌ <b>Запрос на отмену</b>\nКлиент <code>{telegram_id}</code> "
            f"просит отмену, но активной брони в базе нет. Проверьте YClients."
        )
        return

    is_package = bool(b.get("package_id"))
    pen = calculate_penalty(
        b["booking_date"],
        is_package=is_package,
        master_en_route=call.master_en_route,
        reason=call.reason,
        now=now_uae(),
    )

    # Record cancellation locally
    await bot_module.booking_service.update_booking_status(
        b["booking_id"], "cancelled", notes=f"Cancelled: {call.reason}"[:500]
    )

    penalty_note = ""
    if pen["charge_aed"] > 0:
        await bot_module.booking_service.apply_penalty(
            b["booking_id"], pen["charge_aed"], pen["reason"]
        )
        penalty_note = f"\n💸 Штраф: {pen['charge_aed']:.0f} AED ({pen['reason']})"
    elif pen["deduct_session"] and is_package and bot_module.package_service:
        await bot_module.package_service.consume_session(b["package_id"])
        penalty_note = "\n💳 Списан 1 сеанс из пакета (отмена в день визита)"
    elif pen["force_majeure"]:
        penalty_note = "\n🤝 Форс-мажор — без штрафа"
    elif pen["free"]:
        penalty_note = "\n✅ Без штрафа (заблаговременная отмена)"

    when = b["booking_date"].strftime("%d.%m.%Y %H:%M") if b.get("booking_date") else "—"
    await _admin_text(
        f"❌ <b>Отмена брони (обработать в YClients вручную)</b>\n\n"
        f"👤 {b.get('client_name') or telegram_id}\n"
        f"📞 {phone}\n"
        f"🛎️ {b['service_name']} — {when}\n"
        f"💬 Причина: {call.reason or '—'}{penalty_note}\n"
        f"🆔 YClients: {b.get('yclients_appointment_id') or '—'}"
    )

    # Waiting list: a slot just freed up — notify first match.
    await _notify_waiting_list(b.get("area"), b.get("booking_date"))


async def _handle_reschedule(telegram_id: str, phone: str, call: "RescheduleCall"):
    """Move the client's active booking to a new date/time (local) + notify admin.

    YClients is NOT auto-modified (safety rule).
    """
    import bot as bot_module
    from datetime import datetime as _dt, timedelta as _td

    b = await bot_module.booking_service.get_latest_active_booking(telegram_id)
    if not b:
        await _admin_text(
            f"📅 <b>Запрос на перенос</b>\nКлиент <code>{telegram_id}</code> "
            f"просит перенос, но активной брони нет. Проверьте YClients."
        )
        return

    try:
        new_dt = _dt.strptime(f"{call.new_date} {call.new_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        logger.error(f"Reschedule: bad datetime {call.new_date} {call.new_time}")
        return

    # Sanity window — same guard as new bookings: not in the past (1h grace),
    # not more than 60 days out. Prevents a hallucinated/past slot becoming a
    # confirmed row the scheduler then messages about.
    now_uae = _dt.utcnow() + _td(hours=4)
    if new_dt < now_uae - _td(hours=1) or new_dt > now_uae + _td(days=60):
        logger.error(f"Reschedule: new date out of window: {new_dt.isoformat()}")
        await _admin_text(
            f"⚠️ <b>Перенос отклонён</b>\nКлиент <code>{telegram_id}</code>: "
            f"новая дата вне допустимого окна ({new_dt:%d.%m.%Y %H:%M}). "
            f"Обработайте вручную."
        )
        return

    # Create the new booking, chain the old one to it. Use base_price (pre-VAT)
    # so calculate_total() doesn't re-apply VAT on an already-inclusive total.
    new_booking = await bot_module.booking_service.create_booking(
        telegram_id=telegram_id,
        service_name=b["service_name"],
        duration=b.get("duration"),
        base_price=(b.get("base_price") if b.get("base_price") is not None else 0.0),
        booking_date=new_dt,
        payment_method=b.get("payment_method") or "cash",
    )
    await bot_module.booking_service.update_booking_status(new_booking.id, "confirmed")
    await bot_module.booking_service.set_rescheduled(b["booking_id"], new_booking.id)

    old_when = b["booking_date"].strftime("%d.%m.%Y %H:%M") if b.get("booking_date") else "—"
    new_when = new_dt.strftime("%d.%m.%Y %H:%M")
    await _admin_text(
        f"📅 <b>Перенос брони (обновить в YClients вручную)</b>\n\n"
        f"👤 {b.get('client_name') or telegram_id}\n"
        f"📞 {phone}\n"
        f"🛎️ {b['service_name']}\n"
        f"⏮️ Было: {old_when}\n"
        f"⏭️ Стало: {new_when}\n"
        f"🆔 YClients: {b.get('yclients_appointment_id') or '—'}"
    )


async def _notify_waiting_list(area, freed_date):
    """When a slot frees up, ping the first matching waiting-list client."""
    import bot as bot_module
    wls = getattr(bot_module, "waiting_list_service", None)
    if not wls:
        return
    date_str = freed_date.strftime("%Y-%m-%d") if freed_date else None
    try:
        matches = await wls.get_matches(area=area, preferred_date=date_str)
    except Exception as e:
        logger.error(f"Waiting-list lookup failed: {e}")
        return
    if not matches:
        return
    first = matches[0]
    if first.get("phone") and wappi_client:
        try:
            await wappi_client.send_message(
                first["phone"],
                "Good news dear 🌹 a slot just opened up for your preferred time! "
                "Would you like to book it? 😊",
            )
            await wls.mark_notified(first["id"])
            logger.info(f"Waiting-list: notified {first['phone']}")
        except Exception as e:
            logger.error(f"Waiting-list notify failed: {e}")


async def _reset_user(user_id: str, telegram_id: str):
    """Clear context, history, and client data for a user."""
    import bot as bot_module
    dialog_manager.clear_context(user_id)
    deleted = await bot_module.message_service.clear_history(telegram_id)
    await bot_module.client_service.reset_client(telegram_id)
    await bot_module.dialog_session_service.end_session(telegram_id)
    logger.info(f"Reset user {user_id}: deleted {deleted} messages")
    return deleted


async def _process_wappi_message(phone: str, text: str, sender_name: str):
    """Background task: process WhatsApp message through AI agent."""
    try:
        import bot as bot_module

        user_id = f"wappi_{phone}"
        telegram_id = user_id

        # Check for reset commands (also handled pre-buffer in the webhook so a
        # reset sent right after another message still fires).
        if _is_reset_command(text):
            await _reset_user(user_id, telegram_id)
            if wappi_client:
                await wappi_client.send_message(
                    phone,
                    "✅ Memory cleared dear 🌹 Let's start fresh! What services are you interested in?"
                )
            return

        client = await bot_module.client_service.get_or_create_client(telegram_id)
        if sender_name and not client.name:
            await bot_module.client_service.update_client(telegram_id, name=sender_name)

        context = dialog_manager.get_or_create_context(user_id)

        if not context.recent_messages:
            db_history = await bot_module.message_service.get_conversation_history(telegram_id)
            if db_history:
                for msg in db_history[-20:]:
                    context.recent_messages.append({
                        "role": msg["role"],
                        "content": msg["content"],
                    })

        await bot_module.message_service.save_message(telegram_id, "user", text)
        dialog_manager.add_user_message(user_id, text)

        # Client replied — reset the follow-up counter so nudges restart from
        # the beginning next time they go quiet (was Telegram-only before).
        if getattr(bot_module, "follow_up_service", None):
            bot_module.follow_up_service.reset_follow_up(user_id)

        # Persist the service category so slot injection routes to the right
        # specialists on THIS and later turns (nails clients were shown
        # massage therapists because service_type stayed None on the Wappi path).
        # Last mention wins, so a client who switches massage↔nails is re-routed.
        _svc_cat = _detect_service_category(text)
        if _svc_cat and _svc_cat != (context.booking_data.get("service_type") or None):
            dialog_manager.update_booking_data(user_id, "service_type", _svc_cat)

        # Inject YClients slots if we know the area
        logger.info(
            f"slot_inject_check: yc_service={bot_module.yclients_service is not None} "
            f"mock={config.MOCK_YCLIENTS} text={text[:60]!r}"
        )
        if bot_module.yclients_service and not config.MOCK_YCLIENTS:
            _text_lower = text.lower()
            _client_area = context.client_data.get("area") or ""
            logger.info(
                f"slot_inject_entry: text_low={_text_lower!r} "
                f"area_cached={_client_area!r}"
            )
            if not _client_area:
                import re as _re_area
                # Short tokens like "raha", "yas", "mbz" match inside unrelated
                # words if we just check substring containment (e.g. "raha"
                # inside "Sarah", "yas" inside "always"). Require word
                # boundaries. Multi-word tokens like "abu dhabi" still work.
                def _has_kw(kw: str) -> bool:
                    return _re_area.search(r"\b" + _re_area.escape(kw) + r"\b", _text_lower) is not None

                # Typo-tolerant pattern for "Al Ain": covers "al ain",
                # "alain", "al-ain", "al aim" (common autocorrect),
                # "alaim", "ai ain", "aiain", etc. Allows 0-1 space/hyphen
                # between "al" and the second word, which starts with a/e/i
                # and ends in n/m (captures vowel and terminal-letter
                # autocorrects).
                _al_ain_typo = _re_area.compile(
                    r"\ba[li][\s\-]*[aie]i[nm]\b", _re_area.IGNORECASE
                )

                if _al_ain_typo.search(_text_lower) or any(
                    _has_kw(kw) for kw in ["al ain", "alain", "al-ain", "аль айн"]
                ):
                    _client_area = "al_ain"
                    dialog_manager.update_client_data(user_id, "area", "al_ain")
                elif any(_has_kw(kw) for kw in [
                    "abu dhabi", "abudhabi", "абу даби",
                    "abudabi", "abu-dhabi", "abu-dabi",  # common typos
                    "raha", "al raha", "khalifa", "al khalifa",
                    "mussafah", "mbz", "mohammed bin zayed", "mohamed bin zayed",
                    "yas", "yas island", "saadiyat", "al reem", "reem island",
                    "corniche", "tourist club", "al bateen", "bateen",
                    "shahama", "baniyas", "shamkha", "al wathba", "wathba",
                ]):
                    _client_area = "abu_dhabi"
                    dialog_manager.update_client_data(user_id, "area", "abu_dhabi")

            logger.info(f"slot_inject_post_detect: area_now={_client_area!r}")
            if _client_area:
                try:
                    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
                    _uae = _tz(_td(hours=4))
                    _now = _dt.now(_uae)
                    today = _now.strftime("%Y-%m-%d")
                    tomorrow = (_now + _td(days=1)).strftime("%Y-%m-%d")

                    service_name = context.booking_data.get("service_type") or ""
                    slots_today = await bot_module.yclients_service.get_available_slots_summary(
                        date=today, service_name=service_name)
                    slots_tomorrow = await bot_module.yclients_service.get_available_slots_summary(
                        date=tomorrow, service_name=service_name)

                    # Detect specific date mentioned in message (e.g. "Sunday", "26 april", "sat")
                    extra_dates = []
                    logger.info(
                        f"weekday_detect: text_low={_text_lower!r} "
                        f"today={today} tomorrow={tomorrow} "
                        f"current_wd={_now.weekday()}"
                    )
                    _day_keywords = {
                        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                        "friday": 4, "saturday": 5, "sunday": 6,
                        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
                        "понедел": 0, "вторник": 1, "сред": 2, "четверг": 3,
                        "пятниц": 4, "суббот": 5, "воскрес": 6,
                    }
                    import re as _re_day
                    for kw, weekday in _day_keywords.items():
                        # Word-boundary match: "sat" must not match "satellite",
                        # "mon" must not match "money", "fri" must not match
                        # "afraid". Russian prefixes (e.g. "понедел") anchor
                        # only at start — still match "понедельник".
                        if _re_day.search(r"\b" + kw, _text_lower):
                            # For English full/short forms also require \b at
                            # end. "понедел" is a prefix, leave trailing open.
                            if kw.isascii() and not _re_day.search(r"\b" + kw + r"\b", _text_lower):
                                continue
                            _current_wd = _now.weekday()
                            days_ahead = (weekday - _current_wd) % 7
                            # If today matches — today (not next week)
                            if days_ahead == 0 and "next" in _text_lower:
                                days_ahead = 7
                            target_date = (_now + _td(days=days_ahead)).strftime("%Y-%m-%d")
                            if target_date != today and target_date != tomorrow:
                                extra_dates.append(target_date)
                                # Persist the chosen day so a later turn with no
                                # weekday word (villa/name/GPS/"cash") keeps
                                # injecting THIS day's slots — fixes the
                                # "loses Sunday then says no schedule" dead-end.
                                dialog_manager.update_booking_data(
                                    user_id, "date", target_date
                                )
                            logger.info(
                                f"weekday_detect: matched kw={kw!r} → "
                                f"weekday={weekday} days_ahead={days_ahead} "
                                f"target={target_date} appended={target_date not in (today, tomorrow)}"
                            )
                            break
                    else:
                        logger.info("weekday_detect: no weekday keyword matched")

                    # Fetch slots for specific date if mentioned.
                    # We label each date with its weekday name so the LLM
                    # can map the client's "Wednesday" / "среда" to the
                    # actual ISO date — without that bridge it claims
                    # "I don't have availability info yet" even when the
                    # context lists "2026-04-29: <real slots>". (See bug
                    # report 2026-04-27: client asked for Wednesday and
                    # Thursday, bot fell back to "tomorrow" despite
                    # having the data.)
                    _weekday_names = [
                        "Monday", "Tuesday", "Wednesday", "Thursday",
                        "Friday", "Saturday", "Sunday",
                    ]

                    def _label(date_str: str) -> str:
                        try:
                            wd = _dt.strptime(date_str, "%Y-%m-%d").weekday()
                            return f"{_weekday_names[wd]} ({date_str})"
                        except Exception:
                            return date_str

                    # Always include the booking's chosen date if it's set —
                    # otherwise once the client has picked Sunday and the
                    # next message is just "Villa 23" / a GPS pin / their
                    # name (no weekday keyword), the slot block falls back
                    # to today+tomorrow only. The model then sees Sunday
                    # in chat history but no Sunday data in the context
                    # and emits "Sorry, we don't have Sunday schedule"
                    # AFTER it has already confirmed Sunday 12:00. Real
                    # bug from the 2026-04-27 16:09 UAE chat.
                    chosen_date = (context.booking_data or {}).get("date")
                    if chosen_date and chosen_date not in extra_dates \
                            and chosen_date != today and chosen_date != tomorrow:
                        extra_dates.insert(0, chosen_date)

                    extra_slots_text = ""
                    for d in extra_dates[:2]:  # chosen date + at most 1 mentioned extra
                        try:
                            slots = await bot_module.yclients_service.get_available_slots_summary(
                                date=d, service_name=service_name)
                            extra_slots_text += f"\n\n{_label(d)}:\n{slots}"
                        except Exception:
                            pass

                    area_note = ""
                    if _client_area == "al_ain":
                        area_note = "\n🚨 Client in AL AIN. Show ONLY Al Ain therapists."
                    elif _client_area == "abu_dhabi":
                        area_note = "\n🚨 Client in ABU DHABI. Do NOT show Al Ain therapists."

                    # Build a list of weekdays that ARE in this context so we
                    # can name them explicitly in the guard. The LLM keeps
                    # echoing its own previous "I don't have Sunday schedule
                    # yet" replies from chat history; naming the available
                    # weekdays inline forces it to compare against ground
                    # truth instead of pattern-matching on past responses.
                    _today_wd = _weekday_names[_dt.strptime(today, "%Y-%m-%d").weekday()]
                    _tom_wd = _weekday_names[_dt.strptime(tomorrow, "%Y-%m-%d").weekday()]
                    _extra_wd_list = []
                    for d in extra_dates[:1]:
                        try:
                            _extra_wd_list.append(
                                _weekday_names[_dt.strptime(d, "%Y-%m-%d").weekday()]
                            )
                        except Exception:
                            pass
                    _all_wd = ", ".join([_today_wd, _tom_wd] + _extra_wd_list)

                    context.extra_system_info = (
                        f"\n\nREAL AVAILABLE SLOTS (ground truth — overrides anything you said before):\n"
                        f"TODAY — {_label(today)}:\n{slots_today}\n\n"
                        f"TOMORROW — {_label(tomorrow)}:\n{slots_tomorrow}"
                        f"{extra_slots_text}\n\n"
                        f"🚨 The schedule above is the GROUND TRUTH. Available weekdays in "
                        f"this context: {_all_wd}.\n"
                        "🚨 If the client names ANY of those weekdays (in EN or RU: Wednesday / "
                        "среда / Thursday / четверг / Sunday / воскресенье …), MATCH it to the "
                        "labelled block above and quote those exact slots. NEVER reply 'I don't "
                        "have [weekday] schedule yet' / 'no availability info' for a weekday "
                        "that is IN this context — that's a hallucination from earlier in the "
                        "chat, ignore your past replies on this point.\n"
                        "🚨 PRESENTATION ORDER: when the client hasn't named a specific day, "
                        "offer TODAY's slots first. If the client doesn't want today, ask 'When "
                        "would suit you dear?' instead of jumping straight to tomorrow.\n"
                        "🚨 Use ONLY these real slots. Answer immediately — do NOT say 'checking'."
                        f"{area_note}"
                    )
                except Exception as e:
                    logger.warning(f"Wappi: failed to fetch slots: {e}")
            else:
                # Area unknown but user might be asking about timing
                # ("when", "available", "tomorrow", "сегодня", etc.).
                # Without real slots the model happily invents times
                # like "2pm, 4pm, 6pm" — caught red-handed in a live
                # test. Inject a hard rule instead: never volunteer
                # times before we know the area.
                _asks_time = any(
                    kw in _text_lower for kw in (
                        "when", "time", "available", "slot", "schedule",
                        "today", "tomorrow", "morning", "afternoon", "evening",
                        "когда", "время", "свободн", "сегодня", "завтра",
                        "утро", "день", "вечер",
                    )
                )
                if _asks_time:
                    context.extra_system_info = (
                        "\n\n⚠️ CLIENT AREA IS STILL UNKNOWN.\n"
                        "🚨 NEVER show or invent specific times (no '2pm', "
                        "'4pm', '10:00', etc.) before area is confirmed.\n"
                        "🚨 If the client asks about timing, reply first:\n"
                        "    'Are you in Abu Dhabi or Al Ain dear? 🌹'\n"
                        "   Once they answer, the system will provide real "
                        "slots on the next turn.\n"
                        "🚨 Do NOT guess the area from ambiguous words. "
                        "Ask explicitly."
                    )

        # LLM timeout — OpenAI hangs cost us background-task slots and
        # leave clients silent indefinitely. 30s is well above p99 for
        # GPT-4o-class models; anything longer is a hang, not a slow run.
        #
        # Uses the with_tools path: the agent may call book_appointment,
        # in which case we get a structured BookingCall alongside the
        # reply text and create the YClients record directly from those
        # fields — no regex parsing of the reply.
        response_text: str = ""
        actions = AgentActions()
        try:
            response_text, actions = await asyncio.wait_for(
                booking_agent.process_message_with_tools(text, context),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.error(f"Wappi [{phone}]: booking_agent timed out after 30s")
            response_text = "Sorry dear, one moment 🙏 Please repeat your message 🌹"
        booking_call: Optional[BookingCall] = actions.booking_call

        if not response_text or not response_text.strip():
            response_text = "Just a moment dear 🙏"

        # Post-hoc area detection from the BOT's reply. The model is
        # smarter at reading typos than our regex (e.g. user wrote
        # "Al aim" — user-side detector missed it, but the model still
        # replied "Al Ain noted 😊"). Trust the model's interpretation
        # and write area into client_data so the next turn gets slot
        # injection. Requires both a confirming verb AND the area
        # name to avoid false positives from free narration.
        if not context.client_data.get("area"):
            import re as _re_posthoc
            _resp_low = response_text.lower()
            _mentions_both = ("al ain" in _resp_low or "al-ain" in _resp_low) and \
                             "abu dhabi" in _resp_low
            # CRITICAL: the bot's OWN disambiguation question "Are you in Abu
            # Dhabi or Al Ain dear?" contains "in abu dhabi" and both city
            # names — the old regex fired on it and LOCKED the wrong area
            # before the client even answered. Skip when the reply names both
            # cities or is itself a question.
            if _mentions_both or "?" in response_text:
                _area_confirm = None
            else:
                # Only STRONG confirmation signals (dropped weak prepositions
                # in/for/to/with that matched free narration).
                _area_confirm = _re_posthoc.search(
                    r"\b(?:noted|confirmed|your area is|area:|you're in|you are in|great,?\s*)\s*"
                    r"(?:—\s*)?"
                    r"(al\s*ain|abu\s*dhabi)\b",
                    _resp_low,
                ) or _re_posthoc.search(
                    r"\b(al\s*ain|abu\s*dhabi)\s+(?:noted|confirmed|it is)\b", _resp_low
                )
            if _area_confirm:
                area_kw = _area_confirm.group(1).replace(" ", "_")
                if "al" in area_kw and "ain" in area_kw:
                    _detected = "al_ain"
                elif "abu" in area_kw and "dhabi" in area_kw:
                    _detected = "abu_dhabi"
                else:
                    _detected = None
                if _detected:
                    logger.info(
                        f"Wappi [{phone}]: post-hoc area detection from bot "
                        f"reply → {_detected}"
                    )
                    dialog_manager.update_client_data(user_id, "area", _detected)

        await bot_module.message_service.save_message(telegram_id, "assistant", response_text)
        dialog_manager.add_bot_response(user_id, response_text)

        if wappi_client:
            parts = [p.strip() for p in response_text.split("---MESSAGE_SPLIT---") if p.strip()]
            # Guard against a reply that is only the separator/whitespace —
            # response_text.strip() is non-empty (so the earlier empty-fallback
            # was skipped) but parts is [], and the client would get nothing.
            if not parts:
                parts = ["Just a moment dear 🙏"]
            # Small delay between parts: Wappi + WhatsApp can reorder
            # near-simultaneous sends, which breaks narrative flow (parts
            # arriving out of order, or admin/marketing inserts falling
            # between them). 0.4s per part gives WhatsApp time to process
            # in the intended order and also feels more natural to the
            # recipient (simulates typing).
            for i, part in enumerate(parts):
                if i > 0:
                    await asyncio.sleep(0.4)
                await wappi_client.send_message(phone, part)
        elif not wappi_client:
            # No Wappi client at message time (creds missing/rotated) — the
            # client gets NO reply. Make the failure loud instead of silent.
            logger.error(
                f"Wappi [{phone}]: NO wappi_client — reply NOT delivered. "
                f"Check WAPPI_TOKEN/WAPPI_PROFILE_ID."
            )

        # Post-booking: create DB + YClients record if the agent called
        # the book_appointment tool. If it sent a ✅ confirmation WITHOUT
        # calling the tool, _maybe_create_booking alerts the admin and
        # doesn't create anything — no more guessing dates from text.
        await _maybe_create_booking(
            user_id, telegram_id, phone, sender_name, context,
            response_text, booking_call,
        )

        # Cancellation / reschedule actions (FR-5.1–5.3, 7.2).
        if actions.cancel_call is not None:
            await _handle_cancellation(telegram_id, phone, actions.cancel_call)
        if actions.reschedule_call is not None:
            await _handle_reschedule(telegram_id, phone, actions.reschedule_call)

    except Exception as e:
        logger.error(f"Wappi background processing error: {e}", exc_info=True)
        if wappi_client:
            try:
                await wappi_client.send_message(
                    phone,
                    "Sorry dear, technical issue 🙏 Please try again in a moment 🌹"
                )
            except Exception:
                pass


@app.post("/admin/reset/{phone}")
async def admin_reset(phone: str, request: Request):
    """Clear dialog history for a WhatsApp user by phone.

    Protected by WEBHOOK_SECRET header: X-Admin-Secret
    Usage: curl -X POST https://.../admin/reset/375447574000 -H "X-Admin-Secret: <secret>"
    """
    secret = request.headers.get("X-Admin-Secret", "")
    if not config.WEBHOOK_SECRET or secret != config.WEBHOOK_SECRET:
        return Response(status_code=403, content="forbidden")

    phone_clean = phone.replace("+", "").strip()
    user_id = f"wappi_{phone_clean}"
    deleted = await _reset_user(user_id, user_id)
    return {"status": "ok", "phone": phone_clean, "messages_deleted": deleted}


@app.get("/admin/health/yclients")
async def admin_yclients_health(request: Request):
    """Diagnostic: is the YClients user_token still valid?

    Runs get_records() for the first staff member on today's date.
    A 401 ("Не указан идентификатор пользователя") means the token
    on this deploy has expired — the bot will stop producing real
    slots until it's rotated.

    Protected by X-Admin-Secret header.
    Usage: curl https://.../admin/health/yclients -H "X-Admin-Secret: <secret>"
    """
    secret = request.headers.get("X-Admin-Secret", "")
    if not config.WEBHOOK_SECRET or secret != config.WEBHOOK_SECRET:
        return Response(status_code=403, content="forbidden")

    import bot as bot_module
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    if not bot_module.yclients_service:
        return {
            "status": "not_configured",
            "detail": "yclients_service is None (MOCK_YCLIENTS or missing tokens)",
        }

    try:
        staff = await bot_module.yclients_service.get_staff()
    except Exception as e:
        return {"status": "error", "stage": "get_staff", "detail": str(e)}

    if not staff:
        return {"status": "partner_token_fail", "detail": "get_staff returned empty"}

    today = _dt.now(_tz(_td(hours=4))).strftime("%Y-%m-%d")
    sample = staff[0]
    recs = await bot_module.yclients_service.get_records(sample["id"], today)
    if recs is None:
        return {
            "status": "user_token_fail",
            "detail": (
                "records API returned None (likely 401 'Не указан "
                "идентификатор пользователя'). Rotate YCLIENTS_USER_TOKEN "
                "in the deploy env and redeploy."
            ),
            "staff_probed": {"id": sample["id"], "name": sample.get("name")},
            "date": today,
        }
    return {
        "status": "ok",
        "records_count": len(recs),
        "staff_probed": {"id": sample["id"], "name": sample.get("name")},
        "date": today,
    }


@app.post("/webhook/wappi")
async def wappi_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive WhatsApp messages via Wappi.pro webhook.

    Responds with 200 OK immediately, then processes in background.
    Prevents Wappi retries that cause duplicate responses.
    Deduplicates by message_id (5 min TTL).
    """
    # Verify optional auth secret
    if config.WAPPI_WEBHOOK_SECRET:
        auth = request.headers.get("Authorization", "")
        if auth != config.WAPPI_WEBHOOK_SECRET:
            logger.warning("Wappi webhook: invalid auth")
            return Response(status_code=403)

    try:
        data = await request.json()
    except Exception as e:
        logger.error(f"Wappi webhook: invalid JSON: {e}")
        return {"status": "bad_json"}

    parsed = parse_incoming_message(data)
    if not parsed:
        return {"status": "ignored"}

    phone = parsed["phone"]
    text = parsed["text"]
    sender_name = parsed["sender_name"]
    msg_type = parsed["message_type"]
    message_id = parsed.get("message_id", "")
    latitude = parsed.get("latitude")
    longitude = parsed.get("longitude")

    # Dedup: skip if we've already processed this message_id.
    if _dedup_seen(message_id, time.time()):
        logger.info(f"Wappi: duplicate message {message_id} ignored")
        return {"status": "duplicate"}

    logger.info(f"Wappi [{phone}] {sender_name}: {text[:100]}")

    # Location message — synthesize a text representation so the agent
    # treats it like a client sharing their address. Also prime
    # context.client_data with coords + inferred area so the slot-injection
    # code path in _process_wappi_message picks the right therapists.
    if msg_type == "location" and latitude is not None and longitude is not None:
        user_id = f"wappi_{phone}"
        area = _area_from_coords(latitude, longitude)

        if area:
            # Valid UAE coordinates — store them, model may use in address.
            dialog_manager.update_client_data(
                user_id, "location", {"lat": latitude, "lng": longitude}
            )
            dialog_manager.update_client_data(user_id, "area", area)
            area_label = {
                "abu_dhabi": "Abu Dhabi",
                "al_ain": "Al Ain",
            }.get(area, "UAE")
            synthetic_text = (
                f"[Client shared GPS location in {area_label} "
                f"(lat={latitude:.5f}, lng={longitude:.5f}). Use this as "
                f"their address field — you still need to ask for the "
                f"building / villa / apartment number if not obvious.]"
            )
        else:
            # Coordinates outside UAE — clients testing from abroad, or
            # an accidental pin. Do NOT store the coords as "location"
            # (model took them and stuffed them into tool-call address,
            # which confused admin seeing Minsk GPS in a UAE booking).
            # Tell the model to ask for a text address instead.
            synthetic_text = (
                f"[Client shared a GPS location OUTSIDE the UAE "
                f"(lat={latitude:.5f}, lng={longitude:.5f}). DO NOT use "
                f"these coordinates as their address. Ask the client to "
                f"type their Abu Dhabi or Al Ain address in text (e.g. "
                f"'Khalifa City, Villa 42'). If area is still unknown, "
                f"ask 'Are you in Abu Dhabi or Al Ain dear?' first.]"
            )
            logger.info(
                f"Wappi [{phone}] non-UAE location "
                f"({latitude:.3f}, {longitude:.3f}) — asking for text address"
            )

        logger.info(f"Wappi [{phone}] location → {area or 'non_uae'}")
        background_tasks.add_task(
            _buffer_and_process_wappi, phone, synthetic_text, sender_name
        )
        return {"status": "location_accepted", "area": area or "outside_uae"}

    # Other non-text messages (image, audio, video, document, sticker…) —
    # we can't read them yet. Acknowledge politely and ask for text.
    if msg_type != "chat" or not text:
        if wappi_client:
            background_tasks.add_task(
                wappi_client.send_message,
                phone,
                "Sorry dear, I can only read text messages right now 🙏 "
                "Please type your question in text 🌹"
            )
        return {"status": "non_text"}

    # Reset command — handle BEFORE buffering. Otherwise a "/clear" arriving
    # within 7s of a prior message gets joined ("book sunday\n/clear") and the
    # exact-match reset check never fires (reported "не очищает историю").
    if _is_reset_command(text):
        user_id = f"wappi_{phone}"
        # Drop any pending buffered fragments so they don't process post-reset.
        _wappi_buffer.pop(phone, None)
        background_tasks.add_task(_reset_and_greet, phone, user_id)
        return {"status": "reset"}

    # Schedule buffered processing (7s wait to combine multi-part messages per PRD 4.1.6)
    background_tasks.add_task(_buffer_and_process_wappi, phone, text, sender_name)
    return {"status": "accepted"}


async def _reset_and_greet(phone: str, user_id: str):
    """Reset a user's state and send the fresh-start greeting (WhatsApp)."""
    try:
        await _reset_user(user_id, user_id)
        if wappi_client:
            await wappi_client.send_message(
                phone,
                "✅ Memory cleared dear 🌹 Let's start fresh! What services are you interested in?"
            )
    except Exception as e:
        logger.error(f"Reset-and-greet failed for {phone}: {e}")


# ── Coordinate → area classifier ─────────────────────────────────────
# Crystal Lab serves Abu Dhabi + Al Ain only. Pick the nearer of the two
# city centers, but only if within ~0.6° (~66 km). Anything farther
# (Dubai, Sharjah, outside UAE) returns None — the agent will ask the
# client to confirm the area in text.
_AREA_CENTERS = {
    "abu_dhabi": (24.47, 54.37),   # Abu Dhabi city
    "al_ain":    (24.21, 55.75),   # Al Ain city
}
_AREA_RADIUS_DEG = 0.6  # ~66 km; covers outskirts, excludes Dubai


def _area_from_coords(lat: float, lng: float) -> Optional[str]:
    """Return 'abu_dhabi' | 'al_ain' | None for a GPS coordinate.

    None means "unknown / outside service area" — the agent should ask
    the client to confirm their area in text rather than assume.
    """
    best_area: Optional[str] = None
    best_d2 = _AREA_RADIUS_DEG * _AREA_RADIUS_DEG
    for area, (clat, clng) in _AREA_CENTERS.items():
        # Squared Euclidean distance in degrees. Good enough at UAE
        # latitudes for a binary classifier with a 0.6° threshold —
        # no need for haversine.
        d2 = (lat - clat) ** 2 + (lng - clng) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_area = area
    return best_area


@app.get("/webhook/instagram")
async def instagram_verify(request: Request):
    """Meta webhook verification handshake (GET hub.challenge)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token == config.INSTAGRAM_VERIFY_TOKEN:
        logger.info("Instagram webhook verified")
        return Response(content=challenge or "", media_type="text/plain")
    logger.warning("Instagram webhook verification failed")
    return Response(content="forbidden", status_code=403)


@app.post("/webhook/instagram")
async def instagram_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive Instagram DMs, qualify briefly, hand off to WhatsApp (CTA)."""
    import hashlib
    import hmac
    import json as _json
    from services.instagram_client import (
        parse_instagram_events, build_handoff_reply, send_instagram_message,
    )

    raw = await request.body()

    # Verify Meta's X-Hub-Signature-256 (HMAC-SHA256 of the raw body) when an
    # app secret is configured. Reject forgeries before doing any work.
    if config.INSTAGRAM_APP_SECRET:
        sig = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            config.INSTAGRAM_APP_SECRET.encode(), raw, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            logger.warning("Instagram webhook: bad signature")
            return Response(content="forbidden", status_code=403)

    try:
        payload = _json.loads(raw or b"{}")
    except ValueError:
        return Response(content="bad request", status_code=400)
    events = parse_instagram_events(payload)
    logger.info(f"Instagram webhook: {len(events)} event(s)")

    for ev in events:
        # Lightweight qualification: pass the prospect's first line as context
        # into the WhatsApp deep link so the agent picks up where IG left off.
        context_hint = ev["text"][:120]
        reply = build_handoff_reply(prefill_context=context_hint)
        background_tasks.add_task(send_instagram_message, ev["sender_id"], reply)

    return {"status": "ok", "events": len(events)}


@app.post("/admin/share-with-driver/{booking_id}")
async def admin_share_with_driver(booking_id: int, request: Request):
    """Push a logistics notification to the driver group for a booking
    (FR 5.2 'share with driver'). Master/admin triggers this manually.
    """
    import bot as bot_module
    if config.WEBHOOK_SECRET:
        secret = request.headers.get("X-Admin-Secret", "")
        if secret != config.WEBHOOK_SECRET:
            return Response(content="forbidden", status_code=403)

    if not config.DRIVER_TELEGRAM_CHAT_ID:
        return {"status": "no_driver_configured"}

    # Find the booking + client
    from sqlalchemy import select
    from database.models import Booking, Client
    async with bot_module.booking_service.db.session() as session:
        row = (await session.execute(
            select(Booking, Client).join(Client, Booking.client_id == Client.id)
            .where(Booking.id == booking_id)
        )).first()
    if not row:
        return {"status": "booking_not_found"}
    b, c = row

    when = b.booking_date.strftime("%d.%m.%Y %H:%M") if b.booking_date else "—"
    maps = ""
    if c.location_latitude and c.location_longitude:
        maps = f"\n🗺️ https://maps.google.com/?q={c.location_latitude},{c.location_longitude}"
    text = (
        f"🚗 <b>New transport request</b>\n\n"
        f"📅 {when}\n"
        f"💆 {b.service_name} ({b.duration or '?'} min)\n"
        f"👤 {c.name or 'Client'} — {c.phone or '—'}\n"
        f"📍 {c.location_details or '—'}{maps}"
    )
    try:
        await bot_instance.send_message(
            chat_id=config.DRIVER_TELEGRAM_CHAT_ID, text=text, parse_mode="HTML"
        )
        return {"status": "sent"}
    except Exception as e:
        logger.error(f"Driver notify failed: {e}")
        return {"status": "error", "detail": str(e)}


@app.post("/admin/payment/{booking_id}/paid")
async def admin_mark_paid(booking_id: int, request: Request):
    """Mark a booking as paid (admin reconciles a bank transfer)."""
    import bot as bot_module
    if config.WEBHOOK_SECRET:
        secret = request.headers.get("X-Admin-Secret", "")
        if secret != config.WEBHOOK_SECRET:
            return Response(content="forbidden", status_code=403)
    from services.payment import PaymentService
    try:
        await PaymentService(bot_module.booking_service).mark_paid(booking_id)
        return {"status": "paid", "booking_id": booking_id}
    except Exception as e:
        logger.error(f"mark_paid failed: {e}")
        return {"status": "error", "detail": str(e)}


@app.post("/webhook/manychat")
async def manychat_webhook(request: Request):
    """Receive ManyChat External Request.

    ManyChat sends subscriber data + message, we process through AI agent
    and return v2 Dynamic Content JSON.
    """
    data = await request.json()
    logger.info(f"ManyChat webhook: {data}")

    # TODO: implement full ManyChat processing (Task #14)
    # For now, return a simple acknowledgement
    subscriber_id = data.get("subscriber_id", "unknown")
    message_text = data.get("last_input_text", "")
    channel = data.get("channel", "unknown")

    logger.info(f"ManyChat [{channel}] from {subscriber_id}: {message_text}")

    return {
        "version": "v2",
        "content": {
            "messages": [
                {
                    "type": "text",
                    "text": "Thank you for your message! Our team will get back to you shortly. 💎"
                }
            ],
            "actions": [
                {
                    "action": "add_tag",
                    "tag_name": "bot_responded"
                }
            ]
        }
    }
