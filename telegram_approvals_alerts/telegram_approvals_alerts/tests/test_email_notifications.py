"""
Unit tests for Native SMTP Email Notifications.
Verifies native Frappe sendmail integration, absence of hardcoded credentials, and failure logging.
"""

import os
from unittest.mock import MagicMock, patch

from telegram_approvals_alerts.services.email_service import (
    send_approval_confirmation_email,
    send_approval_request_email,
    send_email_notification,
)


def test_send_email_notification_calls_frappe_sendmail(mock_frappe_env):
    """Verify that send_email_notification properly delegates to frappe.sendmail."""
    success, msg = send_email_notification(
        recipients=["manager@example.com", "director@example.com"],
        subject="Important Alert",
        message="<p>Alert message</p>",
        reference_doctype="Purchase Order",
        reference_name="PO-001",
    )

    assert success is True
    mock_frappe_env.sendmail.assert_called_once()
    kwargs = mock_frappe_env.sendmail.call_args[1]
    assert kwargs["recipients"] == ["manager@example.com", "director@example.com"]
    assert kwargs["subject"] == "Important Alert"
    assert kwargs["reference_doctype"] == "Purchase Order"


def test_send_email_notification_handles_failure(mock_frappe_env):
    """Verify error catching and logging when frappe.sendmail fails."""
    mock_frappe_env.sendmail.side_effect = Exception("SMTP Connection Refused")

    success, msg = send_email_notification(
        recipients=["user@example.com"],
        subject="Test Failure",
        message="Test",
    )

    assert success is False
    assert "SMTP Connection Refused" in msg
    mock_frappe_env.log_error.assert_called_once()


def test_send_approval_confirmation_email(mock_frappe_env):
    """Verify approval confirmation email content and recipient resolution."""
    mock_user = MagicMock()
    mock_user.email = "creator@example.com"
    mock_frappe_env.get_doc.return_value = mock_user

    success, msg = send_approval_confirmation_email(
        doctype="Purchase Order",
        docname="PO-2026-0001",
        action="approve",
        approver_user="boss@example.com",
        owner_user="creator@example.com",
    )

    assert success is True
    mock_frappe_env.sendmail.assert_called_once()
    kwargs = mock_frappe_env.sendmail.call_args[1]
    assert "Approved" in kwargs["subject"]
    assert "creator@example.com" in kwargs["recipients"]
    assert "boss@example.com" in kwargs["message"]


def test_no_hardcoded_smtp_credentials_in_codebase():
    """
    CRITICAL REQUIREMENT:
    Never hardcode SMTP credentials.
    Scan Python source files in telegram_approvals_alerts for hardcoded credentials.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prohibited_keywords = [
        "smtp_server =",
        "smtp_port =",
        "smtp_password =",
        "mail.smtp2go.com",
        "smtp.gmail.com",
        "smtp.office365.com",
        "smtp.sendgrid.net",
    ]

    for root, _, files in os.walk(base_dir):
        if "tests" in root or "__pycache__" in root:
            continue
        for f in files:
            if f.endswith(".py"):
                fpath = os.path.join(root, f)
                with open(fpath, "r", encoding="utf-8") as py_file:
                    content = py_file.read()
                    for keyword in prohibited_keywords:
                        assert keyword.lower() not in content.lower(), (
                            f"Prohibited SMTP credential pattern '{keyword}' found in {fpath}"
                        )


def test_send_email_notification_empty_recipients():
    """Verify that send_email_notification returns error when recipients list is empty."""
    success, msg = send_email_notification(
        recipients=[],
        subject="Test",
        message="Test",
    )
    assert success is False
    assert "no recipients" in msg.lower() or "empty" in msg.lower()

    success, msg = send_email_notification(
        recipients="",
        subject="Test",
        message="Test",
    )
    assert success is False


def test_send_approval_confirmation_email_no_valid_owner(mock_frappe_env):
    """Verify handling when no valid owner email address can be found."""
    mock_frappe_env.get_doc.side_effect = Exception("User not found")

    success, msg = send_approval_confirmation_email(
        doctype="Purchase Order",
        docname="PO-100",
        action="approve",
        approver_user="admin@example.com",
        owner_user="invalid_non_email_user",
    )
    assert success is False
    assert "no valid owner email" in msg.lower()


def test_send_customer_overdue_email_blocked_by_guard(mock_frappe_env):
    """Direct call to send_customer_overdue_email is blocked if setting is disabled."""
    from telegram_approvals_alerts.services.email_service import send_customer_overdue_email

    mock_settings = MagicMock()
    mock_settings.enable_customer_email_reminders = 0
    mock_frappe_env.get_single.return_value = mock_settings

    success, msg = send_customer_overdue_email(
        customer_email="client@example.com",
        customer_name="Client Corp",
        invoice_name="SINV-001",
        due_date="2026-11-20",
        outstanding_amount=500.0,
        currency="USD",
        overdue_days=6,
    )
    assert success is False
    assert "disabled in telegram settings" in msg.lower()


def test_send_approval_request_email(mock_frappe_env):
    """Verify dispatch of internal approval request notification email."""
    success, msg = send_approval_request_email(
        recipients=["manager@example.com"],
        doctype="Purchase Order",
        docname="PO-2026-9999",
        details_html="<p>Order details</p>",
    )
    assert success is True
    mock_frappe_env.sendmail.assert_called_once()
    assert "Approval Required: Purchase Order PO-2026-9999" in mock_frappe_env.sendmail.call_args[1]["subject"]

