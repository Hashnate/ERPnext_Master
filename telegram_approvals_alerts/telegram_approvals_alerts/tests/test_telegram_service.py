"""
Unit tests for Telegram Bot Client and Service.
Verifies message formatting, inline keyboard generation, sanitization, and API call error handling.
"""

from unittest.mock import MagicMock, patch
import urllib.error

import pytest

from telegram_approvals_alerts.services.telegram_service import (
    TelegramBotClient,
    build_approval_keyboard,
    get_bot_token,
    get_webhook_secret,
    resolve_doctype_from_code,
    sanitize_payload,
)


def test_sanitize_payload_masks_sensitive_data():
    """Ensure bot tokens, secrets, and passwords are never logged."""
    payload = {
        "bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        "webhook_secret": "my-ultra-secret-token",
        "nested": {
            "password": "secret_password",
            "safe_field": "public_data",
        },
        "chat_id": "987654321",
    }
    cleaned = sanitize_payload(payload)

    assert cleaned["bot_token"] == "******"
    assert cleaned["webhook_secret"] == "******"
    assert cleaned["nested"]["password"] == "******"
    assert cleaned["nested"]["safe_field"] == "public_data"
    assert cleaned["chat_id"] == "987654321"


def test_inline_keyboard_generation():
    """Verify inline Approve and Reject button callback data format and limit."""
    kb = build_approval_keyboard("Purchase Order", "PO-2026-00012")
    assert "inline_keyboard" in kb
    buttons = kb["inline_keyboard"][0]
    assert len(buttons) == 2

    # Approve button
    assert "Approve" in buttons[0]["text"]
    assert buttons[0]["callback_data"] == "app:PO:PO-2026-00012"
    assert len(buttons[0]["callback_data"]) <= 64  # Telegram 64-byte callback_data limit

    # Reject button
    assert "Reject" in buttons[1]["text"]
    assert buttons[1]["callback_data"] == "rej:PO:PO-2026-00012"
    assert len(buttons[1]["callback_data"]) <= 64


def test_resolve_doctype_from_code():
    """Verify short code resolution."""
    assert resolve_doctype_from_code("PO") == "Purchase Order"
    assert resolve_doctype_from_code("LA") == "Leave Application"
    assert resolve_doctype_from_code("EC") == "Expense Claim"
    assert resolve_doctype_from_code("Custom Doc") == "Custom Doc"


def test_bot_token_and_secret_retrieval(mock_frappe_env):
    """Verify settings retrieval for bot token and webhook secret."""
    mock_settings = MagicMock()
    mock_settings.get_password = MagicMock(side_effect=lambda f: f"test_{f}_val")
    mock_frappe_env.get_single.return_value = mock_settings

    token = get_bot_token(mock_settings)
    secret = get_webhook_secret(mock_settings)

    assert token == "test_bot_token_val"
    assert secret == "test_webhook_secret_val"


def test_send_message_success(mock_frappe_env):
    """Verify successful message dispatch to Telegram."""
    mock_settings = MagicMock()
    mock_settings.enabled = 1
    mock_frappe_env.get_single.return_value = mock_settings

    client = TelegramBotClient(token="mock_token_123")

    fake_response = MagicMock()
    fake_response.getcode.return_value = 200
    fake_response.read.return_value = b'{"ok": true, "result": {"message_id": 42}}'
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=fake_response):
        success, res = client.send_message(chat_id="12345", text="<b>Test</b>")
        assert success is True
        assert res.get("message_id") == 42


def test_send_message_disabled_in_settings(mock_frappe_env):
    """Verify that send_message stops if Telegram integration is disabled."""
    mock_settings = MagicMock()
    mock_settings.enabled = 0
    mock_frappe_env.get_single.return_value = mock_settings

    client = TelegramBotClient(token="mock_token_123")
    success, res = client.send_message(chat_id="12345", text="Test")
    assert success is False
    assert "disabled" in res.get("error", "").lower()


def test_send_message_api_error_handling(mock_frappe_env):
    """Verify handling of Telegram HTTP 400 Bad Request."""
    mock_settings = MagicMock()
    mock_settings.enabled = 1
    mock_frappe_env.get_single.return_value = mock_settings

    client = TelegramBotClient(token="mock_token_123")

    http_error = urllib.error.HTTPError(
        url="https://api.telegram.org",
        code=400,
        msg="Bad Request",
        hdrs={},
        fp=MagicMock(read=lambda: b'{"ok": false, "error_code": 400, "description": "Chat not found"}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        success, res = client.send_message(chat_id="nonexistent", text="Test")
        assert success is False
        assert res.get("error_code") == 400
        assert "Chat not found" in res.get("description", "")


def test_send_message_timeout_handling(mock_frappe_env):
    """Verify timeout and network error handling without unhandled exceptions."""
    mock_settings = MagicMock()
    mock_settings.enabled = 1
    mock_frappe_env.get_single.return_value = mock_settings

    client = TelegramBotClient(token="mock_token_123")

    url_error = urllib.error.URLError(reason="timed out")

    with patch("urllib.request.urlopen", side_effect=url_error):
        success, res = client.send_message(chat_id="12345", text="Test")
        assert success is False
        assert "timeout" in res.get("error", "").lower()


def test_telegram_bot_client_unconfigured_token(mock_frappe_env):
    """Client with no configured token refuses API calls gracefully."""
    mock_settings = MagicMock()
    mock_settings.get_password = MagicMock(return_value=None)
    mock_settings.bot_token = None
    mock_frappe_env.get_single.return_value = mock_settings

    client = TelegramBotClient(token=None)
    assert client.is_configured is False
    success, res = client.send_message(chat_id="123", text="Hello")
    assert success is False
    assert "not configured" in res.get("error", "").lower()


def test_answer_callback_query_success():
    """Verify answering callback queries sends payload to Telegram."""
    client = TelegramBotClient(token="mock_token_123")
    fake_response = MagicMock()
    fake_response.getcode.return_value = 200
    fake_response.read.return_value = b'{"ok": true, "result": true}'
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=fake_response):
        success, res = client.answer_callback_query(
            callback_query_id="cb_12345",
            text="Done",
            show_alert=True,
        )
        assert success is True
        assert res is True


def test_edit_message_text_success():
    """Verify editing message text dispatches editMessageText request."""
    client = TelegramBotClient(token="mock_token_123")
    fake_response = MagicMock()
    fake_response.getcode.return_value = 200
    fake_response.read.return_value = b'{"ok": true, "result": {"message_id": 99}}'
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=fake_response):
        success, res = client.edit_message_text(
            chat_id="12345",
            message_id=99,
            text="<b>Updated</b>",
            reply_markup={"inline_keyboard": []},
        )
        assert success is True
        assert res.get("message_id") == 99

