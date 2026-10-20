# SPEC-015: Deploy na VPS pessoal (Docker Compose + Caddy), banco no Supabase e keep-alive

| Campo | Valor |
|---|---|
| Status | In Security |
| Rodada atual | r1 |
| Autor da implementação | security-devops |
| Tags | deploy, security, infra |
| Depende de | SPEC-004, SPEC-013, SPEC-026 (teto da carta p; sem ele, a rota SPC pode passar dos 512 MB da API), SPEC-027 (migração `002` e simulador corrigido), SPEC-028 (recusa de `API_BASE_URL` sem `https://`) (e, por elas, SPEC-003, SPEC-005, SPEC-006, SPEC-014) |
| Semana alvo | S4 |
| Requisitos cobertos | RNF-01, RNF-06, RNF-10, RF-15; R-01, R-02, R-03, R-12, R-13, R-14 |
| ADRs relevantes | ADR-006, ADR-007, ADR-008 (banco e keep-alive), ADR-010, ADR-015, ADR-016, ADR-017, ADR-018 |

> **Reaprovada pelo humano em 2026-10-19**: correção do SPEC_ISSUE-01 de `reviews/SPEC-015/r1-dev-report.md` (escopo e lista de permissão do CA-05). Classificação ADR-019: exige humano (X-7). Ver o Histórico.

## 1. Contexto

Publica a nuvem descrita em `docs/architecture.md` §1, §4, §5 e §8 conforme o **ADR-018**. A `qc-api` e o `qc-dashboard` rodam na VPS pessoal do humano, com Docker Compose, atrás de um Caddy que publica só as portas 80 e 443 de um único subdomínio pessoal. O banco continua no Supabase (ADR-006, ADR-008), e o Render vira a reserva fria da API. O Streamlit Community Cloud e o Koyeb saem do plano. O guia de operação é o `docs/deployment-plan.md`, mantido por este autor.

Os agentes não têm acesso à VPS nem às contas: tudo que roda na VPS, no painel do Supabase, no DNS ou no GitHub é **passo humano**, descrito aqui e verificado depois. Como o autor é o `security-devops`, o portão de segurança é feito pelo **reviewer** (`reviews/README.md`). O subdomínio real e o IP da VPS **nunca** entram no repositório (R-13): a documentação usa `<subdominio>`, e o valor real fica em `PUBLIC_HOST`, no `infra/.env` da VPS.

Fatos externos conferidos pelo architect em 2026-10-18 (as fontes ficam no ADR-018; o autor confere de novo os que fixar no `deployment-plan.md` e atualiza a data):

- portas publicadas pelo Docker passam por fora do `ufw` (<https://docs.docker.com/engine/network/packet-filtering-firewalls/>);
- com o BuildKit, o `<Dockerfile>.dockerignore` ao lado do Dockerfile tem precedência sobre o `.dockerignore` da raiz (<https://docs.docker.com/build/concepts/context/>);
- o `uv sync` instala os membros do workspace em modo editável por padrão; a imagem oficial do `uv` é copiada com `COPY --from=ghcr.io/astral-sh/uv:<versão> /uv /uvx /bin/`, e a documentação recomenda fixar a versão, `UV_PYTHON_DOWNLOADS=0` para usar o Python da imagem e `.venv` no `.dockerignore` (<https://docs.astral.sh/uv/guides/integration/docker/>);
- as tags atuais são `python:3.12.15-slim-trixie` (<https://hub.docker.com/_/python>) e `caddy:2.11.7` (<https://hub.docker.com/_/caddy>);
- o Caddy repassa WebSocket e o header `Host` sem configuração (<https://caddyserver.com/docs/caddyfile/directives/reverse_proxy>) e aceita `{$VAR}` no endereço do site (<https://caddyserver.com/docs/caddyfile/concepts>);
- o Streamlit lê o `.streamlit/config.toml` da pasta de onde se roda o `streamlit run`, e `enableCORS` e `enableXsrfProtection` são `true` por padrão (<https://docs.streamlit.io/develop/api-reference/configuration/config.toml>); o healthcheck do tutorial de Docker usa `/_stcore/health` (<https://docs.streamlit.io/deploy/tutorials/docker>);
- no `.env` do Compose, valores sem aspas ou com aspas duplas sofrem interpolação (`$`), e valores com aspas simples são literais (<https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/>).

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

E fecha as pendências de operação deixadas pelas SPECs 005, 006 e 014 (§4.9):

- **SEC-05-01** (`reviews/SPEC-005/r1-security-report.md`): as consultas da API não têm `statement_timeout`. No Supabase, o papel `postgres` não tem timeout próprio e fica sujeito ao teto global de 2 min (<https://supabase.com/docs/guides/database/postgres/timeouts>, consultado pelo architect em 2026-10-17). Leituras pesadas do dashboard podem ocupar as 5 conexões do pool, e a escrita da borda recebe 503.
- **INFO-02** (mesmo relatório): geração da `READ_API_KEY`, separada das chaves de dispositivo, e a ordem da troca (API e dashboard juntos).
- **Limite de memória da API** (`reviews/SPEC-006/r1-security-report.md`, checklist de deploy): o plano gratuito do Render, hoje a reserva, tem **512 MB de RAM e 0,1 CPU** (<https://render.com/docs/compute-plans>, tabela "Web service plans", linha `free`, consultado pelo architect em 2026-10-17). Na VPS, o mesmo valor é o padrão do `mem_limit` da API (§4.12). O SEC-06-01 (média) mostrou que a rota SPC sem teto passava desse limite. Ele é corrigido pela SPEC-026, que por isso é dependência desta.
- **SEC-07 e a mitigação do SEC-01** (`reviews/SPEC-014/r1-security-report.md`): uma execução válida do simulador pode enviar 500 000 itens e consumir a cota do banco gratuito; e, até a SPEC-027, o argparse do simulador repetia no stderr uma chave digitada na opção errada.

E as pendências de deploy dos portões das SPECs 013, 026 e 027 (todas já mergeadas):

- **RV-06** de `reviews/SPEC-013/r1-review-report.md`: o `REPO_ROOT` do dashboard é calculado a partir do `__file__` do pacote `qc_dashboard`. Instalado de forma não editável (em `site-packages`), ele aponta para fora do repositório, e a página "Sobre o modelo" esconde as métricas sem erro visível. Resolvido pela imagem do dashboard (§4.3).
- **SEC-13-01** de `reviews/SPEC-013/r2-security-report.md` (parte de deploy): `API_BASE_URL` é sempre `https://`. O compose a define como `https://${PUBLIC_HOST}` (§4.12). A recusa de `http://` no código é da SPEC-028.
- **SEC-26-02** de `reviews/SPEC-026/r1-security-report.md`: uma consulta cancelada pelo `statement_timeout` responde **503** `Database unavailable`, e não o 500 genérico, porque o `QueryCanceled` é subclasse de `psycopg.OperationalError` (§4.9, item 1).
- **SEC-26-03** do mesmo relatório: o `EXPLAIN ANALYZE` da carta usa a consulta nova da SPEC-026 (`SELECT_LOT_SELECTION`), e o valor fica no padrão de `15s`, porque a medição em produção é feita com poucos lotes (§4.9, item 1; CA-26).
- **SEC-02** de `reviews/SPEC-027/r1-security-report.md`: a `002` é idempotente por nome; depois de migrar a produção, as definições das 4 restrições são conferidas com `pg_get_constraintdef` (CA-19).

## 2. Objetivo

API e dashboard no ar na VPS pessoal, em `https://<subdominio>`, sem custo adicional e sem cartão (R-01). Só o Caddy expõe portas, nenhum segredo vai para o Git nem para as imagens (R-03), e as imagens não contêm ML (R-12) nem dados ou fotos (R-02, R-14). O smoke test passa contra produção, e a pausa do Supabase é evitada pelo healthcheck da API e pelo keep-alive agendado.

## 3. Escopo

### 3.1 Dentro

- `infra/docker/api.Dockerfile` e `infra/docker/dashboard.Dockerfile` (§4.10).
- `infra/docker/api.Dockerfile.dockerignore` e `infra/docker/dashboard.Dockerfile.dockerignore` (§4.11).
- `infra/compose.yaml` (§4.12) e `infra/Caddyfile` (§4.13).
- `infra/render.yaml`, a reserva fria da API (§4.1).
- `.github/workflows/keepalive.yml` (§4.2) e `.github/workflows/docker.yml` (§4.14). O `ci.yml` **não** muda.
- `.streamlit/config.toml`, na raiz do repositório (§4.4).
- `scripts/smoke_test.py` (§4.5).
- `infra/migrate.py`: só os ajustes da §4.7.
- `pyproject.toml`: só o marcador `docker` (§4.14).
- Testes em `infra/tests/` (`"infra/tests"` já está em `testpaths` desde a SPEC-003), inclusive `infra/tests/docker_support.py` e os hooks do marcador em `infra/tests/conftest.py` (§4.14).
- `docs/deployment-plan.md` com os passos da VPS, os valores finais e as datas de verificação (§4.6, §4.8, §4.9, §4.15, §4.16).
- `.env.example`: o bloco `infra/.env` da VPS, o `CLOUD_API_URL` e o `DASHBOARD_URL` com marcadores (§4.12).
- `.gitignore`: conferir que cobre `infra/.env`, `infra/.env.api` e `infra/.env.dashboard`. Os padrões `.env` e `.env.*` já cobrem; mudar o arquivo só se o CA-06 falhar.

### 3.2 Fora

- Código da API e do dashboard → SPECs 004, 005, 006, 013, 026 e 028. A mensagem "API acordando (free tier)" do dashboard fica como está: a SPEC-028 a declarou sem mudança, e uma troca de texto entra numa SPEC futura do dashboard.
- Arquivos de migração (`infra/migrations/*.sql`) → SPEC-003 (`001`) e SPEC-027 (`002`); nenhuma migração nova aqui. O `statement_timeout` é configurado no papel do banco (§4.9), não por migração nem no código da API. Registro de dispositivos → `scripts/register_device.py` (SPEC-004).
- `dashboard/requirements.txt` e o deploy no Streamlit Community Cloud: **removidos** pelo ADR-018. O arquivo não é criado, e o `ci.yml` não ganha passo de comparação.
- Koyeb: removido pelo ADR-018.
- Deploy automático (o GitHub Actions entrando na VPS por SSH) e registro de imagens (GHCR): **proibidos** nesta SPEC. Exigiriam uma credencial da VPS, que hospeda outros projetos, nos Secrets do GitHub. O build é feito na própria VPS.
- Rotas públicas `/docs` e `/openapi.json` da API: não roteadas pelo Caddy (ADR-018, decisão 4). Publicá-las exige decisão humana e uma emenda desta SPEC.
- Limitação de taxa no Caddy (plugin `rate_limit`, build próprio): não adotada; risco aceito (§4.8). Entra por SPEC nova, se o humano pedir.
- Papel de banco só de DML para a API (SEC-05 da SPEC-003): não adotado no MVP; exigiria rever o ADR-006 (o RLS sem `force` depende de a API conectar como dona das tabelas).
- Rodar migrações no GitHub Actions: proibido (§7).
- Configuração do sistema operacional da VPS (atualizações, SSH, usuários, ativação do `ufw`): responsabilidade do humano, fora do loop. Esta SPEC só **confere** o firewall e **acrescenta** regras (§4.15).
- Alertas → SPEC-017.

## 4. Requisitos detalhados

### 4.1 Reserva fria da API: `infra/render.yaml`

O blueprint fica versionado, mas **não é publicado** no deploy normal. Ele só é usado num incidente, conforme a §4.16, item 5. O conteúdo é o de antes: um serviço `type: web`, `runtime: python`, `plan: free`, `name: partqc-api`, `branch: main`, com:

- `buildCommand: pip install uv && uv sync --package qc-api --frozen --no-dev`
- `startCommand: uv run --package qc-api uvicorn qc_api.main:app --host 0.0.0.0 --port $PORT`
- `healthCheckPath: /api/v1/health`
- `envVars`: `PYTHON_VERSION` (a mesma `3.12.<patch>` da imagem base da §4.10), e `DATABASE_URL` e `READ_API_KEY` com `sync: false` e **sem** `value`.
- Região: a mais próxima do projeto Supabase entre as oferecidas no plano free (registrar a escolha e a fonte no `deployment-plan.md`).

### 4.2 `.github/workflows/keepalive.yml`

- Gatilhos: `schedule` com `cron: "17 9 */3 * *"` (intervalo máximo de 3 dias) e `workflow_dispatch`.
- `permissions: {}`; um job `ping` em runner Linux hospedado, `timeout-minutes: 10`.
- Passo único: falha com mensagem se `secrets.KEEPALIVE_URL` estiver vazio; senão, `curl -fsS --retry 5 --retry-delay 30 "$KEEPALIVE_URL/api/v1/health"`. A URL vem só do secret (nada fixo no arquivo). Em produção, `KEEPALIVE_URL=https://<subdominio>`.
- O keep-alive principal passa a ser o healthcheck da API (§4.10), que faz `SELECT 1` a cada 60 s. O workflow continua como verificação externa: um job vermelho avisa o humano de que a VPS ou o banco caiu. Num repositório público, workflows agendados são desligados depois de 60 dias sem atividade (ADR-018); o healthcheck cobre esse caso.

### 4.3 Imagem do dashboard e a página "Sobre o modelo" (RV-06 da SPEC-013)

- O `qc-dashboard` é instalado **em modo editável**, que é o padrão do `uv sync`, a partir da cópia do repositório em `/app`. O Dockerfile **não** usa `--no-editable`. Com isso, `qc_dashboard.config.REPO_ROOT` é `/app`, e o padrão de `MODEL_METRICS_PATH` (`ml/models/partqc-mnv3-v1/metrics.json`) e os PNGs de `ml/reports/` são procurados dentro da imagem.
- O contexto de build (§4.11) inclui os JSONs de `ml/models/<versão>/` e todo o `ml/reports/`, que estão no Git (`docs/architecture.md` §7), e exclui os pesos (`*.onnx`, `*.pt`, `*.pth`) e `ml/data/`. A imagem leva, portanto, as métricas e os relatórios **do commit publicado**. Depois do merge do primeiro `metrics.json` (SPEC-012), basta a atualização da §4.16 (`git pull` e `up -d --build`).
- `MODEL_METRICS_PATH` fica vazio no `infra/.env.dashboard` (vale o padrão). Se for definido, é um caminho relativo à raiz do repositório.
- Não há montagem (`volumes`) de `ml/` no contêiner: a imagem é imutável, e o checkout da VPS não tem `ml/data/`.

### 4.4 `.streamlit/config.toml`

- `[browser] gatherUsageStats = false`; `[server] headless = true`; `[client] showErrorDetails` com o valor que **oculta** os detalhes de erro na versão do Streamlit travada no `uv.lock`: `"none"` ou `"type"` pela documentação de 2026-10-18 (§1). O autor confere a versão travada e cita no dev-report.
- O arquivo **não** define `server.address`, `server.port`, `server.baseUrlPath` nem `server.fileWatcherType`, que ficam na linha de comando da imagem (§4.10). Assim, a execução local continua em `localhost`. Ele também **não** põe `server.enableCORS` nem `server.enableXsrfProtection` em `false`: os padrões (`true`) funcionam atrás do Caddy, porque o navegador e o WebSocket ficam na mesma origem e o Caddy preserva o `Host`.
- Nenhum segredo. Na VPS, `API_BASE_URL` vem do compose e `READ_API_KEY` vem do `infra/.env.dashboard`. Localmente, as duas ficam no `.streamlit/secrets.toml` (SPEC-028), que fica fora da imagem (§4.11).

### 4.5 `scripts/smoke_test.py`

`main(argv=None, *, transport=None) -> int`.

- **Argumentos:** `--api-url` (env `CLOUD_API_URL`) e `--dashboard-url` (env `DASHBOARD_URL`); em produção, os dois são `https://<subdominio>`. As chaves vêm só do ambiente: `READ_API_KEY`, `SIM_DEVICE_ID`, `SIM_DEVICE_API_KEY`.
- **Validação:** as URLs precisam ser `https://`, exceto `http://` em `localhost`/`127.0.0.1`; variável ausente ou URL inválida → código 2.
- **TLS:** o cliente usa a verificação padrão do `httpx`, **nunca** `verify=False`.

Checagens, em ordem, cada uma imprimindo `PASS <nome>` ou `FAIL <nome>: <motivo>`:

1. `health`: `GET /api/v1/health` (timeout de 90 s, para cobrir o cold start da reserva no Render) → 200, `status=ok`, `db=ok` e `contract_version == qc_contracts.__version__`.
2. `write_requires_key`: `POST /api/v1/inspections` sem `X-API-Key` → 401.
3. `write`: 1 `InspectionCreate` com `source=simulated`, `lot_id=SMOKE-<AAAAMMDDTHHMMSSZ>`, `model_version=smoke-v0` e `model_sha256="0"*64` → 201 `created`.
4. `read_requires_key`: `GET /api/v1/inspections` sem chave → 401.
5. `read`: `GET /api/v1/inspections?lot_id=<lote>&source=simulated` com a `READ_API_KEY` → `total == 1` e o mesmo `inspection_id`.
6. `cors_closed`: `GET /api/v1/health` com `Origin: https://example.org` → sem o header `access-control-allow-origin`.
7. `dashboard`: `GET <dashboard-url>` (segue redirecionamentos, timeout de 60 s) → 200.
8. `dashboard_health`: `GET <dashboard-url>/_stcore/health` (barra única entre as partes, timeout de 60 s) → 200, com o corpo sem espaços igual a `ok`.

Saída e código:

- o código é 0 se todas passarem e 1 se alguma falhar;
- nenhuma chave é impressa;
- o `<motivo>` traz só o status HTTP, a classe da exceção ou o campo que divergiu, **nunca** a URL nem o host (R-13: a saída é colada no dev-report).

### 4.6 Passos humanos da primeira publicação (o autor escreve as instruções exatas no `deployment-plan.md` §4)

1. **Supabase:**
   - usar o projeto já existente (conta pessoal, sem cartão);
   - seguir o CA-19: conferir o `search_path` e aplicar as migrações pelo pooler em **modo session**, nunca pela 6543;
   - rodar as consultas do CA-14 (RLS e grants);
   - copiar a connection string do pooler em **modo transaction** (6543) para a `DATABASE_URL` do `infra/.env.api` (passo 5).
2. **Conferência da VPS** (§4.15): `docker version` (a versão do Engine), `docker compose version` (v2) e `docker buildx version`; `free -h`, `nproc` e `df -h /`; portas 80 e 443 livres; `sudo ufw status verbose` salvo num arquivo **fora** do repositório. Registrar no `deployment-plan.md` as versões, a RAM, as CPUs e o disco livre (sem IP nem nome de host).
3. **DNS:** criar no provedor de DNS do humano um registro `A` de `<subdominio>` para o IPv4 da VPS. Criar `AAAA` só se o humano confirmar que o Docker da VPS publica as portas em IPv6. Esperar `dig +short <subdominio> A` devolver o IP antes do passo 7.
4. **Checkout:** `git clone https://github.com/CarlosZeyy/Projeto_IoT.git <dir>` (repositório público, sem credencial na VPS) e `cd <dir>`, na branch `main`.
5. **Arquivos de ambiente** (§4.12):
   - criar `infra/.env`, `infra/.env.api` e `infra/.env.dashboard` **com um editor** (nunca com `echo ... >`, que deixa o valor no histórico do shell) e rodar `chmod 600 infra/.env infra/.env.api infra/.env.dashboard`;
   - a `READ_API_KEY` é gerada na VPS com `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` e colada nos dois arquivos que a usam;
   - valores com `$` vão entre aspas simples;
   - ajustar os limites de recursos do `infra/.env` conforme o `free -h` e o `nproc` do passo 2 (§4.12, item 4);
   - conferir com `git status --short` que nenhum dos três aparece.
6. **Validação:** `docker compose -f infra/compose.yaml config --quiet` → código 0. **Nunca** rodar `config` sem `--quiet` num terminal compartilhado ou gravado, porque ele imprime os valores dos `env_file`.
7. **Subida:** `docker compose -f infra/compose.yaml up -d --build`. Depois, `docker compose -f infra/compose.yaml ps`: os 3 serviços `running`, com `api` e `dashboard` `healthy`. Em `docker compose -f infra/compose.yaml logs caddy`, conferir a obtenção do certificado.
8. **Dispositivos:** na máquina do humano (não na VPS), rodar `register_device.py` para `edge-01` e `sim-01`, com a URL lida do arquivo `.env.migrate` (pooler em modo session, criado no passo 1): `uv run --env-file .env.migrate --package qc-api python scripts/register_device.py --device-id edge-01` (e o mesmo para `sim-01`). **Nunca** passar a URL de produção por `--database-url`, que a deixaria no `argv` e no histórico do shell (SEC-04-03). As chaves vão para os `.env` locais.
9. **Borda:** no `.env` do notebook, `CLOUD_API_URL=https://<subdominio>`.
10. **GitHub:** secret `KEEPALIVE_URL=https://<subdominio>`; disparar o workflow manualmente (CA-16).
11. **Smoke:** rodar `scripts/smoke_test.py` e `scripts/simulate.py --lots 3` contra produção, este sempre com `uv run --env-file <arquivo> ...` e dentro dos limites da §4.9, item 4.
12. **Banco:** configurar e conferir o `statement_timeout` do papel da API (§4.9, item 1; CA-26).
13. **CAs manuais:** executar os CAs manuais da §5 e registrar no dev-report e no `deployment-plan.md`, sem o subdomínio real nem o IP.

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

### 4.8 Riscos aceitos no `docs/deployment-plan.md`

O autor acrescenta ao `docs/deployment-plan.md` uma seção `## 7. Riscos aceitos` com, no mínimo, estas linhas, cada uma com a fonte e a data de verificação:

1. **Rajada anônima ocupando o pool (SEC-04-02).**
   - **Efeito:** enquanto a rajada dura, os dispositivos recebem 503. Não há perda de dados, porque o outbox da borda reenvia com backoff (SPEC-009).
   - **Na VPS:** não há proteção de provedor contra DDoS, e o Caddy padrão não tem limitação de taxa. A diretiva `rate_limit` não está na lista padrão e exigiria um build próprio com plugin (<https://caddyserver.com/docs/caddyfile/directives>, consultada pelo architect em 2026-10-18; o autor confere de novo e atualiza a data). O impacto nos outros projetos da VPS fica limitado pelo `mem_limit` e pelos `cpus` de cada serviço (§4.12).
   - **Na reserva (Render):** vale a proteção automática do Render (<https://render.com/docs/ddos-protection>, consultada em 2026-10-13).
   - **Decisão:** **risco aceito** no MVP (projeto acadêmico, URL não divulgada). Uma limitação de taxa só entra por SPEC nova, se o humano pedir.
2. **Log do `psycopg.pool` (SEC-04-05).** Com o banco fora do ar, o log da API mostra o host, a porta e, numa falha de autenticação, o usuário do pooler do Supabase. Esse log fica em `docker compose logs api`, que só o humano acessa na VPS, e no painel do Render quando a reserva está ativa. Não são segredos (R-03 continua cumprida, e a senha não aparece). No portão `deploy`, esse log não conta como vazamento. É a exceção prevista na regra "Erros de banco no log" de `docs/architecture.md` §4.
3. **Consulta cancelada pelo `statement_timeout`**, com o código `57014` (§4.9, item 1).
4. **Subdomínio nos logs de Certificate Transparency.** Todo certificado do Let's Encrypt vai para os logs públicos (<https://letsencrypt.org/docs/ct-logs/>), e o nome do subdomínio fica descobrível. A R-13 exige manter o nome fora do repositório, e não escondê-lo.
5. **VPS como ponto único de falha, compartilhada com outros projetos.** Mitigação: outbox na borda, limites por serviço e reserva fria no Render (§4.16, item 5).
6. **Limite de emissão de certificados.** São no máximo 5 certificados por conjunto exato de nomes a cada 7 dias (<https://letsencrypt.org/docs/rate-limits/>). Perder o volume `caddy_data` força uma emissão nova. Por isso, nunca usar `docker compose down -v`.

E toda menção a `register_device.py` no `deployment-plan.md` segue o passo 8 da §4.6: o comando completo com `--env-file .env.migrate`, nunca `--database-url` com a URL de produção.

### 4.9 Pendências de operação das SPECs 005, 006 e 014

O autor registra no `docs/deployment-plan.md`, com fonte e data de verificação:

1. **`statement_timeout` (SEC-05-01).**
   - Medir em produção, depois das migrações e do `simulate.py --lots 3`, o tempo das leituras mais pesadas: `EXPLAIN ANALYZE` da agregação de `/api/v1/lots` e da consulta da carta p da SPEC-026 (`SELECT_LOT_SELECTION` de `qc_api.repositories.inspections`, com os parâmetros padrão da rota: `source=live`, sem `object_type`, `baseline_lots=20`, `min_lot_size=5`, `max_points=100` e `max_excluded=50`), pelo SQL Editor. Não usar a agregação antiga da SPEC-006, que não existe mais. Registrar os tempos.
   - Escolher o valor (SEC-26-03): **`15s`**. Como a medição em produção é feita com poucos lotes, 3 vezes a leitura medida seria um limite de milissegundos que cortaria a carta de uma história realista (no Postgres local, a carta levou 2,9 s com 200 000 lotes e de 4,2 a 5,3 s com 1 M, medidos no test-report da SPEC-026). Só se 3 vezes a leitura mais lenta medida passar de 15 s, usar esse valor, até 30 s.
   - Registrar no `deployment-plan.md` que o `statement_timeout` é o teto do custo de banco da carta p e das demais leituras, e que a memória da API já é limitada pelo corte do ADR-017 (SPEC-026).
   - Aplicar no papel que a API usa, pelo SQL Editor: `alter role <papel> set statement_timeout = '<valor>';`. O papel é o usuário da `DATABASE_URL` da API, sem o sufixo do projeto (no Supabase, `postgres`). Segundo a documentação do Supabase, uma configuração de sessão não funciona pelo pooler em modo transaction (porta 6543), e a configuração de um papel se confere em `pg_roles.rolconfig`, porque `show statement_timeout` não a reflete (<https://supabase.com/docs/guides/database/postgres/timeouts>, consultado em 2026-10-17). Por isso, a forma é o `alter role`, e não o parâmetro `options` da conexão.
   - Conferir: `select rolconfig from pg_roles where rolname = '<papel>';` contém `statement_timeout=<valor>`; e uma conexão **pelo mesmo caminho da API** (pooler em modo transaction, porta 6543), aberta com a URL lida de um arquivo local ignorado pelo Git (nunca na linha de comando), devolve o valor em `show statement_timeout`. Se não devolver, parar e registrar `SPEC_ISSUE` para o architect (a alternativa é um `set local statement_timeout` na transação de leitura da API, que exige uma SPEC do developer).
   - **Efeito aceito**, registrado em "Riscos aceitos" (§4.8, item 3):
     - uma consulta cancelada (`57014`, `QueryCanceled`) responde **503** `{"detail": "Database unavailable"}`, igual a um banco fora do ar, sem a mensagem do Postgres nem stack trace;
     - o `QueryCanceled` é subclasse de `psycopg.OperationalError`, que o `db_connection` (`api/src/qc_api/db.py`) converte em `DatabaseUnavailableError` (medido pela rota SPC, SEC-26-02 de `reviews/SPEC-026/r1-security-report.md`);
     - o dashboard mostra o aviso de API indisponível e não repete a chamada em laço (SPEC-013);
     - as migrações rodam com o mesmo papel. Se uma migração futura passar do limite, ela falha e faz `rollback`, e o humano a repete com o limite ajustado só naquela sessão.
2. **`READ_API_KEY` (INFO-02 de `reviews/SPEC-005/r1-security-report.md`).**
   - Gerada só com `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`, nunca reaproveitando uma chave do `register_device.py`.
   - **Troca:**
     - gerar a nova chave;
     - na VPS, atualizar o valor no `infra/.env.api` e no `infra/.env.dashboard` e rodar `docker compose -f infra/compose.yaml up -d`, que recria os dois serviços; durante a recriação, o painel fica indisponível por alguns segundos;
     - se a reserva no Render estiver ativa, atualizar também a variável no painel dele, na mesma sessão;
     - conferir com o `scripts/smoke_test.py` (checagens `read_requires_key` e `read`), que lê a chave do ambiente. **Nunca** conferir com `curl -H "X-API-Key: ..."`, que deixa a chave no `argv`.
3. **Limites da reserva (Render).** A linha do Render na §2 do `deployment-plan.md` diz **512 MB de RAM e 0,1 CPU**, com a fonte <https://render.com/docs/compute-plans> e a data da conferência do autor, e nunca "não confirmado".
4. **Simulador em produção (SEC-07 e mitigação do SEC-01 de `reviews/SPEC-014/r1-security-report.md`).**
   - Contra produção, só execuções pequenas: `--lots` até 10 e `--lot-size` até 50 (no máximo 500 itens por execução).
   - A chave vai sempre pelo arquivo de ambiente: `uv run --env-file .env --package qc-api python scripts/simulate.py ...`. **Nunca** `--api-key` em demo gravada, terminal projetado, CI ou workflow. Se for inevitável, usar a forma `--api-key=<valor>` com um espaço no início do comando, para que ele não entre no histórico do shell.
   - Se uma chave aparecer numa gravação, num log compartilhado ou num print, rotacioná-la com `scripts/register_device.py --device-id sim-01 --rotate` (pelo `--env-file .env.migrate` do passo 8 da §4.6) e atualizar o `.env`.

### 4.10 Dockerfiles (`infra/docker/api.Dockerfile` e `infra/docker/dashboard.Dockerfile`)

O contexto de build é a **raiz do repositório**. Os dois arquivos seguem o mesmo esqueleto, e só mudam o pacote, a porta, o healthcheck e o comando:

| Item | `api.Dockerfile` | `dashboard.Dockerfile` |
|---|---|---|
| Base (toda linha `FROM`) | `python:3.12.<patch>-slim-<bookworm\|trixie>`, com o patch fixado (hoje `3.12.15`); o digest `@sha256:` é recomendado | igual |
| `uv` | `COPY --from=ghcr.io/astral-sh/uv:<X.Y.Z> /uv /uvx /bin/`, com versão numérica fixada (nunca `latest`); a mesma nos dois arquivos | igual |
| Ambiente de build | `UV_PYTHON_DOWNLOADS=0`, `UV_COMPILE_BYTECODE=1`, `UV_LINK_MODE=copy`, `PYTHONUNBUFFERED=1` | igual |
| Usuário | grupo e usuário `app`, UID e GID `10001`, com `HOME=/home/app` | igual |
| Código | `WORKDIR /app`; `COPY . /app` (o contexto já filtrado pela §4.11) | igual |
| Instalação | `RUN uv sync --package qc-api --frozen --no-dev` | `RUN uv sync --package qc-dashboard --frozen --no-dev` |
| `PATH` | `ENV PATH="/app/.venv/bin:$PATH"` | igual |
| Execução | `USER 10001:10001`, a última instrução `USER`, depois do último `RUN` | igual |
| Porta | `EXPOSE 8000` | `EXPOSE 8501` |
| Healthcheck | `HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3`, com um `python -c` em forma exec que faz `GET http://127.0.0.1:8000/api/v1/health` (urllib, timeout 5 s) e sai com 0 só com 200 | o mesmo esquema para `http://127.0.0.1:8501/_stcore/health` |
| Comando (forma exec, sem `uv`) | `["uvicorn", "qc_api.main:app", "--host", "0.0.0.0", "--port", "8000"]` | `["streamlit", "run", "dashboard/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.fileWatcherType=none"]` |
| Rótulo | `LABEL partqc.component="api"` | `LABEL partqc.component="dashboard"` |

Regras:

- **Proibido** nos dois arquivos: `--no-editable` (§4.3), `--extra`, `--all-extras`, `--all-packages`, `pip install`, `ADD` de URL, `curl | sh`, `ENV` ou `ARG` com nome de segredo (`DATABASE_URL`, `READ_API_KEY`, `*_API_KEY`, `*TOKEN*`, `*PASSWORD*`).
- A instalação roda como root, e o código e o `.venv` ficam de dono root, legíveis pelo usuário `app`. O processo não precisa escrever em `/app`.
- **R-12:** com `--package` e sem `--extra`, nenhuma imagem instala torch, torchvision, timm, onnx ou onnxruntime, e a do dashboard não instala `psycopg` (o dashboard não acessa o banco, ADR-007). O CA-35 confere dentro da imagem.
- **Keep-alive:** o healthcheck da API, a cada 60 s, faz o `SELECT 1` do `/api/v1/health` (`docs/architecture.md` §4), o que mantém o Supabase ativo (ADR-018). Com o banco pausado ou fora do ar, o contêiner fica `unhealthy`, mas continua rodando: o Docker não reinicia um contêiner por healthcheck. A condição é só informativa.
- O processo do dashboard roda a partir de `/app`, para que o Streamlit leia o `/app/.streamlit/config.toml` (§4.4).
- Um build em vários estágios é permitido, desde que todo `FROM` siga a tabela e o estágio final cumpra as demais linhas.

### 4.11 Contexto de build: `infra/docker/<nome>.Dockerfile.dockerignore`

- Um arquivo por Dockerfile, no mesmo diretório e com o nome do Dockerfile como prefixo: `infra/docker/api.Dockerfile.dockerignore` e `infra/docker/dashboard.Dockerfile.dockerignore`. Com o BuildKit, ele tem precedência sobre um `.dockerignore` na raiz (§1). **Não** se cria `.dockerignore` na raiz, que está fora da lista de caminhos do autor.
- **Exclusões obrigatórias**, nos dois arquivos, para que nada disso entre no contexto nem na imagem:

  | Item | Padrões | Regra |
  |---|---|---|
  | Git | `.git` | — |
  | Arquivos de ambiente | `**/.env*`, inclusive `infra/.env`, `infra/.env.api`, `infra/.env.dashboard`, `.env.migrate` e `.env.prod`. A exceção `!.env.example` é permitida | R-03 |
  | Secrets locais do Streamlit | `.streamlit/secrets.toml` | R-03 |
  | Configuração local do Claude Code | `.claude/` | — |
  | Notas da dupla | `notas-locais/` | — |
  | Dados e fotos | `ml/data/`, `edge/data/`, `data/` e as imagens `**/*.jpg`, `**/*.jpeg`, `**/*.png`, `**/*.heic`, `**/*.webp`, com a exceção `!ml/reports/**/*.png` | R-02, R-14 |
  | Pesos do modelo | `ml/models/**/*.onnx`, `ml/models/**/*.pt`, `ml/models/**/*.pth`, `ml/checkpoints/` | — |
  | Bancos locais | `**/*.sqlite`, `**/*.sqlite3`, `**/*.db` (o outbox) | — |
  | Ambiente e caches de ferramentas | `**/.venv`, `**/__pycache__`, `.pytest_cache`, `.ruff_cache` | — |

- O arquivo pode excluir também `docs/`, `reviews/` e `**/tests`, mas **não** pode excluir `pyproject.toml`, `uv.lock`, os `pyproject.toml` dos membros do workspace, `packages/`, o código do próprio pacote, `.streamlit/config.toml`, `ml/models/**/*.json` e `ml/reports/`, que o dashboard usa (§4.3).
- Se o CA-36 mostrar que o Compose da máquina ou do CI não respeita o arquivo por Dockerfile, o autor para e registra `SPEC_ISSUE`. A alternativa, um `.dockerignore` na raiz, exige mudar a lista de caminhos do hook (architect e humano).

### 4.12 `infra/compose.yaml` e os arquivos de ambiente da VPS

1. **Projeto e serviços:** `name: partqc` no topo (volumes e redes ganham o prefixo `partqc_` e não colidem com os outros projetos da VPS). Os serviços são exatamente `caddy`, `api` e `dashboard`, com `container_name` não fixado.
2. **Portas:** só o `caddy` tem `ports`, exatamente `"80:80"`, `"443:443"` e `"443:443/udp"` (HTTP/3). A `api` e o `dashboard` **não** têm `ports` e usam só `expose` (`"8000"` e `"8501"`). Nenhum serviço usa `network_mode: host`, `privileged`, `pid: host` ou um volume com `docker.sock`.
3. **Rede:** uma rede `partqc` (bridge, **sem** `internal: true`, porque a API precisa sair para o Supabase), da qual os três participam. No `caddy`, a rede tem `aliases: ["${PUBLIC_HOST:?…}"]`. Assim, o `https://<subdominio>` que o dashboard chama resolve, dentro da rede, para o próprio Caddy, e o tráfego não sai da VPS.
4. **Limites e endurecimento**, em todos os serviços:

   | Serviço | `mem_limit` | `cpus` |
   |---|---|---|
   | `api` | `${API_MEM_LIMIT:-512m}` | `${API_CPUS:-1.0}` |
   | `dashboard` | `${DASHBOARD_MEM_LIMIT:-1g}` | `${DASHBOARD_CPUS:-1.0}` |
   | `caddy` | `${CADDY_MEM_LIMIT:-256m}` | `${CADDY_CPUS:-0.5}` |

   - os limites são escritos literalmente nessas formas;
   - o humano ajusta os valores no `infra/.env` conforme o `free -h` e o `nproc` (§4.6, passo 5): a soma dos `mem_limit` fica abaixo da RAM disponível, cada `cpus` fica ≤ `nproc`, e a API não fica abaixo de `512m` sem uma decisão registrada no `deployment-plan.md`;
   - `restart: unless-stopped`;
   - `security_opt: ["no-new-privileges:true"]`;
   - `logging` com `driver: json-file` e `options` `max-size: "10m"` e `max-file: "3"`. Sem isso, o log cresce sem limite no disco compartilhado.
5. **`caddy`:**
   - imagem `caddy:2.<minor>.<patch>` (ou `-alpine`), com a versão fixada (hoje `2.11.7`) e o digest recomendado;
   - `environment: PUBLIC_HOST: "${PUBLIC_HOST:?…}"`;
   - volumes `./Caddyfile:/etc/caddy/Caddyfile:ro`, `caddy_data:/data` e `caddy_config:/config`, com os dois nomeados declarados no topo;
   - `cap_drop: [ALL]` e `cap_add: [NET_BIND_SERVICE]`;
   - `depends_on: [api, dashboard]`, sem `condition: service_healthy`, para que o Caddy suba mesmo com o Supabase pausado.
6. **`api`:** `build: {context: .., dockerfile: infra/docker/api.Dockerfile}`, `env_file: [.env.api]` (o caminho é relativo à pasta do compose, `infra/`) e `cap_drop: [ALL]`.
7. **`dashboard`:** `build: {context: .., dockerfile: infra/docker/dashboard.Dockerfile}`, `env_file: [.env.dashboard]`, `environment: API_BASE_URL: "https://${PUBLIC_HOST:?…}"` (o `environment` prevalece sobre o `env_file`; SEC-13-01, SPEC-028) e `cap_drop: [ALL]`.
8. **Segredos:** nenhum `environment` define `DATABASE_URL`, `READ_API_KEY` ou outra chave. Os segredos chegam só pelo `env_file`. O `${PUBLIC_HOST:?…}` faz o Compose parar com erro se a variável faltar.

**Arquivos da VPS**, todos ignorados pelo Git (padrões `.env` e `.env.*`) e pelo contexto de build (§4.11), com `chmod 600`:

| Arquivo | Conteúdo | Lido por |
|---|---|---|
| `infra/.env` | `PUBLIC_HOST=<subdominio>` (sem esquema nem barra) e, opcionalmente, `API_MEM_LIMIT`, `API_CPUS`, `DASHBOARD_MEM_LIMIT`, `DASHBOARD_CPUS`, `CADDY_MEM_LIMIT`, `CADDY_CPUS` | interpolação do Compose (o `.env` da pasta do projeto) |
| `infra/.env.api` | `DATABASE_URL` (pooler em modo transaction, 6543), `READ_API_KEY` e, opcionalmente, `MAX_BODY_BYTES` e `LOG_LEVEL` | contêiner `api` |
| `infra/.env.dashboard` | `READ_API_KEY` (o mesmo valor) e, opcionalmente, `MODEL_METRICS_PATH`. Sem `API_BASE_URL`, que vem do compose | contêiner `dashboard` |

O dashboard não recebe `DATABASE_URL` nem chaves de dispositivo, como pede a SPEC-028 §4.6. Valores com `$` vão entre aspas simples, porque valores sem aspas sofrem interpolação no Compose (§1).

O `.env.example` ganha um bloco `infra/.env (VPS, infra/compose.yaml)` com `PUBLIC_HOST=<subdominio>` e as 6 variáveis de recursos com os valores padrão. Os comentários dizem que `infra/.env.api` recebe as variáveis do bloco `qc-api` e `infra/.env.dashboard` recebe `READ_API_KEY` e `MODEL_METRICS_PATH`. Também mudam:

- `CLOUD_API_URL=https://<subdominio>`;
- o comentário do `DASHBOARD_URL`, que passa a dizer `https://<subdominio>/` e não cita mais o Streamlit Community Cloud;
- o cabeçalho do bloco do dashboard, que deixa de dizer "Streamlit Secrets";
- a última linha, que fica `# ---------- Segredos fora do .env (GitHub Secrets) ----------`.

As linhas de comentário acima de `API_BASE_URL=` continuam citando `.streamlit/secrets.toml` (CA-11 da SPEC-028).

### 4.13 `infra/Caddyfile`

- **Sem bloco de opções globais** (sem `email`, `acme_ca`, `local_certs` ou `debug`). O endereço do site é exatamente `{$PUBLIC_HOST}`, sem valor padrão e sem domínio literal no arquivo.
- **Rotas:**
  - `handle /api/* { reverse_proxy api:8000 }`: o prefixo **não** é removido (nada de `handle_path`), porque as rotas da API já começam em `/api/v1`;
  - `handle { reverse_proxy dashboard:8501 }` para todo o resto, inclusive `/_stcore/stream` (WebSocket) e `/_stcore/health`;
  - nenhuma rota para `/docs` nem `/openapi.json` (ADR-018, decisão 4). Elas caem no Streamlit, que não as serve.
- **Headers de resposta:** `Strict-Transport-Security "max-age=31536000"`, **sem** `includeSubDomains` nem `preload` (o domínio é pessoal e tem outros projetos), e `X-Content-Type-Options "nosniff"`.
- Sem `tls internal`, sem a CA de staging e sem a diretiva `log` (o Caddy não registra acessos, nem IPs de clientes, por padrão). O HTTPS automático e o redirecionamento de HTTP para HTTPS são os padrões do Caddy (ADR-018).
- O arquivo é formatado com `caddy fmt`, para que o `caddy adapt` não avise de formatação.

### 4.14 CI das imagens e o marcador `docker`

- **Marcador:**
  - `pyproject.toml` ganha em `markers` a entrada `docker: requires Docker with BuildKit and Compose v2 (PARTQC_DOCKER_TESTS=1)`;
  - `infra/tests/docker_support.py` expõe:
    - `docker_tests_enabled(environ: Mapping[str, str]) -> bool`, que é `True` se, e só se, `environ.get("PARTQC_DOCKER_TESTS") == "1"`;
    - `check_docker(run: Callable[[list[str]], int] | None = None) -> None`, que roda `docker version`, `docker compose version` e `docker buildx version` e levanta `DockerUnavailableError` (cuja mensagem cita o comando que falhou) se algum devolver código diferente de 0 ou o executável não existir;
    - `copy_tracked_tree(dest: Path, extra_files: Mapping[str, bytes] = {}) -> Path`, que copia para `dest` os arquivos de `git ls-files` que existem e grava os `extra_files` (caminhos relativos), sem nunca escrever na árvore de trabalho real.
  - Em `infra/tests/conftest.py`, o hook `pytest_collection_modifyitems` marca como `skip` (motivo `set PARTQC_DOCKER_TESTS=1 to run`) todo item com o marcador `docker` quando `docker_tests_enabled(os.environ)` é falso. Quando é verdadeiro e há itens `docker`, ele chama `check_docker()` e converte o erro em `pytest.UsageError`.
  - O conftest oferece a fixture de sessão `build_image(dockerfile: str, extra_files: Mapping[str, bytes] = {}) -> str`, que monta um contexto temporário com `copy_tracked_tree`, roda `docker build -f <dockerfile> <contexto>` (BuildKit), devolve a tag e remove as imagens no fim da sessão. O mesmo par de argumentos reaproveita a imagem.
- **Workflow:** `.github/workflows/docker.yml`:
  - gatilhos `pull_request` e `push` em `main`; `permissions: {contents: read}`;
  - um único job em `ubuntu-latest`, com `timeout-minutes` ≤ 30;
  - o mesmo serviço `postgres:16` e o mesmo `TEST_DATABASE_URL` do `ci.yml`, porque o `conftest.py` da raiz exige a variável quando `CI=true`. Os testes `db` não são selecionados aqui;
  - passos: `actions/checkout` e `astral-sh/setup-uv` com versões fixadas (como no `ci.yml`), `uv python install 3.12`, `uv sync --all-packages --frozen` e `uv run pytest -m docker -q`, com `PARTQC_DOCKER_TESTS: "1"`;
  - sem `secrets.`, sem `docker login` e sem `docker push`.
- No job do `ci.yml`, os testes `docker` aparecem como `skip`, e o `ci.yml` não muda: o CA-10 da SPEC-001 exige exatamente 1 job nele.
- O check novo (`docker`) passa a contar no "CI verde" da R-09.

### 4.15 Rede e firewall da VPS (passos humanos; o autor escreve os comandos exatos no `deployment-plan.md`)

1. **Antes do primeiro `up`:** `ss -tlnp '( sport = :80 or sport = :443 )'` não mostra nenhum processo; `sudo ufw status verbose` é salvo num arquivo fora do repositório (`~/ufw-antes-partqc.txt`).
2. **O Docker publica as portas do Caddy por fora do `ufw`** (§1): nenhuma regra do `ufw` é necessária para o Caddy funcionar. Se o humano quiser que o `ufw status` documente as portas, ele **só acrescenta** `sudo ufw allow 80/tcp`, `sudo ufw allow 443/tcp` e `sudo ufw allow 443/udp`. Se o provedor da VPS tiver um firewall no painel, conferir que 80/tcp, 443/tcp e 443/udp estão liberadas na entrada.
3. **Proibido**, porque afeta os outros projetos da VPS:
   - `ufw reset`, `ufw default ...`, `ufw delete ...` e `ufw --force ...`;
   - ativar ou desativar o `ufw`;
   - `iptables -F`/`-X` e `nft flush`;
   - editar `/etc/docker/daemon.json`;
   - reiniciar o Docker;
   - `docker system prune`, `docker volume prune` e `docker network prune`;
   - `docker compose down -v`.

   Toda menção a esses comandos no `deployment-plan.md` vem numa frase que começa com "Nunca".
4. **Depois do `up`:** `sudo ufw status verbose` é comparado com o arquivo do item 1 (nenhuma regra a menos), e os outros projetos do humano continuam respondendo. As portas 8000 e 8501 não aparecem no `ss -tlnp` do host, e uma conexão externa a `<IP>:8000` e `<IP>:8501` falha.

### 4.16 Atualização, logs, rollback e reserva (no `deployment-plan.md` §4 e §6)

1. **Atualização** (depois de cada merge que afete a API, o dashboard, `infra/` ou `ml/models/**/*.json` e `ml/reports/`):
   1. `cd <dir> && git pull --ff-only`;
   2. `docker compose -f infra/compose.yaml up -d --build`;
   3. `docker compose -f infra/compose.yaml ps`;
   4. smoke (§4.5);
   5. `docker image prune -f --filter label=partqc.component`, que remove só as imagens órfãs do PartQC.
2. **Logs:** `docker compose -f infra/compose.yaml logs --tail 200 <serviço>`. Nunca colar logs da API em lugar público (SEC-04-05, §4.8).
3. **Rollback:**
   1. `git log --oneline -10`;
   2. `git checkout <sha anterior>` e `docker compose -f infra/compose.yaml up -d --build`;
   3. com a correção mergeada, `git checkout main && git pull --ff-only` e o mesmo `up`.

   As migrações são só aditivas no MVP. Um rollback não desfaz migração.
4. **Parar:** `docker compose -f infra/compose.yaml down`, sem `-v`. Nunca `docker compose down -v`, que apaga o volume `caddy_data` (§4.8, item 6).
5. **Ativar a reserva** (VPS fora do ar por mais tempo, ou no dia da demo):
   1. no Render, "New → Blueprint" com `infra/render.yaml`, e definir `DATABASE_URL` e `READ_API_KEY`;
   2. na borda, `CLOUD_API_URL=https://<servico>.onrender.com`;
   3. o dashboard roda no notebook com `.streamlit/secrets.toml` apontando para essa URL (SPEC-028 §4.6);
   4. `KEEPALIVE_URL` passa a apontar para a reserva enquanto ela estiver em uso;
   5. registrar o uso e a data no `deployment-plan.md`;
   6. ao voltar para a VPS, desfazer os passos 2 a 4 e suspender o serviço do Render.

## 5. Critérios de aceite

Os CAs marcados `docker` só rodam com `PARTQC_DOCKER_TESTS=1` (§4.14) e usam contextos e cópias temporárias, nunca a árvore de trabalho real. O host fictício dos testes é `partqc.example.org`.

- **CA-01** — *Dado* `infra/render.yaml` carregado com `yaml.safe_load`, *então* há exatamente 1 serviço com `type=web`, `plan=free`, `runtime=python`, os `buildCommand`, `startCommand` e `healthCheckPath` da §4.1 literalmente, e `envVars` contém `DATABASE_URL` e `READ_API_KEY` com `sync: false` e sem chave `value`.
- **CA-02** — *Dado* `keepalive.yml` carregado, *então* os gatilhos são `schedule` (cron `17 9 */3 * *`) e `workflow_dispatch`, `permissions == {}`, o job tem `timeout-minutes: 10`, o passo usa `secrets.KEEPALIVE_URL` e contém `curl -fsS --retry 5 --retry-delay 30`, e o arquivo não contém `http://` nem `https://` literais.
- **CA-03** — (removido em 2026-10-18: sem `dashboard/requirements.txt`, ADR-018.)
- **CA-04** — (removido em 2026-10-18: a R-12 do dashboard passa a ser verificada dentro da imagem, CA-35.)
- **CA-05 (R-03)** — *Dado* cada arquivo listado por `git ls-files` cujo caminho não começa com `docs/` e que existe na árvore de trabalho, lido como bytes e decodificado em UTF-8 com `errors="replace"` (nenhum arquivo é pulado; `reviews/` e todas as suítes de teste, inclusive as `tests/acceptance/`, estão no escopo), *quando* busco os padrões abaixo com `re.finditer` no texto inteiro, *então*:
  - `eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}`, `-----BEGIN [A-Z ]*PRIVATE KEY-----` e `service_role\s*[:=]\s*\S{20,}`: nenhuma ocorrência, sem exceção;
  - `postgres(ql)?://(?P<user>[^\s:/@]+):(?P<password>[^\s@]+)@` (o mesmo padrão de antes, com grupos nomeados): toda ocorrência é aceita por pelo menos uma das regras abaixo, e nenhuma outra ocorrência é aceita:
    1. **marcador de documentação:** `password` casa `^<[a-z][a-z_-]*>$` (por exemplo, `<password>` e `<senha>`) ou é exatamente `…` (U+2026) ou `...` (três pontos ASCII);
    2. **valor montado em tempo de execução:** `password` casa `^\$?\{[A-Za-z_][A-Za-z0-9_]*\}$` (por exemplo, o `{SECRET}` de uma f-string ou um `${VAR}`), ou seja, o arquivo traz o nome de uma variável, e não um valor;
    3. **credencial fictícia conhecida:** o texto que começa logo depois do `://` da ocorrência começa com um destes cinco, exatamente: `u:pw@127.0.0.1`, `u:s3cr3t-pw@127.0.0.1`, `postgres:postgres@localhost`, `postgres:postgres@...` (três pontos ASCII) ou `u:senha@…` (U+2026);
  - em `.env.example`, as variáveis de segredo (`DEVICE_API_KEY`, `READ_API_KEY`, `SIM_DEVICE_API_KEY`, `DATABASE_URL`, `EDGE_SESSION_TOKEN`) só têm valor vazio ou marcadores `<...>`.
- **CA-06 (R-03)** — *Dado* `.gitignore`, *então* `git check-ignore` ignora `.env`, `.env.prod`, `.env.migrate`, `infra/.env`, `infra/.env.api`, `infra/.env.dashboard` e `.streamlit/secrets.toml`, e não ignora `.env.example` nem `.streamlit/config.toml`.
- **CA-07** — *Dado* `.streamlit/config.toml` carregado com `tomllib`, *então*:
  - `browser.gatherUsageStats is False`, `server.headless is True` e `client.showErrorDetails` está em `{"none", "type"}`;
  - não existem as chaves `server.address`, `server.port`, `server.baseUrlPath` e `server.fileWatcherType`;
  - `server.enableCORS` e `server.enableXsrfProtection`, se existirem, são `True`;
  - não há chave com `key`, `secret` ou `token` no nome.
- **CA-08** — *Dado* a API e o dashboard falsos (`httpx.MockTransport`) corretos, com `/_stcore/health` respondendo `ok`, *quando* rodo `smoke_test.main` com URLs `https://`, *então* o código é 0, o stdout tem as 8 linhas `PASS` na ordem da §4.5, e a inspeção enviada tem `source=simulated` (R-06).
- **CA-09** — *Dado* a API falsa aceitando leitura **sem** chave (ou escrita sem chave), *então* `FAIL read_requires_key` (ou `FAIL write_requires_key`) e código 1.
- **CA-10** — *Dado* a API falsa devolvendo `access-control-allow-origin: *`, *então* `FAIL cors_closed` e código 1; *dado* `/health` com `db=error` ou `contract_version` diferente, *então* `FAIL health` e código 1; *dado* `/_stcore/health` respondendo 200 com o corpo `nope`, ou 502, *então* `FAIL dashboard_health` e código 1.
- **CA-11** — *Dado* `--api-url http://api.exemplo.org` ou `--dashboard-url http://painel.exemplo.org`, ou `READ_API_KEY` ausente, *então* código 2 e 0 requisições.
- **CA-12 (R-03, R-13)** — *Dado* qualquer execução do smoke (sucesso, falha por status ou falha por `httpx.ConnectError`), com as URLs `https://api.host-secreto-15.example` e `https://painel.host-secreto-15.example`, *então*:
  - os valores de `READ_API_KEY` e `SIM_DEVICE_API_KEY` não aparecem no stdout nem no stderr;
  - `host-secreto-15` também não aparece;
  - o código-fonte de `scripts/smoke_test.py` não contém `verify=False`.
- **CA-13 (manual)** — API na VPS:
  1. `curl -fsS https://<subdominio>/api/v1/health` → 200, com `"db":"ok"` e o `contract_version` atual;
  2. `curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' http://<subdominio>/api/v1/health` → `301` ou `308`, com o destino `https://<subdominio>/api/v1/health`;
  3. `curl -i https://<subdominio>/api/v1/inspections` sem chave → 401;
  4. `curl -sI https://<subdominio>/api/v1/health` tem o header `strict-transport-security` com `max-age=31536000` e sem `includesubdomains`;
  5. `echo | openssl s_client -connect <subdominio>:443 -servername <subdominio> 2>/dev/null | openssl x509 -noout -issuer -enddate` → emissor do Let's Encrypt (ou da ZeroSSL, a CA alternativa do Caddy) e validade futura;
  6. `curl -s https://<subdominio>/docs | grep -ci swagger` → `0`, e `curl -s https://<subdominio>/openapi.json | grep -c '"openapi"'` → `0`;
  7. registrar as saídas no dev-report, trocando o subdomínio por `<subdominio>`.
- **CA-14 (manual, R-03/RNF-06)** — RLS e grants em produção, no SQL Editor:
  1. `select relname, relrowsecurity, relforcerowsecurity from pg_class where relname in ('devices','inspections','schema_migrations');` → as 3 linhas com `relrowsecurity = true` e `relforcerowsecurity = false`;
  2. `select count(*) from pg_policies where tablename in ('devices','inspections','schema_migrations');` → `0`;
  3. `select grantee, table_name, privilege_type from information_schema.role_table_grants where table_schema = 'public' and grantee in ('anon','authenticated');` → se houver linhas, rodar `revoke all on devices, inspections, schema_migrations from anon, authenticated;` e repetir a consulta, que deve voltar vazia (SEC-02; o `revoke` não vai para uma migração, porque esses papéis não existem no Postgres local nem no do CI);
  4. chamar a API REST do Supabase em `/rest/v1/inspections` com a chave anon → nenhuma linha retornada, mesmo com dados na tabela;
  5. registrar no dev-report a saída das consultas 1 a 3 (sem segredos).
- **CA-15 (manual)** — Smoke em produção:
  1. exportar as variáveis num shell local, com as duas URLs iguais a `https://<subdominio>`;
  2. `uv run --package qc-api python scripts/smoke_test.py`;
  3. as 8 checagens dão `PASS`;
  4. colar a saída no dev-report (ela não tem chaves nem o host, §4.5).
- **CA-16 (manual)** — Keep-alive:
  1. disparar o `keepalive` por `workflow_dispatch`;
  2. o job termina verde em ≤ 10 min;
  3. o próximo agendamento aparece na aba Actions.
- **CA-17 (manual)** — Dashboard na VPS:
  1. abrir `https://<subdominio>/` num navegador de desktop e num celular pelos dados móveis: a Visão geral carrega;
  2. nas ferramentas do navegador (aba Rede), a conexão `wss://<subdominio>/_stcore/stream` tem status 101 e continua aberta por 5 min sem recarregar a página;
  3. trocar um filtro da barra lateral atualiza os gráficos;
  4. depois de `simulate.py --lots 3`, com a origem `Todos`, aparece o selo "Contém dados simulados";
  5. em "Sobre o modelo":
     - se a `main` publicada tiver o `metrics.json` do modelo, a tabela "Métricas × metas do PRD" aparece;
     - se não tiver, a mensagem "Nenhum modelo avaliado ainda" cita `ml/models/partqc-mnv3-v1/metrics.json` (relativo, SPEC-028), nunca um caminho sob `site-packages` (RV-06);
  6. `docker compose -f infra/compose.yaml exec dashboard printenv API_BASE_URL` começa com `https://`;
  7. registrar o resultado e a data no `deployment-plan.md`, com a nota de repetir o passo 5 depois do merge do primeiro `metrics.json` (SPEC-012) e da atualização da §4.16.
- **CA-18 (manual, R-01)** — Para cada recurso, a dupla registra no `deployment-plan.md` §2 a fonte e o "Verificado em" com a data desta SPEC:
  - **Supabase e GitHub Actions:** a conta e o recurso estão em uso **sem cartão**;
  - **VPS:** é preexistente e pessoal, e o projeto não mudou o plano nem contratou nada (o humano confirma por escrito);
  - **domínio:** o subdomínio é de um domínio que o humano já tinha, sem custo novo;
  - **Render (reserva):** a conta existe sem cartão e, se a reserva for ativada, o serviço é `free`.
- **CA-19 (manual, SEC-04 e SPEC_ISSUE-01 da SPEC-003)** — Migração em produção:
  1. no SQL Editor, `show search_path;` e `select current_schema();` → o schema corrente é `public` (se não for, parar e registrar `SPEC_ISSUE`);
  2. criar `.env.migrate` com a URL do pooler em **modo session** (porta 5432) e conferir com `git status` que ele não aparece;
  3. `uv run --env-file .env.migrate --package qc-api python infra/migrate.py --status` → lista as pendentes e sai com 0;
  4. `uv run --env-file .env.migrate --package qc-api python infra/migrate.py` → sai com 0;
  5. repetir o passo 3 → `0 pending`;
  6. no SQL Editor, `select conname, pg_get_constraintdef(oid) from pg_constraint where conrelid = 'inspections'::regclass and conname like 'inspections\_%\_check' order by 1;` → as definições das 4 restrições da `002` são as da tabela da SPEC-027 §4.1 (se uma restrição com o mesmo nome tiver outra definição, parar e registrar `SPEC_ISSUE`; SEC-02 de `reviews/SPEC-027/r1-security-report.md`);
  7. registrar no dev-report as saídas dos passos 1, 3, 4, 5 e 6.
- **CA-20 (SPEC_ISSUE-01)** — *Dado* `--database-url postgresql://u:s3cr3t-pw@127.0.0.1:6543/x_test`, ou `postgresql://u@h1:5432,h2:6543/x_test`, ou uma URL sem porta com `PGPORT=6543` no ambiente, *quando* se roda a CLI (com e sem `--status`) e quando se chamam `apply_migrations` e `pending_migrations` com a mesma conninfo, *então*:
  - a CLI sai com código 2 e o stderr contém `transaction pooler (port 6543) is not supported for migrations`;
  - as funções levantam `UnsupportedConnectionError` (instância de `MigrationError`) com a mesma mensagem;
  - um listener TCP local na porta usada recebe 0 conexões;
  - `s3cr3t-pw` não aparece no stdout, no stderr nem na mensagem da exceção.
- **CA-21 (SEC-01)** — *Dado* o banco de teste e outra sessão segurando `pg_advisory_lock(ADVISORY_LOCK_KEY)`, *quando* `apply_migrations(conninfo, <dir com 001>, lock_wait_s=1)` roda num schema vazio, *então* levanta `MigrationError` cuja mensagem começa com `could not acquire the migration lock within`, em menos de 5 s, e `schema_migrations` não existe; e, depois que a outra sessão libera o lock, a mesma chamada retorna `["001"]`. `apply_migrations(..., lock_wait_s=0)` levanta `ValueError`.
- **CA-22 (RV-02)** — *Dado* um diretório temporário com a cópia de `001_init.sql` e `002_tx.sql` contendo `create table t_tx(id int); commit;`, *quando* `apply_migrations` roda num schema vazio, *então* levanta `MigrationError` cuja mensagem contém `ended the transaction` e `002`, e `schema_migrations` contém só `001`; e o mesmo vale para um `002_tx.sql` com `create table t_tx2(id int); commit; begin;`.
- **CA-23 (RV-03)** — *Dado* um diretório temporário com a cópia de `001_init.sql` e um arquivo `١٢٣_x.sql` (dígitos arábico-índicos), *quando* `apply_migrations` roda, *então* levanta `MigrationError` de nome de arquivo inválido antes de aplicar qualquer migração (`schema_migrations` não existe ou está vazia).
- **CA-24 (RV-04)** — *Dado* um diretório temporário com a cópia de `001_init.sql` e um espião em `pathlib.Path.read_bytes` que conta as chamadas por caminho, *quando* `apply_migrations` roda num schema vazio, *então* `001_init.sql` é lido exatamente 1 vez, e o `checksum` gravado em `schema_migrations` é o SHA-256 dos bytes devolvidos nessa leitura.
- **CA-25 (SEC-04-02, SEC-04-03, SEC-04-05)** — *Dado* o texto de `docs/deployment-plan.md`, *então*:
  - há uma seção de nível 2 cujo título contém `Riscos aceitos`;
  - no trecho dela até o próximo título de nível 2, uma linha contém `pool` e `503`, outra contém `psycopg.pool`, e o trecho contém `caddyserver.com/docs/caddyfile/directives`, `letsencrypt.org/docs/ct-logs` e `letsencrypt.org/docs/rate-limits`;
  - toda linha que contém `register_device.py` contém também `--env-file` e não contém `--database-url`.
- **CA-26 (manual, SEC-05-01, SEC-26-03)** — `statement_timeout` em produção:
  1. no SQL Editor, rodar `EXPLAIN ANALYZE` da agregação de `/api/v1/lots` e da `SELECT_LOT_SELECTION` com os parâmetros padrão da rota (§4.9, item 1) e anotar os tempos;
  2. escolher o valor pela regra da §4.9, item 1;
  3. rodar `alter role <papel> set statement_timeout = '<valor>';`;
  4. `select rolconfig from pg_roles where rolname = '<papel>';` → contém `statement_timeout=<valor>`;
  5. por uma conexão pelo pooler em modo transaction (porta 6543), com a URL lida de um arquivo local, `show statement_timeout` → `<valor>`;
  6. registrar no dev-report e no `deployment-plan.md` as saídas dos passos 1, 4 e 5 (sem segredos) e a data.
- **CA-27 (SEC-05-01, INFO-02, SEC-07, reserva)** — *Dado* o texto de `docs/deployment-plan.md`, *então*:
  - ele contém `statement_timeout`, `rolconfig` e `token_urlsafe(32)`;
  - a linha da tabela da §2 que começa com `| Render` contém `512 MB`, `0,1 CPU` e `render.com/docs/compute-plans`, e não contém `não confirmado`;
  - toda linha que contém `simulate.py` contém também `--env-file`;
  - o trecho da seção `Riscos aceitos` contém `57014`, e a linha que contém `57014` contém também `503` e `Database unavailable` e não contém `500 genérico` (SEC-26-02).
- **CA-28 (R-12, §4.10)** — *Dado* `infra/docker/api.Dockerfile` e `infra/docker/dashboard.Dockerfile` lidos como texto (instruções juntadas nas continuações `\`), *então*, em cada um:
  - toda instrução `FROM` casa `^FROM python:3\.12\.\d+-slim-(bookworm|trixie)(@sha256:[0-9a-f]{64})?( AS \w+)?$`;
  - há exatamente 1 `COPY --from=ghcr.io/astral-sh/uv:<X.Y.Z>` (casa `uv:\d+\.\d+\.\d+(@sha256:[0-9a-f]{64})? /uv /uvx /bin/`), com a mesma versão nos dois arquivos;
  - há um `RUN` que contém `uv sync --package qc-api --frozen --no-dev` (resp. `qc-dashboard`), e o arquivo contém `UV_PYTHON_DOWNLOADS=0` e `WORKDIR /app`;
  - o arquivo não contém `--no-editable`, `--extra`, `--all-extras`, `--all-packages`, `pip install` nem `latest`;
  - a última instrução `USER` é `USER 10001:10001` e vem depois do último `RUN`;
  - há exatamente 1 `HEALTHCHECK`, com `--interval=60s` e o caminho `/api/v1/health` (resp. `/_stcore/health`);
  - o `CMD` está em forma exec (JSON) e é exatamente o da tabela da §4.10, sem `uv` nem `uvx`;
  - há `LABEL partqc.component="api"` (resp. `"dashboard"`);
  - nenhum `ENV` ou `ARG` tem nome que contenha `DATABASE_URL`, `API_KEY`, `TOKEN`, `PASSWORD` ou `SECRET`.
- **CA-29 (§4.12, R-03)** — *Dado* `infra/compose.yaml` carregado com `yaml.safe_load`, *então*:
  - **projeto:** `name == "partqc"`, e os serviços são exatamente `{"caddy", "api", "dashboard"}`;
  - **portas:** só `caddy` tem `ports`, igual a `["80:80", "443:443", "443:443/udp"]`; `api` e `dashboard` não têm `ports` e expõem `8000` e `8501`, respectivamente;
  - **proibições:** nenhum serviço tem `privileged`, `network_mode`, `pid`, `container_name` ou um volume com `docker.sock`;
  - **build:**
    - `api.build == {"context": "..", "dockerfile": "infra/docker/api.Dockerfile"}`, e o `dashboard` é o análogo;
    - `api.env_file` é `[".env.api"]` (ou o item equivalente com `path` e sem `required: false`), e o `dashboard` é o análogo com `.env.dashboard`;
  - **variáveis:**
    - `dashboard.environment.API_BASE_URL` casa `^https://\$\{PUBLIC_HOST:\?[^}]*\}$`;
    - `caddy.environment.PUBLIC_HOST` casa `^\$\{PUBLIC_HOST:\?[^}]*\}$`, e `caddy.networks.partqc.aliases` tem 1 item que casa a mesma regex;
    - nenhum `environment` tem chave `DATABASE_URL` ou `READ_API_KEY`;
  - **caddy:**
    - `caddy.image` casa `^caddy:2\.\d+\.\d+(-alpine)?(@sha256:[0-9a-f]{64})?$`;
    - `caddy.volumes` contém `./Caddyfile:/etc/caddy/Caddyfile:ro`, `caddy_data:/data` e `caddy_config:/config`, e os dois nomeados estão no topo;
    - `caddy.cap_drop == ["ALL"]` e `caddy.cap_add == ["NET_BIND_SERVICE"]`;
    - `caddy.depends_on` cita `api` e `dashboard`, sem `condition: service_healthy`;
  - **api e dashboard:** `cap_drop == ["ALL"]`;
  - **todos os serviços:** `restart == "unless-stopped"`, `"no-new-privileges:true"` em `security_opt`, `logging == {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}`, e `mem_limit` e `cpus` iguais às strings da tabela da §4.12, item 4;
  - **rede:** a rede `partqc` existe e não tem `internal: true`.
- **CA-30 (§4.13, R-13)** — *Dado* `infra/Caddyfile` como texto, sem as linhas de comentário, *então*:
  - o único endereço de site é `{$PUBLIC_HOST}`, e não há bloco global (nenhuma linha começa com `{` sozinha);
  - não há nome de domínio literal (nenhum token casa `\b[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}\b`, exceto `api:8000` e `dashboard:8501`, que não casam) nem IPv4 literal;
  - há `handle /api/*` com `reverse_proxy api:8000` e um `handle` sem matcher com `reverse_proxy dashboard:8501`;
  - não aparecem `handle_path`, `tls internal`, `acme_ca`, `local_certs`, `includeSubDomains`, `preload`, `/docs` nem `openapi`;
  - aparecem `Strict-Transport-Security "max-age=31536000"` e `X-Content-Type-Options "nosniff"`.
- **CA-31 (§4.14)** — *Dado* `.github/workflows/docker.yml` carregado, *então*:
  - os gatilhos são `pull_request` e `push` com `branches: [main]`, e `permissions == {"contents": "read"}`;
  - há exatamente 1 job, em `ubuntu-latest`, com `timeout-minutes` ≤ 30 e o serviço `postgres:16`;
  - os `uses` começam com `actions/checkout@v` e `astral-sh/setup-uv@v`, sem `@main` nem `@master`;
  - um passo roda `uv sync --all-packages --frozen` e um passo posterior roda `uv run pytest -m docker -q`, com `PARTQC_DOCKER_TESTS` igual a `"1"` no `env` do passo ou do job;
  - o arquivo não contém `secrets.`, `docker login` nem `docker push`;
  - `.github/workflows/ci.yml` continua com exatamente 1 job.
- **CA-32 (§4.14)** — *Dado* `pyproject.toml`, *então* `tool.pytest.ini_options.markers` tem uma entrada que começa com `docker:`; e, *dado* `infra/tests/docker_support.py`:
  - `docker_tests_enabled({})`, `docker_tests_enabled({"PARTQC_DOCKER_TESTS": "true"})` e `docker_tests_enabled({"PARTQC_DOCKER_TESTS": "0"})` são `False`, e `docker_tests_enabled({"PARTQC_DOCKER_TESTS": "1"})` é `True`;
  - `check_docker(run=f)`, com `f` devolvendo 1 para `["docker", "compose", "version"]` e 0 para o resto, levanta `DockerUnavailableError` com `compose` na mensagem; com `f` devolvendo 0 para tudo, não levanta;
  - `copy_tracked_tree(tmp_path / "ctx", {"x/y.txt": b"z"})` cria `ctx/pyproject.toml`, `ctx/uv.lock` e `ctx/x/y.txt`, e `git status --porcelain` da árvore real não muda.
- **CA-33 (docker, §4.12)** — *Dado* uma cópia temporária do repositório (`copy_tracked_tree`) com `infra/.env` (`PUBLIC_HOST=partqc.example.org`), `infra/.env.api` (`DATABASE_URL=postgresql://<user>:<password>@db.example.org:6543/postgres` e uma `READ_API_KEY` gerada no teste) e `infra/.env.dashboard`, e um ambiente de processo sem `PUBLIC_HOST`, *quando* se roda `docker compose -f <cópia>/infra/compose.yaml config --format json`, *então*:
  - o código é 0;
  - `services.dashboard.environment.API_BASE_URL == "https://partqc.example.org"`, e o alias do `caddy` na rede `partqc` é `partqc.example.org`;
  - o `mem_limit` resolvido da `api` corresponde a 512 MiB e o do `dashboard` a 1 GiB;
  - com `API_MEM_LIMIT=768m` no `infra/.env`, o da `api` corresponde a 768 MiB;
  - *dado* o `infra/.env` sem `PUBLIC_HOST`, *então* o código é diferente de 0 e o stderr contém `PUBLIC_HOST`;
  - *dado* a cópia sem `infra/.env.api`, *então* o código é diferente de 0.
- **CA-34 (docker, §4.13)** — *Dado* a imagem do `caddy` exatamente como em `infra/compose.yaml` e o `infra/Caddyfile` montado só para leitura, *quando* se roda `caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile` com `PUBLIC_HOST=partqc.example.org`, *então*:
  - o código é 0 e o stderr não tem aviso de formatação;
  - numa busca recursiva no JSON da saída, todo `match.host` citado contém só `partqc.example.org`;
  - existe exatamente 1 handler `reverse_proxy` com `upstreams == [{"dial": "api:8000"}]`, cuja rota tem `match` com `path == ["/api/*"]`;
  - existe exatamente 1 handler `reverse_proxy` com `upstreams == [{"dial": "dashboard:8501"}]`, cuja rota não tem matcher de `path`;
  - não há outro `dial`;
  - existe um handler `headers` com `Strict-Transport-Security == ["max-age=31536000"]`.
- **CA-35 (docker, R-12)** — *Dado* as imagens construídas com `build_image` a partir dos dois Dockerfiles, *quando* se roda `docker run --rm --entrypoint python <imagem> -c <script>`, *então*:
  - em ambas, `importlib.util.find_spec(m) is None` para `torch`, `torchvision`, `timm`, `onnx` e `onnxruntime`, e `sys.version_info[:2] == (3, 12)`;
  - na da API, `qc_api` e `qc_contracts` são importáveis e `find_spec("streamlit") is None`;
  - na do dashboard, `qc_dashboard`, `qc_contracts` e `streamlit` são importáveis e `find_spec("psycopg") is None`.
- **CA-36 (docker, R-02, R-03, R-14)** — *Dado* um contexto montado com `build_image(..., extra_files=<sentinelas>)`, com as sentinelas:
  - de ambiente: `.env`, `.env.prod`, `.env.migrate`, `infra/.env`, `infra/.env.api`, `infra/.env.dashboard` e `.streamlit/secrets.toml`;
  - do Git e de ferramentas: `.git/config`, `.claude/settings.local.json`, `notas-locais/diario.md` e `.venv/sentinela-do-host`;
  - de dados e fotos: `ml/data/raw/screw/good/S-001__a__x.jpg`, `edge/data/captures/2026-10-18/x.jpg`, `edge/data/outbox.sqlite3`, `foto.jpg`, `foto.jpeg`, `foto.png`, `foto.heic` e `foto.webp`;
  - do modelo: `ml/models/partqc-sentinel-v0/model.onnx`, `ml/models/partqc-sentinel-v0/metrics.json` e `ml/reports/partqc-sentinel-v0/type_confusion.png`;

  *quando* as duas imagens são construídas e se roda nelas `test -e /app/<caminho>` para cada sentinela, *então*:
  - nenhuma das sentinelas de ambiente, do Git e de ferramentas, de dados e fotos, nem o `model.onnx`, existe em nenhuma das duas imagens;
  - na do dashboard, existem `/app/ml/models/partqc-sentinel-v0/metrics.json`, `/app/ml/reports/partqc-sentinel-v0/type_confusion.png` e `/app/.streamlit/config.toml`.
- **CA-37 (docker, §4.3, §4.10)** — *Dado* as duas imagens do CA-35, *quando* se roda `docker image inspect`, *então*:
  - `Config.User == "10001:10001"`, `Config.WorkingDir == "/app"` e `Config.Labels["partqc.component"]` é `api` (resp. `dashboard`);
  - `Config.Healthcheck.Test` começa com `CMD` e cita `/api/v1/health` (resp. `/_stcore/health`), com `Interval == 60000000000`;
  - nenhum item de `Config.Entrypoint` e `Config.Cmd` é `uv` ou `uvx`;
  - `docker run --rm --entrypoint id <imagem> -u` imprime `10001`;
  - na do dashboard, sem `MODEL_METRICS_PATH` no ambiente, `python -c "from qc_dashboard import config; print(config.REPO_ROOT); print(config.get_model_metrics_path())"` imprime `/app` e `/app/ml/models/partqc-mnv3-v1/metrics.json` (RV-06).
- **CA-38 (§4.6, §4.15, §4.16)** — *Dado* o texto de `docs/deployment-plan.md`, *então*:
  - ele contém `docker compose -f infra/compose.yaml up -d --build`, `git pull --ff-only`, `free -h`, `nproc`, `chmod 600`, `<subdominio>` e `--filter label=partqc.component`;
  - toda linha que contém `docker compose` e o subcomando `config` (a palavra `config` separada por espaço) contém também `--quiet`;
  - toda linha que contém `ufw reset`, `ufw default`, `ufw delete`, `ufw --force`, `iptables -F`, `docker system prune`, `volume prune` ou `down -v` contém também `Nunca` ou `nunca`;
  - o arquivo não contém `streamlit.app` nem `Koyeb` fora da tabela da §2 (onde a linha do Koyeb, se existir, diz "não usado").
- **CA-39 (§4.12)** — *Dado* `.env.example`, *então*:
  - existe a linha `PUBLIC_HOST=<subdominio>` e as linhas `API_MEM_LIMIT=512m`, `API_CPUS=1.0`, `DASHBOARD_MEM_LIMIT=1g`, `DASHBOARD_CPUS=1.0`, `CADDY_MEM_LIMIT=256m` e `CADDY_CPUS=0.5`;
  - a linha que começa com `CLOUD_API_URL=` é `CLOUD_API_URL=https://<subdominio>`;
  - o arquivo não contém `onrender.com` nem `Streamlit Community Cloud`;
  - as linhas de comentário imediatamente acima de `API_BASE_URL=` contêm `.streamlit/secrets.toml` (CA-11 da SPEC-028, preservado).
- **CA-40 (manual, §4.15)** — Rede e coexistência na VPS:
  1. antes do primeiro `up`, o `ss` do item 1 da §4.15 não mostra processo nas portas 80 e 443, e o `ufw status verbose` está salvo;
  2. depois do `up`, `docker compose -f infra/compose.yaml ps` mostra portas publicadas só no `caddy`;
  3. `ss -tlnp` do host não tem `:8000` nem `:8501`, e, de outra máquina, `curl --connect-timeout 5 http://<IP>:8000/` e `curl --connect-timeout 5 http://<IP>:8501/` falham;
  4. `sudo ufw status verbose` comparado com o arquivo salvo não tem nenhuma regra a menos;
  5. cada um dos outros projetos do humano na VPS responde como antes (o humano lista quais conferiu, sem nomes de host);
  6. registrar no dev-report sem o IP nem o subdomínio.
- **CA-41 (automatizado, R-13)** — *Dado* `infra/compose.yaml`, `infra/Caddyfile`, `infra/docker/*`, `infra/render.yaml`, `.github/workflows/docker.yml`, `.github/workflows/keepalive.yml` e `.env.example`, *então* nenhum contém IPv4 literal (`\b\d{1,3}(\.\d{1,3}){3}\b`) diferente de `0.0.0.0` e `127.0.0.1`. *Dado* `docs/deployment-plan.md` e `.env.example`, *então* toda ocorrência de `PUBLIC_HOST=` é seguida exatamente de `<subdominio>`, e todo `CLOUD_API_URL=`, `DASHBOARD_URL=` e `KEEPALIVE_URL=` com valor não vazio tem o valor começando por `https://<subdominio>` ou por `https://<servico>.onrender.com` (a reserva).
- **CA-42 (manual, R-13)** — Na VPS, com o `infra/.env` preenchido: `git grep -nF -e "$(grep '^PUBLIC_HOST=' infra/.env | cut -d= -f2-)"` → nenhuma linha; o mesmo com o IPv4 público da VPS → nenhuma linha; e os dev-reports e security-reports da SPEC-015 em `reviews/SPEC-015/` também não têm nenhum dos dois (o reviewer confere com o mesmo `git grep`, a partir dos valores que o humano informa fora do repositório).
- **CA-43 (manual, §4.16, R-03)** — Atualização e rollback ensaiados na VPS:
  1. depois do primeiro `up`, `docker compose -f infra/compose.yaml run --rm --no-deps --entrypoint find api /app -maxdepth 2 -name '.env*'` e o mesmo com `dashboard` → nenhuma linha, ou só `/app/.env.example`;
  2. fazer o ciclo da §4.16, item 1, com um commit novo da `main` → health 200 e smoke `PASS`;
  3. rollback para o commit anterior pela §4.16, item 3 → health 200;
  4. voltar para a `main` → health 200;
  5. `docker volume ls` mostra `partqc_caddy_data` o tempo todo, e `docker compose -f infra/compose.yaml logs caddy` não mostra uma nova emissão de certificado no ciclo;
  6. registrar no dev-report.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | YAML/TOML; Dockerfiles, compose e Caddyfile como texto; busca de segredos e de IPs; smoke com `MockTransport`; `docker_support`; ajustes do executor (§4.7); um teste `docker` de fumaça que constrói as duas imagens | `infra/tests/` |
| Aceite (tester) | CA-01, CA-02, CA-05…CA-12, CA-20…CA-25, CA-27…CA-39 e CA-41. CA-21 a CA-24 marcados `db`; CA-33 a CA-37 marcados `docker` | `infra/tests/acceptance/test_spec_015.py` |
| Manual (dupla + autor) | CA-13…CA-19, CA-26, CA-40, CA-42 e CA-43 | VPS e produção; resultado no dev-report e no `deployment-plan.md`, sem o subdomínio nem o IP |

- Nenhum teste automatizado acessa a internet, a VPS ou os serviços reais. As imagens base são baixadas do Docker Hub e do GHCR no build, o que não conta como serviço do projeto.
- O smoke é importado por `importlib.util.spec_from_file_location`.
- Os testes do executor usam o Postgres de teste da SPEC-003 (fixtures do `conftest.py`, com banco temporário próprio quando precisam de schema vazio), sem mock de banco.
- Os testes `docker` rodam no workflow `docker` (§4.14). Localmente, o tester os roda com `PARTQC_DOCKER_TESTS=1` (a máquina da dupla tem Docker) e registra no test-report a contagem de testes `docker` executados. Um test-report com os testes `docker` só pulados não vale como PASS desses CAs.
- Os CAs 33 a 37 usam contextos e cópias em `tmp_path`, via `copy_tracked_tree`, e nunca criam `.env*` na árvore real. As chaves dos testes são geradas com `secrets.token_urlsafe`, nunca literais.

## 7. Riscos e notas para o implementador

- A allowlist do `security-devops` (`.claude/hooks/guard_paths.py`) cobre todos os caminhos desta SPEC: `infra/**` (inclusive `infra/docker/` e `infra/tests/`, menos `acceptance/`), `.github/**`, `.streamlit/**`, `scripts/smoke_test.py`, `.env.example`, `.gitignore`, `pyproject.toml`, `uv.lock` e `docs/deployment-plan.md`. Um `.dockerignore` na raiz **não** está coberto (§4.11).
- **`README.md` da raiz e `.claude/agents/security-devops.md`** ainda citam o Render e o Streamlit CC como caminho principal. Ficam fora desta SPEC e são atualizados pelo orquestrador. O `description` do agente é conferido literalmente pelo CA de agentes da SPEC-001 (`tests/acceptance/test_spec_001.py`) e não deve ser mudado sem ajustar esse teste.
- **Dockerfile por arquivo `.dockerignore`:** depende do BuildKit, o builder padrão. Se o `docker compose build` da VPS não respeitar o arquivo, o CA-43, passo 1, mostra o `.env*` dentro da imagem. Nesse caso, parar, remover as imagens (`docker image rm`), não publicar e registrar `SPEC_ISSUE`.
- **`docker compose config` imprime segredos:** sem `--quiet`, ele mostra os valores dos `env_file`. Nos testes, os valores são fictícios; na VPS, só `--quiet` (§4.6, passo 6).
- **Alias do subdomínio na rede:** se o alias da §4.12, item 3, não resolver dentro da rede (o dashboard mostra "API acordando" com a API saudável), o caminho alternativo é remover o alias, para que a resolução vá pelo DNS público. Isso exige registrar `SPEC_ISSUE` com o log do dashboard, sem a chave. A regra `https://` da SPEC-028 não muda em nenhum dos dois casos.
- **Capacidades do Caddy:** a imagem oficial roda como root. Com `cap_drop: [ALL]` e `cap_add: [NET_BIND_SERVICE]`, ela deve conseguir abrir 80/443 e gravar em `/data`. Se o Caddy não subir por falta de capacidade, registrar `SPEC_ISSUE` com a linha do log, em vez de tirar o `cap_drop` por conta própria.
- **HTTP/3:** a imagem do Caddy pode avisar no log sobre o tamanho do buffer UDP. O exemplo oficial usa `cap_add: NET_ADMIN` para isso. Esta SPEC não concede `NET_ADMIN`, e o aviso é aceito: o HTTP/2 por TCP continua.
- **Interpolação no `env_file`:** uma senha do Supabase com `$` é truncada sem aviso se não estiver entre aspas simples (§4.12).
- **`unhealthy` com o Supabase pausado:** é esperado, e o contêiner não reinicia. O Caddy sobe mesmo assim (sem `condition: service_healthy`).
- Os limites de free tier e as versões das imagens mudam: confira cada um na fonte oficial antes de fixar e atualize "Verificado em" no `deployment-plan.md`.
- Os testes que conferem a detecção do CA-05 e do CA-41 montam os exemplos de segredo e de IP por concatenação em tempo de execução, para o próprio arquivo de teste não casar com os padrões.
- Workflows agendados podem atrasar alguns minutos; o intervalo de 3 dias tem folga contra a pausa de 7 dias do Supabase.
- **Migrações nunca rodam no GitHub Actions contra produção** (SEC-03 da SPEC-003): o repositório é público e os logs do Actions também, e o executor mostra o `DETAIL` e o `LINE` do servidor. Elas também não rodam a partir da VPS: só da máquina do humano, com `.env.migrate`. Se um dia isso mudar, o executor passa a mostrar só o `sqlstate` e o `diag.message_primary`, numa SPEC nova.
- **Por que conexão direta/modo session, e não `pg_advisory_xact_lock`:** o lock de transação exigiria pegar o lock e refazer o plano dentro de cada migração, um redesenho do executor aprovado na SPEC-003. A recomendação oficial do Supabase para migrações é a conexão direta (§1), e o modo session é o equivalente em IPv4. O prazo do lock (§4.7, item 2) continua valendo como defesa, inclusive na conexão direta.
- A recusa da porta 6543 é uma heurística: ela cobre o caso real (a `DATABASE_URL` da API usada por engano), não um pooler numa porta não padrão.
- O CA-20 da SPEC-003 usa a porta 1 e continua passando; nenhum CA da SPEC-003 muda.
- `uv run` sincroniza o ambiente antes de rodar e, por padrão, inclui o grupo `dev`; por isso, as imagens não usam `uv run` (§4.10). No Render (reserva), se o log mostrar instalação no start, use `uv run --frozen --no-dev --package qc-api ...` e atualize §4.1, o `deployment-plan.md` e o CA-01 por `SPEC_ISSUE`.

## 8. Definição de pronto

- [ ] Todos os CAs automatizados com teste de aceite passando (test-report PASS, com os testes `docker` executados e não só pulados), e os CAs CA-13…CA-19, CA-26, CA-40, CA-42 e CA-43 registrados
- [ ] review-report APPROVED + security-report PASS (feito pelo **reviewer**)
- [ ] CI verde (`ci` e `docker`); `ruff` limpo
- [ ] `docs/deployment-plan.md` com os valores finais e as datas, sem o subdomínio real nem o IP (só `<subdominio>`); `.env.example` atualizado
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-12 | Mudanças: (a) §1 com as pendências de produção da SPEC-003; (b) §3.1 inclui `infra/migrate.py` (só a §4.7) e corrige a nota de `testpaths`; §3.2 registra o papel só de DML como não adotado e proíbe migrações no Actions; (c) §4.6, passo 1: migração pelo pooler em modo session, com `.env.migrate`; (d) §4.7 nova: recusa da porta 6543, prazo do lock com `pg_try_advisory_lock` (`lock_wait_s`, padrão 30 s), detecção de controle de transação no arquivo, regex só com dígitos ASCII e leitura única do arquivo; (e) CA-06 ganhou `.env.migrate`; CA-14 ganhou `schema_migrations`, `relforcerowsecurity` e a verificação de grants de `anon`/`authenticated`; CAs novos: CA-19 (manual, `search_path` e migração) e CA-20 a CA-24 (executor). Nenhuma decisão de ADR muda: a API continua no modo transaction (ADR-006). SPEC marcada como "Aguardando reaprovação humana". | SPEC_ISSUE-01 e RV-02 a RV-04 de `reviews/SPEC-003/r1-review-report.md`; SEC-01 a SEC-05 de `reviews/SPEC-003/r1-security-report.md` | Orquestrador, a pedido do humano |
| 2026-10-12 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
| 2026-10-13 | Mudanças: (a) §1 com as três pendências de operação da SPEC-004; (b) §4.6, passo 3: registro de dispositivos com `--env-file .env.migrate`, nunca `--database-url` com a URL de produção; (c) §4.8 nova: seção "Riscos aceitos" no `deployment-plan.md` (rajada anônima no pool, com a verificação do Render, e o log do `psycopg.pool`); (d) CA-25 novo; (e) §6 atualizada. Nenhum CA existente muda. SPEC marcada como "Aguardando reaprovação humana". | SEC-04-02, SEC-04-03 e SEC-04-05 de `reviews/SPEC-004/r2-security-report.md` | Orquestrador, a pedido do humano |
| 2026-10-13 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
| 2026-10-17 | Mudanças: (a) passa a depender da SPEC-026 (teto da carta p, sem o qual a rota SPC passa dos 512 MB do Render) e da SPEC-027 (migração `002` e simulador corrigido); (b) §1 com as pendências de operação das SPECs 005, 006 e 014; (c) §3.2 cita a migração `002` (SPEC-027), aplicada pelo CA-19 junto com a `001`; (d) §4.6: passo 6 com `--env-file` e os limites do simulador, passo 7 novo (`statement_timeout`); (e) §4.9 nova: `statement_timeout` medido e aplicado por `alter role`, conferido em `pg_roles.rolconfig` e pela porta 6543; geração e troca da `READ_API_KEY`; linha do Render com 512 MB e 0,1 CPU; simulador em produção só com execuções pequenas e a chave pelo arquivo de ambiente; (f) CAs novos: CA-26 (manual) e CA-27; §6 e §8 atualizadas. Nenhum CA existente muda. Fatos externos conferidos pelo architect em 2026-10-17: <https://render.com/docs/compute-plans> e <https://supabase.com/docs/guides/database/postgres/timeouts>. SPEC marcada como "Aguardando reaprovação humana". | SEC-05-01 e INFO-02 de `reviews/SPEC-005/r1-security-report.md`; SEC-06-01 e a pendência de deploy de `reviews/SPEC-006/r1-security-report.md`; SEC-07 e a mitigação do SEC-01 de `reviews/SPEC-014/r1-security-report.md` | Orquestrador, a pedido do humano |
| 2026-10-17 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
| 2026-10-17 | Mudanças: (a) §1 com as pendências de deploy das SPECs 013, 026 e 027; (b) §3.2: o código do dashboard das pendências de segurança vai para a SPEC-028; (c) §4.3: `qc-dashboard` importado da cópia do repositório, ou `MODEL_METRICS_PATH` absoluto nos Secrets; (d) §4.6, passo 4: `API_BASE_URL` sempre `https://`; (e) §4.9, item 1: `EXPLAIN ANALYZE` da consulta nova da carta (`SELECT_LOT_SELECTION`), valor fixo de `15s` (salvo se 3× a leitura medida passar disso), registro no `deployment-plan.md` de que o timeout é o teto do custo de banco, e o efeito aceito corrigido de 500 para **503** `Database unavailable`; (f) CA-17 ganha a conferência da página "Sobre o modelo" e do `https://`; CA-19 ganha a conferência das restrições da `002` com `pg_get_constraintdef`; CA-26 usa a consulta nova; CA-27 exige `503` e `Database unavailable` (e não `500 genérico`) na linha do `57014`. Nenhum outro CA muda. SPEC marcada como "Aguardando reaprovação humana". | RV-06 de `reviews/SPEC-013/r1-review-report.md`; SEC-13-01 de `reviews/SPEC-013/r2-security-report.md`; SEC-26-02 e SEC-26-03 de `reviews/SPEC-026/r1-security-report.md`; SEC-02 de `reviews/SPEC-027/r1-security-report.md` | Orquestrador, a pedido do humano |
| 2026-10-18 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
| 2026-10-18 | **Reescrita para a VPS pessoal (ADR-018).** Mudanças: (a) título, §1, §2 e §3: API e dashboard na VPS com Docker Compose e Caddy, banco no Supabase, Render como reserva fria; Streamlit CC, Koyeb e `dashboard/requirements.txt` removidos; deploy automático e registro de imagens proibidos; `/docs` não publicado; tag `infra` e dependência da SPEC-028; (b) §4.1: `render.yaml` como reserva (conteúdo igual); §4.2: o healthcheck da API vira o keep-alive principal; §4.3 nova: imagem do dashboard editável em `/app` (RV-06); §4.4: chaves proibidas no `config.toml`; §4.5: 8ª checagem (`dashboard_health`), sem `verify=False` e sem URL nos motivos; §4.6: passos da VPS; §4.8: riscos da VPS (sem proteção de DDoS nem limitação de taxa, CT logs, ponto único de falha, limite de emissão); §4.9: troca da `READ_API_KEY` nos arquivos da VPS; (c) seções novas: §4.10 Dockerfiles, §4.11 `.dockerignore` por Dockerfile, §4.12 compose e arquivos de ambiente (limites de recursos com padrões no `infra/.env`), §4.13 Caddyfile, §4.14 workflow `docker` e marcador `docker`, §4.15 firewall sem apagar regras, §4.16 atualização, rollback e reserva; (d) CAs: CA-03 e CA-04 removidos; CA-06, CA-07, CA-08, CA-10, CA-12, CA-13, CA-15, CA-17, CA-18 e CA-25 alterados; CA-28 a CA-43 novos; os demais (CA-01, 02, 05, 09, 11, 14, 16, 19 a 24, 26 e 27) sem mudança; §6, §7 e §8 atualizadas. As §4.7 e §4.9 (item 1 e 4) não mudam. Fatos externos conferidos pelo architect em 2026-10-18 (fontes no §1 e no ADR-018). SPEC marcada como "Aguardando reaprovação humana". | Decisão do humano de hospedar na VPS pessoal (ADR-018) | Orquestrador, a pedido do humano |
| 2026-10-18 | Reescrita reaprovada pelo humano, junto com a confirmação da decisão 4 do ADR-018 (`/docs` e `/openapi.json` não publicados). | Aprovação humana | Humano (Carlos) |
| 2026-10-19 | **Correção do SPEC_ISSUE-01 (r1): só o CA-05.** **Texto antigo:** "*Dado* os arquivos de `git ls-files` fora de `docs/`, *quando* busco `postgres(ql)?://[^\s:/@]+:[^\s@]+@`, `eyJ…`, `-----BEGIN [A-Z ]*PRIVATE KEY-----` e `service_role…`, *então* não há ocorrência, exceto os marcadores e as credenciais de teste conhecidos da lista de permissão (`<user>:<password>`, `postgres:postgres@localhost`, `u:pw@127.0.0.1`, `u:s3cr3t-pw@127.0.0.1`); e, em `.env.example`, [...]". **Texto novo:** (a) o escopo fica explícito: todo arquivo de `git ls-files` fora de `docs/`, inclusive `reviews/` e as suítes de teste, decodificado com `errors="replace"`, sem pular arquivo; (b) os padrões de JWT, chave privada e `service_role` ficam sem exceção; (c) no padrão de URL do Postgres (o mesmo de antes, com os grupos `user` e `password`), a lista de permissão vira três regras fechadas: marcador de documentação (`password` igual a `<minúsculas>`, `…` ou `...`), valor montado em tempo de execução (`password` igual a `{NOME}` ou `${NOME}`) e cinco credenciais fictícias exatas (as três de antes com host, mais `postgres:postgres@...` e `u:senha@…`, que só aparecem como exemplo em relatórios); (d) a cláusula do `.env.example` não muda. **Evidência:** a varredura literal casava, fora da lista antiga, as f-strings `u:{SECRET}@127.0.0.1` de `infra/tests/acceptance/test_spec_003.py` (linhas 640, 1008, 1010 e 1023) e os marcadores de `reviews/SPEC-009/r1-review-report.md:46`, `reviews/SPEC-022/r1-review-report.md:22 e 29` e `reviews/checklist.md:42`; nenhum é segredo, e o architect conferiu que, com as regras novas, todas as ocorrências atuais do repositório fora de `docs/` são aceitas. **Efeito na R-03:** não enfraquece. O escopo não diminui (`reviews/` continua dentro, e nenhum arquivo é pulado), nenhum padrão sai, e cada forma aceita ou não tem valor de senha (marcador, reticências, nome de variável) ou tem um valor fictício fixo e público. Uma senha real numa URL continua reprovando o CA. Classificação ADR-019: exige humano (X-7: o CA-05 verifica a R-03, regra inegociável). Nenhuma outra exclusão se aplica (o escopo, os padrões e os casos de erro não mudam; X-6 não se aplica). SPEC marcada como "Aguardando reaprovação humana"; o status continua `Blocked` (r1) até a reaprovação. | SPEC_ISSUE-01 de `reviews/SPEC-015/r1-dev-report.md` | Orquestrador |
| 2026-10-19 | Correção do SPEC_ISSUE-01 (CA-05) reaprovada pelo humano; `Blocked` → `In Dev`, retomada na r1. O humano também pediu que o autor volte a montar em tempo de execução as credenciais fictícias de `infra/tests/test_cli.py` (commit `b067b85`), como manda o `reviews/checklist.md`. | Fluxo do loop (§4 da skill `features`) | Humano (Carlos) |
