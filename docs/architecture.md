# Arquitetura

Fonte de verdade técnica do projeto. As SPECs detalham cada parte, mas **não podem contradizer** este documento sem um ADR.

## 1. Visão em 3 camadas (IoT: dispositivo → borda → nuvem)

```
┌─ DISPOSITIVO ─────────┐      ┌─ BORDA (notebook, LAN) ──────────────────────────┐      ┌─ NUVEM ──────────────────────────┐
│ Celular (navegador)   │      │ qc-edge (FastAPI, 0.0.0.0:8000)                  │      │ qc-api (FastAPI, Render)         │
│                       │ HTTP │  ├─ console do operador (QR de pareamento)       │HTTPS │  ├─ POST /api/v1/inspections     │
│ /capture              │─────►│  ├─ /api/capture: recebe a foto                  │─────►│  ├─ POST /api/v1/inspections/batch│
│  • foto (câmera nativa│      │  ├─ qc-preprocess (o mesmo do treino)            │      │  ├─ GET leituras, métricas, SPC  │
│  • lote, modo         │◄─────│  ├─ onnxruntime → probabilidades                 │      │  └─► Supabase Postgres (RLS)     │
│  • resultado na tela  │ JSON │  ├─ decisão (unknown / needs_review)             │      │                                  │
└───────────────────────┘      │  ├─ foto salva no disco local (nunca sobe)       │      │ qc-dashboard (Streamlit CC)      │
                               │  └─ outbox SQLite → HttpPublisher (retry)        │      │  └─ lê tudo via qc-api           │
                               └──────────────────────────────────────────────────┘      └──────────────────────────────────┘
                                                                                          scripts/simulate.py ─► qc-api (source=simulated)
```

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
| `api/` | `qc-api` (`qc_api`) | API na nuvem: ingestão, leitura, métricas, SPC | qc-contracts, fastapi, uvicorn, psycopg 3 (pool), pydantic-settings, httpx | torch, onnxruntime |
| `dashboard/` | `qc-dashboard` | Painel Streamlit | qc-contracts, streamlit, plotly, pandas, httpx | torch, onnxruntime, acesso direto ao banco |
| `ml/` | `qc-ml` (`qc_ml`) | Manifest, split, treino, avaliação, export ONNX, paridade | qc-contracts, qc-preprocess, numpy, pandas, scikit-learn, onnxruntime, pillow; **extra opcional `train`**: torch, torchvision, timm, onnx, coral-pytorch | — |
| `scripts/` | (scripts soltos, executados com o ambiente do `qc-api`) | `simulate.py`, `register_device.py`, `smoke_test.py` | httpx, qc-contracts, psycopg | — |
| `infra/` | — | `migrations/*.sql`, `render.yaml`, configs de deploy | — | segredos |

O acesso ao banco é feito com **psycopg 3 direto ao Postgres do Supabase** (connection string do pooler em modo transaction, guardada em `DATABASE_URL`, com `prepare_threshold=None`, porque esse modo não suporta prepared statements — ADR-006), e não pelo SDK `supabase-py`. Isso dá SQL explícito, transações e `ON CONFLICT` para a idempotência. A chave `service_role` não é necessária no MVP; se algum dia for, vale R-03.

## 3. Contrato v0 (`qc-contracts` 0.1.0)

### 3.1 Enums

| Enum | Valores (código) | Rótulo PT-BR |
|---|---|---|
| `ObjectType` | `screw`, `nut`, `unknown` | parafuso, porca, desconhecido |
| `Grade` (ordem = severidade 0..4) | `perfect`(0), `good`(1), `fair`(2), `poor`(3), `unusable`(4) | perfeito, bom, mediano, ruim, inutilizável |
| `Source` | `live`, `simulated` | real, simulado |
| `CaptureMode` (só borda) | `inspect`, `collect` | inspeção, coleta |

Expansões futuras de `ObjectType`, cada uma acompanhada de aumento de versão:
- **Fase 2:** `pliers`, `adjustable_wrench`, `allen_key`, `flat_screwdriver`, `phillips_screwdriver`.
- **Fase 3:** `angle_grinder`, `saw`, `drill`, `cordless_screwdriver`.

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
| `grade` | Grade \| null | `null` **se e somente se** `object_type == unknown` |
| `grade_score` | float \| null | 0–4, valor esperado Σ i·p(i); `null` quando `grade` é `null` |
| `type_confidence` | float | 0–1 |
| `grade_confidence` | float \| null | 0–1; `null` quando `grade` é `null` |
| `needs_review` | bool | sinalização da borda (confiança baixa) |
| `model_version` | str | `^[a-z0-9.-]{3,40}$`, ex.: `partqc-mnv3-v1` |
| `model_sha256` | str | 64 caracteres hexadecimais |
| `latency_ms` | int | ≥ 0 (pré-processamento + inferência) |
| `source` | Source | |

Campos extras são rejeitados (`extra="forbid"`).

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
- Erros: `{"detail": ...}` no formato padrão do FastAPI, sem stack trace.

### 3.4 SPC — carta p por lote (ADR-013)

- **Subgrupo:** `lot_id`. Os lotes são ordenados pelo menor `inspected_at`.
- **Registros considerados:** `object_type != unknown` e `source` filtrado (padrão `live`).
- **Por lote:** `n` = número de inspeções, `defects` = número de defeituosas, `p = defects / n`.
- **Lotes excluídos:** com `n < min_lot_size` (padrão 5). Saem do cálculo e são listados em `excluded_lots`.
- **Linha central:** `p̄ = Σ defects / Σ n` nos primeiros `baseline_lots` lotes válidos (padrão 20; se houver menos, usa todos).
- **Limites por lote:**
  - `ucl_i = min(1, p̄ + 3·√(p̄(1−p̄)/n_i))`
  - `lcl_i = max(0, p̄ − 3·√(p̄(1−p̄)/n_i))`
  - com `p̄ = 0` ou `p̄ = 1`, os limites são iguais a `p̄` (sem divisão por zero)
- **Fora de controle:** `out_of_control = p_i > ucl_i or p_i < lcl_i` (regra 1).
- **Menos de 2 lotes válidos:** `points = []` e `p_bar = null`, com `message` explicando.
- **Implementação:** função pura `qc_api.services.spc.compute_p_chart(lots, baseline_lots=20, min_lot_size=5, *, source)`, com testes unitários. O endpoint só faz a consulta e a serialização.

Resposta:

```json
{
  "baseline_lots": 20, "min_lot_size": 5, "source": "live", "p_bar": 0.18,
  "points": [{"lot_id": "L-001", "started_at": "...", "ended_at": "...", "n": 25, "defects": 4,
              "p": 0.16, "cl": 0.18, "ucl": 0.41, "lcl": 0.0, "out_of_control": false}],
  "excluded_lots": [{"lot_id": "L-009", "n": 3}],
  "message": null
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
| `GET /metrics/spc` | leitura | `source`, `object_type` (opcional), `baseline_lots`, `min_lot_size` | 006 |
| `GET /lots` | leitura | `Page[LotSummary]`: lotes com `n`, `defects` e período | 005 |

**Autenticação** (header `X-API-Key`):
- **Dispositivo:** a chave é gerada por `scripts/register_device.py`. Só o hash SHA-256 fica na tabela `devices`, e a comparação usa `secrets.compare_digest`. O `device_id` do corpo precisa ser o dono da chave; caso contrário, retorna 403. A cada escrita, atualiza `devices.last_seen_at`.
- **Leitura:** chave única `READ_API_KEY` (variável de ambiente da API), usada pelo dashboard.
- Sem chave ou com chave inválida: 401.

**Outras proteções:** corpo limitado a 256 KB, CORS fechado (o dashboard chama do servidor, não do navegador) e documentação em `/docs`.

## 5. Banco (Supabase Postgres)

```sql
devices(device_id text pk, api_key_hash text not null, created_at timestamptz default now(), last_seen_at timestamptz)
inspections(
  inspection_id uuid pk, device_id text fk→devices, lot_id text not null,
  inspected_at timestamptz not null, received_at timestamptz not null default now(),
  object_type text not null check(...), grade text null check(...),
  grade_score real, type_confidence real not null, grade_confidence real,
  needs_review boolean not null, model_version text not null, model_sha256 text not null,
  latency_ms integer not null, source text not null check(source in ('live','simulated')),
  is_defective boolean generated always as (coalesce(grade in ('poor','unusable'), false)) stored,
  check ((object_type = 'unknown') = (grade is null))
)
-- índices: (inspected_at), (lot_id), (source, inspected_at), (device_id)
-- RLS habilitado nas duas tabelas, sem políticas → as chaves anon/authenticated não leem nada.
```

As migrações ficam em `infra/migrations/NNN_descricao.sql`, escritas para poder rodar de novo sem erro (`if not exists`). São aplicadas por `infra/migrate.py`, que registra cada uma em `schema_migrations` com um checksum (SPEC-003); o SQL Editor do Supabase e o `psql` são a alternativa manual. A idempotência usa `INSERT ... ON CONFLICT (inspection_id) DO NOTHING RETURNING inspection_id`: sem linha retornada, a resposta é `duplicate`.

## 6. Gateway de borda (`qc-edge`)

### 6.1 Rotas na LAN

| Rota | Quem usa | Descrição |
|---|---|---|
| `GET /` | operador (navegador do notebook) | Console com QR code para `http://<ip-lan>:<porta>/capture?t=<token>`, status do modelo, tamanho do outbox, último envio, últimas inspeções |
| `GET /capture?t=<token>` | celular | Página HTML/JS mínima: campo de lote, modo (inspeção/coleta), botão "Fotografar" (`<input type=file accept="image/*" capture="environment">`) e resultado. O JS redimensiona para no máximo 1280 px no lado maior e reencoda em JPEG (q=0,9) via canvas, o que também corrige a rotação EXIF |
| `POST /api/capture` | celular | `multipart/form-data`: `image` (JPEG/PNG, ≤ 10 MB), `lot_id`, `mode`; no modo `collect`, também `item_id`, `object_type`, `grade`, `labeler`, `angle`. Header `X-Session-Token`. Responde com o resultado ou a confirmação da coleta |
| `GET /api/status` | console e celular | Modelo (versão, sha), outbox (pendentes), conectividade com a nuvem |

**Sem modelo carregado** (`MODEL_DIR` vazio, por exemplo na S2, antes do primeiro treino): a borda sobe normalmente, o modo `collect` funciona e o modo `inspect` responde 503 com `{"detail": "model not loaded"}` (a página mostra o rótulo PT-BR). O stub de desenvolvimento (`--stub-model`, SPEC-007) **nunca** publica na nuvem.

**Token de sessão:** 32 bytes aleatórios (`secrets.token_urlsafe`), gerados na inicialização (ou via `EDGE_SESSION_TOKEN`) e comparados em tempo constante. Requisição sem token válido recebe 401.

### 6.2 Fluxo de uma inspeção

1. O celular envia a foto. A borda gera `inspection_id` e `inspected_at` (UTC).
2. `qc_preprocess.preprocess(image) → float32[1,3,224,224]`: RGB, resize do lado menor para 256 (bilinear), crop central de 224, /255 e normalização ImageNet (mean `0.485,0.456,0.406`, std `0.229,0.224,0.225`). Os parâmetros vêm do `preprocessing.json` do modelo.
3. O `onnxruntime` devolve `type_probs[T]` e `grade_probs[5]`, já em probabilidade (a conversão de logits/CORN fica **dentro** do grafo ONNX).
4. **Decisão** (os limiares vêm do `decision.json` do modelo, com override por env):
   - se `type = argmax(type_probs)` for `other`, ou se `max(type_probs) < type_threshold`, o resultado é `object_type = unknown`, e os campos `grade`, `grade_score` e `grade_confidence` ficam `null`;
   - se `grade_probs[unusable] ≥ unusable_threshold` (ajustado na validação para favorecer o recall de `unusable`), `grade = unusable`; caso contrário, `grade = argmax(grade_probs)`;
   - `grade_confidence = grade_probs[grade]` e `grade_score = Σ i·grade_probs[i]`;
   - `needs_review = type_confidence < type_threshold + 0.10 or (grade_confidence is not None and grade_confidence < grade_review_threshold)` (padrão 0,60).
5. A foto é salva em `EDGE_DATA_DIR/captures/AAAA-MM-DD/<inspection_id>.jpg`.
6. Monta o `InspectionCreate` e grava no **outbox** (SQLite) **antes** de responder.
7. Responde ao celular com o resultado e os rótulos PT-BR.
8. Um laço em segundo plano publica os pendentes com `HttpPublisher`:
   - em lotes de até 100 via `/inspections/batch`, timeout de 5 s;
   - backoff exponencial de 1 s até 60 s, com jitter;
   - marca como enviado ao receber `created` ou `duplicate`.

### 6.3 Modo coleta (montagem do dataset)

O operador escolhe `item_id`, `object_type`, `grade`, `labeler` e `angle` **antes** de fotografar. A borda:
- salva em `DATASET_DIR/raw/<object_type>/<grade>/<item_id>__<angle>__<timestamp>.jpg`;
- acrescenta uma linha a `DATASET_DIR/manifest.csv`.

Nada é enviado à nuvem e nenhuma inferência é feita. Formato do manifest em `docs/dataset-protocol.md`.

### 6.4 Configuração (`.env` da borda)

`EDGE_HOST` (0.0.0.0), `EDGE_PORT` (8000), `EDGE_DATA_DIR` (padrão `edge/data`, no `.gitignore`), `EDGE_SESSION_TOKEN` (opcional), `DEVICE_ID`, `DEVICE_API_KEY`, `CLOUD_API_URL`, `MODEL_DIR`, `DATASET_DIR`, `OUTBOX_PATH`, `TYPE_THRESHOLD`, `UNUSABLE_THRESHOLD`, `GRADE_REVIEW_THRESHOLD` (os três últimos são opcionais e sobrescrevem o `decision.json`).

## 7. Modelo (`qc-ml`) — artefatos

Cada versão vive em `ml/models/<model_version>/`. **O nome do diretório é o `model_version`** enviado em cada inspeção (ex.: `partqc-mnv3-v1`). Os pesos não vão para o Git: `ml/models/**/*.onnx` está no `.gitignore`. Os JSONs e a fixture vão.

| Arquivo | Conteúdo |
|---|---|
| `model.onnx` | Entrada `image` float32 `[N,3,224,224]`; saídas `type_probs` `[N,T]` e `grade_probs` `[N,5]` |
| `model.sha256` | Hash do `model.onnx` (vai em cada inspeção) |
| `labels.json` | `{"object_types": ["screw","nut","other"], "grades": ["perfect","good","fair","poor","unusable"]}` |
| `preprocessing.json` | Saída de `PreprocessParams.to_json()`: `resize_shorter`, `crop`, `mean`, `std` |
| `decision.json` | `type_threshold`, `unusable_threshold`, `grade_review_threshold` (escolhidos na **validação**) |
| `metrics.json` | Métricas do teste final (ver a skill `ml-pipeline`) |
| `training_config.json` | Backbone, hiperparâmetros, seeds, versão do manifest, hash do split |
| `parity_fixture.npz` | Cerca de 8 entradas pré-processadas, geradas a partir de imagens **sintéticas** (nunca fotos reais no Git), e as saídas do torch, para o teste de paridade com ONNX sem precisar de torch |

Para distribuir o `model.onnx`, use um GitHub Release do repositório (anexo gratuito) ou copie manualmente para o notebook da borda.

## 8. Rede e operação

- A borda escuta em `0.0.0.0:8000`. No Arch, libere a porta 8000/tcp no firewall ativo (ufw, firewalld ou nftables).
- **Em casa (desenvolvimento e testes):** celular e notebook na mesma rede Wi-Fi.
- **Na apresentação (padrão):** o notebook se conecta ao **hotspot do celular** e o celular acessa o IP do notebook nessa rede. A rede fica sob controle da dupla, independente do Wi-Fi do campus (que pode isolar os clientes), e o notebook chega à nuvem pelos dados móveis.
- **Plano C:** **ancoragem USB** (USB tethering): o celular ligado ao notebook pelo cabo cria uma rede local entre os dois, e o celular acessa o IP do notebook nessa interface.
- **Túneis públicos (ex.: Cloudflare quick tunnel) são proibidos** para a captura, porque o tráfego, com as fotos, passaria pela infraestrutura do provedor e violaria a R-02.
- **Nuvem fora do ar:** a borda continua inspecionando e o outbox acumula. O console mostra `offline` e o número de pendentes.

## 9. Segurança (resumo; detalhes por SPEC)

| Ameaça | Mitigação |
|---|---|
| Alguém na LAN envia fotos falsas | Token de sessão no QR + 401 |
| Console (que exibe o token) exposto por proxy ou túnel indevido | Console só para loopback **e** 403 se houver headers de proxy (`X-Forwarded-For`, `CF-Connecting-IP`); uvicorn com `proxy_headers=False` (defesa em profundidade; túneis são proibidos pela §8) |
| Chave de dispositivo vazada | Hash no banco; rotação por `register_device.py --rotate` |
| Leitura indevida pela chave anon do Supabase | RLS sem políticas; a API usa `DATABASE_URL` só no servidor |
| Payload malicioso | Pydantic com `extra="forbid"`, limites de tamanho e tipo de imagem validado pelo conteúdo (Pillow), não pela extensão |
| Vazamento de segredo no Git | `.gitignore`, `.env.example` e a busca do reviewer (R-03) |
