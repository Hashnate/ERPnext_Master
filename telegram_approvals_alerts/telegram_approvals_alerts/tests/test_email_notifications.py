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
