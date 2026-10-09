"""Small deterministic rules for explicit corrections and direct questions.

Keep the original message in history. This normalized view is only for extracting
choices; rejected choices must never become the selected service or location.
"""
import re


def affirmative_choice_text(text: str) -> str:
    text = text or ''
    # Discard the rejected alternative, preserving a later independent clause.
    boundary = r'(?=[,;.!?\n]|\b(?:but|actually|i am|i.m|i want|хочу|я в|а\s)\b|$)'
    text = re.sub(r'\b(?:instead of|rather than|вместо)\b.*?' + boundary,
                  ' ', text, flags=re.I)
    text = re.sub(r'\b(?:not|не|no longer)\b(?!\s+only\b).*?' + boundary,
                  ' ', text, flags=re.I)
    return text


LOCATION_QUESTION_RE = re.compile(
    r'^\s*(?:your\s+)?locations?[?.! ]*$|where\s+(?:are|r)\s+(?:you|u)\b'
    r'|where\s+is\s+your\s+(?:location|place|studio|salon|office)'
    r'|what(?:.s|\s+is)\s+(?:the|your)\s+location'
    r'|\bbranch\b|\bhome service\b.*\?|\b(?:do|can|will)\s+you\s+come\b'
    r'|\b(?:is|free|how much|cost).*\btransport(?:ation)?\b'
    r'|где\s+вы\s+наход|ваш\s+адрес|выезд.*\?|وين\s*مكانكم', re.I)
PAYMENT_QUESTION_RE = re.compile(
    r'\b(?:pay|payment|cash|bank transfer|vat|terminal)\b|оплат|налич|перевод', re.I)
PRICE_QUESTION_RE = re.compile(
    r'how much|how long|\bprice|\bcost|\bduration|сколько|цен[аыу]', re.I)
QUESTION_RE = re.compile(r'\?|^\s*(?:what|which|where|when|how|can|do|is|are|когда|где|как|сколько)\b', re.I)


def direct_question_topics(text: str) -> set[str]:
    topics = set()
    if LOCATION_QUESTION_RE.search(text or ''):
        topics.add('location')
    if QUESTION_RE.search(text or '') and PAYMENT_QUESTION_RE.search(text or ''):
        topics.add('payment')
    if PRICE_QUESTION_RE.search(text or '') and not re.search(r'transport', text, re.I):
        topics.add('price')
    return topics


def factual_answer(topics: set[str], text: str) -> str:
    """Catalogue-independent facts; never promises availability or a booking."""
    lines = []
    if 'location' in topics:
        lines.append('We offer home service in Abu Dhabi, Al Ain and Dubai. '
                     'We come to your home, villa or hotel — free transportation.')
    if 'payment' in topics:
        lines.append('Payment is after the service. Cash is tax free; bank transfer includes 5% VAT.')
        if re.search(r'\b(?:card|terminal)\b|терминал|карт', text, re.I):
            lines.append('A card terminal is available on request; please let us know if you need one.')
    return '\n\n'.join(lines)
