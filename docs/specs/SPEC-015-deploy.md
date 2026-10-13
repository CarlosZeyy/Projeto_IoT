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

Esta SPEC também fecha as pendências de produção do executor de migrações, deixadas pela SPEC-003 (`reviews/SPEC-003/r1-review-report.md` e `r1-security-report.md`):

- **SPEC_ISSUE-01 / RV-01 / SEC-01:** o `infra/migrate.py` usa `pg_advisory_lock` de sessão. A documentação do Supabase diz que, no modo transaction do pooler (porta 6543), "Session-level state is lost between transactions. This covers `set` and `reset`, session-level advisory locks", e recomenda a conexão direta para migrações; numa rede só IPv4, a alternativa é o pooler em modo session, que é "IPv4-only on every plan" (<https://supabase.com/docs/guides/database/connecting-to-postgres>, consultado em 2026-10-12). Pela 6543, o lock pode ficar preso num backend do pool e a execução seguinte trava sem prazo.
- **SEC-02:** o RLS não cobre `TRUNCATE`, `REFERENCES` e `TRIGGER`. Pelo changelog 45329 do Supabase, tabelas novas do `public` deixam de receber grants automáticos para `anon`/`authenticated` (padrão em projetos novos desde 30/05/2026; aplicado aos projetos existentes em 30/10/2026), mas isso depende da opção escolhida na criação do projeto (<https://supabase.com/changelog/45329-breaking-change-tables-not-exposed-to-data-and-graphql-api-automatically>, consultado em 2026-10-12). A nota da SPEC-003 §7 ("recebem `GRANT` por padrão") está desatualizada; vale o `architecture.md` §5.
- **SEC-03:** as mensagens de erro do executor trazem o `DETAIL` e o `LINE` do servidor.
- **SEC-04:** o `search_path` não é fixado pelo executor.
- **RV-02, RV-03 e RV-04:** ajustes pequenos no mesmo arquivo (§4.7).

E fecha três pendências de operação deixadas pela SPEC-004 (`reviews/SPEC-004/r2-security-report.md`), todas na documentação de deploy (§4.6 e §4.8):

- **SEC-04-02:** toda requisição anônima com chave não vazia de até 256 caracteres, e todo `GET /health`, ocupa uma conexão do pool (máximo de 5, espera de 5 s). Uma rajada anônima pode esgotar o pool, e os dispositivos recebem 503 enquanto ela durar. A API não tem limitação de taxa.
- **SEC-04-03:** `register_device.py --database-url URL` deixa a senha no `argv` (visível em `ps` e em `/proc/<pid>/cmdline`) e no histórico do shell.
- **SEC-04-05:** com o banco fora do ar, o logger `psycopg.pool` registra em `WARNING` o host, a porta e, numa falha de autenticação, o usuário do pooler, sem a senha.

## 2. Objetivo

API, banco e dashboard no ar em free tier sem cartão (R-01), sem nenhum segredo no Git (R-03), com o smoke test passando contra produção e o keep-alive agendado.

## 3. Escopo

### 3.1 Dentro

- `infra/render.yaml` (blueprint).
- `.github/workflows/keepalive.yml` e um passo novo em `.github/workflows/ci.yml` que confere `dashboard/requirements.txt`.
- `dashboard/requirements.txt` (gerado).
- `.streamlit/config.toml` (raiz do repositório).
- `scripts/smoke_test.py`.
- `infra/migrate.py`: só os ajustes da §4.7.
- Testes em `infra/tests/` (`"infra/tests"` já está em `testpaths` desde a SPEC-003).
- `docs/deployment-plan.md` com os valores finais e as datas de verificação; `.env.example` com `DASHBOARD_URL`; `.gitignore` com `.streamlit/secrets.toml`.

### 3.2 Fora

- Código da API e do dashboard → SPECs 004, 005, 006 e 013. Arquivos de migração (`infra/migrations/*.sql`) → SPEC-003; nenhuma migração nova aqui. Registro de dispositivos → `scripts/register_device.py` (SPEC-004).
- Papel de banco só de DML para a API (SEC-05 da SPEC-003): não adotado no MVP; exigiria rever o ADR-006 (RLS sem `force` depende de a API conectar como dona das tabelas).
- Rodar migrações no GitHub Actions: proibido nesta SPEC (§7).
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

1. Supabase: usar o projeto já existente (conta pessoal, sem cartão); seguir o CA-19 (conferir o `search_path` e aplicar as migrações pelo pooler em **modo session**, nunca pela 6543); rodar as consultas do CA-14 (RLS e grants); copiar a connection string do pooler em **modo transaction** (6543) para a `DATABASE_URL` da API.
2. Render: "New → Blueprint" com `infra/render.yaml`; definir `DATABASE_URL` e `READ_API_KEY` (gerada com `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
3. Dispositivos: `register_device.py` para `edge-01` e `sim-01`, com a URL lida do arquivo `.env.migrate` (pooler em modo session, já criado no passo 1): `uv run --env-file .env.migrate --package qc-api python scripts/register_device.py --device-id edge-01` (e o mesmo para `sim-01`). **Nunca** passar a URL de produção por `--database-url`, que a deixaria no `argv` e no histórico do shell (SEC-04-03). Chaves nos `.env` locais.
4. Streamlit CC: app do repositório público, branch `main`, entrypoint `dashboard/app.py`, Python 3.12, Secrets `API_BASE_URL` e `READ_API_KEY`.
5. GitHub: secret `KEEPALIVE_URL` = URL base da API; disparar o workflow manualmente.
6. Rodar `scripts/smoke_test.py` e `scripts/simulate.py --lots 3` contra produção.

### 4.7 Executor de migrações em produção (`infra/migrate.py`)

Mudanças mínimas, todas compatíveis com os CAs da SPEC-003 (os testes de aceite dela continuam passando sem alteração):

1. **Conexão (SPEC_ISSUE-01):** as migrações rodam pela conexão direta (`db.<ref>.supabase.co:5432`, IPv6) ou pelo pooler em **modo session** (`<host>.pooler.supabase.com:5432`, IPv4), nunca pelo modo transaction.
   - Antes de abrir qualquer conexão, `apply_migrations`, `pending_migrations` e a CLI leem a porta efetiva da conninfo (`conninfo_to_dict(...)["port"]`; se ausente, `PGPORT`; com vários hosts, cada porta da lista). Se alguma for `6543`, levantam `UnsupportedConnectionError` (subclasse de `MigrationError`) com a mensagem exata `transaction pooler (port 6543) is not supported for migrations; use the direct connection or the session pooler (port 5432)`. A URL nunca aparece na mensagem.
   - Na CLI, esse erro sai com código `2` (uso inválido), sem conectar.
   - A `DATABASE_URL` da API continua sendo a do modo transaction (ADR-006). Para migrar, o humano usa um arquivo local `.env.migrate` (ignorado pelo `.gitignore`, padrão `.env.*`) com `DATABASE_URL=<URL do pooler em modo session>` e roda `uv run --env-file .env.migrate --package qc-api python infra/migrate.py`. A URL não vai para a linha de comando nem para o histórico do shell.
2. **Prazo do lock (SEC-01):** o `pg_advisory_lock` bloqueante é trocado por `pg_try_advisory_lock` (mesma chave `ADVISORY_LOCK_KEY`), tentado a cada 1 s até `lock_wait_s` segundos. `apply_migrations` ganha o parâmetro só por palavra-chave `lock_wait_s: float = 30.0` (> 0). Sem o lock no prazo → `MigrationError` com uma mensagem que começa com `could not acquire the migration lock within` (seguida do prazo em segundos), nada é aplicado e a CLI sai com código `1`. O `pg_advisory_unlock` do `finally` continua.
3. **Controle de transação no arquivo (RV-02):** dentro da transação de cada migração, o executor lê `select pg_current_xact_id()` antes de executar o arquivo. Depois de executá-lo, se `conn.info.transaction_status` não for `INTRANS`, ou se `pg_current_xact_id()` for diferente do valor anterior, levanta `MigrationError` com uma mensagem que contém `ended the transaction` e o número da migração, por exemplo `migration 002 (002_x.sql) ended the transaction (COMMIT/ROLLBACK/BEGIN in the file); statements before it may have been committed; fix the file and check the database by hand`. A migração não é registrada em `schema_migrations`.
4. **Nome do arquivo (RV-03):** a regex passa a ser `^[0-9]{3}_[a-z0-9_]+\.sql$` (só dígitos ASCII). Um arquivo como `١٢٣_x.sql` gera o mesmo erro de nome inválido, antes de aplicar qualquer coisa.
5. **Leitura única (RV-04):** `load_migrations` lê cada arquivo uma única vez, com `Path.read_bytes()`. `Migration` ganha o campo `content: bytes`, o checksum é o SHA-256 desses bytes e `read_sql()` decodifica `content` sem ler o disco de novo.
6. **Mensagens de erro (SEC-03):** não mudam. Como as migrações de produção só rodam na máquina do humano (§7), o `DETAIL` e o `LINE` do servidor não chegam a nenhum log público.

O `search_path` (SEC-04) não é fixado pelo executor: o humano o confere antes de migrar (CA-19).

### 4.8 Riscos aceitos no `docs/deployment-plan.md` (pendências da SPEC-004)

O autor acrescenta ao `docs/deployment-plan.md` uma seção `## 7. Riscos aceitos` com, no mínimo, estas duas linhas, cada uma com a fonte e a data de verificação:

1. **Rajada anônima ocupando o pool (SEC-04-02).** Efeito: enquanto ela dura, os dispositivos recebem 503; não há perda de dados, porque o outbox da borda reenvia com backoff (SPEC-009). Mitigação no provedor: o Render aplica proteção contra DDoS automática (Cloudflare) em todo serviço web, sem configuração, mas não documenta limitação de taxa configurável pelo cliente; a limitação de taxa na aplicação é responsabilidade de quem publica (<https://render.com/docs/ddos-protection> e <https://render.com/articles/how-render-handles-ddos-attacks>, consultadas pelo architect em 2026-10-13; o autor confere de novo e atualiza a data). Decisão: **risco aceito** no MVP (projeto acadêmico, URL da API não divulgada). Uma limitação de taxa dentro da API só entra por SPEC nova, se o humano pedir.
2. **Log do `psycopg.pool` no Render (SEC-04-05).** Com o banco fora do ar, o log do serviço mostra o host, a porta e, numa falha de autenticação, o usuário do pooler do Supabase. Não são segredos (R-03 continua cumprida, e a senha não aparece). No portão `deploy`, esse log não conta como vazamento. É a exceção prevista na regra "Erros de banco no log" de `docs/architecture.md` §4.

E toda menção a `register_device.py` no `deployment-plan.md` (hoje, a §3 "Chaves de dispositivo" e o passo 3 da §4) segue o passo 3 da §4.6 desta SPEC: o comando completo com `--env-file .env.migrate`, nunca `--database-url` com a URL de produção.

## 5. Critérios de aceite

- **CA-01** — *Dado* `infra/render.yaml` carregado com `yaml.safe_load`, *então* há exatamente 1 serviço com `type=web`, `plan=free`, `runtime=python`, os `buildCommand`, `startCommand` e `healthCheckPath` de §4.1 literalmente, e `envVars` contém `DATABASE_URL` e `READ_API_KEY` com `sync: false` e sem chave `value`.
- **CA-02** — *Dado* `keepalive.yml` carregado, *então* os gatilhos são `schedule` (cron `17 9 */3 * *`) e `workflow_dispatch`, `permissions == {}`, o job tem `timeout-minutes: 10`, o passo usa `secrets.KEEPALIVE_URL` e contém `curl -fsS --retry 5 --retry-delay 30`, e o arquivo não contém `http://` nem `https://` literais.
- **CA-03** — *Dado* o repositório no commit do PR, *quando* rodo `uv export --package qc-dashboard --no-hashes --frozen --no-dev --no-header`, *então* a saída é idêntica a `dashboard/requirements.txt`; e `ci.yml` contém o passo de comparação.
- **CA-04 (R-12)** — *Dado* `dashboard/requirements.txt`, *então* nenhuma linha começa com `torch`, `torchvision`, `timm`, `onnxruntime`, `onnx` ou `psycopg`.
- **CA-05 (R-03)** — *Dado* os arquivos de `git ls-files` fora de `docs/`, *quando* busco `postgres(ql)?://[^\s:/@]+:[^\s@]+@`, `eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}`, `-----BEGIN [A-Z ]*PRIVATE KEY-----` e `service_role\s*[:=]\s*\S{20,}`, *então* não há ocorrência, exceto os marcadores e credenciais de teste conhecidos da lista de permissão (`<user>:<password>`, `postgres:postgres@localhost`, `u:pw@127.0.0.1`, `u:s3cr3t-pw@127.0.0.1`); e, em `.env.example`, as variáveis de segredo (`DEVICE_API_KEY`, `READ_API_KEY`, `SIM_DEVICE_API_KEY`, `DATABASE_URL`, `EDGE_SESSION_TOKEN`) só têm valor vazio ou marcadores `<...>`.
- **CA-06 (R-03)** — *Dado* `.gitignore`, *então* `git check-ignore` ignora `.env`, `.env.prod`, `.env.migrate` e `.streamlit/secrets.toml`, e não ignora `.env.example`.
- **CA-07** — *Dado* `.streamlit/config.toml` carregado com `tomllib`, *então* `browser.gatherUsageStats is False`, `server.headless is True`, `client.showErrorDetails` existe, e não há chave com `key`, `secret` ou `token` no nome.
- **CA-08** — *Dado* a API falsa (`httpx.MockTransport`) correta, *quando* rodo `smoke_test.main` com URLs `https://`, *então* o código é 0, o stdout tem as 7 linhas `PASS` na ordem de §4.5, e a inspeção enviada tem `source=simulated` (R-06).
- **CA-09** — *Dado* a API falsa aceitando leitura **sem** chave (ou escrita sem chave), *então* `FAIL read_requires_key` (ou `FAIL write_requires_key`) e código 1.
- **CA-10** — *Dado* a API falsa devolvendo `access-control-allow-origin: *`, *então* `FAIL cors_closed` e código 1; *dado* `/health` com `db=error` ou `contract_version` diferente, *então* `FAIL health` e código 1.
- **CA-11** — *Dado* `--api-url http://api.exemplo.org` ou `--dashboard-url http://painel.exemplo.org`, ou `READ_API_KEY` ausente, *então* código 2 e 0 requisições.
- **CA-12** — *Dado* qualquer execução do smoke (sucesso ou falha), *então* os valores de `READ_API_KEY` e `SIM_DEVICE_API_KEY` não aparecem no stdout nem no stderr.
- **CA-13 (manual)** — API: 1. `curl -fsS https://<api>/api/v1/health` → 200 com `"db":"ok"` e o `contract_version` atual; 2. depois de 20 min sem tráfego, repetir e anotar o tempo do cold start; 3. `curl -i https://<api>/api/v1/inspections` sem chave → 401.
- **CA-14 (manual, R-03/RNF-06)** — RLS e grants em produção, no SQL Editor: 1. `select relname, relrowsecurity, relforcerowsecurity from pg_class where relname in ('devices','inspections','schema_migrations');` → as 3 linhas com `relrowsecurity = true` e `relforcerowsecurity = false`; 2. `select count(*) from pg_policies where tablename in ('devices','inspections','schema_migrations');` → `0`; 3. `select grantee, table_name, privilege_type from information_schema.role_table_grants where table_schema = 'public' and grantee in ('anon','authenticated');` → se houver linhas, rodar `revoke all on devices, inspections, schema_migrations from anon, authenticated;` e repetir a consulta, que deve voltar vazia (SEC-02; o `revoke` não vai para uma migração, porque esses papéis não existem no Postgres local nem no do CI); 4. chamar a API REST do Supabase em `/rest/v1/inspections` com a chave anon → nenhuma linha retornada, mesmo com dados na tabela; 5. registrar no dev-report a saída das consultas 1 a 3 (sem segredos).
- **CA-15 (manual)** — Smoke em produção: 1. exportar as variáveis em um shell local; 2. `uv run --package qc-api python scripts/smoke_test.py`; 3. as 7 checagens dão `PASS`; 4. colar a saída (sem chaves) no dev-report.
- **CA-16 (manual)** — Keep-alive: 1. disparar `keepalive` por `workflow_dispatch`; 2. o job termina verde em ≤ 10 min; 3. o próximo agendamento aparece na aba Actions.
- **CA-17 (manual)** — Dashboard: 1. publicar no Streamlit CC com `dashboard/requirements.txt`; 2. o log de build mostra a instalação de `qc-contracts` a partir de `packages/contracts` (ou falha → `SPEC_ISSUE`, §4.3); 3. depois de `simulate.py --lots 3`, o dashboard abre e mostra o selo "simulado"; 4. registrar o resultado e a data no `deployment-plan.md`.
- **CA-18 (manual, R-01)** — Para cada serviço (Supabase, Render, Streamlit CC, GitHub Actions), a dupla confirma que a conta foi criada e o recurso publicado **sem cartão**, e o `deployment-plan.md` §2 tem fonte e "Verificado em" com data desta SPEC.
- **CA-19 (manual, SEC-04 e SPEC_ISSUE-01 da SPEC-003)** — Migração em produção: 1. no SQL Editor, `show search_path;` e `select current_schema();` → o schema corrente é `public` (se não for, parar e registrar `SPEC_ISSUE`); 2. criar `.env.migrate` com a URL do pooler em **modo session** (porta 5432) e conferir com `git status` que ele não aparece; 3. `uv run --env-file .env.migrate --package qc-api python infra/migrate.py --status` → lista as pendentes e sai com 0; 4. `uv run --env-file .env.migrate --package qc-api python infra/migrate.py` → sai com 0; 5. repetir o passo 3 → `0 pending`; 6. registrar no dev-report as saídas dos passos 1, 3, 4 e 5.
- **CA-20 (SPEC_ISSUE-01)** — *Dado* `--database-url postgresql://u:s3cr3t-pw@127.0.0.1:6543/x_test`, ou `postgresql://u@h1:5432,h2:6543/x_test`, ou uma URL sem porta com `PGPORT=6543` no ambiente, *quando* se roda a CLI (com e sem `--status`) e quando se chamam `apply_migrations` e `pending_migrations` com a mesma conninfo, *então* a CLI sai com código 2 e o stderr contém `transaction pooler (port 6543) is not supported for migrations`; as funções levantam `UnsupportedConnectionError` (instância de `MigrationError`) com a mesma mensagem; um listener TCP local na porta usada recebe 0 conexões; e `s3cr3t-pw` não aparece no stdout, no stderr nem na mensagem da exceção.
- **CA-21 (SEC-01)** — *Dado* o banco de teste e outra sessão segurando `pg_advisory_lock(ADVISORY_LOCK_KEY)`, *quando* `apply_migrations(conninfo, <dir com 001>, lock_wait_s=1)` roda num schema vazio, *então* levanta `MigrationError` cuja mensagem começa com `could not acquire the migration lock within`, em menos de 5 s, e `schema_migrations` não existe; e, depois que a outra sessão libera o lock, a mesma chamada retorna `["001"]`. `apply_migrations(..., lock_wait_s=0)` levanta `ValueError`.
- **CA-22 (RV-02)** — *Dado* um diretório temporário com a cópia de `001_init.sql` e `002_tx.sql` contendo `create table t_tx(id int); commit;`, *quando* `apply_migrations` roda num schema vazio, *então* levanta `MigrationError` cuja mensagem contém `ended the transaction` e `002`, e `schema_migrations` contém só `001`; e o mesmo vale para um `002_tx.sql` com `create table t_tx2(id int); commit; begin;`.
- **CA-23 (RV-03)** — *Dado* um diretório temporário com a cópia de `001_init.sql` e um arquivo `١٢٣_x.sql` (dígitos arábico-índicos), *quando* `apply_migrations` roda, *então* levanta `MigrationError` de nome de arquivo inválido antes de aplicar qualquer migração (`schema_migrations` não existe ou está vazia).
- **CA-24 (RV-04)** — *Dado* um diretório temporário com a cópia de `001_init.sql` e um espião em `pathlib.Path.read_bytes` que conta as chamadas por caminho, *quando* `apply_migrations` roda num schema vazio, *então* `001_init.sql` é lido exatamente 1 vez, e o `checksum` gravado em `schema_migrations` é o SHA-256 dos bytes devolvidos nessa leitura.
- **CA-25 (SEC-04-02, SEC-04-03, SEC-04-05)** — *Dado* o texto de `docs/deployment-plan.md`, *então*:
  - há uma seção de nível 2 cujo título contém `Riscos aceitos`; no trecho dela até o próximo título de nível 2, uma linha contém `pool` e `503`, outra contém `psycopg.pool`, e o trecho contém `render.com/docs/ddos-protection`;
  - toda linha que contém `register_device.py` contém também `--env-file` e não contém `--database-url`.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | YAML/TOML, requirements, busca de segredos, smoke com `MockTransport`; ajustes do executor (§4.7) | `infra/tests/` |
| Aceite (tester) | CA-01…CA-12 e CA-20…CA-25 (CA-21 a CA-24 marcados `db`) | `infra/tests/acceptance/test_spec_015.py` |
| Manual (dupla + autor) | CA-13…CA-19 | produção; resultado no dev-report e no `deployment-plan.md` |

Nenhum teste automatizado acessa a internet nem os serviços reais. O smoke é importado por `importlib.util.spec_from_file_location`. Os testes do executor usam o Postgres de teste da SPEC-003 (fixtures de `conftest.py`, com banco temporário próprio quando precisam de schema vazio), sem mock de banco.

## 7. Riscos e notas para o implementador

- A allowlist do `security-devops` (SPEC-001 §4.6) já cobre todos os caminhos que esta SPEC exige: `infra/**`, `.github/**`, `dashboard/requirements.txt`, `.streamlit/**`, `scripts/smoke_test.py`, `.env.example`, `.gitignore`, `pyproject.toml`, `uv.lock` e `docs/deployment-plan.md`.
- `uv run` sincroniza o ambiente antes de rodar e, por padrão, inclui o grupo `dev`. Se o log do Render mostrar instalação no start, use `uv run --frozen --no-dev --package qc-api ...` e atualize §4.1, o `deployment-plan.md` e o CA-01 por `SPEC_ISSUE`.
- Os limites de free tier mudam: confira cada um na fonte oficial antes de fixar e atualize "Verificado em" (inclusive as regras do GitHub Actions para repositório público, hoje "a verificar na SPEC-015 (CA-18)").
- Os testes que conferem a detecção do CA-05 devem montar os exemplos de segredo por concatenação em tempo de execução, para o próprio arquivo de teste não casar com os padrões.
- Workflows agendados podem atrasar alguns minutos; o intervalo de 3 dias tem folga contra a pausa de 7 dias do Supabase.
- **Migrações nunca rodam no GitHub Actions contra produção** (SEC-03 da SPEC-003): o repositório é público e os logs do Actions também, e o executor mostra o `DETAIL` e o `LINE` do servidor. Se um dia isso mudar, o executor passa a mostrar só o `sqlstate` e o `diag.message_primary`, numa SPEC nova.
- **Por que conexão direta/modo session, e não `pg_advisory_xact_lock`:** o lock de transação exigiria pegar o lock e refazer o plano dentro de cada migração, um redesenho do executor aprovado na SPEC-003. A recomendação oficial do Supabase para migrações é a conexão direta (§1), e o modo session é o equivalente em IPv4. O prazo do lock (§4.7, item 2) continua valendo como defesa, inclusive na conexão direta.
- A recusa da porta 6543 é uma heurística: ela cobre o caso real (a `DATABASE_URL` da API usada por engano), não um pooler numa porta não padrão.
- O CA-20 da SPEC-003 usa a porta 1 e continua passando; nenhum CA da SPEC-003 muda.

## 8. Definição de pronto

- [ ] Todos os CAs automatizados com teste de aceite passando (test-report PASS) e CA-13…19 registrados
- [ ] review-report APPROVED + security-report PASS (feito pelo **reviewer**)
- [ ] CI verde; `ruff` limpo
- [ ] `docs/deployment-plan.md` com os valores finais, URLs públicas (sem segredos) e datas; `.env.example` atualizado
- [ ] PR aberto com os relatórios; merge humano

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-12 | Mudanças: (a) §1 com as pendências de produção da SPEC-003; (b) §3.1 inclui `infra/migrate.py` (só a §4.7) e corrige a nota de `testpaths`; §3.2 registra o papel só de DML como não adotado e proíbe migrações no Actions; (c) §4.6, passo 1: migração pelo pooler em modo session, com `.env.migrate`; (d) §4.7 nova: recusa da porta 6543, prazo do lock com `pg_try_advisory_lock` (`lock_wait_s`, padrão 30 s), detecção de controle de transação no arquivo, regex só com dígitos ASCII e leitura única do arquivo; (e) CA-06 ganhou `.env.migrate`; CA-14 ganhou `schema_migrations`, `relforcerowsecurity` e a verificação de grants de `anon`/`authenticated`; CAs novos: CA-19 (manual, `search_path` e migração) e CA-20 a CA-24 (executor). Nenhuma decisão de ADR muda: a API continua no modo transaction (ADR-006). SPEC marcada como "Aguardando reaprovação humana". | SPEC_ISSUE-01 e RV-02 a RV-04 de `reviews/SPEC-003/r1-review-report.md`; SEC-01 a SEC-05 de `reviews/SPEC-003/r1-security-report.md` | Orquestrador, a pedido do humano |
| 2026-10-12 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
| 2026-10-13 | Mudanças: (a) §1 com as três pendências de operação da SPEC-004; (b) §4.6, passo 3: registro de dispositivos com `--env-file .env.migrate`, nunca `--database-url` com a URL de produção; (c) §4.8 nova: seção "Riscos aceitos" no `deployment-plan.md` (rajada anônima no pool, com a verificação do Render, e o log do `psycopg.pool`); (d) CA-25 novo; (e) §6 atualizada. Nenhum CA existente muda. SPEC marcada como "Aguardando reaprovação humana". | SEC-04-02, SEC-04-03 e SEC-04-05 de `reviews/SPEC-004/r2-security-report.md` | Orquestrador, a pedido do humano |
| 2026-10-13 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
