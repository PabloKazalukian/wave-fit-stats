# Stats Lambda

Implementación en Python del Lambda descrito en `Stats Module — Contract` y
`Stats Lambda — Implementation Guide`.

## Estructura

```
stats_lambda/
├── lambda_function.py     # handler (entry point)
├── graphql_client.py      # auth + query getRawDataForWorker + 4 mutations
├── stats_calculator.py    # cómputo de las 4 estadísticas
├── config.py               # env vars y constantes (tabla de important exercises, etc.)
├── requirements.txt
└── example_sqs_event.json  # evento de prueba
```

## Variables de entorno

| Variable | Requerida | Descripción |
|---|---|---|
| `GRAPHQL_API_URL` | Sí | URL completa del endpoint GraphQL, ej. `https://wave-fit-api.onrender.com/graphql` |
| `STATS_SERVICE_JWT` | Sí | Bearer token de servicio (guardado en Secrets Manager, generado fuera del Lambda) |
| `AWS_REGION` | No | Default `us-east-1` |
| `REQUEST_TIMEOUT_SECONDS` | No | Default `15` |
| `DLQ_QUEUE_URL` | No | Si se define, las mutations de guardado que fallan tras el reintento se mandan acá en vez de perderse |

## Flujo

1. El event source mapping de SQS invoca `lambda_function.handler(event, context)`.
2. Por cada `record` del batch: se parsea `userId` del body (es el único dato que se necesita del mensaje).
3. Se llama `getRawDataForWorker(userId)`.
4. Se calculan las 4 estadísticas (`stats_calculator.py`).
5. Se guardan con las 4 mutations (`saveTopExercises`, `saveTopRoutines`, `savePersonalRecords`, `saveAdherence`), usando siempre el mismo `computedAt`.
6. Si `getRawDataForWorker` devuelve todo vacío, igual se guardan las 4 mutations con arrays vacíos (limpia stats viejas, según sección 8 del implementation guide).

### Manejo de errores

- **401 de la API** → error fatal (`GraphQLAuthError`). No se reintenta (el token no se regenera en el Lambda). Se corta el procesamiento del batch y el mensaje se reporta como fallido para que SQS lo reintente más tarde (una vez rotado el token).
- **Otros errores de una query/mutation** → 1 reintento automático con backoff de 1s. Si vuelve a fallar:
  - En `getRawDataForWorker`: se propaga y el mensaje entero se marca como fallido (partial batch response).
  - En las mutations de guardado: se loggea y se manda a `DLQ_QUEUE_URL` (si está configurada) en vez de bloquear el resto del batch — así una mutation que falla no te frena las otras 3.
- El handler devuelve `{"batchItemFailures": [...]}` (partial batch response de SQS), así que hay que habilitar `ReportBatchItemFailures` en el event source mapping.

## Supuestos tomados (por ambigüedad en la spec)

- **`status` de WorkoutSession**: el contrato define el campo como `String!` sin enum explícito. Se asumió `"completed"` como el valor que marca una sesión terminada (usado para filtrar en Personal Records). Está centralizado en `config.WORKOUT_STATUS_COMPLETED` — cambiarlo ahí si el valor real es otro (ej. `"COMPLETED"` o `"finished"`).
- **`bestVolume` en Personal Records**: la guía dice literalmente *"max (weight × reps × series) in a single session"*. Como `series` es un campo a nivel de la performance del ejercicio (no por set), se interpretó como: para cada `set` dentro de esa performance, `volumen = set.weights × set.reps × performance.series`, y se toma el máximo entre todos los sets de todas las sesiones. Si la intención real era otra (ej. sumar los sets y multiplicar una sola vez por `series`), es un cambio de una línea en `stats_calculator.compute_personal_records`.
- **Matching de `IMPORTANT_EXERCISES`**: se matchea por nombre normalizado (sin acentos, minúsculas) entre la tabla fija del implementation guide y `exercises[].name` que devuelve la API. Si el usuario no tiene ese ejercicio en su catálogo, se omite (no rompe el cómputo).
- **Empates en Top Exercises**: se desempata por volumen total descendente (no está especificado en la guía, pero evita un orden arbitrario).

## Deploy

```bash
pip install -r requirements.txt -t package/ --break-system-packages
cp *.py package/
cd package && zip -r ../stats-lambda.zip . && cd ..
```

Handler a configurar en AWS: `lambda_function.handler`.

## Test local

```bash
export GRAPHQL_API_URL="https://tu-api/graphql"
export STATS_SERVICE_JWT="tu-token"
python3 -c "
import json, lambda_function
event = json.load(open('example_sqs_event.json'))
print(lambda_function.handler(event, None))
"
```

(Esto va a intentar pegarle a `GRAPHQL_API_URL` de verdad — para un test 100% offline, mockeá `GraphQLClient` o corré sólo `stats_calculator.py` con datos sintéticos.)
