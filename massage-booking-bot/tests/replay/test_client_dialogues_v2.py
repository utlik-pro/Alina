"""Replay client turns through the final channel pipeline, with no external I/O."""
import re
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
    # The invariant is that an outage produces NO availability claim — either
    # the agent says it cannot verify, or it does not discuss times at all.
    # A price question is answered with the admin card (Tatyana 31.08), which
    # takes the second route: it quotes 370 and asks morning-or-evening, so
    # nothing about the calendar is asserted while YClients is down.
    assert "can't verify" in out or not re.search(
        r'\b\d{1,2}(?::\d{2})?\s*[ap]m\b', out, re.I)


@pytest.mark.asyncio
async def test_fresh_facial_request_loads_calendar_without_body_duration_gate(dialogue, monkeypatch):
    summary = AsyncMock(return_value=None)
    monkeypatch.setattr(wh.config, 'MOCK_YCLIENTS', False)
    monkeypatch.setattr(bot, 'yclients_service', SimpleNamespace(
        get_available_slots_summary=summary, is_slot_available=AsyncMock(return_value=None)))
    await dialogue.turn('Facial massage in Abu Dhabi please', 'Facial massage is 370 AED for 50 minutes.')
    assert dialogue.ctx.booking_data['service_duration'] == 50
    summary.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('question', [
    'U have branch in sharjaha',
    'Do you do facial massage in Sharjah?',
    'Home service in Sharja?',
    'Вы работаете в Шардже?',
])
async def test_sharjah_question_gets_explicit_refusal_before_sales(dialogue, monkeypatch, question):
    """Tatyana 2026-10-08: a city list hidden in the card is not an answer."""
    calendar = SimpleNamespace(get_available_slots_summary=AsyncMock(return_value=None))
    monkeypatch.setattr(bot, 'yclients_service', calendar)
    monkeypatch.setattr(wh.config, 'MOCK_YCLIENTS', False)
    create = AsyncMock()
    monkeypatch.setattr(wh, '_maybe_create_booking', create)
    dialogue.ctx.booking_data.update(service_type='face_massage', service_named=True,
                                     ad_prefill='summer')
    out = await dialogue.turn(question,
        'Hello 👋 ✅WE have an offer for facial massage !!! 370 AED. Free transportation')
    assert "don't currently operate in Sharjah" in out
    assert 'home service in Abu Dhabi, Al Ain and Dubai' in out
    assert '370' not in out and 'offer for' not in out and '?' not in out
    wh.booking_agent.process_message_with_tools.assert_not_awaited()
    calendar.get_available_slots_summary.assert_not_awaited()
    create.assert_not_awaited()
    assert dialogue.ctx.booking_data['out_of_area']
    assert not dialogue.ctx.booking_data.get('face_card_sent')
    saved = bot.message_service.save_context.await_args.args[1]
    assert saved['booking_data']['out_of_area']


@pytest.mark.asyncio
async def test_sharjah_close_survives_restart_and_dubai_reopens(dialogue, monkeypatch):
    await dialogue.turn('U have branch in sharjaha', 'Facial massage 370 AED')
    snapshot = bot.message_service.save_context.await_args.args[1]
    bot.message_service.load_context.return_value = snapshot
    wh.dialog_manager.clear_context('ig_555')
    wh.booking_agent.process_message_with_tools.reset_mock()
    for message in ('Okay', 'Thanks'):
        out = await dialogue.turn(message, 'Which service do you want? 370 AED')
        assert 'Abu Dhabi, Al Ain or Dubai' in out
        assert '?' not in out and '370' not in out
    wh.booking_agent.process_message_with_tools.assert_not_awaited()
    restored = wh.dialog_manager.get_context('ig_555')
    assert restored.booking_data['out_of_area']
    # A client can voluntarily return with a supported service location.
    out = await dialogue.turn('I can have the facial at my hotel in Dubai',
                              'We can come to your hotel in Dubai.')
    assert not restored.booking_data.get('out_of_area')
    assert wh.booking_agent.process_message_with_tools.await_count == 1
    assert "don't currently operate in Sharjah" not in out


@pytest.mark.asyncio
@pytest.mark.parametrize('correction,expected', [
    ("Not Sharjah, I'm in Dubai", 'dubai'),
    ("Dubai, not Sharjah", 'dubai'),
    ("Не в Шардже, я в Дубае", 'dubai'),
    ("Sharjah was wrong, actually Abu Dhabi", 'abu_dhabi'),
    ("I live in Sharjah but want the massage in Dubai", 'dubai'),
])
async def test_city_correction_reopens_without_losing_booking(dialogue, correction, expected):
    dialogue.ctx.client_data['phone'] = '971500000000'
    dialogue.ctx.booking_data.update(service_type='face_massage', service_duration=50,
                                     date='2026-11-12', time='17:30')
    await dialogue.turn('Sharjah', 'Facial massage 370 AED')
    out = await dialogue.turn(correction, 'We can come to your home. Which day?')
    assert not dialogue.ctx.booking_data.get('out_of_area')
    assert dialogue.ctx.client_data['area'] == expected
    assert dialogue.ctx.client_data['phone'] == '971500000000'
    assert dialogue.ctx.booking_data['date'] == '2026-11-12'
    assert dialogue.ctx.booking_data['time'] == '17:30'
    assert "don't currently operate" not in out
    assert wh.booking_agent.process_message_with_tools.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('message', ['Dubai or Sharjah?', 'Dubai or Abu Dhabi?', 'Not Dubai'])
async def test_unclear_city_asks_before_using_cached_city(dialogue, monkeypatch, message):
    create = AsyncMock()
    monkeypatch.setattr(wh, '_maybe_create_booking', create)
    out = await dialogue.turn(message, 'Your booking in Abu Dhabi is confirmed!')
    assert 'which city' in out.lower()
    assert out.count('?') == 1
    assert not dialogue.ctx.client_data.get('area')
    wh.booking_agent.process_message_with_tools.assert_not_awaited()
    create.assert_not_awaited()
    await dialogue.turn('Dubai', 'We come to your home in Dubai.')
    assert dialogue.ctx.client_data['area'] == 'dubai'
    assert wh.booking_agent.process_message_with_tools.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('correction,kind', [
    ('Not facial, body massage please', 'body_massage'),
    ('Not body, facial massage please', 'face_massage'),
    ('Body massage instead of facial', 'body_massage'),
    ('Не массаж лица, хочу массаж тела', 'body_massage'),
])
async def test_rejected_service_does_not_win_over_correction(dialogue, correction, kind):
    dialogue.ctx.client_data['phone'] = '971500000000'
    dialogue.ctx.booking_data.update(service_type='face_massage', service_duration=50,
                                     time='17:30', service_named=True)
    await dialogue.turn(correction, 'Which time suits you?')
    assert dialogue.ctx.booking_data['service_type'] == kind
    assert dialogue.ctx.client_data['phone'] == '971500000000'
    assert dialogue.ctx.booking_data['time'] == '17:30'
    if kind == 'body_massage':
        assert dialogue.ctx.booking_data.get('service_duration') != 50


@pytest.mark.asyncio
@pytest.mark.parametrize('question,answer', [
    ('Location', 'home service'),
    ('Do you have a branch in Dubai?', 'home service'),
    ('Do you come to my hotel?', 'home service'),
    ('Is transportation free?', 'free transportation'),
    ('Do I pay before or after the massage?', 'after'),
    ('Can I pay by bank transfer?', '5% VAT'),
])
async def test_direct_question_survives_ad_and_service_card(dialogue, question, answer):
    dialogue.ctx.booking_data.update(service_type='face_massage', service_named=True,
                                     ad_prefill='summer')
    out = await dialogue.turn(question, 'Hello dear! Facial massage is 370 AED. Which time suits you?')
    assert answer.lower() in out.lower()
    assert '370' not in out and '420' not in out and '1650' not in out
    assert out.count('?') <= 1
    assert not dialogue.ctx.booking_data.get('face_card_sent')
    # The deferred card is still available when the client actually asks for a price.
    out = await dialogue.turn('How much is facial massage?', 'Facial massage is 370 AED.')
    assert '370' in out and '1650' in out
    assert dialogue.ctx.booking_data.get('face_card_sent')


@pytest.mark.asyncio
async def test_location_clarification_survives_restart(dialogue):
    dialogue.ctx.client_data.update(phone='971500000000', location_details='Old villa in Abu Dhabi')
    dialogue.ctx.booking_data['pending_booking'] = {'service': 'face_massage', 'time': '17:30'}
    await dialogue.turn('Not Abu Dhabi', 'Confirmed!')
    snapshot = bot.message_service.save_context.await_args.args[1]
    bot.message_service.load_context.return_value = snapshot
    wh.dialog_manager.clear_context('ig_555')
    out = await dialogue.turn('Okay', 'Facial massage 370 AED')
    assert 'which city' in out.lower()
    wh.booking_agent.process_message_with_tools.assert_not_awaited()
    ctx = wh.dialog_manager.get_context('ig_555')
    assert ctx.client_data['phone'] == '971500000000'
    assert not ctx.client_data.get('location_details')
    assert not ctx.booking_data.get('pending_booking')
    await dialogue.turn('Dubai', 'We can come to your home.')
    assert ctx.client_data['area'] == 'dubai'
    assert not ctx.booking_data.get('area_needs_clarification')


@pytest.mark.asyncio
async def test_unsupported_city_correction_does_not_choose_negated_dubai(dialogue):
    out = await dialogue.turn("I'm in Sharjah, not Dubai", 'Facial massage 370 AED')
    assert "don't currently operate in Sharjah" in out
    wh.booking_agent.process_message_with_tools.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('question,needed', [
    ('Which therapist will come?', 'therapist is assigned'),
    ('What types of facial massage do you offer?', 'buccal'),
    ('Where are you and how much is facial massage?', 'home service'),
])
async def test_mixed_and_other_direct_questions_keep_answer_first(dialogue, question, needed):
    dialogue.ctx.booking_data.update(service_type='face_massage', service_named=True, ad_prefill='summer')
    out = await dialogue.turn(question, 'Facial massage is 370 AED for 50 min. Which day?')
    assert needed in out.lower()
    assert '420' not in out and '1650' not in out
    if 'how much' in question:
        assert '370' in out
        assert out.lower().index('home service') < out.index('370')
    assert not dialogue.ctx.booking_data.get('face_card_sent')
    assert 'THIS CLIENT CAME FROM THE SUMMER' not in dialogue.ctx.extra_system_info


@pytest.mark.asyncio
async def test_payment_question_does_not_select_payment_method(dialogue):
    dialogue.ctx.booking_data['payment_method'] = 'cash'
    out = await dialogue.turn('Can I also pay by bank transfer?', 'Facial massage 370 AED')
    assert '5% VAT' in out
    assert dialogue.ctx.booking_data['payment_method'] == 'cash'


@pytest.mark.asyncio
async def test_service_correction_invalidates_pending_confirmation(dialogue):
    dialogue.ctx.booking_data.update(service_type='face_massage', service_duration=50,
                                    pending_booking={'service': 'face_massage', 'time': '17:30'})
    await dialogue.turn('Not facial, body massage please', '60 or 90 min?')
    assert dialogue.ctx.booking_data['service_type'] == 'body_massage'
    assert not dialogue.ctx.booking_data.get('pending_booking')


@pytest.mark.asyncio
async def test_city_correction_clears_persisted_address_but_keeps_phone(dialogue, monkeypatch, tmp_path):
    from database.db import Database
    from database.services import ClientService
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'city.db'}")
    await db.create_tables()
    clients = ClientService(db)
    await clients.get_or_create_client('ig_555')
    await clients.update_client('ig_555', phone='971500000000', area='abu_dhabi',
                                location_details='Old villa', location_latitude=24.4,
                                location_longitude=54.4)
    monkeypatch.setattr(bot, 'client_service', clients)
    try:
        await dialogue.turn('Not Abu Dhabi', 'Which time?')
        client = await clients.get_or_create_client('ig_555')
        assert client.area is None
        assert client.location_details is None
        assert client.location_latitude is None and client.location_longitude is None
        assert client.phone == '971500000000'
        await dialogue.turn('Dubai', 'We come to your home.')
        client = await clients.get_or_create_client('ig_555')
        assert client.area == 'dubai'
    finally:
        await db.close()
