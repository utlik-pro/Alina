"""
Crystal Lab — Centralized Price Catalog (Single Source of Truth)

ALL prices across the system come from this file.
To update a price: change it HERE and it updates everywhere
(bot.py, booking_agent.py, booking_flow.py, follow_up.py, tests).

Last updated: 2026-02-25
"""

from typing import Optional


# ═══════════════════════════════════════════════════════════
# SERVICE CATALOG — all services with prices and durations
# ═══════════════════════════════════════════════════════════

SERVICE_CATALOG = {
    # ── Body Massage ──────────────────────────────────────
    "body_massage_60": {
        "name": "Body massage",
        "duration": 60,
        "price": 350.0,
        "category": "body_massage",
        "techniques": [
            "Lymphatic drainage", "Maderatherapie", "Anti cellulite",
            "Postpartum", "Deep tissue", "Prenatal (after 4 months)",
            "Body massage with guasha", "Body massage with cup",
            "Body massage with brooms", "Aftersurgery",
            "Mixed signature techniques",
        ],
    },
    "body_massage_90": {
        "name": "Body massage 90min",
        "duration": 90,
        "price": 480.0,
        "category": "body_massage",
    },
    "body_face_combo": {
        "name": "Body + Face massage",
        "duration": 110,
        "price": 650.0,
        "category": "combo",
    },

    # ── Face Massage ──────────────────────────────────────
    "face_massage": {
        "name": "Face massage",
        "duration": 50,
        "price": 370.0,
        "category": "face_massage",
        "techniques": [
            "Lifting drainage facial", "Buccal facial",
            "Myofascial massage (non-surgical face lift)",
            "Lifting massage with goasha", "Signature mix techniques",
        ],
    },

    # ── Additional Body Services ──────────────────────────
    "back_massage": {"name": "Back massage", "duration": 30, "price": 175.0, "category": "body_additional"},
    "full_body_scrub": {"name": "Full body scrubbing", "duration": 30, "price": 200.0, "category": "body_additional"},
    "head_spa": {"name": "Head spa massage", "duration": 15, "price": 85.0, "category": "body_additional"},
    "hand_spa": {"name": "Hand spa massage", "duration": 15, "price": 85.0, "category": "body_additional"},
    "foot_reflexology": {"name": "Foot reflexology", "duration": 30, "price": 175.0, "category": "body_additional"},
    "lifting_bandage": {"name": "Lifting body bandage", "duration": 30, "price": 250.0, "category": "body_additional"},
    "drainage_bandage": {"name": "Drainage body bandage", "duration": 30, "price": 250.0, "category": "body_additional"},
    "taping": {"name": "Taping", "duration": None, "price": 100.0, "category": "body_additional", "price_note": "from"},
    "neck_shoulders": {"name": "Neck and shoulders massage", "duration": 30, "price": 200.0, "category": "body_additional"},
    # "cupping" as standalone REMOVED — cupping is a body massage technique (350 AED) or part of 275 AED offer
    # Kept in SPECIAL_OFFERS as lymphatic_cupping_combo (275 AED)

    # ── Facials ───────────────────────────────────────────
    "deep_facial_cleansing": {
        "name": "Deep facial cleansing",
        "duration": 90,
        "price": 420.0,
        "category": "facial",
        "description": "8 steps, 2h treatment: cleansing, peeling, hydrating gel, ultrasonic machine, deep manual cleansing, antibacterial toning, soothing mask, cream with SPF",
    },
    "carboxy_therapy": {"name": "Carboxy-therapy", "duration": 40, "price": 300.0, "category": "facial"},
    "carboxy_alginate": {"name": "Carboxy-therapy + alginate mask", "duration": 60, "price": 300.0, "category": "facial"},
    "shiny_face": {"name": "Shiny face", "duration": None, "price": 299.0, "category": "facial"},

    # ── Facial Treatments ─────────────────────────────────
    # "vitamin_c_facial" REMOVED per Tatyana's request — not in actual price list
    "co2_carboxy": {"name": "CO2 Needle free Carboxy-therapy", "duration": 40, "price": 300.0, "category": "facial_treatment"},
    # "express_facial" REMOVED per Tatyana's request — not in actual price list

    # ── Facial Additional ─────────────────────────────────
    "alginate_mask": {"name": "Alginate mask", "duration": None, "price": 100.0, "category": "facial_additional"},
    "lifting_serum_vc": {"name": "Lifting serum with vitamin C", "duration": None, "price": 100.0, "category": "facial_additional"},
    "face_massage_25": {"name": "Face massage", "duration": 25, "price": 185.0, "category": "facial_additional"},
    "head_spa_15": {"name": "Head spa massage", "duration": 15, "price": 75.0, "category": "facial_additional"},

    # ── Body Treatments ───────────────────────────────────
    "lymphatic_wrap": {"name": "Lymphatic detox wrap", "duration": 60, "price": 350.0, "category": "body_treatment"},
    "slim_wrap": {"name": "Slim detox wrap with cold mask", "duration": 60, "price": 350.0, "category": "body_treatment"},

    # ── Kinesiotaping ─────────────────────────────────────
    "kinesio_1zone": {"name": "Kinesiotaping 1 zone", "duration": 20, "price": 100.0, "category": "kinesio"},
    "kinesio_2zones": {"name": "Kinesiotaping 2 zones", "duration": 30, "price": 170.0, "category": "kinesio"},

    # ── Aesthetic Body Correcting ─────────────────────────
    "aesthetic_stomach": {"name": "Aesthetic body - Stomach", "duration": 20, "price": 100.0, "category": "aesthetic"},
    "aesthetic_hands": {"name": "Aesthetic body - Hands", "duration": 20, "price": 100.0, "category": "aesthetic"},
    "aesthetic_hips": {"name": "Aesthetic body - Hips", "duration": 20, "price": 150.0, "category": "aesthetic"},
    "aesthetic_stomach_hips": {"name": "Aesthetic body - Stomach + hips", "duration": 30, "price": 220.0, "category": "aesthetic"},
    "aesthetic_full": {"name": "Aesthetic body - Stomach + hips + hands", "duration": 40, "price": 330.0, "category": "aesthetic"},

    # ── Nails ─────────────────────────────────────────────
    "russian_mani": {"name": "Russian gelish manicure", "duration": None, "price": 200.0, "category": "nails"},
    "russian_pedi": {"name": "Russian gelish pedicure", "duration": None, "price": 220.0, "category": "nails"},
    "russian_combo": {"name": "Combo Russian gellish mani + pedi", "duration": None, "price": 380.0, "category": "nails"},
    "japanese_mani": {"name": "Japanese manicure", "duration": None, "price": 180.0, "category": "nails"},
    "japanese_pedi": {"name": "Japanese pedicure", "duration": None, "price": 200.0, "category": "nails"},
    "japanese_combo": {"name": "Combo Japanese mani + pedi", "duration": None, "price": 330.0, "category": "nails"},
    "russian_mani_basic": {"name": "Russian manicure (cleaning, nail polish)", "duration": None, "price": 130.0, "category": "nails"},
    "russian_pedi_basic": {"name": "Russian pedicure with smart disc", "duration": None, "price": 150.0, "category": "nails"},
    "nail_ext_soft": {"name": "Nail extensions soft gel", "duration": None, "price": 380.0, "category": "nails"},
    "nail_ext_hard": {"name": "Nail extensions hard gel", "duration": None, "price": 450.0, "category": "nails"},

    # ── Nails Additional ──────────────────────────────────
    "gel_removal": {"name": "Old gel removal", "duration": None, "price": 40.0, "category": "nails_additional"},
    "nail_repair": {"name": "Nail repair (1 nail)", "duration": None, "price": 40.0, "category": "nails_additional"},
    "french_design": {"name": "French design", "duration": None, "price": 60.0, "category": "nails_additional"},
    "nail_design": {"name": "Nail design (1 nail)", "duration": None, "price": 10.0, "category": "nails_additional", "price_note": "10-20"},
    "chrome_design": {"name": "Chrome design (all nails)", "duration": None, "price": 50.0, "category": "nails_additional"},
    "ombre_design": {"name": "Ombre design (all nails)", "duration": None, "price": 60.0, "category": "nails_additional"},
    "cat_eye": {"name": "Cat eye", "duration": None, "price": 50.0, "category": "nails_additional"},
    "cut_and_file": {"name": "Cut and file", "duration": None, "price": 30.0, "category": "nails_additional"},
    "polish_change": {"name": "Polish change", "duration": None, "price": 50.0, "category": "nails_additional"},
    "medical_polish": {"name": "Medical nail polish", "duration": None, "price": 20.0, "category": "nails_additional"},
    "gel_strengthening": {"name": "Gel strengthening", "duration": None, "price": 70.0, "category": "nails_additional"},

    # ── Lashes and Brows ──────────────────────────────────
    "lash_ext_classic": {"name": "Classical volume eyelash extension", "duration": None, "price": 300.0, "category": "lashes_brows"},
    "lash_ext_2d": {"name": "2D volume eyelash extension", "duration": None, "price": 350.0, "category": "lashes_brows"},
    "lash_ext_russian": {"name": "Russian volume eyelash extension", "duration": None, "price": 400.0, "category": "lashes_brows"},
    "lash_removal": {"name": "Eyelashes removal", "duration": None, "price": 50.0, "category": "lashes_brows"},
    "lash_lifting": {"name": "Eyelash lifting", "duration": None, "price": 200.0, "category": "lashes_brows"},
    "brow_lamination": {"name": "Eyebrow lamination (shaping included)", "duration": None, "price": 200.0, "category": "lashes_brows"},
    "brow_tinting": {"name": "Brow tinting", "duration": None, "price": 80.0, "category": "lashes_brows"},
    "lash_tinting": {"name": "Eyelash tinting", "duration": None, "price": 50.0, "category": "lashes_brows"},
    "brow_shaping": {"name": "Brow shaping", "duration": None, "price": 40.0, "category": "lashes_brows"},
    "upper_lip_threading": {"name": "Upper lip threading", "duration": None, "price": 35.0, "category": "lashes_brows"},
    "chin_threading": {"name": "Chin threading", "duration": None, "price": 35.0, "category": "lashes_brows"},
    "lash_brow_combo": {"name": "Combo eyelash lifting + eyebrow lamination", "duration": None, "price": 350.0, "category": "lashes_brows"},

    # ── Permanent Makeup ──────────────────────────────────
    "pmu_lips": {"name": "Permanent makeup - Lips", "duration": None, "price": 900.0, "category": "pmu"},
    "pmu_eyebrows": {"name": "Permanent makeup - Eyebrows", "duration": None, "price": 900.0, "category": "pmu"},
    "pmu_eyeliner": {"name": "Permanent makeup - Eyeliner", "duration": None, "price": 800.0, "category": "pmu"},

    # ── Hair and Makeup ───────────────────────────────────
    "wavy_blow_dry": {"name": "Wavy blow dry", "duration": None, "price": 250.0, "category": "hair_makeup"},
    "hairstyle": {"name": "Hairstyles", "duration": None, "price": 250.0, "category": "hair_makeup", "price_note": "from"},
    "makeup": {"name": "Make up", "duration": None, "price": 300.0, "category": "hair_makeup"},
    "hair_makeup": {"name": "Hair + make up", "duration": None, "price": 500.0, "category": "hair_makeup"},
    "evening_makeup": {"name": "Evening make up", "duration": None, "price": 600.0, "category": "hair_makeup"},
    "kids_makeup": {"name": "Kids make up", "duration": None, "price": 250.0, "category": "hair_makeup"},

    # ── Face Waxing ───────────────────────────────────────
    "wax_eyebrow": {"name": "Eyebrow waxing", "duration": None, "price": 40.0, "category": "face_waxing"},
    "wax_upper_lip": {"name": "Upper lip waxing", "duration": None, "price": 25.0, "category": "face_waxing"},
    "wax_chin": {"name": "Chin waxing", "duration": None, "price": 25.0, "category": "face_waxing"},
    "wax_sideburn": {"name": "Sideburn waxing", "duration": None, "price": 35.0, "category": "face_waxing"},
    "wax_forehead": {"name": "Forehead waxing", "duration": None, "price": 35.0, "category": "face_waxing"},
    "wax_full_face": {"name": "Full face waxing", "duration": None, "price": 100.0, "category": "face_waxing"},
}


# ═══════════════════════════════════════════════════════════
# SPECIAL OFFERS
# ═══════════════════════════════════════════════════════════

SPECIAL_OFFERS = {
    "winter_body_combo": {
        "name": "OFFER - BODY COMBO",
        "price": 499,
        "was": 720,
        "duration": 100,
        "description": "Lymphatic drainage body massage + Facial lifting massage + Head spa treatment + Alginate mask",
    },
    "ramadan_facial": {
        "name": "OFFER - Deep Facial Cleansing",
        "price": 420,
        "was": 770,
        "description": "2h treatment + FREE facial massage + FREE hand massage",
    },
    "winter_nails_japanese": {
        "name": "OFFER - Japanese mani + pedi",
        "price": 330,
        "was": 380,
    },
    "winter_nails_russian": {
        "name": "OFFER - Russian gellish mani + pedi",
        "price": 380,
        "was": 420,
    },
    "winter_lamination": {
        "name": "OFFER - Eyelash lifting + Eyebrow lamination",
        "price": 350,
        "was": 400,
    },
    "lymphatic_cupping_combo": {
        "name": "NEW OFFER - Lymphatic drainage massage + Cupping + Head spa",
        "price": 275,
        "was": 480,
        "duration": 45,
        "description": "Lymphatic drainage body massage + Cupping + Head spa treatment",
    },
    "trial_session": {
        "name": "TRIAL SESSION (NEW CLIENTS ONLY)",
        "price": 350,
        "was": 700,
        "duration": 80,
        "description": "Body massage 60min + Face massage 20min",
    },
    "book_a_friend": {
        "name": "BOOK A FRIEND",
        "price": None,
        "description": "Refer a friend and get 50 AED coupon",
    },
}


# ═══════════════════════════════════════════════════════════
# PACKAGES
# ═══════════════════════════════════════════════════════════

PACKAGES = {
    "face_5x50": {"name": "Face massage", "sessions": 5, "duration": 50, "price": 1650, "was": 1850},
    "body_5x60": {"name": "Body massage", "sessions": 5, "duration": 60, "price": 1550, "was": 1750},
    "body_10x60": {"name": "Body massage", "sessions": 10, "duration": 60, "price": 3000, "was": 3500},
    "body_6x90": {"name": "Body massage", "sessions": 6, "duration": 90, "price": 2590, "was": 2760},
    "body_facial_5x85": {"name": "Body + Facial", "sessions": 5, "duration": 85, "price": 2200, "was": 2675},
}


# ═══════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════

def get_price(service_key: str) -> float:
    """Get price by service key."""
    svc = SERVICE_CATALOG.get(service_key)
    if svc:
        return svc["price"]
    raise KeyError(f"Unknown service: {service_key}")


def get_service(service_key: str) -> dict:
    """Get full service info by key."""
    svc = SERVICE_CATALOG.get(service_key)
    if svc:
        return svc
    raise KeyError(f"Unknown service: {service_key}")


def find_service_by_name(name: str) -> Optional[dict]:
    """Find service by approximate name match."""
    name_lower = name.lower()
    for key, svc in SERVICE_CATALOG.items():
        if svc["name"].lower() == name_lower:
            return {**svc, "key": key}
    return None


# ═══════════════════════════════════════════════════════════
# PROMPT GENERATORS — for booking_agent.py system prompt
# ═══════════════════════════════════════════════════════════

def format_price_list_for_prompt() -> str:
    """Generate the SERVICES & PRICES section for the system prompt."""
    p = get_price  # shorthand

    return f"""SERVICES & PRICES (show WITHOUT VAT)
All prices in AED, VAT NOT included
═══════════════════════════════════════

BODY MASSAGE (all techniques same price):
Techniques: Lymphatic drainage, Maderatherapie, Anti cellulite, Postpartum, Deep tissue, Prenatal (after 4 months), Body massage with guasha, Body massage with cup, Body massage with brooms, Aftersurgery, Mixed signature techniques
- 60 min: {p('body_massage_60'):.0f} AED
- 90 min: {p('body_massage_90'):.0f} AED

FACIAL MASSAGE (50 min each): {p('face_massage'):.0f} AED
Techniques: Lifting drainage facial, Buccal facial, Myofascial massage (non-surgical face lift), Lifting massage with goasha, Signature mix techniques

COMBO: Face + Body massage: {SERVICE_CATALOG['body_face_combo']['duration']} min: {p('body_face_combo'):.0f} AED

ADDITIONAL BODY SERVICES:
- Back massage: 30 min - {p('back_massage'):.0f} AED
- Full body scrubbing: 30 min - {p('full_body_scrub'):.0f} AED
- Head spa massage: 15 min - {p('head_spa'):.0f} AED
- Hand spa massage: 15 min - {p('hand_spa'):.0f} AED
- Foot reflexology: 30 min - {p('foot_reflexology'):.0f} AED
- Lifting body bandage: 30 min - {p('lifting_bandage'):.0f} AED
- Drainage body bandage: 30 min - {p('drainage_bandage'):.0f} AED
- Taping: from {p('taping'):.0f} AED
- Neck and shoulders massage: 30 min - {p('neck_shoulders'):.0f} AED

FACIALS:
- Deep facial cleansing (8 steps, 2h treatment): 90 min - {p('deep_facial_cleansing'):.0f} AED
- Carboxy-therapy: 40 min - {p('carboxy_therapy'):.0f} AED
- Carboxy-therapy + alginate mask: 60 min - {p('carboxy_alginate'):.0f} AED
- Shiny face: {p('shiny_face'):.0f} AED

FACIAL TREATMENTS:
- CO2 Needle free Carboxy-therapy: 40 min - {p('co2_carboxy'):.0f} AED

FACIAL ADDITIONAL:
- Alginate mask: {p('alginate_mask'):.0f} AED
- Lifting serum with vitamin C: {p('lifting_serum_vc'):.0f} AED
- Face massage: 25 min - {p('face_massage_25'):.0f} AED
- Head spa massage: 15 min - {p('head_spa_15'):.0f} AED

BODY TREATMENTS:
- Lymphatic detox wrap: 60 min - {p('lymphatic_wrap'):.0f} AED
- Slim detox wrap with cold mask: 60 min - {p('slim_wrap'):.0f} AED

KINESIOTAPING:
- 1 zone: 20 min - {p('kinesio_1zone'):.0f} AED
- 2 zones: 30 min - {p('kinesio_2zones'):.0f} AED

AESTHETIC BODY CORRECTING:
- Stomach: 20 min - {p('aesthetic_stomach'):.0f} AED | Hands: 20 min - {p('aesthetic_hands'):.0f} AED
- Hips: 20 min - {p('aesthetic_hips'):.0f} AED | Stomach + hips: 30 min - {p('aesthetic_stomach_hips'):.0f} AED
- Stomach + hips + hands: 40 min - {p('aesthetic_full'):.0f} AED

NAILS:
- Russian gelish manicure with machine: {p('russian_mani'):.0f} AED
- Russian gelish pedicure with machine (smart disc): {p('russian_pedi'):.0f} AED
- Combo Russian gellish mani + pedi: {p('russian_combo'):.0f} AED
- Japanese mani: {p('japanese_mani'):.0f} AED | Japanese pedicure: {p('japanese_pedi'):.0f} AED
- Combo Japanese mani + pedi: {p('japanese_combo'):.0f} AED
- Russian manicure (cleaning, nail polish included): {p('russian_mani_basic'):.0f} AED
- Russian pedicure with smart disc (cleaning, nail polish included): {p('russian_pedi_basic'):.0f} AED
- Nail extensions soft gel: {p('nail_ext_soft'):.0f} AED | Hard gel: {p('nail_ext_hard'):.0f} AED

NAILS ADDITIONAL:
Old gel removal: {p('gel_removal'):.0f} | Nail repair (1): {p('nail_repair'):.0f} | French: {p('french_design'):.0f} | Nail design (1): 10-20
Chrome (all): {p('chrome_design'):.0f} | Ombre (all): {p('ombre_design'):.0f} | Cat eye: {p('cat_eye'):.0f} | Cut and file: {p('cut_and_file'):.0f}
Polish change: {p('polish_change'):.0f} | Medical polish: {p('medical_polish'):.0f} | Gel strengthening: {p('gel_strengthening'):.0f}

LASHES AND BROWS:
- Classical eyelash extension: {p('lash_ext_classic'):.0f} AED
- 2D volume: {p('lash_ext_2d'):.0f} AED | Russian volume: {p('lash_ext_russian'):.0f} AED
- Eyelashes removal: {p('lash_removal'):.0f} AED
- Eyelash lifting: {p('lash_lifting'):.0f} AED
- Eyebrow lamination (shaping included): {p('brow_lamination'):.0f} AED
- Brow tinting: {p('brow_tinting'):.0f} | Eyelash tinting: {p('lash_tinting'):.0f} | Brow shaping: {p('brow_shaping'):.0f}
- Upper lip threading: {p('upper_lip_threading'):.0f} | Chin threading: {p('chin_threading'):.0f}
- Combo eyelash lifting + eyebrow lamination: {p('lash_brow_combo'):.0f} AED

PERMANENT MAKE UP:
Lips: {p('pmu_lips'):.0f} AED | Eyebrows: {p('pmu_eyebrows'):.0f} AED | Eyeliner: {p('pmu_eyeliner'):.0f} AED

HAIR AND MAKE UP:
- Wavy blow dry: {p('wavy_blow_dry'):.0f} | Hairstyles: from {p('hairstyle'):.0f} | Make up: {p('makeup'):.0f}
- Hair + make up: {p('hair_makeup'):.0f} | Evening make up: {p('evening_makeup'):.0f} | Kids make up: {p('kids_makeup'):.0f}

FACE WAXING:
Eyebrow: {p('wax_eyebrow'):.0f} | Upper lip: {p('wax_upper_lip'):.0f} | Chin: {p('wax_chin'):.0f} | Sideburn: {p('wax_sideburn'):.0f} | Forehead: {p('wax_forehead'):.0f} | Full face: {p('wax_full_face'):.0f}"""


def format_special_offers_for_prompt() -> str:
    """Generate the SPECIAL OFFERS section for the system prompt."""
    p = get_price  # shorthand
    lines = ["CURRENT SPECIAL OFFERS (Feb 2026)", "═══════════════════════════════════"]

    for key, offer in SPECIAL_OFFERS.items():
        if offer["price"] is None:
            lines.append(f"\n🎁 {offer['name']}")
        else:
            lines.append(f"\n🔥 {offer['name']}: {offer['price']} AED (was {offer.get('was', '?')})")
        if offer.get("duration"):
            lines.append(f"{offer['duration']} min: {offer.get('description', '')}")
        elif offer.get("description"):
            lines.append(offer["description"])

    lines.append(f"\nMASSAGE PACKAGES:")
    for key, pkg in PACKAGES.items():
        lines.append(f"- {pkg['name']}: {pkg['sessions']} x {pkg['duration']}min - {pkg['price']:,} AED (was {pkg['was']:,})")

    return "\n".join(lines)
