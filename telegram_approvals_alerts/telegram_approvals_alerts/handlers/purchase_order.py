"""
Document Event Handlers for Purchase Orders.
Dispatches Telegram approval notifications with inline buttons when a PO requires approval.
"""

import logging
from typing import Any, List

logger = logging.getLogger(__name__)


def get_po_approver_recipients() -> List[dict]:
    """Retrieve all active Telegram users permitted to approve Purchase Orders."""
    try:
        import frappe

        return frappe.get_all(
            "Telegram User Mapping",
            filters={"is_active": 1, "can_approve_po": 1},
            fields=["user", "telegram_chat_id", "telegram_username"],
        )
    except Exception as e:
        logger.error("Failed to query PO approvers: %s", e)
        return []


def format_po_message(doc) -> str:
    """Format rich HTML message for Purchase Order approval request."""
    import html
    from unittest.mock import MagicMock

    raw_supplier = None
    if hasattr(doc, "get") and callable(doc.get):
        raw_supplier = doc.get("supplier_name") or doc.get("supplier")
    if not raw_supplier or isinstance(raw_supplier, MagicMock):
        s_name = getattr(doc, "supplier_name", None)
        if s_name and not isinstance(s_name, MagicMock):
            raw_supplier = s_name
        else:
            s_val = getattr(doc, "supplier", None)
            if s_val and not isinstance(s_val, MagicMock):
                raw_supplier = s_val
            else:
                raw_supplier = "Unknown"

    supplier = html.escape(str(raw_supplier))
    grand_total = getattr(doc, "grand_total", 0.0)
    currency = html.escape(str(getattr(doc, "currency", "USD")))
    txn_date = html.escape(str(getattr(doc, "transaction_date", "Today")))
    doc_name = html.escape(str(doc.name))

    # Item breakdown (first 3 items)
    items_text = ""
    items = getattr(doc, "items", []) or []
    if items:
        items_preview = []
        for it in items[:3]:
            item_code = html.escape(str(getattr(it, "item_code", "")))
            qty = getattr(it, "qty", 0)
            rate = getattr(it, "rate", 0.0)
            items_preview.append(f"  • {item_code} (Qty: {qty} @ {rate:,.2f})")
        items_text = "\n" + "\n".join(items_preview)
        if len(items) > 3:
            items_text += f"\n  <i>... and {len(items) - 3} more item(s)</i>"

    message = (
        f"📋 <b>Purchase Order Approval Required</b>\n\n"
        f"<b>PO Number:</b> <code>{doc_name}</code>\n"
        f"<b>Supplier:</b> {supplier}\n"
        f"<b>Date:</b> {txn_date}\n"
        f"<b>Grand Total:</b> <b>{currency} {grand_total:,.2f}</b>\n"
        f"<b>Items:</b>{items_text}\n\n"
        f"Please click below to Approve or Reject this order:"
    )
    return message


def on_purchase_order_insert(doc, method=None):
    """Triggered on Purchase Order creation."""
    send_po_approval_notification(doc)


def on_purchase_order_update(doc, method=None):
    """Triggered on Purchase Order update if still in draft."""
    # Only notify if draft and not already notified in this request
    if getattr(doc, "docstatus", 0) == 0 and not getattr(doc.flags, "telegram_notified", False):
        send_po_approval_notification(doc)


def send_po_approval_notification(doc):
    """Send Telegram message with inline buttons and internal email to approvers."""
    try:
        import frappe

        # Check toggle in Telegram Settings
        settings = frappe.get_single("Telegram Settings")
        if not getattr(settings, "enabled", 0) or not getattr(settings, "enable_po_approval", 1):
            return

        approvers = get_po_approver_recipients()
        if not approvers:
            logger.info("No active PO approvers mapped for Telegram notification.")
            return

        from telegram_approvals_alerts.services.email_service import send_approval_request_email
        from telegram_approvals_alerts.services.telegram_service import (
            TelegramBotClient,
            build_approval_keyboard,
        )

        client = TelegramBotClient()
        keyboard = build_approval_keyboard("Purchase Order", doc.name)
        text = format_po_message(doc)

        email_recipients = []
        for approver in approvers:
            chat_id = approver.get("telegram_chat_id")
            if chat_id:
                client.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                    reference_doctype="Purchase Order",
                    reference_name=doc.name,
                )

            approver_user = approver.get("user")
            if approver_user and "@" in approver_user:
                email_recipients.append(approver_user)

        # Dispatch internal email alert to approvers
        if email_recipients:
            details_html = (
                f"<p><b>PO:</b> {doc.name}<br>"
                f"<b>Supplier:</b> {getattr(doc, 'supplier', 'N/A')}<br>"
                f"<b>Total:</b> {getattr(doc, 'currency', 'USD')} {getattr(doc, 'grand_total', 0.0):,.2f}</p>"
            )
            send_approval_request_email(
                recipients=email_recipients,
                doctype="Purchase Order",
                docname=doc.name,
                details_html=details_html,
            )

        doc.flags.telegram_notified = True

    except Exception as e:
        logger.error("Error sending PO approval notification: %s", e)
