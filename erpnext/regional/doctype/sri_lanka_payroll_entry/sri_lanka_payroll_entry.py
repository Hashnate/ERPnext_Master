# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from erpnext import get_region
from erpnext.regional.sri_lanka.constants import COUNTRY_NAME, DEFAULT_CURRENCY
from erpnext.regional.sri_lanka.payroll import (
	build_payroll_journal_accounts,
	calculate_payroll_row,
	get_payroll_settings,
)


class SriLankaPayrollEntry(Document):
	def validate(self):
		self.validate_company_region()
		self.validate_dates()
		self.validate_employees()
		self.calculate_all_rows()
		self.validate_accounting_accounts()

	def on_submit(self):
		if self.post_journal_entry:
			self.make_journal_entry()

	def on_cancel(self):
		if self.get("journal_entry") and frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus") == 1:
			je = frappe.get_doc("Journal Entry", self.journal_entry)
			je.flags.ignore_permissions = True
			je.cancel()

	def validate_company_region(self):
		if self.get("company") and get_region(self.company) != COUNTRY_NAME:
			frappe.throw(_("Company {0} is not in Sri Lanka.").format(frappe.bold(self.company)))
		if not self.get("currency") and self.get("company"):
			self.currency = frappe.get_cached_value("Company", self.company, "default_currency") or DEFAULT_CURRENCY

	def validate_dates(self):
		if self.from_date and self.to_date and getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(_("From Date must be before or equal to To Date."))

	def validate_employees(self):
		seen: set[str] = set()
		for row in self.get("employees") or []:
			if not row.employee:
				frappe.throw(_("Row #{0}: Employee is required.").format(row.idx))
			if row.employee in seen:
				frappe.throw(_("Row #{0}: Duplicate employee {1} in payroll run.").format(row.idx, row.employee))
			seen.add(row.employee)

			for fieldname, label in (
				("basic_salary", "Basic Salary"),
				("epf_liable_allowances", "EPF-Liable Allowances"),
				("non_epf_allowances", "Non-EPF Allowances"),
				("lump_sum_bonus", "Lump Sum / Bonus"),
				("other_deductions", "Other Deductions"),
			):
				if flt(row.get(fieldname)) < 0:
					frappe.throw(_("Row #{0}: {1} cannot be negative.").format(row.idx, _(label)))

	def calculate_all_rows(self):
		settings = get_payroll_settings(self.company)
		totals = {
			"total_employees": 0,
			"total_gross_pay": 0.0,
			"total_epf_liable": 0.0,
			"total_epf_employee": 0.0,
			"total_epf_employer": 0.0,
			"total_etf_employer": 0.0,
			"total_apit": 0.0,
			"total_other_deductions": 0.0,
			"total_net_pay": 0.0,
		}

		for row in self.get("employees") or []:
			computed = calculate_payroll_row(row, settings=settings)
			if computed["total_deduction"] > computed["gross_pay"]:
				frappe.throw(
					_("Row #{0}: Total deductions ({1}) cannot exceed Gross Pay ({2}) for {3}.").format(
						row.idx,
						computed["total_deduction"],
						computed["gross_pay"],
						row.employee_name or row.employee,
					)
				)
			row.gross_pay = computed["gross_pay"]
			row.epf_liable_earnings = computed["epf_liable_earnings"]
			row.epf_employee = computed["epf_employee"]
			row.epf_employer = computed["epf_employer"]
			row.etf_employer = computed["etf_employer"]
			row.apit_tax = computed["apit_tax"]
			row.total_deduction = computed["total_deduction"]
			row.net_pay = computed["net_pay"]

			totals["total_employees"] += 1
			totals["total_gross_pay"] += computed["gross_pay"]
			totals["total_epf_liable"] += computed["epf_liable_earnings"]
			totals["total_epf_employee"] += computed["epf_employee"]
			totals["total_epf_employer"] += computed["epf_employer"]
			totals["total_etf_employer"] += computed["etf_employer"]
			totals["total_apit"] += computed["apit_tax"]
			totals["total_other_deductions"] += flt(row.other_deductions, 2)
			totals["total_net_pay"] += computed["net_pay"]

		for key, value in totals.items():
			setattr(self, key, value if key == "total_employees" else flt(value, 2))

	def validate_accounting_accounts(self):
		if not self.post_journal_entry:
			return

		required = [
			("salary_expense_account", "Salary Expense Account"),
			("payroll_payable_account", "Payroll Payable Account"),
		]
		if flt(self.total_epf_employee) + flt(self.total_epf_employer) > 0:
			required.append(("epf_payable_account", "EPF Payable Account"))
		if flt(self.total_epf_employer) > 0:
			required.append(("epf_employer_expense_account", "EPF Employer Expense Account"))
		if flt(self.total_etf_employer) > 0:
			required.append(("etf_employer_expense_account", "ETF Employer Expense Account"))
			required.append(("etf_payable_account", "ETF Payable Account"))
		if flt(self.total_apit) > 0:
			required.append(("apit_payable_account", "APIT / PAYE Payable Account"))

		for fieldname, label in required:
			if not self.get(fieldname):
				frappe.throw(_("{0} is required when Post Accounting Journal Entry is enabled.").format(_(label)))

	def make_journal_entry(self):
		accounts = build_payroll_journal_accounts(self)
		if not accounts:
			return

		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Journal Entry",
				"company": self.company,
				"posting_date": self.posting_date,
				"user_remark": _("Sri Lanka Payroll Entry {0} ({1} to {2})").format(
					self.name, self.from_date, self.to_date
				),
				"accounts": accounts,
			}
		)
		je.flags.ignore_permissions = True
		je.insert()
		je.submit()
		self.db_set("journal_entry", je.name)

	@frappe.whitelist()
	def fetch_employees(self):
		if not self.company:
			frappe.throw(_("Please select a Company first."))

		filters = {"company": self.company, "status": "Active"}
		if self.department:
			filters["department"] = self.department
		if self.branch:
			filters["branch"] = self.branch

		requested_fields = [
			"name",
			"employee_name",
			"nic_number",
			"epf_number",
			"is_non_resident_for_apit",
			"sri_lanka_basic_salary",
			"sri_lanka_epf_allowances",
			"sri_lanka_non_epf_allowances",
			"ctc",
			"bank_name",
			"sri_lanka_bank_code",
			"sri_lanka_branch_code",
			"bank_ac_no",
		]
		has_column = getattr(frappe.db, "has_column", None)
		fields = [f for f in requested_fields if not callable(has_column) or has_column("Employee", f)]

		employees = frappe.get_all(
			"Employee",
			filters=filters,
			fields=fields,
			order_by="name asc",
		)

		existing = {row.employee for row in (self.get("employees") or []) if row.employee}
		added = 0
		for emp in employees:
			if emp.name in existing:
				continue

			bank_code = emp.sri_lanka_bank_code or (
				frappe.db.get_value("Bank", emp.bank_name, "sri_lanka_bank_code") if emp.bank_name else ""
			)
			basic = flt(emp.sri_lanka_basic_salary) or flt(emp.ctc)
			self.append(
				"employees",
				{
					"employee": emp.name,
					"employee_name": emp.employee_name,
					"nic_number": emp.nic_number or "",
					"epf_number": emp.epf_number or "",
					"is_non_resident_for_apit": int(bool(emp.is_non_resident_for_apit)),
					"basic_salary": basic,
					"epf_liable_allowances": flt(emp.sri_lanka_epf_allowances),
					"non_epf_allowances": flt(emp.sri_lanka_non_epf_allowances),
					"lump_sum_bonus": 0.0,
					"other_deductions": 0.0,
					"bank_name": emp.bank_name or "",
					"bank_code": bank_code or "",
					"branch_code": emp.sri_lanka_branch_code or "",
					"bank_account_no": emp.bank_ac_no or "",
				},
			)
			added += 1

		self.calculate_all_rows()
		return added
