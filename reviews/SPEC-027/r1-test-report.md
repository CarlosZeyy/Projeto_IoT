# SPEC-027 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-027](../../docs/specs/SPEC-027-manutencao-api-banco-simulador.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `a619da1` (código do developer em `45fdb19`, `2db2a22` e `13a5b29`); testes do tester em `9b8ff6f`, `732bf6f` e `efe5d8f` |
| **Veredicto** | **PASS** |

Os testes foram escritos a partir da SPEC (caixa-preta), antes da leitura da implementação. Depois disso, li o diff de produção e acrescentei casos exploratórios. Fronteiras mockadas: a API falsa do simulador (`httpx.MockTransport`) e, no CA-06, `insert_inspections` como usado em `qc_api.routers.inspections`. Os testes não usam rede real, não rodam pytest em subprocesso e não têm credencial literal: `S`, as chaves e os marcadores são gerados com `secrets`/`uuid` em tempo de execução, e a conninfo do banco temporário é montada com `make_conninfo`.

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `infra/tests/acceptance/test_spec_027.py::test_ca01_apply_on_empty_schema` | ✅ |
| CA-02 | `infra/tests/acceptance/test_spec_027.py::test_ca02_idempotent_runner_and_sql_editor` | ✅ |
| CA-03 | `infra/tests/acceptance/test_spec_027.py::test_ca03_refusals` (10 casos: `CheckViolation`, `23514` e o nome da restrição), `::test_ca03_limits_accepted` (2 casos) | ✅ |
| CA-04 | `infra/tests/acceptance/test_spec_027.py::test_ca04_inspection_id_check_mirrors_pydantic_uuid4` (256 pares `V`/`W`; aceitos exatamente `4`+`8/9/a/b`), `::test_ca04_model_version_check_mirrors_contract` | ✅ |
| CA-05 | `infra/tests/acceptance/test_spec_027.py::test_ca05_refuses_invalid_rows_with_counts_only` | ✅ |
| CA-06 | `api/tests/acceptance/test_spec_027.py::test_ca06_write_log_uses_the_sqlstate_label` | ✅ |
| CA-07 | `scripts/tests/acceptance/test_spec_027.py::test_ca07_usage_errors_never_echo_the_value` (12 casos), `::test_ca07_help_exits_0_with_usage` | ✅ |
| CA-08 | `scripts/tests/acceptance/test_spec_027.py::test_ca08_readme_and_help_document_the_equals_form`, `::test_ca08_help_keeps_the_equals_form_at_any_width` (4 larguras), `::test_ca08_key_starting_with_dash_in_the_equals_form`, `::test_ca08_key_starting_with_dash_in_the_environment` | ✅ |
| CA-09 | `scripts/tests/acceptance/test_spec_027.py::test_ca09_api_url_outside_visible_ascii_is_refused` (7 casos), `::test_ca09_visible_ascii_url_still_sends` (2 casos) | ✅ |
| CA-10 | `scripts/tests/acceptance/test_spec_027.py::test_ca10_lot_numbers_with_more_than_4_digits_exit_2` (2 casos), `::test_ca10_leading_zeros_give_the_same_bytes` | ✅ |
| CA-11 | `scripts/tests/acceptance/test_spec_027.py::test_ca11_no_invalid_usage_exits_with_code_1` (37 `argv`: os 8 do CA-08 da SPEC-014 em `--dry-run` e com envio, os 12 do CA-07, os 7 do CA-09 e os 2 do CA-10; todos com código 2) | ✅ |
| CA-12 (manual) | 30 execuções seguidas de `uv run pytest -q api/tests/acceptance/test_spec_004.py -k "real_server"`, todas sem falhas, e a suíte inteira (ver "CA-12" abaixo) | ✅ |

Notas sobre a cobertura:

- **CA-07, pré-condição comum:** o arquivo define `SIM_DEVICE_ID=sim-01` no ambiente, como indicado no dev-report. O simulador confere o `device_id` antes das outras opções (ordem herdada da SPEC-014). Sem a variável, os casos `--start`, `--out-of-control-lots` e `--model-version` terminam com código 2, sem ecoar `S`, mas a mensagem cita `--device-id` em vez da opção do caso (conferido à parte). Com a variável, o caso `["--device-id", S]` continua sendo testado, porque o argumento prevalece sobre ela. Ver OBS-01.
- **CA-10:** "saída" foi lida como o stdout (as linhas JSON), comparado byte a byte. O resumo no stderr inclui a seed e a contagem, que são iguais nos dois casos.
- **CA-03:** além do SQLSTATE, cada recusa confere `diag.constraint_name` contra o nome da tabela da §4.1, para garantir que a recusa vem da restrição nova, e não de outra.
- **Teste de mutação (CA-06):** com um plugin no scratchpad, troquei `sqlstate_label` por `str(exc.sqlstate)` só no processo de teste. O CA-06 e 2 extras passaram a falhar. Os testes detectam a regressão do RV-03.

## Suíte completa

```text
uv run ruff check .                 -> All checks passed!
uv run ruff format --check .        -> 116 files already formatted

uv run pytest -q (sem TEST_DATABASE_URL)
  -> 2093 passed, 642 skipped, 1 warning in 176.02s

TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
  -> 2735 passed, 1 warning in 345.74s (0:05:45)

Testes novos desta SPEC (tester): 156
  infra/tests/acceptance/test_spec_027.py    48 (17 de CA + 31 extras), todos db
  api/tests/acceptance/test_spec_027.py       7 (1 de CA + 6 extras), todos db
  scripts/tests/acceptance/test_spec_027.py 101 (33 de CA + 68 extras), sem banco
```

O único aviso é o `StarletteDeprecationWarning` do `fastapi.testclient`, que já existia. Depois das execuções, o servidor de teste tem só `partqc_test`, `postgres`, `template0` e `template1`: o banco temporário `partqc_test_acc027`, criado pelo módulo da `infra`, foi removido.

## Ajustes em testes de aceite de SPECs anteriores

Regra "Testes de aceite de SPECs anteriores" (`docs/architecture.md` §10, PR #16) e autorização explícita da §3.1 desta SPEC. Cada arquivo foi ajustado num commit próprio do tester. Nenhum CA das SPECs 003 e 004 mudou. O número de testes coletados não mudou: 114 em `test_spec_003.py` e 81 em `test_spec_004.py`, antes e depois.

### `infra/tests/acceptance/test_spec_003.py` (commit `732bf6f`; SPEC-027 §3.1 item 1 e §4.1)

Motivo comum: com a `002_contract_checks.sql` em `infra/migrations/` (§4.1), o diretório padrão passou a ter mais de uma versão. Antes dos ajustes, com banco, o arquivo dava 6 falhas e 5 erros. Depois, 114 passed.

| Teste | Asserção antes → depois |
|---|---|
| (apoio) imports e helper | `from migrate import apply_migrations, pending_migrations` → também `load_migrations`; novo `_default_versions()` = `[m.version for m in load_migrations(MIGRATIONS_DIR)]` (a lista "calculada no teste" da §3.1) |
| fixture `ca01_db` | `apply_migrations(empty_db) == ["001"]` → `== _default_versions()` |
| `test_ca01_apply_on_empty_schema` | `apply_migrations(empty_db) == ["001"]` → `== _default_versions()`; `select version, checksum from schema_migrations` → `... where version = '001'` (a verificação do checksum da `001` continua: `rows == [("001", sha256(001_init.sql))]`) |
| `test_ca02_second_apply_is_noop` | `_count(conn, "schema_migrations") == 1` → `== len(_default_versions())` |
| `test_extra_schema_migrations_columns` (estrutura de `schema_migrations`) | `select filename, applied_at from schema_migrations` → `... where version = '001'` |
| `test_extra_manual_then_runner` | `apply_migrations(empty_db) == ["001"]` → `== _default_versions()` |
| `test_extra_pending_on_empty_schema` | `pending_migrations(empty_db) == ["001"]` → `== _default_versions()` |
| `test_extra_new_migration_after_existing` (SPEC_ISSUE-01, saída (a) aprovada) | cópia só de `001_init.sql` → cópia de todos os `.sql` de `infra/migrations/`; `002_more.sql` → `<N>_more.sql`, com `N = f"{int(versions[-1]) + 1:03d}"` e o mesmo conteúdo; `pending`/`apply == ["002"]` → `== [N]`; versões aplicadas `["001", "002"]` → `[*versions, N]` |
| `test_extra_concurrent_runs_apply_once` | `repr(["001"])` → `repr(_default_versions())`; `_count(schema_migrations) == 1` → `== len(_default_versions())` |
| `test_extra_cli_apply_success_hides_url` | `_applied_versions(conn) == ["001"]` → `== _default_versions()` (o `"001" in out` e o `SECRET not in out` não mudaram) |
| `test_extra_cli_uses_database_url_env` | `_applied_versions(conn) == ["001"]` → `== _default_versions()` |

`test_ca03_rerunning_sql_file_changes_nothing` e `test_ca21_cli_status_lists_applied` só falhavam pela fixture `ca01_db`, e o corpo deles não mudou. Nenhuma outra linha do arquivo mudou.

### `api/tests/acceptance/test_spec_004.py` (commit `efe5d8f`; SPEC-027 §4.4)

| Teste / trecho | Antes → depois | Requisito |
|---|---|---|
| `_free_port` | Função que fazia `bind` na porta 0, lia o número e **liberava** a porta antes de o uvicorn subir → substituída por `_start_uvicorn(env, *hidden)`, que sobe `uvicorn qc_api.main:app --port 0` e lê a porta da linha `Uvicorn running on http://127.0.0.1:<porta>`, com prazo de 20 s. Uma thread guarda toda a saída para as asserções finais. Se a linha não aparecer, a função levanta `AssertionError` com as mesmas mensagens de antes (`uvicorn exited` / `uvicorn did not start`), agora seguidas do fim do log. Também foram criadas `_stop_uvicorn` (`terminate`, `wait` e retorno da saída inteira, no lugar de `communicate`) e `_log_tail` (fim do log com `ke`, `READ_KEY` e `NO_DB_PASSWORD` trocados por `<KE>`, `<READ_KEY>` e `<NO_DB_PASSWORD>`). | §4.4 item 2, "porta" (opção `--port 0`); §4.4 item 1 (log nas mensagens) |
| `test_extra_real_server_413_for_declared_and_chunked_bodies` | `_free_port()` + `Popen` + laço de `create_connection` → `_start_uvicorn(env)`; `proc.terminate(); communicate()` → `_stop_uvicorn(server)`. As requisições e as asserções (`413`, `< 4 s`, `NO_DB_PASSWORD + "@"`, `READ_KEY`) não mudaram. | §4.4 item 2, "porta" |
| `test_extra_r2_real_server_unencodable_bodies_are_422_and_not_logged` | Mesma troca da subida e da parada. Só a requisição de 50 000 níveis ganhou `timeout=60`; as demais continuam com 10 s. As asserções de status (`(400, 422)` para `deep-50000` e `(422,)` para as outras), `Traceback` e `" ERROR "` ganharam o `_log_tail(log, ke)` como **mensagem**, com a condição igual. As asserções sobre o marcador, `ke`, o número de linhas e `last_seen_at` não mudaram. | §4.4 item 2, "porta" e "timeout"; §4.4 item 1 |

A asserção `" ERROR " not in log` **não** foi alterada: o diagnóstico não mostrou nenhuma linha `ERROR` do uvicorn (§4.4 item 2, terceiro ponto, não se aplica).

## CA-12 e diagnóstico da §4.4

**1. Diagnóstico (antes de qualquer correção).** Instrumentei temporariamente os dois testes, sem commit, depois desfeito com `git checkout`. No `finally`, eles imprimiam o fim do log do servidor (com `ke`, `READ_KEY` e `NO_DB_PASSWORD` trocados por marcadores) e o tempo de cada requisição com corpo aninhado. Comando, com o Postgres de teste no ar:

```bash
export TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test
for i in $(seq 1 20); do
  uv run pytest -q -rA --tb=long api/tests/acceptance/test_spec_004.py -k "real_server" -p no:cacheprovider
done
```

- **20 execuções isoladas:** 20 × `2 passed`, 0 falhas.
- **20 execuções com a CPU saturada** (8 laços `while True: pass` em 4 núcleos, para reproduzir a carga da suíte completa em que a falha original apareceu): 20 × `2 passed`, 0 falhas.
- **Log do servidor nas 40 execuções:** nenhuma linha `ERROR`, `WARNING` ou `Traceback`. O processo sempre terminou pelo `terminate` (`rc=-15`), com `Shutting down` / `Application shutdown complete`. Os status foram os esperados: 422 nos demais casos e 400 em `deep-50000`.
- **Tempo da requisição de 50 000 níveis:** no máximo 0,014 s sem carga e 0,026 s com carga (o limite era 10 s). Com a carga, o caso mais lento entre todos os corpos aninhados levou 0,061 s.
- **A falha não se reproduziu** em 40 execuções. A causa restante está no próprio teste. Li `uvicorn/server.py` (0.54.0): `startup()` roda `lifespan.startup()` (que abre o pool do psycopg e faz conexões de saída com portas efêmeras) **antes** de `create_server` (o bind). Com o `_free_port()`, a porta escolhida ficava livre durante a partida do interpretador, os imports e a abertura do pool. Nessa janela, qualquer conexão de saída da máquina (inclusive as do próprio pool) ou outro processo podia ocupá-la. O resultado seria o uvicorn sair com `address already in use`, ou o teste falar com outro servidor. É uma corrida estrutural e rara, compatível com "1 falha em 3 execuções completas, sem traceback do servidor".
- **Nenhum defeito da API apareceu** (§4.4 item 4): não há `SPEC_ISSUE`.

**2. Correção aplicada** (commit `efe5d8f`, tabela acima): `--port 0` com a porta lida da linha `Uvicorn running on http://127.0.0.1:<porta>` (prazo de 20 s, saída guardada para as asserções), e timeout de 60 s só na requisição de 50 000 níveis. O diagnóstico não indicou o timeout como causa (26 ms medidos contra 10 s de limite). Ele foi aplicado porque está na lista fechada da §4.4 e protege runners de CI mais lentos sem afrouxar nenhuma asserção. A asserção `ERROR` ficou como estava. Antes da rodada, testei à parte o caminho de falha de `_start_uvicorn`: com o app sem `DATABASE_URL`, ele levanta `AssertionError: uvicorn exited` em 1,4 s, com o fim do log.

**3. CA-12, as 30 execuções** (laço no shell, comando exato da SPEC, rodado por mim, depois do commit da correção):

```bash
export TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test
for i in $(seq 1 30); do
  uv run pytest -q api/tests/acceptance/test_spec_004.py -k "real_server"
done
```

| Execuções | Resultado de cada uma | Falhas |
|---|---|---|
| 1 a 30 | `2 passed, 79 deselected, 1 warning` (entre 2,97 s e 4,10 s) | **0** |

**4. Suíte inteira, uma vez:** com banco, 2735 passed (ver "Suíte completa"). Os dois testes com uvicorn real passaram dentro da suíte completa.

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

**Migração `002` (`infra`, 31 extras, todos passando):**

- **Mensagem exata da recusa:** confere o formato completo da §4.1 (`... (model_version=1, inspection_id=1, inspected_at=1, received_at=0); fix or delete them before migrating`).
- **Uma linha que viola 3 regras e outra que viola 1, mais uma válida:** `total=2`, com cada contagem por regra correta. O total conta linhas, não violações.
- **A mensagem não traz valores de linha:** nem o `model_version`, nem o UUID v1, nem o `lot_id` marcador, nem `edge-01`, nem `Failing row`, em `str`, `repr` e na causa da exceção. O `%` do `raise` não é interpretado pelo psycopg.
- **Nada fica pela metade:** o arquivo `002` rodado à mão sobre uma linha inválida (`received_at = 'infinity'`), numa transação explícita (SQL Editor) e em autocommit, levanta `RaiseException` com a mensagem de contagens. O snapshot do schema (colunas, restrições, índices, RLS e políticas) e o `schema_migrations` ficam idênticos.
- **Linhas válidas existentes:** são mantidas, e a `002` aplica.
- **Restrição preexistente com o mesmo nome:** é mantida, e as outras 3 são criadas (`if not exists` por nome em `pg_constraint`).
- **Aplicação manual seguida do executor:** `001` e `002` aplicadas à mão e depois o executor não dão erro, e `pending == []`.
- **Nenhuma outra mudança no schema (§4.1.3):** colunas, índices, RLS e políticas iguais; as restrições da `001` mantidas; só as 4 novas acrescentadas. As 4 restrições estão validadas (`convalidated = true`, nenhuma `NOT VALID`).
- **O arquivo não tem `BEGIN`, `COMMIT`, `ROLLBACK` nem `START TRANSACTION`.**
- **Limites com a sessão em `America/Sao_Paulo`:** `0001-01-01T00:00:00Z` e `9999-12-31T23:59:59.999999Z` são aceitos em `inspected_at` e `received_at`. O `check` compara instantes.
- **Mais recusas, todas com a restrição certa:**
  - `received_at` com `-infinity` e com `10000-01-01Z`;
  - `inspected_at` com `0001-12-31 BC`, com `0001-01-01T00:00:00+01:00` (1 a.C. em UTC) e com `10000-01-01T00:00:00-01:00`;
  - `9999-12-31T23:59:59.999999-03:00`, que em UTC é 10000-01-01T02:59Z;
  - `model_version` com tab, espaço no fim e vazio;
  - UUID todo `f` e variante `c`.
- **Aceitos, como no contrato:** UUID v4 em maiúsculas e entre chaves (o Postgres normaliza, e o pydantic também aceita); `0001-01-01T03:00:00+03:00` (exatamente o limite inferior); `model_version` com 40 caracteres e com `0.0`.
- **Erros meus corrigidos no próprio teste, sem relação com o código:** usei o ano `0000`, que o Postgres não aceita (`DatetimeFieldOverflow`), e o instante `10000-01-01T00:00:00+01:00`, que é 9999-12-31T23:00Z e fica dentro da faixa.

**Log da escrita (`api`, 6 extras, todos passando):**

- A rota `batch` usa o mesmo rótulo nos 3 casos.
- O log não traz a mensagem da exceção (marcador aleatório), o `lot_id`, a chave, `Traceback` nem `exc_info`. O `WARNING` traz `edge-01`.
- `NumericValueOutOfRange` sai com `sqlstate=22003`.
- Depois de uma escrita recusada, `last_seen_at` continua `NULL` e nenhuma linha é gravada.

**Simulador (`scripts`, 68 extras, todos passando):**

- **Sem eco e sem traceback, sempre com código 2:**
  - `--lots=S`, `--lot-size-min S`, `--lot-size-max S`, `--dry-run=S` (`ignored explicit argument`) e `--defect-rate=S`;
  - valores soltos com espaços;
  - valor com `'`, valor com `"'\` (repr com aspas duplas e escapes), valor com unicode, valor com 2 200 caracteres e valor com `\n` no meio;
  - `--api-key -S` (`expected one argument`), opção sem valor no fim e `-- S`.
- **Abreviações:** `--api=S`, `--lot=S`, `--api S` e `--lot-size-m=S` viram `unrecognized arguments: <k> value(s) (not shown)`, porque o parser usa `allow_abbrev=False` e o argparse nunca chega à mensagem `ambiguous option: <token>`, que citaria o token cru.
- **Contagem e formato:** a contagem de `unrecognized arguments` é exata (4 valores, um deles com espaços). O formato `argument --lots: invalid int value (not shown)` vem com `usage:` no stderr.
- **`-h<S>`:** o argparse mostra o help (código 0), sem ecoar `S`. Ver OBS-03.
- **Números grandes ou inválidos em outras opções:** `--lots`, `--lot-size` e `--seed` com 5 000 dígitos, `--lot-size-min` com 4 400 dígitos, `--defect-rate nan`/`inf`, `--unknown-rate 1e400`/`-1e-7`, `--lots 0`/`501` e `--seed -1` dão código 2, sem traceback. Uma `--seed` com 4 000 dígitos (abaixo do limite de conversão do Python) não quebra.
- **URLs com caractere inválido:** URL com `\x01`, `\n` no fim, espaço no início, `é` no caminho, `​` ou `\x00` dá `invalid --api-url (not shown)`, 0 requisições, e o host (gerado a partir de `S`) não aparece. O mesmo vale para `CLOUD_API_URL` com `\x01`, `\n` no fim ou `ä`.
- **URLs ASCII malformadas:** nunca saem com código 1 nem com traceback. Com `https://xn--zz.com`, `https://[::1`, `https://[zz]/`, porta `99999` ou porta `-1`, o código é 2 (`invalid --api-url (not shown)`). Com `-bad-.example.org`, `exa..mple.com`, `.example.com`, porta vazia, rótulo de 64 caracteres ou host com 400 caracteres, a validação aceita, e a API falsa responde (código 0). Ver OBS-04.
- **Listas de lotes inválidas (código 2):** `0000`, `00000`, `1,99999`, dígito de largura total `３`, dígito arábico `٣`, `1,,2`, `+7`, `-7`, `1_0` (que `int()` aceitaria como 10) e `7 7`. A regex `[0-9]{1,4}` com `fullmatch` só aceita dígitos ASCII.
- **Zeros à esquerda:** `0010` dá a mesma saída que `10`.
- **Espaços em volta de cada item:** `" 3, 0007 "` dá a mesma saída que `3,7`. Ver OBS-02.
- **Documentação:** o help e a seção "Simulador" do `README.md` citam `SIM_DEVICE_API_KEY` e `--api-key=`, e o help mantém `--api-key=` inteiro com `COLUMNS` 40, 60, 80 e 200.
- **Chave que começa com `-`:** não aparece (nem ela, nem ela sem o `-`) no stdout, no stderr ou no log de um envio com sucesso.

**Observações (não são bugs):**

- **OBS-01 (CA-07):** o simulador valida o `device_id` antes das outras opções (ordem herdada da SPEC-014). Sem `SIM_DEVICE_ID`/`--device-id`, os casos `--start`, `--out-of-control-lots` e `--model-version` saem com código 2, sem eco, mas a mensagem cita `--device-id`. O teste usa `SIM_DEVICE_ID=sim-01` como contexto comum, como sugere o dev-report. A intenção do CA (nenhum eco, e a mensagem cita a opção com problema) foi verificada. Se o architect quiser que o CA-07 dispense o `device_id`, é ajuste de texto, não de código.
- **OBS-02:** os espaços em volta dos itens de `--out-of-control-lots` são ignorados (`part.strip()`), comportamento igual ao da `main` (conferido rodando o `simulate.py` da `main`). A §4.3.4 fala de "cada número", e o número continua com 1 a 4 dígitos.
- **OBS-03:** `-h<valor>` mostra o help com código 0. É o comportamento padrão do argparse, e não há eco.
- **OBS-04:** hosts ASCII sintaticamente estranhos (`-bad-`, `..`, rótulo com mais de 63 caracteres) passam por `_api_url`. Com a API real, terminariam em erro de rede (código 5), não em código 1 nem em traceback. A SPEC não pede essa validação.
- **OBS-05:** uma `CLOUD_API_URL` com espaço ou `\n` no fim (por exemplo, vinda de um `.env`) passa a ser recusada, com `invalid --api-url (not shown)`, o que é consequência direta da §4.3.3. O dev-report (decisão 5) e o README ("só caracteres ASCII visíveis, sem espaço") registram isso.

## SPEC_ISSUE (se houver)

Nenhum. O SPEC_ISSUE-01 do dev-report já tinha sido resolvido em `e015926` e foi aplicado como autorizado (linha de `test_extra_new_migration_after_existing` na tabela acima).

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` (`infra/tests/acceptance/test_spec_027.py`, `api/tests/acceptance/test_spec_027.py`, `scripts/tests/acceptance/test_spec_027.py` e os ajustes autorizados em `infra/tests/acceptance/test_spec_003.py` e `api/tests/acceptance/test_spec_004.py`) e este relatório.
