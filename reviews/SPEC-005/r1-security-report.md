# SPEC-005 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-005](../../docs/specs/SPEC-005-api-leitura-metricas.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `origin/main...ddd66c2` (base `e9c9060`, ponta de `docs/pendencias-pos-007`, já mergeada na `main` = `65c3214`) |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante, alto ou médio. Os dois achados são de severidade baixa e vão para outras SPECs (015 e manutenção da 003). Os dois itens informativos são para a SPEC-013 e a SPEC-015.

## Superfície analisada

- **Rotas novas:** `GET /api/v1/inspections`, `GET /api/v1/metrics/summary`, `GET /api/v1/metrics/timeseries` e `GET /api/v1/lots`, todas com `require_read_key` (na rota, no caso de `/inspections`, ou no router, nos outros casos).
- **Entradas externas:** o header `X-API-Key` e a query string (`InspectionFilters`, `Pagination`, `bucket`).
- **Banco:** consultas de leitura novas (`repositories/inspections.py`) e o tratamento de `IntegrityError` na escrita (`routers/inspections.py`, §4.5 item 1).
- **Log:** o `UnhandledErrorMiddleware` com `find_database_error` e `sqlstate_label` (§4.5 item 2).
- **Segredos, dependências e deploy:** nada mudou. `pyproject.toml`, `uv.lock`, `.env.example`, `infra/` e os workflows estão fora do diff. Não há variável de ambiente nova.

### Verificações feitas

1. **Chave de leitura contra chave de dispositivo.**
   - **Separação:** é mecânica. `require_read_key` (`auth.py:54`) compara só com `READ_API_KEY` e nunca consulta `devices`. `require_device` só aceita um hash presente em `devices`. Uma chave de dispositivo nas rotas de leitura dá 401 (CA-01). A chave de leitura em `POST /inspections` e `/batch` dá 401 e não grava nada (exploratório do tester).
   - **Comparação:** `secrets.compare_digest` sobre bytes (`auth.py:60`). O único vazamento possível é o do tamanho, documentado no Python, e o tamanho mínimo de `READ_API_KEY` é 32 (`config.py`). Não dá para explorar.
   - **Enumeração:** o 401 tem o mesmo corpo para chave ausente, chave errada e chave de dispositivo. A autenticação roda antes da validação dos parâmetros, então quem não tem chave não descobre nada sobre os filtros. Uma requisição sem chave nas rotas de leitura **não toca o banco**: não abre caminho de negação de serviço anônima contra o pool.
2. **Injeção de SQL.**
   - Li cada texto SQL de `repositories/inspections.py`. São constantes `str` compostas só com `sql.SQL(CONST).format(where=..., columns=...)`. `where` é um `join` de fragmentos fixos com placeholders nomeados (`%(f_<nome>)s`), e `columns` usa `sql.Identifier` sobre uma tupla constante.
   - Todo valor é parâmetro do psycopg: filtros, `limit`, `offset`, `bucket`, o fuso `'UTC'` e `'unknown'`. As chaves `{{}}` do `'{}'::jsonb` estão escapadas corretamente para o `format`.
   - Defesa adicional: toda leitura roda em `repeatable read, read only` (`:187`). Mesmo que uma injeção existisse, a transação recusaria escrita.
   - O CA-12 (`bucket=hour;drop table inspections` dá 422 e a tabela fica intacta) e o CA-19 (varredura AST, com sonda que prova que o scanner funciona) passam.
3. **Custo das consultas como vetor de negação de serviço.** Sonda num banco temporário próprio (`partqc_test_secprobe`, apagado no fim) com **1 000 000 linhas** e 2 000 lotes, chamando a app real com `TestClient`. O tempo inclui a rede local e a serialização.

   | Requisição | Tempo | Status |
   |---|---|---|
   | `/inspections` (padrão) / `limit=500` | 0,06 s / 0,04 s | 200 |
   | `/inspections?limit=500&offset=999990` | 0,45 s | 200 |
   | `/inspections?offset=9223372036854775807` | 0,44 s | 200 (`items=[]`) |
   | `/metrics/summary` (sem filtro) | 0,80 s | 200 |
   | `/metrics/timeseries?bucket=minute` (1 M buckets) | 0,27 s | 422 |
   | `/metrics/timeseries?bucket=day` | 0,33 s | 200 |
   | `/lots?limit=500` / `&offset=1500` | 1,76 s / 1,76 s | 200 |
   | `/inspections?lot_id=L-7` (índice) | 0,004 s | 200 |

   - O custo é linear no tamanho da tabela, e não no valor de `offset` ou de `limit`. O `offset` gigante é limitado a `2⁶³−1` (`_sql_offset`, `:191`) e custa o mesmo que um `count(*)`. Não há 500 por `bigint`.
   - O `limit 5001` da série (`:120`) limita a memória e a resposta, mas não a CPU do banco: o `group by` agrega a tabela inteira antes do `limit`. Isso é aceitável nessa escala.
   - O volume esperado do projeto é de milhares de linhas, muito abaixo de 1 M. O plano gratuito do Supabase tem 500 MB.
   - As respostas são limitadas: `limit ≤ 500`, ≤ 5 000 buckets e ≤ 500 lotes por página, com o maior corpo medido em 231 KB.
   - O que sobra é o SEC-05-01: falta de `statement_timeout`.
4. **Exposição de dados.**
   - As respostas usam só `InspectionRead`, `MetricsSummary`, `TimeseriesPoint`, `LotSummary` e `Page` de `qc_contracts`, com `response_model` em cada rota.
   - `InspectionRead` traz as colunas da inspeção mais `received_at` e `is_defective`, e nada de `devices`: nem `api_key_hash` nem `last_seen_at`.
   - Não há imagem nem caminho de arquivo (R-02, R-14).
   - **R-06:** `source` aparece em cada item da listagem e `sources` em cada lote, e o filtro `source` funciona nas 4 rotas. O resumo e a série sem `source` somam as duas origens, como a §4.2 define (ver INFO-01).
   - O 422 da validação ecoa só o `input` do próprio chamador. Já o 422 de `from >= to` não tem `input`.
5. **Regra "Erros de banco no log" (`architecture.md` §4).**
   - **Escrita:** o `except (psycopg.DataError, psycopg.IntegrityError)` registra só a rota, o `device_id` e o SQLSTATE. O CA-20 tem restrição real e verifica a ausência do marcador em todo registro DEBUG.
   - **500 genérico:** com um `psycopg.Error` na exceção ou na cadeia, sai uma linha `ERROR` sem `exc_info` e sem mensagem. O SQLSTATE é validado por regex antes de ir para o log. A busca inclui o `__context__` suprimido por `from None` e não entra em loop com ciclos.
   - **Resposta já iniciada:** o middleware relança `RuntimeError(...) from None`, para que o uvicorn não imprima a mensagem do banco.
   - A regra está cumprida. Também conferi que o log por requisição registra o template da rota, nunca a query string nem o header.
6. **Suíte:** `TEST_DATABASE_URL=… uv run pytest -q api/tests` deu **358 passed** (inclui os 63 testes de aceite da SPEC-005 e os da SPEC-004).

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-05-01 | baixa | deploy (disponibilidade) | `api/src/qc_api/db.py:39-47` (`create_pool`) | **As consultas não têm `statement_timeout`.** O pool tem `max_size=5` e espera 5 s por uma conexão; depois responde 503. Localmente, `statement_timeout = 0`. No Supabase, o papel `postgres` não tem timeout próprio e fica sujeito só ao teto global de **2 min** (<https://supabase.com/docs/guides/database/postgres/timeouts>, consultado em 2026-10-17). Quem tem a chave de leitura, ou seja, só o servidor do dashboard, pode ocupar as 5 conexões com leituras sem filtro (1,8 s cada em `/lots` com 1 M linhas localmente, provavelmente mais na CPU compartilhada do plano gratuito). Nesse caso, a escrita da borda recebe 503. Não há perda de dado, porque o outbox da SPEC-009 retém e reenvia, mas o dashboard e a borda competem pelo mesmo pool. O risco é baixo: exige a chave de leitura, que nunca vai para o navegador, e o volume real do projeto é de milhares de linhas. | **Não bloqueia. Vai para a SPEC-015** (configuração de deploy): definir um teto de tempo para as consultas da API, por exemplo `alter role <papel da API> set statement_timeout = '15s'`, documentado no `deployment-plan.md` e conferido em produção com `show statement_timeout`. O valor deve ser medido. O parâmetro `options` na conexão pode não ser repassado pelo pooler em modo transaction, então isso precisa ser verificado antes de escolher entre ele e o `alter role`. Um `QueryCanceled` (`57014`) cai hoje no 500 genérico sem mensagem, que é seguro. Se o architect quiser 503 nesse caso, isso é decisão de SPEC. **Para a SPEC-013:** usar cache com TTL (`st.cache_data`) nas chamadas à API, para não repetir agregações a cada interação. |
| SEC-05-02 | baixa | privacy (log) / input | `api/src/qc_api/repositories/inspections.py:209` (também `:259` e `:281`), via `middleware.py:167` | **RV-01 do review: minha opinião sobre o log.** Uma linha gravada fora da API e fora do contrato (UUID v1, `model_version` fora da regex, `inspected_at = 'infinity'`) gera 500 na listagem. O `logger.exception` registra o `ValidationError` com `input_value`. Conferi o que de fato vai para o log: o pydantic mostra o valor com `repr` e o **trunca** (um `model_version` de 300 caracteres virou `'XXXXXXXXXXXXXXXXXXXXXXXX...XXXXXXXX\nFAKE LOG LINE'`), e o `\n` sai **escapado**. Por isso, não há injeção de linhas no log nem crescimento sem limite. O traceback não inclui variáveis locais (a linha inteira não vai para o log), só os campos que falharam. Esses valores são dados de inspeção que o portador da chave de leitura já veria, e não segredos, chaves, hashes ou imagens. O caso `infinity` já sai sanitizado (`type=DataError sqlstate=-`). O caminho só é alcançável por quem escreve direto no banco, com credencial de dono. **Conclusão:** não é vazamento de dado sensível e não pede uma regra nova de log. O problema real é de integridade e disponibilidade: uma linha ruim derruba toda página que a contém, e a correção é na origem. | **Não bloqueia. Vai para o architect, numa SPEC de manutenção da SPEC-003**, como o reviewer propôs: `check (model_version ~ '^[a-z0-9.-]{3,40}$')`, `check` da versão 4 do `inspection_id` e `check (isfinite(inspected_at))`, com verificação das linhas existentes antes de aplicar. Com essas `check`, o caminho se fecha. **Não recomendo** mudar agora o log do `ValidationError` na leitura. Se o architect quiser defesa em profundidade, a forma aceitável seria registrar só `type=ValidationError`, a rota e os `loc`/`type` dos erros, sem `input_value` (o mesmo padrão de `_error_without_input` em `errors.py`), numa SPEC futura de manutenção da API. É opcional. |
| INFO-01 | info | privacy (R-06) | `api/src/qc_api/repositories/inspections.py` (`summarize`, `timeseries`) | Sem `source`, `summary` e `timeseries` somam `live` e `simulated`, conforme a §4.2. A resposta não diz quais origens entraram. | **Para a SPEC-013:** o dashboard deve sempre mostrar o filtro de origem em vigor ao lado dos indicadores e da série (R-06). Não é achado contra esta SPEC. |
| INFO-02 | info | secrets / deploy | `api/src/qc_api/auth.py:54-61` | A separação entre as chaves é garantida pelo código. A única forma de juntá-las é um erro de operação: definir `READ_API_KEY` com o mesmo valor de uma chave de dispositivo. Trocar a `READ_API_KEY` exige atualizar a API (Render) e o segredo do dashboard (Streamlit) juntos. | **Para a SPEC-015** (`deployment-plan.md`): gerar a `READ_API_KEY` com `python -c "import secrets; print(secrets.token_urlsafe(32))"`, separada das chaves do `register_device.py`, e documentar a ordem da troca (dashboard e API) e a verificação com `curl` (401 sem chave e 200 com chave, sem imprimir a chave). |

Sobre a **RV-03** do review (`sqlstate=None` cru no log da escrita): concordo que é baixa. Não tem impacto de segurança, porque `None` não vaza nada, e a mensagem do servidor não entra. Unificar com `sqlstate_label` fica para a próxima mudança do arquivo.

Sobre os valores literais nos headers dos testes do autor (`{"X-API-Key": "errada"}` em `api/tests/test_filters.py:88` e `api/tests/test_reads.py:115`, e `"r" * 32`): não são credenciais. São os valores que a própria SPEC define (`X-API-Key: errada` no CA-01 e a chave `R = "r"*32` do conjunto D), e o mesmo padrão já existia nos testes da SPEC-004 (`test_inspections.py:106`). Não há achado de R-03. No teste de aceite, o `errada` é montado em tempo de execução.

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | ✅ As 4 rotas exigem `require_read_key` (`secrets.compare_digest` sobre bytes). O 401 é uniforme e vem antes do 422. Sem chave, não há acesso ao banco. A chave de dispositivo é recusada na leitura, e a chave de leitura é recusada na escrita. |
| Entradas validadas (tamanho, tipo de imagem, regex, `extra="forbid"`) | ✅ Os filtros usam as regexes, enums e `UtcDatetime` de `qc_contracts`. `limit` vai de 1 a 500, `offset ≥ 0` (limitado a `2⁶³−1` no SQL), `bucket` é `Literal` e `from < to`. Não há corpo de requisição nem imagem nas rotas novas. Parâmetros desconhecidos são ignorados (§4.1). |
| SQL sempre parametrizado, sem f-string em query | ✅ Fragmentos fixos e `psycopg.sql`, com todo valor como parâmetro (inclusive `bucket` e fuso). Transação `read only`. CA-12 e CA-19 passam. |
| RLS ligado; `DATABASE_URL`/`service_role` só na API | ✅ Sem mudança (SPEC-003). As leituras usam o pool da API. Nada é exposto ao navegador. |
| CORS fechado ou mínimo | ✅ Continua sem middleware de CORS (`main.py`), de propósito. |
| Logs sem segredos e sem payloads de imagem | ✅ O log por requisição registra o template da rota, sem query string e sem chave. Os erros de banco saem só com classe e SQLSTATE (CA-20 e CA-21). O `ValidationError` da leitura (SEC-05-02) registra valores de inspeção truncados e escapados, não segredos. |
| Dependências novas | ✅ Nenhuma (`pyproject.toml` e `uv.lock` inalterados). |
| Deploy: variáveis no provedor, health check, plano free sem cartão | N/A (não há mudança de deploy). Pendência registrada em SEC-05-01 e INFO-02 para a SPEC-015. |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma dependência nova nesta SPEC. |

## Encaminhamentos

| Item | Destino | Bloqueia? |
|---|---|---|
| SEC-05-01 (`statement_timeout`, pool compartilhado) | SPEC-015 (deploy); cache com TTL na SPEC-013 | Não |
| SEC-05-02 = RV-01 (linha fora do contrato; log do `ValidationError`) | Architect: manutenção da SPEC-003 (`check` no banco); log sem `input_value` é opcional, numa SPEC futura da API | Não |
| INFO-01 (origem visível nos agregados) | SPEC-013 | Não |
| INFO-02 (geração e troca da `READ_API_KEY`) | SPEC-015 | Não |

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs. Só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC: os autores são o developer, o tester, o architect, o reviewer e o orchestrator.
- [x] As sondas rodaram num banco temporário próprio (`partqc_test_secprobe`), apagado no fim, com um script fora do repositório. Também apaguei o `partqc_test_secprobe_005` (1 M linhas), que sobrou da execução interrompida deste portão. Não criei nenhum papel.
