# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional


class ReconciliationExceptionsQueue:
	"""
	Manages unmatched and ambiguous bank statement lines.
	Enables accountants to review reasons, view suggested candidates,
	and resolve exceptions manually.
	"""

	CATEGORY_NO_MATCH = "NO_MATCH_FOUND"
	CATEGORY_AMBIGUOUS = "AMBIGUOUS_MATCH"
	CATEGORY_LOW_CONFIDENCE = "LOW_CONFIDENCE"
	CATEGORY_BANK_CHARGE = "BANK_CHARGE_OR_TAX"

	def __init__(self):
		self.queue: List[Dict[str, Any]] = []

	def add_exception(
		self,
		bank_tx: Dict[str, Any],
		reason: str,
		category: Optional[str] = None,
		candidates: Optional[List[Dict[str, Any]]] = None,
	) -> Dict[str, Any]:
		"""
		Enqueues an unmatched or ambiguous transaction into the exceptions queue.
		"""
		detected_category = category or self._classify_category(bank_tx, reason)

		exception_entry = {
			"exception_id": str(uuid.uuid4())[:8],
			"created_at": datetime.now().isoformat(),
			"status": "Pending",  # Pending | Resolved | Ignored
			"category": detected_category,
			"reason": reason,
			"transaction": {
				"date": bank_tx.get("date"),
				"description": bank_tx.get("description"),
				"reference_number": bank_tx.get("reference_number"),
				"amount": bank_tx.get("amount"),
				"transaction_type": bank_tx.get("transaction_type"),
				"withdrawal": bank_tx.get("withdrawal", 0.0),
				"deposit": bank_tx.get("deposit", 0.0),
				"bank": bank_tx.get("bank", "Unknown"),
			},
			"suggested_candidates": candidates or [],
			"resolved_by": None,
			"resolved_voucher": None,
			"resolution_notes": None,
		}

		self.queue.append(exception_entry)
		return exception_entry

	def get_pending(self) -> List[Dict[str, Any]]:
		"""Returns all items currently awaiting review."""
		return [e for e in self.queue if e["status"] == "Pending"]

	def resolve(
		self, exception_id: str, voucher_no: str, user: str = "Administrator", notes: Optional[str] = None
	) -> bool:
		"""
		Marks an exception item as resolved by linking it to an ERPNext voucher.
		"""
		for entry in self.queue:
			if entry["exception_id"] == exception_id:
				entry["status"] = "Resolved"
				entry["resolved_voucher"] = voucher_no
				entry["resolved_by"] = user
				entry["resolved_at"] = datetime.now().isoformat()
				entry["resolution_notes"] = notes or "Manually linked by accountant"
				return True
		return False

	def ignore(self, exception_id: str, reason: str, user: str = "Administrator") -> bool:
		"""
		Marks an exception item as ignored (e.g. non-business transaction or erroneous line).
		"""
		for entry in self.queue:
			if entry["exception_id"] == exception_id:
				entry["status"] = "Ignored"
				entry["resolved_by"] = user
				entry["resolved_at"] = datetime.now().isoformat()
				entry["resolution_notes"] = reason
				return True
		return False

	def summary(self) -> Dict[str, Any]:
		"""Returns aggregate statistics of the queue."""
		total = len(self.queue)
		pending = len(self.get_pending())
		resolved = sum(1 for e in self.queue if e["status"] == "Resolved")
		ignored = sum(1 for e in self.queue if e["status"] == "Ignored")

		categories = {}
		for e in self.queue:
			cat = e["category"]
			categories[cat] = categories.get(cat, 0) + 1

		return {
			"total_exceptions": total,
			"pending_review": pending,
			"resolved": resolved,
			"ignored": ignored,
			"by_category": categories,
		}

	def _classify_category(self, bank_tx: Dict[str, Any], reason: str) -> str:
		"""Determines exception classification based on narration and matching outcome."""
		narration = str(bank_tx.get("description") or "").lower()
		charge_keywords = ["bank charge", "service charge", "chq return", "stamp duty", "tax", "vat", "wht", "fee", "interest credit"]
		if any(k in narration for k in charge_keywords):
			return self.CATEGORY_BANK_CHARGE

		if "multiple" in reason.lower() or "ambiguous" in reason.lower():
			return self.CATEGORY_AMBIGUOUS

		if "score" in reason.lower() or "confidence" in reason.lower():
			return self.CATEGORY_LOW_CONFIDENCE

		return self.CATEGORY_NO_MATCH
