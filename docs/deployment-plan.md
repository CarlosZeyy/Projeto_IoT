# Plano de deploy

Este documento é de responsabilidade do agente `security-devops` (SPEC-015). Os limites de free tier mudam com frequência: **confira de novo antes de cada decisão** e atualize a coluna "Verificado em".

## 1. Ambientes

| Ambiente | Onde | Para quê |
|---|---|---|
| `local` | Notebook da equipe | Desenvolvimento e testes: a API local aponta para um **Postgres local em Docker** (o mesmo dos testes, `TEST_DATABASE_URL`) |
| `edge` | Notebook da demo | Gateway de borda na LAN (`qc-edge`) |
| `cloud` | Render, Supabase e Streamlit CC | API, banco e dashboard públicos (dados protegidos por chave) |

**Um único projeto Supabase** (o que a dupla já criou para este trabalho) é o banco de produção (`cloud`). O desenvolvimento e os testes usam o Postgres local em Docker, então os dados de teste nunca chegam ao Supabase. Confirme que o projeto está numa conta **pessoal** (R-13).

## 2. Serviços e limites

| Serviço | Uso | Limites relevantes (free) | Fonte | Verificado em |
|---|---|---|---|---|
| Render (Web Service free) | `qc-api` | Dorme após 15 min sem tráfego; acorda em cerca de 1 min; 750 h/mês por workspace. RAM e CPU não informadas na página (≈ 512 MB, não confirmado) | <https://render.com/docs/free> | 2026-10-12 |
| Koyeb (Hobby) — **reserva** | `qc-api` se o Render falhar | 1 web service, 512 MB, 0,1 vCPU, dorme após 1 h, sem cartão | <https://www.koyeb.com/pricing> | 2026-10-12 |
| Supabase Free | Postgres | 500 MB de banco, 2 projetos ativos, **pausa após 1 semana sem atividade**, 5 GB de egress | <https://supabase.com/pricing> | 2026-10-12 |
| Streamlit Community Cloud | `qc-dashboard` | Cerca de 0,078–2 CPU e 690 MB–2,7 GB de RAM; dorme após 12 h sem tráfego (qualquer visitante acorda); repositório público não exige permissão extra (privado exigiria) | <https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app> | 2026-10-12 |
| GitHub (repo **público** + Actions) | Código, CI, keep-alive, Releases para o `model.onnx` | Actions com runners padrão gratuito para repositórios públicos | <https://docs.github.com/billing> | a verificar na SPEC-015 (CA-18) |
| Fly.io / Cloud Run / Oracle Cloud | **Não usar** | Exigem cartão ou conta de faturamento (violam R-01) | <https://docs.fly.io/about/pricing>, <https://docs.cloud.google.com/free/docs/free-cloud-features>, <https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm> | 2026-10-12 |
| HiveMQ Cloud | **Não usar no MVP** | A página oficial não lista mais plano gratuito Serverless | <https://www.hivemq.com/pricing/> | 2026-10-12 |

## 3. Segredos e variáveis

Nenhum valor real vai para o Git (R-03). Os nomes ficam em `.env.example`.

| Variável | Onde é definida | Quem lê |
|---|---|---|
| `DATABASE_URL` (connection string do pooler do Supabase, modo transaction) | Render → Environment | `qc-api` |
| `DATABASE_URL` (pooler em modo session, porta 5432) | `.env.migrate` local do humano, nunca no Git nem no Actions | `infra/migrate.py` |
| `READ_API_KEY` | Render → Environment **e** Streamlit → Secrets | `qc-api` (valida) e `qc-dashboard` (envia) |
| `API_BASE_URL` | Streamlit → Secrets | `qc-dashboard` |
| `DEVICE_ID`, `DEVICE_API_KEY`, `CLOUD_API_URL` | `.env` do notebook da borda | `qc-edge` |
| `SIM_DEVICE_ID`, `SIM_DEVICE_API_KEY` | `.env` local de quem roda o simulador | `scripts/simulate.py` |
| `KEEPALIVE_URL` | GitHub → Secrets do repositório | workflow `keepalive.yml` |

Chaves de dispositivo:
- geradas por `scripts/register_device.py --device-id edge-01` (imprime a chave **uma única vez**; o banco guarda só o hash);
- rotação com `--rotate`.

## 4. Passo a passo (primeira publicação)

1. **Supabase:**
   1. Usar o projeto Supabase já existente (criado em 2026-10-12). Anotar a região.
   2. Aplicar as migrações pelo pooler em **modo session** (porta 5432) ou pela conexão direta, **nunca** pela porta 6543 (o advisory lock do executor é de sessão; SPEC-015 §4.7 e CA-19): criar `.env.migrate` (ignorado pelo Git) com `DATABASE_URL=<URL do modo session>` e rodar `uv run --env-file .env.migrate --package qc-api python infra/migrate.py`. Antes, conferir `select current_schema();` → `public`. Alternativa: colar `infra/migrations/*.sql`, em ordem, no SQL Editor. O passo a passo final é escrito pela SPEC-015.
   3. Conferir que o RLS está ligado em `devices`, `inspections` e `schema_migrations` e que `anon`/`authenticated` não têm grants nessas tabelas (SPEC-015 CA-14).
   4. Copiar a connection string do **pooler** (modo transaction, porta 6543) para a `DATABASE_URL` da API. A API conecta com `prepare_threshold=None` (ADR-006).
2. **Render:**
   1. Criar o Web Service a partir do repositório público `CarlosZeyy/Projeto_IoT`, usando o blueprint `infra/render.yaml`.
   2. Build: `pip install uv && uv sync --package qc-api --frozen --no-dev`.
   3. Start: `uv run --package qc-api uvicorn qc_api.main:app --host 0.0.0.0 --port $PORT`.
   4. Health check: `/api/v1/health`.
   5. Definir `DATABASE_URL` e `READ_API_KEY`.
3. **Dispositivos:** rodar `register_device.py` para `edge-01` e `sim-01` e guardar as chaves nos `.env` locais.
4. **Streamlit CC:**
   1. Conectar o repositório público. Entry point: `dashboard/app.py`.
   2. Dependências: `dashboard/requirements.txt`, gerado por `uv export --package qc-dashboard --no-hashes --frozen`. A SPEC-015 confirma se a dependência local `packages/contracts` instala no Streamlit CC; se não, use o fallback descrito na SPEC.
   3. Secrets: `API_BASE_URL` e `READ_API_KEY`.
5. **Keep-alive:** o workflow `.github/workflows/keepalive.yml` faz `GET $KEEPALIVE_URL/api/v1/health` a cada 3 dias. Isso mantém o Supabase ativo, porque o `/health` executa `SELECT 1`.
6. **Smoke test:**
   1. Rodar `scripts/simulate.py --lots 3` contra a API de produção.
   2. Ver os dados no dashboard com o selo "simulado".
   3. Manter os dados simulados (filtráveis por `source`; o dashboard mostra o selo). Se for preciso apagar: `delete from inspections where source = 'simulated';` no SQL Editor, executado pelo humano.

## 5. Checklist do dia da apresentação

**Na véspera:**
- [ ] Abrir o projeto Supabase (não pode estar pausado) e chamar `/api/v1/health` (deve retornar `db: ok`).
- [ ] Carregar o `model.onnx` congelado no notebook e conferir que o `sha256` bate com o `metrics.json`.
- [ ] Conferir as baterias e o carregador do celular e do notebook.
- [ ] Gravar o vídeo de backup da demo (S7) e deixá-lo offline no notebook.

**30 min antes:**
- [ ] Chamar `/api/v1/health` para acordar o Render (cerca de 1 min) e abrir o dashboard para acordar o Streamlit.
- [ ] Ligar a borda (`uv run --package qc-edge qc-edge`), abrir o console e ler o QR com o celular.
- [ ] Rede: usar por padrão a **rede própria** (notebook conectado ao hotspot do celular), ensaiada em casa; o Wi-Fi do campus só se já tiver sido testado. Se o celular não abrir `/capture`, conferir o IP do notebook na rede do hotspot e o firewall. Se ainda assim falhar, usar a ancoragem USB (plano C). Túnel público é proibido (R-02). Último recurso: o vídeo de backup.
- [ ] Liberar a porta 8000 no firewall do notebook.
- [ ] Fundo A4, luminária e peças separadas por lote (incluindo uma `unusable` e um objeto `other` para mostrar o "desconhecido").

**Durante:**
- [ ] Mostrar o modo offline: desligar o Wi-Fi do notebook, inspecionar 3 peças, religar e ver o outbox esvaziar.

## 6. Rollback

- **API:** no Render, "Rollback" para o deploy anterior. As migrações são só aditivas no MVP.
- **Modelo:** trocar `MODEL_DIR` para a versão anterior. O `model_version` de cada inspeção permite filtrar.
- **Dashboard:** redeploy do commit anterior pelo Streamlit CC.
