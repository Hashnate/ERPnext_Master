# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import flt

from erpnext import get_region
from erpnext.regional.sri_lanka.constants import (
	COUNTRY_NAME,
	DEFAULT_EPF_EMPLOYEE_RATE,
	DEFAULT_EPF_EMPLOYER_RATE,
	DEFAULT_ETF_EMPLOYER_RATE,
	DEFAULT_MONTHLY_APIT_SLABS,
	DEFAULT_NON_RESIDENT_APIT_RATE,
)


@dataclass(frozen=True)
class EPFETFBreakdown:
	liable_earnings: float
	epf_employee: float
	epf_employer: float
	epf_total: float
	etf_employer: float


@dataclass(frozen=True)
class APITBreakdown:
	taxable_income: float
	regular_tax: float
	lump_sum_tax: float
	total_tax: float
	effective_rate: float


def get_epf_liable_earnings(
	earnings: list[dict],
	applicable_components: set[str] | None = None,
	precision: int = 2,
) -> float:
	"""Sum earnings components eligible for EPF and ETF contributions."""
	total = 0.0
	for row in earnings or []:
		amount = flt(row.get("amount"))
		if amount <= 0:
			continue

		component = row.get("salary_component")
		if row.get("is_epf_etf_applicable"):
			total += amount
		elif applicable_components is not None and component in applicable_components:
			total += amount

	return flt(max(total, 0.0), precision)


def calculate_epf_etf(
	liable_earnings: float,
	epf_employee_rate: float = DEFAULT_EPF_EMPLOYEE_RATE,
	epf_employer_rate: float = DEFAULT_EPF_EMPLOYER_RATE,
	etf_employer_rate: float = DEFAULT_ETF_EMPLOYER_RATE,
	precision: int = 2,
) -> EPFETFBreakdown:
	"""Calculate EPF (Employee + Employer) and ETF (Employer) contributions."""
	base = max(flt(liable_earnings), 0.0)
	if base <= 0:
		return EPFETFBreakdown(
			liable_earnings=0.0,
			epf_employee=0.0,
			epf_employer=0.0,
			epf_total=0.0,
			etf_employer=0.0,
		)

	for label, rate in (
		("EPF Employee Rate", epf_employee_rate),
		("EPF Employer Rate", epf_employer_rate),
		("ETF Employer Rate", etf_employer_rate),
	):
		if flt(rate) < 0:
			frappe.throw(_("{0} cannot be negative.").format(label))

	epf_emp = flt(base * flt(epf_employee_rate) / 100.0, precision)
	epf_er = flt(base * flt(epf_employer_rate) / 100.0, precision)
	etf_er = flt(base * flt(etf_employer_rate) / 100.0, precision)

	return EPFETFBreakdown(
		liable_earnings=flt(base, precision),
		epf_employee=epf_emp,
		epf_employer=epf_er,
		epf_total=flt(epf_emp + epf_er, precision),
		etf_employer=etf_er,
	)


def _normalize_slabs(tax_slabs: list[dict] | tuple[dict, ...] | None) -> list[dict]:
	slabs = list(tax_slabs or DEFAULT_MONTHLY_APIT_SLABS)
	normalized = []
	for slab in slabs:
		from_amt = flt(slab.get("from_amount"))
		to_amt = flt(slab.get("to_amount"))
		rate = flt(slab.get("tax_rate"))
		if rate < 0:
			frappe.throw(_("APIT slab tax rate cannot be negative."))
		normalized.append({"from_amount": from_amt, "to_amount": to_amt, "tax_rate": rate})

	normalized.sort(key=lambda s: s["from_amount"])
	return normalized


def calculate_apit(
	monthly_taxable_income: float,
	tax_slabs: list[dict] | tuple[dict, ...] | None = None,
	is_non_resident: bool = False,
	non_resident_rate: float = DEFAULT_NON_RESIDENT_APIT_RATE,
	precision: int = 2,
) -> float:
	"""Calculate monthly APIT/PAYE tax using progressive slabs or non-resident flat rate."""
	income = max(flt(monthly_taxable_income), 0.0)
	if income <= 0:
		return 0.0

	if is_non_resident:
		return flt(income * flt(non_resident_rate) / 100.0, precision)

	slabs = _normalize_slabs(tax_slabs)
	tax = 0.0
	for slab in slabs:
		lower = slab["from_amount"]
		upper = slab["to_amount"]
		rate = slab["tax_rate"]

		if income <= lower:
			break

		taxable_in_band = (min(income, upper) - lower) if upper > 0 else (income - lower)
		if taxable_in_band > 0 and rate > 0:
			tax += taxable_in_band * rate / 100.0

	return flt(tax, precision)


def calculate_apit_with_lump_sum(
	regular_monthly_income: float,
	lump_sum_amount: float = 0.0,
	tax_slabs: list[dict] | tuple[dict, ...] | None = None,
	is_non_resident: bool = False,
	non_resident_rate: float = DEFAULT_NON_RESIDENT_APIT_RATE,
	precision: int = 2,
) -> APITBreakdown:
	"""Calculate monthly APIT including bonus/lump-sum apportionment across a 12-month year."""
	regular_income = max(flt(regular_monthly_income), 0.0)
	lump_sum = max(flt(lump_sum_amount), 0.0)
	total_income = flt(regular_income + lump_sum, precision)

	if total_income <= 0:
		return APITBreakdown(
			taxable_income=0.0,
			regular_tax=0.0,
			lump_sum_tax=0.0,
			total_tax=0.0,
			effective_rate=0.0,
		)

	regular_tax = calculate_apit(
		regular_income,
		tax_slabs=tax_slabs,
		is_non_resident=is_non_resident,
		non_resident_rate=non_resident_rate,
		precision=precision,
	)

	if lump_sum <= 0:
		total_tax = regular_tax
		lump_sum_tax = 0.0
	elif is_non_resident:
		lump_sum_tax = flt(lump_sum * flt(non_resident_rate) / 100.0, precision)
		total_tax = flt(regular_tax + lump_sum_tax, precision)
	else:
		# Annualized IRD method: spread lump sum over 12 months on top of regular annual remuneration
		monthly_equivalent = regular_income + (lump_sum / 12.0)
		annual_tax_with_bonus = (
			calculate_apit(monthly_equivalent, tax_slabs=tax_slabs, precision=6) * 12.0
		)
		annual_tax_regular = calculate_apit(regular_income, tax_slabs=tax_slabs, precision=6) * 12.0
		lump_sum_tax = flt(max(annual_tax_with_bonus - annual_tax_regular, 0.0), precision)
		total_tax = flt(regular_tax + lump_sum_tax, precision)

	effective_rate = flt((total_tax / total_income) * 100.0, 2) if total_income else 0.0
	return APITBreakdown(
		taxable_income=total_income,
		regular_tax=regular_tax,
		lump_sum_tax=lump_sum_tax,
		total_tax=total_tax,
		effective_rate=effective_rate,
	)


def get_payroll_settings(company: str):
	"""Return Sri Lanka Payroll Settings doc for a company, or None if not configured."""
	if not company or not frappe.db.exists("Sri Lanka Payroll Settings", company):
		return None
	return frappe.get_cached_doc("Sri Lanka Payroll Settings", company)


def apply_sri_lanka_payroll_deductions(doc, method=None):
	"""Populate EPF, ETF, and APIT values on an hrms Salary Slip for Sri Lanka companies."""
	if not getattr(doc, "company", None) or get_region(doc.company) != COUNTRY_NAME:
		return

	settings = get_payroll_settings(doc.company)
	if not settings or not getattr(settings, "auto_calculate_statutory", 1):
		return

	earnings_rows = [
		{
			"salary_component": row.salary_component,
			"amount": row.amount,
			"is_epf_etf_applicable": _is_component_epf_liable(row.salary_component),
		}
		for row in (doc.get("earnings") or [])
	]

	liable_earnings = get_epf_liable_earnings(earnings_rows)
	epf_etf = calculate_epf_etf(
		liable_earnings,
		epf_employee_rate=flt(settings.epf_employee_rate),
		epf_employer_rate=flt(settings.epf_employer_rate),
		etf_employer_rate=flt(settings.etf_employer_rate),
	)

	doc.epf_liable_earnings = epf_etf.liable_earnings
	doc.epf_employer_contribution = epf_etf.epf_employer
	doc.etf_employer_contribution = epf_etf.etf_employer

	if settings.epf_employee_component:
		_upsert_deduction_row(doc, settings.epf_employee_component, epf_etf.epf_employee)

	if settings.apit_component:
		is_non_resident = bool(
			doc.get("employee")
			and frappe.db.get_value("Employee", doc.employee, "is_non_resident_for_apit")
		)
		lump_sum = _get_lump_sum_earnings(doc)
		regular_taxable = max(flt(doc.get("gross_pay")) - lump_sum, 0.0)
		slabs = [
			{"from_amount": s.from_amount, "to_amount": s.to_amount, "tax_rate": s.tax_rate}
			for s in (settings.get("apit_slabs") or [])
		]
		apit = calculate_apit_with_lump_sum(
			regular_monthly_income=regular_taxable,
			lump_sum_amount=lump_sum,
			tax_slabs=slabs or None,
			is_non_resident=is_non_resident,
			non_resident_rate=flt(settings.non_resident_apit_rate or DEFAULT_NON_RESIDENT_APIT_RATE),
		)
		doc.apit_tax_amount = apit.total_tax
		_upsert_deduction_row(doc, settings.apit_component, apit.total_tax)

	_recalculate_salary_slip_totals(doc)


def _recalculate_salary_slip_totals(doc):
	"""Recompute Salary Slip totals after Sri Lanka statutory deductions are updated."""
	total_deduction = flt(sum(flt(row.get("amount")) for row in (doc.get("deductions") or [])), 2)
	gross_pay = flt(doc.get("gross_pay"), 2)
	net_pay = flt(gross_pay - total_deduction, 2)
	exchange_rate = flt(doc.get("exchange_rate")) or 1.0

	doc.total_deduction = total_deduction
	doc.net_pay = net_pay
	if hasattr(doc, "base_total_deduction") or "base_total_deduction" in doc:
		doc.base_total_deduction = flt(total_deduction * exchange_rate, 2)
	if hasattr(doc, "base_net_pay") or "base_net_pay" in doc:
		doc.base_net_pay = flt(net_pay * exchange_rate, 2)
	if hasattr(doc, "rounded_total") or "rounded_total" in doc:
		doc.rounded_total = flt(round(net_pay), 2)
	if hasattr(doc, "base_rounded_total") or "base_rounded_total" in doc:
		doc.base_rounded_total = flt(round(net_pay * exchange_rate), 2)
	if hasattr(doc, "set_net_total_in_words") and callable(doc.set_net_total_in_words):
		doc.set_net_total_in_words()


def _extract_apit_settings(settings) -> tuple[list[dict] | None, float]:
	if not settings:
		return None, DEFAULT_NON_RESIDENT_APIT_RATE

	slabs = [
		{"from_amount": s.from_amount, "to_amount": s.to_amount, "tax_rate": s.tax_rate}
		for s in (settings.get("apit_slabs") or [])
	]
	non_res_rate = flt(settings.non_resident_apit_rate or DEFAULT_NON_RESIDENT_APIT_RATE)
	return (slabs or None), non_res_rate


def calculate_payroll_row(row, settings=None, precision: int = 2) -> dict:
	"""Calculate EPF, ETF, APIT/PAYE, and Net Pay for a Sri Lanka Payroll Employee row."""
	basic = max(flt(row.get("basic_salary")), 0.0)
	epf_allowances = max(flt(row.get("epf_liable_allowances")), 0.0)
	non_epf_allowances = max(flt(row.get("non_epf_allowances")), 0.0)
	lump_sum = max(flt(row.get("lump_sum_bonus")), 0.0)
	other_deductions = max(flt(row.get("other_deductions")), 0.0)

	regular_income = flt(basic + epf_allowances + non_epf_allowances, precision)
	gross_pay = flt(regular_income + lump_sum, precision)
	liable_earnings = flt(basic + epf_allowances, precision)

	epf_emp_rate = flt(settings.epf_employee_rate) if settings else DEFAULT_EPF_EMPLOYEE_RATE
	epf_er_rate = flt(settings.epf_employer_rate) if settings else DEFAULT_EPF_EMPLOYER_RATE
	etf_er_rate = flt(settings.etf_employer_rate) if settings else DEFAULT_ETF_EMPLOYER_RATE
	epf_etf = calculate_epf_etf(
		liable_earnings,
		epf_employee_rate=epf_emp_rate,
		epf_employer_rate=epf_er_rate,
		etf_employer_rate=etf_er_rate,
		precision=precision,
	)

	slabs, non_res_rate = _extract_apit_settings(settings)
	apit = calculate_apit_with_lump_sum(
		regular_monthly_income=regular_income,
		lump_sum_amount=lump_sum,
		tax_slabs=slabs,
		is_non_resident=bool(row.get("is_non_resident_for_apit")),
		non_resident_rate=non_res_rate,
		precision=precision,
	)

	total_deduction = flt(epf_etf.epf_employee + apit.total_tax + other_deductions, precision)
	net_pay = flt(max(gross_pay - total_deduction, 0.0), precision)

	return {
		"gross_pay": gross_pay,
		"epf_liable_earnings": epf_etf.liable_earnings,
		"epf_employee": epf_etf.epf_employee,
		"epf_employer": epf_etf.epf_employer,
		"etf_employer": epf_etf.etf_employer,
		"apit_tax": apit.total_tax,
		"total_deduction": total_deduction,
		"net_pay": net_pay,
	}


def build_payroll_journal_accounts(doc) -> list[dict]:
	"""Build balanced Journal Entry account lines for a Sri Lanka Payroll Entry."""
	total_gross = flt(doc.get("total_gross_pay"), 2)
	total_epf_emp = flt(doc.get("total_epf_employee"), 2)
	total_epf_er = flt(doc.get("total_epf_employer"), 2)
	total_etf_er = flt(doc.get("total_etf_employer"), 2)
	total_apit = flt(doc.get("total_apit"), 2)
	total_other_ded = flt(doc.get("total_other_deductions"), 2)
	total_net = flt(doc.get("total_net_pay"), 2)

	accounts: list[dict] = []
	if total_gross > 0 and doc.get("salary_expense_account"):
		accounts.append({"account": doc.salary_expense_account, "debit_in_account_currency": total_gross})
	if total_epf_er > 0 and doc.get("epf_employer_expense_account"):
		accounts.append(
			{"account": doc.epf_employer_expense_account, "debit_in_account_currency": total_epf_er}
		)
	if total_etf_er > 0 and doc.get("etf_employer_expense_account"):
		accounts.append(
			{"account": doc.etf_employer_expense_account, "debit_in_account_currency": total_etf_er}
		)

	if total_net > 0 and doc.get("payroll_payable_account"):
		accounts.append({"account": doc.payroll_payable_account, "credit_in_account_currency": total_net})
	epf_total = flt(total_epf_emp + total_epf_er, 2)
	if epf_total > 0 and doc.get("epf_payable_account"):
		accounts.append({"account": doc.epf_payable_account, "credit_in_account_currency": epf_total})
	if total_etf_er > 0 and doc.get("etf_payable_account"):
		accounts.append({"account": doc.etf_payable_account, "credit_in_account_currency": total_etf_er})
	if total_apit > 0 and doc.get("apit_payable_account"):
		accounts.append({"account": doc.apit_payable_account, "credit_in_account_currency": total_apit})
	other_ded_acct = doc.get("other_deductions_account") or doc.get("salary_expense_account")
	if total_other_ded > 0 and other_ded_acct:
		accounts.append({"account": other_ded_acct, "credit_in_account_currency": total_other_ded})

	return accounts


def _has_hrms_salary_slip() -> bool:
	if not frappe.db.exists("DocType", "Salary Slip"):
		return False
	get_apps = getattr(frappe, "get_installed_apps", None)
	if callable(get_apps) and "hrms" not in (get_apps() or []):
		return False
	table_exists = getattr(frappe.db, "table_exists", None)
	if callable(table_exists) and not table_exists("Salary Slip"):
		return False
	return True


def get_sri_lanka_payroll_records(filters: frappe._dict) -> list[dict]:
	"""Fetch submitted payroll rows from built-in Sri Lanka Payroll Entry and optional HRMS Salary Slips."""
	settings = get_payroll_settings(filters.company)
	emp_rate = flt(settings.epf_employee_rate) if settings else DEFAULT_EPF_EMPLOYEE_RATE
	er_rate = flt(settings.epf_employer_rate) if settings else DEFAULT_EPF_EMPLOYER_RATE
	etf_rate = flt(settings.etf_employer_rate) if settings else DEFAULT_ETF_EMPLOYER_RATE
	slabs, non_res_rate = _extract_apit_settings(settings)
	currency = frappe.get_cached_value("Company", filters.company, "default_currency") or "LKR"

	records: list[dict] = []

	if frappe.db.exists("DocType", "Sri Lanka Payroll Entry"):
		entries = frappe.get_all(
			"Sri Lanka Payroll Entry",
			filters={
				"company": filters.company,
				"docstatus": 1,
				"posting_date": ["between", [filters.from_date, filters.to_date]],
			},
			pluck="name",
		)
		if entries:
			emp_rows = frappe.get_all(
				"Sri Lanka Payroll Employee",
				filters={"parent": ["in", entries], "parenttype": "Sri Lanka Payroll Entry"},
				fields=[
					"employee",
					"employee_name",
					"epf_number",
					"nic_number",
					"is_non_resident_for_apit",
					"gross_pay",
					"epf_liable_earnings",
					"epf_employee",
					"epf_employer",
					"etf_employer",
					"apit_tax",
				],
				order_by="employee asc",
			)
			for row in emp_rows:
				epf_emp = flt(row.epf_employee, 2)
				epf_er = flt(row.epf_employer, 2)
				records.append(
					{
						"employee": row.employee,
						"employee_name": row.employee_name,
						"epf_number": row.epf_number or "",
						"nic_number": row.nic_number or "",
						"is_non_resident": int(bool(row.is_non_resident_for_apit)),
						"gross_pay": flt(row.gross_pay, 2),
						"liable_earnings": flt(row.epf_liable_earnings, 2),
						"epf_employee": epf_emp,
						"epf_employer": epf_er,
						"epf_total": flt(epf_emp + epf_er, 2),
						"etf_employer": flt(row.etf_employer, 2),
						"apit_tax_amount": flt(row.apit_tax, 2),
						"currency": currency,
					}
				)

	if _has_hrms_salary_slip():
		has_column = getattr(frappe.db, "has_column", None)
		slip_fields = ["employee", "employee_name", "gross_pay"]
		if not callable(has_column) or has_column("Salary Slip", "epf_liable_earnings"):
			slip_fields.append("epf_liable_earnings")
		if not callable(has_column) or has_column("Salary Slip", "apit_tax_amount"):
			slip_fields.append("apit_tax_amount")

		slips = frappe.get_all(
			"Salary Slip",
			filters={
				"company": filters.company,
				"docstatus": 1,
				"posting_date": ["between", [filters.from_date, filters.to_date]],
			},
			fields=slip_fields,
			order_by="employee asc",
		)
		for slip in slips:
			emp = frappe.db.get_value(
				"Employee",
				slip.employee,
				["epf_number", "nic_number", "is_non_resident_for_apit"],
				as_dict=True,
			) or {}
			base = flt(slip.get("epf_liable_earnings") or slip.get("gross_pay"))
			epf_etf = calculate_epf_etf(
				base,
				epf_employee_rate=emp_rate,
				epf_employer_rate=er_rate,
				etf_employer_rate=etf_rate,
			)
			is_non_res = bool(emp.get("is_non_resident_for_apit"))
			apit_amt = flt(slip.get("apit_tax_amount"))
			if not apit_amt and flt(slip.gross_pay) > 0:
				apit_amt = calculate_apit(
					flt(slip.gross_pay),
					tax_slabs=slabs,
					is_non_resident=is_non_res,
					non_resident_rate=non_res_rate,
				)
			records.append(
				{
					"employee": slip.employee,
					"employee_name": slip.employee_name,
					"epf_number": emp.get("epf_number") or "",
					"nic_number": emp.get("nic_number") or "",
					"is_non_resident": int(is_non_res),
					"gross_pay": flt(slip.gross_pay, 2),
					"liable_earnings": epf_etf.liable_earnings,
					"epf_employee": epf_etf.epf_employee,
					"epf_employer": epf_etf.epf_employer,
					"epf_total": epf_etf.epf_total,
					"etf_employer": epf_etf.etf_employer,
					"apit_tax_amount": apit_amt,
					"currency": currency,
				}
			)

	return records


def _is_component_epf_liable(component_name: str | None) -> bool:
	if not component_name:
		return False
	return bool(frappe.db.get_value("Salary Component", component_name, "is_epf_etf_applicable"))


def _get_lump_sum_earnings(doc) -> float:
	lump_sum = 0.0
	for row in doc.get("earnings") or []:
		if row.salary_component and frappe.db.get_value(
			"Salary Component", row.salary_component, "is_apit_lump_sum"
		):
			lump_sum += flt(row.amount)
	return lump_sum


def _upsert_deduction_row(doc, component_name: str, amount: float):
	for row in doc.get("deductions") or []:
		if row.salary_component == component_name:
			row.amount = amount
			return

	if amount > 0:
		doc.append("deductions", {"salary_component": component_name, "amount": amount})
