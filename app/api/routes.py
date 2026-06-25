import json
import uuid
from typing import Any

import redis
from fastapi import Depends, FastAPI, HTTPException, status
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

from app.api.dependencies import get_redis_connection
from app.api.schemas import (
    SolveAcceptedResponse,
    SolveRequest,
    StopResponse,
)
from app.worker.tasks import on_job_failure, process_job

app = FastAPI(title="Alocacao Solver API")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/solve", status_code=status.HTTP_202_ACCEPTED)
def solve(
    request: SolveRequest,
    redis_conn: redis.Redis = Depends(get_redis_connection),
) -> SolveAcceptedResponse:
    job_id = str(uuid.uuid4())
    job_data = request.model_dump()
    job_data["job_id"] = job_id

    queue = Queue(connection=redis_conn)
    # job_timeout deve cobrir o tempo do solver + build do modelo + I/O.
    # Sem isto, o RQ aplica o default de 180s e mata o work-horse em
    # 180+60=240s, antes do CP-SAT concluir (time_limit_seconds).
    job_timeout = request.config.time_limit_seconds + 180
    queue.enqueue(
        process_job,
        job_data,
        job_id=job_id,
        job_timeout=job_timeout,
        on_failure=on_job_failure,
    )

    return SolveAcceptedResponse(
        job_id=job_id,
        status="queued",
        message="Job aceito e enfileirado com sucesso.",
    )


@app.post("/api/v1/jobs/{job_id}/stop")
def stop_job(
    job_id: str,
    redis_conn: redis.Redis = Depends(get_redis_connection),
) -> StopResponse:
    try:
        Job.fetch(job_id, connection=redis_conn)
    except NoSuchJobError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job não encontrado ou já expirou.",
        )

    redis_conn.setex(f"stop_job:{job_id}", 3600, "true")
    return StopResponse(
        job_id=job_id,
        message="Sinal de parada enviado. O worker enviará a solução parcial via webhook em instantes.",
    )


@app.get("/api/v1/jobs/{job_id}/result")
def get_result(
    job_id: str,
    redis_conn: redis.Redis = Depends(get_redis_connection),
) -> dict[str, Any]:
    raw = redis_conn.get(f"result:{job_id}")

    if raw is not None:
        return json.loads(raw)

    try:
        Job.fetch(job_id, connection=redis_conn)
    except NoSuchJobError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job não existe ou o resultado expirou.",
        )

    raise HTTPException(
        status_code=status.HTTP_425_TOO_EARLY,
        detail="O job ainda está processando.",
        headers={"Retry-After": "10"},
    )
