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
	rename_mod = types.ModuleType("frappe.model.rename_doc")
	rename_mod.rename_doc = lambda *a, **kw: None

	sys.modules["frappe"] = frappe_mod
	sys.modules["frappe.model"] = model_mod
	sys.modules["frappe.model.rename_doc"] = rename_mod
	sys.modules["frappe.utils"] = utils_mod
	sys.modules["erpnext"] = erpnext_mod
	sys.modules["erpnext.controllers"] = ctrl_mod
	sys.modules["erpnext.controllers.taxes_and_totals"] = taxes_mod


_install_frappe_stub_if_missing()

import frappe  # noqa: E402

from erpnext.regional.sri_lanka.bank_payment import (  # noqa: E402
	BankPaymentHeader,
	BankPaymentRow,
	generate_bank_payment_file,
	validate_payment_batch,
)
from erpnext.regional.sri_lanka.payroll import (  # noqa: E402
	calculate_apit,
	calculate_apit_with_lump_sum,
	calculate_epf_etf,
	get_epf_liable_earnings,
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


class TestSriLankaMetadataJSON(unittest.TestCase):
	def test_regional_json_files_valid(self):
		repo_root = Path(__file__).resolve().parents[3]
		json_paths = [
			repo_root / "erpnext/setup/setup_wizard/data/country_wise_tax.json",
			repo_root / "erpnext/regional/doctype/sri_lanka_vat_settings/sri_lanka_vat_settings.json",
			repo_root / "erpnext/regional/doctype/sri_lanka_vat_account/sri_lanka_vat_account.json",
			repo_root / "erpnext/regional/doctype/sri_lanka_payroll_settings/sri_lanka_payroll_settings.json",
			repo_root / "erpnext/regional/doctype/sri_lanka_apit_slab/sri_lanka_apit_slab.json",
			repo_root / "erpnext/regional/print_format/sri_lanka_tax_invoice/sri_lanka_tax_invoice.json",
			repo_root / "erpnext/regional/print_format/sri_lanka_simplified_tax_invoice/sri_lanka_simplified_tax_invoice.json",
			repo_root / "erpnext/regional/report/sri_lanka_vat_return/sri_lanka_vat_return.json",
			repo_root / "erpnext/regional/report/sri_lanka_epf_c_form/sri_lanka_epf_c_form.json",
			repo_root / "erpnext/regional/report/sri_lanka_etf_return/sri_lanka_etf_return.json",
			repo_root / "erpnext/regional/report/sri_lanka_apit_schedule/sri_lanka_apit_schedule.json",
		]
		for path in json_paths:
			self.assertTrue(path.exists(), f"Missing metadata file: {path}")
			with path.open(encoding="utf-8") as fh:
				data = json.load(fh)
			self.assertIsInstance(data, dict)

		tax_data = json.loads((repo_root / "erpnext/setup/setup_wizard/data/country_wise_tax.json").read_text(encoding="utf-8"))
		self.assertIn("Sri Lanka", tax_data)
		self.assertEqual(tax_data["Sri Lanka"]["Sri Lanka VAT 18%"]["tax_rate"], 18.0)

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


if __name__ == "__main__":
	unittest.main()
