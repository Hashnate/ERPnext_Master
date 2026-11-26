app_name = "telegram_approvals_alerts"
app_title = "Telegram Approvals and Alerts"
app_publisher = "Custom Developer"
app_description = "Telegram approvals and notification alerts for ERPNext"
app_email = "dev@example.local"
app_license = "MIT"

# Document Event Hooks for Approvals (Purchase Order, Leave Application, Expense Claim)
doc_events = {
    "Purchase Order": {
        "after_insert": "telegram_approvals_alerts.handlers.purchase_order.on_purchase_order_insert",
        "on_update": "telegram_approvals_alerts.handlers.purchase_order.on_purchase_order_update",
    },
    "Leave Application": {
        "after_insert": "telegram_approvals_alerts.handlers.leave_application.on_leave_application_insert",
    },
    "Expense Claim": {
        "after_insert": "telegram_approvals_alerts.handlers.expense_claim.on_expense_claim_insert",
    },
}

# Scheduled Background Tasks for Daily Summary & Overdue Reminders
scheduler_events = {
    "cron": {
        "0 20 * * *": [
            "telegram_approvals_alerts.tasks.daily_summary.send_daily_summary"
        ],
        "0 9 * * *": [
            "telegram_approvals_alerts.tasks.overdue_reminders.send_overdue_invoice_reminders"
        ],
    },
    "daily": [
        "telegram_approvals_alerts.tasks.daily_summary.send_daily_summary",
        "telegram_approvals_alerts.tasks.overdue_reminders.send_overdue_invoice_reminders",
    ],
}
