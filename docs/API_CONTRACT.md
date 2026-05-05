# Contrato de API (Laravel <-> Python Solver)

Este documento define os contratos HTTP e os schemas de dados para comunicação entre o monólito Laravel e o microserviço Python (FastAPI + RQ).

## 1. Submissão do Problema (Dispatch)

*   **Rota:** `POST /api/v1/solve`
*   **Ação:** Recebe o JSON do problema, valida os tipos via Pydantic, joga na fila de processamento do RQ e retorna um `job_id`.
*   **Request Payload (Exemplo):**
{
  "meta": {
    "version": "1.0.0",
    "school_term_id": 42,
    "webhook_url": "http://laravel-app/api/webhooks/allocation-result"
  },
  "config": {
    "strict_capacity": false,
    "block_b_restriction_for_pos": true,
    "wasted_seats_weight": 1.5,
    "unassigned_penalty": 1000.0,
    "time_limit_seconds": 300
  },
  "timeslots":[
    { "id": 0, "label": "seg_0800_0940", "day": "seg", "start": "08:00", "end": "09:40" },
    { "id": 1, "label": "qua_1000_1140", "day": "qua", "start": "10:00", "end": "11:40" }
  ],
  "rooms":[
    { "id": 1, "name": "B09", "capacity": 40 },
    { "id": 2, "name": "A242", "capacity": 36 }
  ],
  "groups":[
    {
      "id": 101,
      "type": "single",
      "class_ids": [101],
      "coddis": "MAC0110",
      "tiptur": "Graduacao",
      "demand": 55,
      "has_null_enrollment": false,
      "timeslot_ids": [0, 1],
      "preassigned_room_id": null
    },
    {
      "id": 205,
      "type": "fusion",
      "class_ids": [205, 206],
      "coddis": "MAT2453",
      "tiptur": "Graduacao",
      "demand": 120,
      "has_null_enrollment": false,
      "timeslot_ids": [0],
      "preassigned_room_id": 2
    }
  ]
}

*   **Response (202 Accepted):**
{
  "job_id": "uuid-1234-5678",
  "status": "queued",
  "message": "Job aceito e enfileirado com sucesso."
}

## 2. Abortar Execução (Soft Stop)

*   **Rota:** `POST /api/v1/jobs/{job_id}/stop`
*   **Ação:** O FastAPI grava a chave `stop_job:{job_id} = true` no Redis (com TTL de 1h). O callback do OR-Tools lê isso, intercepta a execução, aciona `solver.StopSearch()` e o worker devolve a melhor solução parcial calculada até aquele momento via Webhook.
*   **Response (200 OK):**
{
  "job_id": "uuid-1234-5678",
  "message": "Sinal de parada enviado. O worker enviará a solução parcial via webhook em instantes."
}

## 3. Rota de Resgate (Fallback)

*   **Rota:** `GET /api/v1/jobs/{job_id}/result`
*   **Ação:** Criada como redundância caso o Webhook falhe devido à rede. O Laravel consulta essa rota. O FastAPI busca a chave `result:{job_id}` no Redis.
*   **Status Codes:** 
    *   `200 OK` (Retorna o Payload Final de Resultado).
    *   `425 Too Early` (Ainda está processando).
    *   `404 Not Found` (Job não existe ou o resultado expirou após 24h).

## 4. O Webhook de Resultado (Python -> Laravel)

*   **Ação:** Disparado pelo Worker RQ para a `webhook_url` ao terminar o job (seja por atingir o ótimo, por timeout, falha ou stop do usuário).
*   **Payload de Sucesso:**
{
  "job_id": "uuid-1234-5678",
  "status": "optimal", 
  "solve_time_seconds": 124.5,
  "solutions_found": 14,
  "objective_value": 450.5,
  "allocations":[
    { "group_id": 101, "room_id": 1 },
    { "group_id": 205, "room_id": 2 }
  ],
  "unassigned_groups": [],
  "suggestions":[
    {
      "group_id": 310,
      "timeslot_id": 4,
      "suggested_room_id": 2
    }
  ]
}
*   **Nota sobre `status`:** Os status possíveis são `optimal` (perfeito), `feasible` (achou solução, mas bateu no tempo-limite), `stopped` (usuário abortou e resgatou a parcial), ou `infeasible` (impossível matematicamente).
*   **Payload de Erro (Exception handling):**
{
  "job_id": "uuid-1234-5678",
  "status": "error",
  "message": "Mensagem da Exception capturada no Python",
  "trace": "Stack trace..."
}