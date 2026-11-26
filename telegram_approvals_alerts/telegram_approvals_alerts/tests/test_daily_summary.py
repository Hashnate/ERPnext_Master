"""
Unit tests for Daily Business Summary Scheduled Task.
Verifies aggregation of daily sales, payments, purchases, pending approvals,
and delivery to owner and designated recipients.
"""

from unittest.mock import MagicMock, patch

from telegram_approvals_alerts.tasks.daily_summary import (
    format_summary_message,
    get_daily_metrics,
    send_daily_summary,
)


def test_get_daily_metrics(mock_frappe_env):
    """Verify daily metrics calculation from database queries."""
    # Simulate database results
    def fake_sql(query, values=None, as_dict=False):
        if "tabSales Invoice" in query:
            return [{"cnt": 5, "total": 12500.50}]
        elif "tabPayment Entry" in query:
            return [{"cnt": 3, "total": 8200.00}]
        elif "tabPurchase Order" in query:
            return [{"cnt": 2, "total": 4500.00}]
        return []

    mock_frappe_env.db.sql.side_effect = fake_sql
    mock_frappe_env.db.count.side_effect = lambda dt, filters=None: 2 if "Purchase" in dt else 1

    metrics = get_daily_metrics("2026-11-26")

    assert metrics["date"] == "2026-11-26"
    assert metrics["sales_count"] == 5
    assert metrics["sales_total"] == 12500.50
    assert metrics["payments_count"] == 3
    assert metrics["payments_total"] == 8200.00
    assert metrics["po_count"] == 2
    assert metrics["po_total"] == 4500.00
    assert metrics["pending_po"] == 2
    assert metrics["pending_leaves"] == 1


def test_format_summary_message():
    """Verify text formatting of daily digest."""
    metrics = {
        "date": "2026-11-26",
        "sales_count": 4,
        "sales_total": 15000.0,
        "payments_count": 2,
        "payments_total": 7500.0,
        "po_count": 1,
        "po_total": 3000.0,
        "pending_po": 2,
        "pending_leaves": 1,
        "pending_expenses": 3,
        "currency": "USD",
    }
    msg = format_summary_message(metrics)

    assert "DAILY BUSINESS SUMMARY" in msg
    assert "2026-11-26" in msg
    assert "USD 15,000.00" in msg
    assert "USD 7,500.00" in msg
    assert "Pending Approvals" in msg or "PENDING APPROVALS" in msg


def test_send_daily_summary_dispatches_telegram_and_email(mock_frappe_env):
    """Verify delivery to Telegram owner chat and internal email to system managers."""
    mock_settings = MagicMock()
    mock_settings.enabled = 1
    mock_settings.enable_daily_summary = 1
    mock_settings.owner_chat_id = "998877"
    mock_frappe_env.get_single.return_value = mock_settings

    mock_frappe_env.get_all.side_effect = lambda dt, **kwargs: (
        [{"telegram_chat_id": "112233"}]
        if dt == "Telegram User Mapping"
        else [{"parent": "manager@example.com"}]
    )

    with patch("telegram_approvals_alerts.services.telegram_service.TelegramBotClient.send_message") as mock_tg:
        send_daily_summary()

        # Dispatched to owner (998877) and mapped recipient (112233)
        assert mock_tg.call_count == 2
        called_chats = {call[1]["chat_id"] for call in mock_tg.call_args_list}
        assert "998877" in called_chats
        assert "112233" in called_chats

        # Dispatched internal email
        mock_frappe_env.sendmail.assert_called_once()
        assert "manager@example.com" in mock_frappe_env.sendmail.call_args[1]["recipients"]
