"""
Pytest configuration and Mock Frappe test environment.
Allows full unit testing of telegram_approvals_alerts without a live Frappe Bench / MariaDB environment.
"""

import datetime
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest


class MockFrappeDoc:
    """Mock Frappe Document for testing."""

    def __init__(self, doctype, **kwargs):
        self.doctype = doctype
        self.name = kwargs.get("name", f"TEST-{doctype[:3].upper()}-0001")
        self.docstatus = kwargs.get("docstatus", 0)
        self.owner = kwargs.get("owner", "creator@example.com")
        self.comments = []
        self.flags = MagicMock()
        self.flags.ignore_permissions = False
        self.flags.telegram_notified = False

        for k, v in kwargs.items():
            setattr(self, k, v)

    def submit(self):
        if self.docstatus == 1:
            raise Exception("Document already submitted")
        self.docstatus = 1
        return self

    def cancel(self):
        self.docstatus = 2
        return self

    def save(self, ignore_permissions=False):
        return self

    def insert(self, ignore_permissions=False):
        return self

    def add_comment(self, comment_type, text):
        self.comments.append({"type": comment_type, "text": text})

    def get_password(self, fieldname):
        return getattr(self, fieldname, None)

    def get(self, key, default=None):
        return getattr(self, key, default)


def setup_mock_frappe():
    """Build and register mock frappe modules into sys.modules."""
    frappe = ModuleType("frappe")

    # Exceptions
    class ValidationError(Exception):
        pass

    class PermissionError(Exception):
        pass

    frappe.ValidationError = ValidationError
    frappe.PermissionError = PermissionError

    # Whitelist decorator
    def whitelist(allow_guest=False, methods=None):
        def decorator(fn):
            fn.whitelisted = True
            fn.allow_guest = allow_guest
            return fn
        return decorator

    frappe.whitelist = whitelist

    # Model Document
    model_mod = ModuleType("frappe.model")
    doc_mod = ModuleType("frappe.model.document")
    doc_mod.Document = MockFrappeDoc
    model_mod.document = doc_mod

    # Model Workflow
    workflow_model = ModuleType("frappe.model.workflow")
    def apply_workflow(doc, action):
        if action == "Approve":
            doc.docstatus = 1
            doc.workflow_state = "Approved"
        elif action == "Reject":
            doc.workflow_state = "Rejected"
        return doc

    workflow_model.apply_workflow = apply_workflow
    model_mod.workflow = workflow_model

    # Workflow Module
    workflow_mod = ModuleType("frappe.workflow")
    workflow_mod.get_workflow_name = MagicMock(return_value=None)
    workflow_mod.get_transitions = MagicMock(return_value=[])

    # Utils
    utils_mod = ModuleType("frappe.utils")
    utils_mod.nowdate = MagicMock(return_value="2026-11-26")
    utils_mod.now_datetime = MagicMock(
        return_value=datetime.datetime(2026, 11, 26, 13, 30, 0)
    )
    utils_mod.date_diff = lambda d1, d2: (
        datetime.date.fromisoformat(str(d1)) - datetime.date.fromisoformat(str(d2))
    ).days
    utils_mod.get_url = MagicMock(return_value="https://erp.example.com")

    # Defaults
    defaults_mod = ModuleType("frappe.defaults")
    defaults_mod.get_user_default = MagicMock(return_value="Test Company")

    frappe.model = model_mod
    frappe.workflow = workflow_mod
    frappe.utils = utils_mod
    frappe.defaults = defaults_mod

    # Database
    db = MagicMock()
    db.exists = MagicMock(return_value=True)
    db.commit = MagicMock()
    db.count = MagicMock(return_value=0)
    db.get_value = MagicMock(return_value="USD")
    frappe.db = db

    # Context & state
    frappe.local = MagicMock()
    frappe.local.form_dict = {}
    frappe.request = MagicMock()
    frappe.request.headers = {}
    frappe.get_request_header = MagicMock(return_value=None)
    frappe.response = {}

    # Email
    frappe.sendmail = MagicMock()
    frappe.log_error = MagicMock()

    # User & Permissions
    frappe.session = MagicMock()
    frappe.session.user = "Administrator"
    frappe.set_user = MagicMock()
    frappe.get_roles = MagicMock(return_value=["System Manager", "All"])
    frappe.has_permission = MagicMock(return_value=True)

    # Document retrieval
    frappe.get_single = MagicMock()
    frappe.get_doc = MagicMock()
    frappe.new_doc = MagicMock(side_effect=lambda dt, **kwargs: MockFrappeDoc(dt, **kwargs))
    frappe.get_all = MagicMock(return_value=[])

    # Register in sys.modules
    sys.modules["frappe"] = frappe
    sys.modules["frappe.model"] = model_mod
    sys.modules["frappe.model.document"] = doc_mod
    sys.modules["frappe.model.workflow"] = workflow_model
    sys.modules["frappe.workflow"] = workflow_mod
    sys.modules["frappe.utils"] = utils_mod
    sys.modules["frappe.defaults"] = defaults_mod

    return frappe


# Initialize mock frappe at import time so module imports succeed
_global_mock_frappe = setup_mock_frappe()


@pytest.fixture(autouse=True)
def mock_frappe_env():
    """Fixture providing clean mock frappe environment for each test."""
    frappe = setup_mock_frappe()
    yield frappe
