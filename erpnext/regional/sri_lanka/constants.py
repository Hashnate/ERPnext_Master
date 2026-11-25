# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Default configuration values for Sri Lanka localization.

Rates and tax slabs defined here serve only as initial seed defaults for Settings
DocTypes and Templates; runtime calculations always read from configured records.
"""

COUNTRY_NAME = "Sri Lanka"
DEFAULT_CURRENCY = "LKR"

# Seed default standard VAT rate (%) — configurable via Tax Templates / Sri Lanka VAT Settings
DEFAULT_VAT_RATE = 18.0

# Seed default statutory payroll rates (%) — configurable via Sri Lanka Payroll Settings
DEFAULT_EPF_EMPLOYEE_RATE = 8.0
DEFAULT_EPF_EMPLOYER_RATE = 12.0
DEFAULT_ETF_EMPLOYER_RATE = 3.0
DEFAULT_NON_RESIDENT_APIT_RATE = 25.0

# Seed default monthly APIT progressive slabs (LKR) — configurable via Sri Lanka APIT Slab
DEFAULT_MONTHLY_APIT_SLABS = (
	{"from_amount": 0.0, "to_amount": 150000.0, "tax_rate": 0.0},
	{"from_amount": 150000.0, "to_amount": 233333.33, "tax_rate": 6.0},
	{"from_amount": 233333.33, "to_amount": 275000.0, "tax_rate": 18.0},
	{"from_amount": 275000.0, "to_amount": 316666.67, "tax_rate": 24.0},
	{"from_amount": 316666.67, "to_amount": 358333.33, "tax_rate": 30.0},
	{"from_amount": 358333.33, "to_amount": 0.0, "tax_rate": 36.0},
)

# Common Sri Lanka licensed commercial bank 4-digit SLIPS codes
SRI_LANKA_BANK_CODES = {
	"Bank of Ceylon": "7010",
	"People's Bank": "7135",
	"Commercial Bank of Ceylon": "7056",
	"Hatton National Bank": "7083",
	"Sampath Bank": "7278",
	"Seylan Bank": "7287",
	"Nations Trust Bank": "7162",
	"National Development Bank": "7214",
	"DFCC Bank": "7454",
	"Union Bank of Colombo": "7302",
	"Pan Asia Banking Corporation": "7311",
	"Amana Bank": "7463",
	"Cargills Bank": "7481",
	"HSBC": "7092",
	"Standard Chartered Bank": "7038",
	"Citibank": "7047",
}

SUPPORTED_BANK_FILE_FORMATS = ("SLIPS", "COMBANK", "SAMPATH", "HNB", "BOC")
