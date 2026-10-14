from unittest.mock import AsyncMock, Mock
import pytest
from prices import nail_promotion_terms
from services.yclients_service import YClientsService

@pytest.mark.parametrize('name,price,regular', [
    ('russian_manicure',140,200), ('pedicure',154,220),
    ('combo_mani_pedi',266,380), ('Japanese manicure',126,180),
    ('Japanese pedicure',140,200), ('Japanese manicure + pedicure',231,330),
    ('russian_mani_basic',91,130), ('russian_pedi_basic',105,150),
    ('russian_combo',266,380), ('japanese_combo',231,330),
])
def test_canonical_promotion_terms(name,price,regular):
    assert nail_promotion_terms(name,price)=={'cost':price,'first_cost':regular,'discount':30}


def test_other_services_not_discounted_and_wrong_quotes_refused():
    assert nail_promotion_terms('nail_extension',380) is None
    assert nail_promotion_terms('face_massage',370) is None
    with pytest.raises(ValueError): nail_promotion_terms('russian_manicure',98)
    with pytest.raises(ValueError): nail_promotion_terms('russian_manicure',200)


@pytest.mark.asyncio
@pytest.mark.parametrize('success',[True,False])
async def test_create_transmits_price_and_never_drops_it_on_fallback(monkeypatch, success):
    yc=YClientsService()
    monkeypatch.setattr(yc,'get_real_available_slots',AsyncMock(return_value=['17:00']))
    response=AsyncMock()
    response.json.return_value={'success':success,'data':{'id':42},'meta':{'message':'rejected'}}
    manager=AsyncMock(); manager.__aenter__.return_value=response
    session=Mock(); session.post.return_value=manager
    monkeypatch.setattr(yc,'_get_session',AsyncMock(return_value=session))
    terms=nail_promotion_terms('russian_manicure',140)
    result=await yc.create_booking(1,[2],'2030-01-01','17:00',service_pricing=terms)
    session.post.assert_called_once()
    payload=session.post.call_args.kwargs['json']
    assert payload['services']==[{'id':2,'first_cost':200,'discount':30,'cost':140}]
    assert ('id' in result)==success
