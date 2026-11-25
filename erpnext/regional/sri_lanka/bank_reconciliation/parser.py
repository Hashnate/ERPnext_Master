# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import csv
import io
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Union


class BankStatementParser:
	"""
	Parses Sri Lankan bank statements in CSV and PDF formats.
	Supports Commercial Bank, Sampath Bank, HNB, BOC, and generic Sri Lankan banking formats.
	"""

	COMMON_BANKS = ["Commercial Bank", "Sampath Bank", "Hatton National Bank", "Bank of Ceylon", "Generic"]

	def __init__(self, bank_name: Optional[str] = None):
		self.bank_name = bank_name

	def parse(self, file_content: Union[str, bytes], file_type: str = "csv") -> List[Dict[str, Any]]:
		"""
		Main entrypoint to parse statement data from bytes or string.
		"""
		file_type = file_type.lower().strip()
		if file_type == "csv":
			return self.parse_csv(file_content)
		elif file_type == "pdf":
			return self.parse_pdf(file_content)
		else:
			raise ValueError(f"Unsupported file type: {file_type}. Supported types are 'csv' and 'pdf'.")

	def parse_csv(self, content: Union[str, bytes]) -> List[Dict[str, Any]]:
		"""
		Parses CSV content into standardized transaction dictionaries.
		"""
		if isinstance(content, bytes):
			try:
				text = content.decode("utf-8")
			except UnicodeDecodeError:
				text = content.decode("latin-1")
		else:
			text = content

		lines = [line.strip() for line in text.splitlines() if line.strip()]
		if not lines:
			return []

		# Identify header line
		header_idx, headers, bank = self._detect_csv_header(lines)
		detected_bank = self.bank_name or bank

		reader = csv.reader(lines[header_idx:])
		header_row = next(reader)
		header_map = self._map_columns([h.strip() for h in header_row])

		transactions = []
		for row in reader:
			if not row or all(not cell.strip() for cell in row):
				continue

			tx = self._extract_transaction_from_row(row, header_map, detected_bank)
			if tx:
				transactions.append(tx)

		return transactions

	def parse_pdf(self, content: Union[str, bytes]) -> List[Dict[str, Any]]:
		"""
		Parses PDF statement content using pdfplumber or pypdf.
		"""
		try:
			import pdfplumber
		except ImportError:
			raise ImportError("pdfplumber is required for parsing PDF bank statements. Please install it.")

		if isinstance(content, str):
			file_obj = io.BytesIO(content.encode("latin-1"))
		else:
			file_obj = io.BytesIO(content)

		transactions = []
		with pdfplumber.open(file_obj) as pdf:
			for page in pdf.pages:
				# First try extracting tabular data
				tables = page.extract_tables()
				if tables:
					for table in tables:
						txs = self._parse_pdf_table(table)
						transactions.extend(txs)
				else:
					# Fallback to line-by-line regex parsing
					text = page.extract_text() or ""
					txs = self._parse_pdf_text_lines(text)
					transactions.extend(txs)

		return transactions

	def _detect_csv_header(self, lines: List[str]):
		"""
		Scans initial lines to find the table header row and identify the bank.
		"""
		detected_bank = "Generic"
		full_intro = " ".join(lines[:10]).lower()

		if "commercial bank" in full_intro or "combank" in full_intro:
			detected_bank = "Commercial Bank"
		elif "sampath" in full_intro:
			detected_bank = "Sampath Bank"
		elif "hatton national bank" in full_intro or "hnb" in full_intro:
			detected_bank = "Hatton National Bank"
		elif "bank of ceylon" in full_intro or "boc" in full_intro:
			detected_bank = "Bank of Ceylon"

		for idx, line in enumerate(lines[:20]):
			lower = line.lower()
			if any(k in lower for k in ["date", "txn date", "transaction date"]) and any(
				k in lower for k in ["description", "particulars", "narration", "debit", "credit", "amount"]
			):
				sample_reader = csv.reader([line])
				headers = next(sample_reader)
				return idx, [h.strip() for h in headers], detected_bank

		# Fallback to first line
		sample_reader = csv.reader([lines[0]])
		return 0, [h.strip() for h in next(sample_reader)], detected_bank

	def _map_columns(self, headers: List[str]) -> Dict[str, int]:
		"""
		Maps standard fields to column indices based on common Sri Lankan bank header names.
		"""
		mapping = {
			"date": -1,
			"description": -1,
			"reference": -1,
			"debit": -1,
			"credit": -1,
			"amount": -1,
			"balance": -1,
		}

		for idx, h in enumerate(headers):
			clean = h.lower().replace("_", " ").strip()

			# Date
			if mapping["date"] == -1 and any(
				k in clean for k in ["txn date", "transaction date", "value date", "post date", "date"]
			):
				mapping["date"] = idx

			# Description
			elif mapping["description"] == -1 and any(
				k in clean for k in ["particulars", "description", "narration", "details", "remarks"]
			):
				mapping["description"] = idx

			# Reference
			elif mapping["reference"] == -1 and any(
				k in clean for k in ["cheque no", "chq no", "ref no", "reference", "txn id", "trans ref"]
			):
				mapping["reference"] = idx

			# Debit / Withdrawal
			elif mapping["debit"] == -1 and any(
				k in clean for k in ["withdrawal", "debit amount", "debit", "dr", "payments"]
			):
				mapping["debit"] = idx

			# Credit / Deposit
			elif mapping["credit"] == -1 and any(
				k in clean for k in ["deposit", "credit amount", "credit", "cr", "receipts"]
			):
				mapping["credit"] = idx

			# Unified Amount
			elif mapping["amount"] == -1 and clean in ["amount", "txn amount", "net amount"]:
				mapping["amount"] = idx

			# Balance
			elif mapping["balance"] == -1 and any(k in clean for k in ["balance", "account balance"]):
				mapping["balance"] = idx

		return mapping

	def _extract_transaction_from_row(
		self, row: List[str], mapping: Dict[str, int], bank: str
	) -> Optional[Dict[str, Any]]:
		"""
		Converts a raw table row into a structured transaction dict.
		"""
		def get_val(key):
			idx = mapping.get(key, -1)
			return row[idx].strip() if 0 <= idx < len(row) else ""

		raw_date = get_val("date")
		parsed_date = self._parse_date(raw_date)
		if not parsed_date:
			# Not a valid transaction line (e.g. summary or footer row)
			return None

		description = get_val("description")
		reference = get_val("reference")

		# If reference wasn't in its own column, attempt to extract from narration
		if not reference:
			reference = self._extract_reference_from_narration(description)

		debit = self._parse_amount(get_val("debit"))
		credit = self._parse_amount(get_val("credit"))
		amount_val = self._parse_amount(get_val("amount"))
		balance = self._parse_amount(get_val("balance"))

		# Resolve debit/credit if only a single 'amount' column was present
		if debit == 0.0 and credit == 0.0 and amount_val != 0.0:
			raw_amt = get_val("amount").upper()
			if "DR" in raw_amt or amount_val < 0:
				debit = abs(amount_val)
			else:
				credit = abs(amount_val)

		# Transaction must have an amount
		if debit == 0.0 and credit == 0.0:
			return None

		return {
			"date": parsed_date,
			"description": description,
			"reference_number": reference,
			"withdrawal": debit,
			"deposit": credit,
			"amount": credit if credit > 0 else debit,
			"transaction_type": "Deposit" if credit > 0 else "Withdrawal",
			"balance": balance,
			"bank": bank,
			"raw_data": row,
		}

	def _parse_pdf_table(self, table: List[List[Optional[str]]]) -> List[Dict[str, Any]]:
		"""
		Processes an extracted PDF table.
		"""
		if not table or len(table) < 2:
			return []

		cleaned_table = []
		for r in table:
			cleaned_table.append([(c or "").strip() for c in r])

		# Locate header row
		header_idx = -1
		for idx, row in enumerate(cleaned_table[:5]):
			joined = " ".join(row).lower()
			if "date" in joined and any(k in joined for k in ["description", "particulars", "debit", "credit", "amount"]):
				header_idx = idx
				break

		if header_idx == -1:
			return []

		header_map = self._map_columns(cleaned_table[header_idx])
		results = []
		for row in cleaned_table[header_idx + 1:]:
			tx = self._extract_transaction_from_row(row, header_map, self.bank_name or "Generic")
			if tx:
				results.append(tx)

		return results

	def _parse_pdf_text_lines(self, text: str) -> List[Dict[str, Any]]:
		"""
		Fallback for text-based PDF statements matching common Sri Lankan regex patterns:
		e.g.: "2026-05-12  CHQ 839201  PAYMENT TO ABC TRADERS  15,000.00  DR  120,400.00"
		"""
		results = []
		date_regex = re.compile(r"^(\d{2}[/-]\d{2}[/-]\d{4}|\d{4}[/-]\d{2}[/-]\d{2})")
		amount_regex = re.compile(r"(\d{1,3}(?:,\d{3})*\.\d{2})")

		for line in text.splitlines():
			line = line.strip()
			date_match = date_regex.match(line)
			if not date_match:
				continue

			date_str = date_match.group(1)
			parsed_date = self._parse_date(date_str)
			if not parsed_date:
				continue

			amounts = amount_regex.findall(line)
			if not amounts:
				continue

			# Remainder is description & reference
			desc = line[len(date_str):].strip()
			for amt in amounts:
				desc = desc.replace(amt, "")
			desc = re.sub(r"\s+", " ", desc).strip()

			ref = self._extract_reference_from_narration(desc)
			amt_val = self._parse_amount(amounts[0])

			is_debit = "DR" in line.upper() or "DEBIT" in line.upper()
			debit = amt_val if is_debit else 0.0
			credit = 0.0 if is_debit else amt_val

			results.append({
				"date": parsed_date,
				"description": desc,
				"reference_number": ref,
				"withdrawal": debit,
				"deposit": credit,
				"amount": amt_val,
				"transaction_type": "Withdrawal" if is_debit else "Deposit",
				"balance": self._parse_amount(amounts[1]) if len(amounts) > 1 else 0.0,
				"bank": self.bank_name or "Generic",
				"raw_data": [line],
			})

		return results

	def _parse_date(self, val: str) -> Optional[str]:
		"""
		Parses date strings into ISO format YYYY-MM-DD.
		Supports standard Sri Lankan date variations.
		"""
		if not val:
			return None

		clean_val = val.strip().split(" ")[0]  # strip time component if any
		formats = [
			"%d/%m/%Y",
			"%d-%m-%Y",
			"%Y-%m-%d",
			"%d/%m/%y",
			"%d-%m-%y",
			"%d-%b-%Y",
			"%d-%b-%y",
			"%d %b %Y",
			"%Y/%m/%d",
		]
		for fmt in formats:
			try:
				dt = datetime.strptime(clean_val, fmt)
				return dt.strftime("%Y-%m-%d")
			except ValueError:
				continue

		return None

	def _parse_amount(self, val: str) -> float:
		"""
		Cleans numeric strings (e.g. '1,250.00', 'Rs. 5,000.00', '(500.00)') into float.
		"""
		if not val:
			return 0.0

		clean = str(val).strip().replace(",", "").replace("Rs.", "").replace("LKR", "").replace(" ", "")
		is_negative = False
		if clean.startswith("(") and clean.endswith(")"):
			is_negative = True
			clean = clean[1:-1]
		elif clean.endswith("-"):
			is_negative = True
			clean = clean[:-1]
		elif clean.startswith("-"):
			is_negative = True
			clean = clean[1:]

		# Remove trailing DR/CR
		clean = re.sub(r"(?i)(dr|cr)$", "", clean).strip()

		try:
			amount = float(clean)
			return -amount if is_negative else amount
		except ValueError:
			return 0.0

	def _extract_reference_from_narration(self, text: str) -> str:
		"""
		Extracts cheque numbers or transaction reference codes from narration text.
		e.g. 'CHQ NO: 489201', 'REF # 99281234', 'CEFT/9382109'
		"""
		if not text:
			return ""

		patterns = [
			r"(?:chq|cheque|chk)\s*(?:no[.:]*)?\s*([0-9]{4,10})",
			r"(?:ref|reference|txn)\s*(?:no[.:]*)?\s*([A-Za-z0-9_-]{5,20})",
			r"(?:ceft|slips|rtgs)[/:\s]+([A-Za-z0-9_-]{5,20})",
		]

		for pat in patterns:
			match = re.search(pat, text, re.IGNORECASE)
			if match:
				return match.group(1).strip()

		return ""
