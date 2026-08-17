"""The agent must never answer in a script the admins can't read.

Client rule 2026-08-16 (after the agent answered an Arabic ad-reply with a
whole Arabic paragraph): Arabic and unknown languages get an English answer
plus "In English please 🙏". Russian stays the one allowed switch — the
admins speak it.
"""

from webhook_app import (
    ENGLISH_PLEASE_MSG,
    _enforce_english_reply,
    _is_non_english_script,
)


def test_arabic_is_detected():
    assert _is_non_english_script("شو التكنيك هذا")
    assert _is_non_english_script("مرحبا، ممكن احجز جلسة")


def test_russian_is_exempt():
    assert not _is_non_english_script("Привет, хочу массаж завтра")
    assert not _is_non_english_script("напишите пожалуйста на русском")


def test_english_and_mixed_service_words_pass():
    assert not _is_non_english_script("Hello, I want a massage")
    assert not _is_non_english_script("60 min - 350 AED 🌹")
    # A lone Arabic word inside an English sentence still trips the guard on
    # inbound (fine — the injection just reminds the model to answer English).
    assert _is_non_english_script("hello مساج please")


def test_arabic_reply_is_replaced():
    arabic_reply = "التكنيك يعني نوع المساج 🌹 عندنا مساج جسم 60 دقيقة 350 درهم"
    out = _enforce_english_reply(arabic_reply, "شو التكنيك هذا")
    assert out == ENGLISH_PLEASE_MSG


def test_english_reply_untouched():
    text = "This is Buccal massage dear 🌹 In English please 🙏"
    assert _enforce_english_reply(text, "شو التكنيك هذا") == text


def test_russian_reply_untouched():
    text = "Конечно, дорогая 🌹 Какая услуга вас интересует?"
    assert _enforce_english_reply(text, "напишите на русском") == text


def test_out_of_area_cities_are_detected():
    # Client rule 2026-08-16: after "we don't work in Sharjah", an "Okay" must
    # get a warm goodbye — not "what service are you interested in?".
    from webhook_app import _detect_out_of_area

    for phrase in ("Availble in sharjah", "I'm in Ajman", "ras al khaimah?",
                   "Fujairah please", "умм аль-кувейн... шарджа"):
        assert _detect_out_of_area(phrase), phrase
    for phrase in ("Abu Dhabi", "al ain tomorrow", "Dubai marina",
                   "Okay", "body massage"):
        assert _detect_out_of_area(phrase) is None, phrase
