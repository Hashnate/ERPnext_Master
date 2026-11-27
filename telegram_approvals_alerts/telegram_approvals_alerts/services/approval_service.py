"""
Approval Service for Telegram Approvals and Alerts.
Handles authorization, workflow validation, and execution of document approvals/rejections.
"""

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def get_mapped_telegram_user(telegram_chat_id: str) -> Optional[Dict[str, Any]]:
    """
    Look up active ERPNext user mapped to the given Telegram Chat ID.
    Verifies both mapping record is active and ERPNext User is enabled in tabUser.
    Returns dict or Document if found and active, else None.
    """
    try:
        import frappe

        clean_id = str(telegram_chat_id).strip()
        users = frappe.get_all(
            "Telegram User Mapping",
            filters={"telegram_chat_id": clean_id, "is_active": 1},
            fields=[
                "name",
                "user",
                "telegram_chat_id",
                "telegram_username",
                "can_approve_po",
                "can_approve_leave",
                "can_approve_expense",
                "receive_daily_summary",
            ],
            limit=1,
        )
        if users:
            user_record = users[0]
            erp_user = user_record.get("user")
            if erp_user:
                user_enabled = frappe.db.get_value("User", erp_user, "enabled")
                if user_enabled in (0, "0", False):
                    logger.warning("Mapped ERPNext user %s is disabled in User doctype.", erp_user)
                    return None
            return user_record
        return None
    except Exception as e:
        logger.error("Error looking up Telegram User Mapping: %s", e)
        return None


def check_feature_toggle(doctype: str) -> Tuple[bool, str]:
    """Check whether approval for this doctype is enabled in Telegram Settings."""
    try:
        import frappe

        settings = frappe.get_single("Telegram Settings")
        if not settings.enabled:
            return False, "Telegram integration is globally disabled."

        if doctype == "Purchase Order" and not getattr(settings, "enable_po_approval", 1):
            return False, "Purchase Order approvals are disabled in Telegram Settings."
        if doctype == "Leave Application" and not getattr(settings, "enable_leave_approval", 1):
            return False, "Leave Application approvals are disabled in Telegram Settings."
        if doctype == "Expense Claim" and not getattr(settings, "enable_expense_approval", 1):
            return False, "Expense Claim approvals are disabled in Telegram Settings."

        return True, ""
    except Exception as e:
        logger.warning("Could not check feature toggle: %s", e)
        return True, ""


def check_telegram_user_permission(mapping: Dict[str, Any], doctype: str) -> Tuple[bool, str]:
    """Verify if mapped user has permission for the specified DocType in mapping record."""
    if doctype == "Purchase Order":
        if not mapping.get("can_approve_po"):
            return False, "You do not have permission to approve Purchase Orders."
    elif doctype == "Leave Application":
        if not mapping.get("can_approve_leave"):
            return False, "You do not have permission to approve Leave Applications."
    elif doctype == "Expense Claim":
        if not mapping.get("can_approve_expense"):
            return False, "You do not have permission to approve Expense Claims."
    return True, ""


def check_assigned_approver(doc, erp_user: str, doctype: str) -> Tuple[bool, str]:
    """
    Verify if the user is the assigned approver on the document, or has appropriate role.
    """
    try:
        import frappe

        # System Manager or Administrator can always approve
        user_roles = frappe.get_roles(erp_user) or []
        if "System Manager" in user_roles or "Administrator" == erp_user:
            return True, ""

        if doctype == "Leave Application":
            assigned = getattr(doc, "leave_approver", None)
            if assigned and assigned != erp_user:
                if "HR Manager" not in user_roles and "HR User" not in user_roles:
                    return (
                        False,
                        f"You are not the designated Leave Approver ({assigned}) for this application.",
                    )
            if not frappe.has_permission("Leave Application", ptype="submit", user=erp_user) and not frappe.has_permission("Leave Application", ptype="write", user=erp_user):
                return False, "You do not have ERPNext permission to submit or update Leave Applications."

        elif doctype == "Expense Claim":
            assigned = getattr(doc, "expense_approver", None)
            if assigned and assigned != erp_user:
                if "Expense Approver" not in user_roles and "HR Manager" not in user_roles:
                    return (
                        False,
                        f"You are not the designated Expense Approver ({assigned}) for this claim.",
                    )
            if not frappe.has_permission("Expense Claim", ptype="submit", user=erp_user) and not frappe.has_permission("Expense Claim", ptype="write", user=erp_user):
                return False, "You do not have ERPNext permission to submit or update Expense Claims."

        elif doctype == "Purchase Order":
            # Check Purchase User / Purchase Manager role or submit permission
            if not frappe.has_permission("Purchase Order", ptype="submit", user=erp_user):
                if not frappe.has_permission("Purchase Order", ptype="write", user=erp_user):
                    return False, "You do not have ERPNext permission to submit or update Purchase Orders."

        return True, ""
    except Exception as e:
        logger.warning("Error in check_assigned_approver: %s", e)
        return True, ""


def check_duplicate_or_terminal_state(doc, doctype: str) -> Tuple[bool, str]:
    """
    Check if the document is already approved, submitted, rejected, or cancelled.
    Returns (is_terminal: bool, status_message: str).
    """
    docstatus = getattr(doc, "docstatus", 0)

    if docstatus == 1:
        return True, f"{doctype} {doc.name} has already been approved / submitted."
    if docstatus == 2:
        return True, f"{doctype} {doc.name} has already been cancelled."

    if doctype == "Leave Application":
        current_status = getattr(doc, "status", "Open")
        if current_status in ("Approved", "Rejected", "Cancelled"):
            return True, f"Leave Application {doc.name} has already been {current_status.lower()}."

    elif doctype == "Expense Claim":
        current_status = getattr(doc, "approval_status", "Draft")
        if current_status in ("Approved", "Rejected", "Cancelled"):
            return True, f"Expense Claim {doc.name} has already been {current_status.lower()}."

    elif doctype == "Purchase Order":
        current_status = getattr(doc, "status", "Draft")
        if current_status in ("Cancelled", "Closed"):
            return True, f"Purchase Order {doc.name} has already been {current_status.lower()}."

    return False, ""


def apply_workflow_action(doc, action: str, erp_user: str) -> Tuple[bool, str]:
    """
    Attempt to apply ERPNext Workflow transition if active workflow exists for DocType.
    Returns (applied: bool, message: str).
    """
    try:
        import frappe
        import frappe.workflow

        doctype = doc.doctype
        workflow_name = frappe.workflow.get_workflow_name(doctype)
        if not workflow_name:
            return False, "No workflow configured"

        # Check available transitions for the user
        transitions = frappe.workflow.get_transitions(doc)
        target_action = None

        # Look for matching transition action based on approve / reject
        for t in transitions:
            t_action = t.get("action", "").lower()
            if action == "approve" and t_action in ("approve", "submit", "accept", "pass"):
                target_action = t.get("action")
                break
            elif action == "reject" and t_action in ("reject", "cancel", "deny"):
                target_action = t.get("action")
                break

        if not target_action:
            allowed_actions = [t.get("action") for t in transitions]
            return False, (
                f"No workflow transition '{action}' found for user {erp_user}. "
                f"Available actions: {allowed_actions}"
            )

        frappe.set_user(erp_user)
        frappe.model.workflow.apply_workflow(doc, target_action)
        return True, f"Workflow transition '{target_action}' applied successfully."

    except Exception as e:
        logger.info("Workflow check / apply passed or not found: %s", e)
        return False, str(e)


def execute_standard_action(doc, action: str, erp_user: str, doctype: str) -> Tuple[bool, str]:
    """
    Execute standard Frappe document lifecycle approval/rejection without workflow.
    """
    import frappe

    frappe.set_user(erp_user)

    if doctype == "Purchase Order":
        if action == "approve":
            doc.flags.ignore_permissions = False
            doc.submit()
            return True, f"Purchase Order {doc.name} submitted successfully."
        else:
            # Rejection of Purchase Order in Draft
            doc.add_comment("Comment", f"Purchase Order rejected via Telegram by {erp_user}.")
            doc.status = "Cancelled"
            try:
                doc.save(ignore_permissions=False)
            except Exception:
                pass
            return True, f"Purchase Order {doc.name} marked as rejected."

    elif doctype == "Leave Application":
        if action == "approve":
            doc.status = "Approved"
            doc.flags.ignore_permissions = False
            # If docstatus is 0, submit it
            if doc.docstatus == 0:
                doc.submit()
            else:
                doc.save(ignore_permissions=False)
            return True, f"Leave Application {doc.name} approved and submitted."
        else:
            doc.status = "Rejected"
            doc.flags.ignore_permissions = False
            doc.save(ignore_permissions=False)
            return True, f"Leave Application {doc.name} marked as rejected."

    elif doctype == "Expense Claim":
        if action == "approve":
            doc.approval_status = "Approved"
            doc.flags.ignore_permissions = False
            if doc.docstatus == 0:
                doc.submit()
            else:
                doc.save(ignore_permissions=False)
            return True, f"Expense Claim {doc.name} approved and submitted."
        else:
            doc.approval_status = "Rejected"
            doc.flags.ignore_permissions = False
            doc.save(ignore_permissions=False)
            return True, f"Expense Claim {doc.name} marked as rejected."

    return False, f"Unsupported DocType: {doctype}"


def process_approval_action(
    telegram_chat_id: str,
    action: str,
    doctype: str,
    docname: str,
    telegram_username: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main processor for handling Telegram inline button clicks (approve / reject).

    Returns dict:
      {
         "success": bool,
         "status_code": str,  # SUCCESS, UNAUTHORIZED, FORBIDDEN, ALREADY_PROCESSED, ERROR
         "message": str,
         "user": str,
      }
    """
    action = action.lower()
    if action not in ("approve", "reject"):
        return {
            "success": False,
            "status_code": "INVALID_ACTION",
            "message": f"Invalid action: {action}. Must be 'approve' or 'reject'.",
        }

    # 1. Feature toggle check
    toggle_ok, toggle_msg = check_feature_toggle(doctype)
    if not toggle_ok:
        return {"success": False, "status_code": "FEATURE_DISABLED", "message": toggle_msg}

    # 2. Telegram user authentication
    mapping = get_mapped_telegram_user(telegram_chat_id)
    if not mapping:
        return {
            "success": False,
            "status_code": "UNAUTHORIZED",
            "message": "Your Telegram account is not mapped to an active ERPNext user.",
        }

    # 3. User permission check in mapping
    perm_ok, perm_msg = check_telegram_user_permission(mapping, doctype)
    if not perm_ok:
        return {"success": False, "status_code": "FORBIDDEN", "message": perm_msg}

    erp_user = mapping.get("user")

    try:
        import frappe

        # 4. Fetch the document
        if not frappe.db.exists(doctype, docname):
            return {
                "success": False,
                "status_code": "NOT_FOUND",
                "message": f"{doctype} '{docname}' not found in ERPNext.",
            }

        doc = frappe.get_doc(doctype, docname)

        # 5. Duplicate and terminal state prevention
        is_terminal, term_msg = check_duplicate_or_terminal_state(doc, doctype)
        if is_terminal:
            return {
                "success": False,
                "status_code": "ALREADY_PROCESSED",
                "message": term_msg,
            }

        # 6. Check assigned approver & ERPNext permissions
        approver_ok, approver_msg = check_assigned_approver(doc, erp_user, doctype)
        if not approver_ok:
            return {
                "success": False,
                "status_code": "NOT_ASSIGNED_APPROVER",
                "message": approver_msg,
            }

        # 7. Check & apply workflow or standard lifecycle
        applied_wf, wf_msg = apply_workflow_action(doc, action, erp_user)
        if not applied_wf:
            # If workflow check returned failure because transitions not permitted
            if "No workflow transition" in wf_msg:
                return {
                    "success": False,
                    "status_code": "WORKFLOW_BLOCKED",
                    "message": wf_msg,
                }
            # Otherwise execute standard document lifecycle
            success, exec_msg = execute_standard_action(doc, action, erp_user, doctype)
            if not success:
                return {"success": False, "status_code": "ERROR", "message": exec_msg}
            final_message = exec_msg
        else:
            final_message = wf_msg

        # 8. Record audit comment on document
        action_label = "Approved" if action == "approve" else "Rejected"
        timestamp_str = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S")
        comment_text = (
            f"<b>{action_label} via Telegram</b><br>"
            f"ERPNext User: {erp_user}<br>"
            f"Telegram User: @{telegram_username or 'N/A'} (ID: {telegram_chat_id})<br>"
            f"Timestamp: {timestamp_str}"
        )
        try:
            doc.add_comment("Comment", comment_text)
        except Exception as e:
            logger.warning("Could not add comment to document: %s", e)

        # 9. Send dual-channel confirmation email to document owner
        try:
            from telegram_approvals_alerts.services.email_service import send_approval_confirmation_email

            send_approval_confirmation_email(
                doctype=doctype,
                docname=docname,
                action=action,
                approver_user=erp_user,
                owner_user=getattr(doc, "owner", None),
            )
        except Exception as e:
            logger.warning("Failed to dispatch confirmation email: %s", e)

        frappe.db.commit()

        return {
            "success": True,
            "status_code": "SUCCESS",
            "message": final_message,
            "user": erp_user,
        }

    except frappe.ValidationError as ve:
        return {"success": False, "status_code": "VALIDATION_ERROR", "message": str(ve)}
    except frappe.PermissionError as pe:
        return {"success": False, "status_code": "PERMISSION_ERROR", "message": str(pe)}
    except Exception as e:
        logger.exception("Unexpected error processing approval action: %s", e)
        return {"success": False, "status_code": "ERROR", "message": str(e)}
