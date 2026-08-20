"""
Cliente GraphQL para hablar con la API NestJS (Canal 2 y Canal 3 del contrato).

- Usa el service JWT (STATS_SERVICE_JWT), generado externamente. Este Lambda
  NUNCA genera tokens: si la API responde 401, se considera un error fatal
  de configuración (token vencido) y se corta sin reintentar.
- Cada operación (query o mutation) se ejecuta con hasta 1 reintento simple
  ante errores transitorios (timeouts, 5xx, errores de red).
"""

import json
import logging
import time
from typing import Optional

import boto3
import requests

import config

logger = logging.getLogger(__name__)

RAW_DATA_QUERY = """
query GetRawDataForWorker($userId: ID!) {
  getRawDataForWorker(userId: $userId) {
    workoutSessions {
      id
      userId
      date
      routineDayId
      status
      exercises {
        exerciseId
        series
        sets {
          reps
          weights
        }
      }
    }
    weekLogs {
      id
      userId
      startDate
      endDate
      planId
      completed
      days {
        order
        date
        isRest
        status
      }
    }
    exercises {
      id
      name
      category
      usesWeight
    }
    routinePlans {
      id
      name
      description
    }
    strengthMetrics {
      id
      exerciseKey
      oneRmKg
      measuredAt
    }
  }
}
"""

SAVE_TOP_EXERCISES_MUTATION = """
mutation SaveTopExercises($userId: ID!, $input: SaveTopExercisesInput!) {
  saveTopExercises(userId: $userId, input: $input) {
    id
    computedAt
  }
}
"""

SAVE_TOP_ROUTINES_MUTATION = """
mutation SaveTopRoutines($userId: ID!, $input: SaveTopRoutinesInput!) {
  saveTopRoutines(userId: $userId, input: $input) {
    id
    computedAt
  }
}
"""

SAVE_PERSONAL_RECORDS_MUTATION = """
mutation SavePersonalRecords($userId: ID!, $input: SavePersonalRecordsInput!) {
  savePersonalRecords(userId: $userId, input: $input) {
    id
    computedAt
  }
}
"""

SAVE_ADHERENCE_MUTATION = """
mutation SaveAdherence($userId: ID!, $input: SaveAdherenceInput!) {
  saveAdherence(userId: $userId, input: $input) {
    id
    computedAt
  }
}
"""


class GraphQLAuthError(Exception):
    """401: token de servicio vencido o inválido. No se reintenta."""


class GraphQLRequestError(Exception):
    """Error genérico de una operación GraphQL, luego de agotar reintentos."""


class GraphQLClient:
    def __init__(self):
        self._headers = {
            "Authorization": f"Bearer {config.STATS_SERVICE_JWT}",
            "Content-Type": "application/json",
        }
        self._sqs = (
            boto3.client("sqs", region_name=config.AWS_REGION)
            if config.DLQ_QUEUE_URL
            else None
        )

    # ------------------------------------------------------------------ #
    # Transporte
    # ------------------------------------------------------------------ #

    def _post(self, query: str, variables: dict) -> dict:
        response = requests.post(
            config.GRAPHQL_API_URL,
            headers=self._headers,
            json={"query": query, "variables": variables},
            timeout=config.REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code == 401:
            raise GraphQLAuthError(
                "La API respondió 401. El service JWT está vencido o es "
                "inválido. Este Lambda no genera tokens: hay que alertar."
            )

        response.raise_for_status()
        body = response.json()

        if body.get("errors"):
            raise GraphQLRequestError(json.dumps(body["errors"], ensure_ascii=False))

        return body["data"]

    def execute(self, query: str, variables: dict, *, retries: int = 1) -> dict:
        attempt = 0
        last_error: Optional[Exception] = None

        while attempt <= retries:
            try:
                return self._post(query, variables)
            except GraphQLAuthError:
                raise
            except Exception as exc:  # noqa: BLE001 - queremos capturar cualquier fallo transitorio
                last_error = exc
                attempt += 1
                if attempt <= retries:
                    logger.warning(
                        "Llamada GraphQL falló, reintentando (%s/%s): %s",
                        attempt,
                        retries,
                        exc,
                    )
                    time.sleep(1)

        assert last_error is not None
        raise GraphQLRequestError(str(last_error)) from last_error

    def send_to_dlq(self, payload: dict, reason: str) -> None:
        """
        Dead-letter manual para mutations que fallaron después del reintento.
        No bloquea el resto de la queue (implementation guide, sección 8).
        """
        if not self._sqs:
            logger.error(
                "DLQ_QUEUE_URL no configurada; se descarta el payload fallido "
                "(reason=%s): %s",
                reason,
                payload,
            )
            return
        self._sqs.send_message(
            QueueUrl=config.DLQ_QUEUE_URL,
            MessageBody=json.dumps({"reason": reason, "payload": payload}, ensure_ascii=False),
        )

    # ------------------------------------------------------------------ #
    # Canal 2 — Worker -> Lambda
    # ------------------------------------------------------------------ #

    def get_raw_data_for_worker(self, user_id: str) -> dict:
        data = self.execute(RAW_DATA_QUERY, {"userId": user_id})
        return data["getRawDataForWorker"]

    # ------------------------------------------------------------------ #
    # Canal 3 — Lambda -> NestJS
    # ------------------------------------------------------------------ #

    def save_top_exercises(self, user_id: str, input_data: dict) -> dict:
        return self.execute(
            SAVE_TOP_EXERCISES_MUTATION, {"userId": user_id, "input": input_data}
        )

    def save_top_routines(self, user_id: str, input_data: dict) -> dict:
        return self.execute(
            SAVE_TOP_ROUTINES_MUTATION, {"userId": user_id, "input": input_data}
        )

    def save_personal_records(self, user_id: str, input_data: dict) -> dict:
        return self.execute(
            SAVE_PERSONAL_RECORDS_MUTATION, {"userId": user_id, "input": input_data}
        )

    def save_adherence(self, user_id: str, input_data: dict) -> dict:
        return self.execute(
            SAVE_ADHERENCE_MUTATION, {"userId": user_id, "input": input_data}
        )
