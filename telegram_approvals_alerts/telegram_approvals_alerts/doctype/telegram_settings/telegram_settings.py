try:
    import frappe
    from frappe.model.document import Document
except ImportError:
    class Document:
        pass

class TelegramSettings(Document):
    def validate(self):
        """Validate settings before saving."""
        if hasattr(self, "enabled") and self.enabled:
            # Generate Webhook URL helper if frappe is available
            try:
                import frappe
                site_url = frappe.utils.get_url()
                self.webhook_url = f"{site_url}/api/method/telegram_approvals_alerts.api.webhook.telegram_webhook"
            except Exception:
                pass
