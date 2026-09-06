"""Final presentation pass: short thought-sized messages and one next question per turn."""
import re

STYLE_INSTRUCTION = 'Write like the human Crystal Lab administrator in a natural chat.\nAnswer the latest question first, then move the booking forward with at most ONE\nnext question. Use 1–3 short messages: one complete thought per message, separated\nby ---MESSAGE_SPLIT---. Keep a price and its duration together. Do not split a\nsingle sentence or send isolated greetings, acknowledgements or emojis.\nDo not ask again for a known phone, area, service or date. Greet only at first contact.\nNo unsolicited catalogue or repeated price after a phone/hello. Use at most one\nemoji per turn. These presentation rules supersede older sales-card examples.\nKeep factual booking, calendar, confirmation and payment safeguards unchanged.\n'


def compose_reply(text, context):
    history = getattr(context, 'recent_messages', []) or []
    returning = any(m.get('role') == 'assistant' for m in history)
    latest_user = next((m.get('content', '') for m in reversed(history) if m.get('role') == 'user'), '')
    earlier = '\n'.join(m.get('content', '') for m in history if m.get('role') == 'assistant')
    side_question = '?' in latest_user and bool(re.search(
        r'home service|come to my home|branch|male or female|female or male', latest_user, re.I))
    price_requested = bool(re.search(r'how much|how long|price|cost|duration|aed|minutes', latest_user, re.I))
    routine = bool(re.fullmatch(r'[+\d ()-]{7,}', latest_user.strip()) or
                   re.search(r'\b(?:today|tomorrow|at)\s+(?:at\s+)?\d', latest_user, re.I))
    old_prices = set(re.findall(r'\d+(?:\.\d+)?\s*AED', earlier, re.I))
    known = context.client_data or {}
    booking = context.booking_data or {}
    awaiting_phone = (str(getattr(context, 'user_id', '')).startswith('ig_') and not known.get('phone')
                      and not re.search(r'what time|available|slot|when|\b\d{1,2}(?::\d{2})?\s*[ap]m\b', latest_user, re.I))
    text = (text or '').replace('---MESSAGE_SPLIT---', '\n\n')
    truth = getattr(context, 'slot_truth', {}) or {}
    unavailable = context.state != 'completed' and (not truth or all(v is None for v in truth.values()))
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
            if awaiting_phone and re.search(
                    r'fully booked|slots|nearest we have|\b\d{1,2}(?::\d{2})?\s*[ap]m\b', sentence, re.I):
                continue
            if unavailable and re.search(
                r'we can (?:do|book|arrange).*(?:today|tomorrow)|fully booked|no (?:free )?slots|(?:don.t|do not|we have no).*slots|'
                r'slots.*available|(?:free|available) (?:slots|times)|\b\d{1,2}(?::\d{2})?\s*[ap]m\b',
                sentence, re.I):
                removed_availability = True
                continue
            quoted = set(re.findall(r'\d+(?:\.\d+)?\s*AED', sentence, re.I))
            if routine and not price_requested and quoted and quoted <= old_prices and context.state != 'completed':
                continue
            if side_question and re.search(r'\b(?:slots|available|which .*suits|what day|which day|which time)\b', sentence, re.I):
                continue
            is_request = bool('?' in sentence or re.search(
                r'^(?:please |may i |could you )?(?:send|share|give|provide|tell me)\b', sentence, re.I))
            if is_request:
                if side_question:
                    continue
                if known.get('phone') and re.search(r'(?:phone|whatsapp|your)\s*(?:number)|number.*dear', sentence, re.I):
                    continue
                if known.get('area') and re.search(r'which (?:area|city|emirate)', sentence, re.I):
                    continue
                if booking.get('date') and re.search(r'which day|today or tomorrow', sentence, re.I):
                    continue
                if ('?' in latest_user and re.search(r'whatsapp|phone|your number', sentence, re.I)
                        and re.search(r'(?:send|share|have).*?(?:whatsapp|phone|number)', earlier, re.I)):
                    continue
                normalize = lambda value: re.sub(r'\W+|\bdear\b', '', value.lower())
                if '?' in latest_user and normalize(sentence) in normalize(earlier):
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


def split_chat_messages(text):
    """Send thought blocks, keeping at most three bubbles without truncating facts."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    grouped = []
    for block in blocks:
        if (grouped and re.fullmatch(r'\d+\s*(?:min|minutes)[.!]?', block, re.I)
                and re.search(r'\bAED\b', grouped[-1], re.I)):
            grouped[-1] += ' — ' + block
        else:
            grouped.append(block)
    blocks = grouped
    grouped = []
    for block in blocks:
        if (grouped and re.match(r'^[💵🏦\s]*(?:Cash|Bank transfer)\b', block, re.I)
                and re.search(r'pay|cash|bank transfer', grouped[-1], re.I)):
            grouped[-1] += '\n' + block
        else:
            grouped.append(block)
    blocks = grouped
    grouped = []
    for block in blocks:
        if grouped and re.match(r'^Area,? building', block, re.I) and 'address' in grouped[-1].lower():
            grouped[-1] += ': ' + block[0].lower() + block[1:]
        else:
            grouped.append(block)
    blocks = grouped
    if len(blocks) > 1 and re.fullmatch(
            r'(?:hi|hello|ok|okay|thank you|thanks|got it)(?: dear)?[\s.!👋🌹🙏]*', blocks[0], re.I):
        blocks[1] = blocks[0] + ' ' + blocks[1]
        blocks.pop(0)
    if len(blocks) <= 3:
        return blocks
    # Keep the answer first and the next question last; group supporting facts.
    return [blocks[0], "\n".join(blocks[1:-1]), blocks[-1]]
