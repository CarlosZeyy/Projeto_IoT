# Plano de deploy

Este documento é de responsabilidade do agente `security-devops` (SPEC-015). Ele segue o ADR-018: API e dashboard na VPS pessoal, com Docker Compose e Caddy; banco no Supabase; Render como reserva fria da API. A estrutura foi reescrita pelo architect em 2026-10-18, e os comandos exatos, os valores finais e as datas de verificação foram completados pelo autor da SPEC-015 em 2026-10-19.

Os limites de free tier e as versões mudam com frequência: **confira de novo antes de cada decisão** e atualize a coluna "Verificado em". O subdomínio real e o IP da VPS **nunca** entram neste arquivo nem em nenhum outro do repositório (R-13): use `<subdominio>` e `<IP>`.

Os agentes não têm acesso à VPS, ao Supabase, ao DNS nem às contas. Tudo o que está na §4 e na §9 é **passo humano**.

## 1. Ambientes

| Ambiente | Onde | Para quê |
|---|---|---|
| `local` | Notebook da equipe | Desenvolvimento e testes: a API local aponta para um **Postgres local em Docker** (o mesmo dos testes, `TEST_DATABASE_URL`) |
| `edge` | Notebook da demo | Gateway de borda na LAN (`qc-edge`) |
| `cloud` | VPS pessoal (Docker Compose: Caddy, `qc-api`, `qc-dashboard`) e Supabase | API e dashboard públicos em `https://<subdominio>` (dados protegidos por chave) |
| `cloud` (reserva) | Render (Web Service free) | Só a API, publicada num incidente (§6) |

**Um único projeto Supabase** (o que a dupla já criou para este trabalho) é o banco de produção (`cloud`). O desenvolvimento e os testes usam o Postgres local em Docker, então os dados de teste nunca chegam ao Supabase. Confirme que o projeto está numa conta **pessoal** (R-13).

Rotas públicas em `https://<subdominio>` (`infra/Caddyfile`): `/api/*` vai para a API; todo o resto (inclusive o WebSocket `/_stcore/stream`) vai para o Streamlit. `/docs` e `/openapi.json` da API **não** são publicados (ADR-018, decisão 4).

## 2. Serviços e limites

| Serviço | Uso | Limites relevantes | Fonte | Verificado em |
|---|---|---|---|---|
| VPS pessoal do humano | `caddy`, `qc-api`, `qc-dashboard` (`infra/compose.yaml`) | Recurso pessoal **preexistente**, pago a cada 2 anos, sem custo adicional para o projeto (R-01, ADR-018). Docker e Compose v2 instalados; portas 80/443 livres. Versões, RAM, CPUs e disco: preencher no passo 2 da §4 (tabela "Conferência da VPS" logo abaixo) | Declaração do humano (ADR-018) | 2026-10-18 (a completar pelo humano no passo 2) |
| Imagens base | `python:3.12.15-slim-trixie` (API e dashboard), `ghcr.io/astral-sh/uv:0.13.2` (cópia do binário `uv` no build), `caddy:2.11.7`, todas fixadas também pelo digest `@sha256:` do índice multi-arquitetura | Software livre; nenhuma conta. Atualizar: conferir a tag nova na fonte, trocar a tag e o digest (`docker buildx imagetools inspect <imagem>:<tag>`) e abrir PR | <https://hub.docker.com/_/python>, <https://docs.astral.sh/uv/guides/integration/docker/>, <https://hub.docker.com/_/caddy> | 2026-10-19 |
| Supabase Free | Postgres | 500 MB de banco por projeto, 2 projetos ativos, **pausa com pouca atividade num período de 7 dias** ("a few user requests to the database each day over the previous week is enough"), 5 GB de egress | <https://supabase.com/pricing>, <https://supabase.com/docs/guides/platform/free-project-pausing> | 2026-10-19 |
| Let's Encrypt (via Caddy) | Certificado TLS de `<subdominio>` | 5 certificados por conjunto exato de nomes a cada 7 dias; todo certificado emitido vai para os logs de CT | <https://letsencrypt.org/docs/rate-limits/>, <https://letsencrypt.org/docs/ct-logs/> | 2026-10-19 |
| GitHub (repo **público** + Actions) | Código, CI (`ci` e `docker`), keep-alive, Releases para o `model.onnx` | "GitHub Actions usage is free for ... public repositories that use standard GitHub-hosted runners"; workflows agendados são desligados após 60 dias sem atividade no repositório e podem atrasar em horários de pico | <https://docs.github.com/en/billing/concepts/product-billing/github-actions>, <https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows> | 2026-10-19 |
| Render (Web Service free) — **reserva fria** | `qc-api`, só num incidente (§6) | 512 MB de RAM e 0,1 CPU (plano `free`); dorme após 15 min sem tráfego; acorda em cerca de 1 min; 750 h/mês por workspace; região `virginia` no `infra/render.yaml` (ver nota abaixo); proteção automática contra DDoS | <https://render.com/docs/compute-plans>, <https://render.com/docs/free>, <https://render.com/docs/blueprint-spec>, <https://render.com/docs/ddos-protection> | 2026-10-19 |
| Koyeb | **Não usado** (ADR-018) | — | — | 2026-10-18 |
| Streamlit Community Cloud | **Não usado** (ADR-018): o dashboard roda na VPS | — | — | 2026-10-18 |
| Fly.io / Cloud Run / Oracle Cloud | **Não usar** | Exigem cartão ou conta de faturamento (violam R-01) | <https://docs.fly.io/about/pricing>, <https://docs.cloud.google.com/free/docs/free-cloud-features>, <https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm> | 2026-10-12 |
| HiveMQ Cloud | **Não usar no MVP** | A página oficial não lista mais plano gratuito Serverless | <https://www.hivemq.com/pricing/> | 2026-10-12 |

**Região da reserva no Render.** As regiões do blueprint são `oregon` (padrão), `ohio`, `virginia`, `frankfurt` e `singapore`, e a região não muda depois de criado o serviço (<https://render.com/docs/blueprint-spec>, 2026-10-19). O `infra/render.yaml` usa `virginia`, a mais próxima de um projeto Supabase em `sa-east-1` (São Paulo) ou em `us-east-1`. **Pendente do humano:** anotar a região do projeto Supabase no passo 1 da §4. Se for outra (por exemplo, `eu-central-1`), trocar a região do `infra/render.yaml` por PR antes de ativar a reserva (`frankfurt` para a Europa, `singapore` para a Ásia).

**Conferência da VPS** (passo 2 da §4; sem IP nem nome de host):

| Item | Comando | Valor | Data |
|---|---|---|---|
| Docker Engine | `docker version --format '{{.Server.Version}}'` | a preencher | a preencher |
| Compose v2 | `docker compose version` | a preencher | a preencher |
| Buildx | `docker buildx version` | a preencher | a preencher |
| RAM (total e disponível) | `free -h` | a preencher | a preencher |
| CPUs | `nproc` | a preencher | a preencher |
| Disco livre | `df -h /` | a preencher | a preencher |
| Limites escolhidos no `infra/.env` | — | a preencher (padrões: API `512m`/`1.0`, dashboard `1g`/`1.0`, Caddy `256m`/`0.5`) | a preencher |

Regra dos limites (SPEC-015 §4.12): a soma dos três `mem_limit` fica abaixo da RAM disponível, cada `cpus` fica ≤ `nproc`, e a API não fica abaixo de `512m` sem uma decisão registrada aqui. A imagem do dashboard tem cerca de 1,1 GB e a da API cerca de 240 MB (medido no build local de 2026-10-19); o disco precisa de folga para duas gerações de cada imagem durante uma atualização.

## 3. Segredos e variáveis

Nenhum valor real vai para o Git (R-03). Os nomes ficam em `.env.example`. Os arquivos da VPS ficam dentro do checkout, mas são ignorados pelo Git (padrões `.env` e `.env.*` do `.gitignore`) e pelo contexto de build das imagens (`infra/docker/*.Dockerfile.dockerignore`), e têm `chmod 600`.

| Variável | Onde é definida | Quem lê |
|---|---|---|
| `PUBLIC_HOST` (`<subdominio>`, sem esquema nem barra) e os limites `API_MEM_LIMIT`, `API_CPUS`, `DASHBOARD_MEM_LIMIT`, `DASHBOARD_CPUS`, `CADDY_MEM_LIMIT`, `CADDY_CPUS` | `infra/.env` na VPS | Compose (interpolação) e Caddy |
| `DATABASE_URL` (pooler do Supabase, modo transaction, porta 6543) | `infra/.env.api` na VPS (e o painel do Render, se a reserva for ativada) | `qc-api` |
| `DATABASE_URL` (pooler em modo session, porta 5432) | `.env.migrate` local do humano, nunca no Git, na VPS nem no Actions | `infra/migrate.py` e o registro de dispositivos |
| `READ_API_KEY` | `infra/.env.api` **e** `infra/.env.dashboard` na VPS (o mesmo valor) | `qc-api` (valida) e `qc-dashboard` (envia) |
| `API_BASE_URL` | Definida pelo próprio `infra/compose.yaml` como `https://${PUBLIC_HOST}`; localmente, em `.streamlit/secrets.toml` | `qc-dashboard` |
| `MODEL_METRICS_PATH` | Vazio no `infra/.env.dashboard` (vale o padrão `ml/models/partqc-mnv3-v1/metrics.json`, relativo a `/app`) | `qc-dashboard` |
| `DEVICE_ID`, `DEVICE_API_KEY`, `CLOUD_API_URL` (`https://<subdominio>`) | `.env` do notebook da borda | `qc-edge` |
| `SIM_DEVICE_ID`, `SIM_DEVICE_API_KEY` | `.env` local de quem roda o simulador e o smoke test (lido com `uv run --env-file`) | `scripts/simulate.py`, `scripts/smoke_test.py` |
| `KEEPALIVE_URL` (`https://<subdominio>`) | GitHub → Settings → Secrets and variables → Actions | workflow `keepalive.yml` |

Chaves de dispositivo (sempre na máquina do humano, com a URL lida do `.env.migrate`):

- geração: `uv run --env-file .env.migrate --package qc-api python scripts/register_device.py --device-id edge-01` (imprime a chave **uma única vez**; o banco guarda só o hash);
- rotação: `uv run --env-file .env.migrate --package qc-api python scripts/register_device.py --device-id <id> --rotate`.

Nunca passe a URL de produção na linha de comando: ela ficaria no `argv` (visível em `ps`) e no histórico do shell (SEC-04-03).

## 4. Passo a passo (primeira publicação)

Ordem da SPEC-015 §4.6. Todos os passos são humanos. Os comandos com `docker compose` rodam **na raiz do checkout** da VPS.

### Passo 1. Supabase

1. Usar o projeto Supabase já existente (conta pessoal, sem cartão, criado em 2026-10-12). **Anotar a região** (Settings → General) e conferir a nota da reserva na §2.
2. No SQL Editor, conferir o schema corrente (CA-19, passo 1):

   ```sql
   show search_path;
   select current_schema();
   ```

   O schema corrente precisa ser `public`. Se não for, parar e registrar `SPEC_ISSUE`.
3. **Migrações**, na máquina do humano (nunca na VPS nem no GitHub Actions), pelo pooler em **modo session** (porta 5432) ou pela conexão direta, **nunca** pela porta 6543. O executor recusa a porta 6543 antes de conectar (código 2), porque o advisory lock de sessão se perde no modo transaction (SPEC-015 §4.7).
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
5. Copiar a connection string do pooler em modo **transaction** (porta 6543) para a `DATABASE_URL` do `infra/.env.api` (passo 5). A API conecta com `prepare_threshold=None` (ADR-006).

### Passo 2. Conferência da VPS

1. Versões: `docker version`, `docker compose version` (precisa ser v2) e `docker buildx version`.
2. Recursos: `free -h`, `nproc` e `df -h /`.
3. Portas: `ss -tlnp '( sport = :80 or sport = :443 )'` não pode mostrar nenhum processo.
4. Firewall: `sudo ufw status verbose > ~/ufw-antes-partqc.txt`, um arquivo **fora** do repositório.
5. Registrar os valores na tabela "Conferência da VPS" da §2, sem IP nem nome de host.

### Passo 3. DNS

1. No provedor de DNS do humano, criar um registro `A` de `<subdominio>` para o IPv4 da VPS.
2. Criar `AAAA` **só** se o humano confirmar que o Docker da VPS publica as portas em IPv6.
3. Esperar `dig +short <subdominio> A` devolver o IP antes do passo 7.

### Passo 4. Checkout

`git clone https://github.com/CarlosZeyy/Projeto_IoT.git <dir>` (repositório público: nenhuma credencial na VPS) e `cd <dir>`, na branch `main`.

### Passo 5. Arquivos de ambiente

1. Gerar a `READ_API_KEY` na VPS com `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. Nunca reaproveitar uma chave de dispositivo.
2. Criar, **com um editor** (por exemplo, `nano`), os três arquivos abaixo. Nunca com `echo ... >`, que deixa o valor no histórico do shell.
   - `infra/.env`: uma linha com o nome `PUBLIC_HOST` e o subdomínio real como valor (sem `https://` e sem barra) e, se preciso, os limites `API_MEM_LIMIT`, `API_CPUS`, `DASHBOARD_MEM_LIMIT`, `DASHBOARD_CPUS`, `CADDY_MEM_LIMIT` e `CADDY_CPUS` (modelo no bloco `infra/.env` do `.env.example`).
   - `infra/.env.api`: `DATABASE_URL` (pooler em modo transaction, porta 6543) e `READ_API_KEY`; opcionais `MAX_BODY_BYTES` e `LOG_LEVEL`.
   - `infra/.env.dashboard`: `READ_API_KEY` (o mesmo valor) e `MODEL_METRICS_PATH` vazio. **Sem** `API_BASE_URL`, que vem do compose, e sem `DATABASE_URL` ou chaves de dispositivo.
3. Todo valor com `$` vai entre aspas simples, por exemplo `DATABASE_URL='postgresql://...'`. Sem aspas (ou com aspas duplas), o Compose interpola o `$` e trunca a senha sem aviso (<https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/>, 2026-10-19).
4. Ajustar os limites do `infra/.env` conforme o `free -h` e o `nproc` do passo 2 (regra na §2).
5. `chmod 600 infra/.env infra/.env.api infra/.env.dashboard`.
6. `git status --short` não pode listar nenhum dos três.

### Passo 6. Validação

`docker compose -f infra/compose.yaml config --quiet` → código 0. Nunca rode o subcomando de configuração do compose sem `--quiet` num terminal compartilhado ou gravado: sem a opção, ele imprime os valores dos `env_file`.

### Passo 7. Subida

1. `docker compose -f infra/compose.yaml up -d --build`.
2. `docker compose -f infra/compose.yaml ps`: os 3 serviços `running`, com `api` e `dashboard` `healthy` (o primeiro healthcheck roda depois de até 90 s).
3. `docker compose -f infra/compose.yaml logs caddy`: conferir a obtenção do certificado (`certificate obtained successfully`). Um aviso do Caddy sobre o buffer UDP do HTTP/3 é esperado e aceito (SPEC-015 §7: sem `NET_ADMIN`).
4. CA-43, passo 1: `docker compose -f infra/compose.yaml run --rm --no-deps --entrypoint find api /app -maxdepth 2 -name '.env*'` e o mesmo com `dashboard` → nenhuma linha, ou só `/app/.env.example`. Se aparecer outro `.env*`, parar, remover as imagens (`docker image rm`), não publicar e registrar `SPEC_ISSUE` (o Compose da VPS não respeitou o `.dockerignore` por Dockerfile).

### Passo 8. Dispositivos

Na máquina do humano (não na VPS), com o `.env.migrate` do passo 1:

- `uv run --env-file .env.migrate --package qc-api python scripts/register_device.py --device-id edge-01`
- `uv run --env-file .env.migrate --package qc-api python scripts/register_device.py --device-id sim-01`

As chaves vão para os `.env` locais (`DEVICE_API_KEY` da borda e `SIM_DEVICE_API_KEY` do simulador).

### Passo 9. Borda

No `.env` do notebook: `CLOUD_API_URL=https://<subdominio>`.

### Passo 10. Keep-alive (GitHub)

1. O keep-alive principal é o healthcheck da API: a cada 60 s, `GET /api/v1/health` faz `SELECT 1` no Supabase. Com o banco pausado ou fora do ar, o contêiner fica `unhealthy`, mas continua rodando (o Docker não reinicia por healthcheck).
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

Executar os CAs manuais da SPEC-015 (CA-13 a CA-19, CA-26, CA-40, CA-42 e CA-43) e registrar o resultado na §9 e no dev-report, sem o subdomínio real nem o IP.

### Firewall da VPS e coexistência com os outros projetos (SPEC-015 §4.15)

- O Docker publica as portas do Caddy por fora do `ufw`: "traffic to and from that container gets diverted before it goes through the ufw firewall settings" (<https://docs.docker.com/engine/network/packet-filtering-firewalls/>, 2026-10-19). Nenhuma regra do `ufw` é necessária para o Caddy funcionar.
- Se quiser que o `ufw status` documente as portas, **só acrescente**: `sudo ufw allow 80/tcp`, `sudo ufw allow 443/tcp` e `sudo ufw allow 443/udp`.
- Se o provedor da VPS tiver um firewall no painel, conferir que 80/tcp, 443/tcp e 443/udp estão liberadas na entrada.
- Nunca rode `ufw reset`, `ufw default ...`, `ufw delete ...` ou `ufw --force ...`.
- Nunca ative nem desative o `ufw` por causa do projeto.
- Nunca rode `iptables -F`, `iptables -X` ou `nft flush`.
- Nunca edite o `/etc/docker/daemon.json` nem reinicie o Docker por causa do projeto.
- Nunca rode `docker system prune`, `docker volume prune` ou `docker network prune`: todos afetam os outros projetos.
- Nunca rode `docker compose down -v` (§6).
- **Depois do `up`** (CA-40):
  1. `docker compose -f infra/compose.yaml ps` mostra portas publicadas só no `caddy`;
  2. `ss -tlnp` do host não tem `:8000` nem `:8501`;
  3. de outra máquina, `curl --connect-timeout 5 http://<IP>:8000/` e `curl --connect-timeout 5 http://<IP>:8501/` falham;
  4. `sudo ufw status verbose | diff ~/ufw-antes-partqc.txt -` não mostra nenhuma regra a menos (linhas com `<`);
  5. cada um dos outros projetos da VPS responde como antes.

### Atualização (SPEC-015 §4.16)

Depois de cada merge que afete a API, o dashboard, `infra/`, `ml/models/**/*.json` ou `ml/reports/`:

1. `cd <dir> && git pull --ff-only`
2. `docker compose -f infra/compose.yaml up -d --build`
3. `docker compose -f infra/compose.yaml ps` (os 3 `running`; `api` e `dashboard` `healthy`)
4. smoke test (passo 11, item 2)
5. `docker image prune -f --filter label=partqc.component` (remove só as imagens órfãs do PartQC)

A imagem do dashboard leva o `metrics.json` e os PNGs de `ml/reports/` **do commit publicado**: depois do merge do primeiro `metrics.json` (SPEC-012), basta esta atualização, e "Sobre o modelo" passa a mostrar a tabela de métricas.

**Logs:** `docker compose -f infra/compose.yaml logs --tail 200 <serviço>`. Nunca cole logs da API em lugar público: com o banco fora do ar, eles têm o host e o usuário do pooler (§7, item 2). O Caddy não registra acessos (sem a diretiva `log`), e o log de acesso do Uvicorn mostra o IP do Caddy na rede interna, e não o do cliente.

## 5. Checklist do dia da apresentação

**Na véspera:**

- [ ] Abrir o projeto Supabase (não pode estar pausado) e chamar `https://<subdominio>/api/v1/health` (deve retornar `db: ok`).
- [ ] Na VPS, `docker compose -f infra/compose.yaml ps`: os 3 serviços `running` e `healthy`. Não fazer atualização no dia.
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

- **Rollback da API e do dashboard na VPS:**
  1. `git log --oneline -10`;
  2. `git checkout <sha anterior>` e `docker compose -f infra/compose.yaml up -d --build`;
  3. com a correção mergeada, `git checkout main && git pull --ff-only` e o mesmo `up`.

  As migrações são só aditivas no MVP: um rollback não desfaz migração.
- **Parar:** `docker compose -f infra/compose.yaml down`, sem `-v`. Nunca use `docker compose down -v`, que apaga o volume dos certificados (`partqc_caddy_data`) e pode esbarrar no limite de emissão do Let's Encrypt (§7, item 6).
- **Modelo:** trocar `MODEL_DIR` para a versão anterior. O `model_version` de cada inspeção permite filtrar.
- **Reserva fria** (VPS fora do ar por mais de 24 h, ou no dia da demo; SPEC-015 §4.16, item 5):
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
   - **Na VPS:** não há proteção de provedor contra DDoS, e o Caddy padrão não tem limitação de taxa: `rate_limit` não está na lista de diretivas padrão e exigiria um build próprio com plugin (<https://caddyserver.com/docs/caddyfile/directives>, conferido em 2026-10-19). O impacto nos outros projetos da VPS fica limitado pelo `mem_limit` e pelos `cpus` de cada serviço (`infra/compose.yaml`).
   - **Na reserva (Render):** vale a proteção automática do Render (<https://render.com/docs/ddos-protection>, conferido em 2026-10-19).
   - **Decisão:** risco aceito no MVP. Uma limitação de taxa só entra por SPEC nova.
2. **Log do `psycopg.pool` (SEC-04-05).** Com o banco fora do ar, o logger `psycopg.pool` registra em `WARNING` o host, a porta e, numa falha de autenticação, o usuário do pooler do Supabase, sem a senha. Esse log fica em `docker compose -f infra/compose.yaml logs api`, que só o humano acessa na VPS, e no painel do Render quando a reserva está ativa. Não são segredos (R-03 cumprida). No portão `deploy`, esse log não conta como vazamento: é a exceção da regra "Erros de banco no log" de `docs/architecture.md` §4 (SPEC-004, r2-security-report, 2026-10-13).
3. **Consulta cancelada pelo `statement_timeout`:** uma consulta que passa do limite é cancelada com o código `57014` (`QueryCanceled`) e responde 503 `{"detail": "Database unavailable"}`, igual a um banco fora do ar, sem a mensagem do Postgres nem stack trace (SEC-26-02, SPEC-026 r1-security-report; <https://supabase.com/docs/guides/database/postgres/timeouts>, conferido em 2026-10-19).
   - O `QueryCanceled` é subclasse de `psycopg.OperationalError`, que o `db_connection` (`api/src/qc_api/db.py`) converte em `DatabaseUnavailableError`.
   - O dashboard mostra o aviso de API indisponível e não repete a chamada em laço (SPEC-013).
   - As migrações rodam com o mesmo papel: se uma migração futura passar do limite, ela falha e faz `rollback`, e o humano a repete com o limite ajustado só naquela sessão (`set statement_timeout = '60s';` pela conexão do `.env.migrate`, em modo session).
4. **Subdomínio nos logs de Certificate Transparency.** O Let's Encrypt envia todo certificado emitido aos logs de CT (<https://letsencrypt.org/docs/ct-logs/>, conferido em 2026-10-19), e o nome do subdomínio fica descobrível. A R-13 exige manter o nome fora do repositório, e não escondê-lo do mundo.
5. **VPS como ponto único de falha, compartilhada com outros projetos.** Mitigação: outbox na borda (RNF-10), limites de memória e CPU por serviço e a reserva fria no Render (§6). O Caddy sobe mesmo com o Supabase pausado (sem `condition: service_healthy`), e um contêiner `unhealthy` não é reiniciado.
6. **Limite de emissão de certificados.** "Up to 5 certificates can be issued per exact same set of identifiers every 7 days" (<https://letsencrypt.org/docs/rate-limits/>, conferido em 2026-10-19). Perder o volume `partqc_caddy_data` força uma emissão nova. Nunca usar `docker compose down -v`.
7. **HTTP/3 sem `NET_ADMIN`.** O Caddy pode avisar no log sobre o tamanho do buffer UDP; a capacidade `NET_ADMIN` não é concedida (SPEC-015 §7), e o HTTP/2 por TCP continua (<https://hub.docker.com/_/caddy>, conferido em 2026-10-19).

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
5. **Conferir pelo caminho da API** (pooler em modo transaction, porta 6543), com a URL lida de um arquivo local ignorado pelo Git, nunca na linha de comando. Por exemplo, com o `.env.prod` do passo 11 acrescido de uma linha `DATABASE_URL=<URL do modo transaction>` (entre aspas simples se tiver `$`):

   ```bash
   uv run --env-file .env.prod --package qc-api python -c "import os, psycopg; c = psycopg.connect(os.environ['DATABASE_URL'], prepare_threshold=None); print(c.execute('show statement_timeout').fetchone()[0])"
   ```

   Saída esperada: `15s`. Se não for, parar e registrar `SPEC_ISSUE` para o architect (a alternativa é um `set local statement_timeout` na transação de leitura da API, numa SPEC do developer).
6. Registrar na §9 e no dev-report as saídas dos itens 1, 4 e 5 e a data.

### 2. `READ_API_KEY` (INFO-02 da SPEC-005)

- **Geração:** só com `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`, nunca reaproveitando uma chave de dispositivo.
- **Troca:**
  1. gerar a nova chave;
  2. na VPS, atualizar o valor no `infra/.env.api` **e** no `infra/.env.dashboard` (com um editor) e rodar `docker compose -f infra/compose.yaml up -d`, que recria os dois serviços. Durante a recriação, o painel fica indisponível por alguns segundos;
  3. se a reserva no Render estiver ativa, atualizar a variável no painel dele na mesma sessão;
  4. conferir com o smoke test do passo 11 (checagens `read_requires_key` e `read`), que lê a chave do ambiente. Nunca conferir com `curl -H "X-API-Key: ..."`, que deixa a chave no `argv`.

### 3. Limites da reserva (Render)

512 MB de RAM e 0,1 CPU no plano `free` (linha do Render na §2, <https://render.com/docs/compute-plans>, conferido em 2026-10-19). Na VPS, o `mem_limit` padrão da API é o mesmo (`512m`), o envelope do ADR-017.

### 4. Simulador em produção (SEC-07 e SEC-01 da SPEC-014)

- Contra produção, só execuções pequenas: `--lots` até 10 e `--lot-size` até 50 (no máximo 500 itens por execução), por exemplo `uv run --env-file .env.prod --package qc-api python scripts/simulate.py --lots 3`.
- A chave vai sempre pelo arquivo de ambiente (`SIM_DEVICE_API_KEY`). Nunca use `--api-key` em demo gravada, terminal projetado, CI ou workflow. Se for inevitável, use a forma `--api-key=<valor>` com um espaço no início do comando, para que ele não entre no histórico do shell.
- Se uma chave aparecer numa gravação, num log compartilhado ou num print, rotacioná-la com `uv run --env-file .env.migrate --package qc-api python scripts/register_device.py --device-id sim-01 --rotate` e atualizar o `.env` local.

## 9. Registro dos CAs manuais da SPEC-015

Preenchido pelo humano (e copiado no dev-report), sem o subdomínio real nem o IP. Os comandos estão na SPEC-015 §5.

| CA | O que | Resultado | Data |
|---|---|---|---|
| CA-13 | API na VPS: health, redirecionamento HTTP → HTTPS, 401 sem chave, HSTS sem `includeSubDomains`, emissor do certificado, `/docs` e `/openapi.json` não publicados | pendente | — |
| CA-14 | RLS e grants em produção (passo 1, item 4) | pendente | — |
| CA-15 | Smoke em produção: 8 × `PASS` (passo 11) | pendente | — |
| CA-16 | Keep-alive por `workflow_dispatch` verde em ≤ 10 min (passo 10) | pendente | — |
| CA-17 | Dashboard na VPS: desktop e celular, WebSocket `wss://<subdominio>/_stcore/stream` com 101 por 5 min, filtros, selo de simulado, "Sobre o modelo" (mensagem com `ml/models/partqc-mnv3-v1/metrics.json` enquanto não houver `metrics.json`; repetir depois do merge do primeiro `metrics.json` da SPEC-012 e da atualização da §4), `printenv API_BASE_URL` começa com `https://` | pendente | — |
| CA-18 | R-01: Supabase e GitHub Actions sem cartão; VPS preexistente e sem mudança de plano (confirmação escrita do humano); domínio já existente; Render sem cartão e serviço `free` se ativado | pendente | — |
| CA-19 | `search_path`, migração pelo modo session e restrições da `002` (passo 1, itens 2 e 3) | pendente | — |
| CA-26 | `statement_timeout` (§8, item 1) | pendente | — |
| CA-40 | Rede e coexistência na VPS (§4, "Firewall") | pendente | — |
| CA-42 | Na VPS, `git grep -nF -e "$(grep '^PUBLIC_HOST' infra/.env \| cut -d= -f2-)"` → nenhuma linha; o mesmo com o IPv4 público → nenhuma linha | pendente | — |
| CA-43 | `.env*` fora das imagens (passo 7, item 4); ciclo de atualização, rollback e volta à `main` com health 200; `partqc_caddy_data` presente e sem nova emissão de certificado | pendente | — |
