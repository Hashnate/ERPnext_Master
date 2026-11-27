"""
Unit tests for Overdue Customer Invoice Reminders Scheduled Task.
Verifies overdue calculation, internal management alerts, and strict customer email guards.
"""

from unittest.mock import MagicMock, patch

from telegram_approvals_alerts.tasks.overdue_reminders import (
    format_overdue_internal_message,
    get_overdue_invoices,
    send_overdue_invoice_reminders,
)


def test_get_overdue_invoices_calculates_overdue_days(mock_frappe_env):
    """Verify that invoices past due_date have correct overdue days calculated."""
    mock_invoices = [
        {
            "name": "ACC-SINV-2026-0001",
            "customer": "CUST-001",
            "customer_name": "Acme Corp",
            "posting_date": "2026-11-01",
            "due_date": "2026-11-15",
            "grand_total": 5000.0,
            "outstanding_amount": 2500.0,
            "currency": "USD",
        }
    ]
    mock_frappe_env.db.sql.return_value = mock_invoices

    invoices = get_overdue_invoices("2026-11-26")
    assert len(invoices) == 1
    # 2026-11-26 minus 2026-11-15 = 11 days overdue
    assert invoices[0]["overdue_days"] == 11
    assert invoices[0]["outstanding_amount"] == 2500.0


def test_format_overdue_internal_message():
    """Verify overdue alert message structure."""
    invoices = [
        {
            "name": "SINV-001",
            "customer": "CUST-1",
            "customer_name": "Alpha Corp",
            "due_date": "2026-11-10",
            "outstanding_amount": 1200.0,
            "currency": "USD",
            "overdue_days": 16,
        }
    ]
    msg = format_overdue_internal_message(invoices, "2026-11-26")
    assert "OVERDUE INVOICE ALERT" in msg
    assert "Alpha Corp" in msg
    assert "SINV-001" in msg
    assert "16 days overdue" in msg
    assert "USD 1,200.00" in msg


def test_customer_email_reminders_disabled_by_default(mock_frappe_env):
    """
    CRITICAL REQUIREMENT:
    Customer email reminders must remain disabled by default.
    Do not send emails directly to customers unless explicitly enabled in Telegram Settings.
    """
    mock_settings = MagicMock()
    mock_settings.enabled = 1
    mock_settings.enable_overdue_reminders = 1
    mock_settings.enable_customer_email_reminders = 0  # Disabled!
    mock_settings.accounts_chat_id = "445566"
    mock_settings.owner_chat_id = "112233"
    mock_frappe_env.get_single.return_value = mock_settings

    mock_frappe_env.db.sql.return_value = [
        {
            "name": "SINV-001",
            "customer": "CUST-001",
            "customer_name": "Test Customer",
            "due_date": "2026-11-10",
            "grand_total": 2000.0,
            "outstanding_amount": 2000.0,
            "currency": "USD",
        }
    ]

    mock_cust = MagicMock()
    mock_cust.email_id = "customer@client.com"
    mock_frappe_env.get_doc.return_value = mock_cust

    with patch("telegram_approvals_alerts.services.email_service.send_customer_overdue_email") as mock_cust_email:
        send_overdue_invoice_reminders()

        # Internal alerts sent
        # Customer email must NEVER be called when disabled
        mock_cust_email.assert_not_called()


def test_customer_email_reminders_sent_when_explicitly_enabled(mock_frappe_env):
    """When enable_customer_email_reminders is 1, reminder emails are sent to customers."""
    mock_settings = MagicMock()
    mock_settings.enabled = 1
    mock_settings.enable_overdue_reminders = 1
    mock_settings.enable_customer_email_reminders = 1  # Explicitly enabled!
    mock_settings.accounts_chat_id = "445566"
    mock_settings.owner_chat_id = None
    mock_frappe_env.get_single.return_value = mock_settings

    mock_frappe_env.db.sql.return_value = [
        {
            "name": "SINV-002",
            "customer": "CUST-002",
            "customer_name": "Beta Ltd",
            "due_date": "2026-11-12",
            "grand_total": 3500.0,
            "outstanding_amount": 3500.0,
            "currency": "USD",
        }
    ]

    mock_cust = MagicMock()
    mock_cust.email_id = "billing@betaltd.com"
    mock_frappe_env.get_doc.return_value = mock_cust

    with patch(
        "telegram_approvals_alerts.services.email_service.send_customer_overdue_email",
        return_value=(True, "Sent"),
    ) as mock_cust_email:
        send_overdue_invoice_reminders()
        mock_cust_email.assert_called_once()
        assert mock_cust_email.call_args[1]["customer_email"] == "billing@betaltd.com"


def test_send_overdue_reminders_no_overdue_invoices(mock_frappe_env):
    """When no invoices are overdue, reminders task exits without sending messages."""
    mock_settings = MagicMock()
    mock_settings.enabled = 1
    mock_settings.enable_overdue_reminders = 1
    mock_frappe_env.get_single.return_value = mock_settings
    mock_frappe_env.db.sql.return_value = []  # No overdue invoices

    with patch("telegram_approvals_alerts.services.telegram_service.TelegramBotClient.send_message") as mock_tg:
        send_overdue_invoice_reminders()
        mock_tg.assert_not_called()
        mock_frappe_env.sendmail.assert_not_called()


def test_send_overdue_reminders_disabled_in_settings(mock_frappe_env):
    """When overdue reminders toggle is disabled, task does not dispatch alerts."""
    mock_settings = MagicMock()
    mock_settings.enabled = 1
    mock_settings.enable_overdue_reminders = 0  # Disabled!
    mock_frappe_env.get_single.return_value = mock_settings

    with patch("telegram_approvals_alerts.services.telegram_service.TelegramBotClient.send_message") as mock_tg:
        send_overdue_invoice_reminders()
        mock_tg.assert_not_called()

