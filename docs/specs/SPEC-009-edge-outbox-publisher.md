# SPEC-009: Outbox SQLite e publisher HTTP

| Campo | Valor |
|---|---|
| Status | In Review |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-004, SPEC-007, SPEC-025 (validação do `Host` do console: tem de estar `Done` antes do merge desta, SEC-01 de `reviews/SPEC-007/r1-security-report.md`) |
| Semana alvo | S3 |
| Requisitos cobertos | RF-06, RF-07, RNF-04, RNF-05, RNF-09, RNF-10 |
| ADRs relevantes | ADR-002, ADR-009 |

## 1. Contexto

Implementa os passos 6 e 8 de `docs/architecture.md` §6.2 e o comportamento "nuvem fora do ar" de §8: cada inspeção é gravada num outbox SQLite durável (implementação do `InspectionSink` da SPEC-007) e um laço em segundo plano a publica em `POST /api/v1/inspections/batch` (SPEC-004), com idempotência por `inspection_id` (R-05) e sem nunca enviar imagem (R-02).

## 2. Objetivo

Com a nuvem fora do ar por 2 minutos durante 200 inspeções, todas chegam à API exatamente uma vez depois que ela volta (RNF-04), inclusive se a borda for derrubada no meio.

## 3. Escopo

### 3.1 Dentro

- `edge/src/qc_edge/outbox.py`: `SqliteOutbox`, `OutboxItem`, `Clock`.
- `edge/src/qc_edge/publisher.py`: `PublishResult`, Protocol `Publisher`, `HttpPublisher`, exceções de publicação.
- `edge/src/qc_edge/publish_loop.py`: `PublishLoop` (implementa o `BackgroundService` da SPEC-007) e `ConnectivityState`.
- Integração no `qc-edge` (§4.4): sem `--stub-model`, `sink = SqliteOutbox(OUTBOX_PATH)`, e o `PublishLoop` é registrado em `background` quando há `DEVICE_API_KEY` e `CLOUD_API_URL`; com `--stub-model`, `sink = InMemorySink()` (SPEC-007) e nenhum `PublishLoop`.
- Console e `/api/status` com `pending`, `dead`, `last_success_at` e o estado da conectividade (campos de `SinkStats`, SPEC-007).
- `edge/README.md` (seção "Envio para a nuvem") e `.env.example`.

### 3.2 Fora

- Endpoint e idempotência no servidor → SPEC-004. MQTT → SPEC-020.
- Reenvio manual de itens `dead` (fica para uma SPEC futura; aqui eles só aparecem no console).

## 4. Requisitos detalhados

### 4.1 Outbox

Arquivo em `OUTBOX_PATH` (padrão `EDGE_DATA_DIR/outbox.sqlite3`), `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=FULL`.

```sql
CREATE TABLE IF NOT EXISTS outbox (
  inspection_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT NOT NULL, sent_at TEXT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending','sent','dead')), last_error TEXT NULL);
CREATE INDEX IF NOT EXISTS outbox_due ON outbox(status, next_attempt_at, created_at);
```

Datas em ISO 8601 UTC com largura fixa (`isoformat(timespec="microseconds")`, sufixo `+00:00`). `payload` = `InspectionCreate.model_dump_json()`.

```python
Clock = Callable[[], datetime]          # sempre UTC; injetável nos testes
class SqliteOutbox:                     # implementa InspectionSink (SPEC-007)
    def __init__(self, path: Path, clock: Clock = utc_now, connectivity: ConnectivityState | None = None) -> None
    def put(self, inspection: InspectionCreate) -> None        # INSERT ... ON CONFLICT DO NOTHING; commit antes de retornar
    def fetch_due(self, limit: int = 100) -> list[OutboxItem]  # status=pending e next_attempt_at <= now, por created_at
    def mark_sent(self, ids: Sequence[UUID]) -> None
    def mark_retry(self, ids: Sequence[UUID], error: str, delay_s: Callable[[int], float]) -> None
    def mark_dead(self, inspection_id: UUID, error: str) -> None
    def stats(self) -> SinkStats
    def close(self) -> None
```

- Thread-safe: uma conexão com `check_same_thread=False` protegida por `threading.Lock` (ou uma conexão por thread). Falha de SQLite em `put` → `SinkError` (a SPEC-007 responde 503).
- `put` com um `inspection_id` já existente não altera a linha (nem o status `sent`).
- `last_error` truncado em 500 caracteres e **sem** o valor de `DEVICE_API_KEY`.

### 4.2 Publisher

```python
@dataclass(frozen=True)
class PublishResult: inspection_id: UUID; status: Literal["created", "duplicate"]
class PublishTransientError(Exception): ...   # rede, timeout, 5xx, 429, outros 4xx inesperados, resposta malformada
class PublishAuthError(Exception): ...        # 401, 403
class PublishRejectedError(Exception): ...    # 422 ou 413; .detail = resumo da recusa (abaixo), nunca o corpo
class Publisher(Protocol):
    def publish_batch(self, items: Sequence[InspectionCreate]) -> list[PublishResult]: ...
    def check_health(self) -> bool: ...
class HttpPublisher:
    def __init__(self, base_url: str, api_key: str, timeout_s: float = 5.0,
                 transport: httpx.BaseTransport | None = None) -> None
```

- `publish_batch`: `POST {base_url}/api/v1/inspections/batch`, header `X-API-Key`, corpo `qc_contracts.BatchCreate(items=...)` em JSON, 1 a 100 itens. A resposta é validada como `qc_contracts.BatchResult` e precisa ter `results` do mesmo tamanho e com os mesmos ids na mesma ordem; senão `PublishTransientError`.
- **Resumo da recusa (SEC-04-04 de `reviews/SPEC-004/r2-security-report.md`):** no 422 padrão do FastAPI, a API ecoa o `input` enviado (até 256 KB). Para 413 e 422, `PublishRejectedError.detail` é:
  - `"HTTP <status>: <detail>"`, quando o corpo é JSON com `detail` do tipo string (ex.: `HTTP 422: Value cannot be stored`). O texto é cortado em 200 caracteres, e cada caractere de controle vira `?`;
  - `"HTTP <status>: <n> validation errors"`, quando `detail` é uma lista (`n` = tamanho da lista);
  - `"HTTP <status>"`, nos outros casos (corpo que não é JSON ou sem `detail`).

  O corpo da resposta **nunca** vai para o log, para `last_error` nem para a mensagem da exceção. O log da recusa registra só o status, o resumo e a quantidade de itens do lote enviado.
- `check_health`: `GET {base_url}/api/v1/health`, `True` só com 200.
- `CLOUD_API_URL` precisa ser `https://`, exceto host `localhost` ou `127.0.0.1` (testes locais); outro caso → erro na subida, código 2. É o único módulo do `qc_edge` que importa `httpx` (SPEC-007, CA-17).

### 4.3 Laço de publicação (`PublishLoop`)

```python
class PublishLoop:
    def __init__(self, outbox: SqliteOutbox, publisher: Publisher, connectivity: ConnectivityState,
                 clock: Clock = utc_now, rng: random.Random | None = None,
                 interval_s: float = 2.0, health_every_s: float = 60.0) -> None
    def run_once(self) -> None   # um ciclo completo, síncrono; usado pelos testes
    def start(self) -> None      # thread daemon que chama run_once e espera com Event.wait(interval_s)
    def stop(self) -> None       # sinaliza o Event e faz join (timeout 10 s)
```

Ciclo (`run_once`):

1. Estado `auth_error` → não faz requisição nenhuma (pausa até reiniciar o `qc-edge`).
2. `fetch_due(100)`. Lista vazia → se passaram ≥ `health_every_s` desde o último contato, `check_health()` atualiza o estado (`online`/`offline`); fim.
3. `publish_batch(itens)`:
   - sucesso → `mark_sent` de todos (`created` e `duplicate` contam igual), `last_success_at = now`, estado `online`;
   - `PublishTransientError` → `mark_retry` com `attempts += 1` e `next_attempt_at = now + min(60, 2**n · U(0,8; 1,2))` s, onde `n` é o `attempts` **antes** do incremento; estado `offline`;
   - `PublishRejectedError` → bissecção: divide o lote ao meio e publica cada metade; um item sozinho rejeitado vira `dead` com `last_error` = o resumo da recusa (§4.2); os demais seguem as regras acima;
   - `PublishAuthError` → estado `auth_error`, **sem** incrementar `attempts`, log de erro único ("verifique DEVICE_API_KEY e reinicie").
4. Exceção inesperada → log com stack trace, `mark_retry` e o laço continua (a thread nunca morre).

`ConnectivityState` guarda `connectivity` e `last_success_at`, com lock; `SqliteOutbox.stats()` lê dele. Sem `PublishLoop` (sem chave/URL) → `connectivity="disabled"`. Com `--stub-model`, o sink é o `InMemorySink`, que já informa `connectivity="disabled"` (SPEC-007, §4.4 abaixo).

### 4.4 Integração no `qc-edge` e `--stub-model` (R-06)

O sink e o laço dependem só da flag `--stub-model` e, sem ela, de `DEVICE_API_KEY` e `CLOUD_API_URL`. `MODEL_DIR` não interfere: a flag tem precedência sobre ele (SPEC-008 §4.4).

| Situação | `sink` | `background` | `connectivity` |
|---|---|---|---|
| sem `--stub-model`, com `DEVICE_API_KEY` e `CLOUD_API_URL` | `SqliteOutbox(OUTBOX_PATH)` | `[PublishLoop]` | definida pelo laço (§4.3) |
| sem `--stub-model`, faltando `DEVICE_API_KEY` ou `CLOUD_API_URL` | `SqliteOutbox(OUTBOX_PATH)` | `[]` | `disabled` |
| com `--stub-model` (com ou sem chave e URL) | `InMemorySink()` (SPEC-007) | `[]` | `disabled` |

- **Com `--stub-model`, o `qc-edge` não abre, não cria e não valida `OUTBOX_PATH`.** As inspeções do stub (`model_version="stub-v0"`, `model_sha256` com 64 zeros, `source="live"`, SPEC-007) ficam só em memória e se perdem quando o processo termina. Por isso, nenhuma subida posterior, com ou sem a flag, consegue publicá-las: a R-06 vale por construção, sem depender de configuração (por exemplo, de usar outro `OUTBOX_PATH`). Linhas que já existiam no arquivo ficam intactas e só são publicadas numa subida sem a flag.
- A validação de `CLOUD_API_URL` e `DEVICE_API_KEY` na subida (CA-11) é a mesma com ou sem a flag.
- Com a flag, a subida registra um aviso (`WARNING`) que contém `--stub-model` e diz que as inspeções ficam só em memória e não vão para a nuvem. O aviso não cita valor de nenhuma variável.

## 5. Critérios de aceite

Os testes usam `httpx.MockTransport` com uma **nuvem falsa** que implementa a idempotência da SPEC-004 (um `dict` por `inspection_id`, 201/`created` ou `duplicate`), relógio falso e `random.Random(0)`. Nenhuma espera real > 2 s.

- **CA-01** — *Dado* um outbox novo, *quando* faço `put` do mesmo `InspectionCreate` 3 vezes, *então* `stats().pending == 1` e a tabela tem 1 linha com `status='pending'`, `attempts=0`.
- **CA-02** — *Dado* `put` de 150 inspeções e a nuvem falsa ok, *quando* chamo `run_once` 2 vezes, *então* a nuvem recebeu 2 requisições (100 + 50 itens, em ordem de `created_at`), `pending=0`, todas as linhas `sent` com `sent_at` preenchido, e `connectivity="online"`.
- **CA-03** — *Dado* a nuvem respondendo `duplicate` para itens já gravados, *quando* publico, *então* esses itens também ficam `sent`.
- **CA-04** — *Dado* a nuvem falsa com `httpx.ConnectError` (e, em outro caso, timeout e 503), *quando* `run_once` roda com o relógio em T, *então* os itens ficam `pending` com `attempts=1`, `next_attempt_at` entre T+0,8 s e T+1,2 s, `last_error` preenchido e `connectivity="offline"`; um novo `run_once` antes de `next_attempt_at` não faz requisição.
- **CA-05** — *Dado* falhas consecutivas, *então* os atrasos seguem 2ⁿ com jitter de ±20% e nunca passam de 60 s (verificado até `attempts=10`).
- **CA-06** — *Dado* um lote de 8 itens em que o 6º é rejeitado (a nuvem responde 422 a qualquer lote que o contenha), *quando* `run_once` roda até esvaziar, *então* 7 itens ficam `sent`, 1 fica `dead` com `last_error` não vazio, `stats().dead == 1`, e o item `dead` não é mais enviado em 5 ciclos seguintes.
- **CA-07** — *Dado* a nuvem respondendo 401 (e, em outro caso, 403), *quando* `run_once` roda 5 vezes, *então* houve exatamente 1 requisição, `attempts` continua 0, `connectivity="auth_error"`, e `GET /api/status` e o console mostram `auth_error`; os logs não contêm o valor da chave.
- **CA-08 (RNF-04)** — *Dado* 200 inspeções colocadas com `put` (uma a cada 1 s de relógio falso) e a nuvem falsa falhando com erro de conexão entre T+30 s e T+150 s, e ainda uma falha "resposta perdida" (a nuvem grava o lote e depois levanta timeout) em 1 requisição, *quando* `run_once` roda a cada 2 s de relógio até `pending=0` (no máximo 2 000 ciclos), *então* a nuvem tem exatamente 200 ids únicos gravados, 0 gravações duplicadas, os 200 ids são os colocados, `dead=0` e o tempo real do teste é < 30 s.
- **CA-09** — *Dado* um processo filho que faz `put` de 20 inspeções e termina com `SIGKILL` antes de qualquer envio, *quando* reabro o outbox no mesmo arquivo e rodo o laço com a nuvem ok, *então* os 20 ids chegam à nuvem exatamente uma vez.
- **CA-10 (R-02)** — *Dado* qualquer envio, *então* cada requisição é JSON (`application/json`, não multipart), vai só para `/api/v1/inspections/batch` ou `/api/v1/health`, e cada item tem exatamente as chaves de `architecture.md` §3.2 (nenhum campo com imagem ou bytes).
- **CA-11** — *Dado* `CLOUD_API_URL=http://api.exemplo.org`, *quando* o `qc-edge` sobe com `DEVICE_API_KEY` definido, *então* sai com código 2 citando `CLOUD_API_URL`; com `http://127.0.0.1:9000`, sobe.
- **CA-12** — *Dado* o `qc-edge` **sem** `--stub-model`, com `OUTBOX_PATH` não definido e `DEVICE_API_KEY` ausente (e, em outro caso, `DEVICE_API_KEY` definida e `CLOUD_API_URL` ausente), *quando* ele sobe e faço 3 capturas no modo inspeção, *então* o arquivo `EDGE_DATA_DIR/outbox.sqlite3` tem 3 linhas `pending`, `stats().pending == 3`, nenhuma requisição sai e `connectivity="disabled"`. O caso `--stub-model` é o CA-19.
- **CA-13** — *Dado* outbox vazio e o relógio avançando 61 s, *quando* `run_once` roda, *então* há 1 `GET /api/v1/health`; 200 → `online`, erro → `offline`.
- **CA-14** — *Dado* o app de pé com `PublishLoop` real (thread), *quando* o lifespan termina, *então* a thread encerra em ≤ 10 s e o arquivo SQLite fica consistente (`PRAGMA integrity_check` = `ok`).
- **CA-15** — *Dado* 4 threads fazendo `put` de 50 inspeções cada, em paralelo com `run_once`, *então* o outbox tem 200 linhas e nenhuma exceção ocorreu.
- **CA-16** — *Dado* as suítes, *quando* rodo `pytest --cov=qc_edge.outbox`, *então* a cobertura é ≥ 80%.
- **CA-17 (manual)** — Demo offline: 1. borda ligada com `DEVICE_API_KEY` válida e a API publicada; 2. desligar o Wi-Fi do notebook (no plano B, os dados móveis do celular); 3. inspecionar 3 peças: o console mostra `offline` e `pending=3`; 4. religar; 5. em até 90 s o console mostra `online`, `pending=0`, e as 3 inspeções aparecem no dashboard.
- **CA-18 (security, SEC-04-04)** — *Dado* um lote de 4 itens em que o 3º é rejeitado (a nuvem falsa responde 422 a qualquer lote que o contenha) e, em casos separados, o corpo do 422 sendo (a) o formato padrão do FastAPI com 2 erros, cujos campos `input` contêm um marcador gerado no teste que não aparece em nenhum item enviado, e (b) `{"detail": "Value cannot be stored"}`, *quando* `run_once` roda até esvaziar com `caplog` no nível DEBUG, *então* o item rejeitado fica `dead` com `last_error` exatamente `HTTP 422: 2 validation errors` no caso (a) e `HTTP 422: Value cannot be stored` no caso (b), os outros 3 ficam `sent`, e nenhum registro de log nem nenhuma coluna `last_error` contém o marcador.
- **CA-19 (R-06, `--stub-model`)** — *Dado* um arquivo em `OUTBOX_PATH` com 2 inspeções `pending` gravadas antes por `SqliteOutbox.put` (com `model_version="partqc-mnv3-v1"`), `DEVICE_API_KEY` definida, `CLOUD_API_URL=http://127.0.0.1:<porta>` e `MODEL_DIR` não definido, *quando* o `qc-edge` sobe com `--stub-model` e faço 3 capturas no modo inspeção, *então*:
  1. as 3 respostas são 200 e têm `model_version="stub-v0"`;
  2. `GET /api/status` mostra `sink.pending == 3`, `sink.dead == 0` e `sink.connectivity == "disabled"`;
  3. nenhuma requisição sai para a nuvem;
  4. o arquivo continua com exatamente as 2 linhas originais, com os mesmos valores em todas as colunas, e nenhum `payload` contém `stub-v0`;
  5. o log tem um registro `WARNING` que contém `--stub-model`, e nenhum registro contém o valor de `DEVICE_API_KEY`;
  6. depois que o app encerra, ao reabrir o arquivo com `SqliteOutbox` e rodar `PublishLoop.run_once` com a nuvem falsa até `pending=0`, a nuvem recebe exatamente os 2 ids originais e nenhum item com `model_version="stub-v0"`.

  Em outro caso, com `OUTBOX_PATH=<tmp>/sem-outbox/outbox.sqlite3` (pasta inexistente, fora do `EDGE_DATA_DIR`), depois das 3 capturas e do encerramento do app, nem o arquivo nem a pasta `<tmp>/sem-outbox` existem.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | outbox (SQL, concorrência), publisher (códigos HTTP), laço (estados, backoff) | `edge/tests/` |
| Aceite (tester) | Um por CA; nuvem falsa com `httpx.MockTransport`; relógio falso; `tmp_path` | `edge/tests/acceptance/test_spec_009.py` |
| Manual (dupla) | CA-17 | notebook + API publicada |

Mock só de fronteiras: rede da nuvem (MockTransport), relógio e RNG. O SQLite é real (arquivo em `tmp_path`).

## 7. Riscos e notas para o implementador

- O laço roda numa thread; não use `asyncio.sleep`/`time.sleep` longos nos testes — use `run_once` e o relógio falso.
- O cold start do Render (~1 min) aparece como timeouts: é esperado, o backoff absorve (RNF-10).
- Não apague linhas `sent` nesta SPEC (o volume da demo é pequeno); limpeza fica para depois, se necessário.
- `--stub-model` (§4.4): o `edge/README.md` e o `.env.example` dizem que, com a flag, nada vai para o outbox nem para a nuvem; a orientação de usar outro `OUTBOX_PATH` com o stub deixa de existir. Um `outbox.sqlite3` criado por um build da r1 desta branch com `--stub-model` pode ter linhas `stub-v0` pendentes: apague-o antes da primeira subida com chave e URL (só afeta máquinas de desenvolvimento; nada disso chegou à `main`).

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS); CA-17 registrado
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde; `ruff` limpo; cobertura de `qc_edge.outbox` ≥ 80%
- [ ] `edge/README.md` e `.env.example` atualizados
- [ ] SPEC-025 `Done` (merge feito) antes do merge desta
- [ ] PR aberto com os relatórios; merge humano

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-13 | Mudanças: (a) dependência da SPEC-025 (validação do `Host` do console), que precisa estar `Done` antes do merge desta, porque a partir daqui uma inspeção injetada por DNS rebinding chegaria à nuvem como `live`; (b) §4.2: `PublishRejectedError.detail` passa a ser um resumo da recusa (status, `detail` em texto ou contagem de erros), e o corpo do 422 nunca vai para o log nem para `last_error`; §4.3 usa esse resumo no item `dead`; (c) CA-18 novo; (d) §8 com o item da SPEC-025. Nenhum CA existente muda. SPEC marcada como "Aguardando reaprovação humana". | SEC-01 de `reviews/SPEC-007/r1-security-report.md`; SEC-04-04 de `reviews/SPEC-004/r2-security-report.md` | Orquestrador, a pedido do humano |
| 2026-10-13 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
| 2026-10-18 | Correção do SPEC_ISSUE-01 com a opção (d) do dev-report: com `--stub-model`, o sink volta a ser o `InMemorySink` da SPEC-007, e `OUTBOX_PATH` não é aberto, criado nem validado. Assim, nenhuma inspeção `stub-v0` (`source=live`) chega a um arquivo durável, e nenhuma subida posterior pode publicá-la (R-06 por construção). Mudanças: (a) §3.1, bullet da integração; (b) §4.3, último parágrafo; (c) §4.4 nova (tabela sink/laço por situação, `OUTBOX_PATH` intocado com a flag, aviso `WARNING` na subida); (d) CA-12 passa a cobrir só a subida sem a flag (chave ausente, ou URL ausente), com o caminho padrão `EDGE_DATA_DIR/outbox.sqlite3`; (e) CA-19 novo (R-06, `--stub-model`); (f) §7, nota sobre README, `.env.example` e outboxes locais da r1. Opções descartadas: (a) arquivo de outbox próprio do stub, que continuaria durável e seria publicado se alguém apontasse `OUTBOX_PATH` para ele; (b) recusar a subida com o `OUTBOX_PATH` da operação, que quebraria `qc-edge --stub-model` sem configuração (SPEC-025, CA-04 e CA-10); (c) descartar `stub-v0` no laço, que depende do nome da versão e mantém o resultado falso no arquivo. `docs/architecture.md` §6.1 e §6.2 (passo 6) atualizadas. SPEC marcada como "Aguardando reaprovação humana". | SPEC_ISSUE-01 de `reviews/SPEC-009/r1-dev-report.md` | Orquestrador, a pedido do humano |
| 2026-10-18 | Correção do SPEC_ISSUE-01 (opção d) reaprovada; `Blocked` → `In Dev`, retomada na r1. | Fluxo do loop (§4 da skill `features`) | Humano (Carlos) |
