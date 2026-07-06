"""Unit tests for Wappi image sending and promo-photo matching.

Covers the WhatsApp promo-photo feature:
- WappiClient.send_image builds the correct /img/send request with a raw
  base64 file body, normalized recipient, and optional caption.
- get_promo_photo matches offers/services by user + bot keywords and
  respects exclusions.
"""

import base64
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.wappi_client import WappiClient
from services.promo_photos import get_promo_photo, ASSETS_DIR


class _FakeResp:
    """Minimal async context manager standing in for aiohttp's response."""

    def __init__(self, status, data):
        self.status = status
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._data


def _client_with_fake_session(status=200, data=None):
    """WappiClient wired to a fake aiohttp session; returns (client, session)."""
    client = WappiClient()
    client.token = "test-token"
    client.profile_id = "test-profile"

    session = MagicMock()
    session.post = MagicMock(return_value=_FakeResp(status, data or {"status": "done"}))
    client._get_session = AsyncMock(return_value=session)
    return client, session


# ==================== send_image ====================

@pytest.mark.asyncio
async def test_send_image_builds_img_endpoint_and_base64(tmp_path):
    img = tmp_path / "promo.jpg"
    raw = b"\xff\xd8\xff\xe0 fake jpeg bytes"
    img.write_bytes(raw)

    client, session = _client_with_fake_session()
    result = await client.send_image("+971 50 123 4567@c.us", str(img), caption="Special offer")

    assert result == {"status": "done"}
    session.post.assert_called_once()
    _, kwargs = session.post.call_args
    call_url = session.post.call_args[0][0]
    assert call_url.endswith("/api/sync/message/img/send")
    assert kwargs["params"] == {"profile_id": "test-profile"}
    payload = kwargs["json"]
    # Recipient normalized: no '+', no '@c.us', no spaces stripped by client.
    assert payload["recipient"] == "971501234567"
    assert payload["b64_file"] == base64.b64encode(raw).decode("ascii")
    assert payload["file_name"] == "promo.jpg"
    assert payload["caption"] == "Special offer"


@pytest.mark.asyncio
async def test_send_image_omits_caption_when_empty(tmp_path):
    img = tmp_path / "p.jpg"
    img.write_bytes(b"x")
    client, session = _client_with_fake_session()

    await client.send_image("971500000000", str(img))
    payload = session.post.call_args[1]["json"]
    assert "caption" not in payload


@pytest.mark.asyncio
async def test_send_image_missing_file_returns_none_without_request(tmp_path):
    client, session = _client_with_fake_session()
    result = await client.send_image("971500000000", str(tmp_path / "nope.jpg"))
    assert result is None
    session.post.assert_not_called()


@pytest.mark.asyncio
async def test_send_image_no_credentials_returns_none(tmp_path):
    img = tmp_path / "p.jpg"
    img.write_bytes(b"x")
    client = WappiClient()
    client.token = ""
    client.profile_id = ""
    client._get_session = AsyncMock()  # must not be used
    result = await client.send_image("971500000000", str(img))
    assert result is None
    client._get_session.assert_not_called()


@pytest.mark.asyncio
async def test_send_message_still_uses_text_endpoint():
    """Refactor guard: text send must keep hitting /message/send."""
    client, session = _client_with_fake_session()
    await client.send_message("+971500000000", "Hi dear")
    call_url = session.post.call_args[0][0]
    assert call_url.endswith("/api/sync/message/send")
    assert session.post.call_args[1]["json"] == {"body": "Hi dear", "recipient": "971500000000"}


# ==================== get_promo_photo ====================

def _asset_exists(name):
    return os.path.exists(os.path.join(ASSETS_DIR, name))


def test_promo_cupping_match():
    if not _asset_exists("cupping_offer.jpg"):
        pytest.skip("cupping_offer.jpg asset not present")
    path = get_promo_photo("do you have cupping?", "Yes dear, cupping is 275 AED 😊")
    assert path is not None and path.endswith("cupping_offer.jpg")


def test_promo_face_massage_excludes_deep_cleansing():
    # 'deep facial cleansing' must NOT trigger the face-massage photo.
    path = get_promo_photo(
        "I want deep facial cleansing",
        "Our deep facial cleansing is a great face treatment dear",
    )
    assert path is None or not path.endswith("face_massage.jpg")


def test_promo_no_match_returns_none():
    assert get_promo_photo("what are your working hours?", "We're open 10am to 10pm dear") is None
