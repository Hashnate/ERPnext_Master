app_name = "worksight_hrms"
app_title = "WorkSight HRMS"
app_publisher = "Hasnet"
app_description = "WorkSight check-in webhook to ERPNext HRMS Employee Checkin, Late/Overtime tracking, and Payroll inputs"
app_email = "dev@hasnet.local"
app_license = "MIT"

required_apps = ["erpnext", "hrms"]

doc_events = {
	"Attendance": {
		"on_submit": "worksight_hrms.worksight_hrms.services.attendance_processor.on_attendance_submit",
		"on_cancel": "worksight_hrms.worksight_hrms.services.attendance_processor.on_attendance_cancel",
	},
	"WorkSight Late Record": {
		"on_submit": "worksight_hrms.worksight_hrms.services.payroll_sync.on_late_record_submit",
		"on_cancel": "worksight_hrms.worksight_hrms.services.payroll_sync.on_late_record_cancel",
	},
	"WorkSight Overtime Record": {
		"on_submit": "worksight_hrms.worksight_hrms.services.payroll_sync.on_overtime_record_submit",
		"on_cancel": "worksight_hrms.worksight_hrms.services.payroll_sync.on_overtime_record_cancel",
	},
}

scheduler_events = {
	"daily": [
		"worksight_hrms.worksight_hrms.services.payroll_sync.scheduled_sync_pending_records",
	],
}
