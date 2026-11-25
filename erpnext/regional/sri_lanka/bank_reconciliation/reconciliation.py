# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from typing import Any, Dict, List, Optional, Union

try:
	import frappe
	from frappe import _
except ImportError:
	frappe = None
	_ = lambda x: x

from .parser import BankStatementParser
from .matcher import BankReconciliationMatcher
from .exceptions_queue import ReconciliationExceptionsQueue


class SriLankaBankReconciliation:
	"""
	Complete automated Bank Reconciliation pipeline for Sri Lankan banks:
	1. Parses CSV / PDF bank statements.
	2. Matches lines against ERPNext Invoices and Payments with deterministic rules
	   (Amount equality, Date tolerance, Reference matching, and Fuzzy Name matching).
	3. Automatically reconciles verified matches.
	4. Routes unmatched / ambiguous lines into an Exceptions Queue for human audit.
	"""

	def __init__(
		self,
		bank_name: Optional[str] = None,
		date_tolerance_days: int = 7,
		fuzzy_name_threshold: float = 75.0,
		match_confidence_threshold: float = 70.0,
	):
		self.parser = BankStatementParser(bank_name=bank_name)
		self.matcher = BankReconciliationMatcher(
			date_tolerance_days=date_tolerance_days,
			fuzzy_name_threshold=fuzzy_name_threshold,
			match_confidence_threshold=match_confidence_threshold,
		)
		self.exceptions_queue = ReconciliationExceptionsQueue()

	def process_statement(
		self,
		file_content: Union[str, bytes],
		file_type: str = "csv",
		candidates: Optional[List[Dict[str, Any]]] = None,
	) -> Dict[str, Any]:
		"""
		Executes the full parsing, matching, and exception queuing workflow.
		"""
		# 1. Parse statement
		transactions = self.parser.parse(file_content, file_type=file_type)
		if not transactions:
			return {
				"total_transactions": 0,
				"reconciled_count": 0,
				"exceptions_count": 0,
				"reconciled_transactions": [],
				"exceptions": [],
				"summary": self.exceptions_queue.summary(),
			}

		candidate_list = candidates or []
		reconciled = []
		unmatched = []

		# Keep track of already matched candidate IDs to prevent double allocation
		allocated_candidate_ids = set()

		for tx in transactions:
			# Filter out already allocated candidates for this run
			available_candidates = [
				c for c in candidate_list
				if str(c.get("voucher_no") or c.get("name")) not in allocated_candidate_ids
			]

			# Run rule matcher
			result = self.matcher.match_transaction(tx, available_candidates)

			if result["status"] == "MATCHED":
				matched_voucher = result["matched_candidate"]
				voucher_id = str(matched_voucher.get("voucher_no") or matched_voucher.get("name"))
				allocated_candidate_ids.add(voucher_id)

				reconciled_item = {
					"transaction": tx,
					"matched_voucher": matched_voucher,
					"confidence_score": result["confidence_score"],
					"score_breakdown": result["score_breakdown"],
				}
				reconciled.append(reconciled_item)

			else:
				# Route to Exceptions Queue
				exception_entry = self.exceptions_queue.add_exception(
					bank_tx=tx,
					reason=result["reason"],
					candidates=result.get("top_candidates", []),
				)
				unmatched.append(exception_entry)

		return {
			"total_transactions": len(transactions),
			"reconciled_count": len(reconciled),
			"exceptions_count": len(unmatched),
			"reconciled_transactions": reconciled,
			"exceptions": unmatched,
			"queue_summary": self.exceptions_queue.summary(),
		}

	def fetch_erpnext_vouchers(
		self,
		bank_account: str,
		company: str,
		from_date: Optional[str] = None,
		to_date: Optional[str] = None,
	) -> List[Dict[str, Any]]:
		"""
		Queries active candidate vouchers from ERPNext database if running inside Frappe.
		"""
		if not frappe:
			return []

		candidates = []

		# 1. Sales Invoices (Deposits / Receipts)
		si_filters = {"company": company, "docstatus": 1, "outstanding_amount": [">", 0]}
		if from_date and to_date:
			si_filters["posting_date"] = ["between", [from_date, to_date]]

		sales_invoices = frappe.get_all(
			"Sales Invoice",
			filters=si_filters,
			fields=["name", "customer", "customer_name", "posting_date", "outstanding_amount", "currency"],
		)
		for si in sales_invoices:
			candidates.append({
				"voucher_type": "Sales Invoice",
				"voucher_no": si.name,
				"party_name": si.customer_name or si.customer,
				"party_type": "Customer",
				"posting_date": str(si.posting_date),
				"amount": float(si.outstanding_amount),
				"reference_no": "",
			})

		# 2. Payment Entries (Deposits and Withdrawals)
		pe_filters = {"company": company, "docstatus": 1, "clearance_date": ["is", "not set"]}
		if from_date and to_date:
			pe_filters["posting_date"] = ["between", [from_date, to_date]]

		payment_entries = frappe.get_all(
			"Payment Entry",
			filters=pe_filters,
			fields=["name", "party_name", "party_type", "payment_type", "paid_amount", "received_amount", "reference_no", "posting_date"],
		)
		for pe in payment_entries:
			amt = float(pe.received_amount if pe.payment_type == "Receive" else pe.paid_amount)
			candidates.append({
				"voucher_type": "Payment Entry",
				"voucher_no": pe.name,
				"party_name": pe.party_name,
				"party_type": pe.party_type,
				"posting_date": str(pe.posting_date),
				"amount": amt,
				"reference_no": pe.reference_no or "",
			})

		# 3. Purchase Invoices (Withdrawals / Payments)
		pi_filters = {"company": company, "docstatus": 1, "outstanding_amount": [">", 0]}
		if from_date and to_date:
			pi_filters["posting_date"] = ["between", [from_date, to_date]]

		purchase_invoices = frappe.get_all(
			"Purchase Invoice",
			filters=pi_filters,
			fields=["name", "supplier", "supplier_name", "posting_date", "outstanding_amount", "bill_no"],
		)
		for pi in purchase_invoices:
			candidates.append({
				"voucher_type": "Purchase Invoice",
				"voucher_no": pi.name,
				"party_name": pi.supplier_name or pi.supplier,
				"party_type": "Supplier",
				"posting_date": str(pi.posting_date),
				"amount": float(pi.outstanding_amount),
				"reference_no": pi.bill_no or "",
			})

		return candidates


# Whitelisted API endpoints for ERPNext Desk
if frappe:
	@frappe.whitelist(methods=["POST"])
	def upload_and_reconcile_sl_statement(
		file_content: str,
		file_type: str = "csv",
		bank_name: Optional[str] = None,
		bank_account: Optional[str] = None,
		company: Optional[str] = None,
		date_tolerance_days: int = 7,
		fuzzy_threshold: float = 75.0,
	):
		"""
		Whitelisted API for frontend / desk integration.
		"""
		reconciler = SriLankaBankReconciliation(
			bank_name=bank_name,
			date_tolerance_days=int(date_tolerance_days),
			fuzzy_name_threshold=float(fuzzy_threshold),
		)

		candidates = []
		if bank_account and company:
			candidates = reconciler.fetch_erpnext_vouchers(bank_account=bank_account, company=company)

		result = reconciler.process_statement(file_content, file_type=file_type, candidates=candidates)
		return result
