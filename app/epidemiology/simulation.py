"""
Epidemiology simulation engine.

Generates realistic synthetic consultation data for demo, testing, and
visualization purposes. Runs as a background asyncio task when SIMULATION_MODE=True.

Data isolation:
- All generated consultations have is_simulation=TRUE in the database.
- The aggregation and heatmap queries include simulated data by default so
  the pipeline (detection, heatmap, alerts) is fully exercised.
- Set SIMULATION_MODE=False to stop generation. Existing rows remain unless
  explicitly purged via DELETE /epidemiology/simulation/purge.

Anomaly scenarios injected automatically after runtime thresholds:
  - Scenario 1 (Flu outbreak, Casablanca): fires after 3 minutes of uptime
  - Scenario 2 (Food poisoning, Rabat):    fires after 6 minutes of uptime
"""

import asyncio
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import AsyncSessionLocal as AsyncSessionFactory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# City configuration — real Moroccan cities with accurate coordinates
# ---------------------------------------------------------------------------

@dataclass
class CityConfig:
    name: str
    latitude: float
    longitude: float
    # A cabinet ID that will be created/reused for simulation rows
    cabinet_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # A patient ID (stub) — simulation rows point to this
    patient_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # A medecin ID (stub)
    medecin_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # Base cases per cycle (normal activity)
    base_cases: int = 4


CITIES: list[CityConfig] = [
    CityConfig(name="Casablanca", latitude=33.5731, longitude=-7.5898, base_cases=5),
    CityConfig(name="Rabat",      latitude=33.9716, longitude=-6.8498, base_cases=4),
    CityConfig(name="Marrakech",  latitude=31.6295, longitude=-8.0088, base_cases=3),
    CityConfig(name="Tanger",     latitude=35.7595, longitude=-5.8340, base_cases=3),
    CityConfig(name="Fes",        latitude=34.0181, longitude=-5.0078, base_cases=3),
]

# ---------------------------------------------------------------------------
# Disease → French diagnostic text templates
# Each template is a short clinical sentence that matches a DISEASE_KEYWORD
# pattern from keywords.py so it feeds the detection pipeline correctly.
# ---------------------------------------------------------------------------

NORMAL_DIAGNOSTICS: dict[str, list[str]] = {
    "Grippe": [
        "Grippe saisonnière",
        "Syndrome grippal avec fièvre",
        "État grippal",
        "Influenza type A",
    ],
    "Gastro-entérite": [
        "Gastro-entérite aiguë",
        "Gastroentérite virale",
        "Diarrhée aiguë — gastroentérite",
    ],
    "Angine": [
        "Angine érythémateuse",
        "Pharyngite aiguë",
        "Angine bactérienne",
    ],
    "Bronchite": [
        "Bronchite aiguë",
        "Infection bronchique",
    ],
    "Conjonctivite": [
        "Conjonctivite virale",
        "Conjonctivite allergique",
    ],
}

# Weights for normal distribution (more common → higher weight)
NORMAL_DISEASE_WEIGHTS: list[float] = [0.40, 0.20, 0.18, 0.13, 0.09]
NORMAL_DISEASE_KEYS: list[str] = list(NORMAL_DIAGNOSTICS.keys())

# Scenario-specific diagnostics
SCENARIO_FLU_DIAGNOSTICS: list[str] = [
    "Grippe saisonnière avec syndrome fébrile intense",
    "Influenza — fièvre élevée, toux, fatigue marquée",
    "Syndrome grippal sévère",
    "État grippal avec complications respiratoires",
    "Grippe — tableau clinique complet",
]

SCENARIO_FOOD_DIAGNOSTICS: list[str] = [
    "Intoxication alimentaire collective",
    "Gastro-entérite aiguë — toxi-infection alimentaire",
    "TIAC — toxi-infection alimentaire collective",
    "Intoxication alimentaire avec vomissements",
    "Gastro-entérite sévère post-ingestion suspecte",
]


# ---------------------------------------------------------------------------
# State machine for the simulation engine
# ---------------------------------------------------------------------------

class SimulationState:
    """Shared mutable state for the simulation engine (singleton)."""

    def __init__(self) -> None:
        self.running: bool = False
        self.task: Optional[asyncio.Task] = None
        self.start_time: Optional[float] = None   # monotonic clock
        self.cycles_completed: int = 0
        self.total_rows_inserted: int = 0
        self.scenario_1_fired: bool = False
        self.scenario_2_fired: bool = False
        self._rng: Optional[random.Random] = None

    @property
    def rng(self) -> random.Random:
        if self._rng is None:
            seed = settings.SIMULATION_SEED
            self._rng = random.Random(seed)
        return self._rng

    @property
    def uptime_seconds(self) -> float:
        if self.start_time is None:
            return 0.0
        return time.monotonic() - self.start_time


# Module-level singleton
_state = SimulationState()


def get_simulation_state() -> SimulationState:
    return _state


# ---------------------------------------------------------------------------
# Cabinet / patient / medecin bootstrap
# ---------------------------------------------------------------------------

async def _ensure_sim_cabinet(db: AsyncSession, city: CityConfig) -> None:
    """
    Upsert a simulation cabinet row for this city.

    Uses a deterministic ID so re-starts don't duplicate rows.
    The cabinet is marked with nom containing '[SIM]' for easy identification.
    """
    check = text("""
        SELECT COUNT(*) FROM cabinets WHERE id = :id
    """)
    result = await db.execute(check, {"id": city.cabinet_id})
    if result.scalar() > 0:
        return

    # Look up any real cabinet in this city to borrow cabinetOwnerId etc.
    # We do a minimal insert — only required fields.
    insert = text("""
        INSERT INTO cabinets (
            id, nom, ville, latitude, longitude,
            telephone, adresse,
            "createdAt", "updatedAt"
        )
        VALUES (
            :id,
            :nom,
            :ville,
            :latitude,
            :longitude,
            '0000000000',
            :adresse,
            NOW(), NOW()
        )
        ON CONFLICT (id) DO NOTHING
    """)
    await db.execute(insert, {
        "id": city.cabinet_id,
        "nom": f"[SIM] Cabinet {city.name}",
        "ville": city.name,
        "latitude": city.latitude,
        "longitude": city.longitude,
        "adresse": f"Simulation — {city.name}",
    })
    logger.info(f"[SIM] Created simulation cabinet for {city.name} (id={city.cabinet_id})")


async def _ensure_sim_patient(db: AsyncSession, city: CityConfig) -> None:
    """Upsert a simulation patient stub."""
    check = text("SELECT COUNT(*) FROM patients WHERE id = :id")
    result = await db.execute(check, {"id": city.patient_id})
    if result.scalar() > 0:
        return

    insert = text("""
        INSERT INTO patients (
            id, "cabinetId", nom, prenom,
            "dateNaissance", sexe,
            "createdAt", "updatedAt"
        )
        VALUES (
            :id, :cabinet_id,
            'Patient', 'Simulation',
            '1990-01-01', 'M',
            NOW(), NOW()
        )
        ON CONFLICT (id) DO NOTHING
    """)
    await db.execute(insert, {
        "id": city.patient_id,
        "cabinet_id": city.cabinet_id,
    })


async def _ensure_sim_medecin(db: AsyncSession, city: CityConfig) -> None:
    """
    Find an existing MEDECIN user in this city's cabinet, or create a stub.
    Reuses city.medecin_id for idempotency.
    """
    # Prefer a real doctor in this city
    find = text("""
        SELECT u.id FROM users u
        JOIN cabinets c ON u."cabinetId" = c.id
        WHERE u.role = 'MEDECIN' AND c.ville = :ville
        LIMIT 1
    """)
    result = await db.execute(find, {"ville": city.name})
    row = result.fetchone()
    if row:
        city.medecin_id = row[0]
        return

    # Create a stub user
    check = text("SELECT COUNT(*) FROM users WHERE id = :id")
    result = await db.execute(check, {"id": city.medecin_id})
    if result.scalar() > 0:
        return

    insert = text("""
        INSERT INTO users (
            id, "cabinetId", nom, prenom, email, password,
            role, actif,
            "createdAt", "updatedAt"
        )
        VALUES (
            :id, :cabinet_id,
            'Simulation', 'Medecin',
            :email, 'SIMULATION_HASH',
            'MEDECIN', true,
            NOW(), NOW()
        )
        ON CONFLICT (id) DO NOTHING
    """)
    await db.execute(insert, {
        "id": city.medecin_id,
        "cabinet_id": city.cabinet_id,
        "email": f"sim.{city.name.lower()}@simulation.local",
    })


async def bootstrap_simulation_fixtures(db: AsyncSession) -> None:
    """
    Create all cabinets / patients / médecins needed by the simulation.
    Called once at startup. Idempotent.
    """
    for city in CITIES:
        await _ensure_sim_cabinet(db, city)
        await _ensure_sim_patient(db, city)
        await _ensure_sim_medecin(db, city)
    await db.commit()
    logger.info("[SIM] Bootstrap fixtures done.")


# ---------------------------------------------------------------------------
# Consultation row generation
# ---------------------------------------------------------------------------

def _pick_diagnostic(rng: random.Random, disease: Optional[str] = None) -> str:
    """Pick a random French diagnostic text for the given disease category."""
    if disease is None:
        disease = rng.choices(NORMAL_DISEASE_KEYS, weights=NORMAL_DISEASE_WEIGHTS, k=1)[0]
    templates = NORMAL_DIAGNOSTICS.get(disease, NORMAL_DIAGNOSTICS["Grippe"])
    return rng.choice(templates)


async def _insert_consultation(
    db: AsyncSession,
    city: CityConfig,
    diagnostic: str,
    rng: random.Random,
) -> None:
    """Insert a single simulated consultation row."""
    cons_id = str(uuid.uuid4())

    # Randomize date within the last 30 minutes for a natural spread
    offset_minutes = rng.randint(0, 30)

    insert = text("""
        INSERT INTO consultations (
            id, "cabinetId", "patientId", "medecinId",
            date, diagnostic, statut,
            notes,
            is_simulation,
            "createdAt", "updatedAt"
        )
        VALUES (
            :id,
            :cabinet_id,
            :patient_id,
            :medecin_id,
            NOW() - make_interval(mins => :offset),
            :diagnostic,
            'SIGNE',
            '[SIMULATION]',
            TRUE,
            NOW(), NOW()
        )
    """)

    await db.execute(insert, {
        "id": cons_id,
        "cabinet_id": city.cabinet_id,
        "patient_id": city.patient_id,
        "medecin_id": city.medecin_id,
        "offset": offset_minutes,
        "diagnostic": diagnostic,
    })


async def generate_normal_cycle(db: AsyncSession, state: SimulationState) -> int:
    """Generate normal baseline activity for all cities. Returns rows inserted."""
    rng = state.rng
    rows = 0
    for city in CITIES:
        # Slight randomness: ±50% of base_cases
        n = max(1, int(city.base_cases * rng.uniform(0.5, 1.5)))
        for _ in range(n):
            disease = rng.choices(NORMAL_DISEASE_KEYS, weights=NORMAL_DISEASE_WEIGHTS, k=1)[0]
            diagnostic = _pick_diagnostic(rng, disease)
            await _insert_consultation(db, city, diagnostic, rng)
            rows += 1
    return rows


async def generate_scenario_flu_casablanca(db: AsyncSession, state: SimulationState) -> int:
    """
    Scenario 1 — Flu outbreak in Casablanca.
    Generates 3–5x the normal volume with flu-specific diagnostics.
    """
    rng = state.rng
    casa = next(c for c in CITIES if c.name == "Casablanca")
    multiplier = rng.uniform(3.0, 5.0)
    n = max(10, int(casa.base_cases * multiplier))
    rows = 0
    for _ in range(n):
        diagnostic = rng.choice(SCENARIO_FLU_DIAGNOSTICS)
        await _insert_consultation(db, casa, diagnostic, rng)
        rows += 1
    logger.info(f"[SIM] Scenario 1 (flu outbreak Casablanca): {rows} rows injected")
    return rows


async def generate_scenario_food_rabat(db: AsyncSession, state: SimulationState) -> int:
    """
    Scenario 2 — Food poisoning spike in Rabat.
    Short-duration spike (1–2 cycles) with food poisoning diagnostics.
    """
    rng = state.rng
    rabat = next(c for c in CITIES if c.name == "Rabat")
    n = rng.randint(12, 20)
    rows = 0
    for _ in range(n):
        diagnostic = rng.choice(SCENARIO_FOOD_DIAGNOSTICS)
        await _insert_consultation(db, rabat, diagnostic, rng)
        rows += 1
    logger.info(f"[SIM] Scenario 2 (food poisoning Rabat): {rows} rows injected")
    return rows


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------

# Thresholds (in seconds of uptime) at which anomaly scenarios fire
_SCENARIO_1_THRESHOLD = 180   # 3 minutes
_SCENARIO_2_THRESHOLD = 360   # 6 minutes


async def _simulation_loop() -> None:
    """
    Main simulation background coroutine.

    Each cycle:
    1. Generate normal activity for all cities.
    2. Check if anomaly scenario thresholds are crossed and inject them.
    3. Sleep for SIMULATION_INTERVAL_SECONDS.
    """
    logger.info(
        f"[SIM] Background loop started (interval={settings.SIMULATION_INTERVAL_SECONDS}s, "
        f"seed={settings.SIMULATION_SEED})"
    )
    state = _state

    # Bootstrap fixtures once
    async with AsyncSessionFactory() as db:
        try:
            await bootstrap_simulation_fixtures(db)
        except Exception as exc:
            logger.error(f"[SIM] Bootstrap failed: {exc}", exc_info=True)
            return

    while state.running:
        try:
            async with AsyncSessionFactory() as db:
                rows = 0

                # Normal baseline
                rows += await generate_normal_cycle(db, state)

                # Scenario 1 — Flu outbreak in Casablanca
                if not state.scenario_1_fired and state.uptime_seconds >= _SCENARIO_1_THRESHOLD:
                    rows += await generate_scenario_flu_casablanca(db, state)
                    state.scenario_1_fired = True

                # Scenario 2 — Food poisoning in Rabat (fires once, lasts 2 cycles)
                if not state.scenario_2_fired and state.uptime_seconds >= _SCENARIO_2_THRESHOLD:
                    rows += await generate_scenario_food_rabat(db, state)
                    state.scenario_2_fired = True

                await db.commit()

            state.cycles_completed += 1
            state.total_rows_inserted += rows
            logger.info(
                f"[SIM] Cycle {state.cycles_completed} complete — "
                f"{rows} rows this cycle, {state.total_rows_inserted} total"
            )

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error(f"[SIM] Cycle error: {exc}", exc_info=True)

        try:
            await asyncio.sleep(settings.SIMULATION_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            break

    logger.info("[SIM] Background loop stopped.")


# ---------------------------------------------------------------------------
# Public API — start / stop / status
# ---------------------------------------------------------------------------

async def start_simulation() -> dict:
    """
    Start the simulation background loop.
    No-op if already running.
    """
    if _state.running:
        return {"started": False, "reason": "already running", "status": _get_status()}

    _state.running = True
    _state.start_time = time.monotonic()
    _state.cycles_completed = 0
    _state.total_rows_inserted = 0
    _state.scenario_1_fired = False
    _state.scenario_2_fired = False
    # Reset RNG on each start (honours seed setting)
    _state._rng = None

    loop = asyncio.get_event_loop()
    _state.task = loop.create_task(_simulation_loop())

    logger.info("[SIM] Simulation started.")
    return {"started": True, "status": _get_status()}


async def stop_simulation() -> dict:
    """
    Stop the simulation background loop.
    No-op if not running.
    """
    if not _state.running:
        return {"stopped": False, "reason": "not running", "status": _get_status()}

    _state.running = False
    if _state.task and not _state.task.done():
        _state.task.cancel()
        try:
            await asyncio.wait_for(_state.task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    _state.task = None

    logger.info("[SIM] Simulation stopped.")
    return {"stopped": True, "status": _get_status()}


def _get_status() -> dict:
    return {
        "running": _state.running,
        "uptime_seconds": round(_state.uptime_seconds, 1),
        "cycles_completed": _state.cycles_completed,
        "total_rows_inserted": _state.total_rows_inserted,
        "scenario_flu_casablanca_fired": _state.scenario_1_fired,
        "scenario_food_rabat_fired": _state.scenario_2_fired,
        "interval_seconds": settings.SIMULATION_INTERVAL_SECONDS,
        "seed": settings.SIMULATION_SEED,
    }


def get_status() -> dict:
    return _get_status()
