# Telegram Approvals and Alerts for ERPNext

A production-grade custom Frappe application designed to seamlessly bridge **ERPNext** with **Telegram Bot API** and **native SMTP email services**.

---

## 📌 Executive Overview

This application provides an automated, secure, and bidirectional communication bridge for ERPNext:
- **Interactive Telegram Approvals & Rejections:** Real-time inline keyboard buttons for **Purchase Orders**, **Leave Applications**, and **Expense Claims**.
- **Role-Based Authorization & Permission Checks:** Strictly enforces ERPNext user permissions, assigned approver hierarchies, and active ERPNext Workflows.
- **Duplicate Action Prevention:** Prevents double approvals or concurrent conflicting decisions on documents.
- **Automated Daily Business Summary:** Scheduled financial and operational digest (Sales, Payments Collected, POs, Pending Approvals) delivered to the business owner and leadership.
- **Overdue Invoice Reminders:** Proactive alerts for overdue customer invoices delivered to internal management and accounts teams.
- **Safe Customer Reminder Guard:** Customer email reminders remain strictly disabled by default; only sent when explicitly enabled and configured.
- **Native SMTP Email Notifications:** Fully integrated with Frappe's native `frappe.sendmail()` and standard ERPNext `Email Account` without hardcoding SMTP credentials.
- **Full Audit Logging:** Detailed outbound and inbound tracking in the custom `Telegram Log` DocType with automatic credential masking.

---

## 🏗️ Architecture & Layout

Built strictly as an independent Frappe app conforming to standard Frappe framework architecture. **Core ERPNext and Frappe files remain 100% untouched.**

```
telegram_approvals_alerts/
├── pyproject.toml                         # App metadata & dependencies
├── README.md                              # Main documentation
├── DEPLOYMENT_AND_TESTING_GUIDE.md        # Comprehensive deployment & staging guide
├── telegram_approvals_alerts/
│   ├── __init__.py                        # Package init
│   ├── hooks.py                           # Event hooks and scheduled task crons
│   ├── modules.txt                        # Frappe module declaration
│   ├── patches.txt                        # Migration patches
│   ├── api/
│   │   ├── __init__.py
│   │   └── webhook.py                     # Public secure Telegram webhook endpoint
│   ├── doctype/
│   │   ├── telegram_settings/             # Singleton config DocType
│   │   ├── telegram_user_mapping/         # ERPNext user <-> Telegram chat ID mapping
│   │   └── telegram_log/                  # Inbound/outbound audit log
│   ├── services/
│   │   ├── __init__.py
│   │   ├── telegram_service.py            # Telegram Bot API client & logger
│   │   ├── approval_service.py            # Approvals, permissions & workflow logic
│   │   └── email_service.py               # Native frappe.sendmail wrapper
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── purchase_order.py              # Purchase Order event hooks
│   │   ├── leave_application.py           # Leave Application event hooks
│   │   └── expense_claim.py               # Expense Claim event hooks
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── daily_summary.py               # Daily business digest scheduled job
│   │   └── overdue_reminders.py           # Overdue invoices alert scheduled job
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py                    # Mock Frappe test harness
│       ├── test_approvals.py              # Approval & rejection test suite
│       ├── test_daily_summary.py          # Daily summary test suite
│       ├── test_email_notifications.py    # Native email notification test suite
│       ├── test_handlers.py               # Document event handler test suite
│       ├── test_overdue_reminders.py      # Overdue reminder test suite
│       ├── test_telegram_service.py       # Telegram client & security test suite
│       └── test_webhook.py                # Webhook & secret token test suite
```

---

## 🤖 1. Telegram Bot Setup (via @BotFather)

1. Open Telegram and search for the official **[@BotFather](https://t.me/BotFather)** bot.
2. Send `/newbot` to start the bot creation process.
3. Choose a friendly display name (e.g. `Acme ERP Approvals`).
4. Choose a unique username ending in `bot` (e.g. `acme_erp_approvals_bot`).
5. **Save the Bot Token:** @BotFather will reply with an API token (e.g., `7123456789:AAFlkjw-xyz...`). Keep this confidential.
6. **Configure Bot Commands:**
   Send `/setcommands` to @BotFather, select your bot, and paste:
   ```text
   start - Get your Telegram Chat ID
   status - Check linked ERPNext account and permissions
   help - Show help and instructions
   ```
7. **Configure Group Privacy (Optional):**
   If the bot is to be used in accounts group chats, send `/setprivacy` to @BotFather and select `Disable` (or leave `Enable` for direct private messages only).

---

## ⚙️ 2. Configuration in ERPNext

### A. Telegram Settings (`Telegram Settings` DocType)
Log into ERPNext as **System Manager** and open **Telegram Settings**:

| Setting | Recommended Value / Description |
| :--- | :--- |
| **Enable Telegram Integration** | Checked (`1`) |
| **Telegram Bot Token** | Paste the token obtained from @BotFather (stored securely in password field) |
| **Bot Username** | E.g. `@acme_erp_approvals_bot` |
| **Webhook Secret Token** | Enter a strong random secret token (e.g., generated with `openssl rand -hex 24`) |
| **Owner Telegram Chat ID** | Private Chat ID of the company owner |
| **Accounts Team Chat ID** | Private Chat ID or Group ID for overdue alerts |
| **Daily Summary Time** | `20:00:00` (8:00 PM) |
| **Enable Customer Overdue Email Reminders** | **Unchecked (`0`)** by default for safety. Only check if direct customer dunning emails are desired. |
| **Feature Toggles** | Enable/disable PO, Leave, Expense, Daily Summary, or Overdue alerts independently |

### B. Register Webhook with Telegram
Once your ERPNext site has an active HTTPS domain, register your webhook using:
```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://<your-erpnext-domain>/api/method/telegram_approvals_alerts.api.webhook.telegram_webhook",
       "secret_token": "<YOUR_WEBHOOK_SECRET_TOKEN>",
       "allowed_updates": ["message", "callback_query"]
     }'
```

### C. Telegram User Mapping (`Telegram User Mapping` DocType)
1. Instruct each manager/approver to open your Telegram bot and send `/start`.
2. The bot will instantly respond with their **Telegram Chat ID**.
3. In ERPNext, create a new record in **Telegram User Mapping**:
   - **ERPNext User:** Select the user's ERPNext account (e.g. `john@example.com`).
   - **Telegram Chat ID:** Enter the numeric chat ID (e.g. `987654321`).
   - **Permissions:** Check `Can Approve Purchase Orders`, `Can Approve Leave Applications`, `Can Approve Expense Claims`, and/or `Receive Daily Summary`.
   - **Is Active:** Checked (`1`).

---

## 💻 3. Deployment Instructions (Frappe Bench Environment)

Deploying to an official Frappe Bench staging or production server:

```bash
# 1. Access your frappe-bench directory
cd /home/frappe/frappe-bench

# 2. Get the custom app from the Risna branch
bench get-app https://github.com/Hashnate/ERPnext_Dev_Sri.git --branch risna telegram_approvals_alerts

# 3. Install the app onto your site
bench --site erp.example.com install-app telegram_approvals_alerts

# 4. Migrate site database schema
bench --site erp.example.com migrate

# 5. Restart background workers and web server
bench restart
```

---

## 🧪 4. Testing

### Running the Test Suite Locally
All 70 unit and mock tests run under standard Python and pytest:
```bash
cd telegram_approvals_alerts
python -m pytest -v
```

See [TEST_REPORT.md](TEST_REPORT.md) for detailed test execution breakdown, coverage metrics, and bug resolution logs.

### Running Tests in Frappe Bench
```bash
bench --site erp.example.com run-tests --app telegram_approvals_alerts
```

---

## 🔒 Security Best Practices

1. **Webhook Authentication:** Every incoming webhook is validated using `X-Telegram-Bot-Api-Secret-Token` (checked case-insensitively) via constant-time comparison (`hmac.compare_digest`). Unauthorized requests return HTTP 401.
2. **ERPNext User Validation:** Mapped users must be active in `tabUser` (`enabled = 1`). Deactivated users in ERPNext are blocked immediately, even if mapping is active.
3. **Duplicate Decision Prevention:** Documents in submitted, cancelled, approved, or rejected states are locked against subsequent duplicate clicks or conflicting decisions.
4. **HTML Injection Protection:** Dynamic text in Telegram messages is sanitized with `html.escape()` to prevent syntax corruption or injection into Telegram's HTML parser.
5. **Credential Sanitization:** All bot tokens, passwords, and secrets are automatically masked (`******`) before writing to `Telegram Log` or system logs.
6. **Permission Boundaries:** Approvals strictly evaluate `frappe.has_permission()`, assigned approver fields (`doc.leave_approver`, `doc.expense_approver`), and existing ERPNext Workflow transitions.
7. **No Hardcoded Credentials:** SMTP credentials and Telegram secrets are dynamically sourced from encrypted database DocTypes.

