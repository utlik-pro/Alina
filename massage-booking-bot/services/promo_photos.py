"""Promo photo service — sends relevant promotional images with bot responses.

Photos are stored in assets/ and matched to user queries/bot responses by keyword.
"""

import os
from typing import Optional, Tuple
from loguru import logger

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")

# Mapping: (keywords_in_user_message, keywords_in_bot_response) -> photo filename
# Priority order matters — first match wins
PROMO_PHOTOS = [
    # Cupping offer 275 AED
    {
        "file": "cupping_offer.jpg",
        "user_keywords": ["cupping", "банки"],
        "bot_keywords": ["275", "cupping"],
        "match": "any_user",  # match if any user keyword found
    },
    # Japanese manicure
    {
        "file": "japanese_mani.jpg",
        "user_keywords": ["japanese", "японский"],
        "bot_keywords": ["japanese mani", "japanese pedi"],
        "match": "any_user",
    },
    # General manicure/nails
    {
        "file": "manicure.jpg",
        "user_keywords": ["manicure", "mani", "pedi", "nails", "nail", "маникюр", "педикюр"],
        "bot_keywords": ["manicure", "mani", "pedi", "nail"],
        "match": "any_user",
    },
    # Face massage ONLY (NOT deep facial cleansing)
    {
        "file": "face_massage.jpg",
        "user_keywords": ["face massage", "лицо"],
        "bot_keywords": ["face massage"],
        "match": "any_user",
        "exclude_keywords": ["deep", "cleansing", "facial cleansing"],
    },
    # Body massage
    {
        "file": "body_massage.jpg",
        "user_keywords": ["body", "massage", "массаж"],
        "bot_keywords": ["body massage"],
        "match": "any_user",
    },
    # Book a friend / discount
    {
        "file": "book_a_friend.jpg",
        "user_keywords": ["discount", "cheaper", "expensive", "скидка", "дорого"],
        "bot_keywords": ["book a friend", "refer", "coupon"],
        "match": "any_user",
    },
]


def get_promo_photo(user_text: str, bot_response: str) -> Optional[str]:
    """
    Determine if a promo photo should be sent based on user message and bot response.

    Returns the full path to the photo file, or None.
    """
    user_lower = user_text.lower()
    bot_lower = bot_response.lower()

    for promo in PROMO_PHOTOS:
        photo_path = os.path.join(ASSETS_DIR, promo["file"])
        if not os.path.exists(photo_path):
            continue

        user_match = any(kw in user_lower for kw in promo["user_keywords"])
        bot_match = any(kw in bot_lower for kw in promo["bot_keywords"])

        # Check exclusions
        exclude = promo.get("exclude_keywords", [])
        if exclude and any(kw in user_lower for kw in exclude):
            continue

        if user_match and bot_match:
            logger.info(f"Promo photo match: {promo['file']} (user={user_match}, bot={bot_match})")
            return photo_path

    return None
