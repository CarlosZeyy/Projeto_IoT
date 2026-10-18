# SPEC-027: Manutenção da API, do banco e do simulador (pendências das SPECs 004, 005, 006 e 014)

| Campo | Valor |
|---|---|
| Status | In Review |
| Rodada atual | r2 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-003, SPEC-005, SPEC-014 (e SPEC-004, pelo teste de aceite ajustado na §4.4) |
| Semana alvo | S4 |
| Requisitos cobertos | RNF-06, RNF-09 (CI confiável), R-03, R-04 (o banco espelha o contrato), R-09 |
| ADRs relevantes | ADR-006, ADR-013 |

## 1. Contexto

Esta SPEC junta as pendências de baixa severidade que os portões r1 das SPECs 005, 006 e 014 encaminharam ao architect. Todas são pequenas e locais, e o autor de todas é o `developer`, com exceção da §4.4, que é do `tester`.

1. **Linhas fora do contrato derrubam a leitura** (RV-01 de `reviews/SPEC-005/r1-review-report.md` = SEC-05-02 de `r1-security-report.md`; INFO-01 de `reviews/SPEC-006/r1-security-report.md`). O `001_init.sql` aceita linhas que o contrato recusa: `inspection_id` que não é UUID v4, `model_version` fora da regex e `inspected_at = 'infinity'`. A API nunca grava essas linhas, mas o SQL Editor ou uma migração manual podem gravar. Uma linha assim faz `/inspections`, `/timeseries`, `/lots` e `/metrics/spc` responderem 500 em toda página que a contém. A correção é na origem: `check` novos, por uma migração `002` que confere antes as linhas existentes. `docs/architecture.md` §5 descreve as restrições.
2. **SQLSTATE cru no log da escrita** (RV-03 de `reviews/SPEC-005/r1-review-report.md`). O `_write` registra `exc.sqlstate` como veio (pode sair `sqlstate=None`), enquanto o middleware usa `sqlstate_label`, que valida o formato e usa `-`. São duas regras para o mesmo campo.
3. **Simulador: eco de valores do operador e saídas com traceback** (SEC-01 a SEC-04 de `reviews/SPEC-014/r1-security-report.md` = RV-01 a RV-03 de `r1-review-report.md`):
   - SEC-01: o argparse repete no stderr os tokens que não reconhece (`unrecognized arguments: --api-keyy <CHAVE>`) e o valor inválido de uma opção tipada (`argument --lots: invalid int value: '<CHAVE>'`);
   - SEC-02: cerca de 1 chave em 64 começa com `-`, e `--api-key <CHAVE>` falha; `--api-key=<CHAVE>` e a variável de ambiente funcionam;
   - SEC-03: uma URL com caractere de controle gera `httpx.InvalidURL`, traceback e código 1 (reservado para "item gerado inválido");
   - SEC-04: `--out-of-control-lots` com mais de 4 300 dígitos gera `ValueError`, traceback e código 1.
4. **Teste intermitente da SPEC-004** (RV-02 de `reviews/SPEC-005/r1-review-report.md`). `test_extra_r2_real_server_unencodable_bodies_are_422_and_not_logged`, que sobe um uvicorn real, falhou 1 vez em 3 execuções completas, sem traceback capturado. Um teste intermitente põe em risco o portão de CI (R-09). As causas prováveis estão no próprio teste (corrida de porta, timeout curto para o corpo de 50 000 níveis, asserção `" ERROR " not in log` ampla demais). Só o `tester` pode alterar um teste de aceite, e só com autorização em SPEC.

## 2. Objetivo

O banco recusa as linhas que derrubavam a leitura, a migração não é aplicada sobre dados inválidos, o log da escrita usa o mesmo formato de SQLSTATE do middleware, o simulador nunca repete um valor digitado nem sai com traceback por uso inválido, e os testes com uvicorn real da SPEC-004 passam 30 vezes seguidas.

## 3. Escopo

### 3.1 Dentro

- `infra/migrations/002_contract_checks.sql` (§4.1).
- `api/src/qc_api/routers/inspections.py`: o log de `_write` (§4.2).
- `scripts/simulate.py`: parser, `--api-url` e `--out-of-control-lots` (§4.3); seção "Simulador" do `README.md` da raiz.
- Testes do autor em `infra/tests/`, `api/tests/` e `scripts/tests/`. Os testes do próprio autor que assumem só a `001` em `infra/migrations/` (`infra/tests/test_migrate_db.py`, `test_cli.py`, `test_schema_db.py`) são ajustados pelo developer.
- Testes de aceite: `infra/tests/acceptance/test_spec_027.py` (CA-01 a CA-05), `api/tests/acceptance/test_spec_027.py` (CA-06) e `scripts/tests/acceptance/test_spec_027.py` (CA-07 a CA-11). O CA-12 é manual e fica no test-report.
- **Ajustes autorizados ao tester desta SPEC em testes de aceite de SPECs anteriores** (regra "Testes de aceite de SPECs anteriores" de `docs/architecture.md` §10, introduzida pelo PR #16; até ele entrar na `main`, vale esta autorização explícita). Só estes dois, e nada mais nesses arquivos:
  1. `infra/tests/acceptance/test_spec_003.py`: só as expectativas que dependem de `infra/migrations/` conter apenas a `001`. São as chamadas a `apply_migrations`, `pending_migrations` ou à CLI **com o diretório padrão**, e as leituras de `schema_migrations` depois delas: a fixture `ca01_db`, `test_ca01_apply_on_empty_schema`, `test_ca02_second_apply_is_noop`, o teste da estrutura de `schema_migrations` (`select filename, applied_at ...`), `test_extra_manual_then_runner`, `test_extra_pending_on_empty_schema`, `test_extra_concurrent_runs_apply_once`, `test_extra_cli_apply_success_hides_url` e `test_extra_cli_uses_database_url_env` (nomes na `main` em `169951f`). Neles, o literal `["001"]` passa a ser a lista de versões dos arquivos de `infra/migrations/`, calculada no teste (por exemplo, com `migrate.load_migrations`); a contagem `1` de `schema_migrations` passa a ser o tamanho dessa lista; e a leitura de uma linha de `schema_migrations` filtra `where version = '001'`. A verificação do checksum da `001` continua. Os testes que usam um diretório temporário com a cópia da `001` não mudam, com uma exceção: `test_extra_new_migration_after_existing`, o único que combina esse diretório com a fixture `ca01_db` (SPEC_ISSUE-01 de `reviews/SPEC-027/r1-dev-report.md`). Nele, o diretório temporário recebe a cópia de todos os arquivos `.sql` de `infra/migrations/` (em vez de só a `001`), e `002_more.sql` passa a ser `<N>_more.sql`, em que `<N>` é a próxima versão livre, calculada no teste (a maior versão do diretório padrão mais 1, com 3 dígitos), com o mesmo conteúdo. As asserções passam a ser: `pending_migrations` e `apply_migrations` com esse diretório retornam `[<N>]`, e as versões aplicadas são a lista do diretório padrão seguida de `<N>`. A intenção (a migração nova é aplicada depois das existentes) e o resto do teste não mudam.
  2. `api/tests/acceptance/test_spec_004.py`: `_free_port`, `test_extra_real_server_413_for_declared_and_chunked_bodies` e `test_extra_r2_real_server_unencodable_bodies_are_422_and_not_logged`, só dentro dos limites da §4.4.

  Nenhum CA das SPECs 003 e 004 muda. O número de testes coletados nesses arquivos não muda.

### 3.2 Fora

- Teto da carta p e contrato 0.3.0: SPEC-026.
- `statement_timeout`, `READ_API_KEY`, limites do Render e uso do simulador em produção: SPEC-015.
- Mudar o log do `ValidationError` na leitura para não ter `input_value` (sugestão opcional do SEC-05-02): **não adotado**. Com os `check` desta SPEC, o caminho se fecha na origem, e o security-devops não recomendou a mudança.
- Filtrar caracteres de controle no `detail` do 422 impresso pelo simulador (SEC-06 da SPEC-014, informativo): **não adotado** (a API é a própria, por `https://`).
- Fazer o `register_device.py` evitar chaves que começam com `-` (opcional no SEC-02): **não adotado**. A documentação de `--api-key=<valor>` e a variável de ambiente bastam, e o formato da chave da SPEC-004 não muda.

## 4. Requisitos detalhados

### 4.1 Migração `002_contract_checks.sql`

Mesmas regras da `001` (SPEC-003 §4.1): sem `BEGIN`/`COMMIT` (a transação é do executor), idempotente e aplicável também pelo SQL Editor.

1. **Conferência das linhas existentes**, antes de qualquer `alter table`: um bloco `do $$ ... $$` conta, em `inspections`, as linhas que violariam cada regra do item 2. Se o total de linhas que violam alguma regra for maior que zero, o bloco levanta `raise exception` com a mensagem exata no formato `migration 002: <total> row(s) of inspections violate the new checks (model_version=<a>, inspection_id=<b>, inspected_at=<c>, received_at=<d>); fix or delete them before migrating`. A mensagem tem só contagens, nunca valores de linha. O executor faz o `rollback`, e nada é registrado (SPEC-003 §4.2).
2. **Restrições nomeadas** em `inspections`, cada uma criada só se ainda não existir com esse nome em `pg_constraint` (para essa tabela), num bloco `do $$ ... $$`:

   | Nome | Expressão | Espelha |
   |---|---|---|
   | `inspections_model_version_check` | `model_version ~ '^[a-z0-9.-]{3,40}$'` | `MODEL_VERSION_PATTERN` |
   | `inspections_inspection_id_v4_check` | `inspection_id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'` | `UUID4` do pydantic (versão 4, variante RFC 4122) |
   | `inspections_inspected_at_range_check` | `inspected_at >= timestamptz '0001-01-01 00:00:00+00' and inspected_at < timestamptz '10000-01-01 00:00:00+00'` | `UtcDatetime` (faixa do `datetime` do Python em UTC; recusa `infinity` e `-infinity`) |
   | `inspections_received_at_range_check` | a mesma faixa, para `received_at` | `InspectionRead.received_at` |

3. Nenhuma outra mudança no schema: colunas, índices, RLS e as restrições da `001` ficam como estão.

### 4.2 SQLSTATE no log da escrita (RV-03)

Em `_write`, o `logger.warning` do `except (psycopg.DataError, psycopg.IntegrityError)` passa a usar `sqlstate_label(exc)` (a mesma função do middleware, sem duplicar a regex). O resto da regra da SPEC-005 §4.5 não muda: `rollback`, 422 `{"detail": "Value cannot be stored"}` e o log só com a rota, o `device_id` e o SQLSTATE.

### 4.3 Simulador (`scripts/simulate.py`)

1. **Erros de uso sem eco (SEC-01).** O parser passa a ser uma subclasse de `argparse.ArgumentParser` que sobrescreve `error(message)`. A subclasse:
   - troca a lista de `unrecognized arguments: ...` por `unrecognized arguments: <k> value(s) (not shown)`;
   - troca o valor citado em `invalid <tipo> value: '<valor>'` (e em qualquer outra mensagem do argparse que cite o valor recebido entre aspas) pelo texto `(not shown)`, mantendo o nome da opção (ex.: `argument --lots: invalid int value (not shown)`);
   - mantém o resto: `usage` no stderr e saída com código 2.

   Só `parse_known_args` não basta: ele não cobre o caso `invalid int value` (nota do SEC-01). As mensagens próprias do simulador (`parser.error(...)`) já não repetem valores e continuam assim.
2. **Chave começando com `-` (SEC-02).** O help de `--api-key` e a seção "Simulador" do `README.md` dizem: prefira `SIM_DEVICE_API_KEY`; se passar a chave na linha de comando, use a forma `--api-key=<valor>`, porque uma chave que começa com `-` não funciona com espaço. O comportamento não muda.
3. **URL só com ASCII visível (SEC-03).** `_api_url` recusa, antes do `urlsplit`, qualquer `--api-url` (ou `CLOUD_API_URL`) com um caractere fora de `"!"` a `"~"` (espaço, controle, `DEL` ou não ASCII), com a mensagem `invalid --api-url (not shown)` e código 2. As outras validações da URL não mudam (§4.1 e Histórico da SPEC-014).
4. **Números de lote limitados (SEC-04).** Cada número de `--out-of-control-lots` tem de 1 a 4 dígitos (`[0-9]{1,4}`); senão, a mensagem de lista inválida que já existe e código 2. Zeros à esquerda continuam aceitos (`0007` é o lote 7).
5. Nenhum caminho de uso inválido sai com código 1 nem mostra traceback.

### 4.4 Teste intermitente da SPEC-004 (só o tester)

O tester desta SPEC trabalha em `api/tests/acceptance/test_spec_004.py`, nos dois testes que sobem um uvicorn real e em `_free_port`, nesta ordem:

1. **Diagnóstico:** roda esses dois testes com banco, 20 vezes seguidas, com `-rA --tb=long`, e registra no test-report as falhas e a saída do servidor. Para capturar a saída, pode incluir o fim do log do servidor na mensagem das asserções, trocando antes a chave gerada (`ke`), `READ_KEY` e `NO_DB_PASSWORD` por marcadores.
2. **Correção**, limitada a:
   - **porta:** subir o uvicorn com `--port 0` e ler a porta da linha `Uvicorn running on http://127.0.0.1:<porta>` (com prazo de 20 s, guardando o resto da saída para as asserções finais), **ou** tentar até 3 vezes com uma porta nova quando o uvicorn sair antes de ficar pronto;
   - **timeout:** subir para 60 s só o timeout da requisição com corpo de 50 000 níveis;
   - **`" ERROR " not in log`:** só se o diagnóstico mostrar que a falha vem de uma linha do uvicorn emitida quando o cliente desconecta. Nesse caso, a asserção ignora só essa linha, identificada pelo texto exato e registrada no test-report. Qualquer outra linha `ERROR` continua falhando o teste.
3. **Nada mais muda:** os status esperados (422, ou 400/422 no caso de 50 000 níveis, e 413), as asserções sobre o marcador do corpo, `Traceback`, a chave, `NO_DB_PASSWORD`, o número de linhas e `last_seen_at` ficam iguais.
4. Se o diagnóstico mostrar uma causa fora do teste (um defeito da API), o tester para e registra um `SPEC_ISSUE`, em vez de mudar o teste.

## 5. Critérios de aceite

"Linha válida" é a da SPEC-003 §5. Os testes de banco usam o Postgres 16 de teste, com banco próprio do teste (nome com `test`) quando precisam de schema vazio.

- **CA-01 (aplicação)** — *Dado* um schema `public` vazio, *quando* `apply_migrations(conninfo)` roda com o diretório padrão, *então* retorna a lista de versões dos arquivos de `infra/migrations/`, cujos dois primeiros itens são `"001"` e `"002"`; `schema_migrations` tem uma linha por versão, e as linhas de `001` e `002` têm o SHA-256 do próprio arquivo; e as 4 restrições da §4.1 existem em `inspections` com `contype = 'c'`.
- **CA-02 (idempotência)** — *Dado* o banco do CA-01, *quando* `apply_migrations` roda de novo, *então* retorna `[]`; e *quando* o conteúdo de `002_contract_checks.sql` é executado diretamente duas vezes (simulando o SQL Editor), *então* não há erro e o conjunto `(conname, pg_get_constraintdef)` de `inspections` fica igual.
- **CA-03 (recusas e limites)** — *Dado* o banco migrado, *quando* se insere uma linha válida com `model_version` igual a `'MODEL_X'`, `'ab'`, `'a' * 41` ou `'sim-v0\n'`; ou com `inspection_id` igual a `str(uuid.uuid1())` ou `'00000000-0000-0000-0000-000000000000'`; ou com `inspected_at` igual a `'infinity'`, `'-infinity'` ou `'10000-01-01T00:00:00Z'`; ou com `received_at = 'infinity'`, *então* cada `insert` falha com `CheckViolation` (`23514`); e com `model_version='partqc-mnv3-v1'`, `inspection_id=str(uuid.uuid4())` e `inspected_at` igual a `'0001-01-01T00:00:00Z'` ou `'9999-12-31T23:59:59.999999Z'`, o `insert` funciona.
- **CA-04 (espelho do contrato)** — *Dado* o banco migrado, *quando*, para cada par de dígitos hexadecimais `V` e `W`, se insere uma linha válida com `inspection_id = f"12345678-1234-{V}234-{W}234-123456789abc"`, *então* o `insert` funciona se e somente se `pydantic.TypeAdapter(pydantic.UUID4).validate_python(<o texto>)` aceita, e isso acontece exatamente quando `V == "4"` e `W` está em `89ab`; e, para cada `model_version` da lista `["abc", "a.b", "...", "a" * 40, "a" * 41, "ab", "ABC", "abc\n", "ab c", "ábc", "a_b"]`, o `insert` funciona se e somente se `re.fullmatch(qc_contracts.MODEL_VERSION_PATTERN, valor)` casa.
- **CA-05 (conferência antes de migrar)** — *Dado* um diretório temporário com cópias de `001_init.sql` e `002_contract_checks.sql`, um banco em que só a `001` foi aplicada e três linhas gravadas por SQL direto (uma com `model_version='MODEL_X'`, uma com `inspection_id = str(uuid.uuid1())` e uma com `inspected_at = 'infinity'`), *quando* `apply_migrations` roda com esse diretório, *então* levanta `MigrationError` cuja mensagem contém `migration 002: 3 row(s) of inspections violate the new checks` e `model_version=1`, e não contém `MODEL_X` nem o UUID v1; `schema_migrations` continua só com `001`; nenhuma das 4 restrições existe; e as 3 linhas continuam lá. *Quando* as 3 linhas são apagadas e `apply_migrations` roda de novo, *então* retorna `["002"]`.
- **CA-06 (RV-03)** — *Dado* o app da API com `insert_inspections`, como usado em `qc_api.routers.inspections`, substituído no teste (`monkeypatch`) por uma função que levanta, em cada caso, `psycopg.IntegrityError("x")` (sem SQLSTATE), `psycopg.DataError("y")` (sem SQLSTATE) e `psycopg.errors.CheckViolation()` (SQLSTATE `23514`), *quando* `POST /api/v1/inspections` recebe um payload válido com a chave de `edge-01`, *então* cada resposta é 422 com o corpo exato `{"detail": "Value cannot be stored"}`; o registro `WARNING` contém `sqlstate=-`, `sqlstate=-` e `sqlstate=23514`, respectivamente; e nenhum registro contém `sqlstate=None`.
- **CA-07 (SEC-01, sem eco)** — *Dado* `S = "Z" + secrets.token_urlsafe(32)` gerado no teste, *quando* `main` roda com `--dry-run` e cada um destes `argv`: `["--api-keyy", S]`, `["--api-keyy=" + S]`, `[S]`, `["--lots", S]`, `["--lot-size", S]`, `["--seed", "x" + S]`, `["--defect-rate", S]`, `["--unknown-rate", S]`, `["--start", S]`, `["--out-of-control-lots", S]`, `["--device-id", S]` e `["--model-version", S + "!"]`, *então* o código é 2; `S` não aparece no stdout, no stderr nem nos registros do `caplog`; o stderr não contém `Traceback`; ele contém `unrecognized arguments` nos 3 primeiros casos e o nome da opção (`--lots`, `--lot-size`, `--seed` etc.) nos demais. E `["--help"]` dá código 0 com `usage:` no stdout.
- **CA-08 (SEC-02)** — *Dado* o `README.md` e o texto de `--help` do simulador, *então* os dois contêm `--api-key=`; e *dado* uma chave que começa com `-` (gerada no teste), *quando* `main` roda com `--api-key=<chave>` (e, em outro caso, com a chave em `SIM_DEVICE_API_KEY`), uma URL `https://` e a API falsa (`httpx.MockTransport`), *então* o código é 0 e o header `X-API-Key` enviado é a chave.
- **CA-09 (SEC-03)** — *Dado* `--api-url` igual a `"http://local\nhost:8001"`, `"https://exa\x01mple.com"`, `"https://example.com/\t"`, `"https://exa mple.com"`, `"https://exämple.com"`, `"https://example.com\x7f"` ou `"https://example.com\x1b[31m"`, *quando* `main` roda sem `--dry-run`, com chave válida, *então* o código é 2, a API falsa recebe 0 requisições, o stderr contém `invalid --api-url (not shown)` e não contém `Traceback`, `mple.com` nem `host:8001`; e com `https://api.example.org` e `http://127.0.0.1:8001`, o envio segue normalmente (código 0).
- **CA-10 (SEC-04)** — *Dado* `--dry-run --lots 10` e `--out-of-control-lots` igual a `"1" * 5000` ou `"12345"`, *então* o código é 2 e o stderr não contém `Traceback`; e com `--out-of-control-lots 3,0007 --seed 42`, a saída é idêntica byte a byte à de `--out-of-control-lots 3,7 --seed 42`.
- **CA-11 (nenhum código 1 por uso inválido)** — *Dado* todos os `argv` inválidos do CA-08 da SPEC-014 e dos CA-07, CA-09 e CA-10 desta SPEC, *quando* `main` roda, *então* nenhum termina com código 1.
- **CA-12 (manual, tester, RV-02 da SPEC-005)** — 1. Com o Postgres de teste no ar, rodar 30 vezes seguidas `uv run pytest -q api/tests/acceptance/test_spec_004.py -k "real_server"` (um laço no shell, não um teste que roda pytest); 2. as 30 execuções terminam com 0 falhas; 3. rodar a suíte inteira uma vez; 4. registrar no test-report o comando, as 30 contagens, o diagnóstico da §4.4 e a correção aplicada.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Migração `002` (aplicação, idempotência, recusas, conferência); log de `_write`; parser, URL e números de lote do simulador | `infra/tests/`, `api/tests/`, `scripts/tests/` |
| Aceite (tester) | CA-01 a CA-05 (`db`) | `infra/tests/acceptance/test_spec_027.py` |
| Aceite (tester) | CA-06 (`db`) | `api/tests/acceptance/test_spec_027.py` |
| Aceite (tester) | CA-07 a CA-11 | `scripts/tests/acceptance/test_spec_027.py` |
| Manual (tester) | CA-12 e os ajustes autorizados da §3.1 | test-report |

Só fronteiras são mockadas: a API falsa do simulador (`httpx.MockTransport`, como na SPEC-014) e, no CA-06, a função de escrita (as exceções do psycopg sem SQLSTATE só podem ser construídas no cliente; precedente: CA-21 da SPEC-005). O simulador é importado com `importlib.util.spec_from_file_location`, como na SPEC-014. Nenhum teste usa rede real nem roda pytest em subprocesso (§10).

## 7. Riscos e notas para o implementador

- **`%` no arquivo SQL:** o executor roda o arquivo sem parâmetros (protocolo simples), então o `%` do `raise exception` não é interpretado pelo psycopg. Confira com o CA-05.
- **`inspection_id::text`:** o `uuid` do Postgres sai sempre em minúsculas e com hífens, então a regex não precisa de `[A-F]`. Se o CA-04 mostrar que o `UUID4` do pydantic instalado aceita outra variante (`W` fora de `89ab`), pare e registre `SPEC_ISSUE`: o `check` tem de espelhar o contrato, e a leitura (`InspectionRead`) também precisa aceitar a linha.
- **Faixa das datas:** os limites espelham o `UtcDatetime` em UTC. Numa sessão com `TimeZone` diferente de UTC, o psycopg converte para o fuso da sessão, e uma data em `0001-01-01` pode sair do intervalo do Python. A API e o Supabase usam UTC. Esse caso extremo continua sendo o 500 genérico, sem a mensagem, e é aceito.
- **Conferência e concorrência:** entre a contagem e o `alter table`, a API só grava linhas válidas, e o próprio `add constraint` valida a tabela inteira. A conferência existe para dar uma mensagem clara, sem valores, em vez do `Failing row contains (...)` do servidor.
- **Produção:** a `002` é aplicada pelo CA-19 da SPEC-015, junto com a `001`. Num banco ainda vazio, a conferência passa direto.
- **Argparse:** as mensagens que citam valores vêm de `_get_value` (`invalid %(type)s value: %(value)r`) e de `parse_args` (`unrecognized arguments: %s`). Teste a subclasse com os três formatos do SEC-01 (opção errada, valor solto, valor na opção errada).
- A §4.4 depende do diagnóstico. Não aumente timeouts nem afrouxe asserções além do que a §4.4 permite.

## 8. Definição de pronto

- [ ] Todos os CAs automatizados com teste de aceite passando (test-report PASS) e o CA-12 registrado
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `README.md` (seção "Simulador") atualizado
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-17 | Criação (`Draft`) e `Draft` → `Ready`, com aprovação humana. | Pendências dos relatórios das SPECs 005, 006 e 014 | Humano (Carlos), via orquestrador |
| 2026-10-17 | §3.1 item 1: `test_extra_new_migration_after_existing` (SPEC-003) entra nos ajustes autorizados ao tester, com a saída (a): copiar todos os `.sql` de `infra/migrations/` para o diretório temporário e usar a próxima versão livre, calculada no teste, em vez de `002_more.sql`. Os demais testes de aceite da SPEC-003 com diretório temporário usam `empty_db` e não precisam de ajuste. Nenhum CA da SPEC-003 muda de intenção. | SPEC_ISSUE-01 de `reviews/SPEC-027/r1-dev-report.md` (com a `002` real registrada pela `ca01_db`, o teste dava `checksum mismatch for 002`) | Orquestrador |
| 2026-10-17 | Correção do SPEC_ISSUE-01 reaprovada; `Blocked` → `In Test`, retomando a r1. | Fluxo do loop (§4 da skill `features`) | Humano (Carlos) |
