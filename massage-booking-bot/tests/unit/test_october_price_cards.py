"""Client-provided cards, 14 October: no guessed or extra %-discount prices."""
import pytest
from prices import get_price, SERVICE_CATALOG, format_price_list_for_prompt
from services.promo_photos import get_promo_photo

CARD_PRICES = {
    'wax_eyebrow': 80, 'wax_upper_lip': 50, 'wax_chin': 50, 'wax_sideburn': 50,
    'wax_forehead': 50, 'wax_full_face': 200,
    'lash_ext_classic': 300, 'lash_ext_2d': 350, 'lash_ext_russian': 400,
    'lash_removal': 50, 'lash_lifting': 200, 'brow_lamination': 200,
    'brow_tinting': 80, 'lash_tinting': 50, 'brow_shaping': 80,
    'upper_lip_threading': 35, 'chin_threading': 35,
    'pmu_lips': 1000, 'pmu_lips_correction': 500, 'pmu_eyebrows': 1000,
    'pmu_eyebrows_correction': 500, 'pmu_eyeliner': 1000,
    'pmu_eyeliner_correction': 500, 'pmu_lashliner': 800,
    'pmu_lashliner_correction': 400, 'pmu_recovery': 1200,
}

@pytest.mark.parametrize('key,price', CARD_PRICES.items())
def test_price_matches_approved_card(key, price):
    assert get_price(key) == price
    assert 'discount_percent' not in SERVICE_CATALOG[key]

@pytest.mark.parametrize('key,price', {
    'russian_mani': 140, 'russian_pedi': 154, 'russian_combo': 266,
    'japanese_mani': 126, 'japanese_pedi': 140, 'japanese_combo': 231,
    'russian_mani_basic': 91, 'russian_pedi_basic': 105,
}.items())
def test_nail_promotion_exactly_once(key, price):
    assert get_price(key) == price
    assert SERVICE_CATALOG[key]['regular_price'] > price
    assert '30% off ALREADY INCLUDED' in format_price_list_for_prompt()


def test_promotion_scope_and_artwork():
    assert get_price('nail_ext_soft') == 380
    assert get_price('nail_ext_hard') == 450
    assert get_price('gel_removal') == 40
    assert get_promo_photo('Japanese manicure discount', 'Japanese manicure 126 AED') is None
    assert get_promo_photo('eyebrow permanent', 'Permanent eyebrows 1000 AED').endswith('pmu_2026_10.png')
    assert get_promo_photo('eyebrow waxing', 'Eyebrow waxing 80 AED').endswith('face_waxing_2026_10.png')
    assert get_promo_photo('brow lamination', 'Brow lamination 200 AED').endswith('lashes_brows_2026_10.png')
