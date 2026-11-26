"""
Native Frappe SMTP Email Service for Telegram Approvals and Alerts.
Leverages ERPNext's native frappe.sendmail and Email Account configurations.
Never hardcodes SMTP credentials.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


def send_email_notification(
    recipients: Union[str, List[str]],
    subject: str,
    message: str,
    reference_doctype: Optional[str] = None,
    reference_name: Optional[str] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    now: bool = False,
) -> Tuple[bool, str]:
    """
    Send an email using Frappe's native sendmail mechanism.
    Supports ERPNext Email Account configuration without hardcoded credentials.
    """
    if not recipients:
        return False, "No recipients specified."

    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.split(",") if r.strip()]

    if not recipients:
        return False, "Recipients list is empty."

    try:
        import frappe

        # Ensure active outgoing email account exists or warn
        frappe.sendmail(
            recipients=recipients,
            subject=subject,
            message=message,
            reference_doctype=reference_doctype,
            reference_name=reference_name,
            attachments=attachments,
            now=now,
        )

        logger.info("Email queued successfully for: %s with subject: %s", recipients, subject)
        return True, "Email successfully queued via Frappe Mail Queue."

    except Exception as e:
        error_msg = f"Failed to send email via Frappe sendmail: {str(e)}"
        logger.error(error_msg)
        try:
            import frappe
            frappe.log_error(error_msg, "Telegram Approvals Email Service")
        except Exception:
            pass
        return False, error_msg


def send_approval_confirmation_email(
    doctype: str,
    docname: str,
    action: str,
    approver_user: str,
    owner_user: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Send dual-channel internal email notification upon document approval or rejection.
    """
    recipients = []
    if owner_user and "@" in owner_user:
        recipients.append(owner_user)

    if not recipients:
        try:
            import frappe
            if owner_user:
                user_doc = frappe.get_doc("User", owner_user)
                if getattr(user_doc, "email", None):
                    recipients.append(user_doc.email)
        except Exception:
            pass

    if not recipients:
        return False, "No valid owner email found."

    status_str = "Approved" if action.lower() == "approve" else "Rejected"
    status_color = "#28a745" if action.lower() == "approve" else "#dc3545"

    subject = f"[{status_str}] {doctype} {docname} updated via Telegram"
    message = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: {status_color};">Document {status_str}</h2>
        <p>Your <b>{doctype}</b> <code>{docname}</code> has been <b>{status_str.lower()}</b> via Telegram.</p>
        <table style="width: 100%; border-collapse: collapse; margin-top: 15px;">
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd; background: #f9f9f9; width: 30%;"><b>Document:</b></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{doctype} - {docname}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd; background: #f9f9f9;"><b>Action Taken:</b></td>
                <td style="padding: 8px; border: 1px solid #ddd; color: {status_color}; font-weight: bold;">{status_str}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd; background: #f9f9f9;"><b>Approver:</b></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{approver_user}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd; background: #f9f9f9;"><b>Channel:</b></td>
                <td style="padding: 8px; border: 1px solid #ddd;">Telegram Bot Approval Engine</td>
            </tr>
        </table>
        <p style="margin-top: 20px; font-size: 12px; color: #888;">
            This is an automated dual-channel notification from ERPNext Telegram Approvals & Alerts.
        </p>
    </div>
    """

    return send_email_notification(
        recipients=recipients,
        subject=subject,
        message=message,
        reference_doctype=doctype,
        reference_name=docname,
    )


def send_approval_request_email(
    recipients: List[str],
    doctype: str,
    docname: str,
    details_html: str,
) -> Tuple[bool, str]:
    """Send internal email alert when a document requires approval."""
    subject = f"Approval Required: {doctype} {docname}"
    message = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #007bff;">Approval Required</h2>
        <p>A new <b>{doctype}</b> requires your review and approval:</p>
        {details_html}
        <p style="margin-top: 15px;">
            You can approve or reject this directly from your Telegram app or by logging into ERPNext.
        </p>
    </div>
    """
    return send_email_notification(
        recipients=recipients,
        subject=subject,
        message=message,
        reference_doctype=doctype,
        reference_name=docname,
    )


def send_customer_overdue_email(
    customer_email: str,
    customer_name: str,
    invoice_name: str,
    due_date: str,
    outstanding_amount: float,
    currency: str,
    overdue_days: int,
) -> Tuple[bool, str]:
    """
    Send polite overdue payment reminder directly to a customer.
    IMPORTANT: Must ONLY be called when Telegram Settings.enable_customer_email_reminders is 1.
    """
    try:
        import frappe
        settings = frappe.get_single("Telegram Settings")
        if not getattr(settings, "enable_customer_email_reminders", 0):
            return False, "Customer email reminders are disabled in Telegram Settings."
    except Exception:
        return False, "Could not verify customer email reminder toggle."

    subject = f"Friendly Payment Reminder: Invoice {invoice_name} is Overdue"
    message = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <p>Dear {customer_name},</p>
        <p>
            This is a friendly reminder that invoice <b>{invoice_name}</b>, which was due on <b>{due_date}</b>,
            currently has an outstanding balance of <b>{currency} {outstanding_amount:,.2f}</b> ({overdue_days} days overdue).
        </p>
        <p>
            If payment has already been sent, please disregard this notice. Otherwise, please arrange for payment at your earliest convenience.
        </p>
        <p>Thank you for your business.</p>
    </div>
    """

    return send_email_notification(
        recipients=[customer_email],
        subject=subject,
        message=message,
        reference_doctype="Sales Invoice",
        reference_name=invoice_name,
    )
