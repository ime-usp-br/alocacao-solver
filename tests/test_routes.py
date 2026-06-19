import json
from typing import Generator

import fakeredis
import pytest
from fastapi.testclient import TestClient
from rq import Queue
from rq.job import Job

from app.api.dependencies import get_redis_connection
from app.api.routes import app
from app.worker.tasks import process_job

client = TestClient(app)


@pytest.fixture
def fake_redis() -> Generator[fakeredis.FakeRedis, None, None]:
    conn = fakeredis.FakeRedis()
    app.dependency_overrides[get_redis_connection] = lambda: conn
    yield conn
    app.dependency_overrides.clear()


SOLVE_PAYLOAD = {
    "meta": {
        "version": "1.0.0",
        "school_term_id": 42,
        "webhook_url": "http://laravel-app/api/webhooks/allocation-result",
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
        "time_limit_seconds": 300,
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
            "demand": 55,
            "is_freshmen": False,
            "timeslot_ids": [0],
            "preassigned_room_id": None,
            "same_room_cohort": None,
        },
    ],
}


def test_solve_valid_payload(fake_redis: fakeredis.FakeRedis) -> None:
    response = client.post("/api/v1/solve", json=SOLVE_PAYLOAD)
    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "queued"
    assert data["message"] == "Job aceito e enfileirado com sucesso."

    job_id = data["job_id"]
    job = Job.fetch(job_id, connection=fake_redis)
    assert job is not None
    assert job.id == job_id


def test_solve_invalid_payload(fake_redis: fakeredis.FakeRedis) -> None:
    payload = {"meta": "invalid"}
    response = client.post("/api/v1/solve", json=payload)
    assert response.status_code == 422


def test_stop_job(fake_redis: fakeredis.FakeRedis) -> None:
    job_id = "test-job-123"
    queue = Queue(connection=fake_redis)
    queue.enqueue(process_job, {}, job_id=job_id)

    response = client.post(f"/api/v1/jobs/{job_id}/stop")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == job_id

    ttl = fake_redis.ttl(f"stop_job:{job_id}")
    assert ttl > 0
    assert ttl <= 3600
    assert fake_redis.get(f"stop_job:{job_id}") == b"true"


def test_stop_job_not_found(fake_redis: fakeredis.FakeRedis) -> None:
    response = client.post("/api/v1/jobs/inexistente-123/stop")
    assert response.status_code == 404
    assert "não encontrado" in response.json()["detail"]


def test_get_result_not_found(fake_redis: fakeredis.FakeRedis) -> None:
    response = client.get("/api/v1/jobs/nonexistent-job/result")
    assert response.status_code == 404
    assert "não existe" in response.json()["detail"]


def test_get_result_too_early(fake_redis: fakeredis.FakeRedis) -> None:
    job_id = "pending-job-456"
    queue = Queue(connection=fake_redis)
    queue.enqueue(process_job, {}, job_id=job_id)

    response = client.get(f"/api/v1/jobs/{job_id}/result")
    assert response.status_code == 425
    assert response.headers.get("retry-after") == "10"
    assert "processando" in response.json()["detail"]


def test_get_result_ok(fake_redis: fakeredis.FakeRedis) -> None:
    job_id = "finished-job-789"
    result_payload = {
        "job_id": job_id,
        "status": "optimal",
        "solve_time_seconds": 124.5,
        "solutions_found": 14,
        "objective_value": 450.5,
        "allocations": [{"group_id": 101, "room_id": 1}],
        "unassigned_groups": [],
        "suggestions": [],
    }
    fake_redis.set(f"result:{job_id}", json.dumps(result_payload))

    response = client.get(f"/api/v1/jobs/{job_id}/result")
    assert response.status_code == 200
    assert response.json() == result_payload
