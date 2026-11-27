"""
Unit tests for Document Approval & Rejection Logic.
Tests Purchase Orders, Leave Applications, Expense Claims, User Authorization,
Duplicate Prevention, and Workflow Compliance.
"""

from unittest.mock import MagicMock, patch
import pytest

from telegram_approvals_alerts.services.approval_service import (
    check_duplicate_or_terminal_state,
    check_telegram_user_permission,
    process_approval_action,
)


def test_user_authorization_unmapped_user(mock_frappe_env):
    """Unregistered Telegram user is blocked with UNAUTHORIZED status."""
    mock_frappe_env.get_all.return_value = []  # No mapping found

    res = process_approval_action(
        telegram_chat_id="999999",
        action="approve",
        doctype="Purchase Order",
        docname="PO-2026-0001",
    )

    assert res["success"] is False
    assert res["status_code"] == "UNAUTHORIZED"
    assert "not mapped" in res["message"].lower()


def test_user_permission_flag_blocked(mock_frappe_env):
    """Mapped user without specific doctype permission is blocked with FORBIDDEN status."""
    # User is mapped, but can_approve_po is 0
    mock_frappe_env.get_all.return_value = [{
        "user": "approver@example.com",
        "telegram_chat_id": "12345",
        "can_approve_po": 0,
        "can_approve_leave": 1,
        "can_approve_expense": 1,
    }]

    res = process_approval_action(
        telegram_chat_id="12345",
        action="approve",
        doctype="Purchase Order",
        docname="PO-2026-0001",
    )

    assert res["success"] is False
    assert res["status_code"] == "FORBIDDEN"
    assert "do not have permission" in res["message"].lower()


def test_duplicate_approval_prevention_already_submitted(mock_frappe_env):
    """Cannot approve a document that is already submitted (docstatus = 1)."""
    mock_frappe_env.get_all.return_value = [{
        "user": "approver@example.com",
        "telegram_chat_id": "12345",
        "can_approve_po": 1,
    }]

    doc = MagicMock()
    doc.docstatus = 1
    doc.name = "PO-2026-0001"
    doc.doctype = "Purchase Order"
    mock_frappe_env.get_doc.return_value = doc

    res = process_approval_action(
        telegram_chat_id="12345",
        action="approve",
        doctype="Purchase Order",
        docname="PO-2026-0001",
    )

    assert res["success"] is False
    assert res["status_code"] == "ALREADY_PROCESSED"
    assert "already been approved" in res["message"].lower()


def test_purchase_order_approval_success(mock_frappe_env):
    """Purchase Order approval executes submit() and records comment."""
    mock_frappe_env.get_all.return_value = [{
        "user": "buyer@example.com",
        "telegram_chat_id": "12345",
        "can_approve_po": 1,
    }]

    doc = MagicMock()
    doc.docstatus = 0
    doc.name = "PO-2026-0001"
    doc.doctype = "Purchase Order"
    doc.flags = MagicMock()
    mock_frappe_env.get_doc.return_value = doc
    mock_frappe_env.has_permission.return_value = True

    res = process_approval_action(
        telegram_chat_id="12345",
        action="approve",
        doctype="Purchase Order",
        docname="PO-2026-0001",
    )

    assert res["success"] is True
    assert res["status_code"] == "SUCCESS"
    doc.submit.assert_called_once()
    doc.add_comment.assert_called_once()
    assert "Telegram" in doc.add_comment.call_args[0][1]


def test_purchase_order_rejection_success(mock_frappe_env):
    """Purchase Order rejection records comment and updates status."""
    mock_frappe_env.get_all.return_value = [{
        "user": "buyer@example.com",
        "telegram_chat_id": "12345",
        "can_approve_po": 1,
    }]

    doc = MagicMock()
    doc.docstatus = 0
    doc.name = "PO-2026-0001"
    doc.doctype = "Purchase Order"
    doc.flags = MagicMock()
    mock_frappe_env.get_doc.return_value = doc

    res = process_approval_action(
        telegram_chat_id="12345",
        action="reject",
        doctype="Purchase Order",
        docname="PO-2026-0001",
    )

    assert res["success"] is True
    assert res["status_code"] == "SUCCESS"
    assert doc.status == "Cancelled"
    doc.add_comment.assert_called()


def test_leave_application_approval_success(mock_frappe_env):
    """Leave Application approval sets status to Approved and submits."""
    mock_frappe_env.get_all.return_value = [{
        "user": "manager@example.com",
        "telegram_chat_id": "55555",
        "can_approve_leave": 1,
    }]

    doc = MagicMock()
    doc.docstatus = 0
    doc.status = "Open"
    doc.leave_approver = "manager@example.com"
    doc.name = "LAP-2026-0010"
    doc.doctype = "Leave Application"
    doc.flags = MagicMock()
    mock_frappe_env.get_doc.return_value = doc

    res = process_approval_action(
        telegram_chat_id="55555",
        action="approve",
        doctype="Leave Application",
        docname="LAP-2026-0010",
    )

    assert res["success"] is True
    assert res["status_code"] == "SUCCESS"
    assert doc.status == "Approved"
    doc.submit.assert_called_once()


def test_leave_application_unassigned_approver_blocked(mock_frappe_env):
    """User who is NOT the assigned leave approver cannot approve unless HR Manager."""
    mock_frappe_env.get_all.return_value = [{
        "user": "other_manager@example.com",
        "telegram_chat_id": "55555",
        "can_approve_leave": 1,
    }]
    mock_frappe_env.get_roles.return_value = ["Employee"]

    doc = MagicMock()
    doc.docstatus = 0
    doc.status = "Open"
    doc.leave_approver = "assigned_boss@example.com"
    doc.name = "LAP-2026-0010"
    doc.doctype = "Leave Application"
    mock_frappe_env.get_doc.return_value = doc

    res = process_approval_action(
        telegram_chat_id="55555",
        action="approve",
        doctype="Leave Application",
        docname="LAP-2026-0010",
    )

    assert res["success"] is False
    assert res["status_code"] == "NOT_ASSIGNED_APPROVER"
    assert "not the designated leave approver" in res["message"].lower()


def test_expense_claim_approval_and_rejection(mock_frappe_env):
    """Expense Claim approval sets approval_status and rejection sets Rejected."""
    mock_frappe_env.get_all.return_value = [{
        "user": "finance@example.com",
        "telegram_chat_id": "77777",
        "can_approve_expense": 1,
    }]

    # 1. Approval
    doc_app = MagicMock()
    doc_app.docstatus = 0
    doc_app.approval_status = "Draft"
    doc_app.expense_approver = "finance@example.com"
    doc_app.name = "EXP-2026-0050"
    doc_app.doctype = "Expense Claim"
    doc_app.flags = MagicMock()
    mock_frappe_env.get_doc.return_value = doc_app

    res = process_approval_action(
        telegram_chat_id="77777",
        action="approve",
        doctype="Expense Claim",
        docname="EXP-2026-0050",
    )
    assert res["success"] is True
    assert doc_app.approval_status == "Approved"
    doc_app.submit.assert_called_once()

    # 2. Rejection
    doc_rej = MagicMock()
    doc_rej.docstatus = 0
    doc_rej.approval_status = "Draft"
    doc_rej.expense_approver = "finance@example.com"
    doc_rej.name = "EXP-2026-0051"
    doc_rej.doctype = "Expense Claim"
    doc_rej.flags = MagicMock()
    mock_frappe_env.get_doc.return_value = doc_rej

    res_rej = process_approval_action(
        telegram_chat_id="77777",
        action="reject",
        doctype="Expense Claim",
        docname="EXP-2026-0051",
    )
    assert res_rej["success"] is True
    assert doc_rej.approval_status == "Rejected"


def test_respects_erpnext_workflow(mock_frappe_env):
    """When an active ERPNext workflow exists, workflow transition is applied."""
    mock_frappe_env.get_all.return_value = [{
        "user": "boss@example.com",
        "telegram_chat_id": "11111",
        "can_approve_po": 1,
    }]

    doc = MagicMock()
    doc.docstatus = 0
    doc.name = "PO-WF-001"
    doc.doctype = "Purchase Order"
    doc.flags = MagicMock()
    mock_frappe_env.get_doc.return_value = doc

    # Simulate active workflow
    mock_frappe_env.workflow.get_workflow_name.return_value = "PO Workflow"
    mock_frappe_env.workflow.get_transitions.return_value = [
        {"action": "Approve", "next_state": "Approved", "allowed": "Purchase Manager"}
    ]

    with patch("frappe.model.workflow.apply_workflow") as mock_apply:
        res = process_approval_action(
            telegram_chat_id="11111",
            action="approve",
            doctype="Purchase Order",
            docname="PO-WF-001",
        )
        assert res["success"] is True
        mock_apply.assert_called_once_with(doc, "Approve")


def test_leave_application_rejection_success(mock_frappe_env):
    """Leave Application rejection sets status to Rejected, saves document and adds comment."""
    mock_frappe_env.get_all.return_value = [{
        "user": "hr_manager@example.com",
        "telegram_chat_id": "55555",
        "can_approve_leave": 1,
    }]

    doc = MagicMock()
    doc.docstatus = 0
    doc.status = "Open"
    doc.leave_approver = "hr_manager@example.com"
    doc.name = "LAP-2026-0099"
    doc.doctype = "Leave Application"
    doc.flags = MagicMock()
    mock_frappe_env.get_doc.return_value = doc

    res = process_approval_action(
        telegram_chat_id="55555",
        action="reject",
        doctype="Leave Application",
        docname="LAP-2026-0099",
    )

    assert res["success"] is True
    assert res["status_code"] == "SUCCESS"
    assert doc.status == "Rejected"
    doc.save.assert_called_once()
    doc.add_comment.assert_called_once()


def test_duplicate_click_on_already_rejected_purchase_order(mock_frappe_env):
    """Cannot approve or re-reject a Purchase Order that has already been rejected/cancelled."""
    mock_frappe_env.get_all.return_value = [{
        "user": "buyer@example.com",
        "telegram_chat_id": "12345",
        "can_approve_po": 1,
    }]

    doc = MagicMock()
    doc.docstatus = 0
    doc.status = "Cancelled"
    doc.name = "PO-2026-0001"
    doc.doctype = "Purchase Order"
    mock_frappe_env.get_doc.return_value = doc

    res = process_approval_action(
        telegram_chat_id="12345",
        action="approve",
        doctype="Purchase Order",
        docname="PO-2026-0001",
    )

    assert res["success"] is False
    assert res["status_code"] == "ALREADY_PROCESSED"
    assert "already been cancelled" in res["message"].lower()


def test_duplicate_click_on_already_rejected_leave_application(mock_frappe_env):
    """Cannot approve a Leave Application that has already been rejected."""
    mock_frappe_env.get_all.return_value = [{
        "user": "manager@example.com",
        "telegram_chat_id": "55555",
        "can_approve_leave": 1,
    }]

    doc = MagicMock()
    doc.docstatus = 0
    doc.status = "Rejected"
    doc.name = "LAP-2026-0088"
    doc.doctype = "Leave Application"
    mock_frappe_env.get_doc.return_value = doc

    res = process_approval_action(
        telegram_chat_id="55555",
        action="approve",
        doctype="Leave Application",
        docname="LAP-2026-0088",
    )

    assert res["success"] is False
    assert res["status_code"] == "ALREADY_PROCESSED"
    assert "already been rejected" in res["message"].lower()


def test_duplicate_click_on_already_rejected_expense_claim(mock_frappe_env):
    """Cannot approve an Expense Claim that has already been rejected."""
    mock_frappe_env.get_all.return_value = [{
        "user": "finance@example.com",
        "telegram_chat_id": "77777",
        "can_approve_expense": 1,
    }]

    doc = MagicMock()
    doc.docstatus = 0
    doc.approval_status = "Rejected"
    doc.name = "EXP-2026-0077"
    doc.doctype = "Expense Claim"
    mock_frappe_env.get_doc.return_value = doc

    res = process_approval_action(
        telegram_chat_id="77777",
        action="approve",
        doctype="Expense Claim",
        docname="EXP-2026-0077",
    )

    assert res["success"] is False
    assert res["status_code"] == "ALREADY_PROCESSED"
    assert "already been rejected" in res["message"].lower()


def test_user_authorization_disabled_erpnext_user(mock_frappe_env):
    """Mapped Telegram user whose ERPNext account is disabled (enabled=0) is blocked."""
    mock_frappe_env.get_all.return_value = [{
        "user": "deactivated_employee@example.com",
        "telegram_chat_id": "99999",
        "can_approve_po": 1,
    }]
    # Simulate disabled user in tabUser
    mock_frappe_env.db.get_value.return_value = 0

    res = process_approval_action(
        telegram_chat_id="99999",
        action="approve",
        doctype="Purchase Order",
        docname="PO-2026-0001",
    )

    assert res["success"] is False
    assert res["status_code"] == "UNAUTHORIZED"
    assert "not mapped to an active erpnext user" in res["message"].lower()


def test_document_not_found_in_erpnext(mock_frappe_env):
    """Attempting to approve a non-existent document returns NOT_FOUND status."""
    mock_frappe_env.get_all.return_value = [{
        "user": "manager@example.com",
        "telegram_chat_id": "12345",
        "can_approve_po": 1,
    }]
    mock_frappe_env.db.exists.return_value = False

    res = process_approval_action(
        telegram_chat_id="12345",
        action="approve",
        doctype="Purchase Order",
        docname="PO-NONEXISTENT",
    )

    assert res["success"] is False
    assert res["status_code"] == "NOT_FOUND"
    assert "not found" in res["message"].lower()


def test_feature_toggle_disabled(mock_frappe_env):
    """When a feature toggle is disabled in Telegram Settings, approvals are blocked."""
    mock_settings = MagicMock()
    mock_settings.enabled = 1
    mock_settings.enable_po_approval = 0  # PO approvals disabled!
    mock_frappe_env.get_single.return_value = mock_settings

    res = process_approval_action(
        telegram_chat_id="12345",
        action="approve",
        doctype="Purchase Order",
        docname="PO-2026-0001",
    )

    assert res["success"] is False
    assert res["status_code"] == "FEATURE_DISABLED"
    assert "disabled in telegram settings" in res["message"].lower()


def test_invalid_approval_action():
    """Invalid action string returns INVALID_ACTION."""
    res = process_approval_action(
        telegram_chat_id="12345",
        action="forward",
        doctype="Purchase Order",
        docname="PO-2026-0001",
    )

    assert res["success"] is False
    assert res["status_code"] == "INVALID_ACTION"

