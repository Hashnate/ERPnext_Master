try:
    import frappe
    from frappe.model.document import Document
except ImportError:
    class Document:
        pass

class TelegramUserMapping(Document):
    def validate(self):
        """Validate mapping record before save."""
        if hasattr(self, "telegram_chat_id") and self.telegram_chat_id:
            cleaned_id = str(self.telegram_chat_id).strip()
            self.telegram_chat_id = cleaned_id
