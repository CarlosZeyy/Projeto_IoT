# SPEC-004: API de ingestão e autenticação de dispositivos

| Campo | Valor |
|---|---|
| Status | Ready |
| Rodada atual | — |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-002, SPEC-003 |
| Semana alvo | S2 |
| Requisitos cobertos | RF-06, RF-15, RNF-04 (lado da API), RNF-06, R-02, R-03, R-05 |
| ADRs relevantes | ADR-006 (FastAPI + Supabase + psycopg), ADR-009 (publisher HTTP), ADR-008 (Render/Supabase free), ADR-012 (idioma) |

## 1. Contexto

`docs/architecture.md` §4 define a API na nuvem, a autenticação por `X-API-Key` e as proteções; §3.2–3.3 definem os payloads; §5 a idempotência via `ON CONFLICT`. Esta SPEC cria o esqueleto do `qc-api` e as rotas de escrita usadas pelo outbox da borda (SPEC-009) e pelo simulador (SPEC-014), além do `/health` usado pelo keep-alive (SPEC-015).

## 2. Objetivo

Um dispositivo registrado grava inspeções via `POST /api/v1/inspections` e `/inspections/batch` de forma idempotente e autenticada, e `GET /api/v1/health` informa o estado do banco, tudo testado contra o Postgres de teste.

## 3. Escopo

### 3.1 Dentro

- `api/src/qc_api/`: `__init__.py` (`__version__ = "0.1.0"`), `main.py`, `config.py`, `db.py`, `auth.py`, `middleware.py` (limite de corpo), `errors.py`, `routers/health.py`, `routers/inspections.py`.
- `scripts/register_device.py`.
- `.env.example`: `MAX_BODY_BYTES` e `LOG_LEVEL` no bloco `qc-api`, com comentário.
- `README.md` ("Como rodar"): subir a API local e registrar um dispositivo.
- Testes em `api/tests/`.

### 3.2 Fora

- Rotas de leitura e métricas e a dependência de chave de leitura nas rotas (SPEC-005); SPC (SPEC-006). Esta SPEC entrega `require_read_key` em `auth.py`, testado só unitariamente.
- Outbox e publisher (SPEC-009); simulador (SPEC-014).
- `infra/render.yaml`, variáveis no Render, keep-alive (SPEC-015).
- Heartbeat de dispositivos (SPEC-018).

## 4. Requisitos detalhados

### 4.1 Configuração (`config.py`)

- `Settings(BaseSettings)` lendo **só do ambiente** (sem arquivo `.env`; localmente use `uv run --env-file .env ...`):
  - `DATABASE_URL`: `SecretStr`, obrigatória;
  - `READ_API_KEY`: `SecretStr`, obrigatória, mínimo de 32 caracteres;
  - `MAX_BODY_BYTES`: `int > 0`, padrão `262144`;
  - `LOG_LEVEL`: `DEBUG|INFO|WARNING|ERROR`, padrão `INFO`.
- Erro de configuração nunca mostra valores (só o nome da variável).

### 4.2 Aplicação (`main.py`, `db.py`)

- `create_app(settings: Settings | None = None) -> FastAPI`. Com `None`, as settings são carregadas do ambiente no `lifespan` (início do servidor), não no import. `app = create_app()` em nível de módulo mantém válido `uvicorn qc_api.main:app` (`docs/deployment-plan.md` §4).
- `lifespan`: cria `psycopg_pool.ConnectionPool(min_size=1, max_size=5, timeout=5, open=False, kwargs={"prepare_threshold": None, "connect_timeout": 5})` e chama `open(wait=False)`, de modo que a API **sobe mesmo com o banco fora do ar**; fecha o pool no encerramento. Settings e pool ficam em `app.state`.
- Endpoints **síncronos** (`def`). Prefixo `/api/v1`. Documentação em `/docs`.
- **Sem** `CORSMiddleware` (CORS fechado, §4).
- Logging com `logging` no nível `LOG_LEVEL`. Por requisição: método, rota, status, `device_id` (quando houver) e duração. **Nunca** logar `X-API-Key`, `DATABASE_URL`, o corpo da requisição ou hashes de chave.

### 4.3 Autenticação (`auth.py`)

- `hash_api_key(key: str) -> str`: SHA-256 hex minúsculo.
- `require_device` (dependência): lê `X-API-Key`; ausente, vazio ou com mais de 256 caracteres → 401; calcula o hash, busca `select device_id, api_key_hash from devices where api_key_hash = %s`; sem linha → 401; confirma com `secrets.compare_digest`; retorna o `device_id`.
- `require_read_key` (dependência): compara `X-API-Key` com `READ_API_KEY` via `secrets.compare_digest`; diferente ou ausente → 401.
- Toda resposta 401 tem o corpo exato `{"detail": "Missing or invalid API key"}` (sem distinguir o motivo).

### 4.4 Rotas

| Rota | Auth | Sucesso | Erros |
|---|---|---|---|
| `GET /api/v1/health` | — | 200 `HealthResponse` com `status="ok"`, `db="ok"` | 503 `HealthResponse` com `status="degraded"`, `db="error"` |
| `POST /api/v1/inspections` | dispositivo | 201 `InspectionCreated(status="created")` ou 200 `(status="duplicate")` | 401, 403, 413, 422, 503 |
| `POST /api/v1/inspections/batch` | dispositivo | 200 `BatchResult` (mesma ordem da entrada) | 401, 403, 413, 422, 503 |

- `/health` executa `SELECT 1` com timeout de conexão do pool; `api_version = qc_api.__version__`, `contract_version = qc_contracts.__version__`. Nunca inclui a mensagem de erro do banco.
- Escrita: `INSERT ... ON CONFLICT (inspection_id) DO NOTHING RETURNING inspection_id` (§5); sem linha → `duplicate`. Um duplicado **não** altera o registro original, mesmo que o corpo seja diferente (R-05).
- `device_id` de cada inspeção (única ou de qualquer item do lote) diferente do dono da chave → 403 `{"detail": "device_id does not match API key"}` e nada é gravado.
- Lote: todos os itens numa **única transação**, processados em ordem; o mesmo `inspection_id` repetido no lote → o primeiro `created`, os seguintes `duplicate`. Item inválido → 422 (validação do `BatchCreate`) e nada gravado.
- Na mesma transação da escrita bem-sucedida (200/201): `update devices set last_seen_at = now() where device_id = %s`. Respostas 401, 403, 413, 422 e 503 não alteram `last_seen_at`.
- Concorrência: duas requisições simultâneas com o mesmo `inspection_id` resultam em exatamente uma linha (garantido pelo `ON CONFLICT`).
- Nenhuma rota aceita imagem ou `multipart/form-data` (R-02).

### 4.5 Proteções e erros

- **Limite de corpo** (middleware ASGI, todas as rotas): `Content-Length > MAX_BODY_BYTES` → 413 sem ler o corpo; sem `Content-Length` (chunked), conta os bytes lidos e responde 413 ao passar do limite. Corpo: `{"detail": "Request body too large"}`.
- **Precedência** para JSON bem formado: 413 → 503 (banco indisponível ao autenticar) → 401 → 422 → 403.
- Banco indisponível (`psycopg.OperationalError`, `PoolTimeout`) → 503 `{"detail": "Database unavailable"}`.
- Exceção inesperada → 500 `{"detail": "Internal server error"}`; o traceback vai só para o log do servidor.
- Erros de validação usam o 422 padrão do FastAPI (`{"detail": [...]}`).

### 4.6 `scripts/register_device.py`

- Uso: `uv run --package qc-api python scripts/register_device.py --device-id edge-01 [--rotate] [--database-url URL]` (padrão: `DATABASE_URL`).
- Valida `--device-id` com `qc_contracts.DEVICE_ID_PATTERN`.
- Gera a chave com `secrets.token_urlsafe(32)`, grava **só** `hash_api_key(chave)` e escreve no stdout uma única linha `DEVICE_API_KEY=<chave>` (via `sys.stdout.write`; a chave nunca vai para log). Mensagens de status vão para o stderr via `logging`, sem a chave.
- Sem `--rotate`, dispositivo já existente → erro. Com `--rotate`, dispositivo inexistente → erro; existente → troca o hash (a chave antiga deixa de valer na hora).
- Códigos de saída: `0` sucesso; `1` dispositivo existente/inexistente ou falha de banco; `2` uso inválido (`device_id` fora da regex, sem URL).

## 5. Critérios de aceite

Contexto comum: banco de teste migrado (fixtures `migrated_db`/`clean_db` da SPEC-003); dispositivos `edge-01` (chave `KE`) e `sim-01` (chave `KS`) registrados pelo hash; app criada com `create_app(Settings(DATABASE_URL=<teste>, READ_API_KEY="r"*32))` e usada com `TestClient` (lifespan ativo). `P(id)` = payload válido de `InspectionCreate` com `device_id="edge-01"` e `grade="fair"`. "App sem banco" = app com `DATABASE_URL=postgresql://u:pw@127.0.0.1:1/x`.

- **CA-01** — Dado o banco acessível, quando `GET /api/v1/health`, então 200 com `{"status": "ok", "db": "ok", "api_version": "0.1.0", "contract_version": "0.1.0"}`.
- **CA-02** — Dado a app sem banco, quando ela inicia e recebe `GET /api/v1/health`, então a inicialização não falha e a resposta é 503 com `status="degraded"` e `db="error"`, em menos de 10 s.
- **CA-03** — Dado `P(X)` com `inspected_at="2026-10-01T12:00:00-03:00"` (no passado) e a chave `KE`, quando `POST /api/v1/inspections`, então 201 com `{"inspection_id": "X", "status": "created"}`; a tabela tem 1 linha com `inspected_at = 2026-10-01T15:00:00Z`, `received_at` preenchido e `is_defective = false`.
- **CA-04** — Dado `P(X)` já gravado, quando o mesmo `X` é reenviado 3 vezes (a última com `lot_id="L-999"`), então cada resposta é 200 com `status="duplicate"`, a tabela tem 1 linha e `lot_id` continua o original (R-05).
- **CA-05** — Dado `P(X)`, quando `POST /api/v1/inspections` sem `X-API-Key`, com `X-API-Key: errada`, com a chave de leitura (`"r"*32`) ou com uma chave de 300 caracteres, então cada resposta é 401 com o corpo exato `{"detail": "Missing or invalid API key"}` e nada é gravado.
- **CA-06** — Dado um JSON bem formado mas inválido (sem `lot_id`) e nenhuma chave, quando `POST /api/v1/inspections`, então 401 (autenticação antes da validação).
- **CA-07** — Dado `P(X)` com `device_id="sim-01"` e a chave `KE`, quando `POST /api/v1/inspections`, então 403 com `{"detail": "device_id does not match API key"}`, nada é gravado e `last_seen_at` de `edge-01` e `sim-01` não muda.
- **CA-08** — Dado a chave `KE`, quando o corpo é: `P(X)` + `"image": "AAAA"`; `P(X)` com `object_type="unknown"` e `grade="fair"`; `P(X)` com `inspected_at` sem fuso; `P(X)` sem `lot_id`; ou o texto `not json`, então cada resposta é 422, nada é gravado e nenhum corpo contém `Traceback`.
- **CA-09** — Dado a chave `KE`, quando o corpo tem exatamente 262 144 bytes, então a resposta **não** é 413; com 262 145 bytes, é 413 com `{"detail": "Request body too large"}`; com `Content-Length: 300000` declarado, é 413; e com corpo chunked (sem `Content-Length`) de 300 000 bytes, é 413. Nada é gravado.
- **CA-10** — Dado `edge-01` com `last_seen_at` nulo, quando um `POST` válido retorna 201, então `last_seen_at` fica entre o instante antes e o depois da requisição; quando o mesmo `X` é reenviado (200), `last_seen_at` é atualizado de novo (≥ o anterior); e respostas 401, 403 e 422 não o alteram.
- **CA-11** — Dado a chave `KE`, quando `POST /api/v1/inspections/batch` com `P(A)`, `P(B)`, `P(C)`, então 200 com `results` = `[A created, B created, C created]` nessa ordem e 3 linhas na tabela.
- **CA-12** — Dado `P(A)` já gravado, quando o lote é `[P(B), P(A), P(B)]`, então 200 com `results` = `[B created, A duplicate, B duplicate]` e a tabela tem 2 linhas.
- **CA-13** — Dado a chave `KE`, quando o lote tem 3 itens e o 2º tem `type_confidence=2`, então 422 e a tabela continua vazia; com `items` vazio ou com 101 itens, então 422.
- **CA-14** — Dado a chave `KE`, quando o lote tem 3 itens e o 3º tem `device_id="sim-01"`, então 403 e a tabela continua vazia.
- **CA-15** — Dado `P(X)` e a chave `KE`, quando duas threads enviam `POST /api/v1/inspections` ao mesmo tempo (liberadas por uma `threading.Barrier`), repetido 10 vezes com IDs diferentes, então em cada repetição os status são `{201, 200}` e existe exatamente 1 linha por ID.
- **CA-16** — Dado a app sem banco, quando `POST /api/v1/inspections` com qualquer chave, então 503 com o corpo exato `{"detail": "Database unavailable"}`.
- **CA-17** — Dado a app, quando `OPTIONS /api/v1/inspections` com `Origin: https://evil.example` e `Access-Control-Request-Method: POST`, e quando `GET /api/v1/health` com o mesmo `Origin`, então nenhuma das respostas tem o header `access-control-allow-origin`.
- **CA-18** — Dado `caplog` no nível DEBUG, quando a app sem banco inicia e quando a app normal processa um `POST` 201 e um 401, então nenhum registro de log contém `KE`, `hash_api_key(KE)`, a senha `pw` da URL nem o valor de `READ_API_KEY` (R-03).
- **CA-19** — Dado a app, quando se lê `/openapi.json`, então as rotas `POST /api/v1/inspections` e `/inspections/batch` aceitam só `application/json`, nenhuma rota declara `multipart/form-data` (R-02) e `GET /docs` retorna 200.
- **CA-20** — Dado `Settings` com `READ_API_KEY` de 31 caracteres, ou sem `DATABASE_URL`, quando é instanciada, então levanta `ValidationError`, e a mensagem não contém o valor fornecido.
- **CA-21** — Dado o banco migrado sem `lab-02`, quando `register_device.py --device-id lab-02` roda com `DATABASE_URL` de teste, então sai com 0, o stdout é exatamente uma linha `DEVICE_API_KEY=<k>` com `len(k) >= 43`, a linha de `devices` tem `api_key_hash == sha256(k)`, o texto de `k` não aparece em nenhuma coluna e um `POST` com `X-API-Key: k` e `device_id="lab-02"` retorna 201.
- **CA-22** — Dado `lab-02` registrado, quando `register_device.py --device-id lab-02` roda sem `--rotate`, então sai com 1 e o hash não muda; quando roda com `--rotate`, sai com 0 e imprime uma chave nova `k2`; então a chave antiga recebe 401 e `k2` recebe 201.
- **CA-23** — Dado o banco migrado, quando `register_device.py --rotate --device-id ghost-01` roda, então sai com 1; com `--device-id Edge_01`, sai com 2; sem `DATABASE_URL` e sem `--database-url`, sai com 2. Em nenhum caso o stdout contém `DEVICE_API_KEY=`.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | `hash_api_key`, `require_read_key`, middleware de limite (sem banco), settings; rotas e script contra o banco de teste | `api/tests/` |
| Aceite (tester) | Um teste por CA (marcados `db`, exceto CA-17, CA-19 e CA-20) | `api/tests/acceptance/test_spec_004.py` |

Banco: Postgres 16 de teste (SPEC-001/003). Sem mock de banco; a "app sem banco" usa uma porta fechada local. O script é testado com `subprocess` e `sys.executable`.

## 7. Riscos e notas para o implementador

- O pooler do Supabase em modo transaction não aceita prepared statements: `prepare_threshold=None` é obrigatório (ADR-006).
- O health check do Render usa `/api/v1/health` (`deployment-plan.md` §4); com o Supabase pausado, ele responde 503. A SPEC-015 deve avaliar se o Render reinicia o serviço nessa situação.
- `TestClient` precisa do bloco `with` para rodar o `lifespan`.
- O `sys.stdout.write` do script é a saída do próprio CLI (a chave), não log; isso não viola a regra "nada de `print`".
- Um `duplicate` para um ID que pertence a outro dispositivo é aceito como está em `architecture.md` §3.3 (sem 409); registrado aqui como decisão consciente.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED e security-report PASS
- [ ] CI verde; `ruff` limpo; R-12 continua verde
- [ ] `.env.example` e `README.md` atualizados
- [ ] PR aberto com os relatórios; merge humano
