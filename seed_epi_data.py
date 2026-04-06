"""
Idempotent script to seed epidemiology mock data.
Creates ONE virtual cabinet per city (named "Epi - <City>") with ON CONFLICT DO NOTHING,
so re-running is safe. Deletes only its own previous simulation consultations before re-inserting.

Run from Rahadoc/backend:  python seed_epi_data.py
"""
import asyncio
import random
import uuid
from datetime import datetime, timedelta

from sqlalchemy import text
from app.db.session import AsyncSessionLocal

CITIES = [
    ("Casablanca", 33.5731, -7.5898),
    ("Rabat",      33.9716, -6.8498),
    ("Marrakech",  31.6295, -8.0088),
    ("Tanger",     35.7595, -5.8340),
    ("Fes",        34.0181, -5.0078),
]

DIAGNOSTICS_GRIPPE = [
    "Grippe saisonniere", "Syndrome grippal avec fievre",
    "Etat grippal", "Influenza type A",
]
DIAGNOSTICS_INTOX = [
    "Intoxication alimentaire", "Toxi-infection alimentaire collective",
    "Gastro-enterite aigue", "Gastroenterite virale",
]
DIAGNOSTICS_GENERAL = [
    "Angine bacterienne", "Pharyngite aigue", "Bronchite aigue",
    "Pneumonie communautaire", "Conjonctivite virale", "Varicelle",
    "COVID-19 confirme", "Grippe saisonniere", "Gastroenterite virale",
    "Angine streptococcique", "Bronchiolite",
]


async def seed():
    async with AsyncSessionLocal() as db:
        # ── Reuse existing patient/user from the real cabinet ─────────────
        row = (await db.execute(text("""
            SELECT c.id AS cab_id, u.id AS user_id, p.id AS pat_id
            FROM cabinets c
            JOIN users u ON u."cabinetId" = c.id
            JOIN patients p ON p."cabinetId" = c.id
            LIMIT 1
        """))).mappings().fetchone()

        if not row:
            print("ERROR: No cabinet/user/patient found. Run the main seed first.")
            return

        base_cab_id  = row["cab_id"]
        base_user_id = row["user_id"]
        base_pat_id  = row["pat_id"]
        print(f"Using cabinet={base_cab_id[:8]}, user={base_user_id[:8]}, patient={base_pat_id[:8]}")

        # ── Upsert one virtual cabinet per city (idempotent) ──────────────
        cabinet_ids = {}
        for city, lat, lng in CITIES:
            cab_nom = f"Epi - {city}"
            # Check if already exists
            existing = (await db.execute(text(
                "SELECT id FROM cabinets WHERE nom = :nom"
            ), {"nom": cab_nom})).fetchone()

            if existing:
                cabinet_ids[city] = existing[0]
                print(f"  Cabinet '{cab_nom}' already exists ({existing[0][:8]})")
            else:
                cab_id = str(uuid.uuid4())
                cabinet_ids[city] = cab_id
                await db.execute(text("""
                    INSERT INTO cabinets (id, nom, ville, latitude, longitude, "createdAt", "updatedAt")
                    VALUES (:id, :nom, :ville, :lat, :lng, NOW(), NOW())
                """), {"id": cab_id, "nom": cab_nom, "ville": city, "lat": lat, "lng": lng})
                print(f"  Created cabinet '{cab_nom}' ({cab_id[:8]})")

        await db.commit()

        # ── Delete ONLY previous simulation consultations for these cabinets ──
        cab_ids_list = "'" + "','".join(cabinet_ids.values()) + "'"
        deleted = (await db.execute(text(f"""
            DELETE FROM consultations
            WHERE "cabinetId" IN ({cab_ids_list})
              AND is_simulation = true
            RETURNING id
        """))).fetchall()
        if deleted:
            print(f"Removed {len(deleted)} old simulation consultations")
        await db.commit()

        # ── Insert fresh consultations over last 14 days ──────────────────
        total = 0
        for day_offset in range(14):
            day = datetime.utcnow() - timedelta(days=day_offset)

            for city, lat, lng in CITIES:
                if city == "Casablanca":
                    n = random.randint(14, 22)
                    pool = DIAGNOSTICS_GRIPPE * 5 + DIAGNOSTICS_GENERAL
                elif city == "Rabat":
                    n = random.randint(3, 6)
                    pool = DIAGNOSTICS_GENERAL
                elif city == "Marrakech" and day_offset <= 5:
                    n = random.randint(8, 12)
                    pool = DIAGNOSTICS_INTOX * 5 + DIAGNOSTICS_GENERAL
                else:
                    n = random.randint(3, 7)
                    pool = DIAGNOSTICS_GENERAL

                for _ in range(n):
                    con_id = str(uuid.uuid4())
                    consult_dt = day - timedelta(
                        hours=random.randint(0, 23),
                        minutes=random.randint(0, 59),
                    )
                    diag = random.choice(pool)
                    await db.execute(text("""
                        INSERT INTO consultations (
                            id, "cabinetId", "patientId", "medecinId",
                            date, diagnostic, statut, is_simulation,
                            "createdAt", "updatedAt"
                        )
                        VALUES (
                            :id, :cab, :pat, :med,
                            :date, :diag,
                            CAST('SIGNE' AS "StatutConsultation"), true,
                            NOW(), NOW()
                        )
                        ON CONFLICT DO NOTHING
                    """), {
                        "id": con_id,
                        "cab": cabinet_ids[city],
                        "pat": base_pat_id,
                        "med": base_user_id,
                        "date": consult_dt,
                        "diag": diag,
                    })
                    total += 1

        await db.commit()
        print(f"Inserted {total} simulation consultations (14 days)")

        # ── Quick verification ────────────────────────────────────────────
        result = await db.execute(text("""
            SELECT cab.ville, COUNT(DISTINCT c.id) AS cases
            FROM consultations c
            JOIN cabinets cab ON c."cabinetId" = cab.id
            WHERE c.statut = 'SIGNE'
              AND cab.ville IS NOT NULL
              AND cab.latitude IS NOT NULL
              AND c.date >= NOW() - INTERVAL '30 days'
              AND c.is_simulation = true
            GROUP BY cab.ville
            ORDER BY cases DESC
        """))
        print("\nHeatmap preview:")
        for r in result:
            print(f"  {r[0]:15} -> {r[1]} cases")


asyncio.run(seed())
