"""
Telegram Service for Telegram Approvals and Alerts.
Handles all outbound interactions with the Telegram Bot API.
"""

import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def get_telegram_settings():
    """Retrieve the Telegram Settings single document safely."""
    try:
        import frappe
        return frappe.get_single("Telegram Settings")
    except Exception as e:
        logger.warning("Could not load Telegram Settings from database: %s", e)
        return None


def get_bot_token(settings=None) -> Optional[str]:
    """Retrieve decrypted bot token from Telegram Settings."""
    if not settings:
        settings = get_telegram_settings()
    if not settings:
        return None

    token = None
    try:
        if hasattr(settings, "get_password"):
            token = settings.get_password("bot_token")
    except Exception:
        pass

    if not token and hasattr(settings, "bot_token"):
        token = settings.bot_token

    return token.strip() if token else None


def get_webhook_secret(settings=None) -> Optional[str]:
    """Retrieve webhook secret token from Telegram Settings."""
    if not settings:
        settings = get_telegram_settings()
    if not settings:
        return None

    secret = None
    try:
        if hasattr(settings, "get_password"):
            secret = settings.get_password("webhook_secret")
    except Exception:
        pass

    if not secret and hasattr(settings, "webhook_secret"):
        secret = settings.webhook_secret

    return secret.strip() if secret else None


def sanitize_payload(payload: Any) -> Any:
    """Sanitize sensitive fields from payloads before logging."""
    if not payload:
        return payload
    if isinstance(payload, dict):
        sanitized = {}
        for k, v in payload.items():
            if any(s in k.lower() for s in ("token", "secret", "password", "key")):
                sanitized[k] = "******"
            elif isinstance(v, (dict, list)):
                sanitized[k] = sanitize_payload(v)
            else:
                sanitized[k] = v
        return sanitized
    elif isinstance(payload, list):
        return [sanitize_payload(item) for item in payload]
    return payload


def log_telegram_event(
    direction: str,
    status: str,
    action: str,
    reference_doctype: Optional[str] = None,
    reference_name: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
    telegram_user: Optional[str] = None,
    request_payload: Any = None,
    response_payload: Any = None,
):
    """Record an audit entry in the Telegram Log DocType."""
    try:
        import frappe

        req_clean = sanitize_payload(request_payload)
        res_clean = sanitize_payload(response_payload)

        log = frappe.new_doc("Telegram Log")
        log.timestamp = frappe.utils.now_datetime()
        log.direction = direction
        log.status = status
        log.action = action
        log.reference_doctype = reference_doctype
        log.reference_name = reference_name
        log.telegram_chat_id = str(telegram_chat_id) if telegram_chat_id else None
        log.telegram_user = telegram_user
        log.request_payload = (
            json.dumps(req_clean, default=str)
            if isinstance(req_clean, (dict, list))
            else str(req_clean or "")
        )
        log.response_payload = (
            json.dumps(res_clean, default=str)
            if isinstance(res_clean, (dict, list))
            else str(res_clean or "")
        )
        log.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        logger.error("Failed to write to Telegram Log: %s", e)


class TelegramBotClient:
    """Client for Telegram Bot API communication."""

    def __init__(self, token: Optional[str] = None, timeout: int = 10):
        self.token = token or get_bot_token()
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    def _call_api(self, method: str, data: Optional[Dict[str, Any]] = None) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute an HTTP POST call to Telegram Bot API.
        Returns (success: bool, result_or_error_dict).
        """
        if not self.is_configured:
            return False, {"error": "Telegram Bot Token is not configured."}

        url = f"{TELEGRAM_API_BASE}{self.token}/{method}"
        json_data = json.dumps(data or {}).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}

        req = urllib.request.Request(url, data=json_data, headers=headers, method="POST")

        context = ssl.create_default_context()

        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=context) as response:
                status_code = response.getcode()
                body = response.read().decode("utf-8")
                res_json = json.loads(body)
                if status_code == 200 and res_json.get("ok"):
                    return True, res_json.get("result", {})
                return False, res_json
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="ignore")
            logger.error("Telegram HTTPError [%s]: %s", e.code, error_body)
            try:
                parsed_err = json.loads(error_body)
            except Exception:
                parsed_err = {"error_code": e.code, "description": error_body}
            return False, parsed_err
        except urllib.error.URLError as e:
            logger.error("Telegram URLError (timeout or connection): %s", e.reason)
            return False, {"error": "Network/timeout error", "description": str(e.reason)}
        except Exception as e:
            logger.error("Unexpected error calling Telegram API: %s", e)
            return False, {"error": "Unexpected error", "description": str(e)}

    def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
        reference_doctype: Optional[str] = None,
        reference_name: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Send a text message with optional inline keyboard buttons."""
        settings = get_telegram_settings()
        if settings and hasattr(settings, "enabled") and not settings.enabled:
            logger.info("Telegram integration is disabled in Telegram Settings.")
            return False, {"error": "Telegram integration is disabled in settings"}

        payload = {
            "chat_id": str(chat_id),
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        success, result = self._call_api("sendMessage", payload)

        status_str = "Success" if success else "Failed"
        log_telegram_event(
            direction="Outbound",
            status=status_str,
            action="send_message",
            reference_doctype=reference_doctype,
            reference_name=reference_name,
            telegram_chat_id=str(chat_id),
            request_payload=payload,
            response_payload=result,
        )

        return success, result

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Acknowledge a Telegram callback query."""
        payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = True

        return self._call_api("answerCallbackQuery", payload)

    def edit_message_text(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML",
    ) -> Tuple[bool, Dict[str, Any]]:
        """Edit an existing message, commonly to remove buttons after decision."""
        payload = {
            "chat_id": str(chat_id),
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        success, result = self._call_api("editMessageText", payload)
        return success, result


def build_approval_keyboard(doctype: str, docname: str) -> Dict[str, Any]:
    """
    Build inline Approve and Reject buttons.
    Callback data format:
      app:<doctype_code>:<docname>
      rej:<doctype_code>:<docname>
    Telegram callback_data max limit is 64 bytes.
    """
    # Mapping doctype names to short codes if needed, or using direct doctype
    dt_code = doctype
    if doctype == "Purchase Order":
        dt_code = "PO"
    elif doctype == "Leave Application":
        dt_code = "LA"
    elif doctype == "Expense Claim":
        dt_code = "EC"

    return {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Approve",
                    "callback_data": f"app:{dt_code}:{docname}",
                },
                {
                    "text": "❌ Reject",
                    "callback_data": f"rej:{dt_code}:{docname}",
                },
            ]
        ]
    }


def resolve_doctype_from_code(code: str) -> str:
    """Convert short code back to ERPNext DocType name."""
    mapping = {
        "PO": "Purchase Order",
        "LA": "Leave Application",
        "EC": "Expense Claim",
        "Purchase Order": "Purchase Order",
        "Leave Application": "Leave Application",
        "Expense Claim": "Expense Claim",
    }
    return mapping.get(code, code)
