"""Full model-driven booking journey with real temporary DB and fake calendar.
Only OpenAI is contacted. Client transport and all notifications are captured.
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--output", default="../docs/full-booking-journey-2026-09-06.json")
    args = parser.parse_args()
    from dotenv import dotenv_values
    os.environ.update(OPENAI_API_KEY=dotenv_values('/Users/admin/Alina/massage-booking-bot/.env')['OPENAI_API_KEY'],
                      TELEGRAM_BOT_TOKEN='0:test', MOCK_YCLIENTS='false')
    import pytest
    from unittest.mock import AsyncMock, Mock
    from types import SimpleNamespace
    from database.db import Database
    from database.models import Base
    from database.services import ClientService, MessageService, BookingService
    from agents.booking_agent import BookingAgent
    from dialog_context import DialogManager
    import webhook_app as wh
    import bot
    import services.turn_logger as tl
    from loguru import logger
    logger.remove()
    tomorrow=(datetime.now(timezone(timedelta(hours=4)))+timedelta(days=1)).strftime('%Y-%m-%d')
    records=[]
    async def summary(date, **kwargs):
        return f'Available on {date}:\nTest therapist: 2:00 PM, 4:00 PM' if date==tomorrow else 'No slots available'
    async def available(area, date, time, *args, **kwargs):
        return date==tomorrow and time in ('14:00', '16:00')
    async def create(**kwargs):
        records.append(kwargs)
        return {'id':9000+len(records)}
    calendar=SimpleNamespace(get_available_slots_summary=summary,is_slot_available=available,
        find_service_id=AsyncMock(return_value=9),find_staff_id=AsyncMock(return_value=7),
        staff_area_of=AsyncMock(return_value='abu_dhabi'),
        get_staff=AsyncMock(return_value=[{'id':7,'name':'Test therapist Abu Dhabi'}]),create_booking=create)
    turns=['Hi, facial massage in Abu Dhabi please. How much and how long?',
           'Do you come to my home?', '0500000000', 'Tomorrow at 2 pm please',
           'Al Raha, Test Building, apartment 12', 'My name is Jane Test',
           'Cash', 'Yes, please confirm my appointment', 'Thank you']
    result={'model':args.model, 'calendar':'fake; only tomorrow 14:00/16:00', 'turns':[]}
    with tempfile.TemporaryDirectory(prefix='crystal-journey-') as tmp, pytest.MonkeyPatch.context() as patch:
        db=Database(f'sqlite+aiosqlite:///{tmp}/test.db')
        async with db.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        agent=BookingAgent(model=args.model)
        patch.setattr(bot,'client_service',ClientService(db))
        patch.setattr(bot,'message_service',MessageService(db))
        patch.setattr(bot,'booking_service',BookingService(db))
        patch.setattr(bot,'yclients_service',calendar)
        patch.setattr(bot,'follow_up_service',None)
        patch.setattr(bot,'notification_service',None)
        patch.setattr(wh,'dialog_manager',DialogManager())
        patch.setattr(wh,'booking_agent',agent)
        patch.setattr(wh.config,'MOCK_YCLIENTS',False)
        patch.setattr(wh.config,'WAPPI_SEND_PROMO_PHOTOS',False)
        patch.setattr(wh,'wappi_client',None)
        for name in ['_send_to_client','_admin_text','_notify_driver','_alert_admins_about_lead']:
            patch.setattr(wh,name,AsyncMock(return_value=True))
        patch.setattr(wh,'_night_event',Mock())
        patch.setattr(tl,'log_turn',Mock())
        try:
            for text in turns:
                wh._send_to_client.reset_mock()
                await wh._process_wappi_message('ig:555',text,'')
                ctx=wh.dialog_manager.get_context('ig_555')
                row={'client':text,'messages':[c.args[1] for c in wh._send_to_client.await_args_list],
                     'calendar_records':len(records),'state':ctx.state}
                result['turns'].append(row)
                print(json.dumps(row,ensure_ascii=False),flush=True)
                result['calendar_records']=records
                result['local_bookings']=await bot.booking_service.get_active_bookings('ig_555')
                Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str))
            before = result['turns'][:7]
            assert all(turn['calendar_records'] == 0 for turn in before), 'Premature calendar write'
            assert len(records) == 1, 'Expected exactly one calendar record after confirmation and thanks'
            record = records[0]
            assert record['date'] == tomorrow and record['time'] == '14:00'
            assert record['duration_minutes'] == 50 and record['staff_id'] == 7
            assert record['client_name'] == 'Jane Test' and record['client_phone'].endswith('500000000')
            local = result['local_bookings'][0]
            assert local['area'] == 'abu_dhabi' and local['therapist_name']
            assert local['yclients_appointment_id'] == '9001'
            assert local['total_price'] == 370 and local['payment_method'] == 'cash'
            result['verified'] = ['no record before explicit confirmation', 'one record after thanks',
                'correct date/time/duration/name/phone/staff', 'local area/master/calendar ID', 'cash total 370 AED']
            Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str))
        finally:
            await agent.client.close()
            await db.close()

asyncio.run(main())
