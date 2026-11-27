"""
Daily Business Summary Scheduled Task.
Aggregates sales, collections, purchases, and pending approvals for the business owner.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def get_daily_metrics(today_str: str) -> Dict[str, Any]:
    """Calculate core business metrics for the given date."""
    import frappe

    metrics = {
        "date": today_str,
        "sales_count": 0,
        "sales_total": 0.0,
        "payments_count": 0,
        "payments_total": 0.0,
        "po_count": 0,
        "po_total": 0.0,
        "pending_po": 0,
        "pending_leaves": 0,
        "pending_expenses": 0,
        "currency": "USD",
    }

    try:
        # 1. Sales Invoices
        sales = frappe.db.sql(
            """
            SELECT COUNT(name) as cnt, COALESCE(SUM(grand_total), 0) as total
            FROM `tabSales Invoice`
            WHERE docstatus = 1 AND posting_date = %s
            """,
            (today_str,),
            as_dict=True,
        )
        if sales:
            metrics["sales_count"] = sales[0].get("cnt", 0)
            metrics["sales_total"] = float(sales[0].get("total", 0.0))

        # 2. Payments Collected
        payments = frappe.db.sql(
            """
            SELECT COUNT(name) as cnt, COALESCE(SUM(paid_amount), 0) as total
            FROM `tabPayment Entry`
            WHERE docstatus = 1 AND posting_date = %s AND payment_type = 'Receive'
            """,
            (today_str,),
            as_dict=True,
        )
        if payments:
            metrics["payments_count"] = payments[0].get("cnt", 0)
            metrics["payments_total"] = float(payments[0].get("total", 0.0))

        # 3. Purchase Orders
        pos = frappe.db.sql(
            """
            SELECT COUNT(name) as cnt, COALESCE(SUM(grand_total), 0) as total
            FROM `tabPurchase Order`
            WHERE docstatus = 1 AND transaction_date = %s
            """,
            (today_str,),
            as_dict=True,
        )
        if pos:
            metrics["po_count"] = pos[0].get("cnt", 0)
            metrics["po_total"] = float(pos[0].get("total", 0.0))

        # 4. Pending Approvals
        metrics["pending_po"] = frappe.db.count("Purchase Order", filters={"docstatus": 0})
        metrics["pending_leaves"] = frappe.db.count(
            "Leave Application", filters={"docstatus": 0, "status": "Open"}
        )
        metrics["pending_expenses"] = frappe.db.count(
            "Expense Claim", filters={"docstatus": 0, "approval_status": "Draft"}
        )

        # Get default company currency
        default_company = frappe.defaults.get_user_default("company")
        if default_company:
            comp_curr = frappe.db.get_value("Company", default_company, "default_currency")
            if comp_curr:
                metrics["currency"] = comp_curr

    except Exception as e:
        logger.error("Error computing daily metrics: %s", e)

    return metrics


def format_summary_message(metrics: Dict[str, Any]) -> str:
    """Format daily digest into rich HTML message for Telegram."""
    import html

    curr = html.escape(str(metrics.get("currency", "USD")))
    date_str = html.escape(str(metrics.get("date", "")))
    message = (
        f"📊 <b>DAILY BUSINESS SUMMARY</b>\n"
        f"📅 <b>Date:</b> {date_str}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>FINANCIAL PERFORMANCE:</b>\n"
        f"• <b>Sales Invoices:</b> {metrics.get('sales_count')} | <b>{curr} {metrics.get('sales_total', 0.0):,.2f}</b>\n"
        f"• <b>Collections:</b> {metrics.get('payments_count')} | <b>{curr} {metrics.get('payments_total', 0.0):,.2f}</b>\n"
        f"• <b>Purchase Orders:</b> {metrics.get('po_count')} | <b>{curr} {metrics.get('po_total', 0.0):,.2f}</b>\n\n"
        f"⏳ <b>PENDING APPROVALS:</b>\n"
        f"• Purchase Orders: <b>{metrics.get('pending_po')}</b>\n"
        f"• Leave Applications: <b>{metrics.get('pending_leaves')}</b>\n"
        f"• Expense Claims: <b>{metrics.get('pending_expenses')}</b>\n\n"
        f"<i>Automated daily report generated from ERPNext.</i>"
    )
    return message


def get_summary_recipients() -> List[str]:
    """Retrieve chat IDs for owner and mapped summary recipients."""
    recipients = set()
    try:
        import frappe

        settings = frappe.get_single("Telegram Settings")
        owner_id = getattr(settings, "owner_chat_id", None)
        if owner_id:
            recipients.add(str(owner_id).strip())

        mapped = frappe.get_all(
            "Telegram User Mapping",
            filters={"is_active": 1, "receive_daily_summary": 1},
            fields=["telegram_chat_id"],
        )
        for m in mapped:
            cid = m.get("telegram_chat_id")
            if cid:
                recipients.add(str(cid).strip())

    except Exception as e:
        logger.error("Error querying summary recipients: %s", e)

    return list(recipients)


def send_daily_summary():
    """Scheduled task function to build and dispatch Daily Business Summary."""
    try:
        import frappe

        settings = frappe.get_single("Telegram Settings")
        if not getattr(settings, "enabled", 0) or not getattr(settings, "enable_daily_summary", 1):
            logger.info("Daily summary is disabled in Telegram Settings.")
            return

        today_str = frappe.utils.nowdate()
        metrics = get_daily_metrics(today_str)
        text = format_summary_message(metrics)

        recipients = get_summary_recipients()
        if not recipients:
            logger.info("No recipients configured for Daily Business Summary.")
            return

        from telegram_approvals_alerts.services.email_service import send_email_notification
        from telegram_approvals_alerts.services.telegram_service import (
            TelegramBotClient,
            log_telegram_event,
        )

        client = TelegramBotClient()

        # Send via Telegram
        for chat_id in recipients:
            client.send_message(
                chat_id=chat_id,
                text=text,
                reference_doctype="Telegram Settings",
                reference_name="Daily Summary",
            )

        # Dual channel: Send internal email summary to system managers
        system_managers = frappe.get_all(
            "Has Role",
            filters={"role": "System Manager", "parenttype": "User"},
            fields=["parent"],
        )
        emails = [
            sm.get("parent")
            for sm in system_managers
            if sm.get("parent") and "@" in sm.get("parent")
        ]
        if emails:
            email_subject = f"Daily Business Summary - {today_str}"
            email_body = text.replace("\n", "<br>")
            send_email_notification(
                recipients=emails,
                subject=email_subject,
                message=email_body,
                reference_doctype="Telegram Settings",
                reference_name="Daily Summary",
            )

        log_telegram_event(
            direction="Outbound",
            status="Success",
            action="daily_summary",
            reference_doctype="Telegram Settings",
            reference_name="Daily Summary",
            request_payload={"date": today_str, "recipients_count": len(recipients)},
            response_payload=metrics,
        )

        logger.info("Daily Business Summary sent successfully to %d recipients.", len(recipients))

    except Exception as e:
        logger.error("Failed to generate/dispatch Daily Business Summary: %s", e)
