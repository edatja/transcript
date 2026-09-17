"""Transcript label -> normalized field name.

IRS transcripts spell out box names in prose rather than printing box numbers:
a 1099-INT box 1 arrives as ``Interest:....$500.00``.  This table turns those
printed labels into stable machine keys so that totals can be rolled up and
compared across forms and years.

Keys are the output of ``fields.normalize_label`` (lowercase, punctuation
stripped, whitespace collapsed), because the IRS is inconsistent about
quoting, hyphens and possessives between form types and tax years.

ANY label not listed here is still captured verbatim in ``raw_fields``.
This table only controls what gets *totalled*, never what gets *kept*.
"""

from __future__ import annotations

from .fields import normalize_label

# ---------------------------------------------------------------------------
# Labels that mean the same thing on every form.
# ---------------------------------------------------------------------------
_COMMON = {
    "Federal Income Tax Withheld": "federal_withholding",
    "Federal Tax Withheld": "federal_withholding",
    "Foreign Tax Paid": "foreign_tax_paid",
    "Investment Expenses": "investment_expenses",
    "State Income Tax Withheld": "state_withholding",
    "State Tax Withheld": "state_withholding",
    "Local Income Tax Withheld": "local_withholding",
}

# ---------------------------------------------------------------------------
# Form-specific labels.  Checked before _COMMON so a form can override.
# ---------------------------------------------------------------------------
_BY_FORM: dict[str, dict[str, str]] = {
    "W-2": {
        "Wages, Tips and Other Compensation": "wages",
        "Social Security Wages": "ss_wages",
        "Social Security Tax Withheld": "ss_tax_withheld",
        "Medicare Wages and Tips": "medicare_wages",
        "Medicare Tax Withheld": "medicare_tax_withheld",
        "Social Security Tips": "ss_tips",
        "Allocated Tips": "allocated_tips",
        "Dependent Care Benefits": "dependent_care_benefits",
        "Deferred Compensation": "deferred_comp",
        'Code "Q" Nontaxable Combat Pay': "combat_pay",
        'Code "W" Employer Contributions to a Health Savings Account':
            "hsa_employer_contributions",
        'Code "AA" Designated Roth Contributions under a Section 401(k) Plan':
            "roth_401k",
        'Code "BB" Designated Roth Contributions under a Section 403(b) Plan':
            "roth_403b",
        'Code "DD" Cost of Employer-Sponsored Health Coverage':
            "employer_health_coverage_cost",
        'Code "EE" Designated Roth Contributions Under a Governmental Section 457(b) Plan':
            "roth_457b",
    },
    "W-2G": {
        "Gross Winnings": "gambling_winnings",
    },
    "1099-NEC": {
        "Non-Employee Compensation": "nonemployee_comp",
        "Nonemployee Compensation": "nonemployee_comp",
    },
    "1099-MISC": {
        "Rents": "rents",
        "Royalties": "royalties",
        "Other Income": "other_income",
        "Fishing Boat Proceeds": "fishing_boat_proceeds",
        "Medical and Health Care Payments": "medical_health_payments",
        "Non-Employee Compensation": "nonemployee_comp",
        "Nonemployee Compensation": "nonemployee_comp",
        "Substitute Payments for Dividends": "substitute_payments",
        "Substitute Payments in Lieu of Dividends or Interest":
            "substitute_payments",
        "Crop Insurance Proceeds": "crop_insurance_proceeds",
        "Gross Proceeds Paid to an Attorney": "attorney_gross_proceeds",
        "Excess Golden Parachute Payments": "excess_golden_parachute",
        "Section 409A Income": "section_409a_income",
        "Nonqualified Deferred Compensation": "nonqualified_deferred_comp",
    },
    "1099-INT": {
        "Interest": "interest",
        "Early Withdrawal Penalty": "early_withdrawal_penalty",
        "Interest on US Savings Bonds and Treasury Obligations":
            "savings_bond_interest",
        "Tax Exempt Interest": "tax_exempt_interest",
        "Specified Private Activity Bond Interest":
            "private_activity_bond_interest",
        "Market Discount": "market_discount",
        "Bond Premium": "bond_premium",
        "Bond Premium on Treasury Obligation": "bond_premium_treasury",
        "Bond Premium on Tax Exempt Bond": "bond_premium_tax_exempt",
    },
    "1099-OID": {
        "Original Issue Discount": "original_issue_discount",
        "Other Periodic Interest": "other_periodic_interest",
        "Original Issue Discount on U.S. Treasury Obligations":
            "oid_treasury",
        "Early Withdrawal Penalty": "early_withdrawal_penalty",
        "Market Discount": "market_discount",
        "Bond Premium": "bond_premium",
    },
    "1099-DIV": {
        "Ordinary Dividend": "ordinary_dividends",
        "Total Ordinary Dividends": "ordinary_dividends",
        "Qualified Dividends": "qualified_dividends",
        "Total Capital Gain Distribution": "capital_gain_distributions",
        "Total Capital Gain Distributions": "capital_gain_distributions",
        "Unrecaptured Section 1250 Gain": "unrecaptured_1250_gain",
        "Section 1202 Gain": "section_1202_gain",
        "Collectibles (28%) Gain": "collectibles_gain",
        "Nondividend Distributions": "nondividend_distributions",
        "Section 199A Dividends": "section_199a_dividends",
        "Cash Liquidation Distribution": "cash_liquidation_distribution",
        "Non-Cash Liquidation Distribution": "noncash_liquidation_distribution",
        "Exempt Interest Dividend": "exempt_interest_dividends",
        "Exempt Interest Dividends": "exempt_interest_dividends",
    },
    "1099-B": {
        "Gross Proceeds": "gross_proceeds",
        "Proceeds": "gross_proceeds",
        "Cost or Other Basis": "cost_basis",
        "Wash Sale Loss Disallowed": "wash_sale_loss_disallowed",
        "Profit or (Loss) Realized in the Year": "realized_profit_loss",
        "Aggregate Profit or (Loss)": "aggregate_profit_loss",
        "Accrued Market Discount": "market_discount",
    },
    "1099-R": {
        "Gross Distribution": "gross_distribution",
        "Taxable Amount": "taxable_amount",
        "Capital Gain": "capital_gain",
        "Employee Contributions": "employee_contributions",
        "Total Employee Contributions": "employee_contributions",
        "Net Unrealized Appreciation": "net_unrealized_appreciation",
        "Amount Allocable to IRR within 5 Years": "irr_allocable_5yr",
    },
    "1099-G": {
        "Unemployment Compensation": "unemployment_compensation",
        "State or Local Income Tax Refunds, Credits or Offsets":
            "state_tax_refund",
        "Taxable Grants": "taxable_grants",
        "Agriculture Payments": "agriculture_payments",
        "Market Gain": "market_gain",
        "RTAA Payments": "rtaa_payments",
    },
    "1099-K": {
        "Gross Amount of Payment Card/Third Party Network Transactions":
            "gross_payment_card_transactions",
        "Gross Amount": "gross_payment_card_transactions",
        "Card Not Present Transactions": "card_not_present_transactions",
    },
    "1099-S": {
        "Gross Proceeds": "gross_proceeds",
        "Buyer's Part of Real Estate Tax": "buyer_real_estate_tax",
    },
    "1099-SA": {
        "Gross Distribution": "gross_distribution",
        "Earnings on Excess Contributions": "earnings_on_excess",
        "Fair Market Value on Date of Death": "fmv_on_death",
    },
    "1099-Q": {
        "Gross Distribution": "gross_distribution",
        "Earnings": "earnings",
        "Basis": "basis",
    },
    "1099-C": {
        "Amount of Debt Cancelled": "debt_cancelled",
        "Amount of Debt Discharged": "debt_cancelled",
        "Interest if included in Box 2": "cancelled_debt_interest",
        "Fair Market Value of Property": "fmv_property",
    },
    "1099-A": {
        "Balance of Principal Outstanding": "principal_outstanding",
        "Fair Market Value of Property": "fmv_property",
    },
    "1099-PATR": {
        "Patronage Dividends": "patronage_dividends",
        "Non-Patronage Distributions": "nonpatronage_distributions",
        "Per-Unit Retain Allocations": "per_unit_retain",
        "Section 199A(g) Deduction": "section_199a_g_deduction",
    },
    "1099-LTC": {
        "Gross Long Term Care Benefits Paid": "ltc_benefits",
        "Accelerated Death Benefits Paid": "accelerated_death_benefits",
    },
    "1098": {
        "Mortgage Interest Received from Payer(s)/Borrower(s)":
            "mortgage_interest",
        "Mortgage Interest Received from Payer/Borrower": "mortgage_interest",
        "Points Paid on Purchase of Principal Residence": "points_paid",
        "Refund of Overpaid Interest": "refund_of_overpaid_interest",
        "Mortgage Insurance Premiums": "mortgage_insurance_premiums",
        "Outstanding Mortgage Principal": "outstanding_mortgage_principal",
        "Real Estate Taxes": "real_estate_taxes",
    },
    "1098-E": {
        "Student Loan Interest": "student_loan_interest",
        "Student Loan Interest Received by Lender": "student_loan_interest",
    },
    "1098-T": {
        "Payments Received for Qualified Tuition and Related Expenses":
            "qualified_tuition_payments",
        "Amounts Billed for Qualified Tuition and Related Expenses":
            "qualified_tuition_billed",
        "Scholarships or Grants": "scholarships_or_grants",
        "Adjustments Made for Prior Year": "tuition_prior_year_adjustment",
        "Adjustments to Scholarships or Grants for a Prior Year":
            "scholarship_prior_year_adjustment",
    },
    "1098-C": {
        "Gross Proceeds from Sale": "vehicle_gross_proceeds",
        "Value of Goods and Services": "vehicle_goods_and_services",
    },
    "5498": {
        "IRA Contributions": "ira_contributions",
        "Rollover Contributions": "rollover_contributions",
        "Roth IRA Conversion Amount": "roth_conversion",
        "Recharacterized Contributions": "recharacterized_contributions",
        "Fair Market Value of Account": "fmv_account",
        "SEP Contributions": "sep_contributions",
        "SIMPLE Contributions": "simple_contributions",
        "Roth IRA Contributions": "roth_ira_contributions",
        "RMD Amount": "rmd_amount",
        "Postponed Contribution": "postponed_contribution",
        "Repayments": "repayments",
    },
    "5498-SA": {
        "Total Contributions Made": "hsa_contributions",
        "Employee or Self-Employed Person's Archer MSA Contributions":
            "archer_msa_contributions",
        "Rollover Contributions": "rollover_contributions",
        "Fair Market Value of HSA, Archer MSA or MA MSA": "fmv_account",
    },
    "5498-ESA": {
        "Coverdell ESA Contributions": "esa_contributions",
        "Rollover Contributions": "rollover_contributions",
    },
    "SSA-1099": {
        # The Wage & Income transcript prints the SSA net benefit under the
        # generic label "Pensions and Annuities". It is social security, and
        # it belongs on 1040 line 6a -- NOT line 5a with pension income.
        "Pensions and Annuities": "social_security_benefits",
        "Benefits Paid": "social_security_benefits",
        "Benefits Repaid": "social_security_repaid",
        "Net Benefits": "social_security_benefits",
        "Voluntary Federal Income Tax Withheld": "federal_withholding",
        "Workers Compensation Offset": "workers_comp_offset",
        "Medicare Premiums": "medicare_premiums",
    },
    "RRB-1099": {
        "Net Social Security Equivalent Benefit Portion of Tier 1 Paid":
            "social_security_benefits",
        "Federal Income Tax Withheld": "federal_withholding",
    },
    "1042-S": {
        "Gross Income": "gross_income_1042s",
        "Federal Tax Withheld": "federal_withholding",
        "US Federal Tax Withheld": "federal_withholding",
    },
    "1095-A": {
        "Annual Premium Amount": "marketplace_premium",
        "Annual Premium Amount of SLCSP": "marketplace_slcsp",
        "Annual Advance Payment of PTC": "marketplace_advance_ptc",
    },
    "K-1": {
        "Ordinary Business Income": "k1_ordinary_business_income",
        "Ordinary Income": "k1_ordinary_business_income",
        "Net Rental Real Estate Income": "k1_rental_real_estate_income",
        "Other Net Rental Income": "k1_other_rental_income",
        "Guaranteed Payments": "k1_guaranteed_payments",
        "Interest Income": "interest",
        "Ordinary Dividends": "ordinary_dividends",
        "Qualified Dividends": "qualified_dividends",
        "Royalties": "royalties",
        "Net Short-Term Capital Gain": "k1_short_term_capital_gain",
        "Net Long-Term Capital Gain": "k1_long_term_capital_gain",
        "Self-Employment Earnings": "k1_self_employment_earnings",
        "Section 179 Deduction": "k1_section_179",
        "Distributions": "k1_distributions",
    },
}

# Non-money fields worth promoting out of raw_fields because they change how
# an amount is treated on the return.
INDICATOR_LABELS = {
    "Submission Type": "submission_type",
    "Account Number (Optional)": "account_number",
    "Account Number": "account_number",
    "Distribution Code(s)": "distribution_code",
    "Distribution Code": "distribution_code",
    "IRA/SEP/SIMPLE Indicator": "ira_sep_simple_indicator",
    "Taxable Amount Not Determined": "taxable_amount_not_determined",
    "Total Distribution": "total_distribution_indicator",
    "Type of Gain or Loss": "gain_loss_type",
    "Second Notice Indicator": "second_notice_indicator",
    "Direct Sales Indicator": "direct_sales_indicator",
    "HSA Indicator": "hsa_indicator",
    "Half-time Student Indicator": "half_time_student",
    "Graduate Student Indicator": "graduate_student",
    "Identifiable Event Code": "identifiable_event_code",
    "Statutory Employee": "statutory_employee",
    "Retirement Plan Indicator": "retirement_plan_indicator",
    "Third Party Sick Pay Indicator": "third_party_sick_pay",
}


def _build() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    common = {normalize_label(k): v for k, v in _COMMON.items()}
    by_form = {
        form: {normalize_label(k): v for k, v in table.items()}
        for form, table in _BY_FORM.items()
    }
    return common, by_form


COMMON_ALIASES, FORM_ALIASES = _build()
INDICATOR_ALIASES = {normalize_label(k): v for k, v in INDICATOR_LABELS.items()}


def field_for(form_type: str, label: str) -> str | None:
    """Normalized field key for ``label`` on ``form_type``, or None.

    Form-specific wins over common, so SSA-1099's "Pensions and Annuities"
    resolves to social security rather than to pension income.
    """
    key = normalize_label(label)
    # "K-1 (1065)" and friends all share the K-1 table.
    table_name = "K-1" if form_type.startswith("K-1") else form_type
    form_table = FORM_ALIASES.get(table_name, {})
    return form_table.get(key) or COMMON_ALIASES.get(key)


def indicator_for(label: str) -> str | None:
    """Normalized key for a non-money field worth promoting, or None."""
    return INDICATOR_ALIASES.get(normalize_label(label))


def known_fields() -> set[str]:
    """Every normalized field key this table can produce."""
    keys = set(COMMON_ALIASES.values())
    for table in FORM_ALIASES.values():
        keys.update(table.values())
    return keys
