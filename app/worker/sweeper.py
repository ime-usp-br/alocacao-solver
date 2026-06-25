"""Sweeper de jobs órfãos.

Processo independente que detecta jobs cujo work-horse morreu abruptamente
(SIGKILL/OOM) e notifica o Laravel via webhook de erro.

Mecanismo:
1. ``process_job`` registra ``job_meta:{job_id}`` e mantém
   ``job_alive:{job_id}`` renovada por uma thread heartbeat.
2. Se o work-horse for assassinado, a thread morre e ``job_alive`` expira.
3. O sweeper escaneia ``job_meta:*``, e para cada chave onde
   ``job_alive`` já expirou e não há ``result:{job_id}``, dispara o
   webhook de erro e limpa a chave ``job_meta``.

Como roda em processo/container separado, sobrevive à morte do work-horse.
"""

from __future__ import annotations

import json
import logging
import os
import time

import redis

from app.api.schemas import SolveErrorResponse
from app.worker.processor import _save_result_to_redis, _send_webhook

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SWEEP_INTERVAL_SECONDS = int(os.getenv("SWEEP_INTERVAL_SECONDS", "30"))

logger = logging.getLogger(__name__)


def _sweep_once(redis_conn: redis.Redis) -> int:
    """
    Escaneia ``job_meta:*`` e notifica jobs órfãos.

    Retorna o número de jobs órfãos detectados.
    """
    orphan_count = 0
    cursor = 0
    meta_prefix = "job_meta:"

    while True:
        cursor, keys = redis_conn.scan(
            cursor=cursor, match=f"{meta_prefix}*", count=100
        )
        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            job_id = key_str[len(meta_prefix) :]

            # Job ainda vivo? (heartbeat presente)
            if redis_conn.exists(f"job_alive:{job_id}"):
                continue

            # Já tem resultado? (try/except do process_job funcionou)
            if redis_conn.exists(f"result:{job_id}"):
                redis_conn.delete(key)
                continue

            # Job órfão: work-horse morreu sem deixar resultado.
            orphan_count += 1
            _handle_orphan(redis_conn, job_id, key)

        if cursor == 0:
            break

    return orphan_count


def _handle_orphan(redis_conn: redis.Redis, job_id: str, meta_key: bytes | str) -> None:
    """Notifica o Laravel sobre um job órfão e limpa a chave meta."""
    raw_meta = redis_conn.get(meta_key)
    webhook_url = ""
    if raw_meta:
        try:
            meta = json.loads(raw_meta)
            webhook_url = str(meta.get("webhook_url", ""))
        except json.JSONDecodeError, TypeError:
            pass

    error_payload = SolveErrorResponse(
        job_id=job_id,
        status="error",
        message=(
            "O processo de otimização foi abortado pelo sistema "
            "(provável estouro de memória / OOM kill). "
            "A operação não foi concluída."
        ),
        trace="Work-horse terminated unexpectedly (SIGKILL/OOM).",
    ).model_dump(mode="json")

    try:
        _save_result_to_redis(redis_conn, job_id, error_payload)
    except Exception:
        logger.exception(
            "Sweeper: falha ao persistir erro no Redis para job %s.", job_id
        )

    if webhook_url:
        try:
            _send_webhook(webhook_url, error_payload)
            logger.warning("Sweeper: job órfão %s notificado via webhook.", job_id)
        except Exception:
            logger.exception("Sweeper: webhook falhou para job órfão %s.", job_id)

    redis_conn.delete(meta_key)


def main() -> None:
    """Loop principal do sweeper. Roda indefinidamente."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s sweeper: %(levelname)s %(message)s",
    )
    logger.info("Sweeper iniciado (intervalo=%ss).", SWEEP_INTERVAL_SECONDS)

    redis_conn = redis.from_url(REDIS_URL)

    while True:
        try:
            orphans = _sweep_once(redis_conn)
            if orphans:
                logger.warning("Sweeper: %d job(s) órfão(s) detectado(s).", orphans)
        except Exception:
            logger.exception("Sweeper: erro no ciclo de varredura.")

        time.sleep(SWEEP_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
