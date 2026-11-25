# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple, Union

try:
	from rapidfuzz import fuzz
except ImportError:
	raise ImportError("rapidfuzz is required for fuzzy name matching. Please install it via pip.")


class BankReconciliationMatcher:
	"""
	Rule-based matching engine for Bank Transactions against ERPNext vouchers
	(Invoices, Payment Entries, Journal Entries).
	
	Rules evaluated:
	1. Amount Match (Exact equality or within tolerance)
	2. Date Tolerance (Window in days between statement date and posting date)
	3. Reference / Cheque Match (Exact match or extracted from bank narration)
	4. Fuzzy Name Matching (Using rapidfuzz for customer/supplier names)
	"""

	COMMON_BANK_STOPWORDS = {
		"dep", "deposit", "slip", "trf", "transfer", "ceft", "lankapay", "rtgs", "slips",
		"chq", "cheque", "chk", "ft", "fund", "funds", "ibnk", "online", "dr", "cr",
		"payment", "receipt", "branch", "colombo", "kandy", "galle", "atm", "pos", "tax",
		"vat", "sscl", "wht", "fee", "charge", "charges", "comm", "commission", "pvt",
		"ltd", "private", "limited", "plc", "co", "company"
	}

	def __init__(
		self,
		date_tolerance_days: int = 7,
		fuzzy_name_threshold: float = 75.0,
		match_confidence_threshold: float = 70.0,
	):
		self.date_tolerance_days = date_tolerance_days
		self.fuzzy_name_threshold = fuzzy_name_threshold
		self.match_confidence_threshold = match_confidence_threshold

	def match_transaction(
		self,
		bank_tx: Dict[str, Any],
		candidates: List[Dict[str, Any]],
	) -> Dict[str, Any]:
		"""
		Matches a single bank transaction against a list of candidate vouchers.
		Returns match result with status: 'MATCHED', 'AMBIGUOUS', or 'UNMATCHED'.
		"""
		scored_candidates = []
		for cand in candidates:
			score, breakdown = self._evaluate_candidate(bank_tx, cand)
			if score > 0:
				scored_candidates.append({
					"candidate": cand,
					"score": score,
					"breakdown": breakdown,
				})

		# Sort candidates by descending score
		scored_candidates.sort(key=lambda x: x["score"], reverse=True)

		if not scored_candidates:
			return {
				"status": "UNMATCHED",
				"reason": "No matching voucher found within amount and date criteria",
				"matched_candidate": None,
				"top_candidates": [],
			}

		top_match = scored_candidates[0]
		top_score = top_match["score"]

		# Check for ambiguity (multiple candidates with equal top score or within 5 points)
		if len(scored_candidates) > 1:
			runner_up_score = scored_candidates[1]["score"]
			if top_score >= self.match_confidence_threshold and (top_score - runner_up_score) < 5.0:
				return {
					"status": "AMBIGUOUS",
					"reason": f"Multiple equally strong candidates found (Scores: {top_score:.1f} vs {runner_up_score:.1f})",
					"matched_candidate": None,
					"top_candidates": scored_candidates[:3],
				}

		# Check if top score meets the confidence threshold
		if top_score >= self.match_confidence_threshold:
			return {
				"status": "MATCHED",
				"reason": f"High confidence match ({top_score:.1f}% confidence)",
				"matched_candidate": top_match["candidate"],
				"confidence_score": top_score,
				"score_breakdown": top_match["breakdown"],
				"top_candidates": scored_candidates[:3],
			}

		return {
			"status": "UNMATCHED",
			"reason": f"Best match candidate only achieved {top_score:.1f}% score (below {self.match_confidence_threshold}%)",
			"matched_candidate": None,
			"top_candidates": scored_candidates[:3],
		}

	def _evaluate_candidate(
		self, bank_tx: Dict[str, Any], cand: Dict[str, Any]
	) -> Tuple[float, Dict[str, float]]:
		"""
		Calculates a composite score (0 - 100) comparing a bank transaction to a candidate voucher.
		"""
		breakdown = {
			"amount_score": 0.0,
			"reference_score": 0.0,
			"date_score": 0.0,
			"fuzzy_name_score": 0.0,
		}

		# --- 1. Amount Comparison (Weight: 40) ---
		bank_amount = float(bank_tx.get("amount") or (bank_tx.get("deposit") or bank_tx.get("withdrawal") or 0.0))
		cand_amount = float(cand.get("amount") or cand.get("paid_amount") or cand.get("outstanding_amount") or 0.0)

		if bank_amount <= 0 or cand_amount <= 0:
			return 0.0, breakdown

		amount_diff = abs(bank_amount - cand_amount)
		if amount_diff < 0.01:
			breakdown["amount_score"] = 40.0
		elif amount_diff <= 1.00:  # Allow 1 rupee rounding difference
			breakdown["amount_score"] = 35.0
		else:
			# If amount differs significantly, it's not a direct match
			return 0.0, breakdown

		# --- 2. Reference / Cheque Match (Weight: 25) ---
		bank_ref = str(bank_tx.get("reference_number") or "").strip().lower()
		cand_ref = str(cand.get("reference_no") or cand.get("cheque_no") or "").strip().lower()
		cand_voucher = str(cand.get("voucher_no") or cand.get("name") or "").strip().lower()
		narration = str(bank_tx.get("description") or "").lower()

		if bank_ref and cand_ref and (bank_ref == cand_ref or bank_ref in cand_ref or cand_ref in bank_ref):
			breakdown["reference_score"] = 25.0
		elif cand_ref and cand_ref in narration:
			breakdown["reference_score"] = 25.0
		elif cand_voucher and cand_voucher in narration:
			breakdown["reference_score"] = 20.0
		elif bank_ref and bank_ref in narration:
			breakdown["reference_score"] = 10.0

		# --- 3. Date Proximity (Weight: 15) ---
		bank_date = self._to_date(bank_tx.get("date"))
		cand_date = self._to_date(cand.get("posting_date") or cand.get("reference_date") or cand.get("date"))

		if bank_date and cand_date:
			days_diff = abs((bank_date - cand_date).days)
			if days_diff == 0:
				breakdown["date_score"] = 15.0
			elif days_diff <= 2:
				breakdown["date_score"] = 12.0
			elif days_diff <= self.date_tolerance_days:
				# Scale down linearly from 10 to 5
				scale = 1.0 - (days_diff / max(self.date_tolerance_days, 1))
				breakdown["date_score"] = round(5.0 + (scale * 5.0), 1)
			else:
				breakdown["date_score"] = 0.0

		# --- 4. Fuzzy Name Matching with RapidFuzz (Weight: 20) ---
		cand_party = str(cand.get("party_name") or cand.get("party") or cand.get("customer") or cand.get("supplier") or "")
		if cand_party:
			cleaned_narration = self._clean_for_fuzzy(narration)
			cleaned_party = self._clean_for_fuzzy(cand_party)

			if cleaned_party and cleaned_narration:
				# Use a combination of token sort and partial ratio
				sort_ratio = fuzz.token_sort_ratio(cleaned_party, cleaned_narration)
				partial_ratio = fuzz.partial_ratio(cleaned_party, cleaned_narration)
				w_ratio = fuzz.WRatio(cleaned_party, cleaned_narration)

				best_ratio = max(sort_ratio, partial_ratio, w_ratio)

				if best_ratio >= self.fuzzy_name_threshold:
					# Scale weight from 15 to 20 based on ratio
					ratio_factor = (best_ratio - self.fuzzy_name_threshold) / (100.0 - self.fuzzy_name_threshold)
					breakdown["fuzzy_name_score"] = round(15.0 + (ratio_factor * 5.0), 1)
				elif best_ratio >= 60.0:
					breakdown["fuzzy_name_score"] = 8.0

		total_score = sum(breakdown.values())
		return total_score, breakdown

	def _to_date(self, val: Union[str, date, datetime, None]) -> Optional[date]:
		"""Converts string or datetime objects to a standard datetime.date."""
		if not val:
			return None
		if isinstance(val, date) and not isinstance(val, datetime):
			return val
		if isinstance(val, datetime):
			return val.date()

		val_str = str(val).strip().split(" ")[0]
		for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]:
			try:
				return datetime.strptime(val_str, fmt).date()
			except ValueError:
				continue
		return None

	def _clean_for_fuzzy(self, text: str) -> str:
		"""
		Cleans text for accurate fuzzy comparison by removing punctuation and bank stopwords.
		"""
		clean = re.sub(r"[^A-Za-z0-9\s]", " ", text.lower())
		tokens = clean.split()
		filtered = [t for t in tokens if t not in self.COMMON_BANK_STOPWORDS and len(t) > 1]
		return " ".join(filtered)
