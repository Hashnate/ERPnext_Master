// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sri Lanka VAT Settings", {
	refresh: function (frm) {
		frm.set_query("company", function () {
			return {
				filters: {
					country: "Sri Lanka",
				},
			};
		});
		frm.set_query("account", "vat_accounts", function () {
			return {
				filters: {
					company: frm.doc.company,
					account_type: "Tax",
					is_group: 0,
				},
			};
		});
	},
});
