# Plano de deploy

Este documento é de responsabilidade do agente `security-devops` (SPEC-015, SPEC-039). Ele segue o ADR-018, alterado pelo **ADR-023**: a API e o dashboard rodam na VPS pessoal, publicados pelo **Coolify** já instalado nela, como um recurso Docker Compose a partir do repositório público. O TLS e o domínio ficam no proxy do Coolify (Traefik), e o Caddy fica só como roteador interno. O banco continua no Supabase, e o Render, como reserva fria da API.

Histórico do arquivo:

- 2026-10-18: estrutura reescrita pelo architect para o ADR-018;
- 2026-10-19: comandos, valores finais e datas completados pelo autor da SPEC-015;
- 2026-10-25: reescrita pelo architect para o Coolify (ADR-023). O autor da SPEC-039 confere e completa as versões e as datas.

> **Estado em 2026-10-25:** o ADR-023 está `Proposto`, e a SPEC-039, em `Draft`. Os passos da §4 descrevem o deploy pelo Coolify e **só podem ser executados depois do merge da SPEC-039**. O `infra/compose.yaml` da `main` até lá publica as portas 80 e 443, que o proxy do Coolify já ocupa, e o deploy falharia.

Os limites de free tier e as versões mudam com frequência: **confira de novo antes de cada decisão** e atualize a coluna "Verificado em".

Nunca entram neste arquivo nem em nenhum outro do repositório (R-13):

- o subdomínio real (use `<subdominio>`);
- o IP da VPS (use `<IP>`);
- o UUID do recurso no Coolify (use `<uuid>`).

Os agentes não têm acesso à VPS, ao painel do Coolify, ao Supabase, ao DNS nem às contas. Tudo o que está na §4 e na §9 é **passo humano**.

## 1. Ambientes

| Ambiente | Onde | Para quê |
|---|---|---|
| `local` | Notebook da equipe | Desenvolvimento e testes: a API local aponta para um **Postgres local em Docker** (o mesmo dos testes, `TEST_DATABASE_URL`) |
| `edge` | Notebook da demo | Gateway de borda na LAN (`qc-edge`) |
| `cloud` | VPS pessoal com Coolify (recurso Docker Compose: `caddy`, `qc-api`, `qc-dashboard`) atrás do proxy do Coolify, e Supabase | API e dashboard públicos em `https://<subdominio>` (dados protegidos por chave) |
| `cloud` (reserva) | Render (Web Service free) | Só a API, publicada num incidente (§6) |

**Um único projeto Supabase** (o que a dupla já criou para este trabalho) é o banco de produção (`cloud`). O desenvolvimento e os testes usam o Postgres local em Docker, então os dados de teste nunca chegam ao Supabase. Confirme que o projeto está numa conta **pessoal** (R-13).

**Caminho de uma requisição** em `https://<subdominio>`:

1. o proxy do Coolify (Traefik, contêiner `coolify-proxy`, portas 80 e 443) termina o TLS;
2. ele encaminha por HTTP ao serviço `caddy` do recurso, na porta interna 80;
3. o Caddy (`infra/Caddyfile`) manda `/api/*` para a API e todo o resto (inclusive o WebSocket `/_stcore/stream`) para o Streamlit.

`/docs` e `/openapi.json` da API **não** são publicados (ADR-018, decisão 4). Nenhum contêiner do PartQC publica portas (ADR-023).

## 2. Serviços e limites

| Serviço | Uso | Limites relevantes | Fonte | Verificado em |
|---|---|---|---|---|
| VPS pessoal do humano | `caddy`, `qc-api`, `qc-dashboard` (`infra/compose.yaml`), publicados pelo Coolify | Recurso pessoal **preexistente**, pago a cada 2 anos, sem custo adicional para o projeto (R-01, ADR-018). Gerenciada pelo Coolify; o proxy do Coolify ocupa as portas 80/443 e também publica o portfólio do humano (ADR-023). Versões, RAM, CPUs e disco: preencher no passo 2 da §4 (tabela "Conferência da VPS" logo abaixo) | Declaração do humano (ADR-018, ADR-023) | 2026-10-25 (a completar pelo humano no passo 2) |
| Coolify (auto-hospedado, já instalado) | Deploy do recurso Docker Compose a partir do GitHub; domínio e certificado no proxy (Traefik, resolvedor `letsencrypt`); variáveis do recurso | Software livre (Apache-2.0); auto-hospedado é "Free and open source", sem conta paga (R-01). Rolling update não suportado em Compose; o rollback do painel não está documentado para Compose (usar a §6). Versão: a preencher no passo 2 | <https://github.com/coollabsio/coolify>, <https://coolify.io/docs/knowledge-base/docker/compose>, <https://coolify.io/docs/knowledge-base/proxy/traefik/overview>, <https://coolify.io/docs/knowledge-base/rolling-updates> | 2026-10-25 (versão a completar pelo autor da SPEC-039) |
| Imagens base | `python:3.12.15-slim-trixie` (API e dashboard), `ghcr.io/astral-sh/uv:0.13.2` (cópia do binário `uv` no build), `caddy:2.11.7` (o `FROM` de `infra/docker/caddy.Dockerfile`, a partir da SPEC-039), todas fixadas também pelo digest `@sha256:` do índice multi-arquitetura | Software livre; nenhuma conta. Atualizar: conferir a tag nova na fonte, trocar a tag e o digest (`docker buildx imagetools inspect <imagem>:<tag>`) e abrir PR | <https://hub.docker.com/_/python>, <https://docs.astral.sh/uv/guides/integration/docker/>, <https://hub.docker.com/_/caddy> | 2026-10-19 |
| Caddy: headers da resposta | `infra/Caddyfile` (SPEC-032 §4.3): `Strict-Transport-Security`, `X-Content-Type-Options`, `Referrer-Policy "no-referrer"`, `Content-Security-Policy "frame-ancestors 'self'"`, `-Server` e `-Via` | "Prefix with `-` to delete the field"; apagar um campo ativa o `defer`, que "defers the execution of header operations until the response is being sent to the client", ou seja, depois do `reverse_proxy`. Conferido também na prática com a imagem `caddy:2.11.7` fixada: atrás de um `reverse_proxy` cuja origem responde `Server: uvicorn`, a resposta sai sem `Server` e sem `Via` e com os 4 headers. Com o Coolify, os headers passam pelo Traefik até o cliente (conferido no CA-13 da SPEC-015 e no CA-09 da SPEC-032) | <https://caddyserver.com/docs/caddyfile/directives/header> | 2026-10-24 |
| Docker Compose: `pids_limit`, `read_only` e `tmpfs` | `infra/compose.yaml` (SPEC-032 §4.4; no Caddy, `tmpfs` também em `/data` e `/config` a partir da SPEC-039) | `pids_limit` "tunes a container's PIDs limit" (conta processos **e threads**); `read_only` cria o contêiner com sistema de arquivos só de leitura; `tmpfs` na forma curta `<path>:<options>`. A opção `size` da forma curta não aparece na referência, mas foi conferida com `docker compose run` no Compose 5.6.1 e no Docker Engine 29.9.2: `/tmp` montado com `size=65536k` e com `nosuid,nodev,noexec` (os padrões do Docker). Se o Coolify preserva esses campos é conferido no CA-16 da SPEC-039 | <https://docs.docker.com/reference/compose-file/services/> | 2026-10-24 |
| Supabase Free | Postgres | 500 MB de banco por projeto, 2 projetos ativos, **pausa com pouca atividade num período de 7 dias** ("a few user requests to the database each day over the previous week is enough"), 5 GB de egress | <https://supabase.com/pricing>, <https://supabase.com/docs/guides/platform/free-project-pausing> | 2026-10-19 |
| Let's Encrypt (via proxy do Coolify) | Certificado TLS de `<subdominio>`, emitido e renovado pelo Traefik do Coolify | 5 certificados por conjunto exato de nomes a cada 7 dias; todo certificado emitido vai para os logs de CT | <https://letsencrypt.org/docs/rate-limits/>, <https://letsencrypt.org/docs/ct-logs/>, <https://coolify.io/docs/core/networking/domains> | 2026-10-25 |
| GitHub (repo **público** + Actions) | Código, CI (`ci` e `docker`), keep-alive, Releases para o `model.onnx`; fonte do recurso no Coolify (URL HTTPS, sem credencial) | "GitHub Actions usage is free for ... public repositories that use standard GitHub-hosted runners"; workflows agendados são desligados após 60 dias sem atividade no repositório e podem atrasar em horários de pico | <https://docs.github.com/en/billing/concepts/product-billing/github-actions>, <https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows>, <https://coolify.io/docs/applications/ci-cd/github/public-repository> | 2026-10-25 |
| Render (Web Service free) — **reserva fria** | `qc-api`, só num incidente (§6) | 512 MB de RAM e 0,1 CPU (plano `free`); dorme após 15 min sem tráfego; acorda em cerca de 1 min; 750 h/mês por workspace; região `virginia` no `infra/render.yaml` (ver nota abaixo); proteção automática contra DDoS | <https://render.com/docs/compute-plans>, <https://render.com/docs/free>, <https://render.com/docs/blueprint-spec>, <https://render.com/docs/ddos-protection> | 2026-10-19 |
| Koyeb | **Não usado** (ADR-018) | — | — | 2026-10-18 |
| Streamlit Community Cloud | **Não usado** (ADR-018): o dashboard roda na VPS | — | — | 2026-10-18 |
| Fly.io / Cloud Run / Oracle Cloud | **Não usar** | Exigem cartão ou conta de faturamento (violam R-01) | <https://docs.fly.io/about/pricing>, <https://docs.cloud.google.com/free/docs/free-cloud-features>, <https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm> | 2026-10-12 |
| HiveMQ Cloud | **Não usar no MVP** | A página oficial não lista mais plano gratuito Serverless | <https://www.hivemq.com/pricing/> | 2026-10-12 |

**Região da reserva no Render.** As regiões do blueprint são `oregon` (padrão), `ohio`, `virginia`, `frankfurt` e `singapore`, e a região não muda depois de criado o serviço (<https://render.com/docs/blueprint-spec>, 2026-10-19). O `infra/render.yaml` usa `virginia`, a mais próxima de um projeto Supabase em `sa-east-1` (São Paulo) ou em `us-east-1`. **Pendente do humano:** anotar a região do projeto Supabase no passo 1 da §4. Se for outra (por exemplo, `eu-central-1`), trocar a região do `infra/render.yaml` por PR antes de ativar a reserva (`frankfurt` para a Europa, `singapore` para a Ásia).

**Conferência da VPS** (passo 2 da §4; sem IP nem nome de host):

| Item | Comando | Valor | Data |
|---|---|---|---|
| Coolify | rodapé do painel ou Settings | a preencher | a preencher |
| Proxy do Coolify | `docker ps --filter name=coolify-proxy --format '{{.Image}} {{.Ports}}'` | a preencher (esperado: imagem `traefik`, portas 80 e 443) | a preencher |
| Docker Engine | `docker version --format '{{.Server.Version}}'` | a preencher | a preencher |
| Compose v2 | `docker compose version` | a preencher | a preencher |
| Buildx | `docker buildx version` | a preencher | a preencher |
| RAM (total e disponível) | `free -h` | a preencher | a preencher |
| CPUs | `nproc` | a preencher | a preencher |
| Disco livre | `df -h /` | a preencher | a preencher |
| Limites escolhidos nas variáveis do recurso | — | a preencher (padrões: API `512m`/`1.0`, dashboard `1g`/`1.0`, Caddy `256m`/`0.5`; `pids_limit` `256` nos três) | a preencher |

Regra dos limites (SPEC-015 §4.12): a soma dos três `mem_limit` fica abaixo da RAM disponível (descontados o Coolify, o proxy e o portfólio), cada `cpus` fica ≤ `nproc`, e a API não fica abaixo de `512m` sem uma decisão registrada aqui. A imagem do dashboard tem cerca de 670 MB e a da API cerca de 205 MB (medido no build local de 2026-10-19, depois da correção do RV-01 da r1, que tirou das camadas o cache do `uv`; antes eram 1,1 GB e 240 MB). O build roda na própria VPS pelo Coolify, e o disco precisa de folga para duas gerações de cada imagem durante uma atualização.

**Endurecimento dos contêineres (SPEC-032 §4.4).** Os três serviços rodam com `read_only: true` e com `tmpfs` em `/tmp` (`size=64m`). A partir da SPEC-039, o Caddy não guarda estado (os certificados ficam no proxy do Coolify) e tem `tmpfs` também em `/data` e `/config` (`size=16m`), no lugar dos volumes `caddy_data` e `caddy_config`. Nenhum `tmpfs` em `/home/app`: com `docker diff` num contêiner gravável, depois de abrir as 4 páginas do painel (gráficos, tabelas e o botão de download) e de chamar as rotas da API, nenhum arquivo foi criado nem alterado na API e no dashboard; o Caddy só escreve em `/data` e `/config` (medido em 2026-10-24). O limite de processos e threads (`pids_limit`) é `256` por serviço, ajustável pelas variáveis `API_PIDS_LIMIT`, `DASHBOARD_PIDS_LIMIT` e `CADDY_PIDS_LIMIT` do recurso no Coolify. Medido localmente em 2026-10-24, pelo `pids.current` do cgroup de cada contêiner:

| Serviço | Em repouso | Com carga | Carga usada |
|---|---|---|---|
| `dashboard` | 5 | 15 | 5 sessões simultâneas pelo WebSocket, 3 execuções cada, nas 4 páginas, com uma API falsa respondendo |
| `api` | 6 | 51 | 200 requisições, 100 simultâneas, sem banco (o pool de threads do AnyIO para em 40) |
| `caddy` | 9 | 11 | 2.000 requisições, 100 simultâneas |

`256` é pelo menos 5 vezes o pico medido. Na VPS, o CA-09 da SPEC-032 confere a coluna `PIDS` do `docker stats --no-stream` com 3 abas do painel abertas: no máximo metade do `pids_limit`.

- **Se um contêiner bater no `pids_limit`:** o Python registra `can't start new thread` (`RuntimeError`) e o Caddy (Go) sai com `failed to create new OS thread` e é reiniciado pelo `restart: unless-stopped`. Subir o valor da variável do serviço nas Environment Variables do recurso no Coolify (por exemplo, `DASHBOARD_PIDS_LIMIT=512`) e fazer **Redeploy** do recurso.
- **Se um serviço quebrar por causa do `read_only`** depois de uma atualização (uma dependência nova que escreve em disco): o log mostra `Read-only file system` (ou `EROFS`, ou `PermissionError` num caminho fora de `/tmp`), na aba de logs do serviço no painel ou em `docker logs --tail 200 <contêiner>`. Fazer o rollback da §6 e abrir uma SPEC (ou uma manutenção) que meça e acrescente o `tmpfs` necessário, com no máximo `64m`. Nunca tirar o `read_only` direto na VPS.

## 3. Segredos e variáveis

Nenhum valor real vai para o Git (R-03). Os nomes ficam em `.env.example`. Na VPS, **não existe nenhum arquivo de ambiente editado à mão** nem checkout manual (ADR-023): as variáveis ficam no painel do Coolify, em **Environment Variables** do recurso, e o `infra/compose.yaml` só as referencia (`${NOME:?}` para as obrigatórias). No deploy, o Coolify grava um `.env` com elas no diretório do recurso na VPS. O `.dockerignore` de cada Dockerfile mantém esse arquivo fora das imagens (SPEC-039 §4.6).

Regra para os segredos no painel: **build desligado (só runtime)**, **Locked** e interpolação **Literal** (mantém o `$` como digitado). Nunca cole valores em print, log de deploy ou issue.

| Variável | Onde é definida | Quem lê |
|---|---|---|
| `PUBLIC_HOST` (`<subdominio>`, sem esquema nem barra) e os limites `API_MEM_LIMIT`, `API_CPUS`, `DASHBOARD_MEM_LIMIT`, `DASHBOARD_CPUS`, `CADDY_MEM_LIMIT`, `CADDY_CPUS`, `API_PIDS_LIMIT`, `DASHBOARD_PIDS_LIMIT`, `CADDY_PIDS_LIMIT` | Environment Variables do recurso no Coolify (os limites são opcionais e têm padrão no compose) | Compose (interpolação); o `PUBLIC_HOST` vira o `API_BASE_URL` do dashboard |
| `DATABASE_URL` (pooler do Supabase, modo transaction, porta 6543) | Environment Variables do recurso (segredo; e o painel do Render, se a reserva for ativada) | `qc-api` |
| `DATABASE_URL` (pooler em modo session, porta 5432) | `.env.migrate` local do humano, nunca no Git, na VPS, no Coolify nem no Actions | `infra/migrate.py` e o registro de dispositivos |
| `READ_API_KEY` | Environment Variables do recurso (segredo): uma única variável, que o compose entrega à API e ao dashboard | `qc-api` (valida) e `qc-dashboard` (envia) |
| `MAX_BODY_BYTES`, `LOG_LEVEL` (opcionais) | Environment Variables do recurso (padrões `262144` e `INFO` no compose) | `qc-api` |
| `API_BASE_URL` | Definida pelo próprio `infra/compose.yaml` como `https://${PUBLIC_HOST}`; localmente, em `.streamlit/secrets.toml` | `qc-dashboard` |
| `MODEL_METRICS_PATH` (opcional) | Environment Variables do recurso, vazia (vale o padrão `ml/models/partqc-mnv3-v1/metrics.json`, relativo a `/app`) | `qc-dashboard` |
| `DEVICE_ID`, `DEVICE_API_KEY`, `CLOUD_API_URL` (`https://<subdominio>`) | `.env` do notebook da borda | `qc-edge` |
| `SIM_DEVICE_ID`, `SIM_DEVICE_API_KEY` | `.env` local de quem roda o simulador e o smoke test (lido com `uv run --env-file`) | `scripts/simulate.py`, `scripts/smoke_test.py` |
| `KEEPALIVE_URL` (`https://<subdominio>`) | GitHub → Settings → Secrets and variables → Actions | workflow `keepalive.yml` |

Chaves de dispositivo (sempre na máquina do humano, com a URL lida do `.env.migrate`):

- geração: `uv run --env-file .env.migrate --package qc-api python scripts/register_device.py --device-id edge-01` (imprime a chave **uma única vez**; o banco guarda só o hash);
- rotação: `uv run --env-file .env.migrate --package qc-api python scripts/register_device.py --device-id <id> --rotate`.

Nunca passe a URL de produção na linha de comando: ela ficaria no `argv` (visível em `ps`) e no histórico do shell (SEC-04-03).

## 4. Passo a passo (primeira publicação pelo Coolify)

Ordem da SPEC-015 §4.6 (refeita para o Coolify pelo ADR-023). Todos os passos são humanos. Pré-requisito: a SPEC-039 mergeada na `main`.

**Convenções dos comandos na VPS.** O `<uuid>` é o UUID do recurso no Coolify, que aparece na URL da página do recurso no painel. Ele não entra no repositório. O Coolify roda o compose com `--project-name <uuid>` (ADR-023), por isso os contêineres do PartQC são listados com:

```bash
docker ps --filter label=com.docker.compose.project=<uuid> --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
```

Nos comandos abaixo, `<contêiner da api>`, `<contêiner do dashboard>` e `<contêiner do caddy>` são os nomes que essa listagem mostra.

### Passo 1. Supabase

1. Usar o projeto Supabase já existente (conta pessoal, sem cartão, criado em 2026-10-12). **Anotar a região** (Settings → General) e conferir a nota da reserva na §2.
2. No SQL Editor, conferir o schema corrente (CA-19, passo 1):

   ```sql
   show search_path;
   select current_schema();
   ```

   O schema corrente precisa ser `public`. Se não for, parar e registrar `SPEC_ISSUE`.
3. **Migrações**, na máquina do humano (nunca na VPS, no Coolify nem no GitHub Actions), pelo pooler em **modo session** (porta 5432) ou pela conexão direta, **nunca** pela porta 6543. O executor recusa a porta 6543 antes de conectar (código 2), porque o advisory lock de sessão se perde no modo transaction (SPEC-015 §4.7).
   1. Copiar a connection string do pooler em modo **session** (painel → Connect → "Session pooler").
   2. Criar o arquivo `.env.migrate` na raiz do checkout local **com um editor** e pôr nele uma única linha `DATABASE_URL=<URL do modo session>`. Se a senha tiver `$`, pôr a URL entre aspas simples.
   3. `chmod 600 .env.migrate` e conferir com `git status --short` que ele não aparece.
   4. `uv run --env-file .env.migrate --package qc-api python infra/migrate.py --status` → lista as pendentes e sai com 0.
   5. `uv run --env-file .env.migrate --package qc-api python infra/migrate.py` → sai com 0. Se outra execução segurar o lock, o executor desiste em 30 s (`could not acquire the migration lock within 30 s`) sem aplicar nada.
   6. Repetir o passo 4 → `0 pending`.
   7. Conferir as restrições da migração `002` (CA-19, passo 6), que devem ser as da tabela da SPEC-027 §4.1. Se uma restrição com o mesmo nome tiver outra definição, parar e registrar `SPEC_ISSUE`:

      ```sql
      select conname, pg_get_constraintdef(oid) from pg_constraint
      where conrelid = 'inspections'::regclass and conname like 'inspections\_%\_check' order by 1;
      ```

4. **RLS e grants** (CA-14), no SQL Editor:

   ```sql
   select relname, relrowsecurity, relforcerowsecurity from pg_class
   where relname in ('devices','inspections','schema_migrations');
   -- esperado: 3 linhas, relrowsecurity = true e relforcerowsecurity = false

   select count(*) from pg_policies
   where tablename in ('devices','inspections','schema_migrations');
   -- esperado: 0

   select grantee, table_name, privilege_type from information_schema.role_table_grants
   where table_schema = 'public' and grantee in ('anon','authenticated');
   -- esperado: nenhuma linha
   ```

   Se a última consulta devolver linhas, rodar `revoke all on devices, inspections, schema_migrations from anon, authenticated;` e repeti-la (SEC-02 da SPEC-003). Depois, chamar a API REST do Supabase em `/rest/v1/inspections` com a chave anon (painel → API) e conferir que nenhuma linha volta, mesmo com dados na tabela.
5. Copiar a connection string do pooler em modo **transaction** (porta 6543) para a variável `DATABASE_URL` do recurso no Coolify (passo 5). A API conecta com `prepare_threshold=None` (ADR-006).

### Passo 2. Conferência da VPS e do Coolify

1. Versões: a do Coolify (rodapé do painel ou Settings), `docker version`, `docker compose version` (precisa ser v2) e `docker buildx version`.
2. Recursos: `free -h`, `nproc` e `df -h /`.
3. Proxy: `docker ps --filter name=coolify-proxy --format '{{.Image}} {{.Ports}}'` mostra uma imagem `traefik` com as portas 80 e 443 (CA-14 da SPEC-039). Anotar, num arquivo **fora** do repositório, a saída de `docker inspect -f '{{.State.StartedAt}}' coolify-proxy`, para o CA-40.
4. Firewall: `sudo ufw status verbose > ~/ufw-antes-partqc.txt`, um arquivo **fora** do repositório.
5. Registrar os valores na tabela "Conferência da VPS" da §2, sem IP nem nome de host.

### Passo 3. DNS

1. No provedor de DNS do humano, criar um registro `A` de `<subdominio>` para o IPv4 da VPS (o mesmo IP que já atende o portfólio).
2. Criar `AAAA` **só** se o humano confirmar que o proxy do Coolify atende em IPv6.
3. Esperar `dig +short <subdominio> A` devolver o IP antes do passo 7, porque o Traefik só obtém o certificado com o DNS apontando para a VPS.

### Passo 4. Recurso no Coolify

1. No painel: o projeto escolhido → **+ New** → **Public Repository**.
2. URL: `https://github.com/CarlosZeyy/Projeto_IoT.git` (repositório público, nenhuma credencial) → **Check Repository** → branch `main`.
3. Build pack: **Docker Compose**. **Base Directory**: `/infra`. **Docker Compose Location**: `/compose.yaml`. Com isso, o Coolify roda o compose com o diretório do projeto em `infra/`, como na execução local, e o `context: ..` dos três serviços aponta para a raiz do repositório.
4. Em Advanced:
   - o modo de deploy do compose fica no padrão (nunca Raw: nele, o Coolify não gera as rotas do proxy);
   - **Connect to predefined network**: desligado;
   - **Preserve repository during deployment**: desligado (nenhum arquivo do repositório é montado; o Caddyfile vai dentro da imagem);
   - deploy automático por webhook: não configurar (ADR-023, decisão 5).
5. Não clicar em Deploy ainda.

### Passo 5. Variáveis do recurso

1. Gerar a `READ_API_KEY` com `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. Nunca reaproveitar uma chave de dispositivo.
2. Em **Environment Variables** do recurso, o Coolify já lista as variáveis que o compose referencia. Preencher:
   - `PUBLIC_HOST`: o subdomínio real, sem `https://` e sem barra;
   - `DATABASE_URL`: a URL do pooler em modo transaction (passo 1, item 5);
   - `READ_API_KEY`: a chave do item 1;
   - opcionais: os limites (`API_MEM_LIMIT` e os demais da §3), `MAX_BODY_BYTES`, `LOG_LEVEL` e `MODEL_METRICS_PATH` (vazia). Sem valor, vale o padrão do compose.
3. Em `DATABASE_URL` e `READ_API_KEY`: build desligado (só runtime), **Locked** e **Literal**. Em `PUBLIC_HOST`, só runtime basta.
4. Ajustar os limites conforme o `free -h` e o `nproc` do passo 2 (regra na §2).
5. Não existe `API_BASE_URL` no painel: o compose a monta como `https://${PUBLIC_HOST}`.

### Passo 6. Domínio

1. Em **Domains** do recurso, escolher o serviço `caddy` e informar `https://<subdominio>:80`. O `:80` é a porta **interna** do contêiner, não uma porta pública.
2. A `api` e o `dashboard` ficam **sem** domínio.
3. Se o recurso tiver a opção "Force HTTPS", deixá-la ligada (o CA-13, passo 2, confere o redirecionamento).

### Passo 7. Deploy e conferências

1. **Deploy**. Acompanhar o log de deploy no painel até o fim. Ler o log antes de copiar qualquer trecho, e nunca colá-lo em lugar público com um valor de variável (CA-15 da SPEC-039).
2. Listar os contêineres com o comando das convenções acima: 3 contêineres `Up`, a `api` e o `dashboard` `(healthy)` (o primeiro healthcheck roda depois de até 90 s) e nenhuma porta publicada.
3. Conferir o certificado com o CA-13, passo 5, da SPEC-015.
4. CA-43, passo 1: `docker exec <contêiner da api> find /app -maxdepth 2 -name '.env*'` e o mesmo com o `<contêiner do dashboard>` → nenhuma linha, ou só `/app/.env.example`. Se aparecer outro `.env*`, parar, apagar as imagens (`docker image rm`), parar o recurso no painel e registrar `SPEC_ISSUE` (o build não respeitou o `.dockerignore` por Dockerfile).
5. CA-16 e CA-17 da SPEC-039 (endurecimento preservado e segredos).

### Passo 8. Dispositivos

Na máquina do humano (não na VPS), com o `.env.migrate` do passo 1:

- `uv run --env-file .env.migrate --package qc-api python scripts/register_device.py --device-id edge-01`
- `uv run --env-file .env.migrate --package qc-api python scripts/register_device.py --device-id sim-01`

As chaves vão para os `.env` locais (`DEVICE_API_KEY` da borda e `SIM_DEVICE_API_KEY` do simulador).

### Passo 9. Borda

No `.env` do notebook: `CLOUD_API_URL=https://<subdominio>`.

### Passo 10. Keep-alive (GitHub)

1. O keep-alive principal é o healthcheck da API, definido no Dockerfile e mantido pelo Coolify: a cada 60 s, `GET /api/v1/health` faz `SELECT 1` no Supabase. Com o banco pausado ou fora do ar, o contêiner fica `unhealthy`, mas continua rodando (o Docker não reinicia por healthcheck). A API não tem domínio no Coolify, então o estado dela não tira o site da rota; o Caddy não tem healthcheck pelo mesmo motivo (ADR-023).
2. O workflow `.github/workflows/keepalive.yml` é a verificação externa, a cada 3 dias (`17 9 */3 * *`). Ele imprime só o código de saída do `curl`, para que um erro não leve o nome do host ao log público do Actions.
3. Em Settings → Secrets and variables → Actions, criar o secret `KEEPALIVE_URL=https://<subdominio>`.
4. Em Actions → keepalive → "Run workflow", disparar o workflow (CA-16): o job termina verde em ≤ 10 min, e o próximo agendamento aparece na aba Actions.
5. Num repositório público, workflows agendados são desligados depois de 60 dias sem atividade (§2): se isso acontecer, reativar na aba Actions. O healthcheck da API continua cobrindo a pausa do Supabase.

### Passo 11. Smoke test

1. Num shell local, criar com um editor um arquivo de ambiente ignorado pelo Git (por exemplo, `.env.prod`, coberto pelo padrão `.env.*`) com `CLOUD_API_URL=https://<subdominio>`, `DASHBOARD_URL=https://<subdominio>/`, `READ_API_KEY`, `SIM_DEVICE_ID=sim-01` e `SIM_DEVICE_API_KEY`.
2. `uv run --env-file .env.prod --package qc-api python scripts/smoke_test.py`: as 8 checagens dão `PASS` (CA-15). A saída não tem chaves nem o host e pode ser colada no dev-report.
3. `uv run --env-file .env.prod --package qc-api python scripts/simulate.py --lots 3`, contra a API de produção, sempre dentro dos limites da §8, item 4.
4. Ver os dados no dashboard com o selo "Contém dados simulados" (origem `Todos`).
5. Os dados simulados ficam (filtráveis por `source`; o dashboard mostra o selo). Se for preciso apagá-los: `delete from inspections where source = 'simulated';` no SQL Editor, pelo humano.

### Passo 12. Banco: `statement_timeout`

Seguir a §8, item 1 (CA-26).

### Passo 13. CAs manuais

Executar os CAs manuais da SPEC-039 (CA-14 a CA-17), da SPEC-015 (CA-13 a CA-19, CA-26, CA-40, CA-42 e CA-43) e o CA-09 da SPEC-032, e registrar o resultado na §9 e no dev-report, sem o subdomínio real, o IP nem o UUID do recurso.

### Conferência local da composição (opcional, na máquina da dupla)

Antes de um deploy que mude `infra/`, a dupla pode conferir o mesmo compose localmente, com valores **fictícios**:

1. Criar com um editor um `infra/.env` local (ignorado pelo Git e pelo contexto de build) com a variável `PUBLIC_HOST` igual a um nome de teste (por exemplo, `partqc.example.org`), uma `DATABASE_URL` fictícia e uma `READ_API_KEY` gerada na hora, e rodar `chmod 600 infra/.env`.
2. `docker compose -f infra/compose.yaml config --quiet` → código 0. Nunca rode o subcomando de configuração do compose sem `--quiet` num terminal compartilhado ou gravado: sem a opção, ele imprime os valores das variáveis.
3. `docker compose -f infra/compose.yaml up -d --build`, conferir os 3 contêineres com `docker compose -f infra/compose.yaml ps` e depois `docker compose -f infra/compose.yaml down`. Nunca `docker compose down -v`. Sem portas publicadas, nada fica exposto no notebook.

### Firewall da VPS e coexistência com os outros projetos (SPEC-015 §4.15, ADR-023)

- O PartQC não publica nenhuma porta: as portas 80 e 443 já são do proxy do Coolify, que também publica o portfólio. Nenhuma regra nova de `ufw` é necessária.
- Nunca reinicie, pare nem edite o `coolify-proxy` (nem a configuração do proxy no painel) por causa do PartQC: o portfólio depende dele.
- Nunca mude as configurações do servidor no Coolify (Servers) por causa do PartQC.
- Nunca rode `ufw reset`, `ufw default ...`, `ufw delete ...` ou `ufw --force ...`.
- Nunca ative nem desative o `ufw` por causa do projeto.
- Nunca rode `iptables -F`, `iptables -X` ou `nft flush`.
- Nunca edite o `/etc/docker/daemon.json` nem reinicie o Docker por causa do projeto.
- Nunca rode `docker system prune`, `docker volume prune` ou `docker network prune`: todos afetam os outros projetos e o próprio Coolify.
- **Depois do deploy** (CA-40):
  1. a listagem das convenções mostra os 3 contêineres sem nenhuma porta publicada (`0.0.0.0:` ou `[::]:`);
  2. `ss -tlnp` do host não tem `:8000` nem `:8501`;
  3. de outra máquina, `curl --connect-timeout 5 http://<IP>:8000/` e `curl --connect-timeout 5 http://<IP>:8501/` falham;
  4. `sudo ufw status verbose | diff ~/ufw-antes-partqc.txt -` não mostra nenhuma regra a menos (linhas com `<`);
  5. o `StartedAt` do proxy do Coolify é igual ao anotado no passo 2, item 3;
  6. cada um dos outros projetos da VPS (o portfólio, pelo menos) responde como antes.

### Atualização (SPEC-015 §4.16, ADR-023)

Depois de cada merge que afete a API, o dashboard, `infra/`, `ml/models/**/*.json` ou `ml/reports/`:

1. no painel, abrir o recurso e clicar em **Deploy** (o Coolify busca o último commit da `main`); acompanhar o log até o fim
2. conferir no painel que o deploy terminou com sucesso e que o recurso está em execução
3. listar os contêineres (convenções acima): os 3 `Up`; `api` e `dashboard` `(healthy)`
4. smoke test (passo 11, item 2)
5. na VPS, `docker image prune -f --filter label=partqc.component` (remove só as imagens órfãs do PartQC)

A imagem do dashboard leva o `metrics.json` e os PNGs de `ml/reports/` **do commit publicado**: depois do merge do primeiro `metrics.json` (SPEC-012), basta esta atualização, e "Sobre o modelo" passa a mostrar a tabela de métricas.

**Logs:** a aba de logs de cada serviço no painel, ou `docker logs --tail 200 <contêiner>`. Nunca cole logs da API, do Caddy ou do deploy em lugar público sem editá-los: com o banco fora do ar, os da API têm o host e o usuário do pooler (§7, item 2), e o log de deploy do Coolify pode citar o subdomínio. Antes de colar, troque o subdomínio por `<subdominio>`, o IP por `<IP>` e o UUID por `<uuid>` (lista completa na §9). O Caddy não registra acessos (sem a diretiva `log`), e o log de acesso do Uvicorn mostra o IP do Caddy na rede interna, e não o do cliente.

## 5. Checklist do dia da apresentação

**Na véspera:**

- [ ] Abrir o projeto Supabase (não pode estar pausado) e chamar `https://<subdominio>/api/v1/health` (deve retornar `db: ok`).
- [ ] No painel do Coolify, o recurso em execução e, na VPS, os 3 contêineres `Up`, com `api` e `dashboard` `(healthy)`. Não fazer atualização no dia.
- [ ] Carregar o `model.onnx` congelado no notebook e conferir que o `sha256` bate com o `metrics.json`.
- [ ] Conferir as baterias e o carregador do celular e do notebook.
- [ ] Gravar o vídeo de backup da demo (S7) e deixá-lo offline no notebook.
- [ ] Ter à mão o roteiro da reserva (§6), com o `infra/render.yaml` e a `.streamlit/secrets.toml` local prontos.

**30 min antes:**

- [ ] Chamar `/api/v1/health` e abrir o dashboard em `https://<subdominio>/` pelo celular, pelos dados móveis.
- [ ] Ligar a borda (`uv run --env-file .env --package qc-edge qc-edge`), abrir o console e ler o QR com o celular.
- [ ] Rede: usar por padrão a **rede própria** (notebook conectado ao hotspot do celular), ensaiada em casa; o Wi-Fi do campus só se já tiver sido testado. Se o celular não abrir `/capture`, conferir o IP do notebook na rede do hotspot e o firewall. Se ainda assim falhar, usar a ancoragem USB (plano C). Túnel público é proibido (R-02). Último recurso: o vídeo de backup.
- [ ] Liberar a porta 8000 no firewall do notebook.
- [ ] Fundo A4, luminária e peças separadas por lote (incluindo uma `unusable` e um objeto `other` para mostrar o "desconhecido").

**Durante:**

- [ ] Mostrar o modo offline: desligar o Wi-Fi do notebook, inspecionar 3 peças, religar e ver o outbox esvaziar.

## 6. Rollback e reserva

- **Rollback da API e do dashboard (por branch temporária, ADR-023):** o rollback do painel usa imagens antigas e não está documentado para Compose, por isso o caminho é publicar um commit anterior por uma branch.
  1. na máquina do humano, `git log --oneline -10` e escolher o `<sha anterior>`;
  2. `git push origin <sha anterior>:refs/heads/deploy/rollback` (com a conta CarlosZeyy);
  3. no recurso do Coolify, trocar a branch para `deploy/rollback` e clicar em **Deploy**;
  4. com a correção mergeada na `main`, trocar a branch do recurso de volta para `main`, clicar em **Deploy** e apagar a branch (`git push origin --delete deploy/rollback`).

  As migrações são só aditivas no MVP: um rollback não desfaz migração.
- **Parar:** o botão **Stop** do recurso no painel. Nunca apague o recurso nem rode `docker compose down -v` nos contêineres do PartQC. O Caddy não guarda mais certificados, mas apagar o recurso perde as variáveis do painel.
- **Modelo:** trocar `MODEL_DIR` para a versão anterior. O `model_version` de cada inspeção permite filtrar.
- **Reserva fria** (VPS ou Coolify fora do ar por mais de 24 h, ou no dia da demo; SPEC-015 §4.16, item 5):
  1. no Render (conta pessoal, sem cartão), "New → Blueprint" com `infra/render.yaml`; na criação, preencher `DATABASE_URL` (pooler em modo transaction) e `READ_API_KEY` (os dois com `sync: false`);
  2. na borda, `CLOUD_API_URL=https://<servico>.onrender.com`;
  3. rodar o dashboard no notebook com `.streamlit/secrets.toml` apontando para essa URL (SPEC-028 §4.6);
  4. o secret `KEEPALIVE_URL` passa a ser `https://<servico>.onrender.com` enquanto a reserva estiver em uso;
  5. registrar aqui o uso e a data;
  6. ao voltar para a VPS, desfazer os passos 2 a 4 e suspender o serviço do Render.

  Se o log do Render mostrar instalação de dependências no start (o `uv run` inclui o grupo `dev` por padrão), registrar `SPEC_ISSUE` (SPEC-015 §7).

Registro de uso da reserva:

| Data | Motivo | Desativada em |
|---|---|---|
| — | — | — |

## 7. Riscos aceitos

Cada linha tem a fonte e a data da verificação. Os riscos são do MVP (projeto acadêmico, URL não divulgada) e podem ser revistos por SPEC nova, se o humano pedir.

1. **Rajada anônima ocupando o pool (SEC-04-02).** Toda requisição anônima com chave não vazia de até 256 caracteres, e todo `GET /health`, ocupa uma conexão do pool (máximo de 5, espera de 5 s), e enquanto a rajada dura os dispositivos recebem 503.
   - **Efeito:** não há perda de dados: o outbox da borda reenvia com backoff (SPEC-009).
   - **Na VPS:** não há proteção de provedor contra DDoS, e nem o Caddy padrão nem o proxy do Coolify, como configurado, limitam a taxa: no Caddy, `rate_limit` não está na lista de diretivas padrão e exigiria um build próprio com plugin (<https://caddyserver.com/docs/caddyfile/directives>, conferido em 2026-10-19). O impacto nos outros projetos da VPS fica limitado pelo `mem_limit` e pelos `cpus` de cada serviço (`infra/compose.yaml`).
   - **Na reserva (Render):** vale a proteção automática do Render (<https://render.com/docs/ddos-protection>, conferido em 2026-10-19).
   - **Decisão:** risco aceito no MVP. Uma limitação de taxa só entra por SPEC nova.
2. **Log do `psycopg.pool` (SEC-04-05).** Com o banco fora do ar, o logger `psycopg.pool` registra em `WARNING` o host, a porta e, numa falha de autenticação, o usuário do pooler do Supabase, sem a senha. Esse log fica na aba de logs da API no painel do Coolify (e em `docker logs`), que só o humano acessa, e no painel do Render quando a reserva está ativa. Não são segredos (R-03 cumprida). No portão `deploy`, esse log não conta como vazamento: é a exceção da regra "Erros de banco no log" de `docs/architecture.md` §4 (SPEC-004, r2-security-report, 2026-10-13).
3. **Consulta cancelada pelo `statement_timeout`:** uma consulta que passa do limite é cancelada com o código `57014` (`QueryCanceled`) e responde 503 `{"detail": "Database unavailable"}`, igual a um banco fora do ar, sem a mensagem do Postgres nem stack trace (SEC-26-02, SPEC-026 r1-security-report; <https://supabase.com/docs/guides/database/postgres/timeouts>, conferido em 2026-10-19).
   - O `QueryCanceled` é subclasse de `psycopg.OperationalError`, que o `db_connection` (`api/src/qc_api/db.py`) converte em `DatabaseUnavailableError`.
   - O dashboard mostra o aviso de API indisponível e não repete a chamada em laço (SPEC-013).
   - As migrações rodam com o mesmo papel: se uma migração futura passar do limite, ela falha e faz `rollback`, e o humano a repete com o limite ajustado só naquela sessão (`set statement_timeout = '60s';` pela conexão do `.env.migrate`, em modo session).
4. **Subdomínio nos logs de Certificate Transparency.** O Let's Encrypt envia todo certificado emitido (agora pelo proxy do Coolify) aos logs de CT (<https://letsencrypt.org/docs/ct-logs/>, conferido em 2026-10-19), e o nome do subdomínio fica descobrível. A R-13 exige manter o nome fora do repositório, e não escondê-lo do mundo.
5. **VPS e proxy do Coolify como ponto único de falha, compartilhados com outros projetos.** Mitigação: outbox na borda (RNF-10), limites de memória e CPU por serviço e a reserva fria no Render (§6). O Caddy sobe mesmo com o Supabase pausado (sem `condition: service_healthy`), e um contêiner `unhealthy` não é reiniciado. Uma atualização do Coolify pode mudar o comportamento do recurso: depois de atualizar o Coolify, repetir o smoke (passo 11) e o CA-16 da SPEC-039.
6. **Limite de emissão de certificados.** "Up to 5 certificates can be issued per exact same set of identifiers every 7 days" (<https://letsencrypt.org/docs/rate-limits/>, conferido em 2026-10-19). O certificado agora fica no proxy do Coolify. Trocar o domínio do recurso várias vezes, ou apagar e recriar o recurso repetidamente, força emissões novas. Nunca usar `docker compose down -v` nos contêineres do PartQC.
7. **Segredos no disco da VPS, gravados pelo Coolify (ADR-023).** No deploy, o Coolify grava as variáveis de runtime num `.env` no diretório do recurso, além de guardá-las no banco dele. Modo e dono do arquivo, conferidos no CA-17 da SPEC-039: a preencher. A VPS é de um único usuário (o humano). O arquivo fica fora das imagens pelo `.dockerignore` de cada Dockerfile (CA-13 da SPEC-039). Não altere a permissão à mão: o Coolify reescreve o arquivo a cada deploy. (Até a SPEC-039, este item tratava do aviso do HTTP/3 sem `NET_ADMIN`, que deixou de existir, porque o Caddy não publica mais 443/udp.)
8. **Contêiner só de leitura e com limite de processos (SPEC-032 §4.4).** Uma atualização de dependência que passe a escrever em disco fora de `/tmp`, ou que crie muito mais threads, pode derrubar o serviço depois do deploy. Mitigação: as medições da §2 (pico de 15, 51 e 11 PIDs para um limite de 256), o smoke da atualização (§4, "Atualização", item 4), o diagnóstico pelo log (`Read-only file system`, `can't start new thread`) e o rollback da §6.
9. **Respostas que não passam pelo bloco de headers do Caddy (SPEC-032 §4.3).** O bloco `header` do site é adiado (`defer`) e só age nas respostas que passam pelo `reverse_proxy`. Conferido com a imagem `caddy:2.11.7` em 2026-10-24: o `502` que o Caddy devolve quando a API ou o dashboard estão fora do ar sai com `Server: Caddy` e sem os 4 headers do bloco (a SPEC-038 cobre isso com `handle_errors`). Com o Coolify (ADR-023), também saem sem os nossos headers o redirecionamento HTTP → HTTPS, feito pelo proxy do Coolify (o navegador ignora HSTS em HTTP), e os erros gerados pelo próprio proxy, como o `404`/`No available server` com o contêiner do Caddy parado. As respostas da API e do Streamlit por HTTPS saem sem `server` e sem `via`. Nenhuma dessas respostas tem conteúdo que possa ser emoldurado. **Decisão:** risco aceito no MVP. Uma política CSP completa também ficou fora (SPEC-032 §3.2).

## 8. Operação do banco e das chaves (SPEC-015 §4.9)

### 1. `statement_timeout` (SEC-05-01, SEC-26-03; CA-26)

O `statement_timeout` do papel da API é o **teto do custo de banco** da carta p e das demais leituras: sem ele, o papel `postgres` fica só com o teto global de 2 min do Supabase ("postgres: none (capped by default global timeout to be 2min)", <https://supabase.com/docs/guides/database/postgres/timeouts>, conferido em 2026-10-19), e leituras pesadas do dashboard podem ocupar as 5 conexões do pool. A memória da API já é limitada pelo corte da carta do ADR-017 (SPEC-026).

1. **Medir**, depois das migrações e do `simulate.py` do passo 11 (com `--env-file`), no SQL Editor. As duas consultas abaixo são as da API com os parâmetros padrão das rotas, geradas a partir de `qc_api.repositories.inspections` em 2026-10-19 (se a consulta do código mudar, gere de novo):

   Agregação de `GET /api/v1/lots` (sem filtros, `limit=50`):

   ```sql
   explain analyze
   select
       lot_id,
       count(*) as n,
       count(*) filter (where is_defective) as defects,
       count(*) filter (where object_type = 'unknown') as unknown_count,
       min(inspected_at) as started_at,
       max(inspected_at) as ended_at,
       array_agg(distinct source) as sources
   from inspections
   where true
   group by lot_id
   order by started_at desc, lot_id asc
   limit 50 offset 0;
   ```

   `SELECT_LOT_SELECTION` da carta p (`source=live`, sem `object_type`, `baseline_lots=20`, `min_lot_size=5`, `max_points=100`, `max_excluded=50`):

   ```sql
   explain analyze
   with lots as materialized (
       select lot_id, count(*) as n, count(*) filter (where is_defective) as defects,
              min(inspected_at) as started_at, max(inspected_at) as ended_at
       from inspections
       where object_type <> 'unknown' and source = 'live'
       group by lot_id
   )
   select part, lot_id, n, defects, started_at, ended_at, valid_lots_total, excluded_lots_total
   from (
       select 'totals'::text as part, null::text as lot_id, null::bigint as n,
              null::bigint as defects, null::timestamptz as started_at,
              null::timestamptz as ended_at,
              count(*) filter (where n >= 5) as valid_lots_total,
              count(*) filter (where n < 5) as excluded_lots_total
       from lots
       union all
       (select 'baseline', lot_id, n, defects, started_at, ended_at, null, null
        from lots where n >= 5 order by started_at, lot_id collate "C" limit 20)
       union all
       (select 'window', lot_id, n, defects, started_at, ended_at, null, null
        from lots where n >= 5 order by started_at desc, lot_id collate "C" desc limit 100)
       union all
       (select 'excluded', lot_id, n, defects, started_at, ended_at, null, null
        from lots where n < 5 order by started_at desc, lot_id collate "C" desc limit 50)
   ) as parts
   order by part, started_at, lot_id collate "C";
   ```

   Com só dados simulados no banco, a carta com `source = 'live'` lê poucas linhas. Opcionalmente, repetir trocando `source = 'live'` por `source = 'simulated'` e anotar os dois tempos.
2. **Escolher o valor:** `15s`. Só se 3 vezes a leitura mais lenta medida passar de 15 s, usar esse valor, até `30s`. (Com poucos lotes em produção, 3 vezes a medida seria um limite de milissegundos que cortaria a carta de uma história realista: no Postgres local, a carta levou 2,9 s com 200 000 lotes e de 4,2 a 5,3 s com 1 M, no test-report da SPEC-026.)
3. **Aplicar** no papel da API (o usuário da `DATABASE_URL` sem o sufixo do projeto; no Supabase, `postgres`), no SQL Editor: `alter role postgres set statement_timeout = '15s';`. É `alter role`, e não o parâmetro `options` da conexão, porque uma configuração de sessão não funciona pelo pooler em modo transaction (porta 6543).
4. **Conferir no papel:** `select rolname, rolconfig from pg_roles where rolname = 'postgres';` → `rolconfig` contém `statement_timeout=15s` (`show statement_timeout` no SQL Editor não reflete a configuração do papel).
5. **Conferir pelo caminho da API** (pooler em modo transaction, porta 6543), com a URL lida de um arquivo local ignorado pelo Git, nunca na linha de comando. Use um arquivo **próprio e temporário**, só para esta conferência, e não o `.env.prod` do passo 11: o smoke e o simulador não precisam da senha do banco, e ela não deve ficar num arquivo de uso geral nem no ambiente desses processos.
   1. Criar com um editor o arquivo `.env.dbcheck` (coberto pelo padrão `.env.*` do `.gitignore`) com uma única linha `DATABASE_URL=<URL do modo transaction>` (entre aspas simples se tiver `$`) e rodar `chmod 600 .env.dbcheck`.
   2. Rodar:

      ```bash
      uv run --env-file .env.dbcheck --package qc-api python -c "import os, psycopg; c = psycopg.connect(os.environ['DATABASE_URL'], prepare_threshold=None); print(c.execute('show statement_timeout').fetchone()[0])"
      ```

   3. Apagar o arquivo logo depois: `rm .env.dbcheck`.

   Saída esperada: `15s`. Se a conexão falhar, não cole a mensagem de erro sem editá-la: ela pode trazer o host do pooler. Se não for, parar e registrar `SPEC_ISSUE` para o architect (a alternativa é um `set local statement_timeout` na transação de leitura da API, numa SPEC do developer).
6. Registrar na §9 e no dev-report as saídas dos itens 1, 4 e 5 e a data.

### 2. `READ_API_KEY` (INFO-02 da SPEC-005)

- **Geração:** só com `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`, nunca reaproveitando uma chave de dispositivo.
- **Troca:**
  1. gerar a nova chave;
  2. no painel do Coolify, atualizar a variável `READ_API_KEY` do recurso (uma só, entregue à API e ao dashboard) e fazer **Redeploy** (ou **Restart**, que basta para variáveis só de runtime). Durante a recriação, o painel fica indisponível por alguns segundos;
  3. se a reserva no Render estiver ativa, atualizar a variável no painel dele na mesma sessão;
  4. conferir com o smoke test do passo 11 (checagens `read_requires_key` e `read`), que lê a chave do ambiente. Nunca conferir com `curl -H "X-API-Key: ..."`, que deixa a chave no `argv`.

### 3. Limites da reserva (Render)

512 MB de RAM e 0,1 CPU no plano `free` (linha do Render na §2, <https://render.com/docs/compute-plans>, conferido em 2026-10-19). Na VPS, o `mem_limit` padrão da API é o mesmo (`512m`), o envelope do ADR-017.

### 4. Simulador em produção (SEC-07 e SEC-01 da SPEC-014)

- Contra produção, só execuções pequenas: `--lots` até 10 e `--lot-size` até 50 (no máximo 500 itens por execução), por exemplo `uv run --env-file .env.prod --package qc-api python scripts/simulate.py --lots 3`.
- A chave vai sempre pelo arquivo de ambiente (`SIM_DEVICE_API_KEY`). Nunca use `--api-key` em demo gravada, terminal projetado, CI ou workflow. Se for inevitável, use a forma `--api-key=<valor>` com um espaço no início do comando, para que ele não entre no histórico do shell.
- Se uma chave aparecer numa gravação, num log compartilhado ou num print, rotacioná-la com `uv run --env-file .env.migrate --package qc-api python scripts/register_device.py --device-id sim-01 --rotate` e atualizar o `.env` local.

## 9. Registro dos CAs manuais (SPECs 015, 032 e 039)

Preenchido pelo humano (e copiado no dev-report), sem o subdomínio real, o IP nem o UUID do recurso. Os comandos estão na SPEC-015 §5, na SPEC-032 §5 (com a equivalência da SPEC-039 §4.7) e na SPEC-039 §5.

**Antes de colar qualquer saída** aqui, no dev-report ou no PR (todos públicos), troque o subdomínio real por `<subdominio>`, o IP por `<IP>` e o UUID do recurso por `<uuid>` (R-13). Estas saídas os trazem:

- o `%{redirect_url}` (ou o `Location`) do CA-13, item 2 (`https://` seguido do subdomínio real);
- o `openssl s_client` do CA-13, item 5, se a saída não for filtrada pelo `openssl x509 -noout -issuer -enddate` (o `subject` e o SAN têm o subdomínio);
- o `printenv API_BASE_URL` do CA-17, item 6 (`https://` seguido do subdomínio real; basta registrar "começa com `https://`");
- a URL `wss://` do CA-17, item 2, nas ferramentas do navegador;
- o `dig +short <subdominio> A` do passo 3 da §4 (o IP);
- o `curl http://<IP>:8000/` e o `curl http://<IP>:8501/` do CA-40, item 3 (a mensagem de erro do `curl` repete o IP);
- os nomes dos contêineres e as saídas com o seletor `com.docker.compose.project=...` (o UUID do recurso);
- o log de deploy do Coolify e os logs do Caddy (podem citar o subdomínio);
- os logs da API com o banco fora do ar (host e usuário do pooler, §7, item 2);
- a mensagem de erro de uma conexão que falhe no item 5 da §8 (host do pooler).

O smoke test (`scripts/smoke_test.py`), o `--status` do `infra/migrate.py` e as consultas SQL dos CAs 14, 19 e 26 não trazem o host nem o IP e podem ser colados como saem. Depois de colar, o CA-42 confere o repositório inteiro.

**Comando do CA-42**, na máquina do humano, a partir da raiz de um checkout local atualizado (antes, `git pull --ff-only`, para que os relatórios em `reviews/` estejam presentes). Ele lê o subdomínio e o IPv4 sem deixá-los no histórico do shell e tira as aspas e os espaços, que o `git grep -F` procuraria literalmente:

```bash
read -r -p "Subdomínio (sem https://): " h; h=$(printf '%s' "$h" | tr -d "\"' \r")
if [ -n "$h" ]; then git grep -nF -e "$h"; else echo "subdomínio vazio"; fi
read -r -p "IPv4 público da VPS: " ip; ip=$(printf '%s' "$ip" | tr -d "\"' \r")
if [ -n "$ip" ]; then git grep -nF -e "$ip"; else echo "IPv4 vazio"; fi
read -r -p "UUID do recurso no Coolify: " u; u=$(printf '%s' "$u" | tr -d "\"' \r")
if [ -n "$u" ]; then git grep -nF -e "$u"; else echo "UUID vazio"; fi
unset h ip u
```

Esperado: nenhuma linha nos três `git grep` (código de saída 1) e nenhum aviso de valor vazio. O teste de valor vazio evita rodar o `git grep` com um padrão vazio, que casaria todas as linhas.

| CA | O que | Resultado | Data |
|---|---|---|---|
| SPEC-039 CA-14 | Antes do primeiro deploy: versão do Coolify, `coolify-proxy` com imagem `traefik` nas portas 80/443, `StartedAt` anotado fora do repositório | pendente | — |
| SPEC-039 CA-15 | Recurso (Public Repository, Docker Compose, `/infra`, `/compose.yaml`, modo de deploy não Raw, sem rede predefinida, sem Preserve repository, sem webhook), domínio só no `caddy`, deploy com sucesso, 3 contêineres sem portas | pendente | — |
| SPEC-039 CA-16 | `docker inspect`: limites, `read_only`, `tmpfs`, capacidades, `no-new-privileges`, sem `PortBindings`, `unless-stopped` | pendente | — |
| SPEC-039 CA-17 | Segredos só em runtime, Locked e Literal; `docker history` sem os nomes; `.env*` fora das imagens; modo do `.env` do Coolify (§7, item 7) | pendente | — |
| CA-13 | API na VPS: health, redirecionamento HTTP → HTTPS, 401 sem chave, HSTS sem `includeSubDomains`, emissor do certificado, `/docs` e `/openapi.json` não publicados | pendente | — |
| CA-14 | RLS e grants em produção (passo 1, item 4) | pendente | — |
| CA-15 | Smoke em produção: 8 × `PASS` (passo 11) | pendente | — |
| CA-16 | Keep-alive por `workflow_dispatch` verde em ≤ 10 min (passo 10) | pendente | — |
| CA-17 | Dashboard na VPS: desktop e celular, WebSocket `wss://<subdominio>/_stcore/stream` com 101 por 5 min, filtros, selo de simulado, "Sobre o modelo" (mensagem com `ml/models/partqc-mnv3-v1/metrics.json` enquanto não houver `metrics.json`; repetir depois do merge do primeiro `metrics.json` da SPEC-012 e da atualização da §4), `printenv API_BASE_URL` começa com `https://` | pendente | — |
| CA-18 | R-01: Supabase e GitHub Actions sem cartão; VPS preexistente e sem mudança de plano (confirmação escrita do humano); Coolify auto-hospedado, sem plano pago; domínio já existente; Render sem cartão e serviço `free` se ativado | pendente | — |
| CA-19 | `search_path`, migração pelo modo session e restrições da `002` (passo 1, itens 2 e 3) | pendente | — |
| CA-26 | `statement_timeout` (§8, item 1) | pendente | — |
| CA-40 | Rede e coexistência na VPS (§4, "Firewall"), com o proxy do Coolify sem reinício | pendente | — |
| CA-42 | Na máquina do humano, o comando do CA-42 acima: nenhuma linha com o subdomínio, o IPv4 público ou o UUID do recurso | pendente | — |
| CA-43 | `.env*` fora das imagens (passo 7, item 4); ciclo de atualização, rollback por branch e volta à `main` com health 200; certificado sem nova emissão no ciclo | pendente | — |

### CA manual da SPEC-032 (headers e endurecimento)

Depois da atualização da §4 ("Atualização") com a SPEC-032 e a SPEC-039 na `main`, na VPS e no navegador. Os comandos seguem a equivalência da SPEC-039 §4.7. Antes de colar, troque o subdomínio por `<subdominio>` e o UUID por `<uuid>` (a saída do `curl -sI` não tem o host, mas a barra de endereço do navegador e as ferramentas de desenvolvedor têm).

1. `docker ps --filter label=com.docker.compose.project=<uuid> --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'`: os 3 contêineres `Up`, `api` e `dashboard` `(healthy)` e nenhuma porta publicada.
2. `curl -sI https://<subdominio>/api/v1/health`: tem `referrer-policy: no-referrer` e `content-security-policy: frame-ancestors 'self'` (além de `strict-transport-security` e `x-content-type-options`), e **não** tem `server:` nem `via:`.
3. Repetir os passos 1 a 3 do CA-17 da SPEC-015: painel no desktop e no celular, `wss://<subdominio>/_stcore/stream` com 101 aberto por 5 min, filtro atualizando os gráficos. Se algum componente do painel quebrar por causa do `frame-ancestors`, parar e registrar `SPEC_ISSUE`.
4. Com 3 abas do painel abertas, `docker stats --no-stream $(docker ps -q --filter label=com.docker.compose.project=<uuid>)`: a coluna `PIDS` de cada serviço fica em no máximo metade do `pids_limit` (128, com o padrão).
5. Complementar (não faz parte do texto do CA-09): para cada contêiner, `docker logs --tail 200 <contêiner> 2>&1 | grep -ciE 'read-only file system|erofs'` → `0`.
6. Registrar as saídas na tabela abaixo e no dev-report, com o subdomínio trocado por `<subdominio>` (SEC-15-01).

| CA | O que | Resultado | Data |
|---|---|---|---|
| SPEC-032 CA-09 | Serviços de pé com `read_only` e `pids_limit`; headers novos e sem `server`/`via`; painel de ponta a ponta (CA-17, passos 1 a 3, da SPEC-015); `PIDS` ≤ metade do limite; nenhum `Read-only file system` no log | pendente | — |
