from dialog_context import DialogContext
from services.reply_composer import compose_reply, split_chat_messages


def test_phone_reply_moves_forward_without_repeating_price():
    ctx = DialogContext('test')
    ctx.client_data['phone'] = '971500000000'
    ctx.recent_messages = [
        {'role':'assistant','content':'Facial massage is 50 min — 370 AED. Please send your WhatsApp number'},
        {'role':'user','content':'0500000000'}]
    result = split_chat_messages(compose_reply(
        'Ok dear 🌹\nFacial massage is 50 min — 370 AED\nWhich day would suit you?', ctx))
    assert result == ['Ok dear 🌹 Which day would suit you?']


def test_distinct_thoughts_remain_distinct_messages():
    ctx = DialogContext('test')
    result = split_chat_messages(compose_reply(
        'Yes, we come to your home 🌹---MESSAGE_SPLIT---Transportation is included.---MESSAGE_SPLIT---Which day would suit you?', ctx))
    assert result == ['Yes, we come to your home 🌹', 'Transportation is included.', 'Which day would suit you?']


def test_price_and_duration_are_one_thought():
    assert split_chat_messages('370 AED\n\n50 minutes\n\nWhich day?') == ['370 AED — 50 minutes', 'Which day?']


def test_payment_options_stay_with_the_question():
    assert split_chat_messages('How would you like to pay?\n\n💵 Cash (tax free)\n\n🏦 Bank transfer (+5% VAT)') == [
        'How would you like to pay?\n💵 Cash (tax free)\n🏦 Bank transfer (+5% VAT)']


def test_home_service_question_does_not_trigger_slot_sales():
    ctx = DialogContext('test')
    ctx.recent_messages = [{'role': 'user', 'content': 'Do you come to my home?'}]
    ctx.slot_truth = {'2026-09-07': {'14:00'}}
    answer = compose_reply('Yes, home service.\nTomorrow we have slots available.\nWhich time suits you?', ctx)
    assert answer == 'Yes, home service.'


def test_price_question_does_not_dump_calendar_before_asking_phone():
    ctx = DialogContext('ig_test')
    ctx.recent_messages = [{'role':'user','content':'How much is facial massage?'}]
    ctx.slot_truth = {'2026-09-07': {'14:00'}}
    answer = compose_reply('370 AED — 50 min.\nMay I have your WhatsApp number?\nToday no slots available.\nThe nearest we have is tomorrow: 2:00 PM.', ctx)
    assert '370 AED' in answer and 'WhatsApp' in answer
    assert 'slots' not in answer and '2:00 PM' not in answer


def test_bare_location_does_not_leave_a_dangling_booking_question():
    ctx = DialogContext('ig_test')
    ctx.recent_messages = [{'role':'user','content':'Location'}]
    answer = compose_reply('We come to your home in Dubai, transportation is free 🌹\nWhich suits you?', ctx)
    assert answer == 'We come to your home in Dubai, transportation is free 🌹'
