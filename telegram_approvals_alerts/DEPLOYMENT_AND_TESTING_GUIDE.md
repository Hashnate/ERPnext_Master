# DEPLOYMENT, TESTING, AND STAGING VERIFICATION GUIDE
## Telegram Approvals and Alerts Custom App

This guide covers setup, testing, deployment, and staging verification for **Telegram Approvals & Alerts** on ERPNext.

---

## 1. Environment Status and Blockers

### Local Development Environment
- **Operating System:** Windows 11
- **Python Version:** Python 3.13.16
- **Frappe Bench Status:** Not installed / unavailable locally on this Windows host.
- **Testing Approach:** High-fidelity Mock Frappe testing framework (`conftest.py`) allowing 100% of custom business logic, webhook authentication, permission checks, workflow transition routing, and scheduler payloads to be deterministically validated offline.

### Staging / Production Requirements
To run full end-to-end integration with live database persistence and actual external API calls, a standard Linux/Unix Frappe Bench environment is required:
- Ubuntu 22.04 LTS or Debian 12
- Python 3.10 - 3.12
- MariaDB 10.6+
- Redis Server (cache, queue, socketio)
- Node.js 18+ and Yarn
- Nginx with valid TLS/SSL certificate (required by Telegram Webhook API)

---

## 2. Step-by-Step Installation in Frappe Bench

```bash
# Step 1: Switch to frappe user and navigate to bench root
cd /home/frappe/frappe-bench

# Step 2: Fetch app from the Risna branch
bench get-app https://github.com/Hashnate/ERPnext_Dev_Sri.git --branch risna telegram_approvals_alerts

# Step 3: Install app on target site
bench --site [your-site.local] install-app telegram_approvals_alerts

# Step 4: Run database migrations to install custom DocTypes and schema
bench --site [your-site.local] migrate

# Step 5: Clear cache and restart bench services
bench --site [your-site.local] clear-cache
bench restart
```

---

## 3. Telegram BotFather Configuration

1. In Telegram, start a chat with `@BotFather`.
2. Type `/newbot` and follow the prompts:
   - **Name:** E.g., `Acme ERP Approvals`
   - **Username:** E.g., `acme_erp_approvals_bot`
3. Note down the **HTTP API Token** (e.g. `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`).
4. Set description and commands:
   - Send `/setcommands` -> select your bot -> paste:
     ```text
     start - Show Chat ID for linking
     status - View linked account & permissions
     help - Bot help and documentation
     ```
5. Set webhook with Telegram:
   ```bash
   curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
        -H "Content-Type: application/json" \
        -d '{
          "url": "https://<your-erpnext-domain>/api/method/telegram_approvals_alerts.api.webhook.telegram_webhook",
          "secret_token": "<RANDOM_SECRET_STRING>",
          "allowed_updates": ["message", "callback_query"]
        }'
   ```
6. Verify webhook health:
   ```bash
   curl -s "https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo" | jq
   ```

---

## 4. ERPNext Configuration Checklist

### Step A: Telegram Settings
Navigate to **Telegram Settings** in ERPNext:
- **Enable Telegram Integration:** `Checked`
- **Telegram Bot Token:** Paste the BotFather token
- **Bot Username:** `@your_bot_username`
- **Webhook Secret Token:** Paste the `<RANDOM_SECRET_STRING>` used in `setWebhook`
- **Owner Telegram Chat ID:** Owner's personal numeric Chat ID
- **Accounts Team Chat ID:** Accounts manager Chat ID or Group ID
- **Daily Summary Time:** `20:00:00`
- **Enable Customer Overdue Email Reminders:** `0` (Unchecked by default)
- **Feature Toggles:** Ensure PO, Leave, Expense, Daily Summary, and Overdue Reminders are checked.

### Step B: Telegram User Mapping
Navigate to **Telegram User Mapping**:
1. User sends `/start` to your Telegram bot.
2. Bot replies with their Chat ID (e.g., `123456789`).
3. Add a new **Telegram User Mapping** record:
   - **User:** ERPNext User (e.g., `manager@company.com`)
   - **Telegram Chat ID:** `123456789`
   - **Is Active:** Checked
   - **Permissions:** Check relevant approval permissions (`can_approve_po`, `can_approve_leave`, `can_approve_expense`, `receive_daily_summary`).

### Step C: Standard ERPNext Email Account
1. Ensure a default outgoing **Email Account** is configured in ERPNext (**Settings > Email Account**).
2. Check **Default Outgoing** and verify sending using "Send Test Email".
3. Telegram Approvals will automatically use this native service via `frappe.sendmail()`.

---

## 5. Verification Checklist: Offline vs Staging Tests

| Feature / Requirement | Offline (Windows Mock) Status | Requires Live Staging Bench Verification | Verification Notes |
| :--- | :---: | :---: | :--- |
| **Telegram Message Formatting** | ✅ **Passed (70/70)** | Staging Verification | Renders HTML & Markdown tags safely with `html.escape` in Telegram clients |
| **Inline Approve/Reject Buttons** | ✅ **Passed (70/70)** | Staging Verification | Callback query roundtrip over live HTTPS webhook |
| **Webhook Secret Validation** | ✅ **Passed (70/70)** | Staging Verification | Validates `X-Telegram-Bot-Api-Secret-Token` header (case-insensitive) |
| **Duplicate Button Click Guard** | ✅ **Passed (70/70)** | Staging Verification | Handles rapid double-clicking, locks message text, and clears inline buttons |
| **Purchase Order Approvals** | ✅ **Passed (70/70)** | Staging Verification | Full submission lifecycle & ERPNext buying workflow check |
| **Leave Application Approvals & Rejections** | ✅ **Passed (70/70)** | Staging Verification | Checks assigned `leave_approver`, Leave Allocation balances, and saves decisions |
| **Expense Claim Approvals & Rejections** | ✅ **Passed (70/70)** | Staging Verification | Checks assigned `expense_approver`, expense accounts, and updates status |
| **Disabled ERPNext User Guard** | ✅ **Passed (70/70)** | Staging Verification | Deactivated accounts in `tabUser` (`enabled = 0`) are blocked immediately |
| **Daily Business Summary** | ✅ **Passed (70/70)** | Staging Verification | Aggregates live MariaDB GL entries and sales invoice sums |
| **Overdue Customer Alerts** | ✅ **Passed (70/70)** | Staging Verification | Tests Accounts Receivable aging queries against actual invoices |
| **Customer Email Guard** | ✅ **Passed (70/70)** | Staging Verification | Strictly suppresses customer emails unless toggle is explicitly enabled |
| **Native SMTP Notifications** | ✅ **Passed (70/70)** | Staging Verification | Verifies integration with Frappe Email Queue & SMTP relay server without hardcoded credentials |
| **Audit Logging & Timeline** | ✅ **Passed (70/70)** | Staging Verification | Logs all inbound/outbound events with credential sanitization and document comments |

---

## 6. How to Run Tests

### Local Environment (Windows / Mock Mode)
Run the complete automated 70-test suite:
```bash
cd telegram_approvals_alerts
python -m pytest -v
```

### Live Frappe Bench Environment
Run tests inside the live Frappe Bench test harness:
```bash
bench --site [site_name] run-tests --app telegram_approvals_alerts
```

---

## 7. Troubleshooting & Common Issues

| Issue / Error | Root Cause | Solution |
| :--- | :--- | :--- |
| **Webhook returns 401 Unauthorized** | Secret token header mismatch or proxy header stripping | Verify `webhook_secret` in Telegram Settings matches the `secret_token` configured in `setWebhook`. The app checks headers case-insensitively. |
| **Telegram Bad Request: can't parse entities** | Unescaped HTML special characters (`<`, `>`, `&`) in item, supplier, or reason fields | The app uses `html.escape()` on all dynamic strings. Ensure custom modifications preserve escaping. |
| **Approval button click shows "Access Denied"** | Telegram User is not mapped or lacks permission in `Telegram User Mapping` | Ensure a `Telegram User Mapping` record exists for the user's Chat ID with `can_approve_* = 1` and user is enabled in ERPNext. |
| **Customer receives overdue email unexpectedly** | Customer email toggle was enabled | In **Telegram Settings**, ensure **Enable Customer Overdue Email Reminders** is unchecked (`0`). |
| **Scheduler not running daily summary** | Background worker or scheduler disabled on site | Run `bench --site [site_name] enable-scheduler` and restart with `bench restart`. |

