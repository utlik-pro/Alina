"""Replay client turns through the final channel pipeline, with no external I/O."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
import bot
import webhook_app as wh
from agents.tools import AgentActions
from dialog_context import DialogManager

@pytest.fixture
def dialogue(monkeypatch):
    dm = DialogManager()
    client = SimpleNamespace(name='Test', phone=None, area='abu_dhabi',
                             preferred_therapist=None, avoid_therapist=None)
    monkeypatch.setattr(wh, 'dialog_manager', dm)
    monkeypatch.setattr(bot, 'client_service', SimpleNamespace(
        get_or_create_client=AsyncMock(return_value=client), update_client=AsyncMock()))
    monkeypatch.setattr(bot, 'message_service', SimpleNamespace(
        get_conversation_history=AsyncMock(return_value=[]), save_message=AsyncMock(),
        load_context=AsyncMock(return_value=None), save_context=AsyncMock()))
    monkeypatch.setattr(bot, 'notification_service', None)
    monkeypatch.setattr(bot, 'follow_up_service', None)
    monkeypatch.setattr(bot, 'yclients_service', None)
    monkeypatch.setattr(wh.config, 'MOCK_YCLIENTS', True)
    monkeypatch.setattr(wh.config, 'WAPPI_SEND_PROMO_PHOTOS', False)
    monkeypatch.setattr(wh, 'wappi_client', None)
    monkeypatch.setattr(wh, '_night_event', Mock())
    monkeypatch.setattr(wh, '_alert_admins_about_lead', AsyncMock())
    monkeypatch.setattr(wh, '_send_to_client', AsyncMock(return_value=True))
    monkeypatch.setattr(wh, 'booking_agent', SimpleNamespace(process_message_with_tools=AsyncMock()))
    import services.turn_logger as tl
    monkeypatch.setattr(tl, 'log_turn', Mock())
    class Replay:
        ctx = dm.get_or_create_context('ig_555')
        async def turn(self, text, draft):
            wh.booking_agent.process_message_with_tools.return_value = (draft, AgentActions())
            wh._send_to_client.reset_mock()
            await wh._process_wappi_message('ig:555', text, 'Test')
            return '\n'.join(c.args[1] for c in wh._send_to_client.await_args_list)
    return Replay()

@pytest.mark.asyncio
async def test_instagram_reply_does_not_require_whatsapp_credentials(dialogue):
    out = await dialogue.turn('Hi', 'Hello dear! Which service would you like?')
    assert out, 'Instagram must deliver through ManyChat even without Wappi'

@pytest.mark.asyncio
async def test_latest_no_stops_sales_and_preserves_phone(dialogue):
    dialogue.ctx.client_data.update(phone='971500000000', area='abu_dhabi')
    dialogue.ctx.booking_data.update(service_type='face_massage', service_named=True,
                                     date='2026-09-12', time='14:00')
    out = await dialogue.turn('Yes\nNo thank you', '50 min — 370 AED. Which time suits you?')
    assert dialogue.ctx.booking_data.get('closed_politely') is True
    assert 'which time' not in out.lower()
    assert '370' not in out
    assert dialogue.ctx.client_data['phone'] == '971500000000'

@pytest.mark.asyncio
async def test_switch_from_face_to_body_keeps_contact_and_discards_old_duration(dialogue):
    dialogue.ctx.client_data.update(phone='971500000000', area='abu_dhabi')
    dialogue.ctx.booking_data.update(service_type='face_massage', service_duration=50,
                                     service_named=True, time='17:30')
    await dialogue.turn('Body massage if I like it I will do facial too',
                        'Hello 👋\nFacial massage 370 AED. Would you like to book?')
    assert dialogue.ctx.booking_data['service_type'] == 'body_massage'
    assert dialogue.ctx.booking_data['service_duration'] != 50
    assert dialogue.ctx.client_data['phone'] == '971500000000'

@pytest.mark.asyncio
async def test_cupping_ad_does_not_override_explicit_facial_switch(dialogue):
    dialogue.ctx.client_data.update(phone='971500000000', area='abu_dhabi')
    dialogue.ctx.booking_data.update(service_type='lymphatic_cupping_combo', service_duration=45,
                                     service_named=True, ad_prefill='package')
    out = await dialogue.turn('Facial massage please', 'Facial massage is 370 AED for 50 min. Which day?')
    assert dialogue.ctx.booking_data['service_type'] == 'face_massage'
    assert '275' not in out
    assert dialogue.ctx.booking_data.get('ad_prefill') != 'package'

@pytest.mark.asyncio
@pytest.mark.parametrize('text', ["Don't book tomorrow", 'I will confirm later', 'No thanks'])
async def test_refusal_never_invokes_model_or_booking_tools(dialogue, monkeypatch, text):
    create = AsyncMock()
    monkeypatch.setattr(wh, '_maybe_create_booking', create)
    out = await dialogue.turn(text, 'Your appointment is confirmed!')
    assert out == wh.POLITE_CLOSE_LINE
    wh.booking_agent.process_message_with_tools.assert_not_awaited()
    create.assert_not_awaited()

@pytest.mark.asyncio
async def test_customer_can_return_after_refusal_without_losing_contact(dialogue):
    dialogue.ctx.client_data.update(phone='971500000000', area='abu_dhabi')
    await dialogue.turn('No thank you', 'Which time?')
    await dialogue.turn('Facial massage tomorrow please', 'Which time suits you?')
    assert not dialogue.ctx.booking_data.get('closed_politely')
    assert dialogue.ctx.client_data['phone'] == '971500000000'
    assert dialogue.ctx.booking_data['service_type'] == 'face_massage'
    assert wh.booking_agent.process_message_with_tools.await_count == 1

@pytest.mark.asyncio
async def test_restart_restores_refusal_service_and_contact(dialogue, tmp_path, monkeypatch):
    from database.db import Database
    from database.models import Base
    from database.services import MessageService
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'context.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    storage = MessageService(db)
    monkeypatch.setattr(bot.message_service, 'load_context', storage.load_context)
    monkeypatch.setattr(bot.message_service, 'save_context', storage.save_context)
    dialogue.ctx.client_data.update(phone='971500000000', area='abu_dhabi')
    dialogue.ctx.booking_data.update(service_type='face_massage', date='2026-09-12', time='14:00')
    await dialogue.turn('No thank you', 'Which time?')
    await db.engine.dispose()
    reopened = Database(db.database_url)
    monkeypatch.setattr(bot.message_service, 'load_context', MessageService(reopened).load_context)
    monkeypatch.setattr(bot.message_service, 'save_context', MessageService(reopened).save_context)
    wh.dialog_manager.clear_context('ig_555')
    try:
        out = await dialogue.turn('Okay', 'Which time suits you?')
        restored = wh.dialog_manager.get_context('ig_555')
        assert restored.booking_data['closed_politely'] is True
        assert restored.booking_data['service_type'] == 'face_massage'
        assert restored.booking_data['date'] == '2026-09-12'
        assert restored.client_data['phone'] == '971500000000'
        assert 'which time' not in out.lower()
        await MessageService(reopened).clear_context('ig_555')
        assert await MessageService(reopened).load_context('ig_555') is None
    finally:
        await reopened.engine.dispose()

@pytest.mark.asyncio
async def test_storage_outage_does_not_restart_sales_with_empty_context(dialogue):
    bot.message_service.load_context.side_effect = RuntimeError('storage unavailable')
    out = await dialogue.turn('Yes', 'Your appointment is confirmed!')
    wh.booking_agent.process_message_with_tools.assert_not_awaited()
    assert 'technical issue' in out.lower()

@pytest.mark.asyncio
async def test_thought_messages_one_question_and_no_repeated_greeting(dialogue):
    dialogue.ctx.client_data['phone'] = '971500000000'
    dialogue.ctx.recent_messages = [{'role': 'assistant', 'content': 'Hello dear!'}]
    out = await dialogue.turn('Home service only?',
        'Hello dear 🌹\nYes, home service.---MESSAGE_SPLIT---Please send your WhatsApp number.\nWhich day?\nMorning or evening?')
    assert 1 <= wh._send_to_client.await_count <= 3
    assert 'hello' not in out.lower()
    assert 'send your whatsapp' not in out.lower()
    assert out.count('?') <= 1
    assert 'home service' in out.lower()


@pytest.mark.asyncio
async def test_calendar_outage_is_not_reported_as_fully_booked(dialogue, monkeypatch):
    monkeypatch.setattr(wh.config, 'MOCK_YCLIENTS', False)
    monkeypatch.setattr(bot, 'yclients_service', SimpleNamespace(
        get_available_slots_summary=AsyncMock(return_value=None),
        is_slot_available=AsyncMock(return_value=None)))
    dialogue.ctx.client_data.update(phone='971500000000', area='abu_dhabi')
    dialogue.ctx.booking_data.update(service_type='face_massage', service_named=True, service_duration=50)
    out = await dialogue.turn('How much?', 'Facial massage is 370 AED. Today and tomorrow are fully booked. Which day?')
    assert 'fully booked' not in out.lower()
    assert '370' in out
    assert "can't verify" in out


@pytest.mark.asyncio
async def test_fresh_facial_request_loads_calendar_without_body_duration_gate(dialogue, monkeypatch):
    summary = AsyncMock(return_value=None)
    monkeypatch.setattr(wh.config, 'MOCK_YCLIENTS', False)
    monkeypatch.setattr(bot, 'yclients_service', SimpleNamespace(
        get_available_slots_summary=summary, is_slot_available=AsyncMock(return_value=None)))
    await dialogue.turn('Facial massage in Abu Dhabi please', 'Facial massage is 370 AED for 50 minutes.')
    assert dialogue.ctx.booking_data['service_duration'] == 50
    summary.assert_awaited()
