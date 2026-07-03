"""
Test suite for PoolMon chemistry engine.
Run with: python3 test_chemistry.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from chemistry import (
    calculate_fc_targets, classify_fc_status, FCStatus,
    dose_liquid_chlorine_gallons, dose_stabilizer_lbs,
    dose_muriatic_acid_floz, dose_calcium_lbs, dose_baking_soda_lbs,
    dose_cal_hypo_lbs, assess_trichlor_floater, estimate_seasonal_side_effects,
    evaluate_slam_status,
    should_flag_suspect_bleachout, apply_dilution_factor,
    ZERO_CYA_FC_CAP,
)

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  OK   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}")


# =============================================================================
print("=" * 70)
print("1. FC/CYA TARGET MATH")
print("=" * 70)

t = calculate_fc_targets(40)
check("CYA=40 minimum FC = 3.0", t.minimum_fc == 3.0)
check("CYA=40 target FC = 4.6", t.target_fc == 4.6)
check("CYA=40 yellow/mustard min FC = 6.0", t.yellow_mustard_minimum_fc == 6.0)
check("CYA=40 SLAM FC = 16.0", t.slam_fc == 16.0)
check("CYA=40 is in recommended band (30-60)", t.cya_in_recommended_band is True)
check("CYA=40 zero-guardrail not active", t.is_zero_cya_guardrail_active is False)

t0 = calculate_fc_targets(0)
check("CYA=0 target FC capped at 5.0", t0.target_fc == ZERO_CYA_FC_CAP)
check("CYA=0 SLAM FC capped at 5.0", t0.slam_fc == ZERO_CYA_FC_CAP)
check("CYA=0 zero-guardrail IS active", t0.is_zero_cya_guardrail_active is True)
check("CYA=0 not in recommended band", t0.cya_in_recommended_band is False)
check("CYA=20 NOT in recommended band (below 30)", calculate_fc_targets(20).cya_in_recommended_band is False)
check("CYA=80 NOT in recommended band (above 60)", calculate_fc_targets(80).cya_in_recommended_band is False)

try:
    calculate_fc_targets(-5)
    check("negative CYA raises ValueError", False)
except ValueError:
    check("negative CYA raises ValueError", True)

print()
print("FC status classification (CYA=40: min=3.0, target=4.6, slam=16.0)")
t40 = calculate_fc_targets(40)
check("FC=1.0 -> BELOW_MINIMUM", classify_fc_status(1.0, t40) == FCStatus.BELOW_MINIMUM)
check("FC=3.5 -> BELOW_TARGET", classify_fc_status(3.5, t40) == FCStatus.BELOW_TARGET)
check("FC=4.6 -> AT_TARGET", classify_fc_status(4.6, t40) == FCStatus.AT_TARGET)
check("FC=4.9 (within 10% band) -> AT_TARGET", classify_fc_status(4.9, t40) == FCStatus.AT_TARGET)
check("FC=7.0 -> ABOVE_TARGET", classify_fc_status(7.0, t40) == FCStatus.ABOVE_TARGET)
check("FC=20.0 -> AT_OR_ABOVE_SLAM", classify_fc_status(20.0, t40) == FCStatus.AT_OR_ABOVE_SLAM)


# =============================================================================
print()
print("=" * 70)
print("2a. LIQUID CHLORINE DOSING (SLAM/recovery)")
print("=" * 70)

r = dose_liquid_chlorine_gallons(current_fc=0, target_fc=12.5, pool_volume_gallons=10000, chlorine_strength_pct=12.5)
check("1 gal of 12.5% in 10,000 gal raises FC by 12.5 ppm -> dose = 1.0 gal exactly", r.amount == 1.0)

r2 = dose_liquid_chlorine_gallons(current_fc=3.5, target_fc=8.0, pool_volume_gallons=12350, chlorine_strength_pct=12.5)
expected = round((8.0 - 3.5) * (12350 / 10000) / 12.5, 2)
check(f"Dan's pool (12,350 gal) FC 3.5->8.0 = {expected} gal", r2.amount == expected)
check("Calculation shown includes pool volume", "12,350" in r2.calculation_shown)

r3 = dose_liquid_chlorine_gallons(current_fc=10, target_fc=8, pool_volume_gallons=12350)
check("No dose when FC already exceeds target", r3.amount == 0.0)

slam_t = calculate_fc_targets(40)
r4 = dose_liquid_chlorine_gallons(current_fc=20.0, target_fc=slam_t.slam_fc, pool_volume_gallons=12350)
check("Recovery: FC=20 already above SLAM target (16.0) -> no dose", r4.amount == 0.0)

try:
    dose_liquid_chlorine_gallons(current_fc=3, target_fc=8, pool_volume_gallons=0)
    check("Zero pool volume raises ValueError", False)
except ValueError:
    check("Zero pool volume raises ValueError", True)


# =============================================================================
print()
print("=" * 70)
print("2b. CAL-HYPO DOSING (routine maintenance shock)")
print("=" * 70)

cal = dose_cal_hypo_lbs(current_fc=3.0, target_fc=8.0, pool_volume_gallons=12350, cal_hypo_strength_pct=65.0)
check("Cal-Hypo dose is positive for FC 3->8", cal.amount > 0)
check("Cal-Hypo result has side_effect_ppm populated", cal.side_effect_ppm is not None)
check("Cal-Hypo side_effect_parameter is calcium_hardness", cal.side_effect_parameter == "calcium_hardness")
check("Cal-Hypo CH side effect ~3.5 ppm (5 ppm FC * 0.70)", abs(cal.side_effect_ppm - 3.5) < 0.1)
check("Cal-Hypo notes warn against use during SLAM", "SLAM" in cal.notes)
check("Cal-Hypo calculation_shown includes pool volume", "12,350" in cal.calculation_shown)

cal_none = dose_cal_hypo_lbs(current_fc=10, target_fc=8, pool_volume_gallons=12350)
check("No Cal-Hypo dose when FC already above target", cal_none.amount == 0.0)

try:
    dose_cal_hypo_lbs(current_fc=3, target_fc=8, pool_volume_gallons=12350, cal_hypo_strength_pct=99.0)
    check("Out-of-range Cal-Hypo strength raises ValueError", False)
except ValueError:
    check("Out-of-range Cal-Hypo strength raises ValueError", True)


# =============================================================================
print()
print("=" * 70)
print("2c. TRICHLOR TABLET FLOATER ASSESSMENT")
print("=" * 70)

floater_ok = assess_trichlor_floater(
    current_fc=3.0, target_fc=4.6, current_cya=40,
    pool_volume_gallons=12350, tablets_currently_in_floater=2
)
check("Trichlor assessment returns recommended_tablets >= 1", floater_ok.recommended_tablets >= 1)
check("CYA per tablet is positive", floater_ok.cya_added_per_tablet > 0)
check("No CYA warning when CYA=40 (within band)", floater_ok.cya_warning is None)
check("Notes warn to remove tablets during SLAM", "SLAM" in floater_ok.notes)

# Dan's pool: 6 ppm per tablet per 10k gal * (10000/12350) = ~4.86 ppm per tablet
cya_per_tab = floater_ok.cya_added_per_tablet
check(f"CYA per tablet in 12,350 gal = ~4.86 ppm (got {cya_per_tab})", abs(cya_per_tab - 4.86) < 0.1)

floater_warn = assess_trichlor_floater(
    current_fc=3.0, target_fc=4.6, current_cya=52,
    pool_volume_gallons=12350, tablets_currently_in_floater=2
)
check("CYA warning triggered when CYA approaching 60 ppm", floater_warn.cya_warning is not None)
check("Warning mentions recommended maximum of 60", "60" in floater_warn.cya_warning)

floater_critical = assess_trichlor_floater(
    current_fc=3.0, target_fc=4.6, current_cya=65,
    pool_volume_gallons=12350, tablets_currently_in_floater=1
)
check("Critical warning when CYA >= 60", floater_critical.cya_warning is not None)
check("Critical warning suggests switching to liquid chlorine", "liquid chlorine" in floater_critical.cya_warning)


# =============================================================================
print()
print("=" * 70)
print("2d. OTHER CHEMICALS")
print("=" * 70)

stab = dose_stabilizer_lbs(current_cya=0, target_cya=40, pool_volume_gallons=12350)
expected_stab = round(40 * (12350 / 10000) * 0.0375, 2)
check(f"Stabilizer CYA 0->40 in 12,350 gal = {expected_stab} lbs", stab.amount == expected_stab)
check("Stabilizer notes include dissolution caveat", "dissolve" in stab.notes.lower())
check("No stabilizer when already above target", dose_stabilizer_lbs(50, 40, 12350).amount == 0.0)

acid = dose_muriatic_acid_floz(current_ph=7.8, target_ph=7.5, pool_volume_gallons=12350)
check("Muriatic acid dose is positive for pH 7.8->7.5", acid.amount > 0)
check("Muriatic acid notes flag it as ESTIMATE", "ESTIMATE" in acid.notes)
check("No acid when pH already below target", dose_muriatic_acid_floz(7.2, 7.5, 12350).amount == 0.0)

calc = dose_calcium_lbs(current_ch=150, target_ch=250, pool_volume_gallons=12350)
expected_calc = round((100 / 10) * (12350 / 10000) * 1.25, 2)
check(f"Calcium CH 150->250 in 12,350 gal = {expected_calc} lbs", calc.amount == expected_calc)

soda = dose_baking_soda_lbs(current_ta=60, target_ta=90, pool_volume_gallons=12350)
expected_soda = round((30 / 10) * (12350 / 10000) * 1.5, 2)
check(f"Baking soda TA 60->90 in 12,350 gal = {expected_soda} lbs", soda.amount == expected_soda)


# =============================================================================
print()
print("=" * 70)
print("3. SLAM / RECOVERY LOGIC")
print("=" * 70)

slam_done = evaluate_slam_status(current_fc=18.0, cya=40, overnight_fc_drop=0.8, combined_chlorine=0.3, can_see_bottom=True)
check("SLAM complete: fc_meets_slam_level", slam_done.fc_meets_slam_level is True)
check("SLAM complete: oclt_passed", slam_done.oclt_passed is True)
check("SLAM complete: cc_acceptable", slam_done.cc_acceptable is True)
check("SLAM complete: water_clear", slam_done.water_clear is True)
check("SLAM complete: is_complete True", slam_done.is_complete is True)
check("SLAM complete: summary says complete", "complete" in slam_done.summary.lower())

slam_cont = evaluate_slam_status(current_fc=18.0, cya=40, overnight_fc_drop=2.5, combined_chlorine=1.2, can_see_bottom=False)
check("SLAM continuing: OCLT failed", slam_cont.oclt_passed is False)
check("SLAM continuing: CC too high", slam_cont.cc_acceptable is False)
check("SLAM continuing: water not clear", slam_cont.water_clear is False)
check("SLAM continuing: is_complete False", slam_cont.is_complete is False)
check("SLAM continuing: summary says continue", "continue" in slam_cont.summary.lower())

slam_part = evaluate_slam_status(current_fc=18.0, cya=40)
check("SLAM partial: oclt_passed is None (not False)", slam_part.oclt_passed is None)
check("SLAM partial: is_complete False when data missing", slam_part.is_complete is False)
check("SLAM partial: summary mentions not yet tested", "not yet tested" in slam_part.summary)


# =============================================================================
print()
print("=" * 70)
print("4. SEASONAL SIDE-EFFECT TRACKING")
print("=" * 70)

effects = estimate_seasonal_side_effects(
    trichlor_tablets_used=8, cal_hypo_lbs_used=3.0, cal_hypo_strength_pct=65.0,
    pool_volume_gallons=12350, current_cya=42, current_ch=220,
)
check("Seasonal trichlor CYA contribution is positive", effects.total_cya_added_from_trichlor > 0)
check("Seasonal Cal-Hypo CH contribution is positive", effects.total_ch_added_from_cal_hypo > 0)
check("No CYA warning when CYA=42", effects.cya_warning is None)
check("No CH warning when CH=220", effects.ch_warning is None)

effects_high_cya = estimate_seasonal_side_effects(
    trichlor_tablets_used=15, cal_hypo_lbs_used=2.0, cal_hypo_strength_pct=65.0,
    pool_volume_gallons=12350, current_cya=62, current_ch=200,
)
check("CYA warning fires when current_cya >= 60", effects_high_cya.cya_warning is not None)
check("CYA warning mentions trichlor/tablets", any(w in effects_high_cya.cya_warning.lower() for w in ["trichlor", "tablet"]))

effects_high_ch = estimate_seasonal_side_effects(
    trichlor_tablets_used=5, cal_hypo_lbs_used=10.0, cal_hypo_strength_pct=65.0,
    pool_volume_gallons=12350, current_cya=45, current_ch=360,
)
check("CH warning fires when current_ch > 350", effects_high_ch.ch_warning is not None)
check("CH warning mentions Cal-Hypo", "Cal-Hypo" in effects_high_ch.ch_warning)


# =============================================================================
print()
print("=" * 70)
print("5. RELIABILITY / GUARDRAILS (bleach-out detection)")
print("=" * 70)

flagged, reason = should_flag_suspect_bleachout(current_reading_fc=0.5, most_recent_prior_fc=20.0)
check("Real bleach-out scenario (20 ppm prior, 0.5 reading) IS flagged", flagged is True)
check("Bleach-out reason mentions dilution retest", "dilution" in reason.lower())

not_f, _ = should_flag_suspect_bleachout(current_reading_fc=0.5, most_recent_prior_fc=2.0)
check("Low reading with LOW prior FC is NOT flagged", not_f is False)

not_f2, _ = should_flag_suspect_bleachout(current_reading_fc=0.5, most_recent_prior_fc=None)
check("No prior reading -> NOT flagged", not_f2 is False)

not_f3, _ = should_flag_suspect_bleachout(current_reading_fc=0.5, most_recent_prior_fc=20.0, test_method="dilution")
check("Dilution test method is NEVER flagged (already corrected)", not_f3 is False)

check("Dilution factor: raw 10 x 2.0 = 20 ppm", apply_dilution_factor(10.0, 2.0) == 20.0)

try:
    apply_dilution_factor(10.0, 0)
    check("dilution_factor of 0 raises ValueError", False)
except ValueError:
    check("dilution_factor of 0 raises ValueError", True)


# =============================================================================
print()
print("=" * 70)
print(f"RESULTS: {passed} passed, {failed} failed")
print("=" * 70)

if failed > 0:
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
    sys.exit(0)
