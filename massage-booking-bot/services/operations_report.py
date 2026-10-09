"""Read-only reports over durable data. No client messages or calendar writes."""
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
import re
from sqlalchemy import select, func, case, or_, and_
from database.models import (Booking, BookingAttempt, CalendarExpectation, Client,
                             ConversationSnapshot, NightEvent)
from services.booking_reconciliation import check_calendar_record


def identity(value):
    value = str(value or '')
    if value.startswith(('wappi:', 'wappi_')):
        return 'wappi_' + value[6:]
    if value.startswith(('ig:', 'ig_')):
        return 'ig_' + value[3:]
    return 'ig_' + value if value else ''


def is_test_contact(value, tester_ids=()):
    value = identity(value)
    return value.startswith('ig_') and (
        re.fullmatch(r'770099\d{3}', value[3:]) is not None
        or value[3:] in {str(v) for v in tester_ids})


def _extra(event):
    try:
        return json.loads(event.data or '{}')
    except (ValueError, TypeError):
        return {}


NEXT_ACTION = {
    'unanswered': 'Проверить ответ на последнее сообщение.',
    'delivery_failed': 'Проверить канал доставки и ответить клиенту вручную.',
    'booking_problem': 'Сверить попытку с YClients перед любым повтором записи.',
    'service': 'Уточнить услугу.', 'city': 'Уточнить город выезда.',
    'phone': 'Запросить номер телефона в диалоге.',
    'date_time': 'Уточнить удобное время и проверить календарь.',
    'address': 'Уточнить адрес выезда.', 'name': 'Уточнить имя клиента.',
    'payment': 'Уточнить способ оплаты.', 'confirmation': 'Получить подтверждение клиента.',
    'unknown_state': 'Прочитать диалог: сохранённых данных недостаточно.',
}


def build_funnel_report(events, clients, snapshots, bookings, attempts, *, start, end,
                        tester_ids=(), idle_minutes=30, truncated=False):
    """Conversion is unique inbound contacts with an actual calendar ID / routed contacts.

    One contact is counted once in the window, not once per model call or bubble.
    Missing data is unknown. Explicit human routing is not a bot failure.
    """
    grouped = defaultdict(list)
    excluded = set()
    for event in events:
        who = identity(event.who)
        if not who:
            continue
        if is_test_contact(who, tester_ids):
            excluded.add(who)
            continue
        grouped[who].append(event)
    clients = {c.telegram_id: c for c in clients}
    snapshots = {s.user_id: s.payload for s in snapshots if s.updated_at <= end}
    records = {}
    for booking, client in bookings:
        rid = booking.yclients_appointment_id
        if rid and not is_test_contact(client.telegram_id, tester_ids) and client.telegram_id.startswith(('ig_', 'wappi_')):
            records.setdefault(str(rid), (booking, client))
    converted = {client.telegram_id for booking, client in records.values()}
    problems = {client.telegram_id for attempt, client in attempts if client is not None and attempt.status in ('pending', 'failed')}
    summary = Counter()
    summary['excluded_test_contacts'] = len(excluded)
    summary['calendar_records_created'] = len(records)
    summary['active_calendar_records'] = sum(b.status != 'cancelled' for b, _ in records.values())
    contacts, attention = [], []
    for who, evs in sorted(grouped.items()):
        evs.sort(key=lambda e: (e.created_at, e.id or 0))
        inbound = [e for e in evs if e.kind == 'inbound']
        if not inbound:
            continue
        sent = [e for e in evs if e.kind == 'sent']
        routed = [e for e in evs if e.kind == 'routed_to_booking']
        last = inbound[-1].created_at
        idle = max(0, (end - last).total_seconds() / 60)
        client = clients.get(who)
        payload = snapshots.get(who) or {}
        cd, bd = payload.get('client_data') or {}, payload.get('booking_data') or {}
        phone = cd.get('phone') or (client.phone if client else None)
        summary['inbound_contacts'] += 1
        summary['answered_contacts'] += bool(sent)
        summary['agent_contacts'] += bool(routed)
        summary['phone_available_contacts'] += bool(phone) and bool(routed)
        summary['converted_contacts'] += who in converted and bool(routed)
        failures = [e for e in evs if e.kind == 'send_failed']
        routing = [e for e in evs if e.kind in ('human_led_skip', 'routed_to_booking', 'not_ad_skip')]
        human = bool(routing and routing[-1].kind == 'human_led_skip')
        if human:
            stage = 'human_owned'
        elif who in converted:
            stage = 'booked'
        elif payload.get('state') == 'completed':
            stage = 'existing_booking'
        elif not routed:
            stage = ('not_ad' if any(e.kind == 'not_ad_skip' for e in evs) else
                     'outside_window' if not any(_extra(e).get('live') for e in inbound) else 'unanswered')
        elif bd.get('closed_politely'):
            stage = 'closed'
        elif bd.get('out_of_area'):
            stage = 'out_of_area'
        elif who in problems:
            stage = 'booking_problem'
        elif idle < idle_minutes:
            stage = 'in_progress'
        elif failures and (not sent or failures[-1].created_at > sent[-1].created_at):
            stage = 'delivery_failed'
        elif not sent or sent[-1].created_at < last:
            stage = 'unanswered'
        elif not payload:
            stage = 'unknown_state'
        elif not bd.get('service_type'):
            stage = 'service'
        elif bd.get('area_needs_clarification') or not cd.get('area'):
            stage = 'city'
        elif not phone:
            stage = 'phone'
        elif not bd.get('date') or not bd.get('time'):
            stage = 'date_time'
        elif not (cd.get('location') or cd.get('location_details')):
            stage = 'address'
        elif not cd.get('name') or cd.get('name', '').lower() in ('client', 'whatsapp client'):
            stage = 'name'
        elif not bd.get('payment_method'):
            stage = 'payment'
        else:
            stage = 'confirmation'
        summary[stage] += 1
        row = {'contact': who, 'channel': 'instagram' if who.startswith('ig_') else 'whatsapp',
               'stage': stage, 'phone_available': bool(phone), 'last_inbound_utc': last.isoformat(),
               'idle_minutes': round(idle, 1), 'service': bd.get('service_type'),
               'area': cd.get('area')}
        contacts.append(row)
        if stage in NEXT_ACTION and (idle >= idle_minutes or stage == 'booking_problem'):
            attention.append({**row, 'next_action': NEXT_ACTION[stage],
                              'priority': 'high' if stage in ('booking_problem', 'delivery_failed', 'unanswered') else 'normal'})
    denominator = summary['agent_contacts']
    summary['conversion_percent'] = (round(100 * summary['converted_contacts'] / denominator, 1)
                                     if denominator and not truncated else None)
    for key in ('inbound_contacts', 'answered_contacts', 'phone_available_contacts', 'converted_contacts'):
        summary.setdefault(key, 0)
    attention.sort(key=lambda r: (r['priority'] != 'high', -r['idle_minutes'], r['contact']))
    return {'period': {'from_utc': start.isoformat(), 'to_utc': end.isoformat()},
            'source': 'database', 'truncated': truncated, 'summary': dict(summary),
            'conversion_definition': 'Unique routed inbound contacts with a calendar ID created in this window / unique routed inbound contacts.',
            'notes': ['Stages describe the latest saved state; silence is not proof of a lost sale.',
                      'Calendar ID confirms creation, not that every booking field matches; use reconciliation.',
                      'WhatsApp delivery telemetry is available from this release; earlier periods may be incomplete.'],
            'stage_counts': dict(Counter(row['stage'] for row in contacts)),
            'contacts': contacts, 'needs_attention': attention}


async def load_funnel_report(db, *, hours=24, tester_ids=(), now=None):
    end = now or datetime.utcnow()
    start = end - timedelta(hours=hours)
    cap = 20000
    async with db.session() as session:
        events = (await session.execute(select(NightEvent).where(
            NightEvent.created_at >= start, NightEvent.created_at < end
        ).order_by(NightEvent.id.desc()).limit(cap + 1))).scalars().all()
        who = {identity(e.who) for e in events[:cap] if e.who}
        # Contact sets are bounded by the event cap; fetch only this window's cohort.
        clients = (await session.execute(select(Client).where(Client.telegram_id.in_(who)))).scalars().all() if who else []
        snapshots = (await session.execute(select(ConversationSnapshot).where(ConversationSnapshot.user_id.in_(who)))).scalars().all() if who else []
        bookings = (await session.execute(select(Booking, Client).join(Client).outerjoin(
            BookingAttempt, BookingAttempt.booking_id == Booking.id).outerjoin(
            CalendarExpectation, CalendarExpectation.operation_key == BookingAttempt.operation_key).where(
            Booking.created_at >= start, Booking.created_at < end,
            CalendarExpectation.payload['is_test'].as_boolean().is_not(True)))).all()
        attempts = (await session.execute(select(BookingAttempt, Client).join(
            Booking, Booking.id == BookingAttempt.booking_id).join(Client).where(
            Client.telegram_id.in_(who), BookingAttempt.status.in_(['pending', 'failed'])))).all() if who else []
    return build_funnel_report(events[:cap], clients, snapshots, bookings, attempts,
                               start=start, end=end, tester_ids=tester_ids, truncated=len(events) > cap)


async def reconciliation_report(db, calendar, *, limit=20, offset=0, tester_ids=(), now=None):
    now = now or datetime.utcnow()
    async with db.session() as session:
        # Old unresolved attempts first; then newest accepted records.
        query = select(BookingAttempt, Booking, CalendarExpectation, Client).outerjoin(
            Booking, Booking.id == BookingAttempt.booking_id).outerjoin(
            CalendarExpectation, CalendarExpectation.operation_key == BookingAttempt.operation_key
        ).outerjoin(Client, Client.id == Booking.client_id).where(
            or_(Client.telegram_id.is_(None), and_(
                ~Client.telegram_id.like('ig\\_770099___', escape='\\'),
                Client.telegram_id.not_in(['ig_' + str(v) for v in tester_ids]))),
            CalendarExpectation.payload['is_test'].as_boolean().is_not(True),
        ).order_by(
            case((BookingAttempt.status == 'pending', 0), (BookingAttempt.status == 'failed', 1), else_=2),
            case((BookingAttempt.status == 'pending', BookingAttempt.created_at), else_=None).asc(),
            BookingAttempt.created_at.desc())
        rows = (await session.execute(query.offset(offset).limit(limit + 1))).all()
        total = await session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    semaphore = asyncio.Semaphore(5)

    async def inspect(row):
        attempt, booking, expectation, client = row
        expected = expectation.payload if expectation else None
        if (expected or {}).get('is_test') or (client and is_test_contact(client.telegram_id, tester_ids)):
            return None
        async with semaphore:
            try:
                result = await asyncio.wait_for(check_calendar_record(attempt, booking, calendar, expected), timeout=5)
            except Exception:
                result = {'operation': attempt.operation_key, 'booking_id': attempt.booking_id,
                          'record_id': attempt.yclients_id, 'state': 'unverified',
                          'reason': 'Calendar check timed out or failed.'}
        result.update(attempt_status=attempt.status, contact=client.telegram_id if client else None,
                      age_minutes=round(max(0, (now - attempt.created_at).total_seconds() / 60), 1))
        result['needs_attention'] = result['state'] != 'matches' or attempt.status != 'accepted'
        result['next_action'] = (
            'Сверить найденный ID и локальный статус вручную; повторный POST запрещён.' if result['state'] == 'recovered_matches' else
            'Проверить недоступные данные повторно; отсутствие записи не доказано.' if result['state'] == 'unverified' else
            'Проверить отмеченные поля и историю изменений в YClients.' if result['needs_attention'] else None)
        result['priority'] = 'high' if result['state'] == 'mismatch' or (attempt.status == 'pending' and result['age_minutes'] >= 15) else 'normal'
        return result

    results = [r for r in await asyncio.gather(*(inspect(row) for row in rows[:limit])) if r is not None]
    queue = [r for r in results if r['needs_attention']]
    queue.sort(key=lambda r: (r['priority'] != 'high', -r['age_minutes']))
    return {'source': 'database_and_yclients', 'read_only': True, 'total_attempts': total,
            'checked': len(results), 'truncated': len(rows) > limit,
            'offset': offset, 'next_offset': offset + limit if len(rows) > limit else None,
            'summary': dict(Counter(r['state'] for r in results)), 'records': results, 'needs_attention': queue}


STAGE_LABELS = {
    'booked': 'записаны', 'existing_booking': 'ранее завершённая запись',
    'human_owned': 'ведёт администратор', 'outside_window': 'вне рабочего окна',
    'not_ad': 'не рекламное обращение', 'closed': 'клиент отказался или отложил',
    'out_of_area': 'город не обслуживается', 'in_progress': 'диалог продолжается',
    'unanswered': 'ждут ответа', 'delivery_failed': 'ошибка доставки',
    'booking_problem': 'проверить запись', 'service': 'ожидается услуга',
    'city': 'ожидается город', 'phone': 'ожидается телефон', 'date_time': 'ожидается дата/время',
    'address': 'ожидается адрес', 'name': 'ожидается имя', 'payment': 'ожидается способ оплаты',
    'confirmation': 'ожидается подтверждение', 'unknown_state': 'недостаточно данных',
}


def format_funnel_report(report):
    s = report['summary']
    rate = f"{s['conversion_percent']}%" if s['conversion_percent'] is not None else 'нет данных'
    lines = [f"Период UTC: {report['period']['from_utc']} — {report['period']['to_utc']}",
             f"Обращений: {s['inbound_contacts']}; в работе агента: {s['agent_contacts']}; получили ответ: {s['answered_contacts']}",
             f"Телефон известен: {s['phone_available_contacts']}",
             f"Записей с ID YClients: {s['calendar_records_created']}; записавшихся из обращений: {s['converted_contacts']}",
             f"Конверсия обращений агента: {rate}",
             'Состояния: ' + ', '.join(f"{STAGE_LABELS.get(k, k)} — {v}" for k, v in report['stage_counts'].items()),
             f"Требуют внимания: {len(report['needs_attention'])}"]
    for row in report['needs_attention'][:30]:
        lines.append(f"• {row['contact']}: {STAGE_LABELS.get(row['stage'], row['stage'])}, {row['idle_minutes']} мин. — {row['next_action']}")
    if report['truncated']:
        lines.append('ВНИМАНИЕ: лимит данных достигнут; конверсия не рассчитана.')
    return '\n'.join(lines)


def format_reconciliation_report(report):
    lines = [f"Сверено: {report['checked']}; требуют внимания: {len(report['needs_attention'])}"]
    for row in report['needs_attention']:
        fields = ', '.join(k for k, value in row.get('checks', {}).items() if value != 'match')
        lines.append(f"• Запись #{row['booking_id']} / YClients #{row.get('record_id') or 'не сохранён'}: "
                     f"{row['state']}, {row['age_minutes']} мин. {fields}. {row['next_action']}")
    if report['next_offset'] is not None:
        lines.append(f"Следующая страница: --offset {report['next_offset']}")
    lines.append('Отчёт только читает данные. Повторный POST и исправления требуют отдельной проверки.')
    return '\n'.join(lines)
