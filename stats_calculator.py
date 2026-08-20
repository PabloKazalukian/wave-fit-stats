"""
Cálculo de las 4 estadísticas descritas en la sección 5 del
"Stats Lambda — Implementation Guide":

  5.1 Top 5 Exercises
  5.2 Top 5 Routines
  5.3 Personal Records
  5.4 Adherence

Cada función toma el diccionario `raw` devuelto por
`getRawDataForWorker` y devuelve una lista de dicts lista para meter
en el `input` de la mutation correspondiente (sin `computedAt`, que
se agrega en el handler).
"""

import unicodedata
from typing import Optional

import config


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #


def _normalize(text: str) -> str:
    """minúsculas + sin acentos, para matchear nombres de ejercicios."""
    text = text.strip().lower()
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn"
    )


def _brzycki_one_rm(weight: Optional[float], reps: Optional[float]) -> Optional[float]:
    """1RM estimado con la fórmula de Brzycki. Válida para reps entre 1 y 36."""
    if weight is None or reps is None:
        return None
    if reps < 1 or reps > 36:
        return None
    return weight * (36 / (37 - reps))


# ---------------------------------------------------------------------- #
# 5.1 Top Exercises
# ---------------------------------------------------------------------- #


def compute_top_exercises(raw: dict) -> list[dict]:
    sessions = raw.get("workoutSessions", [])
    exercises_catalog = {ex["id"]: ex for ex in raw.get("exercises", [])}

    counts: dict[str, int] = {}
    volumes: dict[str, float] = {}

    for session in sessions:
        for perf in session.get("exercises", []):
            ex_id = perf["exerciseId"]
            counts[ex_id] = counts.get(ex_id, 0) + 1

            session_volume = 0.0
            for s in perf.get("sets", []):
                weight = s.get("weights")
                reps = s.get("reps")
                if weight is None or reps is None:
                    continue
                session_volume += weight * reps

            volumes[ex_id] = volumes.get(ex_id, 0.0) + session_volume

    # Orden por cantidad de sesiones desc; empate se resuelve por volumen desc.
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -volumes.get(kv[0], 0.0)))
    top = ranked[: config.TOP_N]

    result = []
    for rank, (ex_id, total_sessions) in enumerate(top, start=1):
        catalog_entry = exercises_catalog.get(ex_id, {})
        total_volume = round(volumes.get(ex_id, 0.0), 2)
        avg_volume = round(total_volume / total_sessions, 2) if total_sessions else 0.0

        result.append(
            {
                "rank": rank,
                "exerciseId": ex_id,
                "name": catalog_entry.get("name", "Desconocido"),
                "category": catalog_entry.get("category", "unknown"),
                "totalSessions": total_sessions,
                "totalVolume": total_volume,
                "avgVolumePerSession": avg_volume,
            }
        )
    return result


# ---------------------------------------------------------------------- #
# 5.2 Top Routines
# ---------------------------------------------------------------------- #


def compute_top_routines(raw: dict) -> list[dict]:
    week_logs = raw.get("weekLogs", [])
    plans_catalog = {p["id"]: p for p in raw.get("routinePlans", [])}

    counts: dict[str, int] = {}
    total_days: dict[str, int] = {}
    completed_days: dict[str, int] = {}

    for wl in week_logs:
        plan_id = wl.get("planId")
        if not plan_id:
            continue

        counts[plan_id] = counts.get(plan_id, 0) + 1
        total_days[plan_id] = total_days.get(plan_id, 0) + 7

        completed = sum(
            1
            for d in wl.get("days", [])
            if d.get("status") == config.WEEK_DAY_STATUS_COMPLETE
        )
        completed_days[plan_id] = completed_days.get(plan_id, 0) + completed

    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    top = ranked[: config.TOP_N]

    result = []
    for rank, (plan_id, total_weeks) in enumerate(top, start=1):
        catalog_entry = plans_catalog.get(plan_id, {})
        td = total_days.get(plan_id, 0)
        cd = completed_days.get(plan_id, 0)
        adherence_rate = round((cd / td) * 100, 2) if td else 0.0

        result.append(
            {
                "rank": rank,
                "planId": plan_id,
                "name": catalog_entry.get("name", "Desconocido"),
                "totalWeeks": total_weeks,
                "totalSessions": cd,
                "adherenceRate": adherence_rate,
            }
        )
    return result


# ---------------------------------------------------------------------- #
# 5.3 Personal Records
# ---------------------------------------------------------------------- #


def compute_personal_records(raw: dict) -> list[dict]:
    sessions = raw.get("workoutSessions", [])
    exercises_catalog = raw.get("exercises", [])
    strength_metrics = raw.get("strengthMetrics", [])

    # Catálogo de ejercicios del usuario, indexado por nombre normalizado,
    # para matchear contra la tabla fija IMPORTANT_EXERCISES.
    name_to_catalog = {_normalize(ex["name"]): ex for ex in exercises_catalog}

    # Último 1RM conocido por exerciseKey (para previousOneRm).
    latest_one_rm: dict[str, float] = {}
    latest_measured_at: dict[str, str] = {}
    for m in strength_metrics:
        key = m["exerciseKey"]
        measured_at = m["measuredAt"]
        if key not in latest_measured_at or measured_at > latest_measured_at[key]:
            latest_measured_at[key] = measured_at
            latest_one_rm[key] = m["oneRmKg"]

    result = []

    for exercise_key, spanish_name in config.IMPORTANT_EXERCISES.items():
        catalog_entry = name_to_catalog.get(_normalize(spanish_name))
        if not catalog_entry:
            # El usuario no tiene este ejercicio en su catálogo -> se omite.
            continue

        exercise_id = catalog_entry["id"]

        best_weight = None
        best_reps = None
        best_one_rm = None
        best_volume = None
        best_volume_date = None

        for session in sessions:
            if session.get("status") != config.WORKOUT_STATUS_COMPLETED:
                continue

            for perf in session.get("exercises", []):
                if perf["exerciseId"] != exercise_id:
                    continue

                # "series" es el número de series de ESTA performance dentro
                # de la sesión (campo del contrato). Se usa como multiplicador
                # de volumen según la fórmula "weight × reps × series" del
                # implementation guide (5.3).
                series = perf.get("series") or 1

                for s in perf.get("sets", []):
                    weight = s.get("weights")
                    reps = s.get("reps")
                    if not weight:
                        continue

                    if best_weight is None or weight > best_weight:
                        best_weight = weight
                        best_reps = reps

                    one_rm = _brzycki_one_rm(weight, reps)
                    if one_rm is not None and (best_one_rm is None or one_rm > best_one_rm):
                        best_one_rm = one_rm

                    set_volume = weight * (reps or 0) * series
                    if best_volume is None or set_volume > best_volume:
                        best_volume = set_volume
                        best_volume_date = session.get("date")

        if best_weight is None:
            # Nunca se registró con peso -> no hay PR que reportar.
            continue

        result.append(
            {
                "exerciseId": exercise_id,
                "exerciseName": catalog_entry["name"],
                "category": catalog_entry.get(
                    "category", config.IMPORTANT_EXERCISE_CATEGORIES.get(exercise_key, "unknown")
                ),
                "oneRmEstimated": round(best_one_rm, 2) if best_one_rm else 0.0,
                "bestWeight": best_weight,
                "bestReps": best_reps,
                "bestVolume": round(best_volume, 2) if best_volume else 0.0,
                "achievedAt": best_volume_date,
                "previousOneRm": latest_one_rm.get(exercise_key),
            }
        )

    return result


# ---------------------------------------------------------------------- #
# 5.4 Adherence
# ---------------------------------------------------------------------- #


def compute_adherence(raw: dict) -> list[dict]:
    week_logs = raw.get("weekLogs", [])
    result = []

    for wl in week_logs:
        days = wl.get("days", [])
        total = len(days) or 7
        completed = sum(1 for d in days if d.get("status") == config.WEEK_DAY_STATUS_COMPLETE)
        skipped = sum(1 for d in days if d.get("status") == config.WEEK_DAY_STATUS_SKIPPED)
        pending = sum(1 for d in days if d.get("status") == config.WEEK_DAY_STATUS_PENDING)

        if completed == 0 and skipped == 0:
            # Todos los días siguen "pending" -> se omite (guide, 5.4).
            continue

        result.append(
            {
                "weekStartDate": wl["startDate"],
                "totalDays": total,
                "completedDays": completed,
                "skippedDays": skipped,
                "pendingDays": pending,
                "adherencePercent": round((completed / total) * 100, 2),
            }
        )
    return result
