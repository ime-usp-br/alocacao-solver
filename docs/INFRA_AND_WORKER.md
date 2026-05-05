# Infraestrutura e Regras do Worker

Este microserviço foi projetado para conviver dentro da rede Docker junto com a aplicação Laravel, priorizando resiliência, processamento assíncrono blindado e facilidade de manutenção.

## 1. Stack Tecnológica
*   **Imagem Base (Obrigatória):** `python:3.14-slim-trixie`. 
    *   *Nota Crítica:* Não utilizar Alpine Linux, pois a compilação de binários C++ embarcados no OR-Tools via Alpine gera quebras e lentidão no build.
*   **Gerenciador de Ambientes e Dependências:** O projeto deve utilizar `poetry`. Arquivo base: `pyproject.toml`.
*   **Framework de API:** `fastapi` e `uvicorn` (para expor os endpoints REST). Validação via `pydantic` v2.
*   **Fila e Background Jobs:** `rq` (Redis Queue) para rodar o solver matematicamente pesado fora da thread web principal.

## 2. Acompanhamento de Progresso e Interrupção (Callback)
Para não criar um "Buraco Negro" na UX do Frontend, o progresso deve ser relatado em tempo real.
*   **Callback do OR-Tools:** O código deve conter uma classe que herda de `cp_model.CpSolverSolutionCallback`.
*   Durante a resolução, o callback deve interagir com o Redis:
    1.  **Monitorar Progresso:** Escrever na chave `progress:job_{job_id}` o status (Ex: `{"progress": 45, "message": "Calculando (12 soluções parciais)..."}`).
        *   Fórmula de Progresso: Usar a faixa de 15% a 85% para o tempo decorrido vs. timeout (`15 + (elapsed_time / config.time_limit_seconds) * 70`).
    2.  **Monitorar Stop (Soft Stop):** A cada iteração (ou intervalo de tempo no callback), checar se a chave `stop_job:{job_id}` existe no Redis.
    3.  Se a chave `stop` for detectada, invocar o método `self.StopSearch()` para paralisar o C++ educadamente e preservar a melhor variável de decisão.

## 3. Worker e Segurança Contra Falhas (Tratamento de Exceções)
O arquivo que contém a task enfileirada no RQ (ex: `worker.py` ou `tasks.py`) deve seguir um padrão inquebrável de try/except:
*   Toda a invocação do `engine` de resolução deve estar dentro de um grande `try/except Exception as e:`.
*   **Em caso de Sucesso:** Formatar o payload e enviar via requisição HTTP POST para o webhook fornecido pelo Laravel (usar a biblioteca `httpx` ou `requests` com timeout de 10 segundos).
*   **Em caso de Falha Geral/Crash:** Capturar o erro (incluindo o trace de pilha se viável), formatar um JSON com status `error` e também disparar o webhook pro Laravel.
*   **Sempre salvar no Redis:** Antes de tentar disparar o Webhook, o worker deve gravar o JSON do resultado absoluto na chave Redis `result:{job_id}` com um tempo de expiração (TTL) de 86400 segundos (24 horas). Isso previne a perda total da computação caso a rede do container do Laravel caia momentaneamente.