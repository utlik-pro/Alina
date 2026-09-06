"""Final presentation pass: one message and one unresolved question per turn."""
import re

STYLE_INSTRUCTION = '''Reply as a helpful booking receptionist in one coherent message.
Answer the customer's latest question first. Then ask at most ONE question needed
for the next step. Do not ask again for known phone, area, service or date.
Greet only on the first turn. Use short natural sentences and at most one emoji.
Do not send a menu or full promotional card unless the customer asks for options.
Do not repeat prices just because the customer shared a phone or said hello.
These presentation rules supersede earlier examples that split messages or repeat
sales cards. Keep all factual booking, availability and payment safeguards.
'''


def compose_reply(text, context):
    history = getattr(context, 'recent_messages', []) or []
    returning = any(m.get('role') == 'assistant' for m in history)
    known = context.client_data or {}
    booking = context.booking_data or {}
    text = (text or '').replace('---MESSAGE_SPLIT---', '\n\n')
    truth = getattr(context, 'slot_truth', {}) or {}
    unavailable = bool(truth) and all(v is None for v in truth.values())
    removed_availability = False
    parts = []
    seen = set()
    asked = False
    for line in text.splitlines():
        line = line.strip()
        if returning:
            line = re.sub(r'^(?:hello|hi|good morning|good evening)\b[\s,!👋🌹]*(?:dear\b[\s,!👋🌹]*)?', '', line, flags=re.I).strip()
        # Split independent questions on the same line, retaining factual lead-in.
        for sentence in re.split(r'(?<=[?!])\s+|(?<=\.)\s+(?=[A-Z])', line):
            if not sentence:
                continue
            if unavailable and re.search(
                r'fully booked|no (?:free )?slots|(?:don.t|do not|we have no).*slots|'
                r'slots.*available|(?:free|available) (?:slots|times)|\b\d{1,2}(?::\d{2})?\s*[ap]m\b',
                sentence, re.I):
                removed_availability = True
                continue
            is_request = bool('?' in sentence or re.search(
                r'^(?:please |may i |could you )?(?:send|share|give|provide|tell me)\b', sentence, re.I))
            if is_request:
                if known.get('phone') and re.search(r'(?:phone|whatsapp|your)\s*(?:number)|number.*dear', sentence, re.I):
                    continue
                if known.get('area') and re.search(r'which (?:area|city|emirate)', sentence, re.I):
                    continue
                if booking.get('date') and re.search(r'which day|today or tomorrow', sentence, re.I):
                    continue
                if asked:
                    continue
                asked = True
            key = re.sub(r'\W+', '', sentence).lower()
            if key and key not in seen:
                seen.add(key)
                parts.append(sentence)
    if removed_availability:
        parts.append("I can't verify the calendar right now; availability is not confirmed yet.")
    return '\n\n'.join(parts).strip() or 'Thank you 🌹'
