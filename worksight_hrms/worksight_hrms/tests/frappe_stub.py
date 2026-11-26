from __future__ import annotations

import sys
import types
from datetime import date, datetime
from typing import Any


class InMemoryDoc(dict):
	"""Minimal Frappe Document-like object for standalone unit testing."""

	def __init__(self, data: dict[str, Any], db: InMemoryDB):
		super().__init__(data)
		self._db = db
		self.setdefault("docstatus", 0)

	def __getattr__(self, key: str) -> Any:
		try:
			return self[key]
		except KeyError:
			return None

	def __setattr__(self, key: str, value: Any) -> None:
		if key.startswith("_"):
			super().__setattr__(key, value)
		else:
			self[key] = value

	def get_password(self, fieldname: str, raise_exception: bool = True) -> str:
		return self.get(fieldname) or ""

	def insert(self, ignore_permissions: bool = False):
		self._db.insert_doc(self)
		return self

	def submit(self):
		self.docstatus = 1
		self._db.save_doc(self)
		self._db.fire_hook(self.doctype, "on_submit", self)
		return self

	def cancel(self):
		self.docstatus = 2
		self._db.save_doc(self)
		self._db.fire_hook(self.doctype, "on_cancel", self)
		return self

	def db_set(self, fieldname: str, value: Any) -> None:
		self[fieldname] = value
		self._db.save_doc(self)


class InMemoryDB:
	"""Minimal in-memory frappe.db implementation for unit tests."""

	def __init__(self):
		self.tables: dict[str, dict[str, InMemoryDoc]] = {}
		self.singles: dict[str, InMemoryDoc] = {}
		self.counters: dict[str, int] = {}
		self.hooks: dict[str, dict[str, list]] = {}
		self.errors: list[tuple[str, str]] = []

	def register_hook(self, doctype: str, event: str, fn) -> None:
		self.hooks.setdefault(doctype, {}).setdefault(event, []).append(fn)

	def fire_hook(self, doctype: str, event: str, doc: InMemoryDoc) -> None:
		for fn in self.hooks.get(doctype, {}).get(event, []):
			fn(doc)

	def set_single(self, doctype: str, data: dict[str, Any]) -> InMemoryDoc:
		doc = InMemoryDoc({"doctype": doctype, "name": doctype, **data}, self)
		self.singles[doctype] = doc
		return doc

	def insert_doc(self, doc: InMemoryDoc) -> InMemoryDoc:
		doctype = doc["doctype"]
		if not doc.get("name"):
			idx = self.counters.get(doctype, 0) + 1
			self.counters[doctype] = idx
			doc["name"] = f"{doctype.upper().replace(' ', '-')}-{idx:05d}"
		if doctype == "WorkSight Late Record" and doc.get("status") == "Pending":
			pass
		self.tables.setdefault(doctype, {})[doc["name"]] = doc
		return doc

	def save_doc(self, doc: InMemoryDoc) -> None:
		self.tables.setdefault(doc["doctype"], {})[doc["name"]] = doc

	def _matches(self, row: InMemoryDoc, filters: dict[str, Any] | None) -> bool:
		if not filters:
			return True
		for key, cond in filters.items():
			val = row.get(key)
			if isinstance(cond, list) and len(cond) == 2:
				op, target = cond
				if op == "!=":
					if val == target:
						return False
				elif op == "<=":
					if val is None or str(val) > str(target):
						return False
				elif op == "in":
					if val not in target:
						return False
				elif op == "is":
					if target == "not set" and val not in (None, ""):
						return False
				elif op == "between":
					start, end = target
					if val is None:
						return False
					if isinstance(val, str):
						try:
							val_cmp = datetime.fromisoformat(val)
						except ValueError:
							val_cmp = date.fromisoformat(val)
					else:
						val_cmp = val
					if isinstance(start, date) and not isinstance(start, datetime) and isinstance(val_cmp, datetime):
						val_cmp = val_cmp.date()
					if val_cmp < start or val_cmp > end:
						return False
			elif val != cond:
				return False
		return True

	def get_all(
		self,
		doctype: str,
		filters: dict[str, Any] | None = None,
		fields: list[str] | None = None,
		order_by: str | None = None,
		limit: int | None = None,
		pluck: str | None = None,
	) -> list[Any]:
		rows = [r for r in self.tables.get(doctype, {}).values() if self._matches(r, filters)]
		if order_by:
			parts = order_by.split()
			field = parts[0]
			reverse = len(parts) > 1 and parts[1].lower() == "desc"
			rows.sort(key=lambda r: str(r.get(field) or ""), reverse=reverse)
		if limit:
			rows = rows[:limit]
		if pluck:
			return [r.get(pluck) for r in rows]
		if fields:
			return [{f: r.get(f) for f in fields} for r in rows]
		return rows

	def get_value(self, doctype: str, filters: Any, fieldname: Any = "name", as_dict: bool = False) -> Any:
		if isinstance(filters, str):
			row = self.tables.get(doctype, {}).get(filters)
			rows = [row] if row else []
		else:
			rows = self.get_all(doctype, filters=filters, limit=1)
		if not rows:
			return None
		row = rows[0]
		if isinstance(fieldname, list):
			out = {f: row.get(f) for f in fieldname}
			return InMemoryDoc(out, self) if as_dict else tuple(out.values())
		return row.get(fieldname)

	def get_single_value(self, doctype: str, fieldname: str) -> Any:
		doc = self.singles.get(doctype)
		return doc.get(fieldname) if doc else None

	def exists(self, doctype: str, filters: Any) -> str | None:
		return self.get_value(doctype, filters, "name")


def install_frappe_stub() -> InMemoryDB:
	"""Install (or reset) a lightweight `frappe` stub in sys.modules if real Frappe is absent."""
	db = InMemoryDB()
	existing = sys.modules.get("frappe")
	if existing is not None and getattr(existing, "_is_worksight_stub", False):
		existing.db = db
		existing.form_dict = {}
		existing.request = None
		return db

	class PermissionError(Exception):
		pass

	class AuthenticationError(Exception):
		pass

	class ValidationError(Exception):
		pass

	frappe_mod = types.ModuleType("frappe")
	frappe_mod._is_worksight_stub = True
	frappe_mod.db = db
	frappe_mod.PermissionError = PermissionError
	frappe_mod.AuthenticationError = AuthenticationError
	frappe_mod.ValidationError = ValidationError
	frappe_mod.form_dict = {}
	frappe_mod.request = None
	frappe_mod._ = lambda msg: msg

	def whitelist(*args, **kwargs):
		def decorator(fn):
			return fn

		return decorator

	def throw(msg, exc=ValidationError):
		raise exc(msg)

	def get_cached_doc(doctype: str, name: str | None = None):
		cur_db = frappe_mod.db
		if name is None and doctype in cur_db.singles:
			return cur_db.singles[doctype]
		if name and doctype in cur_db.tables and name in cur_db.tables[doctype]:
			return cur_db.tables[doctype][name]
		raise KeyError(f"Missing {doctype} {name}")

	def get_doc(arg1, arg2=None):
		cur_db = frappe_mod.db
		if isinstance(arg1, dict):
			return InMemoryDoc(arg1, cur_db)
		return cur_db.tables[arg1][arg2]

	def delete_doc(doctype: str, name: str, ignore_permissions: bool = False):
		frappe_mod.db.tables.get(doctype, {}).pop(name, None)

	def log_error(title: str = "", message: str = ""):
		frappe_mod.db.errors.append((title, message))

	def only_for(roles):
		return None

	frappe_mod.whitelist = whitelist
	frappe_mod.throw = throw
	frappe_mod.get_cached_doc = get_cached_doc
	frappe_mod.get_doc = get_doc
	frappe_mod.delete_doc = delete_doc
	frappe_mod.log_error = log_error
	frappe_mod.only_for = only_for

	utils_mod = types.ModuleType("frappe.utils")
	utils_mod.cint = lambda v: int(v or 0)
	utils_mod.flt = lambda v: float(v or 0.0)
	utils_mod.get_datetime = lambda v: v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
	utils_mod.getdate = lambda v: (
		v.date()
		if isinstance(v, datetime)
		else (v if isinstance(v, date) else date.fromisoformat(str(v)[:10]))
	)

	model_mod = types.ModuleType("frappe.model")
	doc_mod = types.ModuleType("frappe.model.document")

	class Document:
		pass

	doc_mod.Document = Document
	model_mod.document = doc_mod

	frappe_mod.utils = utils_mod
	frappe_mod.model = model_mod

	sys.modules["frappe"] = frappe_mod
	sys.modules["frappe.utils"] = utils_mod
	sys.modules["frappe.model"] = model_mod
	sys.modules["frappe.model.document"] = doc_mod
	return db
