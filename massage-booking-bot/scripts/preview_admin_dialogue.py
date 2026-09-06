"""Generate a multi-turn client-visible transcript. External actions are mocked."""
import asyncio
import json
import os
import sys
from pathlib import Path

async def main():
    from dotenv import dotenv_values
    os.environ.update(OPENAI_API_KEY=dotenv_values('/Users/admin/Alina/massage-booking-bot/.env')['OPENAI_API_KEY'],
        TELEGRAM_BOT_TOKEN='0:test', DATABASE_URL='sqlite+aiosqlite:///:memory:', MOCK_YCLIENTS='true')
    import pytest
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    import webhook_app as wh
    import bot
    from agents.booking_agent import BookingAgent
    from loguru import logger
    logger.remove()
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests/replay'))
    from test_client_dialogues_v2 import dialogue
    transcript=[]
    with pytest.MonkeyPatch.context() as patch:
        ctx=dialogue.__wrapped__(patch).ctx
        agent=BookingAgent(model='gpt-5.4')
        patch.setattr(wh,'booking_agent',agent)
        patch.setattr(wh.config,'MOCK_YCLIENTS',False)
        patch.setattr(bot,'yclients_service',SimpleNamespace(get_available_slots_summary=AsyncMock(return_value=None),is_slot_available=AsyncMock(return_value=None)))
        for method in ['_maybe_create_booking','_handle_cancellation','_handle_reschedule','_admin_text']:
            patch.setattr(wh,method,AsyncMock())
        try:
            for text in ['Hi, facial massage in Abu Dhabi please. How much and how long?',
                         'Do you come to my home?', '0500000000',
                         'Tomorrow at 2 pm please', 'I will confirm later thank you']:
                wh._send_to_client.reset_mock()
                await wh._process_wappi_message('ig:555',text,'Test')
                replies=[c.args[1] for c in wh._send_to_client.await_args_list]
                transcript.append({'client':text,'messages':replies})
                print(json.dumps(transcript[-1],ensure_ascii=False),flush=True)
                Path('../docs/admin-dialogue-preview-2026-09-06.json').write_text(json.dumps(transcript,ensure_ascii=False,indent=2))
        finally:
            await agent.client.close()

asyncio.run(main())
