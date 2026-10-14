"""Customer screenshot: after tomorrow + bare 9pm must retain the chosen day."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
import webhook_app as wh
from services.customer_intent import direct_question_topics, factual_answer

NOW = datetime(2026, 10, 14, 23, 59, tzinfo=timezone(timedelta(hours=4)))

@pytest.mark.parametrize('text,day', [
    ('After tomorrow', '2026-10-16'),
    ('the day after tomorrow around 9 pm', '2026-10-16'),
    ('послезавтра в 21:00', '2026-10-16'),
    ('tomorrow', '2026-10-15'), ('today', '2026-10-14'),
    ('not tomorrow, after tomorrow', '2026-10-16'),
    ('tomorrow or after tomorrow', None),
    ('today or tomorrow', None),
    ('I txt you tomorrow good night', None),
    ("Good night tomorrow i txt you", None),
    ("I'll text you tomorrow", None),
    ('Напишу вам завтра', None),
    ('Book after tomorrow. I will text you tomorrow', '2026-10-16'),
])
def test_relative_booking_date(text, day):
    assert wh._resolve_named_date(text, NOW)[0] == day

@pytest.mark.parametrize('text', ['Can I see your picture or your massage', 'Send photos please', 'Фото массажа'])
def test_media_is_answered_with_approved_account(text):
    topics = direct_question_topics(text)
    assert 'media' in topics
    answer = factual_answer(topics, text, ig_handle='crystal_lab_ae')
    assert '@crystal_lab_ae' in answer
    assert 'send you' not in answer


def test_after_tomorrow_booking_tool_day_guard():
    now = datetime.now(timezone(timedelta(hours=4)))
    wrong = SimpleNamespace(date=(now + timedelta(days=1)).strftime('%Y-%m-%d'))
    right = SimpleNamespace(date=(now + timedelta(days=2)).strftime('%Y-%m-%d'))
    assert wh._booking_day_mismatch('After tomorrow', wrong) == ('the day after tomorrow', right.date)
    assert wh._booking_day_mismatch('After tomorrow', right) is None

@pytest.mark.asyncio
@pytest.mark.parametrize('chosen_free', [True, False])
async def test_nearest_day_offer_never_replaces_explicit_choice(monkeypatch, chosen_free):
    from unittest.mock import AsyncMock
    import bot
    now = datetime.now(timezone(timedelta(hours=4)))
    chosen = (now + timedelta(days=2)).strftime('%Y-%m-%d')
    alternative = (now + timedelta(days=3)).strftime('%Y-%m-%d')
    async def summary(**kwargs):
        if kwargs['date'] == chosen and not chosen_free:
            return 'No slots available'
        return '2:00 PM, 9:00 PM'
    service = SimpleNamespace(get_available_slots_summary=AsyncMock(side_effect=summary))
    monkeypatch.setattr(bot, 'yclients_service', service)
    ctx = SimpleNamespace(booking_data={'date': chosen, 'service_type': 'body_massage', 'service_duration': 60})
    out = await wh._offer_nearest_day_when_empty('No free slots. Which day suits you?', ctx, 'abu_dhabi')
    assert ctx.booking_data['date'] == chosen
    dates = [c.kwargs['date'] for c in service.get_available_slots_summary.await_args_list]
    assert min(dates) == chosen
    assert 'today' not in out.lower()
    if chosen_free:
        assert 'no free slots' not in out.lower()
        assert wh._nice_day(chosen) in out
    else:
        assert datetime.strptime(alternative, '%Y-%m-%d').strftime('%A %-d %b') in out
