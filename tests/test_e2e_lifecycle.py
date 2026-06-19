"""Testes E2E completos do ciclo de vida: Laravel -> Python API -> RQ -> Solver -> Redis -> Webhook."""

from __future__ import annotations

import json
from typing import Any, Generator
from unittest.mock import patch

import fakeredis
import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response
from rq.worker import SimpleWorker

from app.api.dependencies import get_redis_connection
from app.api.routes import app

WEBHOOK_URL = "http://laravel-app/api/webhooks/allocation-result"

# Payload ridiculamente pequeno para garantir sub-segundo no CP-SAT.
FULL_PAYLOAD: dict[str, Any] = {
    "meta": {
        "version": "1.0.0",
        "school_term_id": 42,
        "webhook_url": WEBHOOK_URL,
        "progress_webhook_url": "http://laravel-app/api/webhooks/allocation-progress",
    },
    "config": {
        "strict_capacity": False,
        "block_b_restriction_for_pos": True,
        "block_a_restriction_for_freshmen": False,
        "undergrad_in_block_a_penalty": 0.0,
        "pos_in_block_b_penalty": 0.0,
        "waste_penalty": 1.5,
        "claustrophobia_penalty": 0.0,
        "comfort_zone_min_percent": 10.0,
        "comfort_zone_max_percent": 25.0,
        "split_class_penalty": 0.0,
        "split_cohort_penalty": 0.0,
        "unassigned_penalty": 1000.0,
        "time_limit_seconds": 5,
    },
    "timeslots": [
        {
            "id": 0,
            "label": "seg_0800_0940",
            "day": "seg",
            "start": "08:00",
            "end": "09:40",
        },
    ],
    "rooms": [
        {"id": 1, "name": "B09", "capacity": 40},
    ],
    "groups": [
        {
            "id": 101,
            "type": "single",
            "class_ids": [101],
            "coddis": "MAC0110",
            "tiptur": "Graduacao",
            "demand": 30,
            "is_freshmen": False,
            "timeslot_ids": [0],
            "preassigned_room_id": None,
            "same_room_cohort": None,
        },
    ],
}


@pytest.fixture
def e2e_redis() -> Generator[fakeredis.FakeRedis, None, None]:
    """Isola o Redis em memória para todo o ciclo E2E."""
    conn = fakeredis.FakeRedis()
    app.dependency_overrides[get_redis_connection] = lambda: conn
    yield conn
    app.dependency_overrides.clear()


@pytest.fixture
def e2e_client(e2e_redis: fakeredis.FakeRedis) -> TestClient:
    """TestClient do FastAPI compartilhando o mesmo Redis fake."""
    return TestClient(app)


@pytest.fixture
def e2e_worker(e2e_redis: fakeredis.FakeRedis) -> SimpleWorker:
    """Worker RQ síncrono (burst) que processa jobs sem fork de processo."""
    return SimpleWorker(queues=["default"], connection=e2e_redis)


class TestE2ELifecycle:
    def test_e2e_happy_path(
        self,
        e2e_client: TestClient,
        e2e_worker: SimpleWorker,
        e2e_redis: fakeredis.FakeRedis,
    ) -> None:
        """Fluxo completo: dispatch -> worker -> Redis -> webhook de sucesso."""
        with respx.mock:
            route = respx.post(WEBHOOK_URL).mock(return_value=Response(200))
            respx.post(FULL_PAYLOAD["meta"]["progress_webhook_url"]).mock(
                return_value=Response(200)
            )

            # 1. Dispatch
            response = e2e_client.post("/api/v1/solve", json=FULL_PAYLOAD)
            assert response.status_code == 202
            data = response.json()
            job_id = data["job_id"]
            assert data["status"] == "queued"

            # 2. Antes do worker: ainda processando
            response = e2e_client.get(f"/api/v1/jobs/{job_id}/result")
            assert response.status_code == 425
            assert response.headers.get("retry-after") == "10"

            # 3. Executa worker síncrono
            with patch("app.worker.tasks.redis.from_url", return_value=e2e_redis):
                e2e_worker.work(burst=True)

            # 4. Resultado disponível via API
            response = e2e_client.get(f"/api/v1/jobs/{job_id}/result")
            assert response.status_code == 200
            result = response.json()
            assert result["job_id"] == job_id
            assert result["status"] in ("optimal", "feasible")
            assert "allocations" in result
            assert "solve_time_seconds" in result

            # 5. Redis persiste o resultado com TTL adequado
            raw = e2e_redis.get(f"result:{job_id}")
            assert raw is not None
            redis_result = json.loads(raw)
            assert redis_result == result
            ttl = e2e_redis.ttl(f"result:{job_id}")
            assert 0 < ttl <= 86400

            # 6. Progresso finalizado
            progress_raw = e2e_redis.get(f"progress:job_{job_id}")
            assert progress_raw is not None
            assert json.loads(progress_raw)["progress"] == 100.0

            # 7. Webhook disparado exatamente 1x com payload correto
            assert route.called
            assert route.call_count == 1
            webhook_body = json.loads(route.calls.last.request.content)
            assert webhook_body == result

    def test_e2e_result_before_worker_runs(
        self,
        e2e_client: TestClient,
        e2e_redis: fakeredis.FakeRedis,
    ) -> None:
        """Rota de resultado deve retornar 425 enquanto o job está na fila."""
        response = e2e_client.post("/api/v1/solve", json=FULL_PAYLOAD)
        job_id = response.json()["job_id"]

        response = e2e_client.get(f"/api/v1/jobs/{job_id}/result")
        assert response.status_code == 425
        assert "processando" in response.json()["detail"]
        assert response.headers.get("retry-after") == "10"

    def test_e2e_webhook_error_still_saves_redis(
        self,
        e2e_client: TestClient,
        e2e_worker: SimpleWorker,
        e2e_redis: fakeredis.FakeRedis,
    ) -> None:
        """Falha no webhook (HTTP 500) não deve impedir a persistência no Redis."""
        with respx.mock:
            route = respx.post(WEBHOOK_URL).mock(return_value=Response(500))
            respx.post(FULL_PAYLOAD["meta"]["progress_webhook_url"]).mock(
                return_value=Response(200)
            )

            response = e2e_client.post("/api/v1/solve", json=FULL_PAYLOAD)
            job_id = response.json()["job_id"]

            with patch("app.worker.tasks.redis.from_url", return_value=e2e_redis):
                e2e_worker.work(burst=True)

            # Redis deve conter o resultado mesmo com webhook falhando
            raw = e2e_redis.get(f"result:{job_id}")
            assert raw is not None
            result = json.loads(raw)
            assert result["job_id"] == job_id
            assert result["status"] in ("optimal", "feasible")

            # Webhook foi tentado, mas recebeu 500
            assert route.called
            assert route.call_count == 1

    def test_e2e_soft_stop_during_solve(
        self,
        e2e_client: TestClient,
        e2e_worker: SimpleWorker,
        e2e_redis: fakeredis.FakeRedis,
    ) -> None:
        """Soft Stop: grava chave no Redis antes do worker iniciar e valida interrupção."""
        with respx.mock:
            route = respx.post(WEBHOOK_URL).mock(return_value=Response(200))
            respx.post(FULL_PAYLOAD["meta"]["progress_webhook_url"]).mock(
                return_value=Response(200)
            )

            # 1. Enfileira job
            response = e2e_client.post("/api/v1/solve", json=FULL_PAYLOAD)
            job_id = response.json()["job_id"]

            # 2. Grava sinal de parada no Redis ANTES de rodar o worker
            stop_response = e2e_client.post(f"/api/v1/jobs/{job_id}/stop")
            assert stop_response.status_code == 200
            assert e2e_redis.get(f"stop_job:{job_id}") == b"true"

            # 3. Inicia worker; o callback lerá a chave de stop na 1ª solução
            with patch("app.worker.tasks.redis.from_url", return_value=e2e_redis):
                e2e_worker.work(burst=True)

            # 4. Resultado deve indicar que foi interrompido
            response = e2e_client.get(f"/api/v1/jobs/{job_id}/result")
            assert response.status_code == 200
            result = response.json()
            assert result["job_id"] == job_id
            assert result["status"] == "stopped"

            # 5. Webhook disparado com a solução parcial
            assert route.called
            assert route.call_count == 1
            webhook_body = json.loads(route.calls.last.request.content)
            assert webhook_body == result
