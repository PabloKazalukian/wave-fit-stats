"""
Entry point del Stats Lambda.

Flujo (implementation guide, secciones 1-6):
  1. Recibe un batch de mensajes SQS, cada uno con {userId, triggerType,
     entityId, timestamp}.
  2. Para cada userId: pide la raw data vía getRawDataForWorker.
  3. Calcula las 4 estadísticas.
  4. Guarda cada una con su mutation correspondiente.

No usa el `triggerType` ni el `entityId` para nada más que logging: el
contrato dice explícitamente que el único input necesario es `userId`
(sección 1 del implementation guide).

Reporta fallas parciales de batch (`batchItemFailures`) para que SQS
reintente sólo los mensajes que fallaron, sin bloquear el resto del batch.
Las mutations de guardado, además, tienen su propio mecanismo de
dead-letter manual (ver graphql_client.send_to_dlq).
"""

import json
import logging
from datetime import datetime, timezone

import stats_calculator as calc
from graphql_client import GraphQLAuthError, GraphQLClient, GraphQLRequestError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _now_iso() -> str:
    """ISO 8601 con milisegundos y sufijo Z, como en los ejemplos del contrato."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _save_stat(client: GraphQLClient, user_id: str, name: str, save_fn, payload: dict) -> None:
    try:
        save_fn(user_id, payload)
        logger.info("%s guardado OK para userId=%s", name, user_id)
    except GraphQLAuthError:
        # Token vencido: no tiene sentido reintentar nada más de este batch.
        raise
    except GraphQLRequestError as exc:
        logger.error("%s falló (tras reintento) para userId=%s: %s", name, user_id, exc)
        client.send_to_dlq(
            {"userId": user_id, "mutation": name, "input": payload}, reason=str(exc)
        )


def process_user(client: GraphQLClient, user_id: str) -> None:
    logger.info("Procesando stats para userId=%s", user_id)

    raw = client.get_raw_data_for_worker(user_id)
    computed_at = _now_iso()

    # Nota (error handling, sección 8): si no hay workoutSessions ni weekLogs,
    # igual se computan (van a dar listas vacías) y se guardan las 4
    # mutations con arrays vacíos, para limpiar stats viejas.
    top_exercises = calc.compute_top_exercises(raw)
    top_routines = calc.compute_top_routines(raw)
    personal_records = calc.compute_personal_records(raw)
    adherence = calc.compute_adherence(raw)

    _save_stat(
        client,
        user_id,
        "saveTopExercises",
        client.save_top_exercises,
        {"computedAt": computed_at, "exercises": top_exercises},
    )
    _save_stat(
        client,
        user_id,
        "saveTopRoutines",
        client.save_top_routines,
        {"computedAt": computed_at, "routines": top_routines},
    )
    _save_stat(
        client,
        user_id,
        "savePersonalRecords",
        client.save_personal_records,
        {"computedAt": computed_at, "records": personal_records},
    )
    _save_stat(
        client,
        user_id,
        "saveAdherence",
        client.save_adherence,
        {"computedAt": computed_at, "weeks": adherence},
    )


def handler(event, context):  # noqa: D401 - firma estándar de Lambda
    client = GraphQLClient()
    batch_item_failures = []

    for record in event.get("Records", []):
        message_id = record.get("messageId", "unknown")

        try:
            body = json.loads(record["body"])
            user_id = body["userId"]
            trigger_type = body.get("triggerType")
            entity_id = body.get("entityId")
        except (KeyError, json.JSONDecodeError) as exc:
            # Mensaje malformado: no tiene sentido reintentarlo, se descarta.
            logger.error("Mensaje SQS malformado (messageId=%s): %s", message_id, exc)
            continue

        logger.info(
            "SQS message recibido: userId=%s triggerType=%s entityId=%s",
            user_id,
            trigger_type,
            entity_id,
        )

        try:
            process_user(client, user_id)
        except GraphQLAuthError as exc:
            # Error de configuración (token vencido): se corta el batch
            # completo y se marca este mensaje (y los que queden) para
            # reintento, ya que reintentar no va a servir hasta que se
            # rote el token, pero tampoco queremos perder el mensaje.
            logger.error("Deteniendo procesamiento por error de auth: %s", exc)
            batch_item_failures.append({"itemIdentifier": message_id})
            break
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Error no manejado procesando userId=%s (messageId=%s): %s",
                user_id,
                message_id,
                exc,
            )
            batch_item_failures.append({"itemIdentifier": message_id})

    # Formato de "partial batch response" para SQS event source mappings
    # con reportBatchItemFailures habilitado.
    return {"batchItemFailures": batch_item_failures}
