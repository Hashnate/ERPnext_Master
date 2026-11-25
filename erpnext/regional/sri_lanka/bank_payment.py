# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime

import frappe
from frappe import _
from frappe.utils import flt, getdate

from erpnext import get_region
from erpnext.regional.sri_lanka.constants import COUNTRY_NAME, DEFAULT_CURRENCY


@dataclass(frozen=True)
class BankPaymentHeader:
	company_name: str
	company_bank_code: str
	company_branch_code: str
	company_account_no: str
	value_date: str | date
	batch_reference: str
	currency: str = DEFAULT_CURRENCY
	transaction_type: str = "SALARY"  # SALARY or SUPPLIER


@dataclass(frozen=True)
class BankPaymentRow:
	payee_name: str
	bank_code: str
	branch_code: str
	account_no: str
	amount: float
	reference: str
	nic_or_id: str = ""
	row_idx: int = 1


@dataclass(frozen=True)
class BankPaymentResult:
	filename: str
	content: str
	bank_format: str
	record_count: int
	total_amount: float


def _clean_digits(value: str | None) -> str:
	return "".join(ch for ch in str(value or "").strip() if ch.isdigit())


def _clean_text(value: str | None, max_len: int) -> str:
	cleaned = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
	return cleaned[:max_len]


def _format_value_date(value_date: str | date) -> str:
	if isinstance(value_date, datetime):
		return value_date.strftime("%Y%m%d")
	if isinstance(value_date, date):
		return value_date.strftime("%Y%m%d")
	parsed = getdate(str(value_date))
	return parsed.strftime("%Y%m%d")


def _format_iso_date(value_date: str | date) -> str:
	if isinstance(value_date, datetime):
		return value_date.strftime("%Y-%m-%d")
	if isinstance(value_date, date):
		return value_date.strftime("%Y-%m-%d")
	parsed = getdate(str(value_date))
	return parsed.strftime("%Y-%m-%d")


def _amount_in_cents(amount: float) -> int:
	return round(flt(amount, 2) * 100)


def validate_payment_batch(header: BankPaymentHeader, rows: list[BankPaymentRow]) -> list[str]:
	"""Validate Sri Lanka bank payment batch header and payee rows; raise on errors."""
	errors: list[str] = []

	if not _clean_text(header.company_name, 50):
		errors.append(_("Company name is required."))

	comp_bank = _clean_digits(header.company_bank_code)
	if len(comp_bank) != 4:
		errors.append(_("Company Bank Code must be a 4-digit numeric SLIPS code."))

	comp_branch = _clean_digits(header.company_branch_code)
	if len(comp_branch) != 3:
		errors.append(_("Company Branch Code must be a 3-digit numeric SLIPS code."))

	comp_acct = _clean_digits(header.company_account_no)
	if not comp_acct:
		errors.append(_("Company Bank Account Number is required."))

	try:
		_format_value_date(header.value_date)
	except Exception:
		errors.append(_("Valid Value Date is required."))

	if not rows:
		errors.append(_("At least one payment row is required to generate a bank file."))

	for idx, row in enumerate(rows, start=1):
		row_no = row.row_idx or idx
		if not _clean_text(row.payee_name, 40):
			errors.append(_("Row #{0}: Payee Name is required.").format(row_no))

		bank_code = _clean_digits(row.bank_code)
		if len(bank_code) != 4:
			errors.append(_("Row #{0}: Bank Code '{1}' must be 4 digits.").format(row_no, row.bank_code))

		branch_code = _clean_digits(row.branch_code)
		if len(branch_code) != 3:
			errors.append(
				_("Row #{0}: Branch Code '{1}' must be 3 digits.").format(row_no, row.branch_code)
			)

		acct_no = _clean_digits(row.account_no)
		if not acct_no or len(acct_no) > 20:
			errors.append(_("Row #{0}: Valid numeric Account Number is required.").format(row_no))

		if flt(row.amount, 2) <= 0:
			errors.append(_("Row #{0}: Payment amount must be greater than 0.").format(row_no))

		if not _clean_text(row.reference, 30):
			errors.append(_("Row #{0}: Payment Reference is required.").format(row_no))

	if errors:
		frappe.throw("<br>".join(errors), title=_("Invalid Bank Payment Batch"))

	return errors


def _format_slips(header: BankPaymentHeader, rows: list[BankPaymentRow]) -> tuple[str, str]:
	val_date = _format_value_date(header.value_date)
	batch_ref = _clean_text(header.batch_reference, 15).ljust(15)
	comp_bank = _clean_digits(header.company_bank_code).zfill(4)
	comp_branch = _clean_digits(header.company_branch_code).zfill(3)
	comp_acct = _clean_digits(header.company_account_no).zfill(12)[-12:]
	comp_name = _clean_text(header.company_name, 30).ljust(30)
	currency = _clean_text(header.currency or DEFAULT_CURRENCY, 3).ljust(3)
	tx_code = "23" if header.transaction_type == "SALARY" else "22"

	lines = [f"H{comp_bank}{comp_branch}{comp_acct}{val_date}{batch_ref}{currency}{comp_name}"]
	total_cents = 0

	for seq, row in enumerate(rows, start=1):
		cents = _amount_in_cents(row.amount)
		total_cents += cents
		dest_bank = _clean_digits(row.bank_code).zfill(4)
		dest_branch = _clean_digits(row.branch_code).zfill(3)
		dest_acct = _clean_digits(row.account_no).zfill(12)[-12:]
		payee = _clean_text(row.payee_name, 30).ljust(30)
		ref = _clean_text(row.reference, 20).ljust(20)
		nic = _clean_text(row.nic_or_id, 12).ljust(12)
		lines.append(
			f"D{seq:06d}{dest_bank}{dest_branch}{dest_acct}{payee}{cents:013d}{tx_code}{ref}{nic}"
		)

	lines.append(f"T{len(rows):06d}{total_cents:015d}{batch_ref}")
	filename = f"SLIPS_{_clean_text(header.batch_reference, 20)}_{val_date}.txt"
	return filename, "\n".join(lines) + "\n"


def _format_csv_rows(
	filename_prefix: str,
	headers: list[str],
	row_builder,
	header: BankPaymentHeader,
	rows: list[BankPaymentRow],
) -> tuple[str, str]:
	buf = io.StringIO()
	writer = csv.writer(buf, lineterminator="\n")
	writer.writerow(headers)
	iso_date = _format_iso_date(header.value_date)
	for row in rows:
		writer.writerow(row_builder(row, header, iso_date))

	val_date = _format_value_date(header.value_date)
	filename = f"{filename_prefix}_{_clean_text(header.batch_reference, 20)}_{val_date}.csv"
	return filename, buf.getvalue()


def _format_combank(header: BankPaymentHeader, rows: list[BankPaymentRow]) -> tuple[str, str]:
	return _format_csv_rows(
		"COMBANK",
		[
			"Beneficiary Name",
			"Bank Code",
			"Branch Code",
			"Account Number",
			"Amount",
			"Currency",
			"Reference",
			"Value Date",
		],
		lambda r, h, d: [
			_clean_text(r.payee_name, 50),
			_clean_digits(r.bank_code).zfill(4),
			_clean_digits(r.branch_code).zfill(3),
			_clean_digits(r.account_no),
			f"{flt(r.amount, 2):.2f}",
			h.currency or DEFAULT_CURRENCY,
			_clean_text(r.reference, 30),
			d,
		],
		header,
		rows,
	)


def _format_sampath(header: BankPaymentHeader, rows: list[BankPaymentRow]) -> tuple[str, str]:
	return _format_csv_rows(
		"SAMPATH",
		[
			"Payee Name",
			"Bank Code",
			"Branch Code",
			"Account No",
			"Amount",
			"Payment Reference",
			"Value Date",
			"NIC",
		],
		lambda r, _h, d: [
			_clean_text(r.payee_name, 50),
			_clean_digits(r.bank_code).zfill(4),
			_clean_digits(r.branch_code).zfill(3),
			_clean_digits(r.account_no),
			f"{flt(r.amount, 2):.2f}",
			_clean_text(r.reference, 30),
			d,
			_clean_text(r.nic_or_id, 20),
		],
		header,
		rows,
	)


def _format_hnb(header: BankPaymentHeader, rows: list[BankPaymentRow]) -> tuple[str, str]:
	return _format_csv_rows(
		"HNB",
		[
			"Account No",
			"Bank Code",
			"Branch Code",
			"Beneficiary Name",
			"Amount",
			"Reference",
			"Value Date",
		],
		lambda r, _h, d: [
			_clean_digits(r.account_no),
			_clean_digits(r.bank_code).zfill(4),
			_clean_digits(r.branch_code).zfill(3),
			_clean_text(r.payee_name, 50),
			f"{flt(r.amount, 2):.2f}",
			_clean_text(r.reference, 30),
			d,
		],
		header,
		rows,
	)


def _format_boc(header: BankPaymentHeader, rows: list[BankPaymentRow]) -> tuple[str, str]:
	return _format_csv_rows(
		"BOC",
		[
			"Bank Code",
			"Branch Code",
			"Account Number",
			"Payee Name",
			"Amount",
			"Reference",
			"Value Date",
		],
		lambda r, _h, d: [
			_clean_digits(r.bank_code).zfill(4),
			_clean_digits(r.branch_code).zfill(3),
			_clean_digits(r.account_no),
			_clean_text(r.payee_name, 50),
			f"{flt(r.amount, 2):.2f}",
			_clean_text(r.reference, 30),
			d,
		],
		header,
		rows,
	)


BANK_FORMATTERS = {
	"SLIPS": _format_slips,
	"COMBANK": _format_combank,
	"SAMPATH": _format_sampath,
	"HNB": _format_hnb,
	"BOC": _format_boc,
}


def generate_bank_payment_file(
	bank_format: str,
	header: BankPaymentHeader,
	rows: list[BankPaymentRow],
) -> BankPaymentResult:
	"""Validate batch and render a Sri Lanka bank upload file in the requested format."""
	fmt = (bank_format or "SLIPS").strip().upper()
	if fmt not in BANK_FORMATTERS:
		frappe.throw(
			_("Unsupported bank file format '{0}'. Supported formats: {1}").format(
				bank_format, ", ".join(sorted(BANK_FORMATTERS))
			)
		)

	validate_payment_batch(header, rows)
	filename, content = BANK_FORMATTERS[fmt](header, rows)
	total_amount = flt(sum(flt(r.amount, 2) for r in rows), 2)

	return BankPaymentResult(
		filename=filename,
		content=content,
		bank_format=fmt,
		record_count=len(rows),
		total_amount=total_amount,
	)


def _get_company_bank_header(company: str, bank_account_name: str, value_date, batch_reference: str, tx_type: str):
	bank_acct = frappe.get_cached_doc("Bank Account", bank_account_name)
	bank_code = frappe.db.get_value("Bank", bank_acct.bank, "sri_lanka_bank_code") if bank_acct.bank else ""
	branch_code = bank_acct.get("sri_lanka_branch_code") or ""
	return BankPaymentHeader(
		company_name=company,
		company_bank_code=bank_code or "",
		company_branch_code=branch_code or "",
		company_account_no=bank_acct.bank_account_no or "",
		value_date=value_date,
		batch_reference=batch_reference,
		currency=frappe.get_cached_value("Company", company, "default_currency") or DEFAULT_CURRENCY,
		transaction_type=tx_type,
	)


@frappe.whitelist()
def generate_payment_order_bank_file(payment_order_name: str, bank_format: str = "SLIPS") -> dict:
	"""Generate a Sri Lanka bank payment file from a submitted or draft Payment Order."""
	po = frappe.get_doc("Payment Order", payment_order_name)
	po.check_permission("read")

	if get_region(po.company) != COUNTRY_NAME:
		frappe.throw(_("Bank payment file generation is only enabled for Sri Lanka companies."))

	header = _get_company_bank_header(
		company=po.company,
		bank_account_name=po.company_bank_account,
		value_date=po.posting_date or frappe.utils.nowdate(),
		batch_reference=po.name,
		tx_type="SUPPLIER",
	)

	rows: list[BankPaymentRow] = []
	for ref in po.get("references") or []:
		bank_acct_name = ref.get("bank_account")
		bank_acct = frappe.get_cached_doc("Bank Account", bank_acct_name) if bank_acct_name else None
		bank_code = (
			frappe.db.get_value("Bank", bank_acct.bank, "sri_lanka_bank_code")
			if bank_acct and bank_acct.bank
			else ""
		)
		party_name = ref.get("supplier") or (bank_acct.party if bank_acct else "") or ref.get("reference_name")
		rows.append(
			BankPaymentRow(
				payee_name=party_name or "",
				bank_code=bank_code or "",
				branch_code=(bank_acct.get("sri_lanka_branch_code") if bank_acct else "") or "",
				account_no=(bank_acct.bank_account_no if bank_acct else "") or "",
				amount=flt(ref.get("amount"), 2),
				reference=ref.get("reference_name") or po.name,
				row_idx=ref.idx,
			)
		)

	result = generate_bank_payment_file(bank_format, header, rows)
	return {
		"filename": result.filename,
		"content": result.content,
		"bank_format": result.bank_format,
		"record_count": result.record_count,
		"total_amount": result.total_amount,
	}


@frappe.whitelist()
def generate_payroll_bank_file(payroll_entry_name: str, bank_format: str = "SLIPS") -> dict:
	"""Generate a Sri Lanka salary bank upload file from an HRMS Payroll Entry."""
	if not frappe.db.exists("DocType", "Payroll Entry"):
		frappe.throw(_("HRMS Payroll Entry is not installed on this site."))

	pe = frappe.get_doc("Payroll Entry", payroll_entry_name)
	pe.check_permission("read")

	if get_region(pe.company) != COUNTRY_NAME:
		frappe.throw(_("Bank payment file generation is only enabled for Sri Lanka companies."))

	if not pe.get("payment_account"):
		frappe.throw(_("Please select a Payment Account on Payroll Entry {0}.").format(pe.name))

	company_bank_account = frappe.db.get_value(
		"Bank Account",
		{"account": pe.payment_account, "is_company_account": 1},
		"name",
	)
	if not company_bank_account:
		frappe.throw(
			_("No Company Bank Account is linked to Payment Account {0}.").format(pe.payment_account)
		)

	header = _get_company_bank_header(
		company=pe.company,
		bank_account_name=company_bank_account,
		value_date=pe.posting_date or pe.end_date or frappe.utils.nowdate(),
		batch_reference=pe.name,
		tx_type="SALARY",
	)

	slips = frappe.get_all(
		"Salary Slip",
		filters={"payroll_entry": pe.name, "docstatus": ["!=", 2]},
		fields=["name", "employee", "employee_name", "net_pay", "bank_name", "bank_account_no"],
		order_by="employee asc",
	)

	rows: list[BankPaymentRow] = []
	for idx, slip in enumerate(slips, start=1):
		emp = frappe.db.get_value(
			"Employee",
			slip.employee,
			["sri_lanka_bank_code", "sri_lanka_branch_code", "nic_number", "bank_ac_no"],
			as_dict=True,
		) or {}
		bank_code = emp.get("sri_lanka_bank_code") or (
			frappe.db.get_value("Bank", slip.bank_name, "sri_lanka_bank_code") if slip.bank_name else ""
		)
		rows.append(
			BankPaymentRow(
				payee_name=slip.employee_name or slip.employee,
				bank_code=bank_code or "",
				branch_code=emp.get("sri_lanka_branch_code") or "",
				account_no=slip.bank_account_no or emp.get("bank_ac_no") or "",
				amount=flt(slip.net_pay, 2),
				reference=slip.name,
				nic_or_id=emp.get("nic_number") or "",
				row_idx=idx,
			)
		)

	result = generate_bank_payment_file(bank_format, header, rows)
	return {
		"filename": result.filename,
		"content": result.content,
		"bank_format": result.bank_format,
		"record_count": result.record_count,
		"total_amount": result.total_amount,
	}
