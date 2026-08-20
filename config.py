"""
Configuración centralizada del Stats Lambda.

Todas las variables de entorno requeridas/opcionales según el contrato
(Stats Module — Contract, sección "Environment Variables") se leen acá.
"""

import os

# --- Requeridas ---
GRAPHQL_API_URL = os.environ["GRAPHQL_API_URL"]
STATS_SERVICE_JWT = os.environ["STATS_SERVICE_JWT"]

# --- Opcionales ---
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
REQUEST_TIMEOUT_SECONDS = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "15"))

# Cola opcional para dead-lettering manual de mutations que fallan
# después de agotar reintentos (ver sección 8 del implementation guide).
DLQ_QUEUE_URL = os.environ.get("DLQ_QUEUE_URL")

# --- Valores de estado (según "Reference" al final del implementation guide) ---
WORKOUT_STATUS_COMPLETED = "completed"

WEEK_DAY_STATUS_PENDING = "pending"
WEEK_DAY_STATUS_COMPLETE = "complete"
WEEK_DAY_STATUS_SKIPPED = "skipped"

TOP_N = 5

# Tabla fija de "important exercises" (sección 5.3 del implementation guide).
# key = exerciseKey (usado en strengthMetrics) -> nombre en español (usado
# para matchear contra el catálogo de exercises que devuelve la API).
IMPORTANT_EXERCISES = {
    "squat": "Sentadilla",
    "bench_press": "Press de banca plano",
    "incline_bench": "Press de banca inclinado",
    "overhead_press": "Press militar",
    "barbell_row": "Remo con barra",
    "romanian_deadlift": "Peso muerto rumano",
    "hip_thrust": "Hip thrust",
}

IMPORTANT_EXERCISE_CATEGORIES = {
    "squat": "legs_front",
    "bench_press": "chest",
    "incline_bench": "chest",
    "overhead_press": "shoulders",
    "barbell_row": "back",
    "romanian_deadlift": "legs_posterior",
    "hip_thrust": "legs_posterior",
}
