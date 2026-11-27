# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json
import sys
import types
import unittest
from pathlib import Path


def _install_frappe_stub_if_missing():
	"""Allow pure-logic unit tests to run standalone when frappe/bench is not installed."""
	if "frappe" in sys.modules:
		return
	try:
		import frappe  # noqa: F401
		return
	except ImportError:
		pass

	class _ValidationError(Exception):
		pass

	class _Dict(dict):
		def __getattr__(self, key):
			return self.get(key)

		def __setattr__(self, key, value):
			self[key] = value

	frappe_mod = types.ModuleType("frappe")
	frappe_mod.__path__ = []
	frappe_mod.ValidationError = _ValidationError
	frappe_mod._ = lambda s: s
	frappe_mod._dict = _Dict
	frappe_mod.bold = lambda s: str(s)
	frappe_mod.whitelist = lambda *a, **kw: (lambda fn: fn)

	def _throw(msg, title=None):
		raise _ValidationError(msg)

	frappe_mod.throw = _throw
	frappe_mod.db = types.SimpleNamespace(exists=lambda *a, **kw: False, get_value=lambda *a, **kw: None)
	frappe_mod.has_permission = lambda *a, **kw: True
	frappe_mod.get_all = lambda *a, **kw: []
	frappe_mod.get_doc = lambda *a, **kw: None
	frappe_mod.get_cached_doc = lambda *a, **kw: None
	frappe_mod.get_cached_value = lambda *a, **kw: None

	utils_mod = types.ModuleType("frappe.utils")

	def _flt(val, precision=None):
		num = float(val or 0.0)
		return round(num, int(precision)) if precision is not None else num

	from datetime import date, datetime

	def _getdate(val):
		if isinstance(val, datetime):
			return val.date()
		if isinstance(val, date):
			return val
		return datetime.strptime(str(val), "%Y-%m-%d").date()

	utils_mod.flt = _flt
	utils_mod.getdate = _getdate
	utils_mod.nowdate = lambda: "2026-11-25"

	erpnext_mod = types.ModuleType("erpnext")
	erpnext_mod.__path__ = [str(Path(__file__).resolve().parents[2])]
	erpnext_mod.get_region = lambda company=None: "Sri Lanka"

	ctrl_mod = types.ModuleType("erpnext.controllers")
	taxes_mod = types.ModuleType("erpnext.controllers.taxes_and_totals")
	taxes_mod.get_itemised_tax = lambda doc: {}

	model_mod = types.ModuleType("frappe.model")
	doc_mod = types.ModuleType("frappe.model.document")

	class _Document:
		def __init__(self, d=None):
			for k, v in (d or {}).items():
				setattr(self, k, v)

		def get(self, key, default=None):
			return getattr(self, key, default)

		def __getattr__(self, key):
			return None

		def append(self, key, value):
			lst = getattr(self, key, None)
			if lst is None:
				lst = []
				setattr(self, key, lst)
			row = _Dict(value) if isinstance(value, dict) else value
			lst.append(row)
			return row

	doc_mod.Document = _Document
	rename_mod = types.ModuleType("frappe.model.rename_doc")
	rename_mod.rename_doc = lambda *a, **kw: None
	custom_mod = types.ModuleType("frappe.custom")
	custom_dt_mod = types.ModuleType("frappe.custom.doctype")
	custom_cf_pkg = types.ModuleType("frappe.custom.doctype.custom_field")
	custom_cf_mod = types.ModuleType("frappe.custom.doctype.custom_field.custom_field")
	custom_cf_mod.create_custom_fields = lambda *a, **kw: None
	perms_mod = types.ModuleType("frappe.permissions")
	perms_mod.add_permission = lambda *a, **kw: None
	perms_mod.update_permission_property = lambda *a, **kw: None

	sys.modules["frappe"] = frappe_mod
	sys.modules["frappe.model"] = model_mod
	sys.modules["frappe.model.document"] = doc_mod
	sys.modules["frappe.model.rename_doc"] = rename_mod
	sys.modules["frappe.custom"] = custom_mod
	sys.modules["frappe.custom.doctype"] = custom_dt_mod
	sys.modules["frappe.custom.doctype.custom_field"] = custom_cf_pkg
	sys.modules["frappe.custom.doctype.custom_field.custom_field"] = custom_cf_mod
	sys.modules["frappe.permissions"] = perms_mod
	sys.modules["frappe.utils"] = utils_mod
	sys.modules["erpnext"] = erpnext_mod
	sys.modules["erpnext.controllers"] = ctrl_mod
	sys.modules["erpnext.controllers.taxes_and_totals"] = taxes_mod


_install_frappe_stub_if_missing()

import frappe  # noqa: E402

from erpnext.regional.doctype.sri_lanka_payroll_entry.sri_lanka_payroll_entry import (  # noqa: E402
	SriLankaPayrollEntry,
)
from erpnext.regional.sri_lanka.bank_payment import (  # noqa: E402
	BankPaymentHeader,
	BankPaymentRow,
	generate_bank_payment_file,
	generate_sri_lanka_payroll_bank_file,
	validate_payment_batch,
)
from erpnext.regional.sri_lanka.payroll import (  # noqa: E402
	apply_sri_lanka_payroll_deductions,
	build_payroll_journal_accounts,
	calculate_apit,
	calculate_apit_with_lump_sum,
	calculate_epf_etf,
	calculate_payroll_row,
	get_epf_liable_earnings,
	get_sri_lanka_payroll_records,
)
from erpnext.regional.sri_lanka.setup import (  # noqa: E402
	_insert_items_after_link,
	_insert_items_in_section,
)
from erpnext.regional.sri_lanka.utils import validate_sri_lanka_report_filters  # noqa: E402
from erpnext.regional.sri_lanka.vat import (  # noqa: E402
	classify_vat_supply,
	compute_vat_return_summary,
	validate_sri_lanka_invoice,
)


class TestSriLankaVAT(unittest.TestCase):
	def test_classify_vat_supply(self):
		self.assertEqual(classify_vat_supply(tax_rate=18.0), "Standard Rated")
		self.assertEqual(classify_vat_supply(is_zero_rated=True, tax_rate=0.0), "Zero Rated")
		self.assertEqual(classify_vat_supply(is_export=True, tax_rate=0.0), "Zero Rated")
		self.assertEqual(classify_vat_supply(is_exempt=True, tax_rate=0.0), "Exempt")

	def test_compute_vat_return_summary(self):
		sales = [
			{"net_amount": 100000.0, "vat_amount": 18000.0, "tax_rate": 18.0},
			{"net_amount": 50000.0, "vat_amount": 0.0, "is_zero_rated": True},
			{"net_amount": 25000.0, "vat_amount": 0.0, "is_exempt": True},
			{"net_amount": -10000.0, "vat_amount": -1800.0, "tax_rate": 18.0, "is_return": True},
		]
		purchases = [
			{"net_amount": 40000.0, "vat_amount": 7200.0, "tax_rate": 18.0},
			{"net_amount": 15000.0, "vat_amount": 0.0, "is_exempt": True},
			{"net_amount": -5000.0, "vat_amount": -900.0, "tax_rate": 18.0, "is_return": True},
		]

		summary = compute_vat_return_summary(sales, purchases)
		self.assertEqual(summary.standard_rated_sales, 100000.0)
		self.assertEqual(summary.output_vat, 18000.0)
		self.assertEqual(summary.zero_rated_sales, 50000.0)
		self.assertEqual(summary.exempt_sales, 25000.0)
		self.assertEqual(summary.sales_credit_notes, 10000.0)
		self.assertEqual(summary.output_vat_adjustments, -1800.0)
		self.assertEqual(summary.standard_rated_purchases, 40000.0)
		self.assertEqual(summary.input_vat_claimable, 7200.0)
		self.assertEqual(summary.exempt_purchases, 15000.0)
		self.assertEqual(summary.purchase_debit_notes, 5000.0)
		self.assertEqual(summary.input_vat_adjustments, -900.0)
		# Net Output (18000 - 1800 = 16200) - Net Input (7200 - 900 = 6300) = 9900
		self.assertEqual(summary.net_vat_payable, 9900.0)

	def test_compute_vat_return_summary_invoice_level_vat_without_item_tax_rate(self):
		summary = compute_vat_return_summary(
			[{"net_amount": 100000.0, "vat_amount": 18000.0, "tax_rate": 0.0}],
			[{"net_amount": 50000.0, "vat_amount": 9000.0, "tax_rate": 0.0}],
		)
		self.assertEqual(summary.standard_rated_sales, 100000.0)
		self.assertEqual(summary.output_vat, 18000.0)
		self.assertEqual(summary.standard_rated_purchases, 50000.0)
		self.assertEqual(summary.input_vat_claimable, 9000.0)
		self.assertEqual(summary.net_vat_payable, 9000.0)

	def test_validate_invoice_rejects_exempt_and_zero_rated_together(self):
		doc = frappe._dict(
			doctype="Sales Invoice",
			company="Lanka Co",
			vat_invoice_type="Simplified Tax Invoice",
			items=[
				frappe._dict(idx=1, item_code="ITEM-1", is_exempt=1, is_zero_rated=1, tax_rate=0.0)
			],
		)
		with self.assertRaises(frappe.ValidationError):
			validate_sri_lanka_invoice(doc)

	def test_validate_invoice_rejects_positive_vat_on_exempt_item(self):
		doc = frappe._dict(
			doctype="Sales Invoice",
			company="Lanka Co",
			vat_invoice_type="Simplified Tax Invoice",
			items=[
				frappe._dict(idx=1, item_code="ITEM-EX", is_exempt=1, is_zero_rated=0, tax_rate=18.0)
			],
		)
		with self.assertRaises(frappe.ValidationError):
			validate_sri_lanka_invoice(doc)

	def test_validate_tax_invoice_requires_customer_vat_reg_no(self):
		doc = frappe._dict(
			doctype="Sales Invoice",
			company="Lanka Co",
			vat_invoice_type="Tax Invoice",
			company_vat_reg_no="123456789-7000",
			customer_vat_reg_no="",
			tax_id="",
			items=[frappe._dict(idx=1, item_code="ITEM-1", is_exempt=0, is_zero_rated=0, tax_rate=18.0)],
		)
		with self.assertRaises(frappe.ValidationError):
			validate_sri_lanka_invoice(doc)


class TestSriLankaPayroll(unittest.TestCase):
	def test_epf_liable_earnings_filters_non_liable_components(self):
		earnings = [
			{"salary_component": "Basic Salary", "amount": 100000.0, "is_epf_etf_applicable": True},
			{"salary_component": "BRA", "amount": 10000.0, "is_epf_etf_applicable": True},
			{"salary_component": "Fuel Allowance", "amount": 15000.0, "is_epf_etf_applicable": False},
		]
		self.assertEqual(get_epf_liable_earnings(earnings), 110000.0)

	def test_calculate_epf_etf(self):
		res = calculate_epf_etf(100000.0)
		self.assertEqual(res.liable_earnings, 100000.0)
		self.assertEqual(res.epf_employee, 8000.0)
		self.assertEqual(res.epf_employer, 12000.0)
		self.assertEqual(res.epf_total, 20000.0)
		self.assertEqual(res.etf_employer, 3000.0)

	def test_calculate_epf_etf_zero_and_negative_rate(self):
		zero = calculate_epf_etf(0.0)
		self.assertEqual(zero.epf_total, 0.0)
		self.assertEqual(zero.etf_employer, 0.0)
		with self.assertRaises(frappe.ValidationError):
			calculate_epf_etf(50000.0, epf_employee_rate=-1.0)

	def test_calculate_apit_progressive_slabs(self):
		# Up to 150,000 -> 0
		self.assertEqual(calculate_apit(150000.0), 0.0)
		# 200,000 -> (200,000 - 150,000) * 6% = 3,000
		self.assertEqual(calculate_apit(200000.0), 3000.0)
		# 300,000:
		# 0..150,000 = 0
		# 150,000..233,333.33 = 83,333.33 * 6% = 5,000.00
		# 233,333.33..275,000 = 41,666.67 * 18% = 7,500.00
		# 275,000..300,000 = 25,000 * 24% = 6,000.00
		# Total = 18,500.00
		self.assertEqual(calculate_apit(300000.0), 18500.0)

	def test_calculate_apit_non_resident_and_lump_sum(self):
		self.assertEqual(calculate_apit(200000.0, is_non_resident=True, non_resident_rate=25.0), 50000.0)

		bonus_res = calculate_apit_with_lump_sum(
			regular_monthly_income=150000.0,
			lump_sum_amount=120000.0,
		)
		# Monthly equivalent = 150,000 + 10,000 = 160,000 -> monthly tax 600 -> annual 7,200
		self.assertEqual(bonus_res.regular_tax, 0.0)
		self.assertEqual(bonus_res.lump_sum_tax, 7200.0)
		self.assertEqual(bonus_res.total_tax, 7200.0)

	def test_calculate_payroll_row_and_journal_accounts(self):
		row = frappe._dict(
			basic_salary=180000.0,
			epf_liable_allowances=20000.0,
			non_epf_allowances=15000.0,
			lump_sum_bonus=0.0,
			other_deductions=5000.0,
			is_non_resident_for_apit=0,
		)
		res = calculate_payroll_row(row)
		self.assertEqual(res["gross_pay"], 215000.0)
		self.assertEqual(res["epf_liable_earnings"], 200000.0)
		self.assertEqual(res["epf_employee"], 16000.0)
		self.assertEqual(res["epf_employer"], 24000.0)
		self.assertEqual(res["etf_employer"], 6000.0)
		# APIT on 215,000 = (215,000 - 150,000) * 6% = 3,900
		self.assertEqual(res["apit_tax"], 3900.0)
		self.assertEqual(res["total_deduction"], 24900.0)
		self.assertEqual(res["net_pay"], 190100.0)

		je_doc = frappe._dict(
			total_gross_pay=res["gross_pay"],
			total_epf_employee=res["epf_employee"],
			total_epf_employer=res["epf_employer"],
			total_etf_employer=res["etf_employer"],
			total_apit=res["apit_tax"],
			total_other_deductions=5000.0,
			total_net_pay=res["net_pay"],
			salary_expense_account="Salaries - LK",
			payroll_payable_account="Payroll Payable - LK",
			epf_employer_expense_account="EPF Expense - LK",
			etf_employer_expense_account="ETF Expense - LK",
			epf_payable_account="EPF Payable - LK",
			etf_payable_account="ETF Payable - LK",
			apit_payable_account="APIT Payable - LK",
		)
		accounts = build_payroll_journal_accounts(je_doc)
		total_debit = sum(a.get("debit_in_account_currency", 0.0) for a in accounts)
		total_credit = sum(a.get("credit_in_account_currency", 0.0) for a in accounts)
		self.assertEqual(round(total_debit, 2), round(total_credit, 2))
		self.assertEqual(total_debit, 245000.0)

	def test_sri_lanka_payroll_entry_validate_totals(self):
		entry = SriLankaPayrollEntry(
			{
				"company": "Lanka Co",
				"posting_date": "2026-11-30",
				"from_date": "2026-11-01",
				"to_date": "2026-11-30",
				"post_journal_entry": 0,
				"employees": [
					frappe._dict(
						idx=1,
						employee="HR-EMP-0001",
						basic_salary=100000.0,
						epf_liable_allowances=0.0,
						non_epf_allowances=0.0,
						lump_sum_bonus=0.0,
						other_deductions=0.0,
						is_non_resident_for_apit=0,
					),
					frappe._dict(
						idx=2,
						employee="HR-EMP-0002",
						basic_salary=200000.0,
						epf_liable_allowances=0.0,
						non_epf_allowances=0.0,
						lump_sum_bonus=0.0,
						other_deductions=0.0,
						is_non_resident_for_apit=0,
					),
				],
			}
		)
		entry.validate()
		self.assertEqual(entry.total_employees, 2)
		self.assertEqual(entry.total_gross_pay, 300000.0)
		self.assertEqual(entry.total_epf_employee, 24000.0)
		self.assertEqual(entry.total_epf_employer, 36000.0)
		self.assertEqual(entry.total_etf_employer, 9000.0)
		self.assertEqual(entry.total_apit, 3000.0)
		self.assertEqual(entry.total_net_pay, 273000.0)

		dup_entry = SriLankaPayrollEntry(
			{
				"company": "Lanka Co",
				"posting_date": "2026-11-30",
				"from_date": "2026-11-01",
				"to_date": "2026-11-30",
				"employees": [
					frappe._dict(idx=1, employee="HR-EMP-0001", basic_salary=100000.0),
					frappe._dict(idx=2, employee="HR-EMP-0001", basic_salary=100000.0),
				],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			dup_entry.validate()

		over_ded_entry = SriLankaPayrollEntry(
			{
				"company": "Lanka Co",
				"posting_date": "2026-11-30",
				"from_date": "2026-11-01",
				"to_date": "2026-11-30",
				"employees": [
					frappe._dict(
						idx=1,
						employee="HR-EMP-0001",
						basic_salary=50000.0,
						other_deductions=60000.0,
					),
				],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			over_ded_entry.validate()

	def test_apply_sri_lanka_payroll_deductions_updates_net_pay(self):
		orig_exists = frappe.db.exists
		orig_get_value = frappe.db.get_value
		orig_get_cached_doc = getattr(frappe, "get_cached_doc", None)
		try:
			settings = frappe._dict(
				auto_calculate_statutory=1,
				epf_employee_rate=8.0,
				epf_employer_rate=12.0,
				etf_employer_rate=3.0,
				epf_employee_component="EPF Employee",
				apit_component="APIT / PAYE",
				non_resident_apit_rate=25.0,
				apit_slabs=[],
			)
			frappe.db.exists = lambda dt, name=None: dt == "Sri Lanka Payroll Settings" and name == "Lanka Co"
			frappe.get_cached_doc = lambda dt, name=None: settings
			frappe.db.get_value = lambda dt, name, field, **kw: (
				1 if (dt == "Salary Component" and name == "Basic Salary" and field == "is_epf_etf_applicable") else 0
			)

			slip = frappe._dict(
				company="Lanka Co",
				employee="HR-EMP-0001",
				gross_pay=200000.0,
				exchange_rate=1.0,
				earnings=[frappe._dict(salary_component="Basic Salary", amount=200000.0)],
				deductions=[],
			)
			slip.append = lambda key, val: slip[key].append(frappe._dict(val))

			apply_sri_lanka_payroll_deductions(slip)
			self.assertEqual(slip.epf_liable_earnings, 200000.0)
			self.assertEqual(slip.epf_employer_contribution, 24000.0)
			self.assertEqual(slip.etf_employer_contribution, 6000.0)
			self.assertEqual(slip.apit_tax_amount, 3000.0)
			# Total deduction = 16,000 (EPF 8%) + 3,000 (APIT) = 19,000; net_pay = 181,000
			self.assertEqual(slip.total_deduction, 19000.0)
			self.assertEqual(slip.net_pay, 181000.0)
		finally:
			frappe.db.exists = orig_exists
			frappe.db.get_value = orig_get_value
			frappe.get_cached_doc = orig_get_cached_doc

	def test_get_sri_lanka_payroll_records_standalone_without_hrms(self):
		orig_exists = frappe.db.exists
		orig_get_all = frappe.get_all
		orig_get_cached_value = frappe.get_cached_value
		orig_get_installed_apps = getattr(frappe, "get_installed_apps", None)
		try:
			# Even if leftover Salary Slip DocType metadata exists, skip querying it when hrms is not installed
			frappe.db.exists = lambda dt, name=None: dt == "DocType" and name in (
				"Sri Lanka Payroll Entry",
				"Salary Slip",
			)
			frappe.get_installed_apps = lambda: ["frappe", "erpnext"]
			frappe.get_cached_value = lambda *a, **kw: "LKR"

			def _fake_get_all(dt, **kw):
				if dt == "Salary Slip":
					raise AssertionError("Salary Slip should not be queried when hrms is not installed")
				if dt == "Sri Lanka Payroll Entry":
					return ["SL-PAY-2026-11-0001"]
				if dt == "Sri Lanka Payroll Employee":
					return [
						frappe._dict(
							employee="HR-EMP-0001",
							employee_name="Nimal Perera",
							epf_number="1001",
							nic_number="199012345678",
							is_non_resident_for_apit=0,
							gross_pay=200000.0,
							epf_liable_earnings=200000.0,
							epf_employee=16000.0,
							epf_employer=24000.0,
							etf_employer=6000.0,
							apit_tax=3000.0,
						)
					]
				return []

			frappe.get_all = _fake_get_all
			records = get_sri_lanka_payroll_records(
				frappe._dict(company="Lanka Co", from_date="2026-11-01", to_date="2026-11-30")
			)
			self.assertEqual(len(records), 1)
			self.assertEqual(records[0]["epf_total"], 40000.0)
			self.assertEqual(records[0]["etf_employer"], 6000.0)
			self.assertEqual(records[0]["apit_tax_amount"], 3000.0)
		finally:
			frappe.db.exists = orig_exists
			frappe.get_all = orig_get_all
			frappe.get_cached_value = orig_get_cached_value
			if orig_get_installed_apps is None:
				if hasattr(frappe, "get_installed_apps"):
					delattr(frappe, "get_installed_apps")
			else:
				frappe.get_installed_apps = orig_get_installed_apps

	def test_get_sri_lanka_payroll_records_preserves_zero_epf_base_in_hrms(self):
		orig_exists = frappe.db.exists
		orig_get_all = frappe.get_all
		orig_get_value = frappe.db.get_value
		orig_get_cached_value = frappe.get_cached_value
		orig_get_installed_apps = getattr(frappe, "get_installed_apps", None)
		try:
			frappe.db.exists = lambda dt, name=None: dt == "DocType" and name == "Salary Slip"
			frappe.get_installed_apps = lambda: ["frappe", "erpnext", "hrms"]
			frappe.get_cached_value = lambda *a, **kw: "LKR"
			frappe.db.get_value = lambda *a, **kw: {}

			def _fake_get_all(dt, **kw):
				if dt == "Salary Slip":
					return [
						frappe._dict(
							employee="HR-EMP-0002",
							employee_name="Zero EPF",
							gross_pay=50000.0,
							epf_liable_earnings=0.0,
							apit_tax_amount=0.0,
						)
					]
				return []

			frappe.get_all = _fake_get_all
			records = get_sri_lanka_payroll_records(
				frappe._dict(company="Lanka Co", from_date="2026-11-01", to_date="2026-11-30")
			)
			self.assertEqual(len(records), 1)
			self.assertEqual(records[0]["liable_earnings"], 0.0)
			self.assertEqual(records[0]["epf_employee"], 0.0)
			self.assertEqual(records[0]["apit_tax_amount"], 0.0)
		finally:
			frappe.db.exists = orig_exists
			frappe.get_all = orig_get_all
			frappe.db.get_value = orig_get_value
			frappe.get_cached_value = orig_get_cached_value
			if orig_get_installed_apps is None:
				if hasattr(frappe, "get_installed_apps"):
					delattr(frappe, "get_installed_apps")
			else:
				frappe.get_installed_apps = orig_get_installed_apps


class TestSriLankaBankPayment(unittest.TestCase):
	def setUp(self):
		self.header = BankPaymentHeader(
			company_name="Lanka Tech Pvt Ltd",
			company_bank_code="7056",
			company_branch_code="001",
			company_account_no="1002345678",
			value_date="2026-11-25",
			batch_reference="PAY-2026-11",
			currency="LKR",
			transaction_type="SALARY",
		)
		self.rows = [
			BankPaymentRow(
				payee_name="Nimal Perera",
				bank_code="7010",
				branch_code="045",
				account_no="80012345",
				amount=125000.50,
				reference="SAL-SLIP-001",
				nic_or_id="199012345678",
				row_idx=1,
			),
			BankPaymentRow(
				payee_name="Kamal Silva",
				bank_code="7278",
				branch_code="012",
				account_no="1009988776",
				amount=84500.00,
				reference="SAL-SLIP-002",
				nic_or_id="925431234V",
				row_idx=2,
			),
		]

	def test_generate_slips_fixed_width(self):
		res = generate_bank_payment_file("SLIPS", self.header, self.rows)
		self.assertEqual(res.bank_format, "SLIPS")
		self.assertEqual(res.record_count, 2)
		self.assertEqual(res.total_amount, 209500.50)
		self.assertTrue(res.filename.endswith(".txt"))

		lines = res.content.strip().splitlines()
		self.assertEqual(len(lines), 4)  # 1 Header + 2 Detail + 1 Trailer
		self.assertTrue(lines[0].startswith("H705600100100234567820261125"))
		self.assertTrue(lines[1].startswith("D0000017010045000080012345"))
		self.assertIn("000001250005023", lines[1])  # 125000.50 -> 12500050 cents + tx code 23
		self.assertTrue(lines[3].startswith("T000002000000020950050"))

	def test_generate_csv_bank_formats(self):
		for fmt in ("COMBANK", "SAMPATH", "HNB", "BOC"):
			res = generate_bank_payment_file(fmt, self.header, self.rows)
			self.assertEqual(res.bank_format, fmt)
			self.assertTrue(res.filename.endswith(".csv"))
			self.assertEqual(len(res.content.strip().splitlines()), 3)

	def test_validate_payment_batch_catches_invalid_codes(self):
		bad_rows = [
			BankPaymentRow(
				payee_name="",
				bank_code="70",
				branch_code="1",
				account_no="",
				amount=0.0,
				reference="",
				row_idx=1,
			)
		]
		with self.assertRaises(frappe.ValidationError):
			validate_payment_batch(self.header, bad_rows)

	def test_slips_rejects_account_number_over_12_digits(self):
		long_acct_rows = [
			BankPaymentRow(
				payee_name="Nimal Perera",
				bank_code="7010",
				branch_code="045",
				account_no="123456789012345",
				amount=50000.0,
				reference="SAL-001",
				row_idx=1,
			)
		]
		with self.assertRaises(frappe.ValidationError):
			generate_bank_payment_file("SLIPS", self.header, long_acct_rows)
		# CSV formats allow up to 20 digits
		csv_res = generate_bank_payment_file("COMBANK", self.header, long_acct_rows)
		self.assertEqual(csv_res.record_count, 1)

	def test_generate_sri_lanka_payroll_bank_file(self):
		orig_get_doc = getattr(frappe, "get_doc", None)
		orig_get_cached_doc = getattr(frappe, "get_cached_doc", None)
		orig_get_value = frappe.db.get_value
		orig_get_cached_value = frappe.get_cached_value
		try:
			pe = frappe._dict(
				name="SL-PAY-2026-11-0001",
				docstatus=1,
				company="Lanka Tech Pvt Ltd",
				company_bank_account="ComBank Main",
				posting_date="2026-11-25",
				bank_file_format="SLIPS",
				employees=[
					frappe._dict(
						idx=1,
						employee="HR-EMP-0001",
						employee_name="Nimal Perera",
						bank_name="Bank of Ceylon",
						bank_code="7010",
						branch_code="045",
						bank_account_no="80012345",
						net_pay=125000.50,
						nic_number="199012345678",
					),
					frappe._dict(
						idx=2,
						employee="HR-EMP-0002",
						employee_name="Zero Net Pay",
						bank_name="Bank of Ceylon",
						bank_code="7010",
						branch_code="045",
						bank_account_no="80012346",
						net_pay=0.0,
						nic_number="199112345678",
					),
				],
			)
			pe.check_permission = lambda *a, **kw: None
			comp_bank = frappe._dict(bank="Commercial Bank of Ceylon", sri_lanka_branch_code="001", bank_account_no="1002345678")

			frappe.get_doc = lambda dt, name=None: pe
			frappe.get_cached_doc = lambda dt, name=None: comp_bank
			frappe.get_cached_value = lambda dt, name, field: "LKR"
			frappe.db.get_value = lambda dt, name, field, **kw: (
				"7056" if dt == "Bank" else {}
			)

			res = generate_sri_lanka_payroll_bank_file("SL-PAY-2026-11-0001")
			self.assertEqual(res["bank_format"], "SLIPS")
			self.assertEqual(res["record_count"], 1)
			self.assertEqual(res["total_amount"], 125000.50)
			self.assertTrue(res["filename"].startswith("SLIPS_SL-PAY-2026-11-0001_20261125"))

			pe.docstatus = 0
			with self.assertRaises(frappe.ValidationError):
				generate_sri_lanka_payroll_bank_file("SL-PAY-2026-11-0001")
		finally:
			frappe.get_doc = orig_get_doc
			frappe.get_cached_doc = orig_get_cached_doc
			frappe.db.get_value = orig_get_value
			frappe.get_cached_value = orig_get_cached_value


class TestSriLankaMetadataJSON(unittest.TestCase):
	def test_regional_json_files_valid(self):
		repo_root = Path(__file__).resolve().parents[3]
		json_paths = [
			repo_root / "erpnext/setup/setup_wizard/data/country_wise_tax.json",
			repo_root / "erpnext/regional/doctype/sri_lanka_vat_settings/sri_lanka_vat_settings.json",
			repo_root / "erpnext/regional/doctype/sri_lanka_vat_account/sri_lanka_vat_account.json",
			repo_root / "erpnext/regional/doctype/sri_lanka_payroll_settings/sri_lanka_payroll_settings.json",
			repo_root / "erpnext/regional/doctype/sri_lanka_apit_slab/sri_lanka_apit_slab.json",
			repo_root / "erpnext/regional/doctype/sri_lanka_payroll_entry/sri_lanka_payroll_entry.json",
			repo_root / "erpnext/regional/doctype/sri_lanka_payroll_employee/sri_lanka_payroll_employee.json",
			repo_root / "erpnext/regional/print_format/sri_lanka_tax_invoice/sri_lanka_tax_invoice.json",
			repo_root / "erpnext/regional/print_format/sri_lanka_simplified_tax_invoice/sri_lanka_simplified_tax_invoice.json",
			repo_root / "erpnext/regional/print_format/sri_lanka_payslip/sri_lanka_payslip.json",
			repo_root / "erpnext/regional/report/sri_lanka_vat_return/sri_lanka_vat_return.json",
			repo_root / "erpnext/regional/report/sri_lanka_epf_c_form/sri_lanka_epf_c_form.json",
			repo_root / "erpnext/regional/report/sri_lanka_etf_return/sri_lanka_etf_return.json",
			repo_root / "erpnext/regional/report/sri_lanka_apit_schedule/sri_lanka_apit_schedule.json",
			repo_root / "erpnext/dock/erpnext/erpnext.json",
			repo_root / "erpnext/accounts/sidebar/accounts/accounts.json",
			repo_root / "erpnext/accounts/workspace/accounting/accounting.json",
		]
		for path in json_paths:
			self.assertTrue(path.exists(), f"Missing metadata file: {path}")
			with path.open(encoding="utf-8") as fh:
				data = json.load(fh)
			self.assertIsInstance(data, dict)

		tax_data = json.loads((repo_root / "erpnext/setup/setup_wizard/data/country_wise_tax.json").read_text(encoding="utf-8"))
		self.assertIn("Sri Lanka", tax_data)
		self.assertEqual(tax_data["Sri Lanka"]["Sri Lanka VAT 18%"]["tax_rate"], 18.0)

		accounts_sidebar = json.loads((repo_root / "erpnext/accounts/sidebar/accounts/accounts.json").read_text(encoding="utf-8"))
		sidebar_targets = {item.get("link_to") for item in accounts_sidebar.get("items", [])}
		self.assertIn("Sri Lanka VAT Settings", sidebar_targets)
		self.assertIn("Sri Lanka VAT Return", sidebar_targets)

		expected_hr_labels = {
			"Sri Lanka Payroll Entry": "Monthly Payroll Entry",
			"Sri Lanka Payroll Settings": "Payroll Settings",
			"Sri Lanka EPF C Form": "EPF C Form",
			"Sri Lanka ETF Return": "ETF Return",
			"Sri Lanka APIT Schedule": "APIT Schedule",
		}
		for hr_path in (
			repo_root / "erpnext/setup/sidebar/hr/hr.json",
			repo_root / "erpnext/workspace_sidebar/hr.json",
		):
			if not hr_path.exists():
				continue
			hr_sidebar = json.loads(hr_path.read_text(encoding="utf-8"))
			labels = {
				item.get("link_to"): item.get("label")
				for item in hr_sidebar.get("items", [])
				if item.get("link_to") in expected_hr_labels
			}
			self.assertEqual(labels, expected_hr_labels)

		hr_workspace_path = repo_root / "erpnext/setup/workspace/hr/hr.json"
		if hr_workspace_path.exists():
			hr_workspace = json.loads(hr_workspace_path.read_text(encoding="utf-8"))
			self.assertIsInstance(hr_workspace, dict)
			link_labels = {
				item.get("link_to"): item.get("label")
				for item in hr_workspace.get("links", [])
				if item.get("link_to") in expected_hr_labels
			}
			self.assertEqual(link_labels, expected_hr_labels)

	def test_sidebar_sync_updates_existing_sri_lanka_labels(self):
		items = [
			{"type": "Link", "link_to": "Payroll Entry", "label": "Payroll Entry"},
			{"type": "Link", "link_to": "Sri Lanka Payroll Entry", "label": "Sri Lanka Payroll Entry"},
			{"type": "Section Break", "label": "Reports"},
			{"type": "Link", "link_to": "Sri Lanka EPF C Form", "label": "Sri Lanka EPF C Form", "child": 1},
		]
		self.assertTrue(
			_insert_items_after_link(
				items,
				"Payroll Entry",
				[{"type": "Link", "link_to": "Sri Lanka Payroll Entry", "label": "Monthly Payroll Entry"}],
			)
		)
		self.assertTrue(
			_insert_items_in_section(
				items,
				"Reports",
				[
					{"type": "Link", "link_to": "Sri Lanka EPF C Form", "label": "EPF C Form", "child": 1},
					{"type": "Link", "link_to": "Sri Lanka ETF Return", "label": "ETF Return", "child": 1},
				],
			)
		)
		labels = {row.get("link_to"): row.get("label") for row in items if row.get("link_to")}
		self.assertEqual(labels["Sri Lanka Payroll Entry"], "Monthly Payroll Entry")
		self.assertEqual(labels["Sri Lanka EPF C Form"], "EPF C Form")
		self.assertEqual(labels["Sri Lanka ETF Return"], "ETF Return")

	def test_validate_sri_lanka_report_filters(self):
		res = validate_sri_lanka_report_filters(
			{"company": "Lanka Co", "from_date": "2026-11-01", "to_date": "2026-11-30"},
			"Sri Lanka VAT Return",
		)
		self.assertEqual(res.company, "Lanka Co")
		with self.assertRaises(frappe.ValidationError):
			validate_sri_lanka_report_filters(
				{"company": "Lanka Co", "from_date": "2026-11-30", "to_date": "2026-11-01"},
				"Sri Lanka VAT Return",
			)

	def test_sri_lanka_payroll_employee_print_columns_compact(self):
		repo_root = Path(__file__).resolve().parents[3]
		data = json.loads(
			(
				repo_root
				/ "erpnext/regional/doctype/sri_lanka_payroll_employee/sri_lanka_payroll_employee.json"
			).read_text(encoding="utf-8")
		)
		printable_fields = [
			f["fieldname"]
			for f in data["fields"]
			if f["fieldtype"] not in ("Section Break", "Column Break") and not f.get("print_hide")
		]
		self.assertEqual(
			printable_fields,
			["employee", "employee_name", "gross_pay", "epf_employee", "apit_tax", "net_pay"],
		)


if __name__ == "__main__":
	unittest.main()
