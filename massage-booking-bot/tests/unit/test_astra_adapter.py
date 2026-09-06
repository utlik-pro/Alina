from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import pytest
from agents.booking_agent import BookingAgent

@pytest.mark.asyncio
async def test_astra_preserves_structured_booking_call():
    agent = BookingAgent.__new__(BookingAgent)
    agent.model = 'gpt-6-astra'
    usage = S(output_tokens=20, model_dump=lambda: {'input_tokens': 100, 'output_tokens': 20})
    result = S(status='completed',output_text='',usage=usage,
               output=[S(type='function_call',name='book_appointment',arguments='{"date":"2026-09-12"}')])
    agent.client = S(responses=S(create=AsyncMock(return_value=result)))
    out = await agent._request_booking_model([{'role':'user','content':'yes'}])
    assert out.choices[0].message.tool_calls[0].function.name == 'book_appointment'
    assert out.choices[0].message.tool_calls[0].function.arguments == '{"date":"2026-09-12"}'
    assert agent.client.responses.create.await_args.kwargs['store'] is False
    assert agent.last_usage['output_tokens'] == 20

@pytest.mark.asyncio
async def test_sol_preserves_chat_tools_with_explicit_no_reasoning():
    agent = BookingAgent.__new__(BookingAgent)
    agent.model = 'gpt-5.6-sol'
    result = S(usage=None)
    create = AsyncMock(return_value=result)
    agent.client = S(chat=S(completions=S(create=create)))
    assert await agent._request_booking_model([{'role':'user','content':'yes'}]) is result
    kwargs = create.await_args.kwargs
    assert kwargs['reasoning_effort'] == 'none'
    assert kwargs['tools'] and kwargs['tool_choice'] == 'auto'
