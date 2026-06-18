# Projeto: Alocacao Solver (Microserviço Python)

## 🎯 Contexto do Projeto
Este é um microserviço construído em Python, responsável por resolver o Problema de Alocação de Salas (University Course Timetabling Problem - UCTP) do Instituto de Matemática e Estatística da USP. 
Ele atua como um worker assíncrono: recebe requisições JSON de um monólito Laravel, processa as otimizações matemáticas com o Google OR-Tools CP-SAT e devolve os resultados via Webhook.

## 🛠️ Stack Tecnológica e Ferramental
- **Linguagem Base:** Python 3.14 (imagem Docker: `python:3.14-slim-trixie`)
- **API Web:** FastAPI + Uvicorn
- **Validação e Tipagem:** Pydantic v2
- **Fila/Background Jobs:** RQ (Redis Queue)
- **Motor Matemático:** Google OR-Tools (CP-SAT Solver)
- **Gerenciador de Dependências:** Poetry

## 📂 Progressive Disclosure (Leia antes de codar)
Não adivinhe regras de negócio. Dependendo da tarefa que você (Agente IA) for realizar, leia obrigatoriamente o documento correspondente:
- 📜 Se for mexer nos **Endpoints, Schemas Pydantic ou Request/Response**: LEIA `docs/API_CONTRACT.md`
- 🧠 Se for mexer na **Lógica do Solver, Variáveis Booleanas ou Restrições**: LEIA `docs/MATHEMATICAL_MODEL.md`
- ⚙️ Se for mexer na **Conexão Redis, RQ Worker, Webhook ou Callbacks**: LEIA `docs/INFRA_AND_WORKER.md`

## ⚠️ Regras Críticas de Desenvolvimento (Diretrizes)
1. **Performance Matemática:** O OR-Tools CP-SAT não deve usar matrizes de conflitos $O(N^2)$. Utilize sempre `NewOptionalIntervalVar` e `AddNoOverlap` convertendo a semana para minutos contínuos (consulte o `MATHEMATICAL_MODEL.md`).
2. **Separação de Contextos (Clean Architecture):** A lógica matemática (`solver/`) não pode ter dependências da API Web (`api/`). O Worker (`worker/`) atua como a cola entre a fila e a matemática.
3. **Morte Graciosa (Stop Search):** O solver precisa herdar de `CpSolverSolutionCallback` para checar no Redis sinais de interrupção (Soft Stops) enviados pelo Laravel.
4. **Tratamento de Exceções:** Nunca deixe o worker do RQ "morrer calado". Todo crash no Python deve ser interceptado (try/except), logado e empurrado para o Webhook de resposta no formato de erro.
5. **Tipagem Estrita:** Use *Type Hints* nativos do Python em todas as funções. Valide todas as entradas com Pydantic.

## 💻 Comandos de Ambiente (Workflow)
Sempre que precisar executar, testar ou instalar pacotes, use estes comandos via Poetry:
- **Instalar/Atualizar dependências:** `poetry install`
- **Adicionar um pacote novo:** `poetry add <pacote>`
- **Rodar a API local (Dev):** `poetry run uvicorn app.api.routes:app --host 0.0.0.0 --port 8000 --reload`
- **Iniciar o Worker do RQ:** `poetry run rq worker`
- **Rodar os Testes:** `poetry run pytest` (Mantenha a suíte de testes verde antes de finalizar uma tarefa)
- **Linter e Formatação:** `poetry run ruff check .` e `poetry run ruff format .`

### 🐳 Docker Compose (Desenvolvimento)
O `docker-compose.yml` usa bind mount `.:/app` nos serviços `api` e `worker`, refletindo mudanças no código-fonte automaticamente nos containers sem rebuild:
- **Build e subir ambiente:** `docker compose build api worker && docker compose up -d`
- **Rodar testes dentro do container:** `docker exec <nome-do-container-api> poetry run pytest`