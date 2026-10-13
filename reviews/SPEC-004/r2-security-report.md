# SPEC-004 — r2 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-004](../../docs/specs/SPEC-004-api-ingestao.md) |
| Rodada | r2 |
| Revisor de segurança | security-devops |
| Diff revisado | `docs/pendencias-pos-024...b5a75ca` (branch empilhada sobre o PR #10) |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante, alto ou médio. Ficam 2 achados baixos e 3 informativos, todos com destino fora desta SPEC (tabela "Destino" abaixo).

## Superfície analisada

- **Rotas novas:** `GET /api/v1/health` (sem autenticação), `POST /api/v1/inspections` e `POST /api/v1/inspections/batch` (chave de dispositivo), além de `/docs` e `/openapi.json`, que são públicos por exigência da SPEC.
- **Autenticação:** `api/src/qc_api/auth.py`, com `require_device` (hash SHA-256, busca pelo hash e `compare_digest`) e `require_read_key` (só teste unitário nesta SPEC).
- **Entradas externas:** corpo JSON (contrato `qc_contracts`), o header `X-API-Key`, o tamanho do corpo (`middleware.py`) e os argumentos do `scripts/register_device.py`.
- **Erros e logs:** `errors.py` (handler de validação da r2), `UnhandledErrorMiddleware` e `RequestLogMiddleware` (`middleware.py`), o log do `DataError` em `routers/inspections.py` e o log do health.
- **Segredos:** `config.py` (`SecretStr` e `hide_input_in_errors`), `.env.example` (`MAX_BODY_BYTES` e `LOG_LEVEL`), o README e o stdout do script.
- **Banco:** SQL de `db.py` e do script, idempotência e transação única.
- **Dependências:** nenhuma nova. O `uv.lock` só muda a versão do `qc-api` (0.0.0 → 0.1.0).
- **Deploy:** nenhum arquivo de deploy no diff (`infra/render.yaml` é da SPEC-015).

### Verificações executadas (read-only, sem alterar código)

1. `uv run pytest -q api/tests` com `TEST_DATABASE_URL`: **182 passed**. `uv run ruff check .`: limpo.
2. Sondas com `TestClient` contra um banco temporário (`partqc_sec_r2_tmp_test`, criado, migrado e removido no fim com `drop database ... with (force)`). Chaves e marcadores foram gerados com `secrets` em tempo de execução. Os resultados estão nas seções abaixo.
3. Sondas com uvicorn real (httptools 0.9.0) por socket bruto, com variações de framing do corpo e a app sem banco. A URL foi montada sem senha e a `READ_API_KEY` gerada em tempo de execução.
4. Log do pool com o banco fora do ar: senha montada em tempo de execução com `urlunsplit`.
5. Busca no diff por padrões de segredo: URL com senha, `password=`, `eyJ…`, `service_role`, `AKIA`, chaves PEM e `api_key = "…"`.

Os scripts ficaram no scratchpad da sessão, fora do repositório.

## Avaliação dos pontos pedidos

### Autenticação de dispositivo

- **Hash e comparação:** só o SHA-256 hex da chave vai para o banco (`devices.api_key_hash`, com `check ~ '^[0-9a-f]{64}$'` e `unique`). A busca é `where api_key_hash = %s`, parametrizada, e o `compare_digest` em bytes ASCII confirma o resultado. A busca pelo índice não é em tempo constante, mas o atacante só controla a pré-imagem: descobrir o prefixo de um hash não ajuda sem inverter o SHA-256. É o padrão aceito para chaves aleatórias de 256 bits (`token_urlsafe(32)`), e por isso o SHA-256 sem sal basta aqui.
- **Corpo único do 401:** chave ausente, vazia, com mais de 256 caracteres, errada, a chave de leitura, o próprio hash usado como chave e a chave com espaço à esquerda dão todos 401 `{"detail": "Missing or invalid API key"}`. Os quatro últimos casos foram conferidos nas minhas sondas.
- **Enumeração de dispositivos:** não há oráculo de existência de dispositivo.
  - Sem chave válida, toda resposta é o mesmo 401.
  - O 403 `device_id does not match API key` só sai depois de uma autenticação válida. Ele é decidido em memória (`item.device_id != device_id`), sem consultar o banco, e por isso não diz se o outro `device_id` existe.
  - A única diferença de tempo é entre "rejeitada sem consultar o banco" (ausente, vazia ou com mais de 256 caracteres) e "consultada". Ela revela o formato da chave, não a existência de um dispositivo.
- **Rotação (`register_device.py --rotate`):** um `update ... returning`, com commit antes de imprimir a chave. A API não guarda a autenticação em cache, então a chave antiga deixa de valer na próxima requisição (CA-22). A chave só sai no stdout, uma vez, e nunca em log. Os erros de banco registram só o tipo da exceção. Uma URL inválida não é ecoada. O `--device-id` é validado com `re.fullmatch`. Ver SEC-04-03 sobre o `--database-url`.

### Limite de corpo (inclusive chunked)

- Com `Content-Length` acima do limite, a resposta é 413 sem ler o corpo. Sem `Content-Length`, ou com um valor que não é número, o middleware conta os bytes recebidos e levanta `BodyTooLargeError` ao passar do limite. A memória fica limitada a `MAX_BODY_BYTES` mais um bloco. O middleware fica fora do `ExceptionMiddleware` e da autenticação, então o 413 vem antes do 503 e do 401 (CA-09 e o teste do tester com uvicorn real).
- **Sondas de framing com uvicorn real:**
  - `Content-Length` duplicado (pequeno e grande, nas duas ordens), `Content-Length: 10, 300000`, `Content-Length` junto com `Transfer-Encoding: chunked` (também com 300 KB em chunks) e `Content-Length: -1` dão **400 do próprio httptools**, antes da app;
  - chunked de 300 × 1 000 bytes, sem `Content-Length`, dá **413** `{"detail":"Request body too large"}`;
  - o log do servidor não tem `ERROR`, traceback nem bytes do corpo.

  Mesmo que o parser HTTP mude, a contagem dentro do middleware é a garantia real, porque o valor declarado só serve para responder mais cedo.

### Segredos e corpo fora dos logs (R-03, §4.2)

- **Configuração:** `DATABASE_URL` e `READ_API_KEY` são `SecretStr`, o modelo usa `hide_input_in_errors=True` e o `.env` não é lido (CA-20). O `.env.example` só tem placeholders e comentários. O `.gitignore` cobre `.env` e `.env.*`, exceto o `.example`. A busca por padrões de segredo no diff não achou nada. As URLs dos testes não têm senha literal: a senha é montada em tempo de execução, conforme a regra da seção 4 do checklist.
- **Log por requisição:** método, template da rota (o caminho cru, quando não há rota, vai com `repr` e corte em 200 caracteres), status, `device_id` e duração. Não registra a chave, o hash, a query string nem o corpo.
- **Sondas de log** (`LOG_LEVEL=DEBUG`, root logger capturado): a chave `KE`, o `hash_api_key(KE)`, a `READ_API_KEY`, o marcador do corpo e o `lot_id` enviado não aparecem no log.
- **Pool com o banco fora do ar:** a senha montada não aparece no log, e o usuário também não, porque a falha foi de TCP. Ver SEC-04-05 sobre o host.
- **T-02 da r1:** corrigido. O handler da r2 delega ao 422 padrão e só usa o fallback sem `input`/`ctx` quando a codificação falha, então a `RequestValidationError` com o corpo bruto não chega mais ao `logger.exception`. O tester cobriu bytes não UTF-8, multipart, aninhamento até 50 000 níveis, NaN/Infinity e surrogates, inclusive com uvicorn real.

### Idempotência por `inspection_id` (R-05) contra sobrescrita por outro dispositivo

Sondas contra o banco temporário:

- `edge-01` grava `X`. Depois, `sim-01`, com a própria chave, envia `X` com `device_id="sim-01"` e `lot_id` diferente: **200 `duplicate`**, e a linha continua `('edge-01', 'L-001')`.
- Variante em lote: `sim-01` envia `[item novo próprio, X]`. O item novo é `created` e `X` é `duplicate`; a linha de `X` continua com o dono e os valores originais.
- `ON CONFLICT (inspection_id) DO NOTHING` não tem caminho de `update`, então nenhum dispositivo sobrescreve o registro de outro.
- O efeito colateral é um oráculo de existência de `inspection_id` para quem tem uma chave válida. Com UUID v4 (122 bits aleatórios, e o contrato recusa as outras versões), adivinhar um ID alheio não é viável. Pela mesma razão, também não dá para "reservar" IDs futuros de outro dispositivo. É a decisão consciente do §7 da SPEC. **Aceito.**

### `DataError` → 422

- `except psycopg.DataError` fica só em volta de `insert_inspections`. A transação (`conn.transaction()`) é desfeita inteira, inclusive o `last_seen_at`. A resposta tem o corpo exato `{"detail": "Value cannot be stored"}`, levantado com `from None`, e o handler de `HTTPException` não registra a exceção.
- **Sonda:** com `grade_score=1e-50`, o log tem só `value cannot be stored: route=/api/v1/inspections device_id=edge-01 sqlstate=22003`, sem valores e sem a mensagem do servidor.
- O `IntegrityError` (classe 23) e o `OperationalError` não são capturados por esse bloco, como manda o §7. O `OperationalError` passa pelo `db_connection` e vira 503 sem mensagem.
- Um NUL em `model_version` é recusado pelo contrato (422), antes de chegar ao `DataError` do lado do cliente psycopg.

### O-01 (eco do corpo no 422 padrão)

As sondas confirmam que o eco só acontece **depois** da autenticação e só para quem enviou o corpo:

| Caso | Resposta | Marcador do corpo na resposta |
|---|---|---|
| `text/plain` sem chave | 401 | não |
| JSON malformado sem chave | 422 `json_invalid` com `"input": {}` e `ctx.error` = mensagem do `json.loads` | não |
| JSON válido, mas inválido para o modelo, sem chave | 401 | não |
| `text/plain` com chave válida | 422 | sim |

Ou seja, o cliente recebe de volta só o que ele mesmo enviou. Não há exposição a terceiros nem dado do servidor na resposta. A amplificação é de no máximo 1× e exige uma chave válida. Nada é gravado e nada vai para o log. O §4.5 exige o 422 padrão, então **não há achado**. Fica a nota informativa SEC-04-04 para o publisher da SPEC-009.

### O-02 (400 antes da autenticação)

- O corpo é decodificado com `json.loads` antes das dependências. Por isso um cliente sem chave consegue gastar CPU de parse, mas esse custo é limitado pelos 256 KB e pelo limite de 4 300 dígitos do Python para inteiros (CA-26). A partir de 100 000 níveis de aninhamento, o próprio `json.loads` recusa com 400.
- A resposta não revela nada além de "não é JSON". **Aceito**, sem achado. É o mesmo custo de qualquer endpoint JSON do FastAPI, e o limite de corpo vem antes.

### RV-01 (`IntegrityError` no log)

Confirmei o risco: a mensagem de uma `CheckViolation` (SQLSTATE `23514`) contém os valores da linha. Numa sonda direta no banco, com `grade_score=5` e um `lot_id` marcador, o marcador aparece em `str(exc)`. Se essa exceção escapasse da rota, o `logger.exception` do `UnhandledErrorMiddleware` registraria parte do corpo.

Hoje o caminho é inalcançável:

- as regex e as faixas do contrato espelham as `check` do `001_init.sql`;
- o arredondamento para `float4` de valores em `[0, 1]` e `[0, 4]` não sai da faixa;
- a FK só falharia numa corrida com a exclusão do dispositivo, que não existe como operação (`on delete restrict`, sem ferramenta de remoção).

Os valores são resultados de inspeção, sem segredo, sem PII e sem imagem. Por isso o RV-01 vira o **SEC-04-01 (baixa, não bloqueia)**, com destino ao architect.

## Achados

| ID | Severidade | Categoria (auth, input, secrets, deps, deploy, privacy) | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-04-01 | baixa | privacy (logs) | `api/src/qc_api/middleware.py:120-121`, `api/src/qc_api/routers/inspections.py:45-58` | Mesmo caso do RV-01. Uma `IntegrityError` (classe 23) na escrita chegaria ao `logger.exception` com `Failing row contains (...)`, ou seja, com os valores do payload (confirmado em sonda: a mensagem da `CheckViolation` contém os valores). Hoje é inalcançável, mas uma migração futura que divirja do contrato reabre o caminho, e o problema só apareceria em produção. | **Não bloqueia.** Para o **architect**, na próxima SPEC que mexer na API (SPEC-005): tratar `psycopg.IntegrityError` em volta da escrita, registrando só a rota, o `device_id` e o SQLSTATE, como no `DataError`. O status (500 genérico, 409 ou 422) fica a critério do architect. Opcionalmente, registrar como regra geral no `architecture.md` §4 que nenhuma mensagem de `psycopg.Error` vai para o log. |
| SEC-04-02 | baixa | auth (disponibilidade) | `api/src/qc_api/auth.py:40-43`, `api/src/qc_api/db.py:18-21`, `api/src/qc_api/routers/health.py` | Toda requisição sem autenticação com uma chave não vazia de até 256 caracteres, e todo `GET /health`, ocupa uma conexão do pool (máximo de 5, espera de 5 s). Uma rajada anônima pode esgotar o pool, e então os dispositivos legítimos recebem 503 enquanto ela durar. Não há perda de dados, porque o outbox da borda reenvia (SPEC-009), mas também não há limitação de taxa na API. | **Não bloqueia.** Para a **SPEC-015**: avaliar se o Render (plano free) oferece alguma limitação de taxa na borda. Se não oferecer, registrar no `docs/deployment-plan.md` como risco aceito (projeto acadêmico, URL não divulgada), com o efeito esperado (503 e reenvio do outbox). Limitação de taxa dentro da API, se o humano quiser, vira uma SPEC nova (architect). |
| SEC-04-03 | informativa | secrets | `scripts/register_device.py:88-91` | `--database-url URL` deixa a senha no `argv`, visível em `ps` e em `/proc/<pid>/cmdline` para outros usuários da máquina, e no histórico do shell. O README já mostra o caminho por `DATABASE_URL`. | **Não bloqueia.** Para a **SPEC-015**: no passo a passo de registro dos dispositivos de produção do `docs/deployment-plan.md`, usar `uv run --env-file .env ...` com `DATABASE_URL`, nunca `--database-url` com a URL de produção. |
| SEC-04-04 | informativa | privacy | — (comportamento exigido pelo §4.5) | O-01: o 422 padrão ecoa o `input` (até 256 KB) **para quem enviou**, e só depois da autenticação (confirmado em sonda). Não expõe nada a terceiros. | **Nenhuma correção nesta SPEC.** Para a **SPEC-009**: o publisher registra do 422 só o status, o `detail` quando for string (`Value cannot be stored`) e a contagem de itens, nunca o corpo da resposta inteiro. |
| SEC-04-05 | informativa | secrets (logs) | dependência `psycopg_pool` (logger `psycopg.pool`) | Com o banco fora do ar, o pool registra em WARNING `error connecting in 'pool-1': connection failed: connection to server at "<host>", port <porta> failed`. A senha não aparece (verificado). Numa falha de autenticação, a mensagem do servidor pode trazer o nome do usuário. Em produção, isso leva o host e o usuário do pooler do Supabase ao log do Render. Não são segredos (R-03 continua ok). | **Nenhuma correção.** Para a **SPEC-015**: saber que esse log existe ao configurar o Render e não tratar esse host ou usuário como segredo nem como vazamento no portão `deploy`. |

### Destino de cada achado

| Achado | Bloqueia a SPEC-004? | Destino |
|---|---|---|
| SEC-04-01 (= RV-01) | Não | architect → SPEC-005 (ou regra no `architecture.md` §4) |
| SEC-04-02 | Não | SPEC-015 (risco aceito ou mitigação no provedor); SPEC nova só se o humano pedir limitação de taxa |
| SEC-04-03 | Não | SPEC-015 (`docs/deployment-plan.md`) |
| SEC-04-04 (= O-01) | Não | SPEC-009 (log do publisher) |
| SEC-04-05 | Não | SPEC-015 (ciência no portão `deploy`) |
| O-02 | Não (aceito, sem achado) | — |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa dela; comparação em tempo constante | ✅ As duas rotas de escrita usam `require_device`, com `compare_digest` em bytes. `require_read_key` também usa `compare_digest` em bytes, o que evita o `TypeError` com não ASCII. O `/health` é público por definição (`architecture.md` §4) |
| Entradas validadas: tamanho do corpo, tipo real da imagem, regex de IDs, `extra="forbid"` | ✅ Limite de corpo com contagem real, inclusive chunked. `InspectionCreate` e `BatchCreate` com `extra="forbid"` e regex nos IDs. `--device-id` com `re.fullmatch`. Tipo de imagem: N/A, porque nenhuma rota aceita imagem (R-02; multipart e binário dão 422) |
| SQL sempre parametrizado | ✅ `db.py` e `register_device.py` só usam `%s`, sem f-string em query |
| RLS ligado; `DATABASE_URL` e `service_role` só na API | ✅ RLS sem mudança (SPEC-003). `DATABASE_URL` como `SecretStr`, só no servidor da API e no script de administração. Nenhuma `service_role` no diff |
| CORS fechado ou mínimo | ✅ Sem `CORSMiddleware` (CA-17) |
| Logs sem segredos e sem payloads de imagem | ✅ Verificado em sonda e coberto pelo CA-18, pelo T-02 e pelos `test_extra_r2_*`. Resta o SEC-04-01 (baixa, caminho hoje inalcançável) |
| Dependências novas: mantidas, licença, CVE | ✅ Nenhuma dependência nova (só a versão do `qc-api` no `uv.lock`) |
| Deploy: variáveis no provedor, health check, plano free | N/A (SPEC-015). O `/health` responde 503 com o banco fora do ar, o que a SPEC-015 deve considerar no health check do Render (§7 da SPEC) |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma. As versões resolvidas que a API usa continuam as mesmas da `main`: fastapi 0.143.0, starlette 1.7.0, uvicorn 0.54.0 (httptools 0.9.0), psycopg 3.3.6, psycopg-pool 3.3.3, pydantic 2.14.1 e pydantic-settings 2.15.0 |

## Declaração

- [x] Não editei código; não sou autor desta SPEC.
- [x] O banco temporário `partqc_sec_r2_tmp_test` foi removido. Não criei papéis.
