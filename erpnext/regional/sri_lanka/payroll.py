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
