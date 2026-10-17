# SPEC-014: Simulador de lotes

| Campo | Valor |
|---|---|
| Status | Done |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-004, SPEC-006 |
| Semana alvo | S4 |
| Requisitos cobertos | RF-14 (com R-05 e R-06) |
| ADRs relevantes | ADR-008, ADR-009, ADR-013 |

## 1. Contexto

O dashboard e a carta p (SPEC-006, SPEC-013) precisam de volume e de lotes fora de controle para a demo, antes de existir produção real suficiente. O simulador gera `InspectionCreate` plausíveis e os envia pela mesma rota de ingestão da borda (`docs/architecture.md` §1 e §4), **sempre** com `source=simulated` (R-06). Como os ids derivam da seed, reexecutar com a mesma seed demonstra a idempotência (R-05).

## 2. Objetivo

`scripts/simulate.py --lots 10 --seed 42` cria 10 lotes `SIM-…` na API, todos `simulated`, e os lotes indicados em `--out-of-control-lots` saem fora de controle na carta p.

## 3. Escopo

### 3.1 Dentro

- `scripts/simulate.py` (argparse), com funções importáveis: `SimConfig`, `parse_args(argv, *, now=None) -> SimConfig` (o `now` só por palavra-chave substitui o relógio no padrão e no limite de `--start`), `generate(cfg) -> list[InspectionCreate]`, `send(items, cfg, *, transport=None, sleep=time.sleep) -> SendSummary`, `main(argv=None, *, transport=None, sleep=time.sleep, now=None) -> int`.
- Testes em `scripts/tests/` e inclusão de `"scripts/tests"` em `testpaths` do `pyproject.toml` da raiz (SPEC-001 §4).
- Seção "Simulador" no `README.md` da raiz; `SIM_DEVICE_ID`/`SIM_DEVICE_API_KEY` no `.env.example` (se ainda não estiverem).

### 3.2 Fora

- Registro do dispositivo `sim-01` → `scripts/register_device.py` (SPEC-004).
- Script de limpeza de dados simulados → não faz parte do MVP (os dados ficam filtráveis por `source`).
- Selo "simulado" no dashboard → SPEC-013. Smoke test de produção → SPEC-015.

## 4. Requisitos detalhados

### 4.1 Argumentos

| Argumento | Padrão | Validação (erro → código 2, mensagem no stderr) |
|---|---|---|
| `--api-url` | env `CLOUD_API_URL` | obrigatório fora do `--dry-run`; `https://`, exceto host `localhost`/`127.0.0.1`; recusada também sem host, com usuário ou senha, com query ou fragmento, ou com porta inválida; a mensagem nunca repete a URL; a barra final é removida |
| `--device-id` | env `SIM_DEVICE_ID` | `^[a-z0-9-]{3,32}$` |
| `--api-key` | env `SIM_DEVICE_API_KEY` | obrigatório fora do `--dry-run`; não vazia e só com ASCII visível (`!` a `~`), sem repetir o valor na mensagem; `SimConfig.api_key` com `repr=False`; o help recomenda a variável de ambiente (R-03) |
| `--lots` | 10 | 1–500 |
| `--lot-size` | 25 | 1–1000; mutuamente exclusivo com o par abaixo |
| `--lot-size-min`, `--lot-size-max` | — | os dois juntos, 1–1000, `min ≤ max`; `n` de cada lote sorteado uniforme em `[min, max]` |
| `--defect-rate` | 0.10 | 0–1; probabilidade base de `poor` + `unusable` entre os itens reconhecidos |
| `--out-of-control-lots` | vazio | lista `"3,7"` de números de lote 1-based dentro de `1..lots`, sem repetição; nesses lotes a taxa é `min(1.0, 3 × defect-rate)` |
| `--unknown-rate` | 0.02 | 0–1 |
| `--start` | `now − lots × 10 min` | ISO 8601 **com fuso**; nenhum `inspected_at` gerado pode passar de `now + 5 min` |
| `--seed` | aleatória (`secrets.randbits(32)`) | inteiro ≥ 0; a seed usada é sempre impressa no resumo |
| `--model-version` | `sim-v0` | `^[a-z0-9.-]{3,40}$` |
| `--dry-run` | falso | não faz requisição nem exige `--api-url`/`--api-key` |

`--device-id` e `--model-version` são validados com `re.fullmatch(qc_contracts.DEVICE_ID_PATTERN, valor)` e `re.fullmatch(qc_contracts.MODEL_VERSION_PATTERN, valor)`, sem redefinir as regexes. **Nunca** com `re.match` ou `re.search`, que aceitam um `\n` final (`architecture.md` §3.2).

Não existe argumento para mudar `source` (R-06): `--source` é argumento desconhecido (código 2). `model_sha256` é sempre `"0" * 64`.

### 4.2 Geração (determinística com a seed)

Um único `random.Random(seed)`, consumido numa ordem fixa. Para o lote `i` (1-based): `lot_id = f"SIM-{start:%Y%m%d}-{i:03d}"` (data UTC de `--start`); início em `start + (i−1)·10 min`; os `n` itens espaçados igualmente nesses 10 min. Para cada item:

1. `inspection_id = uuid.UUID(int=rng.getrandbits(128), version=4)`.
2. Com probabilidade `unknown-rate`: `object_type=unknown`; `grade`, `grade_score`, `grade_confidence` = `None`; `type_confidence ~ U(0,30; 0,69)`.
3. Senão: `object_type` = `screw` ou `nut` (50/50), `type_confidence ~ U(0,75; 0,99)`; defeituoso com a taxa do lote; entre defeituosos `poor`/`unusable` com pesos 0,7/0,3; entre não defeituosos `perfect`/`good`/`fair` com pesos 0,40/0,35/0,25; `grade_confidence ~ U(0,55; 0,95)`; `grade_score = clamp(índice do grau + U(−0,4; 0,4), 0, 4)`.
4. `needs_review = type_confidence < 0.80 or (grade_confidence is not None and grade_confidence < 0.60)`; `latency_ms ~ inteiro U[40, 180]`; `source=simulated`; `device_id` do argumento.
5. Todo item passa por `qc_contracts.InspectionCreate` (inválido → erro de programação, código 1).

A mesma seed com os mesmos argumentos produz os mesmos ids (e, com `--start` fixo, a saída idêntica); com outro `--start`, os ids se repetem e a API responde `duplicate`.

### 4.3 Envio

1. `GET {api-url}/api/v1/health` com timeout de 90 s (acorda o Render), numa única requisição, sem novas tentativas; erro de rede ou qualquer status diferente de 200 → código 5.
2. Lotes de até 100 itens em `POST {api-url}/api/v1/inspections/batch`, header `X-API-Key`, corpo `qc_contracts.BatchCreate`, timeout 10 s. Os redirecionamentos **não** são seguidos (a chave nunca vai para outro host).
3. Erro de rede (`httpx.RequestError`), timeout ou 5xx → até 3 novas tentativas com `sleep(2)`, `sleep(4)`, `sleep(8)`; esgotou → código 5. 401/403 → código 3, sem novas requisições. 422 → código 4, imprimindo o `detail` (uma lista vira JSON compacto). Qualquer outro 4xx, um 3xx, ou um 2xx cujo corpo não é `BatchResult` com um resultado por item → código 5, sem nova tentativa, com o status HTTP na mensagem. Numa falha no meio do envio, o stderr mostra o progresso parcial (`sent=… created=… duplicate=… seed=…`).
4. Resumo no stdout: `sent=<n> created=<n> duplicate=<n> lots=<n> seed=<s> source=simulated`. Código 0.
5. `--dry-run`: imprime um `InspectionCreate` por linha (JSON Lines, `model_dump_json()`) no stdout e o resumo (sem `created`/`duplicate`) no stderr.

A chave nunca é impressa nem registrada em log.

## 5. Critérios de aceite

Os testes chamam `main([...], transport=MockTransport(...), sleep=<registrador>, now=<fixo>)`. A API falsa implementa a idempotência da SPEC-004 (ids gravados num `dict`; `created`/`duplicate`).

- **CA-01** — *Dado* `--dry-run --seed 42 --lots 3 --lot-size 10 --start 2026-10-01T12:00:00Z --device-id sim-01` e `now` fixo em `2026-10-01T13:00:00Z`, *quando* rodo, *então* o código é 0, o stdout tem 30 linhas, cada uma válida como `InspectionCreate`, todas com `source="simulated"`, `model_version="sim-v0"`, `model_sha256="0"*64`, `device_id="sim-01"`, lotes `SIM-20261001-001`…`003` (10 cada) e `inspected_at` crescente; e a API falsa recebeu 0 requisições.
- **CA-02** — *Dado* o comando do CA-01 rodado duas vezes, *então* os stdouts são idênticos byte a byte; com `--seed 43`, nenhum `inspection_id` coincide; todos os ids têm `version == 4` e são únicos.
- **CA-03 (R-06)** — *Dado* `--source live` (ou `--source=live`), *quando* rodo, *então* o código é 2 e nada é gerado; e em 1 000 itens gerados com qualquer combinação de argumentos válidos, `source` é sempre `simulated`.
- **CA-04** — *Dado* `--dry-run --seed 1 --lots 20 --lot-size 500 --defect-rate 0.2 --unknown-rate 0`, *então* a fração de defeituosos (`qc_contracts.is_defective`) está em 0,20 ± 0,02; entre os defeituosos, `poor` está em 0,70 ± 0,04; entre os não defeituosos, `perfect`, `good` e `fair` estão em 0,40, 0,35 e 0,25, cada um ± 0,03.
- **CA-05** — *Dado* `--dry-run --seed 2 --lots 10 --lot-size 200 --unknown-rate 0.1`, *então* a fração de `unknown` está em 0,10 ± 0,03 e todo `unknown` tem `grade`, `grade_score` e `grade_confidence` nulos e `type_confidence < 0.70`.
- **CA-06** — *Dado* `--dry-run --lots 5 --lot-size-min 3 --lot-size-max 8 --seed 3`, *então* cada lote tem entre 3 e 8 itens; *dado* `--lot-size-min 9 --lot-size-max 8`, ou `--lot-size 10 --lot-size-min 3 --lot-size-max 8`, *então* código 2.
- **CA-07 (SPC)** — *Dado* `--dry-run --seed 42 --lots 30 --lot-size 200 --defect-rate 0.1 --unknown-rate 0 --out-of-control-lots 24,28`, *quando* agrego os itens por `lot_id` (n e defeitos via `is_defective`) no formato de entrada da SPEC-006 e chamo `qc_api.services.spc.compute_p_chart(lots, baseline_lots=20, min_lot_size=5)`, *então* `SIM-…-024` e `SIM-…-028` têm `out_of_control=true` e no máximo 2 dos outros 28 lotes têm `out_of_control=true`.
- **CA-08** — *Dado* `--out-of-control-lots 0,3` com `--lots 10`, ou `11`, ou `a,b`, ou `3,3`, ou `--defect-rate 1.5`, ou `--unknown-rate -0.1`, ou `--device-id` igual a `"sim-01\n"`, ou `--model-version` igual a `"sim-v0\n"` (quebra de linha final, passada como elemento de `argv`), *então* código 2.
- **CA-09** — *Dado* `--start` igual a `now + 1 h`, *então* código 2 e 0 requisições.
- **CA-10 (R-05)** — *Dado* a API falsa vazia e `--seed 42 --lots 10 --lot-size 25`, *quando* rodo, *então* há 1 `GET /api/v1/health` seguido de 3 `POST /api/v1/inspections/batch` (100, 100, 50 itens) com `X-API-Key`, o stdout contém `sent=250 created=250 duplicate=0` e o código é 0; *quando* rodo de novo com a mesma seed, *então* `sent=250 created=0 duplicate=250` e a API falsa continua com 250 registros.
- **CA-11** — *Dado* a API falsa respondendo 503 e depois `httpx.ConnectError` ao primeiro lote e 201 na 3ª tentativa, *quando* rodo, *então* o código é 0, o `sleep` registrou `[2, 4]` e não há registro duplicado.
- **CA-12** — *Dado* a API falsa sempre com 503, *então* o código é 5 após 4 tentativas do primeiro lote (`sleep` = `[2, 4, 8]`).
- **CA-13** — *Dado* a API falsa respondendo 401 (e, em outro caso, 403) ao primeiro lote, *então* código 3, nenhuma requisição posterior, e o valor de `--api-key` não aparece no stdout nem no stderr.
- **CA-14** — *Dado* a API falsa respondendo 422 com `{"detail": "x"}`, *então* código 4 e o stderr contém `x`.
- **CA-15** — *Dado* `SIM_DEVICE_API_KEY` ausente e sem `--api-key` (sem `--dry-run`), ou `--api-url http://api.exemplo.org`, *então* código 2 e 0 requisições; com `--api-url http://127.0.0.1:8001`, segue normalmente.
- **CA-16** — *Dado* qualquer requisição de lote, *então* cada item do corpo tem exatamente as chaves de `architecture.md` §3.2 (R-04).

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | parsing, geração, distribuição, envio e códigos de saída | `scripts/tests/` |
| Aceite (tester) | Um por CA; `httpx.MockTransport`; `sleep` e `now` injetados; o CA-07 importa `qc_api.services.spc` | `scripts/tests/acceptance/test_spec_014.py` |

Os testes importam o script com `importlib.util.spec_from_file_location` (não há pacote em `scripts/`). Nenhuma rede real.

## 7. Riscos e notas para o implementador

- Execução: `uv run --package qc-api python scripts/simulate.py ...`. É a convenção de `docs/architecture.md` §2: os scripts usam o ambiente do `qc-api`, que tem `httpx`, `qc-contracts` e `qc_api.services.spc`, sem torch. É a mesma de `scripts/register_device.py` (SPEC-004).
- `lot_id` usa só a data de `--start`: duas execuções no mesmo dia com seeds diferentes geram lotes com o mesmo nome e misturam os dados no SPC. Para uma série nova no mesmo dia, use outro `--start`.
- O CA-07 é robusto por construção (lotes fora de controle depois da linha de base; n = 200; 3σ); se ainda assim a seed 42 produzir um alarme falso extra, registre `SPEC_ISSUE` em vez de mudar o CA.
- O consumo do RNG precisa ter ordem fixa e documentada no código, ou a reprodutibilidade do CA-02 quebra a cada refatoração.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `README.md` e `.env.example` atualizados
- [ ] PR aberto com os relatórios; merge humano

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-12 | §4.1 exige `re.fullmatch` com `DEVICE_ID_PATTERN` e `MODEL_VERSION_PATTERN` de `qc_contracts`. O CA-08 ganhou os casos `"sim-01\n"` e `"sim-v0\n"`. Nenhum outro requisito muda; o `latency_ms` gerado (40 a 180) já respeita o teto do contrato 0.2.0 (SPEC-023). SPEC marcada como "Aguardando reaprovação humana". | RV-04 de `reviews/SPEC-002/r1-review-report.md` | Orquestrador, a pedido do humano |
| 2026-10-12 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
| 2026-10-17 | CA-01 (e, por referência, CA-02): `--start` passa de `2026-11-01T12:00:00Z` para a data passada `2026-10-01T12:00:00Z`, com `now` fixo em `2026-10-01T13:00:00Z`; os lotes esperados passam a `SIM-20261001-001`…`003`. Nenhum comportamento muda (opção (a)): o `InspectionCreate` recusa `inspected_at` mais de 5 min no futuro pelo relógio real, e o último item (12:29:00Z) já está no passado; o `now` fixo fica depois do último item, coerente com o CA-09. SPEC marcada como "Aguardando reaprovação humana". | SPEC_ISSUE-1 de `reviews/SPEC-014/r1-dev-report.md` | Orquestrador |
| 2026-10-17 | Correção do SPEC_ISSUE-1 reaprovada; `Blocked` → `In Test`, retomando a r1. | Fluxo do loop (§4 da skill `features`) | Humano (Carlos) |
| 2026-10-17 | Só texto, depois do merge (PR #18): §3.1 registra o `now` keyword-only de `parse_args`; §4.1 registra a validação extra de `--api-url` e de `--api-key`; §4.3 registra o health sem novas tentativas, os redirecionamentos não seguidos, o código 5 para 3xx, para outros 4xx e para um 2xx inválido, e o progresso parcial na falha. São as decisões 1, 4, 5, 6, 7 e 9 de `reviews/SPEC-014/r1-dev-report.md`, aceitas pelo reviewer. Nenhum CA e nenhum comportamento implementado muda, por isso sem reaprovação. As correções SEC-01 a SEC-04 do security-report ficam na SPEC-027. | RV-04 de `reviews/SPEC-014/r1-review-report.md` | Orquestrador, a pedido do humano |
