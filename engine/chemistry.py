"""
PoolMon Chemistry Calculation Engine
=====================================

Pure Python module - no web framework, no database, no external dependencies.
This is intentional: the math has to be provably correct in isolation before
anything else (API, UI) ever touches it. Every function here is a pure
function (same inputs always produce same outputs, no hidden state, no I/O).

Built against the Trouble Free Pool (TFP) / PoolMath model, confirmed against
TFP guidance and cross-checked with first-principles stoichiometry rather than
relying on any single calculator site's claimed constants.

ORGANIZATION
------------
1. FC/CYA TARGET MATH       - "what should FC be, given CYA?"
2. DOSING MATH               - "how much chemical do I add to get there?"
   2a. Liquid chlorine        - SLAM and recovery use only
   2b. Cal-Hypo granular      - routine maintenance shock (adds CH as side effect)
   2c. Trichlor tablets        - floater, continuous maintenance (adds CYA as side effect)
   2d. Other chemicals         - stabilizer, muriatic acid, calcium, baking soda
3. SLAM / RECOVERY LOGIC     - "is this SLAM complete? what level is needed?"
4. SIDE-EFFECT TRACKING      - CYA creep from trichlor, CH rise from Cal-Hypo
5. RELIABILITY / GUARDRAILS  - bleach-out detection, zero-CYA cap, etc.

CHEMICAL SELECTION BY MODE
--------------------------
Recovery / SLAM:    liquid chlorine ONLY (no CYA or CH side effects to manage)
Routine maintenance:
  - Trichlor 3" tablets in floater (continuous, ~90% available chlorine)
    Side effect: +~6 ppm CYA per tablet per 10,000 gal (~7.4 ppm in Dan's pool)
    Risk: CYA creep over a season if not watched
  - Cal-Hypo granular shock as needed (~65-73% available chlorine)
    Side effect: +~0.7 ppm CH per 1 ppm FC added
    Risk: CH accumulation over repeated shockings

KEY CONSTANTS AND WHERE THEY COME FROM
---------------------------------------
- FC percentages of CYA (7.5% min / 11.5% target / 40% SLAM) are TFP's
  standard model, confirmed directly against TFP/PoolMath guidance.
- The liquid chlorine dosing constant is derived from first-principles
  stoichiometry, not copied from any calculator site:
      12.5% available chlorine = 12.5 g per 100 mL of solution
      1 US gallon = 3.785 L = 473 g available chlorine in that gallon
      473,000 mg / 37,854 L (= 10,000 gal in L) = 12.5 mg/L = 12.5 ppm
  This produces the clean, verifiable result: one gallon of N% liquid
  chlorine added to a 10,000-gallon pool raises FC by exactly N ppm.
  This generalizes cleanly to any pool size and any liquid strength.
- Cal-Hypo side-effect constant (CH per FC ppm) and Trichlor side-effect
  constant (CYA per tablet) are from TFP/PoolMath and standard pool
  chemistry references.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# =============================================================================
# 1. FC/CYA TARGET MATH
# =============================================================================

# TFP standard percentages of CYA used to derive FC targets.
FC_MIN_PERCENT_OF_CYA = 0.075            # 7.5% - never let FC drop below this
FC_TARGET_PERCENT_OF_CYA = 0.115         # 11.5% - normal maintenance target
FC_YELLOW_MUSTARD_PERCENT_OF_CYA = 0.15  # 15% - mustard/yellow algae minimum
FC_SLAM_PERCENT_OF_CYA = 0.40            # 40% - shock/SLAM level

# Guardrail: TFP guidance caps recommended FC at this value when CYA tests as
# a true zero, since a true-zero CYA reading is rare and more often indicates
# a test sensitivity issue than an actual absence of stabilizer.
ZERO_CYA_FC_CAP = 5.0

# Liquid-chlorine-pool recommended CYA operating band (TFP guidance).
CYA_RECOMMENDED_MIN = 30
CYA_RECOMMENDED_MAX = 60

# Warning threshold: CYA getting close to the upper band due to trichlor use.
CYA_CREEP_WARNING_THRESHOLD = 50  # warn at 50, hard limit is 60

# SLAM completion thresholds (three-part condition, see SlamStatus below).
OCLT_MAX_DROP_PPM = 1.0           # overnight chlorine loss must drop <= this
CC_MAX_FOR_SLAM_COMPLETE = 0.5    # combined chlorine must be <= this


@dataclass
class FCTargets:
    """The set of FC reference points for a given CYA level."""
    cya: float
    minimum_fc: float
    target_fc: float
    yellow_mustard_minimum_fc: float
    slam_fc: float
    cya_in_recommended_band: bool
    is_zero_cya_guardrail_active: bool


def calculate_fc_targets(cya: float) -> FCTargets:
    """
    Given a CYA reading, return the full set of FC reference points.

    Special case: if CYA is exactly 0, TFP guidance treats this as likely a
    test-sensitivity artifact rather than genuine zero stabilizer, and caps
    all FC recommendations at ZERO_CYA_FC_CAP rather than computing 0% of
    everything (which would nonsensically recommend FC=0).
    """
    if cya is None:
        raise ValueError("CYA reading is required to calculate FC targets")
    if cya < 0:
        raise ValueError("CYA cannot be negative")

    if cya == 0:
        return FCTargets(
            cya=0,
            minimum_fc=0,
            target_fc=ZERO_CYA_FC_CAP,
            yellow_mustard_minimum_fc=ZERO_CYA_FC_CAP,
            slam_fc=ZERO_CYA_FC_CAP,
            cya_in_recommended_band=False,
            is_zero_cya_guardrail_active=True,
        )

    return FCTargets(
        cya=cya,
        minimum_fc=round(cya * FC_MIN_PERCENT_OF_CYA, 2),
        target_fc=round(cya * FC_TARGET_PERCENT_OF_CYA, 2),
        yellow_mustard_minimum_fc=round(cya * FC_YELLOW_MUSTARD_PERCENT_OF_CYA, 2),
        slam_fc=round(cya * FC_SLAM_PERCENT_OF_CYA, 2),
        cya_in_recommended_band=(CYA_RECOMMENDED_MIN <= cya <= CYA_RECOMMENDED_MAX),
        is_zero_cya_guardrail_active=False,
    )


class FCStatus(Enum):
    BELOW_MINIMUM = "below_minimum"        # urgent - algae risk
    BELOW_TARGET = "below_target"          # acceptable but should be raised
    AT_TARGET = "at_target"                # within +/-10% of target, ideal
    ABOVE_TARGET = "above_target"          # higher than needed but not concerning
    AT_OR_ABOVE_SLAM = "at_or_above_slam"  # in shock/recovery territory


def classify_fc_status(current_fc: float, targets: FCTargets) -> FCStatus:
    """Classify a current FC reading against the computed targets."""
    if current_fc is None:
        raise ValueError("current_fc is required")

    if current_fc >= targets.slam_fc:
        return FCStatus.AT_OR_ABOVE_SLAM
    if current_fc < targets.minimum_fc:
        return FCStatus.BELOW_MINIMUM

    # "At target" defined as within +/-10% of the target value - avoids
    # a reading 0.05 ppm off from target being classified as wrong.
    target_band_low = targets.target_fc * 0.9
    target_band_high = targets.target_fc * 1.1

    if current_fc < target_band_low:
        return FCStatus.BELOW_TARGET
    if current_fc > target_band_high:
        return FCStatus.ABOVE_TARGET
    return FCStatus.AT_TARGET


# =============================================================================
# 2. DOSING MATH
# =============================================================================

@dataclass
class DoseResult:
    """
    Result of a dosing calculation, including the inputs that produced it.
    Designed to map directly onto the recommendations table's inputs_json
    content for the "Why?" / Knowledge Builder feature.

    side_effect_ppm and side_effect_parameter are populated for chemicals
    that have a known, quantifiable cumulative side effect (Cal-Hypo raises
    CH; Trichlor raises CYA). The UI should always display these so the user
    understands what accumulates with each dose.
    """
    chemical: str
    amount: float
    unit: str
    current_value: float
    target_value: float
    delta: float
    pool_volume_gallons: int
    calculation_shown: str
    notes: Optional[str] = None
    side_effect_ppm: Optional[float] = None       # e.g. CH rise from Cal-Hypo
    side_effect_parameter: Optional[str] = None   # e.g. "calcium_hardness"


# -----------------------------------------------------------------------------
# 2a. LIQUID CHLORINE  (recovery / SLAM only)
# -----------------------------------------------------------------------------

def dose_liquid_chlorine_gallons(
    current_fc: float,
    target_fc: float,
    pool_volume_gallons: int,
    chlorine_strength_pct: float = 12.5,
) -> DoseResult:
    """
    Calculate gallons of liquid chlorine needed to raise FC from current to
    target. Used for SLAM and recovery; not routine maintenance.

    DERIVATION (see module docstring for full stoichiometric proof):
    one gallon of N% liquid chlorine in a 10,000-gallon pool raises FC by
    exactly N ppm. Formula:

        gallons = (target_fc - current_fc) * (pool_volume / 10000) / strength_pct
    """
    if current_fc is None or target_fc is None:
        raise ValueError("current_fc and target_fc are required")
    if pool_volume_gallons <= 0:
        raise ValueError("pool_volume_gallons must be positive")
    if chlorine_strength_pct <= 0:
        raise ValueError("chlorine_strength_pct must be positive")

    delta = target_fc - current_fc

    if delta <= 0:
        return DoseResult(
            chemical="liquid_chlorine",
            amount=0.0,
            unit="gallons",
            current_value=current_fc,
            target_value=target_fc,
            delta=delta,
            pool_volume_gallons=pool_volume_gallons,
            calculation_shown="Current FC already at or above target - no dose needed",
            notes="No chlorine addition recommended; current FC meets or exceeds target.",
        )

    gallons_needed = (delta * (pool_volume_gallons / 10000)) / chlorine_strength_pct

    calc_shown = (
        f"({target_fc} - {current_fc} ppm) x ({pool_volume_gallons:,} gal / 10,000) "
        f"/ {chlorine_strength_pct}% = {round(gallons_needed, 3)} gal"
    )

    return DoseResult(
        chemical="liquid_chlorine",
        amount=round(gallons_needed, 2),
        unit="gallons",
        current_value=current_fc,
        target_value=target_fc,
        delta=round(delta, 2),
        pool_volume_gallons=pool_volume_gallons,
        calculation_shown=calc_shown,
        notes=(
            f"{chlorine_strength_pct}% liquid chlorine is the correct choice during "
            f"SLAM - no CYA or calcium side effects. Residual salt increase of "
            f"~{round(delta * 1.65, 1)} ppm is negligible for a non-SWG pool."
        ),
    )


# -----------------------------------------------------------------------------
# 2b. CAL-HYPO GRANULAR SHOCK  (routine maintenance)
#
# Cal-Hypo (calcium hypochlorite) is ~65-73% available chlorine by weight.
# Side effect: each dose raises Calcium Hardness.
#
# DERIVATION:
# Pure chlorine needed (lbs) = delta_ppm * volume_gal * 8.345e-6
#   (8.345e-6 = lbs per gallon of water / 1,000,000 ppm denominator)
# Product needed (lbs) = pure_chlorine_lbs / (strength_pct / 100)
# CH side effect: ~0.70 ppm CH rise per 1 ppm FC added (TFP/PoolMath)
# -----------------------------------------------------------------------------

CAL_HYPO_CH_PPM_PER_FC_PPM = 0.70   # calcium hardness added per ppm FC gained
WATER_LBS_PER_GALLON = 8.345         # weight of one US gallon of water


def dose_cal_hypo_lbs(
    current_fc: float,
    target_fc: float,
    pool_volume_gallons: int,
    cal_hypo_strength_pct: float = 65.0,
) -> DoseResult:
    """
    Calculate pounds of Cal-Hypo granular shock needed to raise FC.
    Used for routine maintenance shocking; not for SLAM.

    Always flags the CH side effect in the result so the dashboard can
    track cumulative calcium hardness contribution from shock usage.
    """
    if current_fc is None or target_fc is None:
        raise ValueError("current_fc and target_fc are required")
    if pool_volume_gallons <= 0:
        raise ValueError("pool_volume_gallons must be positive")
    if not (60 <= cal_hypo_strength_pct <= 75):
        raise ValueError("Cal-Hypo strength should be between 60-75%; check product label")

    delta = target_fc - current_fc

    if delta <= 0:
        return DoseResult(
            chemical="cal_hypo",
            amount=0.0,
            unit="lbs",
            current_value=current_fc,
            target_value=target_fc,
            delta=delta,
            pool_volume_gallons=pool_volume_gallons,
            calculation_shown="Current FC already at or above target - no dose needed",
            notes="No Cal-Hypo addition recommended.",
        )

    pure_chlorine_lbs = delta * pool_volume_gallons * WATER_LBS_PER_GALLON / 1_000_000
    product_lbs = pure_chlorine_lbs / (cal_hypo_strength_pct / 100)
    ch_side_effect = round(delta * CAL_HYPO_CH_PPM_PER_FC_PPM, 2)

    calc_shown = (
        f"Pure Cl needed: {delta} ppm x {pool_volume_gallons:,} gal x "
        f"{WATER_LBS_PER_GALLON} lb/gal / 1,000,000 = {round(pure_chlorine_lbs, 4)} lbs\n"
        f"Product needed: {round(pure_chlorine_lbs, 4)} lbs / {cal_hypo_strength_pct}% = "
        f"{round(product_lbs, 2)} lbs Cal-Hypo"
    )

    return DoseResult(
        chemical="cal_hypo",
        amount=round(product_lbs, 2),
        unit="lbs",
        current_value=current_fc,
        target_value=target_fc,
        delta=round(delta, 2),
        pool_volume_gallons=pool_volume_gallons,
        calculation_shown=calc_shown,
        notes=(
            f"Cal-Hypo ({cal_hypo_strength_pct}%) raises Calcium Hardness as a side "
            f"effect. This dose will add approximately {ch_side_effect} ppm CH. "
            f"Pre-dissolve in a bucket of water before adding to pool. "
            f"Do not use Cal-Hypo during SLAM - use liquid chlorine instead."
        ),
        side_effect_ppm=ch_side_effect,
        side_effect_parameter="calcium_hardness",
    )


# -----------------------------------------------------------------------------
# 2c. TRICHLOR TABLETS  (floater, routine maintenance)
#
# Trichlor (trichloroisocyanuric acid) tablets are ~90% available chlorine.
# Side effects per tablet (TFP/PoolMath):
#   - Raises CYA by ~6 ppm per tablet per 10,000 gallons
#   - Lowers pH slightly (acidic)
#
# Unlike liquid chlorine and Cal-Hypo, trichlor tablets aren't dosed to
# hit a specific FC target in one shot - they're a slow continuous release
# over days in a floater. The dosing function here answers a different
# question: "how many tablets should I put in the floater, and what CYA
# side effect should I expect over the next N days?"
# -----------------------------------------------------------------------------

TRICHLOR_AVAILABLE_CHLORINE_PCT = 90.0
TRICHLOR_CYA_PPM_PER_TABLET_PER_10K_GAL = 6.0  # CYA added per tablet per 10,000 gal
TRICHLOR_TABLET_WEIGHT_LBS = 0.5                  # standard 3" tablet ~0.5 lb each
TRICHLOR_TABLET_FC_PER_10K_GAL = (
    TRICHLOR_TABLET_WEIGHT_LBS * TRICHLOR_AVAILABLE_CHLORINE_PCT / 100 * 453.6 / 37.85
    # (0.5 lb * 0.90 available * 453.6 g/lb) / 37.85 L per 10k gal in mg/L = ppm
)


def estimate_trichlor_cya_contribution(
    num_tablets: int,
    pool_volume_gallons: int,
) -> float:
    """
    Estimate how much CYA a given number of trichlor tablets will add to
    the pool. Used to warn when seasonal trichlor use is pushing CYA toward
    the upper band (60 ppm).

    Returns CYA added in ppm.
    """
    if num_tablets < 0:
        raise ValueError("num_tablets cannot be negative")
    if pool_volume_gallons <= 0:
        raise ValueError("pool_volume_gallons must be positive")

    cya_added = num_tablets * TRICHLOR_CYA_PPM_PER_TABLET_PER_10K_GAL * (10000 / pool_volume_gallons)
    return round(cya_added, 2)


@dataclass
class TrichlorTabletResult:
    """
    Result of a trichlor floater assessment: how many tablets to use and
    what the cumulative CYA contribution will be.
    """
    recommended_tablets: int
    estimated_fc_contribution_per_day: float
    cya_added_per_tablet: float
    current_cya: float
    projected_cya_after_tablets: float
    cya_warning: Optional[str]
    notes: str


def assess_trichlor_floater(
    current_fc: float,
    target_fc: float,
    current_cya: float,
    pool_volume_gallons: int,
    tablets_currently_in_floater: int = 0,
    days_until_next_check: int = 3,
) -> TrichlorTabletResult:
    """
    Assess the trichlor floater situation: recommend how many tablets to
    load, and flag CYA creep risk.

    Trichlor tablets dissolve slowly - a single 3" tablet in a floater
    typically releases FC over 3-7 days depending on flow, temperature,
    and floater opening. This function works in terms of "tablets in floater"
    rather than an instantaneous dose.

    CYA creep is the primary long-term risk with trichlor: 7-8 tablets over
    a season in a 12,350-gallon pool can add ~10+ ppm CYA, which compounds
    across seasons if water isn't partially replaced.
    """
    if pool_volume_gallons <= 0:
        raise ValueError("pool_volume_gallons must be positive")

    cya_per_tablet = estimate_trichlor_cya_contribution(1, pool_volume_gallons)
    projected_cya = round(current_cya + (tablets_currently_in_floater * cya_per_tablet), 2)

    # Simple floater recommendation: 1-2 tablets for pools up to 15k gal,
    # scaled up for larger pools. This is a starting suggestion - actual
    # consumption depends on floater opening, water temp, and turnover rate.
    recommended = max(1, round(pool_volume_gallons / 10000))

    # Estimate daily FC contribution: one full tablet dissolves over ~5 days
    # on average, releasing its FC content gradually.
    fc_per_tablet_total = round(TRICHLOR_TABLET_FC_PER_10K_GAL * (10000 / pool_volume_gallons), 2)
    fc_per_tablet_per_day = round(fc_per_tablet_total / 5, 2)
    estimated_daily_fc = round(fc_per_tablet_per_day * recommended, 2)

    cya_warning = None
    if projected_cya >= CYA_RECOMMENDED_MAX:
        cya_warning = (
            f"CYA is already at {current_cya} ppm - at or above the recommended "
            f"maximum of {CYA_RECOMMENDED_MAX} ppm for a liquid-chlorine pool. "
            f"Continued trichlor use will push CYA higher, reducing chlorine "
            f"effectiveness. Consider switching to liquid chlorine for top-ups "
            f"until CYA drops (via backwash dilution or partial drain/refill)."
        )
    elif projected_cya >= CYA_CREEP_WARNING_THRESHOLD:
        cya_warning = (
            f"CYA is at {current_cya} ppm and projected to reach {projected_cya} ppm "
            f"after current tablets dissolve. Approaching the recommended maximum of "
            f"{CYA_RECOMMENDED_MAX} ppm. Monitor CYA closely this season."
        )

    return TrichlorTabletResult(
        recommended_tablets=recommended,
        estimated_fc_contribution_per_day=estimated_daily_fc,
        cya_added_per_tablet=cya_per_tablet,
        current_cya=current_cya,
        projected_cya_after_tablets=projected_cya,
        cya_warning=cya_warning,
        notes=(
            f"Each trichlor tablet adds ~{cya_per_tablet} ppm CYA to this pool "
            f"({pool_volume_gallons:,} gal) as it dissolves. Trichlor also lowers pH "
            f"slightly - check pH weekly. During SLAM or any recovery event, remove "
            f"tablets from floater and switch to liquid chlorine exclusively."
        ),
    )


# -----------------------------------------------------------------------------
# 2d. OTHER CHEMICALS  (stabilizer, muriatic acid, calcium, baking soda)
# -----------------------------------------------------------------------------

STABILIZER_LBS_PER_10K_GAL_PER_PPM = 0.0375


def dose_stabilizer_lbs(
    current_cya: float,
    target_cya: float,
    pool_volume_gallons: int,
) -> DoseResult:
    """
    Calculate pounds of granular stabilizer (CYA) needed.

    Stabilizer dissolves slowly (days, not hours). Log the application
    method (direct/skimmer/sock/split) - each method has a different
    expected_stable_date. See schema: chemical_additions.expected_stable_date.
    """
    if current_cya is None or target_cya is None:
        raise ValueError("current_cya and target_cya are required")
    if pool_volume_gallons <= 0:
        raise ValueError("pool_volume_gallons must be positive")

    delta = target_cya - current_cya

    if delta <= 0:
        return DoseResult(
            chemical="stabilizer",
            amount=0.0,
            unit="lbs",
            current_value=current_cya,
            target_value=target_cya,
            delta=delta,
            pool_volume_gallons=pool_volume_gallons,
            calculation_shown="Current CYA already at or above target - no dose needed",
            notes="No stabilizer addition recommended.",
        )

    lbs_needed = delta * (pool_volume_gallons / 10000) * STABILIZER_LBS_PER_10K_GAL_PER_PPM

    calc_shown = (
        f"({target_cya} - {current_cya} ppm) x ({pool_volume_gallons:,} gal / 10,000) "
        f"x {STABILIZER_LBS_PER_10K_GAL_PER_PPM} lbs/ppm = {round(lbs_needed, 2)} lbs"
    )

    return DoseResult(
        chemical="stabilizer",
        amount=round(lbs_needed, 2),
        unit="lbs",
        current_value=current_cya,
        target_value=target_cya,
        delta=round(delta, 2),
        pool_volume_gallons=pool_volume_gallons,
        calculation_shown=calc_shown,
        notes=(
            "Stabilizer dissolves slowly (days, not hours). Log the application "
            "method (direct/skimmer/sock/split) - CYA retests are unreliable "
            "until fully dissolved (typically 4-7 days). Do not backwash until "
            "dissolution is complete or you'll lose the stabilizer you just added."
        ),
    )


MURIATIC_ACID_FLOZ_PER_10K_GAL_PER_01_PH = 12.8


def dose_muriatic_acid_floz(
    current_ph: float,
    target_ph: float,
    pool_volume_gallons: int,
) -> DoseResult:
    """
    Estimate fluid ounces of muriatic acid (31.45%) to lower pH.

    CAVEAT: pH adjustment is the least precise dosing calculation because
    actual effect depends heavily on Total Alkalinity. Always add half,
    wait 30-60 minutes, retest before adding the rest.
    """
    if current_ph is None or target_ph is None:
        raise ValueError("current_ph and target_ph are required")
    if pool_volume_gallons <= 0:
        raise ValueError("pool_volume_gallons must be positive")

    delta = current_ph - target_ph  # acid lowers pH

    if delta <= 0:
        return DoseResult(
            chemical="muriatic_acid",
            amount=0.0,
            unit="fl_oz",
            current_value=current_ph,
            target_value=target_ph,
            delta=delta,
            pool_volume_gallons=pool_volume_gallons,
            calculation_shown="Current pH already at or below target - no acid needed",
            notes="No muriatic acid addition recommended.",
        )

    floz_needed = (delta / 0.1) * (pool_volume_gallons / 10000) * MURIATIC_ACID_FLOZ_PER_10K_GAL_PER_01_PH

    calc_shown = (
        f"({current_ph} - {target_ph} pH) x ({pool_volume_gallons:,} gal / 10,000) "
        f"x {MURIATIC_ACID_FLOZ_PER_10K_GAL_PER_01_PH} fl oz per 0.1 pH = {round(floz_needed, 1)} fl oz"
    )

    return DoseResult(
        chemical="muriatic_acid",
        amount=round(floz_needed, 1),
        unit="fl_oz",
        current_value=current_ph,
        target_value=target_ph,
        delta=round(delta, 2),
        pool_volume_gallons=pool_volume_gallons,
        calculation_shown=calc_shown,
        notes=(
            "ESTIMATE ONLY: actual acid demand depends heavily on Total Alkalinity "
            "(higher TA requires more acid for the same pH drop). Add half this "
            "amount first, wait 30-60 minutes with pump running, then retest."
        ),
    )


CALCIUM_LBS_PER_10K_GAL_PER_10PPM = 1.25


def dose_calcium_lbs(
    current_ch: float,
    target_ch: float,
    pool_volume_gallons: int,
) -> DoseResult:
    """Calculate pounds of calcium chloride needed to raise Calcium Hardness."""
    if current_ch is None or target_ch is None:
        raise ValueError("current_ch and target_ch are required")
    if pool_volume_gallons <= 0:
        raise ValueError("pool_volume_gallons must be positive")

    delta = target_ch - current_ch

    if delta <= 0:
        return DoseResult(
            chemical="calcium_chloride",
            amount=0.0,
            unit="lbs",
            current_value=current_ch,
            target_value=target_ch,
            delta=delta,
            pool_volume_gallons=pool_volume_gallons,
            calculation_shown="Current CH already at or above target - no dose needed",
            notes="No calcium addition recommended.",
        )

    lbs_needed = (delta / 10) * (pool_volume_gallons / 10000) * CALCIUM_LBS_PER_10K_GAL_PER_10PPM

    calc_shown = (
        f"({target_ch} - {current_ch} ppm) / 10 x ({pool_volume_gallons:,} gal / 10,000) "
        f"x {CALCIUM_LBS_PER_10K_GAL_PER_10PPM} lbs per 10ppm = {round(lbs_needed, 2)} lbs"
    )

    return DoseResult(
        chemical="calcium_chloride",
        amount=round(lbs_needed, 2),
        unit="lbs",
        current_value=current_ch,
        target_value=target_ch,
        delta=round(delta, 2),
        pool_volume_gallons=pool_volume_gallons,
        calculation_shown=calc_shown,
        notes="Add slowly and brush to help dissolve; calcium chloride generates heat as it dissolves.",
    )


BAKING_SODA_LBS_PER_10K_GAL_PER_10PPM = 1.5


def dose_baking_soda_lbs(
    current_ta: float,
    target_ta: float,
    pool_volume_gallons: int,
) -> DoseResult:
    """Calculate pounds of baking soda (sodium bicarbonate) needed to raise TA."""
    if current_ta is None or target_ta is None:
        raise ValueError("current_ta and target_ta are required")
    if pool_volume_gallons <= 0:
        raise ValueError("pool_volume_gallons must be positive")

    delta = target_ta - current_ta

    if delta <= 0:
        return DoseResult(
            chemical="baking_soda",
            amount=0.0,
            unit="lbs",
            current_value=current_ta,
            target_value=target_ta,
            delta=delta,
            pool_volume_gallons=pool_volume_gallons,
            calculation_shown="Current TA already at or above target - no dose needed",
            notes="No baking soda addition recommended.",
        )

    lbs_needed = (delta / 10) * (pool_volume_gallons / 10000) * BAKING_SODA_LBS_PER_10K_GAL_PER_10PPM

    calc_shown = (
        f"({target_ta} - {current_ta} ppm) / 10 x ({pool_volume_gallons:,} gal / 10,000) "
        f"x {BAKING_SODA_LBS_PER_10K_GAL_PER_10PPM} lbs per 10ppm = {round(lbs_needed, 2)} lbs"
    )

    return DoseResult(
        chemical="baking_soda",
        amount=round(lbs_needed, 2),
        unit="lbs",
        current_value=current_ta,
        target_value=target_ta,
        delta=round(delta, 2),
        pool_volume_gallons=pool_volume_gallons,
        calculation_shown=calc_shown,
        notes="Baking soda raises TA with minimal pH impact, making it the preferred TA-only adjustment.",
    )


# =============================================================================
# 3. SLAM / RECOVERY LOGIC
# =============================================================================

@dataclass
class SlamStatus:
    """
    Three-part SLAM completion evaluation. All three conditions must be true
    simultaneously for SLAM to be considered complete - matching both TFP
    guidance and what was verified during the real June 2026 recovery.
    """
    fc_meets_slam_level: bool
    oclt_passed: Optional[bool]    # None if no OCLT has been run yet
    cc_acceptable: Optional[bool]  # None if no CC reading available
    water_clear: Optional[bool]    # None if not yet assessed (user-reported)
    is_complete: bool
    summary: str


def evaluate_slam_status(
    current_fc: float,
    cya: float,
    overnight_fc_drop: Optional[float] = None,
    combined_chlorine: Optional[float] = None,
    can_see_bottom: Optional[bool] = None,
) -> SlamStatus:
    """
    Evaluate whether SLAM/recovery criteria are met.

    SLAM completion requires ALL THREE of:
      1. OCLT drop <= 1.0 ppm
      2. Combined Chlorine <= 0.5 ppm
      3. Water clarity (can see the bottom)

    Any criterion not yet tested is None (unknown), never assumed passing.
    """
    targets = calculate_fc_targets(cya)
    fc_meets_slam_level = current_fc >= targets.slam_fc

    oclt_passed = None
    if overnight_fc_drop is not None:
        oclt_passed = overnight_fc_drop <= OCLT_MAX_DROP_PPM

    cc_acceptable = None
    if combined_chlorine is not None:
        cc_acceptable = combined_chlorine <= CC_MAX_FOR_SLAM_COMPLETE

    water_clear = can_see_bottom

    all_known_and_passed = (
        oclt_passed is True
        and cc_acceptable is True
        and water_clear is True
    )

    if all_known_and_passed:
        summary = (
            "SLAM complete: OCLT drop, combined chlorine, and water clarity "
            "all meet criteria. Safe to return to Maintenance Mode."
        )
    else:
        missing_or_failed = []
        if oclt_passed is not True:
            missing_or_failed.append(
                "OCLT not yet passed" if oclt_passed is False else "OCLT not yet tested"
            )
        if cc_acceptable is not True:
            missing_or_failed.append(
                "CC too high" if cc_acceptable is False else "CC not yet tested"
            )
        if water_clear is not True:
            missing_or_failed.append(
                "water not yet clear" if water_clear is False else "clarity not yet assessed"
            )
        summary = "Continue SLAM - " + ", ".join(missing_or_failed) + "."

    return SlamStatus(
        fc_meets_slam_level=fc_meets_slam_level,
        oclt_passed=oclt_passed,
        cc_acceptable=cc_acceptable,
        water_clear=water_clear,
        is_complete=all_known_and_passed,
        summary=summary,
    )


# =============================================================================
# 4. SIDE-EFFECT TRACKING
# =============================================================================

@dataclass
class SeasonalSideEffects:
    """
    Cumulative side-effect estimates for a season's chemical usage.
    Used by the Smart Assistant to explain rising CH or CYA trends
    without needing chemistry knowledge from the user.
    """
    total_cya_added_from_trichlor: float     # ppm
    total_ch_added_from_cal_hypo: float      # ppm
    trichlor_tablet_count: int
    cal_hypo_shock_lbs: float
    cya_warning: Optional[str]
    ch_warning: Optional[str]


def estimate_seasonal_side_effects(
    trichlor_tablets_used: int,
    cal_hypo_lbs_used: float,
    cal_hypo_strength_pct: float,
    pool_volume_gallons: int,
    current_cya: float,
    current_ch: float,
) -> SeasonalSideEffects:
    """
    Given a season's worth of chemical usage, estimate cumulative side
    effects and generate warnings if parameters are approaching limits.

    This is what the Smart Assistant uses to say things like:
    "Your CYA has risen 8 ppm this season from trichlor tablet use.
    At this rate it will exceed 60 ppm before end of season."
    """
    if pool_volume_gallons <= 0:
        raise ValueError("pool_volume_gallons must be positive")

    cya_from_trichlor = estimate_trichlor_cya_contribution(trichlor_tablets_used, pool_volume_gallons)

    # CH from Cal-Hypo: FC added = lbs * strength_pct/100 / (pool_gal * 8.345e-6)
    fc_from_cal_hypo = (cal_hypo_lbs_used * (cal_hypo_strength_pct / 100)) / (pool_volume_gallons * WATER_LBS_PER_GALLON / 1_000_000)
    ch_from_cal_hypo = round(fc_from_cal_hypo * CAL_HYPO_CH_PPM_PER_FC_PPM, 2)

    cya_warning = None
    projected_cya = current_cya  # current already reflects what's been added
    if projected_cya >= CYA_RECOMMENDED_MAX:
        cya_warning = (
            f"CYA is at {current_cya} ppm, at or above the recommended maximum "
            f"of {CYA_RECOMMENDED_MAX} ppm. Trichlor tablets have contributed "
            f"approximately {cya_from_trichlor} ppm this season. Switch to liquid "
            f"chlorine for top-ups. Partial drain/refill will lower CYA if needed."
        )
    elif projected_cya >= CYA_CREEP_WARNING_THRESHOLD:
        cya_warning = (
            f"CYA is at {current_cya} ppm, approaching the recommended maximum of "
            f"{CYA_RECOMMENDED_MAX} ppm. Trichlor tablet use has contributed "
            f"approximately {cya_from_trichlor} ppm this season. Monitor closely."
        )

    ch_warning = None
    if current_ch > 350:
        ch_warning = (
            f"Calcium Hardness is at {current_ch} ppm, above the recommended "
            f"maximum of ~350 ppm. Cal-Hypo shock use has added approximately "
            f"{ch_from_cal_hypo} ppm CH this season. Avoid further Cal-Hypo "
            f"additions; switch to liquid chlorine for shocking if needed."
        )
    elif current_ch > 300:
        ch_warning = (
            f"Calcium Hardness is at {current_ch} ppm, trending high. Cal-Hypo "
            f"shock use has added approximately {ch_from_cal_hypo} ppm CH this "
            f"season. Continue to monitor."
        )

    return SeasonalSideEffects(
        total_cya_added_from_trichlor=cya_from_trichlor,
        total_ch_added_from_cal_hypo=ch_from_cal_hypo,
        trichlor_tablet_count=trichlor_tablets_used,
        cal_hypo_shock_lbs=cal_hypo_lbs_used,
        cya_warning=cya_warning,
        ch_warning=ch_warning,
    )


# =============================================================================
# 5. RELIABILITY / GUARDRAILS
# =============================================================================

BLEACHOUT_SUSPECT_FC_THRESHOLD = 1.0          # reading at or below this...
BLEACHOUT_SUSPECT_PRIOR_FC_THRESHOLD = 10.0   # ...shortly after FC was at or above this


def should_flag_suspect_bleachout(
    current_reading_fc: float,
    most_recent_prior_fc: Optional[float],
    test_method: str = "direct",
) -> tuple[bool, Optional[str]]:
    """
    Returns (should_flag, reason) if a reading looks like a DPD bleach-out
    artifact. Does not block saving - only triggers a UI nudge to retest
    with a diluted sample.
    """
    if test_method == "dilution":
        return (False, None)  # already a corrected retest, don't re-flag

    if most_recent_prior_fc is None:
        return (False, None)

    if (
        current_reading_fc <= BLEACHOUT_SUSPECT_FC_THRESHOLD
        and most_recent_prior_fc >= BLEACHOUT_SUSPECT_PRIOR_FC_THRESHOLD
    ):
        reason = (
            f"FC tested at {current_reading_fc} ppm shortly after a reading of "
            f"{most_recent_prior_fc} ppm. At high FC, the DPD reagent can bleach "
            f"out instantly and produce a false near-zero result. Consider a "
            f"dilution retest (e.g. 5ml pool water + 5ml tap water, multiply "
            f"result by 2) before trusting this reading."
        )
        return (True, reason)

    return (False, None)


def apply_dilution_factor(raw_test_result: float, dilution_factor: float) -> float:
    """
    Apply a dilution factor to a raw test result.
    e.g. a 50/50 dilution (factor 2.0) that read 10 ppm = 20 ppm true FC.
    """
    if dilution_factor is None or dilution_factor <= 0:
        raise ValueError("dilution_factor must be a positive number")
    return round(raw_test_result * dilution_factor, 2)
