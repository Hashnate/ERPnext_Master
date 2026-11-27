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


def test_webhook_secret_header_invalid_returns_401(mock_frappe_env):
    """Webhook rejects incoming request with HTTP 401 when header token does not match."""
    mock_settings = MagicMock()
    mock_settings.get_password = MagicMock(return_value="correct_secret_123")
    mock_frappe_env.get_single.return_value = mock_settings
    mock_frappe_env.get_request_header.return_value = "wrong_attacker_secret"

    res = telegram_webhook()
    assert res.get("status") == "error"
    assert res.get("message") == "Unauthorized"
    assert mock_frappe_env.response.get("http_status_code") == 401


def test_webhook_secret_header_case_insensitive(mock_frappe_env):
    """Webhook validates secret header even if header casing differs."""
    mock_settings = MagicMock()
    mock_settings.get_password = MagicMock(return_value="my_expected_secret")
    mock_frappe_env.get_single.return_value = mock_settings
    mock_frappe_env.get_request_header.return_value = None
    mock_frappe_env.request.headers = {"x-telegram-bot-api-secret-token": "my_expected_secret"}
    mock_frappe_env.request.get_json.return_value = {}

    res = telegram_webhook()
    assert res.get("status") == "ok"


def test_handle_callback_query_invalid_payload(mock_frappe_env):
    """Malformed callback query payload notifies user and returns ignored status."""
    client = MagicMock()
    callback_query = {
        "id": "cb_invalid",
        "from": {"id": 12345, "username": "tester"},
        "data": "invalid_payload_without_colons",
        "message": {"chat": {"id": 12345}, "message_id": 11, "text": "Something"},
    }

    res = handle_callback_query(callback_query, client)
    assert res.get("status") == "ignored"
    client.answer_callback_query.assert_called_once()
    assert "invalid" in client.answer_callback_query.call_args[1]["text"].lower()


def test_handle_text_message_status_command_active(mock_frappe_env):
    """Verify /status command displays mapped user details and approval permissions."""
    client = MagicMock()
    msg = {
        "chat": {"id": 7890},
        "from": {"first_name": "Alice"},
        "text": "/status",
    }

    mock_frappe_env.get_all.return_value = [{
        "user": "alice@example.com",
        "telegram_chat_id": "7890",
        "can_approve_po": 1,
        "can_approve_leave": 1,
        "can_approve_expense": 0,
        "receive_daily_summary": 1,
    }]

    res = handle_text_message(msg, client)
    assert res.get("status") == "handled_status"
    client.send_message.assert_called_once()
    reply_text = client.send_message.call_args[1]["text"]
    assert "alice@example.com" in reply_text
    assert "Purchase Orders: ✅ Yes" in reply_text
    assert "Expense Claims: ❌ No" in reply_text


def test_handle_text_message_help_command():
    """Verify /help command returns list of available bot commands."""
    client = MagicMock()
    msg = {
        "chat": {"id": 12345},
        "from": {"first_name": "Bob"},
        "text": "/help",
    }

    res = handle_text_message(msg, client)
    assert res.get("status") == "handled_help"
    client.send_message.assert_called_once()
    assert "/start" in client.send_message.call_args[1]["text"]
    assert "/status" in client.send_message.call_args[1]["text"]

