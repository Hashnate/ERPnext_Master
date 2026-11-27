// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sri Lanka Payroll Entry", {
	setup: function (frm) {
		frm.set_query("company", function () {
			return { filters: { country: "Sri Lanka" } };
		});
		frm.set_query("company_bank_account", function () {
			return {
				filters: {
					is_company_account: 1,
					company: frm.doc.company,
					disabled: 0,
				},
			};
		});
		for (const field of [
			"salary_expense_account",
			"payroll_payable_account",
			"epf_employer_expense_account",
			"etf_employer_expense_account",
			"epf_payable_account",
			"etf_payable_account",
			"apit_payable_account",
			"other_deductions_account",
		]) {
			frm.set_query(field, function () {
				return { filters: { company: frm.doc.company, is_group: 0 } };
			});
		}
	},

	onload: function (frm) {
		if (frm.is_new() && !frm.doc.from_date && !frm.doc.to_date) {
			frm.set_value("from_date", frappe.datetime.month_start());
			frm.set_value("to_date", frappe.datetime.month_end());
		}
	},

	refresh: function (frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Fetch Employees"), function () {
				frm.call("fetch_employees").then((r) => {
					frm.refresh_fields();
					const added = r.message || 0;
					frappe.show_alert({
						message: __("Fetched {0} employee(s) and calculated EPF, ETF, and APIT.", [added]),
						indicator: "green",
					});
				});
			});
		}

		if (frm.doc.docstatus === 1 && (frm.doc.employees || []).length) {
			frm.add_custom_button(__("Download Bank Payment File"), function () {
				frappe.prompt(
					[
						{
							fieldname: "bank_format",
							fieldtype: "Select",
							label: __("Bank Format"),
							options: "SLIPS\nCOMBANK\nSAMPATH\nHNB\nBOC",
							default: frm.doc.bank_file_format || "SLIPS",
							reqd: 1,
						},
					],
					function (values) {
						frappe.call({
							method: "erpnext.regional.sri_lanka.bank_payment.generate_sri_lanka_payroll_bank_file",
							args: {
								payroll_entry_name: frm.doc.name,
								bank_format: values.bank_format,
							},
							callback: function (r) {
								if (!r.message) return;
								const blob = new Blob([r.message.content], {
									type: "text/plain;charset=utf-8",
								});
								const url = URL.createObjectURL(blob);
								const link = document.createElement("a");
								link.href = url;
								link.download = r.message.filename;
								document.body.appendChild(link);
								link.click();
								document.body.removeChild(link);
								URL.revokeObjectURL(url);
							},
						});
					},
					__("Generate Sri Lanka Salary Bank File"),
					__("Download")
				);
			});
		}
	},
});

function recalculate_payroll_entry(frm) {
	if (frm.doc.docstatus !== 0 || !frm.doc.company) {
		return;
	}
	frm.call("recalculate_payroll").then(() => {
		frm.refresh_fields();
	});
}

frappe.ui.form.on("Sri Lanka Payroll Employee", {
	basic_salary: (frm) => recalculate_payroll_entry(frm),
	epf_liable_allowances: (frm) => recalculate_payroll_entry(frm),
	non_epf_allowances: (frm) => recalculate_payroll_entry(frm),
	lump_sum_bonus: (frm) => recalculate_payroll_entry(frm),
	other_deductions: (frm) => recalculate_payroll_entry(frm),
	is_non_resident_for_apit: (frm) => recalculate_payroll_entry(frm),
	employees_remove: (frm) => recalculate_payroll_entry(frm),
});
