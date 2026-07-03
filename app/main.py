"""
PoolMon FastAPI Backend
========================

All API routes in one file - appropriate at this project scale.
If this grows beyond ~800 lines it's worth splitting into routers
by domain (chemistry, maintenance, recovery, etc.).

Route structure:
  GET  /api/dashboard                     - everything the dashboard needs
  POST /api/chemistry/readings            - log a chemistry test
  GET  /api/chemistry/readings            - list readings (filterable)
  POST /api/chemistry/targets             - calculate FC targets for a CYA value
  POST /api/chemistry/dose/liquid-chlorine
  POST /api/chemistry/dose/cal-hypo
  POST /api/chemistry/dose/trichlor-floater
  POST /api/chemistry/dose/stabilizer
  POST /api/chemistry/dose/muriatic-acid
  POST /api/chemistry/dose/calcium
  POST /api/chemistry/dose/baking-soda
  POST /api/chemistry/slam-status
  GET  /api/products                      - list product catalog
  POST /api/products                      - add a product
  GET  /api/products/{chemical_type}      - list products by type
  POST /api/additions                     - log a chemical addition
  GET  /api/additions                     - list additions
  POST /api/maintenance                   - log a maintenance event
  GET  /api/maintenance                   - list maintenance events
  POST /api/incidents                     - log an equipment incident
  GET  /api/incidents                     - list incidents
  PATCH /api/incidents/{id}               - update incident (resolution)
  POST /api/water-level                   - log a top-off
  POST /api/recovery/sessions             - start a recovery session
  GET  /api/recovery/sessions             - list recovery sessions
  PATCH /api/recovery/sessions/{id}/complete
  POST /api/status                        - record operational status change
  GET  /api/status/history                - full status history
  GET  /api/notifications                 - list active notifications
  POST /api/notifications/{id}/dismiss    - dismiss a notification
  GET  /api/seasons                       - list seasons
  POST /api/seasons                       - create a season
  GET  /api/config                        - get pool config
  PATCH /api/config                       - update pool config
  POST /api/daily-conditions              - log daily conditions
  GET  /api/daily-conditions              - list conditions
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional, List
import sqlite3
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from app.database import get_connection, init_db
from app.models import (
    ChemistryReadingCreate, ChemistryReadingResponse,
    DailyConditionsCreate,
    ChemicalProductCreate, ChemicalProductResponse,
    ChemicalAdditionCreate,
    LiquidChlorineDoseRequest, CalHypoDoseRequest, StabilizerDoseRequest,
    MuriaticAcidDoseRequest, CalciumDoseRequest, BakingSodaDoseRequest,
    TrichlorFloaterRequest, DoseResponse,
    FCTargetsResponse, SlamStatusRequest, SlamStatusResponse,
    RecoverySessionCreate, RecoverySessionResponse,
    MaintenanceEventCreate, EquipmentIncidentCreate, EquipmentIncidentUpdate,
    WaterLevelEventCreate, OperationalStatusCreate,
    DashboardResponse, SeasonCreate, SeasonResponse, NotificationResponse,
)
from engine.chemistry import (
    calculate_fc_targets, classify_fc_status,
    dose_liquid_chlorine_gallons, dose_cal_hypo_lbs,
    dose_stabilizer_lbs, dose_muriatic_acid_floz,
    dose_calcium_lbs, dose_baking_soda_lbs,
    assess_trichlor_floater, evaluate_slam_status,
    should_flag_suspect_bleachout, apply_dilution_factor,
)

# =============================================================================
# APP SETUP
# =============================================================================

app = FastAPI(
    title="PoolMon",
    description="Pool Chemistry Tracker & Recovery Dashboard",
    version="1.0.0",
)

# Allow the plain HTML/JS frontend (served from the same container) to call
# the API. In production this is localhost-only anyway, but CORS middleware
# is needed for the dev workflow where frontend and backend may run on
# different ports.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local network only - no auth needed at this stage
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


# Dependency: yields an open DB connection, always closes it after the request
def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row) if row else None


def rows_to_list(rows) -> list:
    return [dict(r) for r in rows]


# =============================================================================
# DASHBOARD
# =============================================================================

@app.get("/api/dashboard", response_model=DashboardResponse)
def get_dashboard(db: sqlite3.Connection = Depends(get_db)):
    """
    Single endpoint for everything the dashboard page needs.
    Avoids the pattern of the frontend making 6-8 separate calls on load.
    """
    cur = db.cursor()

    # Pool config (mode + operational status)
    cur.execute("SELECT current_mode, current_operational_status, clean_filter_pressure_psi FROM pool_config WHERE id = 1")
    config = row_to_dict(cur.fetchone())

    # Latest chemistry reading
    cur.execute("""
        SELECT * FROM chemistry_readings
        ORDER BY reading_date DESC, reading_time DESC
        LIMIT 1
    """)
    latest_row = row_to_dict(cur.fetchone())

    # FC targets + status if we have a reading
    fc_targets_resp = None
    fc_status = None
    suspect_flag = None

    if latest_row and latest_row.get("cyanuric_acid") is not None:
        targets = calculate_fc_targets(latest_row["cyanuric_acid"])
        fc_targets_resp = FCTargetsResponse(
            cya=targets.cya,
            minimum_fc=targets.minimum_fc,
            target_fc=targets.target_fc,
            yellow_mustard_minimum_fc=targets.yellow_mustard_minimum_fc,
            slam_fc=targets.slam_fc,
            cya_in_recommended_band=targets.cya_in_recommended_band,
            is_zero_cya_guardrail_active=targets.is_zero_cya_guardrail_active,
        )
        if latest_row.get("free_chlorine") is not None:
            status = classify_fc_status(latest_row["free_chlorine"], targets)
            fc_status = status.value

            # Bleach-out check against the previous reading
            cur.execute("""
                SELECT free_chlorine FROM chemistry_readings
                WHERE id != ?
                ORDER BY reading_date DESC, reading_time DESC
                LIMIT 1
            """, (latest_row["id"],))
            prev = cur.fetchone()
            prev_fc = prev["free_chlorine"] if prev else None
            flagged, reason = should_flag_suspect_bleachout(
                latest_row["free_chlorine"], prev_fc,
                latest_row.get("test_method", "direct")
            )
            if flagged:
                suspect_flag = reason

    # Active recovery session
    cur.execute("""
        SELECT * FROM recovery_sessions WHERE status = 'active'
        ORDER BY start_date DESC LIMIT 1
    """)
    recovery_row = row_to_dict(cur.fetchone())

    # Pending notifications
    cur.execute("SELECT COUNT(*) as n FROM notifications WHERE is_dismissed = 0")
    notif_count = cur.fetchone()["n"]

    # Days since last backwash
    cur.execute("""
        SELECT event_date FROM maintenance_log
        WHERE event_type = 'backwash'
        ORDER BY event_date DESC LIMIT 1
    """)
    last_backwash = cur.fetchone()
    days_since_backwash = None
    if last_backwash:
        delta = date.today() - date.fromisoformat(last_backwash["event_date"])
        days_since_backwash = delta.days

    # Days since last brush
    cur.execute("""
        SELECT event_date FROM maintenance_log
        WHERE event_type = 'brush'
        ORDER BY event_date DESC LIMIT 1
    """)
    last_brush = cur.fetchone()
    days_since_brush = None
    if last_brush:
        delta = date.today() - date.fromisoformat(last_brush["event_date"])
        days_since_brush = delta.days

    # Days since last vacuum
    cur.execute("""
        SELECT event_date FROM maintenance_log
        WHERE event_type IN ('vacuum', 'robot')
        ORDER BY event_date DESC LIMIT 1
    """)
    last_vacuum = cur.fetchone()
    days_since_vacuum = None
    if last_vacuum:
        delta = date.today() - date.fromisoformat(last_vacuum["event_date"])
        days_since_vacuum = delta.days

    # Filter pressure % above clean baseline
    pressure_pct = None
    clean_psi = config.get("clean_filter_pressure_psi")
    if clean_psi and latest_row and latest_row.get("filter_pressure_psi"):
        current_psi = latest_row["filter_pressure_psi"]
        pressure_pct = round(((current_psi - clean_psi) / clean_psi) * 100, 1)

    return DashboardResponse(
        current_mode=config["current_mode"],
        current_operational_status=config["current_operational_status"],
        latest_reading=ChemistryReadingResponse(**latest_row) if latest_row else None,
        fc_targets=fc_targets_resp,
        fc_status=fc_status,
        active_recovery_session=RecoverySessionResponse(**recovery_row) if recovery_row else None,
        pending_notifications_count=notif_count,
        days_since_backwash=days_since_backwash,
        days_since_brush=days_since_brush,
        days_since_vacuum=days_since_vacuum,
        filter_pressure_pct_above_clean=pressure_pct,
        suspect_reading_flag=suspect_flag,
    )


# =============================================================================
# CHEMISTRY READINGS
# =============================================================================

@app.post("/api/chemistry/readings", response_model=ChemistryReadingResponse, status_code=201)
def create_chemistry_reading(
    body: ChemistryReadingCreate,
    db: sqlite3.Connection = Depends(get_db)
):
    """Log a chemistry test result."""
    cur = db.cursor()
    cur.execute("""
        INSERT INTO chemistry_readings (
            season_id, reading_date, reading_time,
            free_chlorine, combined_chlorine, ph,
            total_alkalinity, calcium_hardness, cyanuric_acid,
            water_temp_f, filter_pressure_psi, weather, air_temp_f, notes,
            is_recovery_entry, recovery_period, recovery_session_id,
            test_method, dilution_factor, is_suspect_reading, suspect_reason
        ) VALUES (
            :season_id, :reading_date, :reading_time,
            :free_chlorine, :combined_chlorine, :ph,
            :total_alkalinity, :calcium_hardness, :cyanuric_acid,
            :water_temp_f, :filter_pressure_psi, :weather, :air_temp_f, :notes,
            :is_recovery_entry, :recovery_period, :recovery_session_id,
            :test_method, :dilution_factor, :is_suspect_reading, :suspect_reason
        )
    """, body.dict())
    db.commit()
    cur.execute("SELECT * FROM chemistry_readings WHERE id = ?", (cur.lastrowid,))
    return row_to_dict(cur.fetchone())


@app.get("/api/chemistry/readings", response_model=List[ChemistryReadingResponse])
def list_chemistry_readings(
    season_id: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    recovery_session_id: Optional[int] = None,
    limit: int = Query(50, le=200),
    db: sqlite3.Connection = Depends(get_db)
):
    """List chemistry readings, newest first, with optional filters."""
    sql = "SELECT * FROM chemistry_readings WHERE 1=1"
    params = []
    if season_id:
        sql += " AND season_id = ?"
        params.append(season_id)
    if from_date:
        sql += " AND reading_date >= ?"
        params.append(from_date)
    if to_date:
        sql += " AND reading_date <= ?"
        params.append(to_date)
    if recovery_session_id:
        sql += " AND recovery_session_id = ?"
        params.append(recovery_session_id)
    sql += " ORDER BY reading_date DESC, reading_time DESC LIMIT ?"
    params.append(limit)

    cur = db.cursor()
    cur.execute(sql, params)
    return rows_to_list(cur.fetchall())


@app.get("/api/chemistry/readings/{reading_id}", response_model=ChemistryReadingResponse)
def get_chemistry_reading(reading_id: int, db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT * FROM chemistry_readings WHERE id = ?", (reading_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Reading not found")
    return row_to_dict(row)


# =============================================================================
# CHEMISTRY CALCULATIONS
# =============================================================================

@app.post("/api/chemistry/targets", response_model=FCTargetsResponse)
def get_fc_targets(
    cya: float = Query(..., ge=0, le=300),
    current_fc: Optional[float] = Query(None, ge=0),
):
    """Calculate FC targets for a given CYA level."""
    targets = calculate_fc_targets(cya)
    status = None
    if current_fc is not None:
        status = classify_fc_status(current_fc, targets).value
    return FCTargetsResponse(
        cya=targets.cya,
        minimum_fc=targets.minimum_fc,
        target_fc=targets.target_fc,
        yellow_mustard_minimum_fc=targets.yellow_mustard_minimum_fc,
        slam_fc=targets.slam_fc,
        cya_in_recommended_band=targets.cya_in_recommended_band,
        is_zero_cya_guardrail_active=targets.is_zero_cya_guardrail_active,
        fc_status=status,
    )


@app.post("/api/chemistry/slam-status", response_model=SlamStatusResponse)
def get_slam_status(body: SlamStatusRequest):
    """Evaluate SLAM completion criteria."""
    result = evaluate_slam_status(
        current_fc=body.current_fc,
        cya=body.cya,
        overnight_fc_drop=body.overnight_fc_drop,
        combined_chlorine=body.combined_chlorine,
        can_see_bottom=body.can_see_bottom,
    )
    return SlamStatusResponse(
        fc_meets_slam_level=result.fc_meets_slam_level,
        oclt_passed=result.oclt_passed,
        cc_acceptable=result.cc_acceptable,
        water_clear=result.water_clear,
        is_complete=result.is_complete,
        summary=result.summary,
    )


def _dose_to_response(result) -> DoseResponse:
    return DoseResponse(
        chemical=result.chemical,
        amount=result.amount,
        unit=result.unit,
        current_value=result.current_value,
        target_value=result.target_value,
        delta=result.delta,
        pool_volume_gallons=result.pool_volume_gallons,
        calculation_shown=result.calculation_shown,
        notes=result.notes,
        side_effect_ppm=result.side_effect_ppm,
        side_effect_parameter=result.side_effect_parameter,
    )


@app.post("/api/chemistry/dose/liquid-chlorine", response_model=DoseResponse)
def dose_liquid_chlorine(body: LiquidChlorineDoseRequest):
    """Calculate liquid chlorine dose (SLAM/recovery use)."""
    result = dose_liquid_chlorine_gallons(
        current_fc=body.current_fc,
        target_fc=body.target_fc,
        pool_volume_gallons=body.pool_volume_gallons,
        chlorine_strength_pct=body.strength_pct,
    )
    return _dose_to_response(result)


@app.post("/api/chemistry/dose/cal-hypo", response_model=DoseResponse)
def dose_cal_hypo(body: CalHypoDoseRequest):
    """Calculate Cal-Hypo granular shock dose (routine maintenance)."""
    try:
        result = dose_cal_hypo_lbs(
            current_fc=body.current_fc,
            target_fc=body.target_fc,
            pool_volume_gallons=body.pool_volume_gallons,
            cal_hypo_strength_pct=body.strength_pct,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _dose_to_response(result)


@app.post("/api/chemistry/dose/trichlor-floater")
def dose_trichlor_floater(body: TrichlorFloaterRequest):
    """Assess trichlor floater situation including CYA creep risk."""
    result = assess_trichlor_floater(
        current_fc=body.current_fc,
        target_fc=body.target_fc,
        current_cya=body.current_cya,
        pool_volume_gallons=body.pool_volume_gallons,
        tablets_currently_in_floater=body.tablets_currently_in_floater,
    )
    return {
        "recommended_tablets": result.recommended_tablets,
        "estimated_fc_contribution_per_day": result.estimated_fc_contribution_per_day,
        "cya_added_per_tablet": result.cya_added_per_tablet,
        "current_cya": result.current_cya,
        "projected_cya_after_tablets": result.projected_cya_after_tablets,
        "cya_warning": result.cya_warning,
        "notes": result.notes,
    }


@app.post("/api/chemistry/dose/stabilizer", response_model=DoseResponse)
def dose_stabilizer(body: StabilizerDoseRequest):
    result = dose_stabilizer_lbs(body.current_cya, body.target_cya, body.pool_volume_gallons)
    return _dose_to_response(result)


@app.post("/api/chemistry/dose/muriatic-acid", response_model=DoseResponse)
def dose_muriatic_acid(body: MuriaticAcidDoseRequest):
    result = dose_muriatic_acid_floz(body.current_ph, body.target_ph, body.pool_volume_gallons)
    return _dose_to_response(result)


@app.post("/api/chemistry/dose/calcium", response_model=DoseResponse)
def dose_calcium(body: CalciumDoseRequest):
    result = dose_calcium_lbs(body.current_ch, body.target_ch, body.pool_volume_gallons)
    return _dose_to_response(result)


@app.post("/api/chemistry/dose/baking-soda", response_model=DoseResponse)
def dose_baking_soda(body: BakingSodaDoseRequest):
    result = dose_baking_soda_lbs(body.current_ta, body.target_ta, body.pool_volume_gallons)
    return _dose_to_response(result)


# =============================================================================
# CHEMICAL PRODUCTS CATALOG
# =============================================================================

@app.get("/api/products", response_model=List[ChemicalProductResponse])
def list_products(
    chemical_type: Optional[str] = None,
    active_only: bool = True,
    db: sqlite3.Connection = Depends(get_db)
):
    """List the product catalog, optionally filtered by chemical type."""
    sql = "SELECT * FROM chemical_products WHERE 1=1"
    params = []
    if active_only:
        sql += " AND is_active = 1"
    if chemical_type:
        sql += " AND chemical_type = ?"
        params.append(chemical_type)
    sql += " ORDER BY chemical_type, brand, product_name"
    cur = db.cursor()
    cur.execute(sql, params)
    return rows_to_list(cur.fetchall())


@app.post("/api/products", response_model=ChemicalProductResponse, status_code=201)
def create_product(body: ChemicalProductCreate, db: sqlite3.Connection = Depends(get_db)):
    """Add a new product to the catalog."""
    cur = db.cursor()
    try:
        cur.execute("""
            INSERT INTO chemical_products
                (chemical_type, brand, product_name, strength_pct_default, package_size, notes)
            VALUES (:chemical_type, :brand, :product_name, :strength_pct_default, :package_size, :notes)
        """, body.dict())
        db.commit()
        cur.execute("SELECT * FROM chemical_products WHERE id = ?", (cur.lastrowid,))
        return row_to_dict(cur.fetchone())
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"Product '{body.brand} {body.product_name}' already exists for {body.chemical_type}"
        )


@app.patch("/api/products/{product_id}/retire")
def retire_product(product_id: int, db: sqlite3.Connection = Depends(get_db)):
    """Retire a product (hide from picker, keep history)."""
    cur = db.cursor()
    cur.execute("UPDATE chemical_products SET is_active = 0 WHERE id = ?", (product_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    db.commit()
    return {"message": "Product retired"}


# =============================================================================
# CHEMICAL ADDITIONS
# =============================================================================

@app.post("/api/additions", status_code=201)
def create_addition(body: ChemicalAdditionCreate, db: sqlite3.Connection = Depends(get_db)):
    """Log a chemical addition."""
    cur = db.cursor()

    # If a product_id was provided and no strength_pct_used was given,
    # pull the product's default strength automatically.
    strength_pct_used = body.strength_pct_used
    if body.product_id and strength_pct_used is None:
        cur.execute(
            "SELECT strength_pct_default FROM chemical_products WHERE id = ?",
            (body.product_id,)
        )
        product = cur.fetchone()
        if product and product["strength_pct_default"]:
            strength_pct_used = product["strength_pct_default"]

    cur.execute("""
        INSERT INTO chemical_additions (
            season_id, inventory_id, product_id, addition_date, addition_time,
            chemical_name, quantity_added, unit, strength_pct_used, reason,
            application_method, expected_stable_date, backwash_hold_until_date, notes
        ) VALUES (
            :season_id, :inventory_id, :product_id, :addition_date, :addition_time,
            :chemical_name, :quantity_added, :unit, :strength_pct_used, :reason,
            :application_method, :expected_stable_date, :backwash_hold_until_date, :notes
        )
    """, {**body.dict(), "strength_pct_used": strength_pct_used})

    # Deduct from inventory if inventory_id provided
    if body.inventory_id:
        cur.execute("""
            UPDATE chemical_inventory
            SET current_quantity = MAX(0, current_quantity - ?), updated_at = datetime('now')
            WHERE id = ?
        """, (body.quantity_added, body.inventory_id))

    db.commit()
    addition_id = cur.lastrowid

    # Auto-generate notifications for backwash holds
    if body.backwash_hold_until_date:
        cur.execute("""
            INSERT INTO notifications (category, severity, message)
            VALUES ('backwash_wait', 'warning',
                    'Do not backwash until ' || ? || ' - stabilizer is still dissolving.')
        """, (body.backwash_hold_until_date,))
        db.commit()

    return {"id": addition_id, "message": "Addition logged"}


@app.get("/api/additions")
def list_additions(
    season_id: Optional[int] = None,
    chemical_name: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: sqlite3.Connection = Depends(get_db)
):
    """List chemical additions with product info joined."""
    sql = """
        SELECT ca.*, cp.brand, cp.product_name
        FROM chemical_additions ca
        LEFT JOIN chemical_products cp ON ca.product_id = cp.id
        WHERE 1=1
    """
    params = []
    if season_id:
        sql += " AND ca.season_id = ?"
        params.append(season_id)
    if chemical_name:
        sql += " AND ca.chemical_name = ?"
        params.append(chemical_name)
    sql += " ORDER BY ca.addition_date DESC, ca.addition_time DESC LIMIT ?"
    params.append(limit)

    cur = db.cursor()
    cur.execute(sql, params)
    return rows_to_list(cur.fetchall())


# =============================================================================
# MAINTENANCE LOG
# =============================================================================

@app.post("/api/maintenance", status_code=201)
def create_maintenance_event(body: MaintenanceEventCreate, db: sqlite3.Connection = Depends(get_db)):
    """Log a maintenance event (backwash, brush, vacuum, etc.)."""
    cur = db.cursor()
    cur.execute("""
        INSERT INTO maintenance_log
            (season_id, event_date, event_time, event_type, pressure_before_psi, pressure_after_psi, notes)
        VALUES
            (:season_id, :event_date, :event_time, :event_type, :pressure_before_psi, :pressure_after_psi, :notes)
    """, body.dict())

    # Update clean_filter_pressure_psi in pool_config after a backwash
    if body.event_type == "backwash" and body.pressure_after_psi:
        cur.execute("""
            UPDATE pool_config
            SET clean_filter_pressure_psi = ?, updated_at = datetime('now')
            WHERE id = 1
        """, (body.pressure_after_psi,))

    db.commit()
    return {"id": cur.lastrowid, "message": "Maintenance event logged"}


@app.get("/api/maintenance")
def list_maintenance_events(
    season_id: Optional[int] = None,
    event_type: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: sqlite3.Connection = Depends(get_db)
):
    sql = "SELECT * FROM maintenance_log WHERE 1=1"
    params = []
    if season_id:
        sql += " AND season_id = ?"
        params.append(season_id)
    if event_type:
        sql += " AND event_type = ?"
        params.append(event_type)
    sql += " ORDER BY event_date DESC, event_time DESC LIMIT ?"
    params.append(limit)
    cur = db.cursor()
    cur.execute(sql, params)
    return rows_to_list(cur.fetchall())


# =============================================================================
# EQUIPMENT INCIDENTS
# =============================================================================

@app.post("/api/incidents", status_code=201)
def create_incident(body: EquipmentIncidentCreate, db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("""
        INSERT INTO equipment_incidents
            (season_id, incident_date, incident_time, component, description,
             cause_identified, resolution, resolved_date)
        VALUES
            (:season_id, :incident_date, :incident_time, :component, :description,
             :cause_identified, :resolution, :resolved_date)
    """, body.dict())
    db.commit()
    return {"id": cur.lastrowid, "message": "Incident logged"}


@app.get("/api/incidents")
def list_incidents(
    season_id: Optional[int] = None,
    component: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db)
):
    sql = "SELECT * FROM equipment_incidents WHERE 1=1"
    params = []
    if season_id:
        sql += " AND season_id = ?"
        params.append(season_id)
    if component:
        sql += " AND component = ?"
        params.append(component)
    sql += " ORDER BY incident_date DESC"
    cur = db.cursor()
    cur.execute(sql, params)
    return rows_to_list(cur.fetchall())


@app.patch("/api/incidents/{incident_id}")
def update_incident(
    incident_id: int,
    body: EquipmentIncidentUpdate,
    db: sqlite3.Connection = Depends(get_db)
):
    """Update an incident with the cause and/or resolution."""
    cur = db.cursor()
    fields = {k: v for k, v in body.dict().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=422, detail="No fields provided to update")
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    cur.execute(
        f"UPDATE equipment_incidents SET {set_clause} WHERE id = ?",
        list(fields.values()) + [incident_id]
    )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Incident not found")
    db.commit()
    return {"message": "Incident updated"}


# =============================================================================
# WATER LEVEL EVENTS
# =============================================================================

@app.post("/api/water-level", status_code=201)
def create_water_level_event(body: WaterLevelEventCreate, db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("""
        INSERT INTO water_level_events (season_id, event_date, reason, estimated_gallons, notes)
        VALUES (:season_id, :event_date, :reason, :estimated_gallons, :notes)
    """, body.dict())
    db.commit()
    return {"id": cur.lastrowid, "message": "Water level event logged"}


# =============================================================================
# DAILY CONDITIONS
# =============================================================================

@app.post("/api/daily-conditions", status_code=201)
def create_daily_conditions(body: DailyConditionsCreate, db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    d = body.dict()
    # Convert booleans to 0/1 for SQLite
    for field in ['cover_installed_overnight', 'cover_removed_during_day',
                  'walls_brushed', 'floor_brushed', 'robot_cleaner_run',
                  'vacuumed_manually', 'skimmer_emptied', 'pump_basket_cleaned']:
        if d[field] is not None:
            d[field] = int(d[field])
    cur.execute("""
        INSERT INTO daily_conditions (
            season_id, condition_date, reading_id, air_temp_f, water_temp_f,
            sky_condition, rainfall_inches, wind_condition,
            swimmer_count, swim_duration_minutes,
            cover_installed_overnight, cover_removed_during_day,
            debris_level, debris_notes,
            walls_brushed, floor_brushed, robot_cleaner_run,
            vacuumed_manually, skimmer_emptied, pump_basket_cleaned, notes
        ) VALUES (
            :season_id, :condition_date, :reading_id, :air_temp_f, :water_temp_f,
            :sky_condition, :rainfall_inches, :wind_condition,
            :swimmer_count, :swim_duration_minutes,
            :cover_installed_overnight, :cover_removed_during_day,
            :debris_level, :debris_notes,
            :walls_brushed, :floor_brushed, :robot_cleaner_run,
            :vacuumed_manually, :skimmer_emptied, :pump_basket_cleaned, :notes
        )
    """, d)
    db.commit()
    return {"id": cur.lastrowid, "message": "Daily conditions logged"}


@app.get("/api/daily-conditions")
def list_daily_conditions(
    season_id: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = Query(30, le=200),
    db: sqlite3.Connection = Depends(get_db)
):
    sql = "SELECT * FROM daily_conditions WHERE 1=1"
    params = []
    if season_id:
        sql += " AND season_id = ?"
        params.append(season_id)
    if from_date:
        sql += " AND condition_date >= ?"
        params.append(from_date)
    if to_date:
        sql += " AND condition_date <= ?"
        params.append(to_date)
    sql += " ORDER BY condition_date DESC LIMIT ?"
    params.append(limit)
    cur = db.cursor()
    cur.execute(sql, params)
    return rows_to_list(cur.fetchall())


# =============================================================================
# RECOVERY SESSIONS
# =============================================================================

@app.post("/api/recovery/sessions", response_model=RecoverySessionResponse, status_code=201)
def create_recovery_session(body: RecoverySessionCreate, db: sqlite3.Connection = Depends(get_db)):
    """Start a new recovery/SLAM session and flip the pool into recovery mode."""
    cur = db.cursor()
    cur.execute("""
        INSERT INTO recovery_sessions (season_id, start_date, starting_cya, trigger_reason, status)
        VALUES (:season_id, :start_date, :starting_cya, :trigger_reason, 'active')
    """, body.dict())
    session_id = cur.lastrowid

    # Flip pool into recovery mode
    cur.execute("""
        UPDATE pool_config
        SET current_mode = 'recovery',
            active_recovery_session_id = ?,
            current_operational_status = 'recovery_mode',
            updated_at = datetime('now')
        WHERE id = 1
    """, (session_id,))

    # Record the status transition
    cur.execute("""
        INSERT INTO operational_status_history (season_id, status, status_date, reason, recovery_session_id)
        VALUES (?, 'recovery_mode', ?, 'Recovery session started', ?)
    """, (body.season_id, body.start_date, session_id))

    db.commit()
    cur.execute("SELECT * FROM recovery_sessions WHERE id = ?", (session_id,))
    return row_to_dict(cur.fetchone())


@app.get("/api/recovery/sessions", response_model=List[RecoverySessionResponse])
def list_recovery_sessions(
    season_id: Optional[int] = None,
    db: sqlite3.Connection = Depends(get_db)
):
    sql = "SELECT * FROM recovery_sessions WHERE 1=1"
    params = []
    if season_id:
        sql += " AND season_id = ?"
        params.append(season_id)
    sql += " ORDER BY start_date DESC"
    cur = db.cursor()
    cur.execute(sql, params)
    return rows_to_list(cur.fetchall())


@app.patch("/api/recovery/sessions/{session_id}/complete")
def complete_recovery_session(
    session_id: int,
    completion_notes: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db)
):
    """Mark a recovery session as complete and return to maintenance mode."""
    cur = db.cursor()
    today = date.today().isoformat()

    cur.execute("""
        UPDATE recovery_sessions
        SET status = 'completed', end_date = ?, completion_notes = ?
        WHERE id = ? AND status = 'active'
    """, (today, completion_notes, session_id))

    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Active recovery session not found")

    cur.execute("""
        SELECT season_id FROM recovery_sessions WHERE id = ?
    """, (session_id,))
    session = cur.fetchone()

    cur.execute("""
        UPDATE pool_config
        SET current_mode = 'maintenance',
            active_recovery_session_id = NULL,
            current_operational_status = 'routine_maintenance',
            updated_at = datetime('now')
        WHERE id = 1
    """)

    cur.execute("""
        INSERT INTO operational_status_history (season_id, status, status_date, reason, recovery_session_id)
        VALUES (?, 'routine_maintenance', ?, 'SLAM complete - returning to maintenance mode', ?)
    """, (session["season_id"], today, session_id))

    db.commit()
    return {"message": "Recovery session completed"}


# =============================================================================
# OPERATIONAL STATUS
# =============================================================================

@app.post("/api/status", status_code=201)
def record_status_change(body: OperationalStatusCreate, db: sqlite3.Connection = Depends(get_db)):
    """Record a pool operational status change."""
    cur = db.cursor()
    cur.execute("""
        INSERT INTO operational_status_history
            (season_id, status, status_date, status_time, reason, recovery_session_id)
        VALUES
            (:season_id, :status, :status_date, :status_time, :reason, :recovery_session_id)
    """, body.dict())

    cur.execute("""
        UPDATE pool_config
        SET current_operational_status = ?, updated_at = datetime('now')
        WHERE id = 1
    """, (body.status.value,))

    db.commit()
    return {"id": cur.lastrowid, "message": "Status recorded"}


@app.get("/api/status/history")
def get_status_history(
    season_id: Optional[int] = None,
    db: sqlite3.Connection = Depends(get_db)
):
    sql = "SELECT * FROM operational_status_history WHERE 1=1"
    params = []
    if season_id:
        sql += " AND season_id = ?"
        params.append(season_id)
    sql += " ORDER BY status_date DESC, status_time DESC"
    cur = db.cursor()
    cur.execute(sql, params)
    return rows_to_list(cur.fetchall())


# =============================================================================
# NOTIFICATIONS
# =============================================================================

@app.get("/api/notifications", response_model=List[NotificationResponse])
def list_notifications(
    dismissed: bool = False,
    db: sqlite3.Connection = Depends(get_db)
):
    cur = db.cursor()
    cur.execute("""
        SELECT * FROM notifications WHERE is_dismissed = ?
        ORDER BY created_date DESC
    """, (int(dismissed),))
    return rows_to_list(cur.fetchall())


@app.post("/api/notifications/{notification_id}/dismiss")
def dismiss_notification(notification_id: int, db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("""
        UPDATE notifications
        SET is_dismissed = 1, dismissed_at = datetime('now')
        WHERE id = ?
    """, (notification_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    db.commit()
    return {"message": "Notification dismissed"}


# =============================================================================
# SEASONS
# =============================================================================

@app.get("/api/seasons", response_model=List[SeasonResponse])
def list_seasons(db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT * FROM seasons ORDER BY start_date DESC")
    return rows_to_list(cur.fetchall())


@app.post("/api/seasons", response_model=SeasonResponse, status_code=201)
def create_season(body: SeasonCreate, db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("""
        UPDATE seasons SET is_current = 0
    """)
    cur.execute("""
        INSERT INTO seasons (label, start_date, end_date, is_current, notes)
        VALUES (:label, :start_date, :end_date, 1, :notes)
    """, body.dict())
    db.commit()
    cur.execute("SELECT * FROM seasons WHERE id = ?", (cur.lastrowid,))
    return row_to_dict(cur.fetchone())


# =============================================================================
# POOL CONFIG
# =============================================================================

@app.get("/api/config")
def get_config(db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT * FROM pool_config WHERE id = 1")
    return row_to_dict(cur.fetchone())


@app.patch("/api/config")
def update_config(updates: dict, db: sqlite3.Connection = Depends(get_db)):
    """Update pool config fields. Only provided fields are changed."""
    allowed = {
        "pool_type", "shape", "diameter_ft", "avg_depth_ft", "volume_gallons",
        "filter_type", "filter_model", "pump_model", "sanitizer_type",
        "liquid_chlorine_strength_pct", "clean_filter_pressure_psi", "test_kit_name",
    }
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        raise HTTPException(status_code=422, detail="No valid config fields provided")
    fields["updated_at"] = datetime.now().isoformat(sep=" ", timespec="seconds")
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    cur = db.cursor()
    cur.execute(f"UPDATE pool_config SET {set_clause} WHERE id = 1", list(fields.values()))
    db.commit()
    cur.execute("SELECT * FROM pool_config WHERE id = 1")
    return row_to_dict(cur.fetchone())


# =============================================================================
# SERVE FRONTEND (static files)
# =============================================================================

STATIC_DIR = Path(__file__).parent.parent / "frontend"

if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="frontend")
