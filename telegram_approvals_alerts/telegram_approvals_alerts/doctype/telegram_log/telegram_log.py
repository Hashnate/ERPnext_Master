try:
    import frappe
    from frappe.model.document import Document
except ImportError:
    class Document:
        pass

class TelegramLog(Document):
    pass
