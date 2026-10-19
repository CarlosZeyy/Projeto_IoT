# Plano de deploy

Este documento é de responsabilidade do agente `security-devops` (SPEC-015). A estrutura abaixo foi reescrita pelo architect em 2026-10-18 para a decisão do ADR-018: API e dashboard na VPS pessoal, com Docker Compose e Caddy; banco no Supabase; Render como reserva fria. Os comandos exatos, os valores finais e as datas de verificação são completados pelo autor da SPEC-015.

Os limites de free tier e as versões mudam com frequência: **confira de novo antes de cada decisão** e atualize a coluna "Verificado em". O subdomínio real e o IP da VPS **nunca** entram neste arquivo (R-13): use `<subdominio>` e `<IP>`.

## 1. Ambientes

| Ambiente | Onde | Para quê |
|---|---|---|
| `local` | Notebook da equipe | Desenvolvimento e testes: a API local aponta para um **Postgres local em Docker** (o mesmo dos testes, `TEST_DATABASE_URL`) |
| `edge` | Notebook da demo | Gateway de borda na LAN (`qc-edge`) |
| `cloud` | VPS pessoal (Docker Compose: Caddy, `qc-api`, `qc-dashboard`) e Supabase | API e dashboard públicos em `https://<subdominio>` (dados protegidos por chave) |
| `cloud` (reserva) | Render (Web Service free) | Só a API, publicada num incidente (§6) |

**Um único projeto Supabase** (o que a dupla já criou para este trabalho) é o banco de produção (`cloud`). O desenvolvimento e os testes usam o Postgres local em Docker, então os dados de teste nunca chegam ao Supabase. Confirme que o projeto está numa conta **pessoal** (R-13).

## 2. Serviços e limites

| Serviço | Uso | Limites relevantes | Fonte | Verificado em |
|---|---|---|---|---|
| VPS pessoal do humano | `caddy`, `qc-api`, `qc-dashboard` (`infra/compose.yaml`) | Recurso pessoal **preexistente**, pago a cada 2 anos, sem custo adicional para o projeto (R-01, ADR-018). Docker e Compose v2 instalados; portas 80/443 livres. RAM, CPUs, disco e versões: preencher com `free -h`, `nproc`, `df -h /` e `docker version` (SPEC-015 §4.6, passo 2) | Declaração do humano (ADR-018) | 2026-10-18 (a completar) |
| Supabase Free | Postgres | 500 MB de banco, 2 projetos ativos, **pausa com pouca atividade num período de 7 dias**, 5 GB de egress | <https://supabase.com/pricing>, <https://supabase.com/docs/guides/platform/free-project-pausing> | 2026-10-18 |
| Let's Encrypt (via Caddy) | Certificado TLS de `<subdominio>` | 5 certificados por conjunto exato de nomes a cada 7 dias; todo certificado vai para os logs públicos de CT | <https://letsencrypt.org/docs/rate-limits/>, <https://letsencrypt.org/docs/ct-logs/> | 2026-10-18 |
| GitHub (repo **público** + Actions) | Código, CI (`ci` e `docker`), keep-alive, Releases para o `model.onnx` | "GitHub Actions usage is free for ... public repositories that use standard GitHub-hosted runners"; workflows agendados são desligados após 60 dias sem atividade no repositório | <https://docs.github.com/en/billing/concepts/product-billing/github-actions>, <https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows> | 2026-10-18 |
| Render (Web Service free) — **reserva fria** | `qc-api`, só num incidente (§6) | 512 MB de RAM e 0,1 CPU; dorme após 15 min sem tráfego; acorda em cerca de 1 min; 750 h/mês por workspace | <https://render.com/docs/compute-plans>, <https://render.com/docs/free> | 2026-10-18 |
| Koyeb | **Não usado** (ADR-018) | — | — | 2026-10-18 |
| Streamlit Community Cloud | **Não usado** (ADR-018): o dashboard roda na VPS | — | — | 2026-10-18 |
| Fly.io / Cloud Run / Oracle Cloud | **Não usar** | Exigem cartão ou conta de faturamento (violam R-01) | <https://docs.fly.io/about/pricing>, <https://docs.cloud.google.com/free/docs/free-cloud-features>, <https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm> | 2026-10-12 |
| HiveMQ Cloud | **Não usar no MVP** | A página oficial não lista mais plano gratuito Serverless | <https://www.hivemq.com/pricing/> | 2026-10-12 |

## 3. Segredos e variáveis

Nenhum valor real vai para o Git (R-03). Os nomes ficam em `.env.example`. Os arquivos da VPS ficam dentro do checkout, mas são ignorados pelo Git e pelo contexto de build das imagens (SPEC-015 §4.11) e têm `chmod 600`.

| Variável | Onde é definida | Quem lê |
|---|---|---|
| `PUBLIC_HOST` (`<subdominio>`, sem esquema) e os limites `API_MEM_LIMIT`, `API_CPUS`, `DASHBOARD_MEM_LIMIT`, `DASHBOARD_CPUS`, `CADDY_MEM_LIMIT`, `CADDY_CPUS` | `infra/.env` na VPS | Compose (interpolação) e Caddy |
| `DATABASE_URL` (pooler do Supabase, modo transaction, porta 6543) | `infra/.env.api` na VPS (e o painel do Render, se a reserva for ativada) | `qc-api` |
| `DATABASE_URL` (pooler em modo session, porta 5432) | `.env.migrate` local do humano, nunca no Git, na VPS nem no Actions | `infra/migrate.py`, `scripts/register_device.py` |
| `READ_API_KEY` | `infra/.env.api` **e** `infra/.env.dashboard` na VPS (o mesmo valor) | `qc-api` (valida) e `qc-dashboard` (envia) |
| `API_BASE_URL` | Definida pelo próprio `infra/compose.yaml` como `https://${PUBLIC_HOST}`; localmente, em `.streamlit/secrets.toml` | `qc-dashboard` |
| `DEVICE_ID`, `DEVICE_API_KEY`, `CLOUD_API_URL` (`https://<subdominio>`) | `.env` do notebook da borda | `qc-edge` |
| `SIM_DEVICE_ID`, `SIM_DEVICE_API_KEY` | `.env` local de quem roda o simulador | `scripts/simulate.py` |
| `KEEPALIVE_URL` (`https://<subdominio>`) | GitHub → Secrets do repositório | workflow `keepalive.yml` |

Chaves de dispositivo:
- geradas na máquina do humano por `uv run --env-file .env.migrate --package qc-api python scripts/register_device.py --device-id edge-01` (imprime a chave **uma única vez**; o banco guarda só o hash);
- rotação com `uv run --env-file .env.migrate --package qc-api python scripts/register_device.py --device-id <id> --rotate`.

## 4. Passo a passo (primeira publicação)

Ordem da SPEC-015 §4.6. Todos os passos são humanos: os agentes não têm acesso à VPS.

1. **Supabase:**
   1. Usar o projeto Supabase já existente (criado em 2026-10-12). Anotar a região.
   2. Antes de migrar, conferir `select current_schema();` → `public` (CA-19).
   3. Aplicar as migrações pela máquina do humano, nunca pela VPS nem pelo Actions, pelo pooler em **modo session** (porta 5432) ou pela conexão direta, **nunca** pela porta 6543 (o advisory lock do executor é de sessão; SPEC-015 §4.7 e CA-19):
      - criar `.env.migrate` (ignorado pelo Git) com `DATABASE_URL=<URL do modo session>`;
      - rodar `uv run --env-file .env.migrate --package qc-api python infra/migrate.py`.
   4. Conferir que o RLS está ligado em `devices`, `inspections` e `schema_migrations` e que `anon`/`authenticated` não têm grants nessas tabelas (SPEC-015 CA-14).
   5. Copiar a connection string do **pooler** (modo transaction, porta 6543) para o `infra/.env.api` (passo 5). A API conecta com `prepare_threshold=None` (ADR-006).
2. **Conferência da VPS** (SPEC-015 §4.15):
   - versões: `docker version`, `docker compose version` e `docker buildx version`;
   - recursos: `free -h`, `nproc` e `df -h /`;
   - portas: `ss -tlnp '( sport = :80 or sport = :443 )'`, que não deve mostrar nenhum processo;
   - firewall: `sudo ufw status verbose > ~/ufw-antes-partqc.txt`, um arquivo fora do repositório;
   - registrar na §2 as versões, a RAM, as CPUs e o disco livre.
3. **DNS:** registro `A` de `<subdominio>` para o IPv4 da VPS; `dig +short <subdominio> A` precisa devolver o IP antes do passo 7.
4. **Checkout:** `git clone https://github.com/CarlosZeyy/Projeto_IoT.git <dir>` e `cd <dir>`.
5. **Arquivos de ambiente:**
   1. Criar `infra/.env`, `infra/.env.api` e `infra/.env.dashboard` com um editor, nunca com `echo`, e rodar `chmod 600 infra/.env infra/.env.api infra/.env.dashboard`.
   2. Gerar a `READ_API_KEY` com `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
   3. Pôr entre aspas simples todo valor que tenha `$`.
   4. Ajustar os limites do `infra/.env` conforme o `free -h` e o `nproc`. Os padrões são API `512m`/`1.0`, dashboard `1g`/`1.0` e Caddy `256m`/`0.5`. A soma da memória fica abaixo da RAM disponível, e cada `cpus` fica ≤ `nproc`.
   5. Conferir com `git status --short` que os três arquivos não aparecem.
6. **Validação:** `docker compose -f infra/compose.yaml config --quiet`. Nunca rode o `config` sem `--quiet` (ele imprime os segredos).
7. **Subida:**
   - `docker compose -f infra/compose.yaml up -d --build`;
   - `docker compose -f infra/compose.yaml ps`: os 3 serviços `running`, com `api` e `dashboard` `healthy`;
   - `docker compose -f infra/compose.yaml logs caddy`: certificado obtido.
8. **Dispositivos:** na máquina do humano, `uv run --env-file .env.migrate --package qc-api python scripts/register_device.py --device-id edge-01` e o mesmo para `sim-01`; as chaves vão para os `.env` locais.
9. **Borda:** `CLOUD_API_URL=https://<subdominio>` no `.env` do notebook.
10. **Keep-alive:** o healthcheck da API (a cada 60 s) faz `SELECT 1` no Supabase. O workflow `.github/workflows/keepalive.yml` faz `GET $KEEPALIVE_URL/api/v1/health` a cada 3 dias como verificação externa: definir o secret `KEEPALIVE_URL=https://<subdominio>` e disparar o workflow manualmente.
11. **Smoke test:**
    1. `uv run --env-file <arquivo> --package qc-api python scripts/smoke_test.py`, com as duas URLs iguais a `https://<subdominio>`: as 8 checagens dão `PASS`.
    2. Rodar `uv run --env-file .env --package qc-api python scripts/simulate.py --lots 3` contra a API de produção (no máximo `--lots 10` e `--lot-size 50`).
    3. Ver os dados no dashboard com o selo "simulado".
    4. Manter os dados simulados (filtráveis por `source`; o dashboard mostra o selo). Se for preciso apagar: `delete from inspections where source = 'simulated';` no SQL Editor, executado pelo humano.
12. **Banco:** `statement_timeout` do papel da API (SPEC-015 §4.9, item 1; CA-26).

**Firewall da VPS (outros projetos):**

- O Docker publica as portas do Caddy por fora do `ufw` (<https://docs.docker.com/engine/network/packet-filtering-firewalls/>), e nenhuma regra do `ufw` é necessária. Se quiser documentá-las, só acrescente: `sudo ufw allow 80/tcp`, `sudo ufw allow 443/tcp` e `sudo ufw allow 443/udp`.
- Nunca rode `ufw reset`, `ufw default`, `ufw delete` ou `ufw --force` nem ative ou desative o `ufw` por causa do projeto.
- Nunca rode `iptables -F`, `docker system prune`, `docker volume prune` ou `docker network prune`, nem reinicie o Docker: tudo isso afeta os outros projetos.
- Depois do `up`, compare `sudo ufw status verbose` com `~/ufw-antes-partqc.txt` (nenhuma regra a menos) e confira que os outros projetos respondem (SPEC-015 CA-40).

**Atualização** (depois de cada merge que afete a API, o dashboard, `infra/`, `ml/models/**/*.json` ou `ml/reports/`):

1. `cd <dir> && git pull --ff-only`
2. `docker compose -f infra/compose.yaml up -d --build`
3. `docker compose -f infra/compose.yaml ps` e o smoke test
4. `docker image prune -f --filter label=partqc.component` (remove só as imagens órfãs do PartQC)

**Logs:** `docker compose -f infra/compose.yaml logs --tail 200 <serviço>`. Não cole logs da API em lugar público: eles podem ter o host e o usuário do pooler (SPEC-015 §4.8).

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

- **API e dashboard na VPS:**
  1. `git log --oneline -10`;
  2. `git checkout <sha anterior>` e `docker compose -f infra/compose.yaml up -d --build`;
  3. com a correção mergeada, `git checkout main && git pull --ff-only` e o mesmo `up`.

  As migrações são só aditivas no MVP.
- **Parar:** `docker compose -f infra/compose.yaml down`. Nunca use `docker compose down -v`, que apaga o volume dos certificados (`caddy_data`) e pode esbarrar no limite de emissão do Let's Encrypt.
- **Modelo:** trocar `MODEL_DIR` para a versão anterior. O `model_version` de cada inspeção permite filtrar.
- **Reserva fria** (VPS fora do ar por mais tempo, ou no dia da demo; SPEC-015 §4.16, item 5):
  1. no Render, "New → Blueprint" com `infra/render.yaml`, e definir `DATABASE_URL` e `READ_API_KEY`;
  2. na borda, `CLOUD_API_URL=https://<servico>.onrender.com`;
  3. rodar o dashboard no notebook com `.streamlit/secrets.toml` apontando para essa URL (SPEC-028);
  4. `KEEPALIVE_URL` aponta para a reserva enquanto ela estiver em uso;
  5. registrar aqui o uso e a data;
  6. ao voltar para a VPS, desfazer os passos 2 a 4 e suspender o serviço do Render.
