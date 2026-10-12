# SPEC-015: Deploy e keep-alive

| Campo | Valor |
|---|---|
| Status | Ready |
| Rodada atual | — |
| Autor da implementação | security-devops |
| Tags | deploy, security |
| Depende de | SPEC-004, SPEC-013 (e, por elas, SPEC-003, SPEC-005, SPEC-006) |
| Semana alvo | S4 |
| Requisitos cobertos | RNF-01, RNF-06, RNF-10, RF-15 |
| ADRs relevantes | ADR-006, ADR-007, ADR-008, ADR-010, ADR-015 |

## 1. Contexto

Publica a nuvem descrita em `docs/architecture.md` §1, §4 e §5 nos serviços de ADR-008, seguindo `docs/deployment-plan.md` (que este autor mantém). O keep-alive impede a pausa do Supabase chamando `/api/v1/health`. Os agentes não têm acesso às contas: tudo que exige painel de provedor é **passo humano**, descrito aqui e verificado depois. Como o autor é o `security-devops`, o portão de segurança é feito pelo **reviewer** (`reviews/README.md`).

## 2. Objetivo

API, banco e dashboard no ar em free tier sem cartão (R-01), sem nenhum segredo no Git (R-03), com o smoke test passando contra produção e o keep-alive agendado.

## 3. Escopo

### 3.1 Dentro

- `infra/render.yaml` (blueprint).
- `.github/workflows/keepalive.yml` e um passo novo em `.github/workflows/ci.yml` que confere `dashboard/requirements.txt`.
- `dashboard/requirements.txt` (gerado).
- `.streamlit/config.toml` (raiz do repositório).
- `scripts/smoke_test.py`.
- Testes em `infra/tests/` e `"infra/tests"` em `testpaths` (SPEC-001 §4).
- `docs/deployment-plan.md` com os valores finais e as datas de verificação; `.env.example` com `DASHBOARD_URL`; `.gitignore` com `.streamlit/secrets.toml`.

### 3.2 Fora

- Código da API e do dashboard → SPECs 004, 005, 006 e 013. Migrações → SPEC-003. Registro de dispositivos → `scripts/register_device.py` (SPEC-004).
- Deploy no Koyeb (reserva): só documentado; executar exige nova decisão humana.
- Alertas → SPEC-017.

## 4. Requisitos detalhados

### 4.1 `infra/render.yaml`

Um serviço `type: web`, `runtime: python`, `plan: free`, `name: partqc-api`, `branch: main`, com:
- `buildCommand: pip install uv && uv sync --package qc-api --frozen --no-dev`
- `startCommand: uv run --package qc-api uvicorn qc_api.main:app --host 0.0.0.0 --port $PORT`
- `healthCheckPath: /api/v1/health`
- `envVars`: `PYTHON_VERSION` (3.12 completa, igual à do CI), `DATABASE_URL` e `READ_API_KEY` com `sync: false` e **sem** `value`.
- Região: a mais próxima do projeto Supabase entre as oferecidas no plano free (registrar a escolha e a fonte no `deployment-plan.md`).

### 4.2 `.github/workflows/keepalive.yml`

- Gatilhos: `schedule` com `cron: "17 9 */3 * *"` (intervalo máximo de 3 dias) e `workflow_dispatch`.
- `permissions: {}`; um job `ping` em runner Linux hospedado, `timeout-minutes: 10`.
- Passo único: falha com mensagem se `secrets.KEEPALIVE_URL` estiver vazio; senão `curl -fsS --retry 5 --retry-delay 30 "$KEEPALIVE_URL/api/v1/health"`. A URL vem só do secret (nada fixo no arquivo).

### 4.3 `dashboard/requirements.txt`

- Gerado por `uv export --package qc-dashboard --no-hashes --frozen --no-dev --no-header > dashboard/requirements.txt` (o `--no-header` evita diferença espúria no cabeçalho).
- Passo no CI (depois de `uv sync`): `uv export ... --no-header | diff -u dashboard/requirements.txt -`; diferença → CI falha.
- **Primário:** usar o arquivo como o `uv export` gerar, inclusive a linha editável da dependência local (`-e ./packages/contracts`). O autor verifica no Streamlit Community Cloud se ela instala (CA-17).
- **Fallback (não implementar aqui):** se a linha local não instalar, o autor para e registra `SPEC_ISSUE` para o architect. A alternativa a avaliar é o dashboard **não** depender de `qc-contracts` na instalação (parsing mínimo próprio do JSON da API e checagem de `contract_version` via `/health`). Cópia vendorizada ou gerada do pacote **não** é permitida. Isso contraria ADR-007 e a skill `contrato-api`, por isso exige decisão do architect e do humano.

### 4.4 `.streamlit/config.toml`

`[browser] gatherUsageStats = false`; `[server] headless = true`; `[client] showErrorDetails` com o valor que **oculta** detalhes de erro na versão do Streamlit travada no `uv.lock` (conferir na documentação e citar no dev-report). Nenhum segredo: `API_BASE_URL` e `READ_API_KEY` ficam em Secrets do painel.

### 4.5 `scripts/smoke_test.py`

`main(argv=None, *, transport=None) -> int`. Argumentos: `--api-url` (env `CLOUD_API_URL`), `--dashboard-url` (env `DASHBOARD_URL`); chaves só por env: `READ_API_KEY`, `SIM_DEVICE_ID`, `SIM_DEVICE_API_KEY`. URLs precisam ser `https://` (exceto `localhost`/`127.0.0.1`); variável ausente ou URL inválida → código 2. Checagens, em ordem, cada uma imprimindo `PASS <nome>` ou `FAIL <nome>: <motivo>`:

1. `health`: `GET /api/v1/health` (timeout 90 s) → 200, `status=ok`, `db=ok`, `contract_version == qc_contracts.__version__`.
2. `write_requires_key`: `POST /api/v1/inspections` sem `X-API-Key` → 401.
3. `write`: 1 `InspectionCreate` com `source=simulated`, `lot_id=SMOKE-<AAAAMMDDTHHMMSSZ>`, `model_version=smoke-v0`, `model_sha256="0"*64` → 201 `created`.
4. `read_requires_key`: `GET /api/v1/inspections` sem chave → 401.
5. `read`: `GET /api/v1/inspections?lot_id=<lote>&source=simulated` com `READ_API_KEY` → `total == 1` e o mesmo `inspection_id`.
6. `cors_closed`: `GET /api/v1/health` com `Origin: https://example.org` → sem header `access-control-allow-origin`.
7. `dashboard`: `GET <dashboard-url>` (segue redirecionamentos, timeout 60 s) → 200.

Código 0 se todas passarem; 1 se alguma falhar. Nenhuma chave é impressa.

### 4.6 Passos humanos (ordem; o autor escreve as instruções exatas no `deployment-plan.md` §4)

1. Supabase: criar `partqc-prod` sem cartão; aplicar `infra/migrations/*.sql`; rodar as consultas do CA-14; copiar a connection string do pooler.
2. Render: "New → Blueprint" com `infra/render.yaml`; definir `DATABASE_URL` e `READ_API_KEY` (gerada com `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
3. Dispositivos: `register_device.py` para `edge-01` e `sim-01`; chaves nos `.env` locais.
4. Streamlit CC: app do repositório privado, branch `main`, entrypoint `dashboard/app.py`, Python 3.12, Secrets `API_BASE_URL` e `READ_API_KEY`.
5. GitHub: secret `KEEPALIVE_URL` = URL base da API; disparar o workflow manualmente.
6. Rodar `scripts/smoke_test.py` e `scripts/simulate.py --lots 3` contra produção.

## 5. Critérios de aceite

- **CA-01** — *Dado* `infra/render.yaml` carregado com `yaml.safe_load`, *então* há exatamente 1 serviço com `type=web`, `plan=free`, `runtime=python`, os `buildCommand`, `startCommand` e `healthCheckPath` de §4.1 literalmente, e `envVars` contém `DATABASE_URL` e `READ_API_KEY` com `sync: false` e sem chave `value`.
- **CA-02** — *Dado* `keepalive.yml` carregado, *então* os gatilhos são `schedule` (cron `17 9 */3 * *`) e `workflow_dispatch`, `permissions == {}`, o job tem `timeout-minutes: 10`, o passo usa `secrets.KEEPALIVE_URL` e contém `curl -fsS --retry 5 --retry-delay 30`, e o arquivo não contém `http://` nem `https://` literais.
- **CA-03** — *Dado* o repositório no commit do PR, *quando* rodo `uv export --package qc-dashboard --no-hashes --frozen --no-dev --no-header`, *então* a saída é idêntica a `dashboard/requirements.txt`; e `ci.yml` contém o passo de comparação.
- **CA-04 (R-12)** — *Dado* `dashboard/requirements.txt`, *então* nenhuma linha começa com `torch`, `torchvision`, `timm`, `onnxruntime`, `onnx` ou `psycopg`.
- **CA-05 (R-03)** — *Dado* os arquivos de `git ls-files` fora de `docs/`, *quando* busco `postgres(ql)?://[^\s:/@]+:[^\s@]+@`, `eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}`, `-----BEGIN [A-Z ]*PRIVATE KEY-----` e `service_role\s*[:=]\s*\S{20,}`, *então* não há ocorrência, exceto os marcadores e credenciais de teste conhecidos da lista de permissão (`<user>:<password>`, `postgres:postgres@localhost`, `u:pw@127.0.0.1`, `u:s3cr3t-pw@127.0.0.1`); e, em `.env.example`, as variáveis de segredo (`DEVICE_API_KEY`, `READ_API_KEY`, `SIM_DEVICE_API_KEY`, `DATABASE_URL`, `EDGE_SESSION_TOKEN`) só têm valor vazio ou marcadores `<...>`.
- **CA-06 (R-03)** — *Dado* `.gitignore`, *então* `git check-ignore` ignora `.env`, `.env.prod` e `.streamlit/secrets.toml`, e não ignora `.env.example`.
- **CA-07** — *Dado* `.streamlit/config.toml` carregado com `tomllib`, *então* `browser.gatherUsageStats is False`, `server.headless is True`, `client.showErrorDetails` existe, e não há chave com `key`, `secret` ou `token` no nome.
- **CA-08** — *Dado* a API falsa (`httpx.MockTransport`) correta, *quando* rodo `smoke_test.main` com URLs `https://`, *então* o código é 0, o stdout tem as 7 linhas `PASS` na ordem de §4.5, e a inspeção enviada tem `source=simulated` (R-06).
- **CA-09** — *Dado* a API falsa aceitando leitura **sem** chave (ou escrita sem chave), *então* `FAIL read_requires_key` (ou `FAIL write_requires_key`) e código 1.
- **CA-10** — *Dado* a API falsa devolvendo `access-control-allow-origin: *`, *então* `FAIL cors_closed` e código 1; *dado* `/health` com `db=error` ou `contract_version` diferente, *então* `FAIL health` e código 1.
- **CA-11** — *Dado* `--api-url http://api.exemplo.org` ou `--dashboard-url http://painel.exemplo.org`, ou `READ_API_KEY` ausente, *então* código 2 e 0 requisições.
- **CA-12** — *Dado* qualquer execução do smoke (sucesso ou falha), *então* os valores de `READ_API_KEY` e `SIM_DEVICE_API_KEY` não aparecem no stdout nem no stderr.
- **CA-13 (manual)** — API: 1. `curl -fsS https://<api>/api/v1/health` → 200 com `"db":"ok"` e o `contract_version` atual; 2. depois de 20 min sem tráfego, repetir e anotar o tempo do cold start; 3. `curl -i https://<api>/api/v1/inspections` sem chave → 401.
- **CA-14 (manual, R-03/RNF-06)** — RLS em produção, no SQL Editor: 1. `select relname, relrowsecurity from pg_class where relname in ('devices','inspections');` → as 2 linhas com `true`; 2. `select count(*) from pg_policies where tablename in ('devices','inspections');` → `0`; 3. chamar a API REST do Supabase em `/rest/v1/inspections` com a chave anon → nenhuma linha retornada, mesmo com dados na tabela.
- **CA-15 (manual)** — Smoke em produção: 1. exportar as variáveis em um shell local; 2. `uv run --package qc-api python scripts/smoke_test.py`; 3. as 7 checagens dão `PASS`; 4. colar a saída (sem chaves) no dev-report.
- **CA-16 (manual)** — Keep-alive: 1. disparar `keepalive` por `workflow_dispatch`; 2. o job termina verde em ≤ 10 min; 3. o próximo agendamento aparece na aba Actions.
- **CA-17 (manual)** — Dashboard: 1. publicar no Streamlit CC com `dashboard/requirements.txt`; 2. o log de build mostra a instalação de `qc-contracts` a partir de `packages/contracts` (ou falha → `SPEC_ISSUE`, §4.3); 3. depois de `simulate.py --lots 3`, o dashboard abre e mostra o selo "simulado"; 4. registrar o resultado e a data no `deployment-plan.md`.
- **CA-18 (manual, R-01)** — Para cada serviço (Supabase, Render, Streamlit CC, GitHub Actions), a dupla confirma que a conta foi criada e o recurso publicado **sem cartão**, e o `deployment-plan.md` §2 tem fonte e "Verificado em" com data desta SPEC.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | YAML/TOML, requirements, busca de segredos, smoke com `MockTransport` | `infra/tests/` |
| Aceite (tester) | CA-01…CA-12 | `infra/tests/acceptance/test_spec_015.py` |
| Manual (dupla + autor) | CA-13…CA-18 | produção; resultado no dev-report e no `deployment-plan.md` |

Nenhum teste automatizado acessa a internet nem os serviços reais. O smoke é importado por `importlib.util.spec_from_file_location`.

## 7. Riscos e notas para o implementador

- A allowlist do `security-devops` (SPEC-001 §4.6) já cobre todos os caminhos que esta SPEC exige: `infra/**`, `.github/**`, `dashboard/requirements.txt`, `.streamlit/**`, `scripts/smoke_test.py`, `.env.example`, `.gitignore`, `pyproject.toml`, `uv.lock` e `docs/deployment-plan.md`.
- `uv run` sincroniza o ambiente antes de rodar e, por padrão, inclui o grupo `dev`. Se o log do Render mostrar instalação no start, use `uv run --frozen --no-dev --package qc-api ...` e atualize §4.1, o `deployment-plan.md` e o CA-01 por `SPEC_ISSUE`.
- Os limites de free tier mudam: confira cada um na fonte oficial antes de fixar e atualize "Verificado em" (inclusive a cota do GitHub Actions para repositório privado, hoje "a verificar na SPEC-015 (CA-18)").
- Os testes que conferem a detecção do CA-05 devem montar os exemplos de segredo por concatenação em tempo de execução, para o próprio arquivo de teste não casar com os padrões.
- Workflows agendados podem atrasar alguns minutos; o intervalo de 3 dias tem folga contra a pausa de 7 dias do Supabase.

## 8. Definição de pronto

- [ ] Todos os CAs automatizados com teste de aceite passando (test-report PASS) e CA-13…18 registrados
- [ ] review-report APPROVED + security-report PASS (feito pelo **reviewer**)
- [ ] CI verde; `ruff` limpo
- [ ] `docs/deployment-plan.md` com os valores finais, URLs públicas (sem segredos) e datas; `.env.example` atualizado
- [ ] PR aberto com os relatórios; merge humano
