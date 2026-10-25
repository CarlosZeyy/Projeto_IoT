# SPEC-018: Fase 2 — heartbeat e página de dispositivos

| Campo | Valor |
|---|---|
| Status | In Review |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | contrato, security |
| Depende de | SPEC-034 (`Done` antes de esta entrar em `In Dev`: mudança de contrato com a borda em operação), SPEC-016 (contrato 0.4.0; esta SPEC leva a 0.5.0), SPEC-030 (prazo e teto do publisher) (e SPEC-004, SPEC-009, SPEC-013, SPEC-028) |
| Semana alvo | S6 |
| Requisitos cobertos | RF-18; PRD §4.2; R-02, R-03, R-04, R-06, R-12 |
| ADRs relevantes | ADR-002, ADR-006, ADR-007, ADR-009, ADR-018 |

> **Aprovada pelo humano em 2026-10-24** (PR #45), no pacote das Fases 2 e 3, com os ADRs 021 e 022 `Aceito`. Revista pelo architect em 2026-10-24 (ver o Histórico). A mudança de contrato é **minor** (schemas novos, nenhum campo existente muda), então pede a SPEC aprovada com a tag `contrato`, sem ADR obrigatório (R-04 e skill `contrato-api`).

## 1. Contexto

Hoje a nuvem só sabe que a borda existe quando chega uma inspeção (`devices.last_seen_at`, `docs/architecture.md` §4). Telemetria de saúde do gateway (modelo carregado, fila pendente, itens `dead`, tempo ligado) é típica de IoT e ajuda na demo e na operação. Desde o ADR-018, a API fica sempre ligada na VPS, e o heartbeat não tem efeito de custo (R-01).

## 2. Objetivo

A borda envia um heartbeat a cada 60 s, e a página "Dispositivos" do dashboard mostra cada dispositivo como online (último heartbeat recebido há menos de 180 s) ou offline, com o estado do gateway e a origem dos dados dele.

## 3. Escopo

### 3.1 Dentro

- `packages/contracts`: `qc-contracts` **0.5.0** com `HeartbeatCreate` e `DeviceStatus` (§4.1).
- `infra/migrations/NNN_device_heartbeat.sql` (próximo número livre) (§4.2).
- `api/`: `POST /api/v1/devices/{device_id}/heartbeat` e `GET /api/v1/devices` (§4.3).
- `edge/`: `HttpPublisher.send_heartbeat` em `qc_edge/publisher.py` e o laço `HeartbeatLoop` (§4.4).
- `dashboard/`: página "Dispositivos" (`dashboard/views/dispositivos.py`), o método do cliente e a formatação (§4.5).
- `.env.example` (`HEARTBEAT_INTERVAL_S`), `edge/README.md` e `packages/contracts/README.md`.
- Testes do autor (fora de `acceptance/`).
- **Tester:** `packages/contracts/tests/acceptance/test_spec_018.py`, `api/tests/acceptance/test_spec_018.py`, `edge/tests/acceptance/test_spec_018.py` e `dashboard/tests/acceptance/test_spec_018.py`.
- **Tester, ajuste de aceite antigo** ("Expectativas de versão" de `docs/architecture.md` §10): as asserções exatas de `0.4.0` em `packages/contracts/tests/acceptance/test_spec_016.py` viram a forma de piso, e o par do `qc-contracts` no `ALLOWED_EXACT` do CA-28 da SPEC-004 passa a apontar para `test_spec_018.py` com `0.5.0`, no mesmo commit.

### 3.2 Fora

- Histórico de heartbeats e gráficos de saúde.
- Alerta de dispositivo offline (poderia estender a SPEC-017).
- Heartbeat por MQTT (SPEC-020 §3.2).
- Heartbeat do simulador: o simulador (SPEC-014) não envia heartbeat; a página mostra a origem pelos dados (§4.3).

## 4. Requisitos detalhados

### 4.1 Contrato `qc-contracts` 0.5.0

```python
class HeartbeatCreate(BaseModel):          # extra="forbid"
    sent_at: UtcDatetime                   # com fuso; no máximo 5 min no futuro (MAX_FUTURE_SKEW)
    model_version: ModelVersion | None     # None = borda sem modelo carregado
    model_sha256: Sha256Hex | None         # nulo se e somente se model_version é nulo
    app_version: str                       # re.fullmatch(r"[0-9A-Za-z.+-]{1,40}")
    uptime_s: int                          # 0 a MAX_HEARTBEAT_COUNT
    outbox_pending: int                    # 0 a MAX_HEARTBEAT_COUNT
    outbox_dead: int                       # 0 a MAX_HEARTBEAT_COUNT

class DeviceStatus(_ResponseModel):        # extra="ignore"
    device_id: str
    last_seen_at: UtcDatetime | None
    last_heartbeat_at: UtcDatetime | None  # hora do servidor ao receber o heartbeat
    online: bool
    model_version: str | None
    model_sha256: str | None
    app_version: str | None
    uptime_s: int | None
    outbox_pending: int | None
    outbox_dead: int | None
    last_source: Source | None             # origem da inspeção mais recente do dispositivo
```

- `MAX_HEARTBEAT_COUNT = 2_147_483_647` (o limite da coluna `integer`, como o `MAX_LATENCY_MS`).
- Regex pública nova `APP_VERSION_PATTERN = r"^[0-9A-Za-z.+-]{1,40}$"`, usada com `re.fullmatch` fora dos schemas (`docs/architecture.md` §3.2).
- `__version__ = "0.5.0"`, `pyproject.toml` e histórico do `README.md`. Nenhum schema existente muda.

### 4.2 Banco

Migração que acrescenta a `devices`, todas anuláveis: `last_heartbeat_at timestamptz`, `hb_sent_at timestamptz`, `hb_model_version text` (`check` com a regex do contrato), `hb_model_sha256 text` (`check` com a regex), `hb_app_version text` (`check` com a regex), `hb_uptime_s integer check (>= 0)`, `hb_outbox_pending integer check (>= 0)`, `hb_outbox_dead integer check (>= 0)`, e `check ((hb_model_version is null) = (hb_model_sha256 is null))`. Um heartbeat é um `UPDATE` da linha do dispositivo (sem histórico).

### 4.3 API

| Rota | Auth | Resposta |
|---|---|---|
| `POST /api/v1/devices/{device_id}/heartbeat` | dispositivo (`X-API-Key`) | **204** sem corpo |
| `GET /api/v1/devices` | leitura (`READ_API_KEY`) | **200** `list[DeviceStatus]`, em ordem de `device_id`, no máximo 500 itens |

- `device_id` do caminho fora de `DEVICE_ID_PATTERN` → 422. Sem chave ou chave inválida → 401. Chave válida de outro dispositivo → 403. Corpo inválido (inclusive campo extra) → 422, sem registrar o corpo no log (regra da SPEC-004). Mesma comparação em tempo constante e mesmo limite de corpo da SPEC-004.
- O heartbeat grava `last_heartbeat_at = now()` e `last_seen_at = now()` (hora do servidor), mais os campos do corpo. O `sent_at` da borda é guardado só para diagnóstico.
- `online = last_heartbeat_at is not null and now() − last_heartbeat_at < 180 s`, calculado no servidor, em UTC.
- `last_source`: o `source` da inspeção com o maior `received_at` do dispositivo, ou `null` sem inspeção. Erros de banco seguem a regra de log de `docs/architecture.md` §4.
- Sem limitação de taxa própria: cada heartbeat é autenticado e custa um `UPDATE`, como uma inspeção (risco aceito, igual ao da SPEC-004).

### 4.4 Borda

- `HttpPublisher.send_heartbeat(heartbeat: HeartbeatCreate) -> None` em `qc_edge/publisher.py`, o único módulo da borda que importa `httpx` (SPEC-009 §4.2): `POST {base_url}/api/v1/devices/{device_id}/heartbeat`, com o timeout de 5 s, o prazo total de 15 s e o teto de 512 KiB da SPEC-030. 204 → sucesso; 401/403 → `PublishAuthError`; qualquer outro resultado → `PublishTransientError` (com o resumo da SPEC-009, nunca o corpo).
- `HeartbeatLoop` (implementa o `BackgroundService` da SPEC-007): a cada `HEARTBEAT_INTERVAL_S` (padrão 60; inteiro de 10 a 3.600; `0` desliga), monta o `HeartbeatCreate` (modelo carregado ou `None`; `app_version = qc_edge.__version__`; `uptime_s` pelo relógio monotônico desde a subida, limitado a `MAX_HEARTBEAT_COUNT`; `outbox_pending` e `outbox_dead` do `SinkStats`) e envia.
- O heartbeat **não** passa pelo outbox: falha de envio vira um `WARNING` com o resumo e o laço segue. `PublishAuthError` → um `ERROR` único e o laço para até a próxima subida, como o `PublishLoop` (SPEC-009 §4.3).
- O laço só é registrado nas mesmas condições do `PublishLoop` (sem `--stub-model`, com `DEVICE_API_KEY` e `CLOUD_API_URL`; SPEC-009 §4.4). Com `--stub-model`, nunca há heartbeat (R-06).
- Corpo sem imagem nem dado pessoal (R-02).

### 4.5 Dashboard

- Cliente: `devices() -> list[DeviceStatus]`, lido com o mesmo cache das outras leituras (`CACHE_TTL_SECONDS`, `CACHE_MAX_ENTRIES`).
- Página "Dispositivos", com a tabela de colunas `Dispositivo`, `Situação` (`online`/`offline`), `Origem` (`real`, `simulado` ou `—`, pelo `SOURCE_LABELS_PT`), `Último sinal` (hora local, ou `nunca`), `Modelo`, `Versão`, `Pendentes`, `Com falha` e `Ligado há` (ex.: `2 h 05 min`; `—` sem heartbeat). Função pura `formatting.device_rows(items) -> list[dict[str, str]]`.
- Um dispositivo com `last_source = simulated` aparece com o selo de simulado já usado nas outras páginas (R-06).

## 5. Critérios de aceite

Contexto comum: banco de teste do marcador `db`; dispositivos registrados pelo teste (`edge-01` e `sim-01`); relógio do servidor controlável no teste (ou `last_heartbeat_at` ajustado direto no banco).

- **CA-01 (contrato)** — *Dado* `qc_contracts`, *então* `__version__ == importlib.metadata.version("qc-contracts") == "0.5.0"`; um `HeartbeatCreate` válido faz ida e volta por `model_dump_json`/`model_validate_json`; e são recusados com `ValidationError`, em casos separados: campo extra, `uptime_s=-1`, `outbox_pending=2_147_483_648`, `app_version="1.0\n"`, `sent_at` sem fuso, `sent_at` 6 min no futuro e `model_version` preenchido com `model_sha256` nulo.
- **CA-02 (escrita)** — *Dado* `edge-01` registrado, *quando* faz `POST /api/v1/devices/edge-01/heartbeat` com a própria chave e `outbox_pending=3`, *então* a resposta é 204 sem corpo, e `GET /api/v1/devices` (chave de leitura) devolve `edge-01` com `online == true`, `outbox_pending == 3` e `last_heartbeat_at` não nulo.
- **CA-03 (autenticação e entrada)** — *Dado* a chave de `edge-01`, *quando* envia o heartbeat para `/api/v1/devices/sim-01/heartbeat`, *então* 403; sem chave, 401; com chave inválida, 401; com um campo extra no corpo, 422; com `device_id` `EDGE_01` no caminho, 422; e o log capturado não contém o corpo enviado.
- **CA-04 (online e offline)** — *Dado* o `last_heartbeat_at` de `edge-01` igual a `now − 179 s`, *quando* `GET /api/v1/devices` é chamado, *então* `online == true`; com `now − 181 s`, `online == false`; e um dispositivo sem heartbeat tem `online == false` e `last_heartbeat_at == null`.
- **CA-05 (origem, R-06)** — *Dado* `edge-01` com uma inspeção `simulated` recebida antes de uma `live`, `sim-01` com só inspeções `simulated` e `edge-02` sem inspeção, *quando* `GET /api/v1/devices` é chamado, *então* `last_source` é `live` em `edge-01` (a mais recente), `simulated` em `sim-01` e `null` em `edge-02`.
- **CA-06 (leitura sem chave)** — *Dado* `GET /api/v1/devices` sem a chave de leitura, ou com uma chave de dispositivo, *então* 401.
- **CA-07 (banco)** — *Dado* as migrações aplicadas, *quando* o teste grava direto em `devices` `hb_uptime_s = -1`, ou `hb_model_version` preenchido com `hb_model_sha256` nulo, *então* o banco recusa com `23514`.
- **CA-08 (borda, envio)** — *Dado* o `HeartbeatLoop` com um `HttpPublisher` sobre `httpx.MockTransport` que responde 204, um modelo dummy carregado e um outbox com 2 `pending` e 1 `dead`, *quando* um ciclo roda, *então* há uma requisição `POST /api/v1/devices/<DEVICE_ID>/heartbeat` com `X-API-Key`, cujo corpo valida como `HeartbeatCreate` com `outbox_pending == 2`, `outbox_dead == 1` e o `model_version` do modelo; sem modelo carregado, `model_version` e `model_sha256` são nulos.
- **CA-09 (borda, nuvem fora do ar)** — *Dado* o transporte levantando `httpx.ConnectError` (ou respondendo 503), *quando* três ciclos rodam, *então* nenhuma exceção sai do laço, o outbox continua com as mesmas linhas (nenhuma linha nova) e a borda continua respondendo a uma captura `inspect`. *Dado* o transporte respondendo 401, *quando* dois ciclos rodam, *então* só o primeiro faz requisição e o log tem um único `ERROR`.
- **CA-10 (borda, condições)** — *Dado* `--stub-model`, ou `HEARTBEAT_INTERVAL_S=0`, ou sem `DEVICE_API_KEY`, *quando* a borda sobe, *então* nenhum `HeartbeatLoop` é registrado; e `HEARTBEAT_INTERVAL_S=5` ou `abc` → erro na subida com código 2.
- **CA-11 (borda, `httpx` isolado)** — *Dado* o código de `edge/src/qc_edge/`, *então* só `publisher.py` importa `httpx` (a verificação do CA-17 da SPEC-007 continua passando com o módulo novo).
- **CA-12 (dashboard)** — *Dado* `formatting.device_rows` com um `DeviceStatus` `online`, `last_source=simulated`, `uptime_s=7500` e um `DeviceStatus` sem heartbeat, *então* o primeiro tem `Situação == "online"`, `Origem == "simulado"` e `Ligado há == "2 h 05 min"`, e o segundo tem `Situação == "offline"`, `Último sinal == "nunca"` e `Ligado há == "—"`.
- **CA-13 (manual, dupla)** — 1. Borda ligada com a nuvem publicada; 2. abrir "Dispositivos" e conferir `edge-01` online, com o modelo e as filas; 3. desligar a borda e conferir `offline` depois de 3 min; 4. conferir que `sim-01` aparece como simulado depois de uma rodada do simulador.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | schemas e limites; rotas (204, 401, 403, 422); `online` no limite; `last_source`; laço (sucesso, falha, 401, sem modelo); formatação | `packages/contracts/tests/`, `api/tests/`, `edge/tests/`, `dashboard/tests/` |
| Aceite (tester) | Um por CA automatizado | os 4 arquivos do §3.1 |
| Manual (dupla) | CA-13 | descrito no CA |

Nada é mockado além das fronteiras: banco de teste real na API; `httpx.MockTransport` na borda; cliente da API simulado no dashboard.

## 7. Riscos e notas para o implementador

- **Ordem de deploy** (skill `contrato-api`): contracts → banco → API → dashboard → borda. Uma borda 0.5.0 contra uma API 0.4.0 recebe 404 no heartbeat (rota inexistente): vira `PublishTransientError`, só log, sem efeito nas inspeções.
- **Relógio:** `online` usa só a hora do servidor; o `sent_at` da borda não decide nada.
- **Modo lax do Pydantic** (SPEC-023 §4.4): `outbox_dead=True` é aceito como `1`, como nos outros inteiros do contrato. Não é recusado e não tem CA.

## 8. Definição de pronto

- [ ] Todos os CAs automatizados com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED e security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] READMEs e `.env.example` atualizados; `docs/architecture.md` §4 pelo architect
- [ ] PR aberto com os relatórios; merge conforme R-09; CA-13 manual registrado

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-18 | §6, pergunta 3: nota do Render superada, porque a API fica sempre ligada na VPS. A SPEC continua `Draft`. | ADR-018 (hospedagem na VPS pessoal) | Orquestrador, a pedido do humano |
| 2026-10-24 | SPEC reescrita para a aprovação. Decisões do architect: contrato 0.5.0 minor (sem ADR obrigatório), com limites inteiros e `model_version`/`model_sha256` nulos juntos; `last_heartbeat_at` e `online` pela hora do servidor; `last_source` em `DeviceStatus` para mostrar dispositivos simulados (pergunta 4: o simulador não envia heartbeat); envio pelo `HttpPublisher` (único módulo com `httpx`), com os limites da SPEC-030 e parada em 401/403; `HEARTBEAT_INTERVAL_S` de 10 a 3.600 ou 0; dependência das SPECs 034 (prazo dela), 016 (versão do contrato) e 030; CAs CA-01 a CA-12 testáveis e CA-13 manual. A SPEC continua `Draft`. | Decisão do humano de 2026-10-24 (projeto inteiro, todas as fases) | Orquestrador, a pedido do humano |
| 2026-10-24 | Aprovada pelo humano (`Draft` → `Ready`) com o pacote das Fases 2 e 3 e a ordem proposta. | Respostas do humano de 2026-10-24 (PR #45) | Orquestrador, a pedido do humano |
| 2026-10-24 | Limpeza de consistência pós-aprovação, sem mudança de requisito, CA, valor ou escopo: o aviso do topo passa a registrar a aprovação. | Status `Ready` desde o PR #45; sobrava o aviso da fase de rascunho | Architect, a pedido do orquestrador |
| 2026-10-24 | Entra em `In Dev` encadeada, antes de a SPEC-016 estar `Done` (todos os portões PASS, PR #52 empilhado sobre a 036), por decisão do humano; a branch nasce da `spec/SPEC-016-ferramentas-manuais` e o merge desta SPEC só acontece depois dos merges da 036 e da 016. | Resposta do humano de 2026-10-24 | Orquestrador, a pedido do humano |
