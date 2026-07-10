"""Notification service for sending updates to Telegram group"""

import os
from typing import Optional
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from loguru import logger

from database.models import Client, Booking


class NotificationService:
    """Service for sending notifications to admin Telegram group"""

    # Admin alerts must NEVER die silently: the configured group turned out
    # not to exist on prod (getChat 400, live 2026-07-10) and every alert —
    # including "booking NOT synced to YClients" — vanished into the void.
    # When the group send fails, fall back to a direct DM (Dmitry).
    FALLBACK_CHAT_ID = os.getenv("ALERT_FALLBACK_CHAT_ID", "1379584180")

    def __init__(self, bot: Bot, group_chat_id: Optional[str] = None):
        """
        Initialize notification service

        Args:
            bot: Telegram Bot instance
            group_chat_id: Telegram group chat ID (e.g., "-1001234567890")
        """
        self.bot = bot
        self.group_chat_id = group_chat_id

        if self.group_chat_id:
            logger.info(f"Notifications enabled for group: {self.group_chat_id}")
        else:
            logger.warning("No group chat ID provided - notifications disabled")

    async def _send_with_fallback(self, **kwargs):
        """Send to the admin group; on ANY failure re-send to the fallback DM
        so a booking-failure alert can't disappear with a dead group id."""
        try:
            await self.bot.send_message(chat_id=self.group_chat_id, **kwargs)
        except Exception as e:
            logger.error(
                f"Admin-group send failed ({e}) — falling back to DM "
                f"{self.FALLBACK_CHAT_ID}"
            )
            text = kwargs.get("text") or ""
            kwargs["text"] = f"⚠️ (группа алертов недоступна)\n{text}"
            await self.bot.send_message(chat_id=self.FALLBACK_CHAT_ID, **kwargs)

    async def send_new_client(self, client: Client):
        """Notify about new client"""
        if not self.group_chat_id:
            return

        message = f"""🆕 <b>Новый клиент!</b>

👤 Telegram ID: <code>{client.telegram_id}</code>
📅 Зарегистрирован: {client.created_at.strftime('%d.%m.%Y %H:%M')}

Ожидаем первое бронирование..."""

        try:
            await self._send_with_fallback(
                text=message,
                parse_mode="HTML",
            )
            logger.info(f"Sent new client notification to group")
        except TelegramBadRequest as e:
            logger.error(f"Failed to send notification: {e}")

    async def send_booking_request(
        self,
        client: Client,
        booking: Booking,
        conversation_link: Optional[str] = None,
    ):
        """Notify about new booking request"""
        if not self.group_chat_id:
            return

        # Format client info
        client_info = f"👤 {client.name}" if client.name else f"👤 Клиент #{client.id}"

        # Format location
        location_info = ""
        if client.location_latitude and client.location_longitude:
            location_info = f"\n📍 <a href='https://maps.google.com/?q={client.location_latitude},{client.location_longitude}'>Локация на карте</a>"
        if client.location_details:
            location_info += f"\n🏠 {client.location_details}"

        # Format medical notes
        medical_info = ""
        if client.medical_notes:
            medical_info = f"\n\n⚕️ <b>Медицинские заметки:</b>\n{client.medical_notes}"

        # Format booking
        price_info = ""
        if booking.total_price:
            price_info = f"\n💰 {booking.total_price} AED (включая 5% VAT)"

        # Conversation link
        conv_link = ""
        if conversation_link:
            conv_link = f"\n\n💬 <a href='{conversation_link}'>Открыть диалог с клиентом</a>"

        message = f"""📋 <b>Новая заявка на бронирование!</b>

{client_info}
📞 Telegram: @{client.telegram_id if not client.telegram_id.isdigit() else f'ID: {client.telegram_id}'}

🛎️ <b>Услуга:</b> {booking.service_name}
⏱️ <b>Длительность:</b> {booking.duration} мин
📅 <b>Дата:</b> {booking.booking_date.strftime('%d.%m.%Y %H:%M') if booking.booking_date else 'Не указана'}
{price_info}
{location_info}
{medical_info}
{conv_link}

📊 Статус: <b>{self._format_status(booking.status)}</b>"""

        try:
            await self._send_with_fallback(
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
            logger.info(f"Sent booking notification to group for booking {booking.id}")
        except TelegramBadRequest as e:
            logger.error(f"Failed to send booking notification: {e}")

    async def send_booking_confirmed(self, client: Client, booking: Booking):
        """Notify about confirmed booking"""
        if not self.group_chat_id:
            return

        # Format client info with name and phone
        client_info = f"👤 {client.name}" if client.name else f"👤 Клиент #{client.id}"
        if client.phone:
            client_info += f"\n📞 {client.phone}"

        # Format location
        location_info = ""
        if client.location_latitude and client.location_longitude:
            location_info = f"\n📍 <a href='https://maps.google.com/?q={client.location_latitude},{client.location_longitude}'>Локация на карте</a>"
        if client.location_details:
            location_info += f"\n🏠 {client.location_details}"

        # Format service duration
        duration_info = f" ({booking.duration} мин)" if booking.duration else ""

        # Format price with payment method details
        if booking.total_price:
            if booking.payment_method == "cash":
                price_str = f"{booking.total_price:.2f} AED 💵 (наличные, без VAT)"
            elif booking.payment_method in ("transfer", "bank_transfer"):
                base = booking.base_price if booking.base_price else 0
                vat = booking.vat_amount if booking.vat_amount else 0
                price_str = f"{booking.total_price:.2f} AED 🏦 (перевод: {base:.2f} + {vat:.2f} VAT)"
            else:
                price_str = f"{booking.total_price:.2f} AED"
        else:
            price_str = "Не указана"

        message = f"""✅ <b>Бронирование подтверждено!</b>

{client_info}
🛎️ {booking.service_name}{duration_info}
📅 {booking.booking_date.strftime('%d.%m.%Y %H:%M') if booking.booking_date else 'TBD'}
💰 {price_str}
{location_info}

✅ Добавлено в YClients!"""

        try:
            await self._send_with_fallback(
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
            logger.info(f"Sent confirmation notification for booking {booking.id}")
        except TelegramBadRequest as e:
            logger.error(f"Failed to send confirmation: {e}")

    async def send_lead(self, client: Client, channel: str = "telegram"):
        """Notify admin about a qualified lead (client provided name+phone but not yet booked).

        Per PRD 4.2 step 11: forward lead/booking details to admin channel.
        """
        if not self.group_chat_id:
            return
        channel_emoji = {"telegram": "💬", "wappi": "📱", "instagram": "📸", "whatsapp": "📱"}.get(channel, "💬")
        name = client.name or "—"
        phone = client.phone or "—"
        message = (
            f"🔥 <b>Новый лид ({channel_emoji} {channel})</b>\n\n"
            f"👤 Имя: {name}\n"
            f"📞 Телефон: {phone}\n"
            f"🆔 ID: <code>{client.telegram_id}</code>\n\n"
            f"Клиент оставил контакты, но ещё не забронировал."
        )
        try:
            await self._send_with_fallback(
                text=message,
                parse_mode="HTML",
            )
            logger.info(f"Sent lead notification for {client.telegram_id}")
        except Exception as e:
            logger.error(f"Failed to send lead notification: {e}")

    async def send_booking_failed(self, telegram_id: str, reason: str):
        """Notify admin that a booking was confirmed by bot but could not be saved
        (missing service/price/date). Admin should handle manually."""
        if not self.group_chat_id:
            return
        message = (
            f"⚠️ <b>Бронирование требует ручной обработки</b>\n\n"
            f"Клиент: <code>{telegram_id}</code>\n"
            f"Причина: {reason[:500]}\n\n"
            f"Бот подтвердил бронь, но не смог извлечь услугу/цену/дату. "
            f"Проверьте диалог и создайте запись вручную."
        )
        try:
            await self._send_with_fallback(
                text=message,
                parse_mode="HTML",
            )
            logger.warning(f"Sent booking_failed notification for {telegram_id}")
        except Exception as e:
            logger.error(f"Failed to send booking_failed notification: {e}")

    async def send_booking_cancelled(
        self,
        client: Client,
        booking: Booking,
        reason: Optional[str] = None,
    ):
        """Notify about cancelled booking"""
        if not self.group_chat_id:
            return

        client_info = f"👤 {client.name}" if client.name else f"👤 Клиент #{client.id}"
        reason_info = f"\n💬 Причина: {reason}" if reason else ""

        message = f"""❌ <b>Бронирование отменено</b>

{client_info}
🛎️ {booking.service_name}
📅 {booking.booking_date.strftime('%d.%m.%Y %H:%M') if booking.booking_date else 'TBD'}
{reason_info}"""

        try:
            await self._send_with_fallback(
                text=message,
                parse_mode="HTML",
            )
            logger.info(f"Sent cancellation notification for booking {booking.id}")
        except TelegramBadRequest as e:
            logger.error(f"Failed to send cancellation: {e}")

    async def send_lost_client_alert(self, client: Client, last_message: str):
        """Notify about lost client (inactive > 1 hour)"""
        if not self.group_chat_id:
            return

        client_info = f"👤 {client.name}" if client.name else f"👤 Клиент #{client.id}"

        message = f"""⚠️ <b>Потенциально потерянный клиент!</b>

{client_info}
📞 Telegram: @{client.telegram_id if not client.telegram_id.isdigit() else f'ID: {client.telegram_id}'}

Более 1 часа нет активности в диалоге.

Последнее сообщение клиента:
💬 "{last_message[:100]}..."

Рекомендуется связаться с клиентом!"""

        try:
            await self._send_with_fallback(
                text=message,
                parse_mode="HTML",
            )
            logger.warning(f"Sent lost client alert for {client.telegram_id}")
        except TelegramBadRequest as e:
            logger.error(f"Failed to send lost client alert: {e}")

    async def send_medical_note_alert(self, client: Client, note: str):
        """Notify about important medical information"""
        if not self.group_chat_id:
            return

        client_info = f"👤 {client.name}" if client.name else f"👤 Клиент #{client.id}"

        message = f"""⚕️ <b>ВАЖНО: Медицинская информация!</b>

{client_info}
📞 Telegram: @{client.telegram_id if not client.telegram_id.isdigit() else f'ID: {client.telegram_id}'}

Клиент упомянул медицинское противопоказание:
💬 "{note}"

⚠️ Необходимо проинформировать мастера перед визитом!"""

        try:
            await self._send_with_fallback(
                text=message,
                parse_mode="HTML",
            )
            logger.warning(f"Sent medical note alert for {client.telegram_id}")
        except TelegramBadRequest as e:
            logger.error(f"Failed to send medical alert: {e}")

    @staticmethod
    def _format_status(status: str) -> str:
        """Format booking status in Russian"""
        status_map = {
            "draft": "Черновик",
            "confirmed": "Подтверждено ✅",
            "in_progress": "В процессе",
            "completed": "Завершено",
            "cancelled": "Отменено",
        }
        return status_map.get(status, status)
