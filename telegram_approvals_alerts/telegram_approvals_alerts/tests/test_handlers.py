"""
Unit tests for Document Event Handlers.
Verifies event hooks for Purchase Orders, Leave Applications, and Expense Claims.
"""

from unittest.mock import MagicMock, patch

from telegram_approvals_alerts.handlers.expense_claim import (
    format_expense_message,
    on_expense_claim_insert,
)
from telegram_approvals_alerts.handlers.leave_application import (
    format_leave_message,
    on_leave_application_insert,
)
from telegram_approvals_alerts.handlers.purchase_order import (
    format_po_message,
    on_purchase_order_insert,
    on_purchase_order_update,
)


def test_po_handlers_dispatch_notifications(mock_frappe_env):
    """Verify PO insert triggers Telegram message with inline buttons and email."""
    mock_settings = MagicMock()
    mock_settings.enabled = 1
    mock_settings.enable_po_approval = 1
    mock_frappe_env.get_single.return_value = mock_settings

    mock_frappe_env.get_all.return_value = [
        {"user": "buyer@example.com", "telegram_chat_id": "112233"}
    ]

    doc = MagicMock()
    doc.docstatus = 0
    doc.name = "PO-2026-0005"
    doc.supplier = "Global Corp"
    doc.grand_total = 15000.0
    doc.currency = "USD"
    doc.transaction_date = "2026-11-26"
    doc.items = []
    doc.flags = MagicMock()
    doc.flags.telegram_notified = False

    with patch("telegram_approvals_alerts.services.telegram_service.TelegramBotClient.send_message") as mock_tg, \
         patch("telegram_approvals_alerts.services.email_service.send_approval_request_email") as mock_email:
        on_purchase_order_insert(doc)

        mock_tg.assert_called_once()
        assert mock_tg.call_args[1]["chat_id"] == "112233"
        assert "Purchase Order Approval Required" in mock_tg.call_args[1]["text"]
        assert "inline_keyboard" in mock_tg.call_args[1]["reply_markup"]

        mock_email.assert_called_once()
        assert "buyer@example.com" in mock_email.call_args[1]["recipients"]


def test_leave_application_handler_dispatch(mock_frappe_env):
    """Verify Leave Application insert notifies assigned approver."""
    mock_settings = MagicMock()
    mock_settings.enabled = 1
    mock_settings.enable_leave_approval = 1
    mock_frappe_env.get_single.return_value = mock_settings

    mock_frappe_env.get_all.return_value = [
        {"user": "hr_lead@example.com", "telegram_chat_id": "998811"}
    ]

    doc = MagicMock()
    doc.docstatus = 0
    doc.status = "Open"
    doc.name = "LAP-00123"
    doc.employee_name = "Jane Doe"
    doc.leave_type = "Sick Leave"
    doc.from_date = "2026-12-01"
    doc.to_date = "2026-12-03"
    doc.total_leave_days = 3
    doc.leave_approver = "hr_lead@example.com"
    doc.flags = MagicMock()

    with patch("telegram_approvals_alerts.services.telegram_service.TelegramBotClient.send_message") as mock_tg:
        on_leave_application_insert(doc)
        mock_tg.assert_called_once()
        assert mock_tg.call_args[1]["chat_id"] == "998811"
        assert "Leave Application Approval Required" in mock_tg.call_args[1]["text"]


def test_expense_claim_handler_dispatch(mock_frappe_env):
    """Verify Expense Claim insert notifies assigned approver."""
    mock_settings = MagicMock()
    mock_settings.enabled = 1
    mock_settings.enable_expense_approval = 1
    mock_frappe_env.get_single.return_value = mock_settings

    mock_frappe_env.get_all.return_value = [
        {"user": "finance_mgr@example.com", "telegram_chat_id": "443322"}
    ]

    doc = MagicMock()
    doc.docstatus = 0
    doc.approval_status = "Draft"
    doc.name = "EXP-9001"
    doc.employee_name = "John Smith"
    doc.total_claimed_amount = 750.0
    doc.remark = "Travel reimbursement"
    doc.expense_approver = "finance_mgr@example.com"
    doc.flags = MagicMock()

    with patch("telegram_approvals_alerts.services.telegram_service.TelegramBotClient.send_message") as mock_tg:
        on_expense_claim_insert(doc)
        mock_tg.assert_called_once()
        assert mock_tg.call_args[1]["chat_id"] == "443322"
        assert "Expense Claim Approval Required" in mock_tg.call_args[1]["text"]


def test_format_po_message_escapes_html_entities():
    """Verify that supplier and item names with '&' or '<' are escaped to prevent Telegram HTML errors."""
    doc = MagicMock()
    doc.name = "PO-2026-TEST"
    doc.supplier = "Tom & Jerry <Supplies>"
    doc.grand_total = 1200.0
    doc.currency = "USD"
    doc.transaction_date = "2026-11-26"
    doc.items = [
        MagicMock(item_code="Widgets <A&B>", qty=2, rate=600.0)
    ]
    msg = format_po_message(doc)

    assert "Tom &amp; Jerry &lt;Supplies&gt;" in msg
    assert "Widgets &lt;A&amp;B&gt;" in msg
    # Verify no raw unescaped unclosed tags that could corrupt HTML
    assert "<Supplies>" not in msg


def test_format_leave_message_escapes_html_entities():
    """Verify that employee name and reason with HTML special characters are safely escaped."""
    doc = MagicMock()
    doc.name = "LAP-002"
    doc.employee_name = "Jane & Joe"
    doc.leave_type = "Medical <Emergency>"
    doc.from_date = "2026-12-01"
    doc.to_date = "2026-12-02"
    doc.total_leave_days = 2
    doc.description = "Doctor & Dentist <visit>"
    msg = format_leave_message(doc)

    assert "Jane &amp; Joe" in msg
    assert "Medical &lt;Emergency&gt;" in msg
    assert "Doctor &amp; Dentist &lt;visit&gt;" in msg


def test_format_expense_message_escapes_html_entities():
    """Verify that employee name and remarks with HTML special characters are safely escaped."""
    doc = MagicMock()
    doc.name = "EXP-003"
    doc.employee_name = "Bob & Alice"
    doc.total_claimed_amount = 350.0
    doc.remark = "Travel & Food <team event>"
    msg = format_expense_message(doc)

    assert "Bob &amp; Alice" in msg
    assert "Travel &amp; Food &lt;team event&gt;" in msg


def test_on_purchase_order_update_skips_if_not_draft(mock_frappe_env):
    """When a PO is updated but docstatus is not 0, notification is suppressed."""
    doc = MagicMock()
    doc.docstatus = 1  # Already submitted
    doc.flags = MagicMock()
    doc.flags.telegram_notified = False

    with patch("telegram_approvals_alerts.handlers.purchase_order.send_po_approval_notification") as mock_notify:
        on_purchase_order_update(doc)
        mock_notify.assert_not_called()


def test_send_po_approval_notification_disabled_in_settings(mock_frappe_env):
    """When PO approval toggle is disabled in Telegram Settings, notifications are not sent."""
    from telegram_approvals_alerts.handlers.purchase_order import send_po_approval_notification

    mock_settings = MagicMock()
    mock_settings.enabled = 1
    mock_settings.enable_po_approval = 0
    mock_frappe_env.get_single.return_value = mock_settings

    doc = MagicMock()
    doc.docstatus = 0
    doc.name = "PO-001"
    doc.flags = MagicMock()

    with patch("telegram_approvals_alerts.services.telegram_service.TelegramBotClient.send_message") as mock_tg:
        send_po_approval_notification(doc)
        mock_tg.assert_not_called()


def test_send_leave_approval_notification_skips_if_not_open(mock_frappe_env):
    """When Leave Application is not in Open status, notification is skipped."""
    from telegram_approvals_alerts.handlers.leave_application import send_leave_approval_notification

    doc = MagicMock()
    doc.docstatus = 1
    doc.status = "Approved"
    doc.flags = MagicMock()

    with patch("telegram_approvals_alerts.services.telegram_service.TelegramBotClient.send_message") as mock_tg:
        send_leave_approval_notification(doc)
        mock_tg.assert_not_called()


def test_send_expense_approval_notification_skips_if_not_draft(mock_frappe_env):
    """When Expense Claim is not in Draft status, notification is skipped."""
    from telegram_approvals_alerts.handlers.expense_claim import send_expense_approval_notification

    doc = MagicMock()
    doc.docstatus = 1
    doc.approval_status = "Approved"
    doc.flags = MagicMock()

    with patch("telegram_approvals_alerts.services.telegram_service.TelegramBotClient.send_message") as mock_tg:
        send_expense_approval_notification(doc)
        mock_tg.assert_not_called()


def test_doctype_settings_validation(mock_frappe_env):
    """TelegramSettings.validate automatically populates the webhook_url."""
    from telegram_approvals_alerts.doctype.telegram_settings.telegram_settings import TelegramSettings

    settings = TelegramSettings("Telegram Settings")
    settings.enabled = 1
    settings.validate()
    assert settings.webhook_url == "https://erp.example.com/api/method/telegram_approvals_alerts.api.webhook.telegram_webhook"


def test_doctype_user_mapping_validation():
    """TelegramUserMapping.validate strips whitespace from telegram_chat_id."""
    from telegram_approvals_alerts.doctype.telegram_user_mapping.telegram_user_mapping import TelegramUserMapping

    mapping = TelegramUserMapping("Telegram User Mapping")
    mapping.telegram_chat_id = "   987654321   "
    mapping.validate()
    assert mapping.telegram_chat_id == "987654321"


