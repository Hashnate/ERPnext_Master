// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sri Lanka Payroll Settings", {
	refresh: function (frm) {
		frm.set_query("company", function () {
			return {
				filters: {
					country: "Sri Lanka",
				},
			};
		});
	},
});
