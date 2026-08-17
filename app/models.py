"""
Pydantic models for PoolMon API request validation and response shaping.

These are the contracts between the frontend and backend. Every API endpoint
that accepts a body validates against one of these models. Every endpoint
that returns data uses one of these as a response model.

Kept in a single file at this project scale - if it grows unwieldy later,
split by domain (chemistry, maintenance, recovery, etc.)
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import date, datetime
from enum import Enum


# =============================================================================
# ENUMS (mirror the allowed values in schema_v4.sql)
# =============================================================================

class TestMethod(str, Enum):
    direct = "direct"
    dilution = "dilution"
    test_strip = "test_strip"
    pool_store = "pool_store"

class WeatherCondition(str, Enum):
    sunny = "sunny"
    partly_cloudy = "partly_cloudy"
    overcast = "overcast"
    rain = "rain"
    storm = "storm"

class WindCondition(str, Enum):
    calm = "calm"
    light = "light"
    moderate = "moderate"
    strong = "strong"

class DebrisLevel(str, Enum):
    light = "light"
    moderate = "moderate"
    heavy = "heavy"

class RecoveryPeriod(str, Enum):
    morning = "morning"
    evening = "evening"
    overnight_test = "overnight_test"

class PoolMode(str, Enum):
    maintenance = "maintenance"
    recovery = "recovery"

class OperationalStatus(str, Enum):
    swimming_ready = "swimming_ready"
    routine_maintenance = "routine_maintenance"
    water_polishing = "water_polishing"
    investigation_required = "investigation_required"
    recovery_mode = "recovery_mode"
    winterized = "winterized"

class ApplicationMethod(str, Enum):
    direct = "direct"
    skimmer = "skimmer"
    sock = "sock"
    split = "split"
    floater = "floater"

class TriggerReason(str, Enum):
    algae_green = "algae_green"
    algae_mustard = "algae_mustard"
    cloudy_water = "cloudy_water"
    other = "other"

class ChemicalType(str, Enum):
    liquid_chlorine = "liquid_chlorine"
    cal_hypo = "cal_hypo"
    trichlor_tablet = "trichlor_tablet"
    stabilizer = "stabilizer"
    muriatic_acid = "muriatic_acid"
    calcium_chloride = "calcium_chloride"
    baking_soda = "baking_soda"
    alkalinity_increaser = "alkalinity_increaser"
    algaecide = "algaecide"
    other = "other"


# =============================================================================
# CHEMISTRY READINGS
# =============================================================================

class ChemistryReadingCreate(BaseModel):
    season_id: int
    reading_date: str                           # 'YYYY-MM-DD'
    reading_time: Optional[str] = None          # 'HH:MM'
    free_chlorine: Optional[float] = Field(None, ge=0, le=100)
    combined_chlorine: Optional[float] = Field(None, ge=0, le=20)
    ph: Optional[float] = Field(None, ge=6.0, le=9.0)
    total_alkalinity: Optional[float] = Field(None, ge=0, le=400)
    calcium_hardness: Optional[float] = Field(None, ge=0, le=1000)
    cyanuric_acid: Optional[float] = Field(None, ge=0, le=300)
    water_temp_f: Optional[float] = Field(None, ge=32, le=120)
    filter_pressure_psi: Optional[float] = Field(None, ge=0, le=60)
    weather: Optional[WeatherCondition] = None
    air_temp_f: Optional[float] = None
    notes: Optional[str] = None
    is_recovery_entry: bool = False
    recovery_period: Optional[RecoveryPeriod] = None
    recovery_session_id: Optional[int] = None
    test_method: TestMethod = TestMethod.direct
    dilution_factor: Optional[float] = Field(None, gt=1.0, le=10.0)
    is_suspect_reading: bool = False
    suspect_reason: Optional[str] = None

    @validator('dilution_factor', always=True)
    def dilution_factor_requires_dilution_method(cls, v, values):
        if v is not None and values.get('test_method') != TestMethod.dilution:
            raise ValueError('dilution_factor should only be set when test_method is dilution')
        return v


class ChemistryReadingResponse(BaseModel):
    id: int
    season_id: int
    reading_date: str
    reading_time: Optional[str]
    free_chlorine: Optional[float]
    combined_chlorine: Optional[float]
    ph: Optional[float]
    total_alkalinity: Optional[float]
    calcium_hardness: Optional[float]
    cyanuric_acid: Optional[float]
    water_temp_f: Optional[float]
    filter_pressure_psi: Optional[float]
    weather: Optional[str]
    air_temp_f: Optional[float]
    notes: Optional[str]
    is_recovery_entry: bool
    recovery_period: Optional[str]
    recovery_session_id: Optional[int]
    test_method: str
    dilution_factor: Optional[float]
    is_suspect_reading: bool
    suspect_reason: Optional[str]
    created_at: str


# =============================================================================
# DAILY CONDITIONS
# =============================================================================

class DailyConditionsCreate(BaseModel):
    season_id: int
    condition_date: str
    reading_id: Optional[int] = None
    air_temp_f: Optional[float] = None
    water_temp_f: Optional[float] = None
    sky_condition: Optional[WeatherCondition] = None
    rainfall_inches: Optional[float] = Field(None, ge=0)
    wind_condition: Optional[WindCondition] = None
    swimmer_count: Optional[int] = Field(None, ge=0)
    swim_duration_minutes: Optional[int] = Field(None, ge=0)
    cover_installed_overnight: Optional[bool] = None
    cover_removed_during_day: Optional[bool] = None
    debris_level: Optional[DebrisLevel] = None
    debris_notes: Optional[str] = None
    walls_brushed: bool = False
    floor_brushed: bool = False
    robot_cleaner_run: bool = False
    vacuumed_manually: bool = False
    skimmer_emptied: bool = False
    pump_basket_cleaned: bool = False
    notes: Optional[str] = None


# =============================================================================
# CHEMICAL PRODUCTS
# =============================================================================

class ChemicalProductCreate(BaseModel):
    chemical_type: ChemicalType
    brand: str = Field(..., min_length=1, max_length=100)
    product_name: str = Field(..., min_length=1, max_length=100)
    strength_pct_default: Optional[float] = Field(None, gt=0, le=100)
    package_size: Optional[str] = None
    notes: Optional[str] = None

class ChemicalProductResponse(BaseModel):
    id: int
    chemical_type: str
    brand: str
    product_name: str
    strength_pct_default: Optional[float]
    package_size: Optional[str]
    notes: Optional[str]
    is_active: bool


# =============================================================================
# CHEMICAL ADDITIONS
# =============================================================================

class ChemicalAdditionCreate(BaseModel):
    season_id: int
    inventory_id: Optional[int] = None
    product_id: Optional[int] = None
    addition_date: str
    addition_time: Optional[str] = None
    chemical_name: str
    quantity_added: float = Field(..., gt=0)
    unit: str
    strength_pct_used: Optional[float] = Field(None, gt=0, le=100)
    reason: Optional[str] = None
    application_method: Optional[ApplicationMethod] = None
    expected_stable_date: Optional[str] = None
    backwash_hold_until_date: Optional[str] = None
    notes: Optional[str] = None


# =============================================================================
# DOSE CALCULATION REQUESTS
# =============================================================================

class LiquidChlorineDoseRequest(BaseModel):
    current_fc: float = Field(..., ge=0, le=100)
    target_fc: float = Field(..., ge=0, le=100)
    pool_volume_gallons: int = Field(..., gt=0)
    strength_pct: float = Field(..., gt=0, le=100,
                                 description="Available chlorine % from the product label")

class CalHypoDoseRequest(BaseModel):
    current_fc: float = Field(..., ge=0, le=100)
    target_fc: float = Field(..., ge=0, le=100)
    pool_volume_gallons: int = Field(..., gt=0)
    strength_pct: float = Field(..., gt=0, le=100,
                                 description="Available chlorine % from the product label (47-73%)")

class StabilizerDoseRequest(BaseModel):
    current_cya: float = Field(..., ge=0, le=300)
    target_cya: float = Field(..., ge=0, le=300)
    pool_volume_gallons: int = Field(..., gt=0)

class MuriaticAcidDoseRequest(BaseModel):
    current_ph: float = Field(..., ge=6.0, le=9.0)
    target_ph: float = Field(..., ge=6.0, le=9.0)
    pool_volume_gallons: int = Field(..., gt=0)

class CalciumDoseRequest(BaseModel):
    current_ch: float = Field(..., ge=0, le=1000)
    target_ch: float = Field(..., ge=0, le=1000)
    pool_volume_gallons: int = Field(..., gt=0)

class BakingSodaDoseRequest(BaseModel):
    current_ta: float = Field(..., ge=0, le=400)
    target_ta: float = Field(..., ge=0, le=400)
    pool_volume_gallons: int = Field(..., gt=0)

class TrichlorFloaterRequest(BaseModel):
    current_fc: float = Field(..., ge=0)
    target_fc: float = Field(..., ge=0)
    current_cya: float = Field(..., ge=0, le=300)
    pool_volume_gallons: int = Field(..., gt=0)
    tablets_currently_in_floater: int = Field(0, ge=0)

class DoseResponse(BaseModel):
    chemical: str
    amount: float
    unit: str
    current_value: float
    target_value: float
    delta: float
    pool_volume_gallons: int
    calculation_shown: str
    notes: Optional[str]
    side_effect_ppm: Optional[float] = None
    side_effect_parameter: Optional[str] = None


# =============================================================================
# FC/CYA TARGETS
# =============================================================================

class FCTargetsResponse(BaseModel):
    cya: float
    minimum_fc: float
    target_fc: float
    yellow_mustard_minimum_fc: float
    slam_fc: float
    cya_in_recommended_band: bool
    is_zero_cya_guardrail_active: bool
    fc_status: Optional[str] = None   # populated when current_fc is provided


# =============================================================================
# SLAM STATUS
# =============================================================================

class SlamStatusRequest(BaseModel):
    current_fc: float = Field(..., ge=0)
    cya: float = Field(..., ge=0)
    overnight_fc_drop: Optional[float] = Field(None, ge=0)
    combined_chlorine: Optional[float] = Field(None, ge=0)
    can_see_bottom: Optional[bool] = None

class SlamStatusResponse(BaseModel):
    fc_meets_slam_level: bool
    oclt_passed: Optional[bool]
    cc_acceptable: Optional[bool]
    water_clear: Optional[bool]
    is_complete: bool
    summary: str


# =============================================================================
# RECOVERY SESSIONS
# =============================================================================

class RecoverySessionCreate(BaseModel):
    season_id: int
    start_date: str
    starting_cya: Optional[float] = Field(None, ge=0)
    trigger_reason: Optional[TriggerReason] = None

class RecoverySessionResponse(BaseModel):
    id: int
    season_id: int
    start_date: str
    end_date: Optional[str]
    starting_cya: Optional[float]
    trigger_reason: Optional[str]
    status: str
    completion_notes: Optional[str]
    created_at: str


# =============================================================================
# MAINTENANCE LOG
# =============================================================================

class MaintenanceEventCreate(BaseModel):
    season_id: int
    event_date: str
    event_time: Optional[str] = None
    event_type: str
    pressure_before_psi: Optional[float] = Field(None, ge=0)
    pressure_after_psi: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None


# =============================================================================
# EQUIPMENT INCIDENTS
# =============================================================================

class EquipmentIncidentCreate(BaseModel):
    season_id: int
    incident_date: str
    incident_time: Optional[str] = None
    component: str
    description: str
    cause_identified: Optional[str] = None
    resolution: Optional[str] = None
    resolved_date: Optional[str] = None

class EquipmentIncidentUpdate(BaseModel):
    cause_identified: Optional[str] = None
    resolution: Optional[str] = None
    resolved_date: Optional[str] = None


# =============================================================================
# WATER LEVEL EVENTS
# =============================================================================

class WaterLevelEventCreate(BaseModel):
    season_id: int
    event_date: str
    reason: Optional[str] = None
    estimated_gallons: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None


# =============================================================================
# OPERATIONAL STATUS
# =============================================================================

class OperationalStatusCreate(BaseModel):
    season_id: int
    status: OperationalStatus
    status_date: str
    status_time: Optional[str] = None
    reason: Optional[str] = None
    recovery_session_id: Optional[int] = None


# =============================================================================
# DASHBOARD
# =============================================================================

class LastChlorineAdditionSummary(BaseModel):
    """Most recent addition of an actual chlorine source (liquid chlorine,
    Cal-Hypo, or Trichlor tablets) - excludes non-chlorine chemicals like
    stabilizer or muriatic acid."""
    chemical_name: str
    quantity: float
    unit: str
    addition_date: str


class DashboardResponse(BaseModel):
    """Single response shape for the dashboard - everything the UI needs in
    one call rather than six separate fetches on every page load."""
    current_mode: str
    current_operational_status: str
    latest_reading: Optional[ChemistryReadingResponse]
    fc_targets: Optional[FCTargetsResponse]
    fc_status: Optional[str]
    active_recovery_session: Optional[RecoverySessionResponse]
    pending_notifications_count: int
    days_since_backwash: Optional[int]
    days_since_brush: Optional[int]
    days_since_vacuum: Optional[int]
    filter_pressure_pct_above_clean: Optional[float]
    suspect_reading_flag: Optional[str]
    fc_trend_delta: Optional[float] = None
    fc_trend_direction: Optional[str] = None  # 'up' | 'down' | 'flat'
    last_chlorine_addition: Optional[LastChlorineAdditionSummary] = None
    days_since_skimmer_emptied: Optional[int] = None
    days_since_basket_cleaned: Optional[int] = None


# =============================================================================
# TIMELINE
# =============================================================================

class TimelineEntry(BaseModel):
    """One unified activity-feed row, merged from chemistry_readings,
    maintenance_log, and chemical_additions. Read-only, computed on request -
    not a stored table."""
    date: str
    time: Optional[str] = None
    type: str  # 'reading' | 'maintenance' | 'addition'
    summary: str
    detail: Optional[str] = None


# =============================================================================
# SEASONS
# =============================================================================

class SeasonCreate(BaseModel):
    label: str
    start_date: str
    end_date: Optional[str] = None
    notes: Optional[str] = None

class SeasonResponse(BaseModel):
    id: int
    label: str
    start_date: str
    end_date: Optional[str]
    is_current: bool
    notes: Optional[str]


# =============================================================================
# NOTIFICATIONS
# =============================================================================

class NotificationResponse(BaseModel):
    id: int
    created_date: str
    category: str
    severity: str
    message: str
    is_dismissed: bool
