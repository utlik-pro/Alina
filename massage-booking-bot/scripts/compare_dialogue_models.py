"""Bounded comparison through v2's final handler; transports/calendar/DB are mocks.
Uses synthetic, anonymized scenarios derived from client feedback. No messages sent.
Run: PYTHONPATH=. python scripts/compare_dialogue_models.py --key-env /path/to/.env
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

async def run(args):
    from dotenv import dotenv_values
    key = dotenv_values(args.key_env).get('OPENAI_API_KEY')
    if not key:
        raise SystemExit('No API key in the selected environment')
    os.environ.update(OPENAI_API_KEY=key, TELEGRAM_BOT_TOKEN='0:test',
                      DATABASE_URL='sqlite+aiosqlite:///:memory:', MOCK_YCLIENTS='true', MOCK_WHATSAPP='true')
    import pytest
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    from agents.booking_agent import BookingAgent
    import webhook_app as wh
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests/replay'))
    from test_client_dialogues_v2 import dialogue
    from loguru import logger
    logger.remove()
    cases = [
        ('home_question', 'Do you have a branch in Dubai or home service only?', 'face_massage'),
        ('phone_provided', '0500000000', 'face_massage'),
        ('change_service', 'Body massage if I like it I will do facial too', 'face_massage'),
        ('price_question', 'How much is facial massage and how long does it take?', 'face_massage'),
    ]
    if args.cases:
        cases = [c for c in cases if c[0] in args.cases]
    results = []
    for model in args.models:
        for name, text, service in cases:
            with pytest.MonkeyPatch.context() as patch:
                replay = dialogue.__wrapped__(patch)
                replay.ctx.client_data.update(phone='971500000000', area='abu_dhabi')
                replay.ctx.booking_data.update(service_type=service, service_named=True, service_duration=50)
                replay.ctx.recent_messages = [{'role':'assistant','content':'Facial massage is 370 AED for 50 minutes. May I have your WhatsApp number?'}]
                agent = BookingAgent(model=model)
                patch.setattr(wh, 'booking_agent', agent)
                # Fixed unavailable calendar for both models: no invented slots
                # are permitted, and no live YClients requests can occur.
                import bot
                patch.setattr(wh.config, 'MOCK_YCLIENTS', False)
                patch.setattr(bot, 'yclients_service', SimpleNamespace(
                    get_available_slots_summary=AsyncMock(return_value=None),
                    is_slot_available=AsyncMock(return_value=None)))
                for method in ['_maybe_create_booking','_handle_cancellation','_handle_reschedule','_admin_text']:
                    patch.setattr(wh, method, AsyncMock())
                start = time.monotonic()
                await wh._process_wappi_message('ig:555', text, 'Test')
                elapsed = time.monotonic()-start
                sent = [c.args[1] for c in wh._send_to_client.await_args_list]
                usage = getattr(agent, 'last_usage', None)
                row = dict(model=model, case=name, user=text, replies=sent, seconds=round(elapsed,2), usage=usage,
                           thought_messages=1<=len(sent)<=3, max_one_question=sum(s.count('?') for s in sent)<=1,
                           service_after=replay.ctx.booking_data.get('service_type'))
                results.append(row)
                Path(args.output).write_text(json.dumps(results,ensure_ascii=False,indent=2))
                print(model,name,f'{elapsed:.1f}s','usage='+str(bool(usage)),flush=True)
                await agent.client.close()
    print('Report:',args.output)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--key-env',required=True)
    p.add_argument('--models',nargs='+',default=['gpt-5.4','gpt-6-astra'])
    p.add_argument('--cases', nargs='+')
    p.add_argument('--output',default='../docs/model-comparison-2026-09-06.json')
    asyncio.run(run(p.parse_args()))
