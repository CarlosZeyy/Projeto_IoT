# Arquitetura

Fonte de verdade técnica do projeto. As SPECs detalham cada parte, mas **não podem contradizer** este documento sem um ADR.

## 1. Visão em 3 camadas (IoT: dispositivo → borda → nuvem)

```
┌─ DISPOSITIVO ─────────┐      ┌─ BORDA (notebook, LAN) ──────────────────────────┐      ┌─ NUVEM ─────────────────────────────────┐
│ Celular (navegador)   │      │ qc-edge (FastAPI, 0.0.0.0:8000)                  │      │ VPS pessoal (Docker Compose, ADR-018)   │
│                       │ HTTP │  ├─ console do operador (QR de pareamento)       │HTTPS │ Caddy (TLS, 80/443, <subdominio>)       │
│ /capture              │─────►│  ├─ /api/capture: recebe a foto                  │─────►│  ├─ /api/* ─► qc-api (FastAPI)          │
│  • foto (câmera nativa│      │  ├─ qc-preprocess (o mesmo do treino)            │      │  │    ├─ POST /inspections, /batch      │
│  • lote, modo         │◄─────│  ├─ onnxruntime → probabilidades                 │      │  │    ├─ GET leituras, métricas, SPC    │
│  • resultado na tela  │ JSON │  ├─ decisão (unknown / needs_review)             │      │  │    └─► Supabase Postgres (RLS)       │
└───────────────────────┘      │  ├─ foto salva no disco local (nunca sobe)       │      │  └─ /* ─► qc-dashboard (Streamlit)      │
                               │  └─ outbox SQLite → HttpPublisher (retry)        │      │           └─ lê tudo via qc-api         │
                               └──────────────────────────────────────────────────┘      └─────────────────────────────────────────┘
                                                                                          scripts/simulate.py ─► qc-api (source=simulated)
```

**Hospedagem** (ADR-018, SPEC-015):
- A `qc-api` e o `qc-dashboard` rodam na VPS pessoal do humano, com Docker Compose (`infra/compose.yaml`), atrás de um Caddy. O Caddy é o único serviço com portas publicadas (80 e 443) e obtém o certificado do Let's Encrypt para um único subdomínio pessoal.
- Roteamento: `/api/*` vai para a API (as rotas já têm o prefixo `/api/v1`); o resto, inclusive o WebSocket `/_stcore/stream`, vai para o Streamlit. `/docs` e `/openapi.json` não são publicados.
- O dashboard chama a API pela URL pública `https://<subdominio>`. O Caddy tem esse nome como alias na rede do compose, e o tráfego não sai da VPS.
- O banco continua no Supabase (ADR-006, ADR-008). O Render é a reserva fria da API (`infra/render.yaml`).
- O subdomínio real e o IP da VPS nunca entram no repositório (R-13): a documentação usa `<subdominio>`, e o valor real fica em `PUBLIC_HOST`, no `infra/.env` da VPS.

**A partir da SPEC-039 (ADR-023, `Aceito`, com a emenda 1 aceita pelo humano em 2026-10-25; substitui em parte o parágrafo acima).** A VPS é gerenciada pelo Coolify, cujo proxy (Traefik, contêiner `coolify-proxy`) ocupa as portas 80 e 443 e já publica outros projetos do humano.

- A `qc-api`, o `qc-dashboard` e o Caddy formam **dois** recursos "Docker Compose" do Coolify, criados a partir do repositório público (branch `main`, Base Directory `/infra`): `partqc-api` (Docker Compose Location `/compose.api.yaml`, só a API) e `partqc-web` (`/compose.yaml`, o Caddy e o dashboard). Motivo (emenda 1): o Coolify entrega a todos os serviços de um recurso o `.env` com todas as variáveis de runtime dele, e só a separação em recursos mantém a `DATABASE_URL` fora do dashboard e do Caddy.
- O Caddy chega à API pela rede `partqc-api-link` (`internal`), criada pelo `partqc-api` e declarada `external` no `partqc-web`.
- O proxy do Coolify termina o TLS de `https://<subdominio>` (certificado do Let's Encrypt) e encaminha por HTTP ao serviço `caddy`, porta interna 80. É o único serviço com domínio no Coolify.
- O Caddy fica só como roteador interno, com o site `:80`, sem TLS e sem portas publicadas, e mantém o roteamento, o bloqueio de `/docs` e de `/openapi.json` e os headers. O Caddyfile vai embutido numa imagem própria (`infra/docker/caddy.Dockerfile`). **Nenhum serviço do PartQC publica portas.**
- O dashboard chama `https://<subdominio>` pelo DNS público. A conexão volta à VPS pelo proxy do Coolify, porque o alias da rede sai.
- O subdomínio e os segredos ficam nas variáveis dos recursos no painel do Coolify, e não em arquivos `infra/.env*` na VPS: `DATABASE_URL` (e as variáveis de alertas) só no `partqc-api`, `PUBLIC_HOST` só no `partqc-web` e `READ_API_KEY` nos dois (SPEC-039 §4.1A).
- O Supabase e a reserva no Render não mudam.

**Por que assim** (ADR-002):
- O celular é só o sensor.
- O notebook concentra a inferência (latência baixa, sem custo de nuvem, imagens não saem da LAN — R-02) e a resiliência (outbox).
- A nuvem guarda o histórico e expõe os indicadores para acesso remoto.

## 2. Componentes e pacotes (workspace uv, Python 3.12)

| Pasta | Pacote | Responsabilidade | Dependências principais | Proibido |
|---|---|---|---|---|
| `packages/contracts/` | `qc-contracts` (`qc_contracts`) | Enums, schemas Pydantic v2, rótulos PT-BR, regra `is_defective` | pydantic | qualquer I/O |
| `packages/preprocess/` | `qc-preprocess` (`qc_preprocess`) | Pré-processamento determinístico da imagem (idêntico no treino e na borda) | numpy, pillow | torch |
| `edge/` | `qc-edge` (`qc_edge`) | Gateway de borda: página do celular, inferência, decisão, outbox, publisher, modo coleta | qc-contracts, qc-preprocess, fastapi, uvicorn, onnxruntime, qrcode, httpx, python-multipart | torch |
| `api/` | `qc-api` (`qc_api`) | API na nuvem: ingestão, leitura, métricas, SPC; alertas no Telegram (a partir da SPEC-017, §4) | qc-contracts, fastapi, uvicorn, psycopg 3 (pool), pydantic-settings, httpx | torch, onnxruntime |
| `dashboard/` | `qc-dashboard` | Painel Streamlit | qc-contracts, streamlit, plotly, pandas, httpx | torch, onnxruntime, acesso direto ao banco |
| `ml/` | `qc-ml` (`qc_ml`) | Manifest, split, treino, avaliação, export ONNX, paridade | qc-contracts, qc-preprocess, numpy, pandas, scikit-learn, onnxruntime, pillow; **extra opcional `train`**: torch, torchvision, timm, onnx, coral-pytorch | — |
| `scripts/` | (scripts soltos, executados com o ambiente do `qc-api`) | `simulate.py`, `register_device.py`, `smoke_test.py` | httpx, qc-contracts, psycopg | — |
| `infra/` | — | `migrations/*.sql`, `migrate.py`, `docker/` (Dockerfiles e um `.dockerignore` por Dockerfile; a partir da SPEC-039, também `caddy.Dockerfile`, com o Caddyfile embutido), `compose.yaml` (a partir da SPEC-039, só o Caddy e o dashboard) e `compose.api.yaml` (a partir da SPEC-039, só a API), `Caddyfile`, `render.yaml` (reserva) | — | segredos (os `infra/.env*` são ignorados pelo Git e pelo build, inclusive o `.env` que o Coolify grava no diretório de cada recurso, SPEC-039); qualquer nome de segredo da API em `compose.yaml` (SPEC-039 §4.1A) |

**Imagens** (SPEC-015 §4.10): `python:3.12.<patch>-slim` e `uv` com versões fixadas, `uv sync --package <pkg> --frozen --no-dev` (editável, para o `REPO_ROOT` do dashboard ser `/app`), usuário não root e `HEALTHCHECK`. Nenhuma imagem contém torch, torchvision, timm, onnx ou onnxruntime (R-12), e a do dashboard não contém driver de banco.

O acesso ao banco é feito com **psycopg 3 direto ao Postgres do Supabase** (connection string do pooler em modo transaction, guardada em `DATABASE_URL`, com `prepare_threshold=None`, porque esse modo não suporta prepared statements — ADR-006), e não pelo SDK `supabase-py`. Isso dá SQL explícito, transações e `ON CONFLICT` para a idempotência. A chave `service_role` não é necessária no MVP; se algum dia for, vale R-03.

As **migrações** são a exceção: o `infra/migrate.py` usa um advisory lock de sessão, que não sobrevive entre transações no modo transaction. Por isso, elas rodam pela conexão direta ou pelo pooler em **modo session** (porta 5432), nunca pela porta 6543, e o executor recusa essa porta (SPEC-015 §4.7).

## 3. Contrato v0 (`qc-contracts` 0.5.0, a partir da SPEC-018)

Versões: 0.1.0, a versão inicial (SPEC-002); 0.2.0, com o teto de `latency_ms` (SPEC-023); 0.3.0, com os 3 campos opcionais de corte da carta p em `SpcResponse` (SPEC-026, ADR-017; vigente até a SPEC-016); 0.4.0, com as 5 ferramentas manuais no `ObjectType` e os grupos de grau (SPEC-016, ADR-021; vigente até a SPEC-018); 0.5.0, com os schemas novos `HeartbeatCreate` e `DeviceStatus` (§3.3), sem mudar nenhum schema existente (SPEC-018, minor; vigente a partir da SPEC-018). O histórico completo fica em `packages/contracts/README.md`.

### 3.1 Enums

| Enum | Valores (código) | Rótulo PT-BR |
|---|---|---|
| `ObjectType` | `screw`, `nut`, `unknown`; a partir da SPEC-016 (0.4.0), também, nesta ordem, `pliers`, `adjustable_wrench`, `allen_key`, `flat_screwdriver`, `phillips_screwdriver` | parafuso, porca, desconhecido; alicate, chave inglesa, chave Allen, chave de fenda, chave Phillips |
| `Grade` (ordem = severidade 0..4) | `perfect`(0), `good`(1), `fair`(2), `poor`(3), `unusable`(4) | perfeito, bom, mediano, ruim, inutilizável |
| `Source` | `live`, `simulated` | real, simulado |
| `CaptureMode` (só borda) | `inspect`, `collect` | inspeção, coleta |

Expansões de `ObjectType`, cada uma acompanhada de aumento de versão:
- **Fase 2:** `pliers`, `adjustable_wrench`, `allen_key`, `flat_screwdriver`, `phillips_screwdriver` (entram na SPEC-016, contrato 0.4.0).
- **Fase 3 (futura):** `angle_grinder`, `saw`, `drill`, `cordless_screwdriver`.

**Grupos de grau** (ADR-021, `Aceito`; a partir da SPEC-016, contrato 0.4.0): `GRADE_REQUIRED_OBJECT_TYPES` (`screw`, `nut`), `GRADE_FORBIDDEN_OBJECT_TYPES` (`unknown` e, a partir da SPEC-021, as ferramentas elétricas) e `GRADE_OPTIONAL_OBJECT_TYPES` (as ferramentas manuais). Cada tipo está em exatamente um grupo.

A classe `other` do modelo é sempre mapeada para `unknown` no contrato.

**Regra de defeito** (ADR-013), implementada uma única vez em `qc_contracts.is_defective(grade)`: `poor` e `unusable` são defeituosos; os demais graus não. `grade = None` (objeto `unknown`) não é defeito e **não entra no SPC**.

### 3.2 `InspectionCreate` (borda → API)

| Campo | Tipo | Regra |
|---|---|---|
| `inspection_id` | UUID | v4, gerado na borda |
| `device_id` | str | `^[a-z0-9-]{3,32}$` |
| `lot_id` | str | `^[A-Za-z0-9_-]{1,40}$`, informado pelo operador |
| `inspected_at` | datetime | com fuso; normalizado para UTC; não pode estar mais de 5 min no futuro |
| `object_type` | ObjectType | |
| `grade` | Grade \| null | `null` **se e somente se** `object_type == unknown`. A partir da SPEC-016 (ADR-021): obrigatório nos tipos de grau obrigatório, `null` nos tipos sem grau e opcional nos de grau opcional (§3.1) |
| `grade_score` | float \| null | 0–4, valor esperado Σ i·p(i); `null` quando `grade` é `null` |
| `type_confidence` | float | 0–1 |
| `grade_confidence` | float \| null | 0–1; `null` quando `grade` é `null` |
| `needs_review` | bool | sinalização da borda (confiança baixa) |
| `model_version` | str | `^[a-z0-9.-]{3,40}$`, ex.: `partqc-mnv3-v1` |
| `model_sha256` | str | 64 caracteres hexadecimais |
| `latency_ms` | int | 0 a 2 147 483 647 (`MAX_LATENCY_MS` = 2³¹ − 1, o limite da coluna `integer` do §5), medindo pré-processamento + inferência |
| `source` | Source | |

Campos extras são rejeitados (`extra="forbid"`).

- **Coerção:** os modelos usam o modo padrão (lax) do Pydantic, sem `strict`. Depois da coerção, todas as faixas, regexes e invariantes continuam valendo. A decisão e os riscos aceitos estão na SPEC-023, §4.4.
- **Regex fora dos schemas:** quem reusar as constantes `DEVICE_ID_PATTERN`, `LOT_ID_PATTERN`, `MODEL_VERSION_PATTERN`, `SHA256_PATTERN` e, a partir da SPEC-018, `APP_VERSION_PATTERN` (ou qualquer outra regex de validação) fora dos schemas valida com `re.fullmatch`, ou pelo próprio schema / `pydantic.TypeAdapter`. **Nunca** com `re.match` ou `re.search`: no módulo `re`, o `$` casa antes de um `\n` final, e `"edge-01\n"` passaria.

### 3.3 Respostas

- `InspectionCreated`: `{"inspection_id": "...", "status": "created" | "duplicate"}`. HTTP 201 quando criado, 200 quando duplicado.
- `InspectionRead`: os campos de `InspectionCreate` mais `received_at` (UTC, servidor) e `is_defective` (bool, servidor).
- `BatchCreate`: `{"items": [InspectionCreate, ...]}`, com 1 a 100 itens. Resposta `{"results": [InspectionCreated, ...]}`, na mesma ordem. Se qualquer item for inválido, retorna 422 e nada é gravado.
- `Page[T]`: `{"items": [...], "total": int, "limit": int, "offset": int}`.
- `MetricsSummary`:
  - totais: `total`, `defective`, `defect_rate`, `unknown_count`, `needs_review_count`;
  - quebras: `by_grade` (dict grade→int), `by_object_type` (dict→int);
  - médias: `mean_type_confidence`, `mean_grade_score`.
- `TimeseriesPoint`: `bucket_start`, `total`, `defective`, `defect_rate`.
- `SpcResponse`: ver a seção 3.4.
- `HeartbeatCreate` (borda → API; a partir da SPEC-018, contrato 0.5.0; campos e limites na SPEC-018 §4.1): `sent_at` (com fuso, no máximo 5 min no futuro), `model_version` e `model_sha256` (nulos juntos quando a borda está sem modelo), `app_version` (`APP_VERSION_PATTERN = ^[0-9A-Za-z.+-]{1,40}$`), `uptime_s`, `outbox_pending` e `outbox_dead` (inteiros de 0 a `MAX_HEARTBEAT_COUNT` = 2 147 483 647). `extra="forbid"`.
- `DeviceStatus` (resposta; a partir da SPEC-018, contrato 0.5.0): `device_id`, `last_seen_at`, `last_heartbeat_at` (hora do servidor ao receber o heartbeat), `online` (calculado no servidor, §4), os campos do último heartbeat (todos anuláveis) e `last_source` (o `source` da inspeção mais recente do dispositivo, ou `null`).
- Erros: `{"detail": ...}` no formato padrão do FastAPI, sem stack trace.

### 3.4 SPC — carta p por lote (ADR-013)

- **Subgrupo:** `lot_id`. Os lotes são ordenados pelo menor `inspected_at`.
- **Registros considerados:** `object_type != unknown` e `source` filtrado (padrão `live`). A partir da SPEC-016 (ADR-021): `grade is not null`, que seleciona as mesmas linhas nos dados do MVP; a mesma regra vale para o denominador de `defect_rate` no resumo e na série temporal.
- **Por lote:** `n` = número de inspeções, `defects` = número de defeituosas, `p = defects / n`.
- **Lotes excluídos:** com `n < min_lot_size` (padrão 5). Saem do cálculo e são listados em `excluded_lots`.
- **Linha central:** `p̄ = Σ defects / Σ n` nos primeiros `baseline_lots` lotes válidos (padrão 20; se houver menos, usa todos).
- **Limites por lote:**
  - `ucl_i = min(1, p̄ + 3·√(p̄(1−p̄)/n_i))`
  - `lcl_i = max(0, p̄ − 3·√(p̄(1−p̄)/n_i))`
  - com `p̄ = 0` ou `p̄ = 1`, os limites são iguais a `p̄` (sem divisão por zero)
- **Fora de controle:** `out_of_control = p_i > ucl_i or p_i < lcl_i` (regra 1).
- **Menos de 2 lotes válidos:** `points = []` e `p_bar = null`, com `message` explicando.
- **Corte** (ADR-017, SPEC-026; a partir do merge dela). A resposta tem tamanho limitado, qualquer que seja a história:
  - `points` traz só os **últimos** `max_points` lotes válidos (parâmetro da rota de 2 a 500, padrão 100), em ordem crescente;
  - `p̄` continua sobre os **primeiros** `baseline_lots` lotes válidos da **história inteira** da consulta, mesmo que fiquem fora da janela. Mudar `max_points` não muda `p̄` nem os limites;
  - `excluded_lots` traz no máximo os 50 excluídos mais recentes (`MAX_EXCLUDED_LOTS`), em ordem crescente;
  - `valid_lots_total` e `excluded_lots_total` são as contagens antes do corte, e `max_points` repete o teto usado. Os três são opcionais (`null` numa resposta 0.2.0);
  - acima do teto, a rota corta e responde 200, nunca 422;
  - o corte é feito no SQL, com uma única agregação por requisição, e os desempates usam `lot_id collate "C"` (a ordem de `str` do Python).
- **Implementação:** funções puras em `qc_api.services.spc`: `compute_p_chart(lots, baseline_lots=20, min_lot_size=5, *, source, max_points=None, max_excluded=None)`, e, a partir da SPEC-026, `select_lots` (referência do corte) e `build_p_chart` (carta a partir da seleção). Todas têm testes unitários. O endpoint só faz a consulta (`lot_selection`, com o corte no SQL) e a serialização.

Resposta (com os campos da 0.3.0; `points` abreviado a 1 dos 100 itens de uma história com 130 lotes válidos):

```json
{
  "baseline_lots": 20, "min_lot_size": 5, "source": "live", "p_bar": 0.18,
  "points": [{"lot_id": "L-001", "started_at": "...", "ended_at": "...", "n": 25, "defects": 4,
              "p": 0.16, "cl": 0.18, "ucl": 0.41, "lcl": 0.0, "out_of_control": false}],
  "excluded_lots": [{"lot_id": "L-009", "n": 3}],
  "message": null,
  "max_points": 100, "valid_lots_total": 130, "excluded_lots_total": 1
}
```

## 4. API na nuvem (`/api/v1`)

| Método e rota | Auth | Descrição | SPEC |
|---|---|---|---|
| `GET /health` | — | `HealthResponse`: `{"status":"ok"|"degraded","db":"ok"|"error","api_version":...,"contract_version":...}`. Responde 200, ou **503** quando o banco falha. Faz `SELECT 1` no banco (o mesmo acesso mantém o Supabase acordado) | 004 |
| `POST /inspections` | dispositivo | Cria a inspeção (idempotente) | 004 |
| `POST /inspections/batch` | dispositivo | 1 a 100 inspeções, para o reenvio do outbox. Responde **200** com `BatchResult` | 004 |
| `GET /inspections` | leitura | Filtros `device_id`, `lot_id`, `object_type`, `grade`, `source`, `defective`, `from`, `to`; `limit` (padrão 50, máximo 500) e `offset`; ordem `inspected_at desc` | 005 |
| `GET /metrics/summary` | leitura | Mesmos filtros da listagem | 005 |
| `GET /metrics/timeseries` | leitura | `bucket=minute|hour|day` e filtros | 005 |
| `GET /metrics/spc` | leitura | `source`, `object_type` (opcional), `baseline_lots`, `min_lot_size`; `max_points` (2 a 500, padrão 100), com o corte do §3.4 | 006, 026 |
| `GET /lots` | leitura | `Page[LotSummary]`: lotes com `n`, `defects` e período | 005 |
| `POST /devices/{device_id}/heartbeat` | dispositivo | `HeartbeatCreate` → **204** sem corpo (a partir da SPEC-018). Um `UPDATE` da linha do dispositivo, sem histórico: grava `last_heartbeat_at = now()` e `last_seen_at = now()` (hora do servidor) e os campos do corpo; o `sent_at` da borda fica só para diagnóstico. `device_id` do caminho fora de `DEVICE_ID_PATTERN` ou corpo inválido → 422, sem o corpo no log | 018 |
| `GET /devices` | leitura | **200** `list[DeviceStatus]`, em ordem de `device_id`, no máximo 500 itens (a partir da SPEC-018). `online = last_heartbeat_at is not null and now() − last_heartbeat_at < 180 s`, pela hora do servidor em UTC; `last_source` pela inspeção de maior `received_at` | 018 |

**Alertas no Telegram** (a partir da SPEC-017; RF-17, sem rota nova e sem mudança de contrato). Um laço em segundo plano, desligado por padrão, avisa num chat do Telegram quando um lote concluído fica fora de controle (`qc_api.services.alerts`):
- **Laço:** com `ALERTS_ENABLED=true` e a configuração válida, o `lifespan` cria uma tarefa `asyncio` (`app.state.alerts_task`; `None` sem laço) que roda `run_check` numa thread (`asyncio.to_thread`) na subida e depois a cada `ALERTS_CHECK_INTERVAL_S`, nunca no caminho de uma requisição. Uma exceção na verificação é registrada só pela classe e pelo SQLSTATE (regra de erros de banco abaixo) e o laço continua. No encerramento, a tarefa é cancelada.
- **Regra:** por origem (`live` sempre; `simulated` só com `ALERTS_INCLUDE_SIMULATED=true`), a carta p do §3.4 com `baseline_lots=20` e `min_lot_size=5`, sem filtro de tipo, lida pela seleção limitada do ADR-017 com tetos inteiros (`max_points=3`, `max_excluded=0`, nunca `None`). Um ponto `out_of_control` gera alerta quando a última inspeção do lote (`ended_at`) tem pelo menos `ALERTS_LOT_IDLE_MINUTES` e no máximo `ALERTS_LOOKBACK_HOURS` em relação ao relógio do servidor (UTC). Pela ADR-021, só contam as inspeções com grau.
- **Deduplicação e teto:** a linha de `alerts_sent` (§5) é inserida **antes** do envio, com `INSERT … ON CONFLICT DO NOTHING RETURNING`; sem linha devolvida, o lote já foi tratado. A chave primária garante uma mensagem por lote também com mais de um worker do uvicorn, e um `pg_advisory_xact_lock` (de transação, válido no pooler em modo transaction) serializa a conferência do teto e a inserção, sem ficar preso durante o envio. Com `ALERTS_MAX_PER_HOUR` linhas criadas na última hora, o alerta é pulado sem linha, com um aviso que traz a contagem. No máximo uma tentativa por alerta: `delivered = true` só depois de o Telegram aceitar; uma falha fica `false` e não é repetida.
- **Envio:** `POST https://api.telegram.org/bot<token>/sendMessage` com `{"chat_id", "text"}` (texto puro em PT-BR, sem imagem, R-02; `[SIMULADO]` no início quando a origem é `simulated`, R-06), `httpx` síncrono com timeout **total** de 5 s (resolução de nome, conexão, cabeçalhos e corpo), `trust_env=False` e sem seguir redirecionamento. Sucesso só com HTTP 200 e `{"ok": true}`; o resto é falha registrada, e nunca afeta a ingestão. A partir da SPEC-017, o limite total é garantido assim: a requisição roda numa thread *daemon*, que é esperada por no máximo 5 s de relógio de parede e, depois disso, é abandonada e o envio conta como falha (`deadline exceeded`); no máximo uma thread abandonada fica viva por processo, porque, enquanto ela existir, a verificação para antes de reservar o próximo alerta.
- **Token (R-03):** o token vai só na URL do Telegram. Nunca aparece em log (um filtro nos loggers `httpx` e `httpcore` e nos filhos do `httpcore` troca o token e a parte depois de `:` por `***`), em resposta da API nem em mensagem de exceção registrada (as do `httpx` são registradas só pela classe). No `Settings`, o token é `SecretStr`.

**Configuração da API** (variáveis de ambiente; na VPS, no `infra/.env.api`; documentadas no `.env.example` e no `api/README.md`). Além de `DATABASE_URL` (§2) e `READ_API_KEY` (autenticação abaixo), a partir da SPEC-017:

| Variável | Padrão | Regra |
|---|---|---|
| `ALERTS_ENABLED` | `false` | booleano |
| `TELEGRAM_BOT_TOKEN` | vazio | obrigatória com os alertas ligados; `[0-9]{3,20}:[A-Za-z0-9_-]{20,100}` (casamento completo) |
| `TELEGRAM_CHAT_ID` | vazio | obrigatória com os alertas ligados; `-?[0-9]{1,20}` (casamento completo) |
| `ALERTS_LOT_IDLE_MINUTES` | `10` | inteiro de 1 a 1.440 |
| `ALERTS_LOOKBACK_HOURS` | `24` | inteiro de 1 a 168 |
| `ALERTS_CHECK_INTERVAL_S` | `60` | inteiro de 30 a 3.600 |
| `ALERTS_MAX_PER_HOUR` | `10` | inteiro de 1 a 60 |
| `ALERTS_INCLUDE_SIMULATED` | `false` | booleano |

As regras ficam fora do `Settings`, em `load_alert_config`, porque os alertas nunca podem impedir a API de subir: com `ALERTS_ENABLED=true` e alguma variável inválida (ou com o próprio `ALERTS_ENABLED` inválido), a API sobe normalmente, registra **um** erro `alerts disabled: invalid configuration (<nomes>)`, só com os nomes das variáveis e sem os valores, e não inicia o laço. Um número ou booleano vazio vale o padrão. No Render (reserva fria, que hiberna), os alertas só rodam enquanto a reserva está acordada (SPEC-017 §7).

**Autenticação** (header `X-API-Key`):
- **Dispositivo:** a chave é gerada por `scripts/register_device.py`. Só o hash SHA-256 fica na tabela `devices`, e a comparação usa `secrets.compare_digest`. O `device_id` do corpo precisa ser o dono da chave; caso contrário, retorna 403. No heartbeat (a partir da SPEC-018), a mesma regra vale para o `device_id` do caminho. A cada escrita, atualiza `devices.last_seen_at`.
- **Leitura:** chave única `READ_API_KEY` (variável de ambiente da API), usada pelo dashboard.
- Sem chave ou com chave inválida: 401.

**Outras proteções:** corpo limitado a 256 KB, CORS fechado (o dashboard chama do servidor, não do navegador) e documentação em `/docs`. Em produção, o `/docs` e o `/openapi.json` não são publicados, porque o Caddy só encaminha `/api/*` para a API (ADR-018); eles ficam acessíveis localmente. Um valor que o contrato aceita mas o banco recusa vira 422 `{"detail": "Value cannot be stored"}`, com `rollback` de tudo, e nunca 500:

- `psycopg.DataError` (SQLSTATE classe `22`, como o underflow das colunas `real` do §5), desde a SPEC-004;
- `psycopg.IntegrityError` (classe `23`, como uma `check` do banco mais estrita que o contrato depois de uma migração), a partir da SPEC-005. Hoje esse caminho é inalcançável, porque as `check` espelham o contrato (§5).

**Erros de banco no log** (regra para o servidor da API, `qc_api`; SEC-04-01 de `reviews/SPEC-004/r2-security-report.md`): de um `psycopg.Error`, o log registra só a rota, o `device_id` (quando houver), a classe da exceção e o SQLSTATE. Nunca `str(exc)`, `exc.diag.*` nem o traceback, que repete a mensagem: a mensagem do servidor pode trazer os valores da linha (`Failing row contains (...)`). Vale também para o 500 genérico (SPEC-005). Exceção aceita: o logger `psycopg.pool` da dependência, que registra falhas de conexão com o host, a porta e o usuário do pooler, sem a senha (SEC-04-05 do mesmo relatório). O `infra/migrate.py` não é servidor: roda só na máquina do humano e mostra o `DETAIL` do servidor (SPEC-015 §4.7).

## 5. Banco (Supabase Postgres)

```sql
devices(device_id text pk, api_key_hash text not null unique, created_at timestamptz not null default now(), last_seen_at timestamptz)
inspections(
  inspection_id uuid pk, device_id text not null fk→devices, lot_id text not null,
  inspected_at timestamptz not null, received_at timestamptz not null default now(),
  object_type text not null check(...), grade text null check(...),
  grade_score real, type_confidence real not null, grade_confidence real,
  needs_review boolean not null, model_version text not null, model_sha256 text not null,
  latency_ms integer not null, source text not null check(source in ('live','simulated')),
  is_defective boolean generated always as (coalesce(grade in ('poor','unusable'), false)) stored,
  check ((object_type = 'unknown') = (grade is null))
)
-- índices: (inspected_at), (lot_id), (source, inspected_at), (device_id)
-- a partir da SPEC-017 (migração 005):
alerts_sent(
  lot_id text not null check (lot_id ~ '^[A-Za-z0-9_-]{1,40}$'),
  source text not null check (source in ('live','simulated')),
  kind text not null check (kind in ('out_of_control')),
  created_at timestamptz not null default now(),
  delivered boolean not null default false,
  primary key (lot_id, source, kind)
)
-- índice: (created_at)
-- RLS habilitado em devices, inspections, schema_migrations e (a partir da SPEC-017) alerts_sent,
--   sem políticas e sem force
--   → as chaves anon/authenticated não leem nem escrevem nada; o dono (a API) não é afetado.
```

- **Restrições** (SPEC-003 §4.1): os `check` espelham os enums, as faixas e as regexes do contrato (defesa em profundidade). `inspections.device_id` é `not null`, porque o contrato o exige (SPEC_ISSUE-02 da SPEC-003, ratificado).
- **Restrições da `002`** (SPEC-027; a partir do merge dela): `model_version` com a regex do contrato; `inspection_id` com versão 4 e variante RFC 4122 (`UUID4` do pydantic); `inspected_at` e `received_at` na faixa do `datetime` do Python em UTC (`>= 0001-01-01 00:00:00+00` e `< 10000-01-01 00:00:00+00`, o que recusa `infinity`). Sem elas, uma linha gravada fora da API (SQL Editor, migração manual) derrubava a leitura com 500. A migração confere antes as linhas existentes e recusa, só com contagens na mensagem, se alguma violar as regras.
- **Restrições da `003`** (SPEC-016 §4.2, ADR-021; a partir da SPEC-016): o `check` de `object_type` aceita os 8 valores do `ObjectType` 0.4.0, e o `check ((object_type = 'unknown') = (grade is null))` do esquema acima é trocado pela invariante dos grupos de grau (§3.1): `screw`/`nut` com grau, `unknown` sem grau e as ferramentas manuais com ou sem grau. `is_defective` não muda.
- **Colunas da `004`** (`004_device_heartbeat.sql`, SPEC-018 §4.2; a partir da SPEC-018): `devices` ganha, todas anuláveis, `last_heartbeat_at timestamptz` (hora do servidor; decide o `online` do §4), `hb_sent_at timestamptz` (relógio da borda, só diagnóstico), `hb_model_version text`, `hb_model_sha256 text` e `hb_app_version text` (`check` com as regexes do contrato 0.5.0), `hb_uptime_s`, `hb_outbox_pending` e `hb_outbox_dead` (`integer`, `check (>= 0)`) e `check ((hb_model_version is null) = (hb_model_sha256 is null))`. Só o último heartbeat de cada dispositivo fica guardado (sem histórico).
- **Tabela da `005`** (`005_alerts.sql`, SPEC-017 §4.3; a partir da SPEC-017): `alerts_sent`, uma linha por alerta já tratado (`lot_id`, `source`, `kind`), inserida pela API **antes** do envio ao Telegram. A chave primária `(lot_id, source, kind)` é a deduplicação (uma mensagem por lote e origem, também com vários workers); a regex de `lot_id` espelha o `LOT_ID_PATTERN` do contrato, e `kind` aceita só `out_of_control`. `created_at` é o `now` da verificação (relógio do servidor em UTC, o mesmo das janelas do §4), e o índice em `created_at` serve à contagem do teto por hora a cada verificação. `delivered` só vira `true` depois de o Telegram aceitar a mensagem; uma falha fica `false` e não é repetida. RLS habilitado, sem políticas e sem `force`, como as demais tabelas. Sem chave estrangeira para `inspections`.
- **Colunas `real` (`float4`):** arredondam (ex.: `0.97` vira `0.9700000286`) e recusam com `22003` todo valor diferente de zero que arredonde para zero (abaixo de cerca de `7e-46`). A API converte esse erro em 422 (§4); a borda legítima não produz esses valores.
- **Grants do Supabase:** o RLS não cobre `TRUNCATE`, `REFERENCES` e `TRIGGER`. Projetos novos do Supabase deixaram de dar grants automáticos a `anon`/`authenticated` nas tabelas novas do `public` (changelog 45329, <https://supabase.com/changelog/45329-breaking-change-tables-not-exposed-to-data-and-graphql-api-automatically>, consultado em 2026-10-12), mas isso depende da opção escolhida na criação. A SPEC-015 (CA-14) confere os grants em produção e os revoga se existirem; o `revoke` não vai para uma migração, porque esses papéis não existem no Postgres local nem no do CI.

As migrações ficam em `infra/migrations/NNN_descricao.sql`, escritas para poder rodar de novo sem erro (`if not exists`). São aplicadas por `infra/migrate.py`, que registra cada uma em `schema_migrations` com um checksum (SPEC-003), pela conexão direta ou pelo pooler em modo session (§2, SPEC-015 §4.7); o SQL Editor do Supabase e o `psql` são a alternativa manual. A idempotência usa `INSERT ... ON CONFLICT (inspection_id) DO NOTHING RETURNING inspection_id`: sem linha retornada, a resposta é `duplicate`.

## 6. Gateway de borda (`qc-edge`)

### 6.1 Rotas na LAN

| Rota | Quem usa | Descrição |
|---|---|---|
| `GET /` | operador (navegador do notebook) | Console com QR code para `http://<ip-lan>:<porta>/capture?t=<token>`, status do modelo, tamanho do outbox, último envio, últimas inspeções. Só responde a cliente de loopback, sem headers de proxy e com `Host` de loopback (`127.0.0.1`, `localhost` ou `[::1]` na porta configurada, SPEC-025); senão, 403. Testes que chamam o console usam a URL base `http://127.0.0.1:<porta>` |
| `GET /capture?t=<token>` | celular | Página HTML/JS mínima: campo de lote, modo (inspeção/coleta), botão "Fotografar" (`<input type=file accept="image/*" capture="environment">`) e resultado. O JS redimensiona para no máximo 1280 px no lado maior e reencoda em JPEG (q=0,9) via canvas, o que também corrige a rotação EXIF |
| `POST /api/capture` | celular | `multipart/form-data`: `image` (JPEG/PNG; limites próprios da rota: ≤ 3 MiB e ≤ 4 M pixels, checados pelo cabeçalho antes de decodificar (SPEC-007 §4.7); depois, as regras do `qc_preprocess.load_image`: ≤ 40 M pixels, proporção ≤ 10:1, JPEG com ≤ 64 marcadores de scan; tudo dentro do limitador de decodificações, §9), `lot_id`, `mode`; no modo `collect`, também `item_id`, `object_type`, `grade`, `labeler`, `angle`. Header `X-Session-Token`. Responde com o resultado ou a confirmação da coleta |
| `GET /api/status` | console e celular | Modelo (versão, sha), outbox (pendentes), conectividade com a nuvem |
| `GET /live?t=<token>` e `POST /api/live/frame` | celular | Vídeo ao vivo com uma inspeção por peça estável; exige HTTPS na LAN (`EDGE_TLS_CERT`/`EDGE_TLS_KEY`, CA local do `mkcert`). A partir da SPEC-019 (Fase 3) |

**Sem modelo carregado** (`MODEL_DIR` vazio, por exemplo na S2, antes do primeiro treino): a borda sobe normalmente, o modo `collect` funciona e o modo `inspect` responde 503 com `{"detail": "model not loaded"}` (a página mostra o rótulo PT-BR). O stub de desenvolvimento (`--stub-model`, SPEC-007) **nunca** publica na nuvem: com ele, a borda usa o `InMemorySink` e não abre o outbox, então as inspeções do stub somem quando o processo termina e nenhuma subida posterior pode enviá-las (SPEC-009 §4.4, R-06).

**Token de sessão:** 32 bytes aleatórios (`secrets.token_urlsafe`), gerados na inicialização (ou via `EDGE_SESSION_TOKEN`) e comparados em tempo constante. Requisição sem token válido recebe 401. Em operação, `EDGE_SESSION_TOKEN` fica vazio, para que cada subida gere um token novo (SPEC-025).

### 6.2 Fluxo de uma inspeção

1. O celular envia a foto. A borda gera `inspection_id` e `inspected_at` (UTC).
2. `qc_preprocess.preprocess(image) → float32[1,3,224,224]`: RGB, resize do lado menor para 256 (bilinear), crop central de 224, /255 e normalização ImageNet (mean `0.485,0.456,0.406`, std `0.229,0.224,0.225`). Os parâmetros vêm do `preprocessing.json` do modelo.
3. O `onnxruntime` devolve `type_probs[T]` e `grade_probs[5]`, já em probabilidade (a conversão de logits/CORN fica **dentro** do grafo ONNX).
4. **Decisão** (os limiares vêm do `decision.json` do modelo, com override por env):
   - se `type = argmax(type_probs)` for `other`, ou se `max(type_probs) < type_threshold`, o resultado é `object_type = unknown`, e os campos `grade`, `grade_score` e `grade_confidence` ficam `null`;
   - se `grade_probs[unusable] ≥ unusable_threshold` (ajustado na validação para favorecer o recall de `unusable`), `grade = unusable`; caso contrário, `grade = argmax(grade_probs)`;
   - `grade_confidence = grade_probs[grade]` e `grade_score = Σ i·grade_probs[i]`;
   - `needs_review = type_confidence < type_threshold + 0.10 or (grade_confidence is not None and grade_confidence < grade_review_threshold)` (padrão 0,60);
   - depois de todas as comparações, que usam os valores brutos, `type_confidence` e `grade_confidence` são limitados a `[0, 1]` e `grade_score` a `[0, 4]`, as faixas do §3.2. O arredondamento do softmax em float32 pode dar `Σ i·p_i` um pouco acima de 4 (ex.: `p4 = 1.0` exato com `p3 ≈ 6e-8`), e o contrato recusaria a inspeção. O limite não muda nenhuma decisão (SPEC-008 §4.1, item 6).
5. A foto é salva em `EDGE_DATA_DIR/captures/AAAA-MM-DD/<inspection_id>.jpg`.
6. Monta o `InspectionCreate` e grava no **outbox** (SQLite) **antes** de responder. Com `--stub-model`, grava só em memória (§6.1).
7. Responde ao celular com o resultado e os rótulos PT-BR.
8. Um laço em segundo plano publica os pendentes com `HttpPublisher`:
   - em lotes de até 100 via `/inspections/batch`, timeout de 5 s;
   - backoff exponencial de 1 s até 60 s, com jitter;
   - marca como enviado ao receber `created` ou `duplicate`;
   - o timeout de 5 s vale por operação (conexão, escrita, cada leitura). A partir da SPEC-030, cada requisição tem também um prazo total de 15 s e lê no máximo 512 KiB de resposta (estourar vira retry), e um salto do relógio para trás não prende o retry nem o health check;
   - a partir da SPEC-020 (Fase 3), `EDGE_PUBLISHER=mqtt` troca o `HttpPublisher` por um `MqttPublisher` (Mosquitto só em loopback no notebook e uma ponte, `python -m qc_edge.mqtt_bridge`, que repassa à mesma rota HTTP); o item só vira enviado com a resposta da ponte, nunca pelo PUBACK;
   - um item recusado (413/422) vira `dead` e fica no arquivo. A partir da SPEC-034, `python -m qc_edge.requeue --outbox-path <arquivo> [--yes]` lista os `dead` e os devolve a `pending`, sem mudar o `payload` (a revalidação pelo contrato e a idempotência por `inspection_id` continuam). A partir da SPEC-038, uma linha com coluna fora do formato (editada à mão ou corrompida) vira `dead` no laço, com `last_error = invalid outbox row`, em vez de parar o envio dos outros itens, e a listagem a pula com um aviso que cita só o `rowid` e a coluna.

### 6.3 Modo coleta (montagem do dataset)

O operador escolhe `item_id`, `object_type`, `grade`, `labeler` e `angle` **antes** de fotografar. A borda:
- salva em `DATASET_DIR/raw/<object_type>/<grade>/<item_id>__<angle>__<timestamp>.jpg`;
- acrescenta uma linha a `DATASET_DIR/manifest.csv`.

Nada é enviado à nuvem e nenhuma inferência é feita. Formato do manifest em `docs/dataset-protocol.md`.

A partir da SPEC-025 (pendências da SPEC-010):
- o JPEG é gravado **sem** os segmentos APP1 (EXIF, XMP), APP13 (IPTC) e COM e sem nada depois do EOI, por varredura estrutural dos marcadores, sem reencodar (os pixels não mudam). Um JPEG com rotação EXIF (`Orientation` de 2 a 8) é recusado com 415, porque sem o APP1 o `qc_preprocess.load_image` deixaria de girá-lo (ADR-004); a página `/capture` nunca envia esse caso. As fotos de inspeção (`captures/`) continuam gravadas como chegaram, porque nunca saem do notebook;
- `python -m qc_edge.privacy --dataset-dir <D> [--fix]` confere (e corrige) as imagens já gravadas, e acusa sem corrigir o achado `orientation` (foto a refazer pela página); roda antes de cada backup do dataset no Drive (`docs/dataset-protocol.md` §8). A partir da SPEC-030, confere `.jpg` e `.jpeg` em qualquer caixa, acusa como `invalid` qualquer outro arquivo de `raw/` (exceto os temporários `.*.tmp` da borda), imprime os caminhos com os caracteres de controle escapados e lista o arquivo ilegível como `unreadable`;
- os diretórios recebem `fsync` depois do `rename` da imagem e da criação de diretórios, antes da linha do manifest;
- `notes` recusa as categorias Unicode `Cc`, `Cs`, `Cf`, `Zl` e `Zp`, e o `capture_device` troca esses caracteres por espaço antes do corte em 60.

O pipeline (SPEC-011) lê o manifest só com `csv`/`pandas`, acusa linha sem arquivo e arquivo sem linha, e aplica `exclusions.csv` (foto que precisa sair do dataset, como uma com pessoa; R-14).

**Importação de fotos que não vêm da página** (ADR-020; a partir das SPECs 035 e 036):
- `python -m qc_edge.importer --dataset-dir <D> --inbox <I> --plan <P> --privacy-checked [--dry-run]` lê arquivos de uma pasta de entrada fora de `DATASET_DIR` e um plano CSV preenchido pela dupla. Cada imagem é normalizada como a página faz (rotação EXIF aplicada, lado maior em até 1280 px, JPEG q=90, sem metadados) e gravada com o mesmo layout, o mesmo `flock`, as mesmas permissões e o mesmo `fsync` da coleta. Sem rede;
- o manifest não muda. A origem de cada imagem importada (`contributor` = foto de conhecido, `external` = imagem de dataset público) fica em `DATASET_DIR/sources.csv`; a imagem sem linha nele é `capture`. As fontes externas ficam no registro `ml/external_sources.csv` (no Git, sem imagens), com uma lista fechada de licenças;
- as imagens externas têm `item_id` `X<tipo>-NNNN` e vão sempre para o treino: o `qc_ml.split.rows_for` recusa uma delas em `val` ou `test`, e o split recusa mais de 30% delas no treino (padrão). A rota de coleta continua recusando esse `item_id`.

### 6.4 Configuração (`.env` da borda)

`EDGE_HOST` (0.0.0.0; só IPv4 literal, SPEC-025), `EDGE_PORT` (8000), `EDGE_DATA_DIR` (padrão `edge/data`, no `.gitignore`), `EDGE_SESSION_TOKEN` (opcional), `DEVICE_ID`, `DEVICE_API_KEY`, `CLOUD_API_URL`, `MODEL_DIR`, `DATASET_DIR`, `OUTBOX_PATH`, `TYPE_THRESHOLD`, `UNUSABLE_THRESHOLD`, `GRADE_REVIEW_THRESHOLD` (os três últimos são opcionais e sobrescrevem o `decision.json`). A partir da SPEC-018, `HEARTBEAT_INTERVAL_S` (padrão 60; inteiro de 10 a 3.600; `0` desliga; fora disso, a borda não sobe e sai com código 2): o `HeartbeatLoop` envia um `HeartbeatCreate` pelo `HttpPublisher` a cada intervalo, sem passar pelo outbox, e só é registrado nas mesmas condições do laço de publicação (sem `--stub-model`, com `DEVICE_API_KEY` e `CLOUD_API_URL`; R-06).

## 7. Modelo (`qc-ml`) — artefatos

Cada versão vive em `ml/models/<model_version>/`. **O nome do diretório é o `model_version`** enviado em cada inspeção (ex.: `partqc-mnv3-v1`). Se o `MODEL_DIR` da borda for um link simbólico, vale o nome do diretório alvo, não o do link (SPEC-008 §4.2). Os pesos não vão para o Git: `ml/models/**/*.onnx` está no `.gitignore`. Os JSONs e a fixture vão.

| Arquivo | Conteúdo |
|---|---|
| `model.onnx` | Entrada `image` float32 `[N,3,224,224]`; saídas `type_probs` `[N,T]` e `grade_probs` `[N,5]` |
| `model.sha256` | Hash do `model.onnx` (vai em cada inspeção) |
| `labels.json` | `{"object_types": ["screw","nut","other"], "grades": ["perfect","good","fair","poor","unusable"]}`. A partir da SPEC-016, também `ungraded_object_types` (lista opcional, padrão `[]`): os tipos que o modelo não gradua (ADR-021) |
| `preprocessing.json` | Saída de `PreprocessParams.to_json()`: `resize_shorter`, `crop`, `mean`, `std` |
| `decision.json` | `type_threshold`, `unusable_threshold`, `grade_review_threshold` (escolhidos na **validação**) |
| `metrics.json` | Métricas do teste final (ver a skill `ml-pipeline`). A partir da SPEC-035, `counts.<split>` traz também `by_origin` (`capture`, `contributor`, `external`) e `by_source`; `val` e `test` têm sempre 0 imagens externas (ADR-020) |
| `training_config.json` | Backbone, hiperparâmetros, seeds, versão do manifest, hash do split |
| `parity_fixture.npz` | Cerca de 8 entradas pré-processadas, geradas a partir de imagens **sintéticas** (nunca fotos reais no Git), e as saídas do torch, para o teste de paridade com ONNX sem precisar de torch |

Para distribuir o `model.onnx`, use um GitHub Release do repositório (anexo gratuito) ou copie manualmente para o notebook da borda.

**Exibição das métricas** (regra única para o CHANGELOG da SPEC-012 e para a página "Sobre o modelo" do dashboard, SPEC-028; RV-07 de `reviews/SPEC-013/r1-review-report.md`). O `metrics.json` guarda o valor bruto, nunca arredondado (R-11). Na exibição:
- 4 casas decimais e vírgula decimal, calculadas a partir de `Decimal(repr(valor))`;
- **nunca a favor da meta:** nas métricas em que menor é melhor (`grade_mae`, `false_unknown_rate`, `needs_review_rate`, `latency_ms_p50`, `latency_ms_p95`), arredondamento para cima (`ROUND_CEILING`); em todas as outras (acurácias, QWK, precisões, recalls, F1, `unknown_rate_on_other`), corte para baixo (`ROUND_FLOOR`);
- nos ICs 95% (`*_ci95`), `low` para baixo e `high` para cima (o intervalo exibido nunca fica mais estreito que o medido);
- inteiros (`support`, contagens, `latency_runs`) sem casas;
- o status em relação à meta (`atingida`/`abaixo da meta`) usa sempre o valor bruto.

Exemplos: `type_accuracy = 0.93127` → `0,9312`; `grade_mae = 0.12341` → `0,1235`. Uma métrica nova entra na lista de "menor é melhor" aqui, na SPEC-012 e no `model_info` do dashboard (que não importa `qc_ml`, R-12).

## 8. Rede e operação

- A borda escuta em `0.0.0.0:8000`. No Arch, libere a porta 8000/tcp no firewall ativo (ufw, firewalld ou nftables) **só para a sub-rede** da Wi-Fi de casa ou do hotspot, só durante a sessão, e desfaça a regra no fim. Não rode a borda com a porta aberta numa rede que não seja da dupla. Comandos no `edge/README.md` (SPEC-025).
- **Em casa (desenvolvimento e testes):** celular e notebook na mesma rede Wi-Fi.
- **Na apresentação (padrão):** o notebook se conecta ao **hotspot do celular** e o celular acessa o IP do notebook nessa rede. A rede fica sob controle da dupla, independente do Wi-Fi do campus (que pode isolar os clientes), e o notebook chega à nuvem pelos dados móveis.
- **Plano C:** **ancoragem USB** (USB tethering): o celular ligado ao notebook pelo cabo cria uma rede local entre os dois, e o celular acessa o IP do notebook nessa interface.
- **Túneis públicos (ex.: Cloudflare quick tunnel) são proibidos** para a captura, porque o tráfego, com as fotos, passaria pela infraestrutura do provedor e violaria a R-02.
- **Nuvem fora do ar:** a borda continua inspecionando e o outbox acumula. O console mostra `offline` e o número de pendentes.
- **Nuvem na VPS** (ADR-018, SPEC-015 §4.12 e §4.15; a partir da SPEC-039, ADR-023: **nenhum** serviço do PartQC publica portas, as portas 80/443 são do proxy do Coolify, a rede própria `partqc` sai, a API fica num recurso separado, ligada ao Caddy só pela rede `partqc-api-link`, "Connect to predefined network" fica desligado, e os passos humanos nunca reiniciam, param nem editam o `coolify-proxy`):
  - só o Caddy publica portas (80/tcp, 443/tcp e 443/udp); a API e o dashboard ficam só na rede `partqc` do compose, sem `ports`;
  - as portas publicadas pelo Docker passam por fora do `ufw`, por isso não publicar é a proteção real;
  - a VPS hospeda outros projetos do humano: os passos de firewall só conferem ou acrescentam regras, nunca apagam, reiniciam ou limpam (`ufw reset`, `prune`, `down -v`);
  - cada serviço tem `mem_limit` e `cpus` (padrões no `infra/.env`; API 512 MB).

## 9. Segurança (resumo; detalhes por SPEC)

| Ameaça | Mitigação |
|---|---|
| Alguém na LAN envia fotos falsas | Token de sessão no QR + 401 |
| Console (que exibe o token) exposto por proxy ou túnel indevido | Console só para loopback **e** 403 se houver headers de proxy (`X-Forwarded-For`, `CF-Connecting-IP`); uvicorn com `proxy_headers=False` (defesa em profundidade; túneis são proibidos pela §8) |
| Página hostil no navegador do notebook usa DNS rebinding para ler o token no console e injetar inspeções falsas | O console só responde com `Host` de loopback (`127.0.0.1`, `localhost` ou `[::1]` na porta configurada); senão, 403. Precisa estar `Done` antes do merge da SPEC-009, quando uma inspeção injetada chegaria à nuvem como `live` (SPEC-025; SEC-01 de `reviews/SPEC-007/r1-security-report.md`). As rotas com token não checam o `Host`: sem o token, nada é aceito |
| Porta da borda alcançada fora da rede da dupla (Wi-Fi do campus, bridges do Docker) | Regra de firewall só para a sub-rede da LAN ou do hotspot, só durante a sessão (§8); o token cobre o resto |
| Fotos lidas por outra conta local do notebook | `captures/` e `DATASET_DIR` com diretórios `0700` e arquivos `0600` (SPEC-025 e SPEC-010); retenção das fotos de inspeção em `docs/dataset-protocol.md` §9 (R-14) |
| Foto do dataset levando a localização (EXIF GPS), o aparelho ou um vídeo (Motion Photo) para o backup no Drive e o Colab, ou uma foto com pessoa no backup (SEC-10-01 e SEC-10-08 de `reviews/SPEC-010/r1-security-report.md`) | Modo coleta grava sem APP1, APP13, COM e trailer, e `python -m qc_edge.privacy` antes de cada backup (SPEC-025, `Done` antes do primeiro backup); remoção de foto com pessoa por `exclusions.csv`, inclusive do backup (`docs/dataset-protocol.md` §8 e §8.1, SPEC-011) |
| Foto recebida de um conhecido levando GPS, aparelho ou vídeo para o dataset e o backup, ou uma pessoa no quadro; imagem externa sem licença (ADR-020) | A importação reencoda sem metadados e confere o resultado, nunca lê fora da pasta de entrada, que fica fora do dataset e do backup, e exige `--privacy-checked` (checagem humana); fonte externa só com licença da lista e registrada (SPEC-036, SPEC-035; `docs/dataset-protocol.md` §10) |
| `API_BASE_URL` do dashboard com `http://` mandando a `READ_API_KEY` em claro (SEC-13-01 de `reviews/SPEC-013/r2-security-report.md`) | O dashboard recusa esquema que não seja `https://`, salvo `http://` em `localhost`/`127.0.0.1` (SPEC-028); em produção, o compose define `API_BASE_URL=https://${PUBLIC_HOST}` (SPEC-015 §4.12) |
| Chave de dispositivo vazada | Hash no banco; rotação por `register_device.py --rotate` |
| Leitura indevida pela chave anon do Supabase | RLS sem políticas; a API usa `DATABASE_URL` só no servidor |
| Payload malicioso | Pydantic com `extra="forbid"`, limites de tamanho e tipo de imagem validado pelo conteúdo (Pillow), não pela extensão. O `load_image` checa pelo cabeçalho, antes de decodificar, o limite de pixels (40 M) e de proporção (≤ 10:1), o que evita o OOM do resize (SPEC-023), e recusa JPEG com mais de 64 marcadores de scan (`FF DA`), o que limita a CPU gasta com scans progressivos repetidos (SPEC-024). Nenhum componente liga `PIL.ImageFile.LOAD_TRUNCATED_IMAGES`: o `load_image` se recusa a rodar com ela ligada, e a borda se recusa a subir (SPEC-007) |
| Muitos uploads simultâneos na borda (memória e CPU) | Toda chamada a `load_image` em `qc_edge` passa por um semáforo de decodificações (padrão 2, espera de 10 s, depois 503 `server busy`); vale para os modos `inspect` e `collect` (SPEC-007 §4.6, SPEC-010). Custo por slot no pior caso aceito: ~2,5 s de CPU e ~360 MB só com os limites do `load_image` (medido, SEC-24-02 de `reviews/SPEC-024/r1-security-report.md`); com os limites próprios da rota (3 MiB e 4 M pixels, SPEC-007 §4.7), **~4 s de CPU e ~90 MB acima da base (pico de 133 MB) medidos**, com os 2 slots serializados pelo GIL (~1 núcleo) (SEC-02 de `reviews/SPEC-007/r1-security-report.md`). A espera por um slot acontece no event loop e não ocupa thread do threadpool, que é compartilhado com o console e o `/api/status` (SPEC-025) |
| Valor aceito pelo contrato e recusado pelo banco | 422 com `rollback` para os SQLSTATE das classes `22` e `23` (§4); o publisher da borda isola o item por bissecção e o marca como `dead`, e do 422 registra só o status, o `detail` em texto ou a contagem de erros, nunca o corpo, que ecoa o `input` (SPEC-009) |
| Muitos lotes pequenos gravados com uma chave de dispositivo, e a carta p do dashboard passando dos 512 MB da API (`mem_limit` padrão na VPS e limite do Render, a reserva) (SEC-06-01 de `reviews/SPEC-006/r1-security-report.md`) | Corte da carta no SQL: no máximo 500 pontos e 50 excluídos por resposta (§3.4, ADR-017, SPEC-026); cache com TTL no dashboard (SPEC-013); `statement_timeout` no papel do banco para a parte do Postgres (SPEC-015) |
| Porta da API ou do dashboard exposta na VPS (o Docker publica por fora do `ufw`) | Só o Caddy tem `ports`; API e dashboard só com `expose` na rede do compose (SPEC-015 §4.12, CA-29 e CA-40). A partir da SPEC-039 (ADR-023): nenhum serviço tem `ports`, e só o `caddy` tem domínio no Coolify (SPEC-039 CA-01, CA-15 e CA-16) |
| Segredo da VPS (`infra/.env*`), `.git`, dados ou fotos embutidos numa imagem | Um `.dockerignore` por Dockerfile em `infra/docker/`, conferido com arquivos-sentinela no build (SPEC-015 §4.11, CA-36). A partir da SPEC-039, o mesmo cobre o `.env` que o Coolify grava em `infra/.env` dentro do contexto de build, os da API e do dashboard excluem `infra/` (onde o Coolify grava o compose processado), e o do Caddy só deixa entrar o Caddyfile (SPEC-039 CA-13) |
| `DATABASE_URL` ou `TELEGRAM_BOT_TOKEN` no ambiente do dashboard ou do Caddy: o Coolify entrega a todos os serviços de um recurso o `.env` com todas as variáveis de runtime dele, e o `environment` do compose não limita isso (SEC-39-01, a partir da SPEC-039) | Dois recursos no Coolify, `partqc-api` (só a API, com os segredos dela) e `partqc-web` (Caddy e dashboard, com `PUBLIC_HOST` e a `READ_API_KEY`); o `compose.yaml` não cita os nomes dos segredos da API; simulação no CI e `Config.Env` na VPS a cada atualização do Coolify (SPEC-039 CA-02, CA-19 e CA-20; ADR-023, emenda 1) |
| Healthcheck derrubando a rota pública: o Traefik do Coolify tira da rota um contêiner `unhealthy` (a partir da SPEC-039) | Só o `caddy` tem domínio, e ele não tem healthcheck; a API pode ficar `unhealthy` com o Supabase pausado sem tirar o painel do ar (ADR-023) |
| Rajada anônima ou DDoS contra a VPS, sem proteção de provedor nem limitação de taxa no Caddy padrão | Risco aceito no MVP; impacto nos outros projetos limitado por `mem_limit` e `cpus`; outbox na borda (SPEC-015 §4.8) |
| Subdomínio pessoal ou IP da VPS no repositório (R-13) | Marcador `<subdominio>` na documentação e `PUBLIC_HOST` só no `infra/.env` da VPS (SPEC-015 CA-30, CA-41 e CA-42). A partir da SPEC-039, `PUBLIC_HOST` e o domínio ficam só no painel do Coolify, e o CA-42 confere também o UUID do recurso |
| Linha fora do contrato gravada direto no banco (SQL Editor, migração manual) derrubando a leitura com 500 | `check` da migração `002` (§5, SPEC-027) |
| Vazamento de segredo no Git | `.gitignore`, `.env.example` e a busca do reviewer (R-03) |

**Ao subir a versão do Pillow no `uv.lock`** (qualquer SPEC; SEC-24-02, item c, de `reviews/SPEC-024/r1-security-report.md`): o limite de 64 scans foi medido com o Pillow 12.3.0, cujo libjpeg-turbo empacotado **não** decodifica JPEG com codificação aritmética (SOF9/SOF10). O `load_image` recusa esse JPEG com `InvalidImageError` em ~10 ms. Quem sobe o Pillow registra no dev-report o `PIL.features.version("libjpeg_turbo")` e confirma que um JPEG progressivo aritmético (gerado fora do repositório, por exemplo com `cjpeg -arithmetic -progressive`) continua recusado. O security-devops da SPEC confere. Se o JPEG passar a ser decodificado, o custo de scans sem dados pode subir: o limite tem de ser medido de novo, e isso vira uma SPEC do `qc-preprocess`.

## 10. Testes (regras do projeto)

- **Marcadores:** `db` (exige `TEST_DATABASE_URL`; sem ela, o teste é pulado, e no CI a sessão falha; SPEC-001 e SPEC-003), `acceptance`, `slow` e `docker`. O `docker` exige Docker com BuildKit e Compose v2, roda só com `PARTQC_DOCKER_TESTS=1` (senão, o teste é pulado) e é executado pelo workflow `docker`, e não pelo `ci` (SPEC-015 §4.14). A partir da SPEC-020, o `mqtt` exige o `mosquitto` instalado e roda só com `PARTQC_MQTT_TESTS=1` (senão, o teste é pulado), fora do CI.
- **Sem suíte dentro da suíte** (RV-01 e RV-03 de `reviews/SPEC-023/r1-review-report.md`):
  - Nenhum teste roda a suíte inteira em subprocesso (`pytest` sem caminhos, ou com um diretório inteiro de `testpaths`). Com k testes assim, cada um se protegendo só da própria recursão, a suíte roda muitas vezes por execução, e uma execução interna pode recriar o schema do banco de teste no meio da sessão externa.
  - Um CA do tipo "`ruff check`, `ruff format --check` e `pytest -q` terminam com código 0" é verificado pelo CI (R-09) e pela execução da suíte inteira que o tester já faz e registra no test-report. Ele não ganha teste automatizado: o test-report o marca como "verificado pela execução da suíte" e cita a contagem de testes. As SPECs novas não precisam escrever esse CA, porque a Definição de pronto já exige CI verde.
  - Um teste que precise rodar o pytest em subprocesso (ex.: as travas de banco da SPEC-001 e da SPEC-003) passa caminhos de arquivo explícitos, nunca inclui outro teste que rode pytest em subprocesso e, se usar o banco, usa um banco próprio (nome com `test`) ou não usa `migrated_db`.
  - Implementação: os dois testes que violavam a regra (CA-15 da SPEC-022 e CA-13 da SPEC-023) são removidos pelo tester da SPEC-004. O reviewer confere a regra em toda SPEC.
- **Expectativas de versão** (RV-04 de `reviews/SPEC-024/r1-review-report.md`). Sem esta regra, cada aumento de versão de um pacote obriga a reeditar o CA de versão de todas as SPECs anteriores, e a lista só cresce.
  - A versão **exata** de um pacote (`== "X.Y.Z"`) só aparece em dois lugares:
    - no `test_smoke.py` do autor, que o developer atualiza a cada aumento;
    - no teste de aceite da **SPEC vigente** do pacote (a que definiu a versão atual), dentro do `tests/acceptance/` do próprio pacote.
  - Todos os outros testes de aceite que tocam a versão de um pacote verificam só três coisas:
    1. a coerência `<mod>.__version__ == importlib.metadata.version("<dist>")`, escrita exatamente nessa forma;
    2. o formato `re.fullmatch(r"\d+\.\d+\.\d+", v)`;
    3. um piso com a mesma major: `piso <= tuple(int(p) for p in v.split(".")) < (major + 1, 0, 0)`. O piso é a versão que a SPEC do arquivo introduziu ou, se ela não mexeu no pacote, a que estava em vigor quando foi escrita. A comparação é por tupla, sem `packaging`, que é só uma dependência transitiva.
  - "O outro pacote não mudou" não vira teste de aceite. O reviewer confere no diff (`pyproject.toml`, `__init__.py` e `uv.lock`).
  - As docstrings de módulo dos testes citam no máximo a versão que a própria SPEC introduziu, nunca "a versão verificada agora".
  - **Quando uma SPEC aumenta a versão de um pacote:** o CA dela fixa a versão nova (exata). A §3.1 dela autoriza o tester a converter para a forma acima as asserções exatas desse pacote no arquivo de aceite da SPEC vigente anterior (um arquivo por pacote), e nada mais. Enquanto existir o CA-28 da SPEC-004 (`test_ca28_version_expectations_migrated`, em `api/tests/acceptance/test_spec_004.py`), que fixa em `ALLOWED_EXACT` o par arquivo/versão vigente de cada pacote e exige essas asserções em funções `test_ca01_*`, a mesma §3.1 autoriza trocar nesse conjunto o par do pacote pelo do arquivo novo, e o CA de versão da SPEC nova é o CA-01 (precedente: SPEC-026).
  - Implementação: migração única pelo tester da SPEC-004 (§3.1 e CA-28 dela). **Arquivos vigentes** (atualizado em 2026-10-17, RV-01 de `reviews/SPEC-026/r1-review-report.md`, em 2026-10-24, observação de `reviews/SPEC-016/r1-test-report.md`, e em 2026-10-25, observação de `reviews/SPEC-018/r1-test-report.md`): as asserções exatas ficam só em `packages/preprocess/tests/acceptance/test_spec_024.py` (`qc-preprocess` 0.3.0) e, a partir da SPEC-018, em `packages/contracts/tests/acceptance/test_spec_018.py` (`qc-contracts` 0.5.0; da SPEC-016 até a SPEC-018, `test_spec_016.py` com 0.4.0; até a SPEC-016, `test_spec_026.py` com 0.3.0). A fonte de verdade é o conjunto `ALLOWED_EXACT` do CA-28 da SPEC-004: quando ele muda, esta linha muda junto. O reviewer confere a regra em toda SPEC.
  - O ajuste do `ALLOWED_EXACT` vai **no mesmo commit** do tester que cria o arquivo de aceite que ele passa a citar; senão, o CA-28 falha num checkout isolado do commit intermediário e atrapalha o `git bisect` (RV-03 de `reviews/SPEC-026/r1-review-report.md`).
- **Testes de aceite de SPECs anteriores** (aprovada pelo humano em 2026-10-17; motivada pelo SPEC_ISSUE-01 de `reviews/SPEC-005/r1-dev-report.md` e pelo SPEC_ISSUE-01 de `reviews/SPEC-010/r1-dev-report.md`). Sem esta regra, toda SPEC que substitui de propósito um comportamento provisório de outra (um 501, uma opção desabilitada, uma rota ainda inexistente) trava o loop num SPEC_ISSUE só para autorizar o tester a mexer no arquivo de aceite antigo.
  - **Quando vale:** uma SPEC nova muda **de propósito** um comportamento que um teste de aceite de uma SPEC anterior verifica, e a mudança decorre de um requisito ou CA escrito na SPEC nova (por exemplo, "substitui o 501 da SPEC-007" ou "coleta habilitado").
  - **O que o tester da SPEC nova pode fazer:** ajustar, no arquivo de aceite da SPEC anterior, só as asserções afetadas, sem mudar a intenção dos CAs antigos. Isso inclui afrouxar ou trocar a asserção que verificava o comportamento substituído e restringir uma contagem ou busca à parte da página ou resposta que o CA antigo descrevia. Remover um teste inteiro só é permitido se for um teste extra, sem CA associado, cujo único objeto é o comportamento substituído; um teste `test_caNN_…` nunca é removido. Renomear um teste **extra** cujo nome descreve o comportamento substituído (ex.: `test_extra_collect_mode_is_501` → `test_extra_collect_mode_without_collect_fields_is_422`) faz parte do ajuste, desde que a renomeação conste na tabela do test-report; um `test_caNN_…` nunca é renomeado (RV-01 de `reviews/SPEC-010/r1-review-report.md`).
  - **O que o autor faz:** não edita `tests/acceptance/` (R-07) nem distorce a implementação para manter passando uma asserção que a SPEC nova invalidou. Ele lista no dev-report os testes antigos que falham e o requisito da SPEC nova que os invalida. Se a falha não for consequência direta de um requisito da SPEC nova, é bug da implementação, não ajuste.
  - **Registro no test-report:** uma tabela com uma linha por ajuste: arquivo, teste, asserção antes → depois e o requisito ou CA da SPEC nova que o motivou. O ajuste vai num commit do tester (`Agent: tester`), como o resto de `tests/acceptance/`.
  - **Conferência do reviewer:** cada linha da tabela é consequência direta do requisito citado, a intenção do CA antigo continua verificada e nenhuma outra linha do arquivo antigo mudou (conferido no diff). Um ajuste fora da tabela ou sem requisito que o justifique é achado bloqueante.
  - **Continua exigindo SPEC_ISSUE:** um ajuste que mude a intenção de um CA antigo (o que ele promete ao usuário ou ao contrato), que remova um teste de CA ou que não decorra de um requisito escrito na SPEC nova. Nesses casos, o architect corrige a SPEC nova ou a antiga.
  - **Relação com a §3.1:** quando o architect já sabe, ao escrever a SPEC nova, quais testes antigos ela invalida, ele os lista na §3.1 como aplicação explícita desta regra (como na SPEC-010), e o tester segue essa lista. A regra cobre os casos que a §3.1 não previu. As regras mais específicas desta seção (como as "Expectativas de versão" acima) prevalecem sobre esta.
