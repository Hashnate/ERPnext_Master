"""
Document Event Handlers for Leave Applications.
Dispatches Telegram approval notifications with inline buttons when a Leave Application is created.
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


def get_leave_approver_recipients(assigned_approver: str = None) -> List[dict]:
    """
    Find active Telegram approvers.
    If assigned_approver is specified and mapped, returns that approver specifically.
    Otherwise returns all active users with can_approve_leave = 1.
    """
    try:
        import frappe

        if assigned_approver:
            direct_mapped = frappe.get_all(
                "Telegram User Mapping",
                filters={"user": assigned_approver, "is_active": 1, "can_approve_leave": 1},
                fields=["user", "telegram_chat_id", "telegram_username"],
            )
            if direct_mapped:
                return direct_mapped

        # Fallback to all leave approvers
        return frappe.get_all(
            "Telegram User Mapping",
            filters={"is_active": 1, "can_approve_leave": 1},
            fields=["user", "telegram_chat_id", "telegram_username"],
        )
    except Exception as e:
        logger.error("Failed to query Leave approvers: %s", e)
        return []


def format_leave_message(doc) -> str:
    """Format rich HTML message for Leave Application approval request."""
    employee_name = (
        getattr(doc, "employee_name", None)
        or getattr(doc, "employee", "Unknown Employee")
    )
    leave_type = getattr(doc, "leave_type", "Leave")
    from_date = getattr(doc, "from_date", "")
    to_date = getattr(doc, "to_date", "")
    total_days = getattr(doc, "total_leave_days", 1)
    reason = getattr(doc, "description", "") or "No reason provided."

    message = (
        f"🏖️ <b>Leave Application Approval Required</b>\n\n"
        f"<b>Application:</b> <code>{doc.name}</code>\n"
        f"<b>Employee:</b> {employee_name}\n"
        f"<b>Leave Type:</b> {leave_type}\n"
        f"<b>Period:</b> {from_date} to {to_date} (<b>{total_days} day(s)</b>)\n"
        f"<b>Reason:</b> <i>{reason}</i>\n\n"
        f"Please click below to Approve or Reject this request:"
    )
    return message


def on_leave_application_insert(doc, method=None):
    """Triggered on Leave Application creation."""
    send_leave_approval_notification(doc)


def send_leave_approval_notification(doc):
    """Send Telegram message with inline buttons and internal email to approvers."""
    try:
        import frappe

        # Only notify if in Open / Draft status
        if getattr(doc, "docstatus", 0) != 0 or getattr(doc, "status", "Open") != "Open":
            return

        settings = frappe.get_single("Telegram Settings")
        if not getattr(settings, "enabled", 0) or not getattr(settings, "enable_leave_approval", 1):
            return

        assigned_approver = getattr(doc, "leave_approver", None)
        approvers = get_leave_approver_recipients(assigned_approver)
        if not approvers:
            logger.info("No active Leave approvers mapped for Telegram notification.")
            return

        from telegram_approvals_alerts.services.email_service import send_approval_request_email
        from telegram_approvals_alerts.services.telegram_service import (
            TelegramBotClient,
            build_approval_keyboard,
        )

        client = TelegramBotClient()
        keyboard = build_approval_keyboard("Leave Application", doc.name)
        text = format_leave_message(doc)

        email_recipients = []
        for approver in approvers:
            chat_id = approver.get("telegram_chat_id")
            if chat_id:
                client.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                    reference_doctype="Leave Application",
                    reference_name=doc.name,
                )

            approver_user = approver.get("user")
            if approver_user and "@" in approver_user:
                email_recipients.append(approver_user)

        if email_recipients:
            details_html = (
                f"<p><b>Application:</b> {doc.name}<br>"
                f"<b>Employee:</b> {getattr(doc, 'employee_name', getattr(doc, 'employee', 'N/A'))}<br>"
                f"<b>Leave Type:</b> {getattr(doc, 'leave_type', 'N/A')}<br>"
                f"<b>Days:</b> {getattr(doc, 'total_leave_days', 1)}</p>"
            )
            send_approval_request_email(
                recipients=email_recipients,
                doctype="Leave Application",
                docname=doc.name,
                details_html=details_html,
            )

        doc.flags.telegram_notified = True

    except Exception as e:
        logger.error("Error sending Leave approval notification: %s", e)
