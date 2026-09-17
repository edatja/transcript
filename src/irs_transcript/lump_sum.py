"""Section 86(e) lump-sum social security election.

When a retroactive award pays several years of benefits at once, taxing the
whole thing in the year of receipt can push almost all of it to the 85%
inclusion tier -- even though the taxpayer's income in the years the benefits
were *for* may have been low enough to tax little or none of it.

Section 86(e) lets the taxpayer cap the inclusion at what the arrears would
have added to gross income in the years they are attributable to. It is a
CEILING, not an amendment: the prior years are not reopened or recomputed,
and the whole payment still reports in the year received.

The statute, for tax year 2025:

  §86(b)(1)      provisional income = modified AGI + one-half of benefits
  §86(b)(2)(B)   modified AGI is increased by tax-exempt interest
  §86(c)(1)      base amount: $25,000, or $32,000 on a joint return
  §86(c)(2)      adjusted base amount: $34,000, or $44,000 on a joint return
  §86(a)(1)      below the adjusted base amount, include the lesser of
                 one-half of benefits or one-half of the excess over base
  §86(a)(2)      above it, include the lesser of
                   85% of the excess over the adjusted base amount
                     + the lesser of the §86(a)(1) amount or half the gap
                       between the two thresholds,
                 or 85% of benefits
  §86(e)(2)(A)   a benefit is attributable to the year whose generally
                 applicable payment date fell in that year

For a married taxpayer who does not file jointly and does not live apart from
their spouse all year, both thresholds are zero -- §86(c)(1)(C).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

HALF = Decimal("0.5")
EIGHTY_FIVE = Decimal("0.85")
ZERO = Decimal("0")


class FilingStatus:
    SINGLE = "single"
    JOINT = "joint"
    HEAD_OF_HOUSEHOLD = "hoh"
    QUALIFYING_SURVIVING_SPOUSE = "qss"
    SEPARATE_APART = "mfs_apart"        # lived apart all year
    SEPARATE_TOGETHER = "mfs_together"  # thresholds are zero

    ALL = {
        SINGLE, JOINT, HEAD_OF_HOUSEHOLD, QUALIFYING_SURVIVING_SPOUSE,
        SEPARATE_APART, SEPARATE_TOGETHER,
    }


# §86(c)(1) and §86(c)(2). These are fixed dollar figures -- they have never
# been indexed for inflation, which is why a lump sum so easily lands in the
# top tier in the year of receipt.
_THRESHOLDS: dict[str, tuple[Decimal, Decimal]] = {
    FilingStatus.SINGLE: (Decimal("25000"), Decimal("34000")),
    FilingStatus.HEAD_OF_HOUSEHOLD: (Decimal("25000"), Decimal("34000")),
    FilingStatus.QUALIFYING_SURVIVING_SPOUSE: (Decimal("25000"), Decimal("34000")),
    FilingStatus.SEPARATE_APART: (Decimal("25000"), Decimal("34000")),
    FilingStatus.JOINT: (Decimal("32000"), Decimal("44000")),
    FilingStatus.SEPARATE_TOGETHER: (ZERO, ZERO),
}


def thresholds(filing_status: str) -> tuple[Decimal, Decimal]:
    """Base amount and adjusted base amount for a filing status."""
    try:
        return _THRESHOLDS[filing_status]
    except KeyError:
        raise ValueError(
            f"unknown filing status {filing_status!r}; expected one of "
            f"{', '.join(sorted(FilingStatus.ALL))}"
        ) from None


@dataclass
class TaxableBenefits:
    """One year's §86 computation, with the intermediate figures shown."""

    benefits: Decimal
    modified_agi: Decimal
    provisional_income: Decimal
    base_amount: Decimal
    adjusted_base_amount: Decimal
    taxable: Decimal
    tier: str   # "none", "50%", "85%"

    @property
    def included_pct(self) -> Decimal:
        if self.benefits == 0:
            return ZERO
        return (self.taxable / self.benefits * 100).quantize(Decimal("0.1"))


def taxable_social_security(
    *,
    benefits: Decimal,
    other_income: Decimal,
    filing_status: str,
    tax_exempt_interest: Decimal = ZERO,
) -> TaxableBenefits:
    """How much of ``benefits`` is included in gross income under §86.

    ``other_income`` is modified AGI BEFORE any social security -- i.e. AGI
    with the benefits themselves left out. ``tax_exempt_interest`` is added
    per §86(b)(2)(B).

    Every argument is keyword-only on purpose. ``benefits`` and
    ``other_income`` are both money, so passing them the wrong way round
    would return a confident, plausible and wrong figure instead of raising.
    """
    base, adjusted_base = thresholds(filing_status)
    modified_agi = other_income + tax_exempt_interest
    provisional = modified_agi + HALF * benefits

    if benefits <= 0 or provisional <= base:
        return TaxableBenefits(
            benefits=benefits, modified_agi=modified_agi,
            provisional_income=provisional, base_amount=base,
            adjusted_base_amount=adjusted_base, taxable=ZERO, tier="none",
        )

    # §86(a)(1): the lesser of half the benefits or half the excess over base.
    excess_over_base = provisional - base
    tier_one = min(HALF * benefits, HALF * excess_over_base)

    if provisional <= adjusted_base:
        return TaxableBenefits(
            benefits=benefits, modified_agi=modified_agi,
            provisional_income=provisional, base_amount=base,
            adjusted_base_amount=adjusted_base,
            taxable=tier_one.quantize(Decimal("0.01")), tier="50%",
        )

    # §86(a)(2): 85% of the excess over the adjusted base amount, plus the
    # lesser of the §86(a)(1) amount or half the gap between the thresholds;
    # capped at 85% of the benefits.
    gap_cap = HALF * (adjusted_base - base)
    additional = EIGHTY_FIVE * (provisional - adjusted_base) + min(tier_one, gap_cap)
    taxable = min(additional, EIGHTY_FIVE * benefits)
    return TaxableBenefits(
        benefits=benefits, modified_agi=modified_agi,
        provisional_income=provisional, base_amount=base,
        adjusted_base_amount=adjusted_base,
        taxable=taxable.quantize(Decimal("0.01")), tier="85%",
    )


@dataclass
class AttributionYear:
    """One earlier year that part of the lump sum is attributable to."""

    year: str
    arrears: Decimal                      # paid now, attributable to this year
    other_income: Decimal                 # that year's MAGI before any benefits
    filing_status: str
    benefits_already_received: Decimal = ZERO   # benefits actually paid that year
    tax_exempt_interest: Decimal = ZERO
    # False when that year's income is not yet known. Such a year cannot be
    # left out of the ceiling and the answer still be sound: omitting it
    # UNDERSTATES the ceiling, which makes the election look better than it
    # is. So a run with any unknown year reports no bottom line at all.
    known: bool = True

    # Filled in by the computation.
    before: TaxableBenefits | None = None
    after: TaxableBenefits | None = None

    @property
    def increase(self) -> Decimal:
        """The increase in that year's gross income -- the §86(e) measure."""
        if self.before is None or self.after is None:
            return ZERO
        return self.after.taxable - self.before.taxable


@dataclass
class LumpSumResult:
    total_benefits: Decimal
    current_year_portion: Decimal
    arrears_total: Decimal
    years: list[AttributionYear] = field(default_factory=list)

    without_election: TaxableBenefits | None = None
    current_portion_only: TaxableBenefits | None = None
    ceiling: Decimal = ZERO          # §86(e)(1): sum of the prior-year increases
    with_election: Decimal = ZERO
    unknown_years: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """False when any attribution year's income is still missing."""
        return not self.unknown_years

    @property
    def savings(self) -> Decimal:
        """Reduction in TAXABLE INCOME, not in tax. Only meaningful if complete."""
        if self.without_election is None or not self.complete:
            return ZERO
        return self.without_election.taxable - self.with_election

    @property
    def election_helps(self) -> bool:
        return self.complete and self.savings > 0


def compute_election(
    total_benefits: Decimal,
    current_year_other_income: Decimal,
    current_year_filing_status: str,
    years: list[AttributionYear],
    current_year_tax_exempt_interest: Decimal = ZERO,
) -> LumpSumResult:
    """Run the §86(e) comparison.

    ``total_benefits`` is everything reported on the SSA-1099 for the year of
    receipt, arrears included. Each ``AttributionYear`` carries the portion
    attributable to an earlier year plus that year's own income figures.
    """
    arrears_total = sum((y.arrears for y in years), ZERO)
    current_portion = total_benefits - arrears_total

    result = LumpSumResult(
        total_benefits=total_benefits,
        current_year_portion=current_portion,
        arrears_total=arrears_total,
        years=list(years),
    )

    if arrears_total > total_benefits:
        result.warnings.append(
            f"the prior-year payments ({arrears_total:,.2f}) exceed total "
            f"benefits ({total_benefits:,.2f}) -- check the SSA-1099 figures"
        )

    # What happens with no election: everything taxed in the year of receipt.
    result.without_election = taxable_social_security(
        benefits=total_benefits,
        other_income=current_year_other_income,
        filing_status=current_year_filing_status,
        tax_exempt_interest=current_year_tax_exempt_interest,
    )

    # With the election, the current-year portion is still taxed normally,
    # using the year-of-receipt income.
    result.current_portion_only = taxable_social_security(
        benefits=current_portion,
        other_income=current_year_other_income,
        filing_status=current_year_filing_status,
        tax_exempt_interest=current_year_tax_exempt_interest,
    )

    # Each earlier year: recompute that year with its arrears added.
    for y in years:
        if not y.known:
            result.unknown_years.append(y.year)
            continue
        y.before = taxable_social_security(
            benefits=y.benefits_already_received,
            other_income=y.other_income,
            filing_status=y.filing_status,
            tax_exempt_interest=y.tax_exempt_interest,
        )
        y.after = taxable_social_security(
            benefits=y.benefits_already_received + y.arrears,
            other_income=y.other_income,
            filing_status=y.filing_status,
            tax_exempt_interest=y.tax_exempt_interest,
        )

    result.ceiling = sum((y.increase for y in years if y.known), ZERO)
    result.with_election = result.current_portion_only.taxable + result.ceiling

    if result.unknown_years:
        missing = ", ".join(sorted(result.unknown_years))
        result.warnings.append(
            f"INCOMPLETE: no income figures for {missing}. Each missing year "
            f"can only ADD to the ceiling, so leaving them out would make the "
            f"election look better than it is. No bottom line is given until "
            f"every year is supplied -- the per-year figures below are still "
            f"correct for the years that are filled in."
        )
    elif not result.election_helps:
        result.warnings.append(
            "the election does NOT reduce taxable income on these figures -- "
            "it is elective, so simply do not make it"
        )
    return result
