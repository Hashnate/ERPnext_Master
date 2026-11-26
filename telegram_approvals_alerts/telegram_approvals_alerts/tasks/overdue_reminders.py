"""
Overdue Customer Invoice Reminders Scheduled Task.
Scans for overdue sales invoices and alerts management, accounts team, and optionally customers.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def get_overdue_invoices(today_str: str) -> List[Dict[str, Any]]:
    """Query submitted Sales Invoices with outstanding balances past due date."""
    import frappe

    invoices = []
    try:
        raw_invoices = frappe.db.sql(
            """
            SELECT
                name,
                customer,
                customer_name,
                posting_date,
                due_date,
                grand_total,
                outstanding_amount,
                currency
            FROM `tabSales Invoice`
            WHERE docstatus = 1
              AND outstanding_amount > 0
              AND due_date < %s
            ORDER BY due_date ASC
            """,
            (today_str,),
            as_dict=True,
        )

        for inv in raw_invoices:
            due_date = str(inv.get("due_date"))
            overdue_days = frappe.utils.date_diff(today_str, due_date)
            invoices.append({
                "name": inv.get("name"),
                "customer": inv.get("customer"),
                "customer_name": inv.get("customer_name") or inv.get("customer"),
                "posting_date": str(inv.get("posting_date")),
                "due_date": due_date,
                "grand_total": float(inv.get("grand_total", 0.0)),
                "outstanding_amount": float(inv.get("outstanding_amount", 0.0)),
                "currency": inv.get("currency") or "USD",
                "overdue_days": overdue_days,
            })
    except Exception as e:
        logger.error("Error querying overdue invoices: %s", e)

    return invoices


def format_overdue_internal_message(invoices: List[Dict[str, Any]], today_str: str) -> str:
    """Format Telegram alert for management and accounts team."""
    total_count = len(invoices)
    total_outstanding = sum(inv["outstanding_amount"] for inv in invoices)
    currency = invoices[0]["currency"] if invoices else "USD"

    # Preview top 5 overdue invoices
    lines = []
    for inv in invoices[:5]:
        lines.append(
            f"• <b>{inv['customer_name']}</b> | <code>{inv['name']}</code>\n"
            f"  Due: {inv['due_date']} (<b>{inv['overdue_days']} days overdue</b>)\n"
            f"  Outstanding: <b>{inv['currency']} {inv['outstanding_amount']:,.2f}</b>"
        )

    preview_text = "\n\n".join(lines)
    if total_count > 5:
        preview_text += f"\n\n<i>... and {total_count - 5} more overdue invoice(s).</i>"

    message = (
        f"⚠️ <b>OVERDUE INVOICE ALERT</b>\n"
        f"📅 <b>Date:</b> {today_str}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔢 <b>Total Overdue Invoices:</b> {total_count}\n"
        f"💰 <b>Total Outstanding:</b> <b>{currency} {total_outstanding:,.2f}</b>\n\n"
        f"<b>Overdue Invoices:</b>\n\n"
        f"{preview_text}\n\n"
        f"<i>Please review ERPNext Accounts Receivable for collection actions.</i>"
    )
    return message


def send_overdue_invoice_reminders():
    """Main scheduled task for overdue invoice alerts."""
    try:
        import frappe

        settings = frappe.get_single("Telegram Settings")
        if not getattr(settings, "enabled", 0) or not getattr(settings, "enable_overdue_reminders", 1):
            logger.info("Overdue invoice reminders are disabled in Telegram Settings.")
            return

        today_str = frappe.utils.nowdate()
        invoices = get_overdue_invoices(today_str)
        if not invoices:
            logger.info("No overdue invoices found for %s.", today_str)
            return

        from telegram_approvals_alerts.services.email_service import (
            send_customer_overdue_email,
            send_email_notification,
        )
        from telegram_approvals_alerts.services.telegram_service import (
            TelegramBotClient,
            log_telegram_event,
        )

        client = TelegramBotClient()
        internal_message = format_overdue_internal_message(invoices, today_str)

        # 1. Internal Telegram alert to Accounts and Owner
        internal_recipients = set()
        accounts_chat = getattr(settings, "accounts_chat_id", None)
        owner_chat = getattr(settings, "owner_chat_id", None)

        if accounts_chat:
            internal_recipients.add(str(accounts_chat).strip())
        if owner_chat:
            internal_recipients.add(str(owner_chat).strip())

        for chat_id in internal_recipients:
            client.send_message(
                chat_id=chat_id,
                text=internal_message,
                reference_doctype="Telegram Settings",
                reference_name="Overdue Reminder",
            )

        # 2. Internal SMTP Email to Accounts Team
        accounts_users = frappe.get_all(
            "Has Role",
            filters={"role": ["in", ["Accounts Manager", "Accounts User"]], "parenttype": "User"},
            fields=["parent"],
        )
        email_list = list({
            u.get("parent") for u in accounts_users if u.get("parent") and "@" in u.get("parent")
        })

        if email_list:
            send_email_notification(
                recipients=email_list,
                subject=f"Overdue Customer Invoices Alert - {today_str}",
                message=internal_message.replace("\n", "<br>"),
                reference_doctype="Telegram Settings",
                reference_name="Overdue Reminder",
            )

        # 3. Customer Email Reminders (STRICTLY GUARDED BY SETTING)
        # Must remain disabled by default. Do not send unless explicitly enabled.
        customer_emails_sent = 0
        if getattr(settings, "enable_customer_email_reminders", 0):
            for inv in invoices:
                # Look up customer billing email
                customer_email = None
                try:
                    customer_doc = frappe.get_doc("Customer", inv["customer"])
                    customer_email = getattr(customer_doc, "email_id", None)
                    if not customer_email and hasattr(customer_doc, "get"):
                        customer_email = customer_doc.get("email_id")
                except Exception:
                    pass

                if customer_email and "@" in customer_email:
                    sent, msg = send_customer_overdue_email(
                        customer_email=customer_email,
                        customer_name=inv["customer_name"],
                        invoice_name=inv["name"],
                        due_date=inv["due_date"],
                        outstanding_amount=inv["outstanding_amount"],
                        currency=inv["currency"],
                        overdue_days=inv["overdue_days"],
                    )
                    if sent:
                        customer_emails_sent += 1

        log_telegram_event(
            direction="Outbound",
            status="Success",
            action="overdue_alert",
            reference_doctype="Telegram Settings",
            reference_name="Overdue Reminder",
            request_payload={"total_overdue": len(invoices), "today": today_str},
            response_payload={
                "telegram_recipients": len(internal_recipients),
                "customer_emails_sent": customer_emails_sent,
            },
        )

        logger.info(
            "Overdue invoice reminder processed: %d overdue invoices found.", len(invoices)
        )

    except Exception as e:
        logger.error("Failed to run overdue invoice reminders: %s", e)
