import pytest
import webhook_app as wh
from services.customer_intent import direct_question_topics, whatsapp_contact_answer

@pytest.mark.parametrize('text,expected', [
    ('2:pm','14:00'), ('2: pm','14:00'), ('12:am','00:00'), ('12: PM','12:00'),
    ('2pm','14:00'), ('2:00 pm','14:00'), ('14:00','14:00'), ('13:pm',None),
    ('0:pm',None), ('25:00',None), ('2:99 pm',None), ('60min',None), ('0500000000',None),
])
def test_phone_style_time(text,expected):
    assert wh._detect_requested_time(text)==expected

@pytest.mark.parametrize('text', ['Can you send me a message on WhatsApp?', 'Your WhatsApp number?', 'Message me on WhatsApp'])
def test_whatsapp_intent(text):
    assert 'whatsapp' in direct_question_topics(text)

def test_whatsapp_answer_uses_only_business_number():
    answer=whatsapp_contact_answer('971551933662','+971500000000')
    assert 'https://wa.me/971551933662' in answer
    assert 'wa.me/971500000000' not in answer
    assert "can't start" in answer
    assert 'ending in 0000' in answer
    assert 'http' not in whatsapp_contact_answer('', '+971500000000')
    assert 'already chatting' in whatsapp_contact_answer('971551933662',on_instagram=False)
