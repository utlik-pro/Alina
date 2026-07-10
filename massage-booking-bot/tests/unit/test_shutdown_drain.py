"""Shutdown drain: a deploy (SIGTERM) must not silently drop Wappi turns.

Live-caught 2026-07-10 14:41 — a push to develop redeployed Render exactly
while a tester asked two questions; both messages were ACKed to Wappi, the
old instance died mid-buffer/mid-LLM, the client got dead air.
"""

import asyncio

import pytest

import webhook_app


@pytest.fixture(autouse=True)
def _clean_state():
    webhook_app._wappi_buffer.clear()
    webhook_app._wappi_inflight.clear()
    webhook_app._wappi_locks.clear()
    yield
    webhook_app._wappi_buffer.clear()
    webhook_app._wappi_inflight.clear()
    webhook_app._wappi_locks.clear()


@pytest.mark.asyncio
async def test_drain_processes_buffered_messages(monkeypatch):
    """Messages still in the collect window are processed, combined, on drain."""
    processed = []

    async def fake_process(phone, text, sender_name):
        processed.append((phone, text, sender_name))

    monkeypatch.setattr(webhook_app, "_process_wappi_message", fake_process)

    async def never_flush():
        await asyncio.sleep(3600)

    timer = asyncio.get_event_loop().create_task(never_flush())
    webhook_app._wappi_buffer["971500000001"] = {
        "messages": ["What kind of massage you have ?", "7 pm?"],
        "timer": timer,
        "sender_name": "Tester",
    }

    await webhook_app._drain_wappi_turns()

    assert processed == [
        ("971500000001", "What kind of massage you have ?\n7 pm?", "Tester")
    ]
    assert webhook_app._wappi_buffer == {}
    assert timer.cancelled() or timer.done()


@pytest.mark.asyncio
async def test_drain_waits_for_inflight_turn(monkeypatch):
    """A turn already past its sleep (mid-LLM) is awaited, not cancelled."""
    finished = asyncio.Event()

    async def slow_turn():
        await asyncio.sleep(0.05)
        finished.set()

    task = asyncio.get_event_loop().create_task(
        slow_turn(), name="wappi-flush:971500000002"
    )
    webhook_app._wappi_inflight.add(task)
    task.add_done_callback(webhook_app._wappi_inflight.discard)

    await webhook_app._drain_wappi_turns()

    assert finished.is_set()
    assert not task.cancelled()


@pytest.mark.asyncio
async def test_drain_timeout_sends_fallback(monkeypatch):
    """If a turn can't finish before SIGKILL, the client gets a nudge, not silence."""
    monkeypatch.setattr(webhook_app, "_WAPPI_DRAIN_TIMEOUT", 0.05)

    sent = []

    class FakeWappi:
        async def send_message(self, phone, body):
            sent.append((phone, body))

    monkeypatch.setattr(webhook_app, "wappi_client", FakeWappi())

    async def hung_turn():
        await asyncio.sleep(3600)

    task = asyncio.get_event_loop().create_task(
        hung_turn(), name="wappi-flush:971500000003"
    )
    webhook_app._wappi_inflight.add(task)

    await webhook_app._drain_wappi_turns()

    assert sent and sent[0][0] == "971500000003"
    assert "🙏" in sent[0][1]
    task.cancel()


@pytest.mark.asyncio
async def test_drain_noop_when_idle():
    """Nothing buffered, nothing in flight — drain returns immediately."""
    await webhook_app._drain_wappi_turns()
