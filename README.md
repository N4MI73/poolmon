# PoolMon

**Pool Chemistry Tracker & Recovery Dashboard**

Self-hosted pool management application for routine maintenance and SLAM/algae recovery.
Built for a single-user, local-network NAS deployment.

---

## What it does

- Records daily chemistry test results (FC, CC, pH, TA, CH, CYA, pressure, temp)
- Calculates chemical doses using TFP/PoolMath formulas with full "Why?" explanation
- Tracks three distinct chlorine types: liquid chlorine (SLAM/recovery), Cal-Hypo granular shock (routine maintenance), Trichlor 3" tablets (floater)
- Flags DPD bleach-out false readings and prompts for dilution retest
- Manages the full SLAM recovery workflow with three-part completion criteria (OCLT, CC, clarity)
- Tracks chemical products by brand/name/strength so doses are always calculated against the label on the actual bottle used
- Records equipment incidents (breaker trips, pump issues) separately from routine maintenance
- Tracks six operational states (Swimming Ready → Investigation → Recovery → Polishing → Maintenance → Winterized) with full history
- Logs daily conditions (weather, swimmer count, debris, cleaning tasks) for trend analysis

---

## Deployment on NAS via Portainer

### 1. Build the image

On your NAS or a machine with Docker:

```bash
git clone https://github.com/N4MI73/poolmon.git   # or copy the folder
cd poolmon
docker build -t poolmon:latest .
```

### 2. Deploy via Portainer

1. In Portainer, go to **Stacks → Add Stack**
2. Name it `poolmon`
3. Paste the contents of `docker-compose.yml` into the Web editor
4. **Edit the volume path** on this line to match your NAS:
   ```yaml
   - /volume1/docker/poolmon/data:/data
   ```
   Use whatever path makes sense for your NAS layout (Synology, QNAP, etc.)
5. Click **Deploy the stack**

The container will:
- Start the API on port **8078**
- Create `poolmon.db` inside your data volume on first run
- Serve the frontend at `http://<nas-ip>:8078`
- Show API docs at `http://<nas-ip>:8078/docs`

### 3. Access

Open `http://<nas-ip>:8078` on any device on your local network.

---

## Backup

Everything that matters is in the data volume:

```
/your/nas/path/poolmon-data/
  poolmon.db        ← the entire database (back this up)
  photos/           ← pool photos by season/date
```

Copy that folder = complete backup of all history, readings, and photos.

---

## Project structure

```
poolmon/
  app/
    main.py          ← FastAPI routes (41 endpoints)
    database.py      ← SQLite connection and initialization
    models.py        ← Pydantic request/response models
  engine/
    chemistry.py     ← Chemistry calculation engine (pure Python, no dependencies)
    test_chemistry.py← 79-test suite for the chemistry engine
  frontend/
    index.html       ← UI (plain HTML/JS, no build pipeline)
  schema_v4.sql      ← SQLite schema (17 tables)
  requirements.txt   ← Python dependencies (FastAPI, uvicorn, pydantic only)
  Dockerfile
  docker-compose.yml
  README.md
```

---

## Running the test suite

```bash
cd poolmon
python3 engine/test_chemistry.py
```

All 79 chemistry engine tests should pass. No pytest or other test framework required.

---

## Chemistry model

Built on the **Trouble Free Pool (TFP) / PoolMath** model:

| Level | Formula |
|---|---|
| Minimum FC | CYA × 7.5% |
| Target FC | CYA × 11.5% |
| SLAM/Shock FC | CYA × 40% |

SLAM completion requires all three simultaneously: OCLT drop ≤ 1.0 ppm, CC ≤ 0.5 ppm, water clarity.

---

## Chemical products

The app maintains a product catalog (brand + product name + available chlorine %). When logging a dose, you pick from the catalog and the strength pre-fills the calculation. The actual strength used is frozen on the addition record — so "Why?" always shows what was really used, not a current default.

**Strength matters:**
- Cal-Hypo ranges from 47% to 73% by brand — wrong strength = wrong dose
- Liquid chlorine ranges from 10% to 12.5%
- Always prompted when logging a dose; always recorded in history

---

## Technology

| Layer | Choice |
|---|---|
| Backend | Python / FastAPI |
| Database | SQLite (single file, backs up with `cp`) |
| Frontend | Plain HTML/JS, no build pipeline |
| Container | Single Docker image, Portainer-managed |
| Photos | Local filesystem (mounted volume) |

No external services, no cloud dependencies, no npm.
