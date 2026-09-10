"""Гейты ответа: подключены к пайплайну и судят по смыслу, а не по подстроке.

Ночь 09→10.09 дала три дефекта разом, и все три — не про модель, а про код:

1. Голое «Hi» уходило приветственным МЕНЮ (с маникюром и ресницами, которых
   некому делать) вместо вопроса Татьяны «лицо, тело или чистка?». Гейт
   `_enforce_full_intro` был подключён, но его страж «уже спрошено ровно
   тремя услугами» проверял НАЛИЧИЕ трёх подстрок — а меню содержит все три
   как пункты списка. Страж срабатывал, меню уходило клиенту. Двое из пяти
   живых лидов той ночи получили именно его.

2. `_enforce_kind_settled` и `_enforce_massage_types_answered` были написаны,
   покрыты своими проверками — и НИ РАЗУ не вызваны из пайплайна. Ровно тот
   же провал, что в v2 с карточками админов: зелёные юнит-тесты при сломанном
   проде. Отсюда универсальный тест подключения ниже — он ловит любой такой
   гейт, а не только два известных.

3. Два клиента прислали ОДИН И ТОТ ЖЕ рекламный префилл, а номер спросили
   только у одного: гейт номера молчит без цены в ответе, а формулировка
   модели плавает. Лид с рекламы цену уже видел в креативе.
"""

import ast
import types

import webhook_app as w
from prices import SERVICE_QUESTION_INTRO


# --- 2. подключение: любой _enforce_* обязан вызываться из пайплайна --------

ENTRY_POINT = "_process_wappi_message"


def _call_graph():
    """{функция: {кого зовёт}} по всему модулю — через AST, не по подстрокам.

    Первая версия этого теста склеивала «тела» гейтов через str.split и
    ловила ВЕСЬ остаток файла: сироты находились всегда, тест был зелёным
    и бесполезным. Считаем вызовы честно.
    """
    tree = ast.parse(open(w.__file__, encoding="utf-8").read())
    graph, defined = {}, set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        defined.add(node.name)
        called = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                fn = sub.func
                name = (fn.id if isinstance(fn, ast.Name)
                        else fn.attr if isinstance(fn, ast.Attribute) else None)
                if name and name != node.name:
                    called.add(name)
        graph[node.name] = called
    return graph, defined


def test_every_enforce_gate_is_wired_into_the_pipeline():
    """Гейт без вызова проходит ВСЕ юнит-тесты и молча ломает прод.

    Так прожили `_enforce_kind_settled` и `_enforce_massage_types_answered`:
    определены, покрыты проверками, никогда не вызваны — жалоба владельца от
    08.09 оставалась живой в проде. Проверяем не «есть ли функция», а
    «достижима ли она из хода диалога».
    """
    graph, defined = _call_graph()
    gates = {n for n in defined if n.startswith("_enforce_")}
    assert gates, "гейты не найдены — тест смотрит не туда"
    assert ENTRY_POINT in graph, f"{ENTRY_POINT} не найден"

    reachable, stack = set(), [ENTRY_POINT]
    while stack:                                 # обход из точки входа
        cur = stack.pop()
        for callee in graph.get(cur, ()):
            if callee not in reachable:
                reachable.add(callee)
                stack.append(callee)

    orphans = sorted(gates - reachable)
    assert not orphans, f"гейты определены, но не вызываются из хода: {orphans}"


# --- 1. full-intro: страж должен смотреть, что СВЕРХ трёх услуг ничего нет --

def _ctx(**booking):
    return types.SimpleNamespace(booking_data=dict(booking), client_data={})


# Дословный ответ прода на голое «Hi» (смоук 770099210, 10.09 11:50).
PROD_WELCOME_MENU = (
    "Hi dear 🌹 Welcome to Crystal Lab home service 🙌\n"
    "Certified Russian therapists and free transportation to your home\n"
    "Abu Dhabi, Al Ain and Dubai\n"
    "- Body massage\n"
    "- Face massage\n"
    "- Deep facial cleansing\n"
    "- Manicure and pedicure\n"
    "- Eyelash extension and lifting\n"
    "What service are you interested in?"
)


def test_welcome_menu_is_replaced_by_the_three_way_question():
    """Живой дефект ночи 09→10.09 — меню вместо вопроса Татьяны."""
    out = w._enforce_full_intro(PROD_WELCOME_MENU, _ctx(), "Hi", who="test")
    assert out.strip() == SERVICE_QUESTION_INTRO.strip()
    assert "Manicure" not in out          # мастера маникюра сейчас нет
    assert "Eyelash" not in out


def test_a_genuine_three_way_question_is_left_alone():
    """Страж существует ради этого случая — его нельзя сломать починкой."""
    already = SERVICE_QUESTION_INTRO
    assert w._enforce_full_intro(already, _ctx(), "Hi", who="test") == already


def test_three_way_question_with_prices_is_left_alone():
    """Сравнение тела и лица — законный ответ (правило 3x, 01.09)."""
    compare = ("Body massage 350 AED, face massage 370 AED, deep facial "
               "cleansing 420 AED.\nWhich service are you interested in?")
    assert w._enforce_full_intro(compare, _ctx(), "Hi", who="test") == compare


def test_known_service_keeps_the_model_reply():
    menu = PROD_WELCOME_MENU
    ctx = _ctx(service_named=True)
    assert w._enforce_full_intro(menu, ctx, "body massage", who="test") == menu


def test_recognised_ad_prefill_keeps_the_model_reply():
    ctx = _ctx(ad_prefill="cleansing")
    assert w._enforce_full_intro(PROD_WELCOME_MENU, ctx, "Hi", who="t") == \
        PROD_WELCOME_MENU


# --- 3. номер спрашивается и у рекламного лида без цены в ответе ------------

def test_ad_lead_is_asked_for_the_number_even_without_a_price():
    """918171931 (10.09 22:28) ушёл без номера: цены в ответе не было.

    Тот же префилл у 90664270 дал цены — и номер спросили. Возвратность лида
    не может зависеть от того, как модель сформулировала ход.
    """
    reply = ("We do home service in Abu Dhabi, Al Ain and Dubai with certified "
             "Russian female specialists 🌹\nBody massage or facial dear?")
    ctx = _ctx(ad_prefill="massage")
    out = w._enforce_phone_first(reply, ctx, phone_known=False, is_ig=True,
                                 who="test")
    assert out != reply
    assert w._ASKS_FOR_NUMBER_RE.search(out), out


def test_walk_in_without_a_price_is_still_not_asked_for_the_number():
    """Без рекламы и без цены просить номер по-прежнему рано."""
    reply = "Hello dear 🌹 Body massage or facial?"
    ctx = _ctx()
    assert w._enforce_phone_first(reply, ctx, phone_known=False, is_ig=True,
                                  who="test") == reply


def test_a_known_phone_is_never_asked_again():
    reply = "Body massage 350 AED 🌹 Which day suits you?"
    ctx = _ctx(ad_prefill="massage", phone_asked=True)
    assert w._enforce_phone_first(reply, ctx, phone_known=True, is_ig=True,
                                  who="test") == reply
