from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

_RECORD_CONFIG: dict[str, dict[str, str]] = {
	"WorkSight Late Record": {
		"amount_field": "deduction_amount",
		"component_field": "late_salary_component",
		"label": "Late Deduction",
	},
	"WorkSight Overtime Record": {
		"amount_field": "overtime_amount",
		"component_field": "overtime_salary_component",
		"label": "Overtime Pay",
	},
}


def _get_settings():
	return frappe.get_cached_doc("WorkSight Settings")


def sync_record_to_additional_salary(
	record,
	settings=None,
	raise_on_missing_component: bool = False,
) -> str | None:
	"""Create an HRMS Additional Salary payroll input for a submitted Late or Overtime record."""
	settings = settings or _get_settings()
	if not cint(settings.enabled):
		return None

	cfg = _RECORD_CONFIG.get(record.doctype)
	if not cfg:
		raise ValueError(f"Unsupported record doctype for payroll sync: {record.doctype}")

	if record.docstatus != 1 or record.status in ("Waived", "Rejected", "Cancelled", "Synced to Payroll"):
		return record.additional_salary

	if record.additional_salary:
		return record.additional_salary

	amount = flt(getattr(record, cfg["amount_field"], 0))
	if amount <= 0:
		return None

	salary_component = getattr(settings, cfg["component_field"], None)
	if not salary_component:
		msg = _(
			"Please configure {0} Salary Component in WorkSight Settings before syncing to Payroll."
		).format(cfg["label"])
		if raise_on_missing_component:
			frappe.throw(msg)
		frappe.log_error(title="WorkSight Payroll Sync Skipped", message=f"{record.name}: {msg}")
		return None

	add_sal = frappe.get_doc(
		{
			"doctype": "Additional Salary",
			"employee": record.employee,
			"company": record.company,
			"salary_component": salary_component,
			"payroll_date": record.attendance_date,
			"amount": amount,
			"overwrite_salary_structure_amount": cint(settings.overwrite_salary_structure_amount),
			"ref_doctype": record.doctype,
			"ref_docname": record.name,
		}
	)
	add_sal.insert(ignore_permissions=True)
	if cint(settings.auto_submit_additional_salary):
		add_sal.submit()

	record.db_set("additional_salary", add_sal.name)
	record.db_set("status", "Synced to Payroll")
	return add_sal.name


def cancel_linked_additional_salary(record) -> None:
	"""Cancel or delete the linked Additional Salary when a Late/Overtime record is cancelled."""
	if record.additional_salary and frappe.db.exists("Additional Salary", record.additional_salary):
		add_sal = frappe.get_doc("Additional Salary", record.additional_salary)
		if add_sal.docstatus == 1:
			add_sal.cancel()
		elif add_sal.docstatus == 0:
			frappe.delete_doc("Additional Salary", add_sal.name, ignore_permissions=True)
	record.db_set("status", "Cancelled")


def on_late_record_submit(doc, method=None) -> None:
	sync_record_to_additional_salary(doc)


def on_late_record_cancel(doc, method=None) -> None:
	cancel_linked_additional_salary(doc)


def on_overtime_record_submit(doc, method=None) -> None:
	sync_record_to_additional_salary(doc)


def on_overtime_record_cancel(doc, method=None) -> None:
	cancel_linked_additional_salary(doc)


@frappe.whitelist()
def sync_payroll_inputs(
	from_date: str | None = None,
	to_date: str | None = None,
	company: str | None = None,
) -> dict[str, Any]:
	"""Sync all submitted, unsynced WorkSight Late and Overtime records into Additional Salary."""
	frappe.only_for(("System Manager", "HR Manager"))
	settings = _get_settings()
	if not cint(settings.enabled):
		return {"synced_late": 0, "synced_overtime": 0, "skipped": "disabled"}

	base_filters: dict[str, Any] = {
		"docstatus": 1,
		"status": "Approved",
		"additional_salary": ["is", "not set"],
	}
	if from_date and to_date:
		base_filters["attendance_date"] = ["between", [getdate(from_date), getdate(to_date)]]
	if company:
		base_filters["company"] = company

	synced_late = 0
	for name in frappe.db.get_all("WorkSight Late Record", filters=base_filters, pluck="name"):
		rec = frappe.get_doc("WorkSight Late Record", name)
		if sync_record_to_additional_salary(rec, settings=settings, raise_on_missing_component=True):
			synced_late += 1

	synced_overtime = 0
	for name in frappe.db.get_all("WorkSight Overtime Record", filters=base_filters, pluck="name"):
		rec = frappe.get_doc("WorkSight Overtime Record", name)
		if sync_record_to_additional_salary(rec, settings=settings, raise_on_missing_component=True):
			synced_overtime += 1

	return {
		"synced_late": synced_late,
		"synced_overtime": synced_overtime,
	}


def scheduled_sync_pending_records() -> None:
	"""Daily scheduler hook to sync approved Late & Overtime records to Additional Salary."""
	settings = _get_settings()
	if not cint(settings.enabled):
		return
	for doctype in ("WorkSight Late Record", "WorkSight Overtime Record"):
		names = frappe.db.get_all(
			doctype,
			filters={"docstatus": 1, "status": "Approved", "additional_salary": ["is", "not set"]},
			pluck="name",
		)
		for name in names:
			rec = frappe.get_doc(doctype, name)
			sync_record_to_additional_salary(rec, settings=settings)
