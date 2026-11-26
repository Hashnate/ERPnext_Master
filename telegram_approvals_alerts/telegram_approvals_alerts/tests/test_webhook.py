"""
Unit tests for Telegram Webhook API Endpoint.
Verifies webhook secret validation, callback query parsing, duplicate button clicks, and command routing.
"""

from unittest.mock import MagicMock, patch

from telegram_approvals_alerts.api.webhook import (
    handle_callback_query,
    handle_text_message,
    parse_callback_data,
    telegram_webhook,
    validate_secret_token,
)


def test_validate_secret_token():
    """Verify constant-time secret validation."""
    assert validate_secret_token("secret123", "secret123") is True
    assert validate_secret_token("secret123", "wrong_secret") is False
    assert validate_secret_token("secret123", None) is False
    # If no secret is configured, passes
    assert validate_secret_token(None, None) is True
    assert validate_secret_token("", None) is True


def test_parse_callback_data():
    """Verify parsing and normalization of callback queries."""
    action, dt, dn = parse_callback_data("app:PO:PO-2026-0001")
    assert action == "approve"
    assert dt == "Purchase Order"
    assert dn == "PO-2026-0001"

    action, dt, dn = parse_callback_data("rej:LA:LAP-0099")
    assert action == "reject"
    assert dt == "Leave Application"
    assert dn == "LAP-0099"

    action, dt, dn = parse_callback_data("approve:Expense Claim:EXP-1234")
    assert action == "approve"
    assert dt == "Expense Claim"
    assert dn == "EXP-1234"

    # Malformed data
    action, dt, dn = parse_callback_data("invalid_data")
    assert action is None


def test_webhook_secret_header_missing_returns_401(mock_frappe_env):
    """Webhook rejects incoming request if configured secret is missing from headers."""
    mock_settings = MagicMock()
    mock_settings.get_password = MagicMock(return_value="my_expected_secret")
    mock_frappe_env.get_single.return_value = mock_settings
    mock_frappe_env.get_request_header.return_value = None

    res = telegram_webhook()
    assert res.get("status") == "error"
    assert mock_frappe_env.response.get("http_status_code") == 401


def test_webhook_secret_header_valid_passes(mock_frappe_env):
    """Webhook accepts request when header token matches configured secret."""
    mock_settings = MagicMock()
    mock_settings.get_password = MagicMock(return_value="my_expected_secret")
    mock_frappe_env.get_single.return_value = mock_settings
    mock_frappe_env.get_request_header.return_value = "my_expected_secret"
    mock_frappe_env.request.get_json.return_value = {}

    res = telegram_webhook()
    assert res.get("status") == "ok"


def test_handle_text_message_start_command(mock_frappe_env):
    """Verify /start command sends back chat ID."""
    client = MagicMock()
    msg = {
        "chat": {"id": 123456789},
        "from": {"first_name": "TestUser"},
        "text": "/start",
    }
    res = handle_text_message(msg, client)
    assert res.get("status") == "handled_start"
    client.send_message.assert_called_once()
    assert "123456789" in client.send_message.call_args[1]["text"]


def test_handle_callback_query_duplicate_click(mock_frappe_env):
    """Verify handling when an already approved document button is clicked again."""
    client = MagicMock()
    callback_query = {
        "id": "cb_999",
        "from": {"id": 12345, "username": "approver"},
        "data": "app:PO:PO-0001",
        "message": {"chat": {"id": 12345}, "message_id": 10, "text": "PO Request"},
    }

    with patch(
        "telegram_approvals_alerts.services.approval_service.process_approval_action",
        return_value={
            "success": False,
            "status_code": "ALREADY_PROCESSED",
            "message": "Purchase Order PO-0001 has already been approved / submitted.",
        },
    ):
        res = handle_callback_query(callback_query, client)
        client.answer_callback_query.assert_called_once()
        assert client.answer_callback_query.call_args[1]["show_alert"] is True
        assert "already" in client.answer_callback_query.call_args[1]["text"].lower()
        # Edits message to disable buttons
        client.edit_message_text.assert_called_once()
