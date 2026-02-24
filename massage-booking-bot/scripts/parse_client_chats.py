"""
Parse exported WhatsApp client chats into structured format.
Extracts: messages, patterns, FAQ, booking scenarios, objections.

Usage:
    python3 scripts/parse_client_chats.py /path/to/chat/exports/

Output: scripts/output/chat_analysis.json
"""

import json
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# WhatsApp message format: "[13/8/2024, 8:39:25 PM] Sender: Message"
# Note: \u202f (narrow no-break space) before AM/PM, optional seconds
MSG_PATTERN = re.compile(
    r"\[(\d{1,2}/\d{1,2}/\d{2,4}),\s+(\d{1,2}:\d{2}(?::\d{2})?(?:\s*\u202f?\s*[AaPp][Mm])?)\]\s+([^:]+):\s+(.*)"
)

# Crystal Lab staff indicators (admin side of the chat)
STAFF_INDICATORS = [
    "crystal lab", "Crystal Lab", "crystal", "Crystal",
    "Алина", "Alina", "Admin", "Утлик",
    "+971 55 193 3662", "+971551933662",
]

# Service keywords for classification
SERVICE_KEYWORDS = {
    "body_massage": ["body massage", "body", "massage 60", "massage 90", "full body"],
    "face_massage": ["face massage", "facial massage", "face"],
    "deep_cleansing": ["deep clean", "facial clean", "deep facial", "cleansing"],
    "manicure": ["manicure", "mani", "nails", "gelish", "russian gelish"],
    "pedicure": ["pedicure", "pedi"],
    "combo_mani_pedi": ["mani pedi", "mani+pedi", "manicure pedicure", "combo"],
    "eyelash": ["eyelash", "lash", "lashes", "extension"],
    "eyebrow": ["eyebrow", "brow", "lamination"],
    "body_face_combo": ["body and face", "body+face", "body & face", "both"],
    "permanent_makeup": ["permanent", "pmu", "tattoo"],
    "waxing": ["wax", "waxing"],
    "cupping": ["cupping", "hijama"],
    "hair_makeup": ["hair", "makeup", "hairstyle"],
}

# Objection patterns
OBJECTION_PATTERNS = [
    r"(?:too\s+)?expensive",
    r"how much",
    r"price",
    r"discount",
    r"cheaper",
    r"offer",
    r"promo",
    r"package",
]

# Booking completion indicators
BOOKING_INDICATORS = [
    "booked", "confirmed", "see you", "waiting for you",
    "appointment", "schedule", "reserved",
]

# Location patterns
LOCATION_PATTERNS = [
    r"villa\s+\d+", r"apartment\s+\d+", r"flat\s+\d+",
    r"al\s+raha", r"khalifa\s+city", r"al\s+ain",
    r"abu\s+dhabi", r"mussafah", r"reem\s+island",
    r"yas\s+island", r"saadiyat",
]


def parse_chat_file(content: str, source_name: str = "") -> List[Dict]:
    """Parse a WhatsApp _chat.txt file into structured messages."""
    messages = []
    current_msg = None

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue

        match = MSG_PATTERN.match(line)
        if match:
            # Save previous message
            if current_msg:
                messages.append(current_msg)

            date_str, time_str, sender, text = match.groups()

            # Determine if sender is staff or client
            is_staff = any(ind.lower() in sender.lower() for ind in STAFF_INDICATORS)

            # Skip WhatsApp system messages
            text_clean = text.strip()
            if text_clean.startswith("\u200e"):
                text_clean = text_clean.lstrip("\u200e")
            # Skip system messages
            if any(skip in text_clean.lower() for skip in [
                "сообщения и звонки защищены",
                "messages and calls are end-to-end",
                "аудиозвонок",
                "видеозвонок",
                "пропущенный",
                "missed voice call",
                "missed video call",
                "изображение отсутствует",
                "image omitted",
                "video omitted",
                "sticker omitted",
                "audio omitted",
                "document omitted",
                "contact card omitted",
                "<media omitted>",
                "this message was deleted",
                "вы удалили это сообщение",
            ]):
                continue

            current_msg = {
                "date": date_str,
                "time": time_str,
                "sender": sender.strip(),
                "text": text_clean,
                "is_staff": is_staff,
                "source": source_name,
            }
        elif current_msg:
            # Multi-line message continuation
            current_msg["text"] += "\n" + line

    # Don't forget the last message
    if current_msg:
        messages.append(current_msg)

    return messages


def classify_dialog(messages: List[Dict]) -> Dict:
    """Classify a dialog by outcome and characteristics."""
    all_text = " ".join(m["text"].lower() for m in messages)
    client_text = " ".join(m["text"].lower() for m in messages if not m["is_staff"])
    staff_text = " ".join(m["text"].lower() for m in messages if m["is_staff"])

    # Detect services discussed
    services = []
    for service, keywords in SERVICE_KEYWORDS.items():
        if any(kw in all_text for kw in keywords):
            services.append(service)

    # Detect outcome
    outcome = "unknown"
    if any(ind in all_text for ind in BOOKING_INDICATORS):
        outcome = "booked"
    elif len(messages) <= 3:
        outcome = "abandoned_early"
    elif any(re.search(pat, client_text) for pat in OBJECTION_PATTERNS):
        if any(ind in all_text for ind in BOOKING_INDICATORS):
            outcome = "objection_resolved"
        else:
            outcome = "objection_unresolved"
    elif len(messages) > 3:
        outcome = "consultation_only"

    # Detect objections
    objections = []
    for msg in messages:
        if not msg["is_staff"]:
            text = msg["text"].lower()
            if "expensive" in text or "too much" in text:
                objections.append("price_objection")
            if "where" in text and ("located" in text or "location" in text or "area" in text):
                objections.append("location_question")
            if "when" in text or "available" in text or "free" in text:
                objections.append("availability_question")

    # Detect locations mentioned
    locations = []
    for pat in LOCATION_PATTERNS:
        found = re.findall(pat, all_text, re.IGNORECASE)
        locations.extend(found)

    # Detect payment method
    payment = None
    if "cash" in all_text:
        payment = "cash"
    elif "transfer" in all_text or "bank" in all_text:
        payment = "transfer"
    elif "terminal" in all_text or "card" in all_text:
        payment = "terminal"

    # Multi-message detection (rapid sequential messages from client)
    multi_msg_sequences = 0
    for i in range(1, len(messages)):
        if (not messages[i]["is_staff"] and not messages[i-1]["is_staff"]):
            multi_msg_sequences += 1

    return {
        "services": list(set(services)),
        "outcome": outcome,
        "objections": list(set(objections)),
        "locations": list(set(locations)),
        "payment_method": payment,
        "total_messages": len(messages),
        "client_messages": sum(1 for m in messages if not m["is_staff"]),
        "staff_messages": sum(1 for m in messages if m["is_staff"]),
        "multi_message_sequences": multi_msg_sequences,
    }


def extract_faq(all_dialogs: List[Dict]) -> List[Dict]:
    """Extract frequently asked questions from all client messages."""
    question_patterns = defaultdict(int)

    for dialog in all_dialogs:
        for msg in dialog["messages"]:
            if not msg["is_staff"] and "?" in msg["text"]:
                text = msg["text"].strip().lower()
                # Normalize
                text = re.sub(r"\s+", " ", text)
                if len(text) > 10:  # Skip very short messages
                    question_patterns[text] += 1

    # Group similar questions
    faq = []
    for q, count in sorted(question_patterns.items(), key=lambda x: -x[1]):
        if count >= 1:  # Include even single occurrences for analysis
            faq.append({"question": q, "count": count})

    return faq[:50]  # Top 50


def extract_client_phrases(all_dialogs: List[Dict]) -> Dict[str, List[str]]:
    """Extract typical client phrases grouped by intent."""
    intents = {
        "greeting": [],
        "price_inquiry": [],
        "booking_request": [],
        "time_selection": [],
        "location_share": [],
        "confirmation": [],
        "objection": [],
        "gratitude": [],
        "cancellation": [],
    }

    for dialog in all_dialogs:
        for msg in dialog["messages"]:
            if msg["is_staff"]:
                continue
            text = msg["text"].strip()
            lower = text.lower()

            if len(text) < 3:
                continue

            # Classify by intent
            if any(w in lower for w in ["hi", "hello", "hey", "good morning", "assalamu"]):
                intents["greeting"].append(text)
            elif any(w in lower for w in ["how much", "price", "cost", "rate", "aed"]):
                intents["price_inquiry"].append(text)
            elif any(w in lower for w in ["book", "appointment", "schedule", "reserve", "want to"]):
                intents["booking_request"].append(text)
            elif any(w in lower for w in ["am", "pm", "morning", "evening", "afternoon", "o'clock", "tomorrow", "today"]):
                intents["time_selection"].append(text)
            elif any(w in lower for w in ["villa", "apartment", "location", "address"]):
                intents["location_share"].append(text)
            elif any(w in lower for w in ["yes", "ok", "confirm", "sure", "perfect", "great"]):
                intents["confirmation"].append(text)
            elif any(w in lower for w in ["expensive", "cheap", "discount", "too much"]):
                intents["objection"].append(text)
            elif any(w in lower for w in ["thank", "thanks", "shukran"]):
                intents["gratitude"].append(text)
            elif any(w in lower for w in ["cancel", "reschedule", "change", "postpone"]):
                intents["cancellation"].append(text)

    # Deduplicate and limit
    for intent in intents:
        seen = set()
        unique = []
        for phrase in intents[intent]:
            normalized = phrase.lower().strip()
            if normalized not in seen:
                seen.add(normalized)
                unique.append(phrase)
        intents[intent] = unique[:30]  # Top 30 per intent

    return intents


def extract_multi_message_patterns(all_dialogs: List[Dict]) -> List[Dict]:
    """Extract patterns of multi-message sequences from clients.
    These are critical for buffering logic calibration."""
    patterns = []

    for dialog in all_dialogs:
        msgs = dialog["messages"]
        sequence = []
        for i, msg in enumerate(msgs):
            if not msg["is_staff"]:
                sequence.append(msg)
            else:
                if len(sequence) >= 2:
                    patterns.append({
                        "client": dialog["client_name"],
                        "count": len(sequence),
                        "messages": [s["text"] for s in sequence],
                        "example": " | ".join(s["text"][:50] for s in sequence),
                    })
                sequence = []
        # Check trailing sequence
        if len(sequence) >= 2:
            patterns.append({
                "client": dialog["client_name"],
                "count": len(sequence),
                "messages": [s["text"] for s in sequence],
                "example": " | ".join(s["text"][:50] for s in sequence),
            })

    return sorted(patterns, key=lambda x: -x["count"])[:50]


def process_zip_archive(zip_path: str) -> Optional[Dict]:
    """Extract and parse _chat.txt from a ZIP archive."""
    # Extract client name from filename
    filename = os.path.basename(zip_path)
    name_match = re.search(r"WhatsApp Chat - (.+?)\.zip", filename)
    client_name = name_match.group(1) if name_match else filename

    # Clean up name
    client_name = re.sub(r"^\d+-", "", client_name)  # Remove prefix numbers
    client_name = client_name.replace("Клиент Crystal", "").replace("Клиент Alain", "").strip()

    try:
        with zipfile.ZipFile(zip_path) as z:
            # Find _chat.txt
            chat_files = [n for n in z.namelist() if n.endswith("_chat.txt")]
            if not chat_files:
                return None

            with z.open(chat_files[0]) as f:
                content = f.read().decode("utf-8", errors="replace")

            messages = parse_chat_file(content, client_name)
            if not messages:
                return None

            classification = classify_dialog(messages)

            return {
                "client_name": client_name,
                "source_file": filename,
                "messages": messages,
                "classification": classification,
            }

    except Exception as e:
        print(f"  Error processing {filename}: {e}")
        return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/parse_client_chats.py /path/to/chat/exports/")
        sys.exit(1)

    export_dir = sys.argv[1]
    if not os.path.isdir(export_dir):
        print(f"Directory not found: {export_dir}")
        sys.exit(1)

    # Find all ZIP files
    zip_files = []
    for f in os.listdir(export_dir):
        if f.endswith(".zip"):
            zip_files.append(os.path.join(export_dir, f))

    print(f"Found {len(zip_files)} chat archives")

    # Process all archives
    all_dialogs = []
    for i, zip_path in enumerate(sorted(zip_files)):
        print(f"  [{i+1}/{len(zip_files)}] Processing {os.path.basename(zip_path)[:60]}...")
        result = process_zip_archive(zip_path)
        if result:
            all_dialogs.append(result)
            cls = result["classification"]
            print(f"    -> {cls['total_messages']} msgs, outcome={cls['outcome']}, services={cls['services']}")

    print(f"\nProcessed {len(all_dialogs)} dialogs successfully")

    # Aggregate statistics
    outcomes = Counter(d["classification"]["outcome"] for d in all_dialogs)
    all_services = Counter()
    for d in all_dialogs:
        for s in d["classification"]["services"]:
            all_services[s] += 1

    all_objections = Counter()
    for d in all_dialogs:
        for o in d["classification"]["objections"]:
            all_objections[o] += 1

    payment_methods = Counter(
        d["classification"]["payment_method"]
        for d in all_dialogs
        if d["classification"]["payment_method"]
    )

    total_messages = sum(d["classification"]["total_messages"] for d in all_dialogs)
    total_client = sum(d["classification"]["client_messages"] for d in all_dialogs)
    total_staff = sum(d["classification"]["staff_messages"] for d in all_dialogs)

    # Extract patterns
    faq = extract_faq(all_dialogs)
    client_phrases = extract_client_phrases(all_dialogs)
    multi_msg_patterns = extract_multi_message_patterns(all_dialogs)

    # Build report
    report = {
        "summary": {
            "total_dialogs": len(all_dialogs),
            "total_messages": total_messages,
            "total_client_messages": total_client,
            "total_staff_messages": total_staff,
            "avg_messages_per_dialog": round(total_messages / max(len(all_dialogs), 1), 1),
        },
        "outcomes": dict(outcomes.most_common()),
        "services_mentioned": dict(all_services.most_common()),
        "objections": dict(all_objections.most_common()),
        "payment_methods": dict(payment_methods.most_common()),
        "faq": faq,
        "client_phrases_by_intent": client_phrases,
        "multi_message_patterns": multi_msg_patterns,
        "dialogs": [
            {
                "client_name": d["client_name"],
                "source_file": d["source_file"],
                "classification": d["classification"],
                "message_count": len(d["messages"]),
                # Include first 5 and last 5 messages as sample
                "sample_start": [
                    {"sender": m["sender"], "text": m["text"][:200], "is_staff": m["is_staff"]}
                    for m in d["messages"][:5]
                ],
                "sample_end": [
                    {"sender": m["sender"], "text": m["text"][:200], "is_staff": m["is_staff"]}
                    for m in d["messages"][-5:]
                ],
            }
            for d in all_dialogs
        ],
    }

    # Save output
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "chat_analysis.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"ANALYSIS REPORT")
    print(f"{'='*60}")
    print(f"Dialogs analyzed: {len(all_dialogs)}")
    print(f"Total messages: {total_messages}")
    print(f"Avg messages/dialog: {report['summary']['avg_messages_per_dialog']}")
    print(f"\nOutcomes:")
    for outcome, count in outcomes.most_common():
        print(f"  {outcome}: {count}")
    print(f"\nTop services:")
    for svc, count in all_services.most_common(10):
        print(f"  {svc}: {count}")
    print(f"\nObjections:")
    for obj, count in all_objections.most_common():
        print(f"  {obj}: {count}")
    print(f"\nPayment methods:")
    for pm, count in payment_methods.most_common():
        print(f"  {pm}: {count}")
    print(f"\nMulti-message sequences: {len(multi_msg_patterns)}")
    print(f"FAQ questions extracted: {len(faq)}")
    print(f"\nClient phrases by intent:")
    for intent, phrases in client_phrases.items():
        print(f"  {intent}: {len(phrases)} unique phrases")
    print(f"\nFull report saved to: {output_path}")


if __name__ == "__main__":
    main()
