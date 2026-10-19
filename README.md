# PartQC — Inspeção visual de qualidade com celular, borda e nuvem

Projeto acadêmico da disciplina **Aplicações de Cloud, IoT e Indústria 4.0 (Python)**.

O operador fotografa uma peça (parafuso ou porca) com o **celular**. O **notebook**, atuando como gateway de borda, classifica o tipo e o **grau de estado**:

| Código | Grau |
|---|---|
| `perfect` | perfeito |
| `good` | bom |
| `fair` | mediano |
| `poor` | ruim |
| `unusable` | inutilizável |

A **nuvem** guarda o histórico e mostra indicadores e uma **carta de controle p (SPC)** por lote.

```text
Celular (câmera, navegador) ──HTTP/LAN──► Notebook (FastAPI + ONNX Runtime + outbox SQLite)
                                                        │ HTTPS (só resultados, nunca imagens)
                                                        ▼
                                  API FastAPI (VPS) ─► Postgres (Supabase) ◄─ Dashboard (Streamlit, VPS)
```

- **Custo:** R$ 0 (free tiers e software livre)
- **Stack:** Python 3.12 · uv · FastAPI · Pydantic v2 · PyTorch/timm → ONNX · onnxruntime · Supabase Postgres · Streamlit + Plotly

## Status

🚧 Fase de fundação: documentação concluída; implementação começa pela [SPEC-001](docs/specs/SPEC-001-setup-repositorio.md). Acompanhe em [docs/plan.md](docs/plan.md).

## Documentação

- [Índice](docs/README.md)
- [PRD](docs/PRD.md)
- [Arquitetura](docs/architecture.md)
- [Regras](docs/rules.md)
- [Plano](docs/plan.md)
- [Protocolo de dataset](docs/dataset-protocol.md)
- [Deploy](docs/deployment-plan.md)
- [ADRs](docs/adr/)
- [SPECs](docs/specs/)

## Como o desenvolvimento funciona

Cada entrega é uma SPEC, implementada por um loop de agentes com papéis separados: autor → tester → reviewer → (segurança). Depois, um PR que o orquestrador confere e mergeia sob delegação do humano, que pode vetar (ADR-016). Detalhes em [reviews/README.md](reviews/README.md) e em [CLAUDE.md](CLAUDE.md).

## Como rodar

Esta seção cresce conforme as SPECs forem concluídas (SPEC-001: ambiente; SPEC-007: borda; SPEC-015: deploy).

### Ambiente (SPEC-001)

Pré-requisito: [uv](https://docs.astral.sh/uv/) ≥ 0,8 (`sudo pacman -S uv` no Arch, ou `curl -LsSf https://astral.sh/uv/install.sh | sh`). O Python do sistema não é usado: o uv instala e fixa o 3.12 (`.python-version`).

```bash
uv python install 3.12
uv sync --all-packages --frozen            # workspace inteiro, sem torch (o que o CI usa)
uv sync --all-packages --extra train       # + torch/timm para treinar localmente (pesado)
uv run ruff check . && uv run ruff format --check .
uv run pytest -q
```

Use sempre `--all-packages` ou `--package <pkg>` no `uv sync`: sem isso, o uv remove os membros do workspace do ambiente.

### Testes de banco (marcador `db`)

Os testes marcados `db` usam um Postgres descartável indicado por `TEST_DATABASE_URL`, lida só do ambiente (o `.env` não é lido pelo pytest). Sem a variável, eles são pulados (`TEST_DATABASE_URL not set`). Com `CI=true` e sem a variável, o pytest falha antes de rodar qualquer teste.

```bash
# Postgres 16 local em Docker (ou use o Postgres do sistema), sem senha (trust)
docker run -d --name partqc-pg -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=partqc_test -p 127.0.0.1:55432:5432 postgres:16
# nas próximas vezes: docker start partqc-pg

export TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test
uv run pytest -q
```

A porta é publicada só em `127.0.0.1`: com `trust`, quem alcança a porta entra sem senha, e o padrão do Docker (`-p 55432:5432`) publica em todas as interfaces, ou seja, na LAN.

**Contêiner antigo:** um contêiner `partqc-pg` criado antes da SPEC-022 (com senha) não aceita a URL acima. Recrie-o com `docker rm -f partqc-pg` seguido do `docker run` acima.

### Migrações do banco (SPEC-003)

As migrações SQL ficam em `infra/migrations/NNN_slug.sql` e são aplicadas por `infra/migrate.py`, que registra cada uma em `schema_migrations` com o SHA-256 do arquivo. Rodar de novo não aplica nada; um arquivo já aplicado que foi alterado gera `checksum mismatch` e nada é aplicado. A URL vem de `DATABASE_URL` (ou `--database-url`) e nunca aparece nos logs.

```bash
# banco local de teste (Docker acima)
export DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test
uv run --package qc-api python infra/migrate.py --status   # lista aplicadas e pendentes, sem aplicar
uv run --package qc-api python infra/migrate.py            # aplica as pendentes, em ordem
```

Códigos de saída: `0` sucesso; `1` falha de banco, de migração ou de checksum; `2` uso inválido (sem URL, argumento inválido). O SQL também pode ser colado no SQL Editor do Supabase ou rodado com `psql`, porque o DDL usa `if not exists` (a aplicação em produção é da SPEC-015).

Nos testes, as fixtures `db_conninfo`, `migrated_db` e `clean_db` do `conftest.py` da raiz recriam o schema `public`, aplicam as migrações e limpam as tabelas. Por segurança, recusam um banco cujo nome não contenha `test`.

### API local e registro de dispositivo (SPEC-004)

A API (`qc-api`) lê a configuração só do ambiente: `DATABASE_URL` e `READ_API_KEY` (mínimo de 32 caracteres) são obrigatórias; `MAX_BODY_BYTES` (padrão 262144) e `LOG_LEVEL` (padrão `INFO`) são opcionais. Ela não lê o `.env` sozinha: use `uv run --env-file .env ...` ou exporte as variáveis. Localmente, aponte para o Postgres de teste em Docker (seção anterior), já migrado.

```bash
export DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test
export READ_API_KEY="$(uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run --package qc-api python infra/migrate.py
uv run --package qc-api uvicorn qc_api.main:app --reload --port 8001
# em outro terminal
curl -s http://localhost:8001/api/v1/health   # {"status":"ok","db":"ok",...}; 503 com o banco fora do ar
```

A documentação interativa fica em <http://localhost:8001/docs>.

Cada dispositivo (borda ou simulador) precisa de uma chave própria, enviada no header `X-API-Key`. O banco guarda só o SHA-256 dela. O script imprime a chave **uma única vez**, numa linha `DEVICE_API_KEY=<chave>`, que vai para o `.env` do dispositivo:

```bash
uv run --package qc-api python scripts/register_device.py --device-id edge-01            # registra
uv run --package qc-api python scripts/register_device.py --device-id edge-01 --rotate   # troca a chave (a antiga deixa de valer na hora)
```

A URL vem de `DATABASE_URL` (ou `--database-url`). Códigos de saída: `0` sucesso; `1` dispositivo já existente (sem `--rotate`), inexistente (com `--rotate`) ou falha de banco; `2` uso inválido (`--device-id` fora de `^[a-z0-9-]{3,32}$`, sem URL).

### Simulador (SPEC-014)

`scripts/simulate.py` gera lotes de inspeções plausíveis e os envia pela mesma rota de ingestão da borda (`POST /api/v1/inspections/batch`), em blocos de até 100 itens. Todo registro sai com `source=simulated` (R-06): não existe opção para mudar isso, e `--source` é recusado. O dispositivo do simulador precisa estar registrado, com a chave no ambiente:

```bash
uv run --package qc-api python scripts/register_device.py --device-id sim-01   # copie a chave para SIM_DEVICE_API_KEY no .env
uv run --env-file .env --package qc-api python scripts/simulate.py --lots 10 --seed 42
uv run --env-file .env --package qc-api python scripts/simulate.py --lots 30 --lot-size 200 --out-of-control-lots 24,28 --seed 42
uv run --package qc-api python scripts/simulate.py --dry-run --device-id sim-01 --lots 3 --seed 42   # JSON Lines no stdout, sem rede
```

- **Variáveis:** `CLOUD_API_URL` (ou `--api-url`; `https://`, e `http://` só para `localhost`/`127.0.0.1`; só caracteres ASCII visíveis, sem espaço), `SIM_DEVICE_ID` (ou `--device-id`) e `SIM_DEVICE_API_KEY` (ou `--api-key`). A chave nunca é impressa.
- **Chave na linha de comando:** prefira `SIM_DEVICE_API_KEY`, porque o argumento fica no histórico do shell e na lista de processos. Se passar a chave na linha de comando, use a forma `--api-key=<valor>`: uma chave que começa com `-` (cerca de 1 em 64) não funciona com espaço (`--api-key <valor>`).
- **Erros de uso:** a mensagem nunca repete o que foi digitado. Uma opção desconhecida aparece só como contagem (`unrecognized arguments: 2 value(s) (not shown)`), e um valor inválido de uma opção, como `(not shown)` (`argument --lots: invalid int value (not shown)`). Uso inválido sempre sai com código 2, sem traceback.
- **Lotes:** `--lots` (padrão 10, até 500), `--lot-size` (padrão 25) ou o par `--lot-size-min`/`--lot-size-max`, `--defect-rate` (padrão 0,10, taxa de `poor` + `unusable`), `--unknown-rate` (padrão 0,02) e `--out-of-control-lots` (números 1-based de 1 a 4 dígitos, separados por vírgula, com a taxa de defeito triplicada, limitada a 1; `0007` é o lote 7). Cada lote se chama `SIM-<AAAAMMDD>-<NNN>` (data UTC de `--start`) e ocupa 10 min a partir de `--start` (padrão: agora − lotes × 10 min; com fuso, sem passar de agora + 5 min).
- **Idempotência (R-05):** os ids derivam de `--seed`. Rodar de novo com a mesma seed reenvia os mesmos ids, e a API responde `duplicate`. Sem `--seed`, uma seed aleatória é sorteada; ela aparece sempre no resumo `sent=<n> created=<n> duplicate=<n> lots=<n> seed=<s> source=simulated`.
- **Mesmo dia, outra série:** o `lot_id` só usa a data de `--start`. Duas execuções no mesmo dia com seeds diferentes geram lotes com o mesmo nome e misturam os dados no SPC; para uma série nova, use outro `--start`.
- **Envio:** antes do primeiro lote, `GET /api/v1/health` com até 90 s de espera (absorve um cold start da API, como o do Render, reserva da hospedagem). Erro de rede, timeout ou 5xx: até 3 novas tentativas por bloco (2, 4 e 8 s).

Códigos de saída: `0` sucesso; `1` erro interno (item gerado inválido); `2` uso inválido; `3` chave recusada (401/403); `4` bloco recusado (422, com o `detail` no stderr); `5` API fora do ar ou falhando (health, rede, timeout, 5xx depois das tentativas, ou outra resposta inesperada).

### Gateway de borda (SPEC-007)

```bash
uv run --env-file .env --package qc-edge qc-edge --stub-model   # console em http://127.0.0.1:8000/
```

Variáveis, firewall no Arch, plano B (hotspot) e o roteiro do teste com os celulares estão em [edge/README.md](edge/README.md).

### CI

O workflow `ci` (`.github/workflows/ci.yml`) roda em todo PR e em push na `main`: `uv sync --all-packages --frozen`, `ruff check`, `ruff format --check` e `pytest -q` com um serviço `postgres:16`. O teste `tests/test_dependency_isolation.py` garante, pelo `uv.lock`, que `qc-api` e `qc-dashboard` não dependem de torch, torchvision, timm nem onnxruntime (R-12).

### Hook de guarda de caminhos (R-07)

Cada subagente em `.claude/agents/` roda `.claude/hooks/guard_paths.py --role <papel>` antes de `Write`, `Edit`, `MultiEdit` e `NotebookEdit`, e a escrita fora do papel é bloqueada. O hook usa o `python3` do sistema (só biblioteca padrão), para funcionar mesmo sem `.venv`. Ele passa a valer depois de reiniciar a sessão do Claude Code.

**Workspace trust:** os hooks do frontmatter dos agentes de projeto só rodam se a pasta tiver a confiança (workspace trust) aceita no Claude Code. Numa máquina ou num clone novo, rode `claude` uma vez na pasta e aceite o diálogo de confiança; uma sessão `claude -p` não conta como aceite. Sem isso, o hook não roda e a escrita fora do papel passa (constatado no CA-23 da SPEC-001, em 2026-10-12).

**Limitação:** o hook **não** intercepta escritas feitas pelo `Bash` (por exemplo, `echo > arquivo` ou `uv lock`). A R-07 continua verificada pelo reviewer com `git log` e os trailers `Agent:` dos commits ([reviews/checklist.md](reviews/checklist.md) §2).
