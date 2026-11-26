// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

function register_sri_lanka_bank_button(doctype, method, arg_name, has_rows) {
	frappe.ui.form.on(doctype, {
		refresh: function (frm) {
			if (frm.is_new() || !frm.doc.company || !has_rows(frm)) {
				return;
			}

			frappe.db.get_value("Company", frm.doc.company, "country", (r) => {
				if (!r || r.country !== "Sri Lanka") return;

				frm.add_custom_button(__("Download Sri Lanka Bank File"), function () {
					frappe.prompt(
						[
							{
								fieldname: "bank_format",
								fieldtype: "Select",
								label: __("Bank Format"),
								options: "SLIPS\nCOMBANK\nSAMPATH\nHNB\nBOC",
								default: "SLIPS",
								reqd: 1,
							},
						],
						function (values) {
							frappe.call({
								method: method,
								args: {
									[arg_name]: frm.doc.name,
									bank_format: values.bank_format,
								},
								callback: function (res) {
									if (!res.message) return;
									const blob = new Blob([res.message.content], {
										type: "text/plain;charset=utf-8",
									});
									const url = URL.createObjectURL(blob);
									const link = document.createElement("a");
									link.href = url;
									link.download = res.message.filename;
									document.body.appendChild(link);
									link.click();
									document.body.removeChild(link);
									URL.revokeObjectURL(url);
								},
							});
						},
						__("Generate Sri Lanka Bank Payment File"),
						__("Download")
					);
				});
			});
		},
	});
}

register_sri_lanka_bank_button(
	"Payment Order",
	"erpnext.regional.sri_lanka.bank_payment.generate_payment_order_bank_file",
	"payment_order_name",
	(frm) => (frm.doc.references || []).length > 0
);

register_sri_lanka_bank_button(
	"Payroll Entry",
	"erpnext.regional.sri_lanka.bank_payment.generate_payroll_bank_file",
	"payroll_entry_name",
	(frm) => frm.doc.docstatus === 1
);
