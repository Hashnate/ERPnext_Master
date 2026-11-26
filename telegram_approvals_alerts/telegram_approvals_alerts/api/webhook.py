"""
Telegram Webhook API Endpoint.
Receives incoming updates from Telegram Bot API securely.
"""

import hmac
import json
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def validate_secret_token(configured_secret: Optional[str], header_token: Optional[str]) -> bool:
    """
    Validate Telegram webhook secret token using constant-time comparison.
    If no secret is configured, returns True (secret validation optional).
    """
    if not configured_secret:
        return True
    if not header_token:
        return False
    return hmac.compare_digest(configured_secret.strip(), header_token.strip())


def parse_callback_data(raw_data: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse callback query data formatted as '<action>:<doctype>:<docname>'.
    Supports short codes:
      app -> approve
      rej -> reject
      PO  -> Purchase Order
      LA  -> Leave Application
      EC  -> Expense Claim
    """
    if not raw_data or ":" not in raw_data:
        return None, None, None

    parts = raw_data.split(":", 2)
    if len(parts) != 3:
        return None, None, None

    raw_action, raw_dt, docname = parts[0].strip(), parts[1].strip(), parts[2].strip()

    # Normalize action
    action = "approve" if raw_action in ("app", "approve") else "reject" if raw_action in ("rej", "reject") else None

    # Normalize DocType
    doctype_map = {
        "PO": "Purchase Order",
        "LA": "Leave Application",
        "EC": "Expense Claim",
        "Purchase Order": "Purchase Order",
        "Leave Application": "Leave Application",
        "Expense Claim": "Expense Claim",
    }
    doctype = doctype_map.get(raw_dt)

    return action, doctype, docname


def get_request_data() -> Dict[str, Any]:
    """Retrieve JSON request body safely from Frappe request context."""
    try:
        import frappe

        if hasattr(frappe, "request") and frappe.request:
            if hasattr(frappe.request, "get_json") and callable(frappe.request.get_json):
                data = frappe.request.get_json()
                if data:
                    return data
            if hasattr(frappe.request, "get_data"):
                raw_bytes = frappe.request.get_data()
                if raw_bytes:
                    if isinstance(raw_bytes, bytes):
                        raw_bytes = raw_bytes.decode("utf-8")
                    return json.loads(raw_bytes)

        if hasattr(frappe, "local") and hasattr(frappe.local, "form_dict"):
            form = frappe.local.form_dict
            if isinstance(form, dict) and "update_id" in form:
                return dict(form)
    except Exception as e:
        logger.warning("Could not parse request json: %s", e)

    return {}


def handle_callback_query(callback_query: Dict[str, Any], client) -> Dict[str, Any]:
    """Process an incoming inline button callback query."""
    from telegram_approvals_alerts.services.approval_service import process_approval_action
    from telegram_approvals_alerts.services.telegram_service import log_telegram_event

    callback_id = callback_query.get("id")
    from_user = callback_query.get("from", {})
    from_id = str(from_user.get("id"))
    username = from_user.get("username", "")
    raw_data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")
    original_text = message.get("text", "")

    action, doctype, docname = parse_callback_data(raw_data)

    if not action or not doctype or not docname:
        client.answer_callback_query(
            callback_id,
            text="⚠️ Invalid button payload format.",
            show_alert=True,
        )
        return {"status": "ignored", "reason": "invalid_payload"}

    # Process approval or rejection action
    result = process_approval_action(
        telegram_chat_id=from_id,
        action=action,
        doctype=doctype,
        docname=docname,
        telegram_username=username,
    )

    status_code = result.get("status_code")
    res_msg = result.get("message", "")

    log_telegram_event(
        direction="Inbound",
        status="Success" if result.get("success") else "Failed",
        action=action,
        reference_doctype=doctype,
        reference_name=docname,
        telegram_chat_id=from_id,
        telegram_user=result.get("user"),
        request_payload=callback_query,
        response_payload=result,
    )

    if result.get("success"):
        # Success: acknowledge and update message
        action_title = "Approved" if action == "approve" else "Rejected"
        client.answer_callback_query(
            callback_id,
            text=f"✅ {action_title} successfully!",
            show_alert=False,
        )

        # Edit Telegram message to lock buttons and show who approved
        if chat_id and message_id:
            import frappe
            now_str = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S")
            user_display = f"@{username}" if username else f"User {from_id}"
            updated_text = (
                f"{original_text}\n\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"<b>Decision:</b> {'✅ Approved' if action == 'approve' else '❌ Rejected'}\n"
                f"<b>By:</b> {user_display} ({result.get('user')})\n"
                f"<b>Time:</b> {now_str}"
            )
            # Remove inline keyboard by passing reply_markup=None or empty
            client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=updated_text,
                reply_markup={"inline_keyboard": []},
            )
    elif status_code == "ALREADY_PROCESSED":
        # Duplicate button click
        client.answer_callback_query(
            callback_id,
            text=f"⚠️ Notice: {res_msg}",
            show_alert=True,
        )
        if chat_id and message_id:
            # Clear buttons to stop further clicks
            client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"{original_text}\n\n<i>[Action disabled: {res_msg}]</i>",
                reply_markup={"inline_keyboard": []},
            )
    elif status_code in ("UNAUTHORIZED", "FORBIDDEN", "NOT_ASSIGNED_APPROVER"):
        client.answer_callback_query(
            callback_id,
            text=f"⛔ Access Denied: {res_msg}",
            show_alert=True,
        )
    else:
        # Other errors or workflow blocks
        client.answer_callback_query(
            callback_id,
            text=f"❌ Error: {res_msg}",
            show_alert=True,
        )

    return result


def handle_text_message(message: Dict[str, Any], client) -> Dict[str, Any]:
    """Handle incoming text commands like /start, /status, /help."""
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    from_user = message.get("from", {})
    first_name = from_user.get("first_name", "User")

    if not chat_id:
        return {"status": "no_chat_id"}

    if text.startswith("/start"):
        reply = (
            f"👋 <b>Welcome {first_name}!</b>\n\n"
            f"Your Telegram Chat ID is: <code>{chat_id}</code>\n\n"
            f"To receive approvals and business alerts, copy this ID and give it to your "
            f"ERPNext Administrator to configure in <b>Telegram User Mapping</b>."
        )
        client.send_message(chat_id=chat_id, text=reply)
        return {"status": "handled_start"}

    elif text.startswith("/status"):
        from telegram_approvals_alerts.services.approval_service import get_mapped_telegram_user

        mapping = get_mapped_telegram_user(str(chat_id))
        if mapping:
            po = "✅ Yes" if mapping.get("can_approve_po") else "❌ No"
            leave = "✅ Yes" if mapping.get("can_approve_leave") else "❌ No"
            exp = "✅ Yes" if mapping.get("can_approve_expense") else "❌ No"
            daily = "✅ Yes" if mapping.get("receive_daily_summary") else "❌ No"

            reply = (
                f"🔗 <b>Telegram Mapping Status: Active</b>\n\n"
                f"<b>ERPNext User:</b> {mapping.get('user')}\n"
                f"<b>Telegram Chat ID:</b> <code>{chat_id}</code>\n\n"
                f"<b>Approval Permissions:</b>\n"
                f"• Purchase Orders: {po}\n"
                f"• Leave Applications: {leave}\n"
                f"• Expense Claims: {exp}\n"
                f"• Daily Summary Digest: {daily}"
            )
        else:
            reply = (
                f"⚠️ <b>Account Not Linked</b>\n\n"
                f"Your Chat ID <code>{chat_id}</code> is not currently mapped to an active ERPNext user."
            )
        client.send_message(chat_id=chat_id, text=reply)
        return {"status": "handled_status"}

    elif text.startswith("/help"):
        reply = (
            "🤖 <b>ERPNext Telegram Approvals & Alerts Bot</b>\n\n"
            "<b>Available Commands:</b>\n"
            "/start - Show your Telegram Chat ID\n"
            "/status - View your linked ERPNext user and approval permissions\n"
            "/help - Display this help message"
        )
        client.send_message(chat_id=chat_id, text=reply)
        return {"status": "handled_help"}

    return {"status": "ignored"}


try:
    import frappe
    whitelist_decorator = frappe.whitelist(allow_guest=True)
except Exception:
    def whitelist_decorator(fn):
        return fn


@whitelist_decorator
def telegram_webhook():
    """
    Main public webhook receiver for Telegram Bot API.
    Secured by Telegram secret token header check.
    """
    try:
        import frappe
    except ImportError:
        return {"status": "error", "message": "Frappe not available"}

    from telegram_approvals_alerts.services.telegram_service import (
        TelegramBotClient,
        get_webhook_secret,
        log_telegram_event,
    )

    # 1. Validate Secret Token Header
    configured_secret = get_webhook_secret()
    header_secret = None
    if hasattr(frappe, "get_request_header"):
        header_secret = frappe.get_request_header("X-Telegram-Bot-Api-Secret-Token")
    elif hasattr(frappe, "request") and hasattr(frappe.request, "headers"):
        header_secret = frappe.request.headers.get("X-Telegram-Bot-Api-Secret-Token")

    if configured_secret and not validate_secret_token(configured_secret, header_secret):
        logger.warning("Telegram webhook received with invalid secret token.")
        log_telegram_event(
            direction="Inbound",
            status="Failed",
            action="webhook_auth_failed",
            request_payload={"header_received": bool(header_secret)},
            response_payload={"error": "Unauthorized secret token"},
        )
        frappe.response["http_status_code"] = 401
        return {"status": "error", "message": "Unauthorized"}

    # 2. Extract Update Data
    update_data = get_request_data()
    if not update_data:
        return {"status": "ok", "message": "empty_payload"}

    client = TelegramBotClient()

    # 3. Route Callback Query (Buttons) vs Message
    if "callback_query" in update_data:
        result = handle_callback_query(update_data["callback_query"], client)
        return {"status": "ok", "result": result}

    elif "message" in update_data:
        result = handle_text_message(update_data["message"], client)
        return {"status": "ok", "result": result}

    return {"status": "ok", "message": "unhandled_update_type"}
