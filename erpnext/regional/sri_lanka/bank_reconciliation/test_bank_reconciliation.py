# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import unittest
from erpnext.regional.sri_lanka.bank_reconciliation.parser import BankStatementParser
from erpnext.regional.sri_lanka.bank_reconciliation.matcher import BankReconciliationMatcher
from erpnext.regional.sri_lanka.bank_reconciliation.exceptions_queue import ReconciliationExceptionsQueue
from erpnext.regional.sri_lanka.bank_reconciliation.reconciliation import SriLankaBankReconciliation


class TestSriLankaBankReconciliation(unittest.TestCase):

	def setUp(self):
		self.sample_commercial_bank_csv = """Commercial Bank of Ceylon PLC - Statement
Txn Date,Particulars,Cheque No,Debit,Credit,Balance
10/05/2026,DEP TRF - PERERA AND SONS PVT LTD,,0.00,"45,000.00","45,000.00"
12/05/2026,CHQ 778812 PAYMENT TO DILMAH TEA CO,778812,"18,500.00",0.00,"26,500.00"
14/05/2026,BANK CHARGES - SMS ALERT FEE,,250.00,0.00,"26,250.00"
15/05/2026,CEFT INWARD / UNKNOWN PAYER REF 9901,,0.00,"12,000.00","38,250.00"
"""

		self.candidate_vouchers = [
			{
				"voucher_type": "Sales Invoice",
				"voucher_no": "ACC-SINV-2026-0001",
				"party_name": "Perera & Sons (Private) Limited",
				"party_type": "Customer",
				"posting_date": "2026-05-09",
				"amount": 45000.00,
				"reference_no": "",
			},
			{
				"voucher_type": "Purchase Invoice",
				"voucher_no": "ACC-PINV-2026-0002",
				"party_name": "Dilmah Ceylon Tea Company PLC",
				"party_type": "Supplier",
				"posting_date": "2026-05-12",
				"amount": 18500.00,
				"reference_no": "778812",
			},
		]

	def test_csv_parser_commercial_bank(self):
		parser = BankStatementParser(bank_name="Commercial Bank")
		transactions = parser.parse(self.sample_commercial_bank_csv, file_type="csv")

		self.assertEqual(len(transactions), 4)

		# First row (Deposit)
		self.assertEqual(transactions[0]["date"], "2026-05-10")
		self.assertEqual(transactions[0]["deposit"], 45000.00)
		self.assertEqual(transactions[0]["transaction_type"], "Deposit")
		self.assertIn("PERERA", transactions[0]["description"])

		# Second row (Withdrawal with Cheque)
		self.assertEqual(transactions[1]["date"], "2026-05-12")
		self.assertEqual(transactions[1]["withdrawal"], 18500.00)
		self.assertEqual(transactions[1]["reference_number"], "778812")

		# Third row (Bank Charge)
		self.assertEqual(transactions[2]["withdrawal"], 250.00)

	def test_matcher_fuzzy_name_matching(self):
		matcher = BankReconciliationMatcher()
		bank_tx = {
			"date": "2026-05-10",
			"description": "DEP TRF - PERERA AND SONS PVT LTD",
			"reference_number": "",
			"deposit": 45000.00,
			"withdrawal": 0.0,
			"amount": 45000.00,
			"transaction_type": "Deposit",
		}

		result = matcher.match_transaction(bank_tx, self.candidate_vouchers)
		self.assertEqual(result["status"], "MATCHED")
		self.assertEqual(result["matched_candidate"]["voucher_no"], "ACC-SINV-2026-0001")
		self.assertGreaterEqual(result["confidence_score"], 70.0)
		self.assertGreater(result["score_breakdown"]["fuzzy_name_score"], 10.0)

	def test_matcher_reference_number(self):
		matcher = BankReconciliationMatcher()
		bank_tx = {
			"date": "2026-05-12",
			"description": "CHQ PAYMENT",
			"reference_number": "778812",
			"deposit": 0.0,
			"withdrawal": 18500.00,
			"amount": 18500.00,
			"transaction_type": "Withdrawal",
		}

		result = matcher.match_transaction(bank_tx, self.candidate_vouchers)
		self.assertEqual(result["status"], "MATCHED")
		self.assertEqual(result["matched_candidate"]["voucher_no"], "ACC-PINV-2026-0002")
		self.assertEqual(result["score_breakdown"]["reference_score"], 25.0)

	def test_exceptions_queue_routing(self):
		queue = ReconciliationExceptionsQueue()
		bank_charge_tx = {
			"date": "2026-05-14",
			"description": "BANK CHARGES - SMS ALERT FEE",
			"reference_number": "",
			"deposit": 0.0,
			"withdrawal": 250.00,
			"amount": 250.00,
			"transaction_type": "Withdrawal",
		}

		entry = queue.add_exception(bank_charge_tx, reason="No matching voucher found")
		self.assertEqual(entry["category"], "BANK_CHARGE_OR_TAX")
		self.assertEqual(entry["status"], "Pending")

		# Manually resolve
		queue.resolve(entry["exception_id"], voucher_no="ACC-JV-2026-0010", user="Accountant")
		self.assertEqual(queue.summary()["resolved"], 1)
		self.assertEqual(queue.summary()["pending_review"], 0)

	def test_end_to_end_reconciliation(self):
		reconciler = SriLankaBankReconciliation(bank_name="Commercial Bank")
		result = reconciler.process_statement(
			file_content=self.sample_commercial_bank_csv,
			file_type="csv",
			candidates=self.candidate_vouchers,
		)

		self.assertEqual(result["total_transactions"], 4)
		self.assertEqual(result["reconciled_count"], 2)
		self.assertEqual(result["exceptions_count"], 2)

		# Verify the 2 reconciled transactions
		reconciled_ids = [r["matched_voucher"]["voucher_no"] for r in result["reconciled_transactions"]]
		self.assertIn("ACC-SINV-2026-0001", reconciled_ids)
		self.assertIn("ACC-PINV-2026-0002", reconciled_ids)

		# Verify the 2 exceptions
		self.assertEqual(len(result["exceptions"]), 2)
		reasons = [e["reason"] for e in result["exceptions"]]
		self.assertTrue(any("No matching" in r for r in reasons))

	def test_pdf_table_parsing(self):
		parser = BankStatementParser(bank_name="Hatton National Bank")
		sample_table = [
			["Date", "Description", "Ref No", "Debit", "Credit", "Balance"],
			["2026-05-12", "FUNDS TRF TO SAMAN MOTORS", "HNB-9901", "35,000.00", "", "150,000.00"],
			["2026-05-14", "DIVIDEND RECEIVED", "DIV-4410", "", "10,000.00", "160,000.00"],
		]
		txs = parser._parse_pdf_table(sample_table)
		self.assertEqual(len(txs), 2)
		self.assertEqual(txs[0]["withdrawal"], 35000.00)
		self.assertEqual(txs[0]["reference_number"], "HNB-9901")
		self.assertEqual(txs[1]["deposit"], 10000.00)

	def test_pdf_text_line_parsing(self):
		parser = BankStatementParser(bank_name="Sampath Bank")
		sample_text = (
			"2026-05-12  CHQ 839201  PAYMENT TO ABC TRADERS  15,000.00  DR  120,400.00\n"
			"2026-05-13  CASH DEPOSIT BRANCH COLOMBO  50,000.00  CR  170,400.00"
		)
		txs = parser._parse_pdf_text_lines(sample_text)
		self.assertEqual(len(txs), 2)
		self.assertEqual(txs[0]["withdrawal"], 15000.00)
		self.assertEqual(txs[0]["reference_number"], "839201")
		self.assertEqual(txs[1]["deposit"], 50000.00)


if __name__ == "__main__":
	unittest.main()
