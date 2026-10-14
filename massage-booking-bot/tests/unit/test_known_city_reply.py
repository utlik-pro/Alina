import pytest
from dialog_context import DialogContext
from services.reply_composer import compose_reply
from agents.booking_agent import BookingAgent


@pytest.mark.parametrize('question', [
    'Are you in Abu Dhabi, Al Ain or Dubai dear?', 'Which city are you in?',
    'Where are you from dear?', 'Where are you located?',
    'Could you confirm your city please?', 'Which area dear?',
    'Are you in Abu Dhabi, Al Ain or Dubai dear',
])
def test_known_city_cannot_be_asked_again(question):
    ctx = DialogContext('ig_123')
    ctx.client_data.update(area='abu_dhabi', phone='971500000000')
    ctx.recent_messages = [{'role': 'user', 'content': 'Tomorrow'}]
    assert question not in compose_reply(question, ctx)
    ctx.client_data['area'] = None
    assert question in compose_reply(question, ctx)


def test_city_does_not_replace_full_address():
    ctx = DialogContext('ig_123')
    ctx.client_data.update(area='abu_dhabi', phone='971500000000')
    text = 'Please share your address in Abu Dhabi — building or villa number?'
    assert text in compose_reply(text, ctx)
    prompt = BookingAgent._format_booking_context(None, ctx.to_dict())
    assert 'CITY ALREADY KNOWN: Abu Dhabi' in prompt
    assert 'PHONE ALREADY KNOWN' in prompt
    assert 'building/villa' in prompt


def test_address_question_with_where_is_kept():
    ctx = DialogContext('ig_123')
    ctx.client_data.update(area='abu_dhabi', phone='971500000000')
    question = 'Where are you located in Khalifa City — which building or villa?'
    assert question in compose_reply(question, ctx)
