"""Unit tests for reset-command detection (webhook_app._is_reset_command)."""

import pytest

from webhook_app import _is_reset_command


@pytest.mark.parametrize("text", [
    "/clear", "/clean", "/reset", "/start", "clear", "clean", "reset",
    "/CLEAN", "  /clear ", "clear!", "очистить", "сброс", "начать заново",
])
def test_recognised(text):
    assert _is_reset_command(text) is True


@pytest.mark.parametrize("text", [
    "book sunday 12pm", "clean my villa please", "reset the massage pressure",
    "", "cleanup my skin", "book sunday\n/clear",  # joined form is NOT a bare reset
])
def test_not_recognised(text):
    assert _is_reset_command(text) is False
