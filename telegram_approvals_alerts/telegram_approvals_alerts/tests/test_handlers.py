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
