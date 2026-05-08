# 🧮 Alocação Solver (IME-USP)

Microserviço de otimização matemática para o Sistema de Alocação de Salas do Instituto de Matemática e Estatística da USP.

Este projeto resolve o **University Course Timetabling Problem (UCTP)** utilizando o solver CP-SAT do Google OR-Tools. Ele atua como um *worker* assíncrono isolado, retirando a carga computacional pesada do monólito Laravel e garantindo alta performance na distribuição de turmas em salas.

---

## 🚀 Tecnologias

- **Linguagem:** Python 3.14
- **API Framework:** FastAPI + Uvicorn
- **Validação:** Pydantic v2
- **Fila/Mensageria:** Redis + RQ (Redis Queue)
- **Motor de Otimização:** Google OR-Tools (CP-SAT Solver)
- **Gerenciamento de Pacotes:** Poetry
- **Containerização:** Docker (`python:3.14-slim-trixie`)

---

## ✨ Principais Funcionalidades

1. **Otimização de Alta Performance:** Modelagem em linha do tempo contínua 1D utilizando `AddNoOverlap` nativo em C++, eliminando o gargalo de memória de matrizes de conflito $O(N^2)$.
2. **Two-Pass Solver (Sugestão de Quebras):** O motor roda um primeiro passe estrito (1 turma = 1 sala). Para as turmas que sobrarem, roda um segundo passe relaxado para sugerir *quebras de horários* nos buracos das salas, ajudando a comissão em semestres superlotados.
3. **Morte Graciosa (Soft Stop):** A otimização pode ser abortada pelo usuário a qualquer momento. O solver é interrompido de forma limpa e devolve a melhor alocação encontrada até aquele segundo.
4. **Resiliência de Rede:** Resultados são enviados proativamente via Webhook, mas também ficam salvos no Redis local (com TTL de 24h) garantindo uma rota de resgate (`Fallback`) caso o servidor do Laravel sofra instabilidade.

---

## 🏗️ Arquitetura e Fluxo de Dados

O fluxo de comunicação com o sistema principal (Laravel) é totalmente assíncrono:

```text
+--------------+                               +-------------------------+
|              | 1. POST /api/v1/solve (JSON)  |  FastAPI (API REST)     |
|   Laravel    | ----------------------------> |  - Valida Payload       |
| (Monólito)   | <---------------------------- |  - Enfileira no RQ      |
|              | 2. 202 Accepted (job_id)      +-------------------------+
+--------------+                                           |
       ^                                                   | 3. Enfileira Job
       |                                                   v
       | 5. POST Webhook (Resultados)          +-------------------------+
       +-------------------------------------- |  Worker (RQ)            |
                                               |  - Monta Modelo         |
       +-------------------------------------- |  - Executa OR-Tools     |
       | 6. Grava progress:job_id (Polled)     |  - Gera Sugestões       |
       v                                       +-------------------------+
+--------------+                                           |
|    Redis     | <-----------------------------------------+
| (Shared/KV)  | 4. Grava resultado final de backup (TTL 24h)
+--------------+
```

---

## 📂 Estrutura do Projeto

A arquitetura do código segue os princípios de separação de responsabilidades (Clean Architecture):

```text
alocacao-solver/
├── app/
│   ├── api/                 # Endpoints FastAPI e Modelos Pydantic
│   ├── core/                # Configurações globais (CORS, Redis URL)
│   ├── solver/              # Coração Matemático (Engine OR-Tools, Constraints)
│   └── worker/              # Configuração do RQ e Tarefas assíncronas
├── docs/                    # Documentação detalhada de regras e contratos
├── tests/                   # Suíte de testes automatizados (pytest)
├── pyproject.toml           # Configuração de dependências (Poetry)
├── Dockerfile               # Build do container Python
└── docker-compose.yml       # Orquestração local (API + Worker + Redis)
```

---

## 📖 Documentação Técnica (Progressive Disclosure)

Para aprofundar no funcionamento interno, consulte a pasta `docs/`:

- 📜 [**API Contract:** `docs/API_CONTRACT.md`](docs/API_CONTRACT.md) - Formato exato dos JSONs de entrada, saída e webhooks.
- 🧠[**Mathematical Model:** `docs/MATHEMATICAL_MODEL.md`](docs/MATHEMATICAL_MODEL.md) - Regras de negócio, restrições *hard/soft* e equações booleanas do motor.
- ⚙️[**Infra & Worker:** `docs/INFRA_AND_WORKER.md`](docs/INFRA_AND_WORKER.md) - Regras de resiliência, filas, tratamento de exceções e timeout.

*(Se você utiliza Agentes de IA, leia o arquivo `AGENTS.md` na raiz do repositório).*

---

## 🛠️ Como Rodar o Projeto

### Pré-requisitos
- Docker e Docker Compose instalados.
- (Opcional) Python 3.14 e Poetry para desenvolvimento local sem Docker.

### Via Docker (Recomendado)

1. Clone o repositório e acesse a pasta:
   ```bash
   git clone https://github.com/ime-usp-br/alocacao-solver.git
   cd alocacao-solver
   ```

2. Crie o arquivo de configuração:
   ```bash
   cp .env.example .env
   ```

3. Suba a infraestrutura completa (FastAPI, Worker RQ e Redis):
   ```bash
    docker compose up -d --build
   ```

4. Acesse a documentação interativa Swagger (OpenAPI) gerada automaticamente pelo FastAPI:
   - **http://localhost:8001/docs**

> **Dica para Testes:** Para verificar o status `425 Too Early` (job ainda processando), envie um payload com muitos grupos/salas e `time_limit_seconds` alto (ex: 300), e imediatamente consulte `GET /api/v1/jobs/{job_id}/result`.

### Ambiente de Desenvolvimento Local (Poetry)

Se preferir rodar fora do Docker para debugar:

```bash
# Instalar dependências
poetry install

# Em um terminal, inicie a API:
poetry run uvicorn app.api.routes:app --host 0.0.0.0 --port 8000 --reload

# Em outro terminal, inicie o Worker do RQ:
poetry run rq worker

# Rodar a suíte de testes:
poetry run pytest
```