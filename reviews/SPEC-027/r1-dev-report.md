# SPEC-027 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-027](../../docs/specs/SPEC-027-manutencao-api-banco-simulador.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-027-manutencao-api` |
| Commits | `45fdb19`, `2db2a22`, `13a5b29` (e o commit deste relatório) |

## Resumo

- **Migração `002` (§4.1):** `infra/migrations/002_contract_checks.sql`, sem `BEGIN`/`COMMIT`, com um único bloco `do $$ ... $$`. Primeiro ele conta, em `inspections`, as linhas que violam cada regra e o total (cada linha conta uma vez). Se o total for maior que zero, faz `raise exception` com a mensagem exata da SPEC, só com contagens. Depois cria cada uma das 4 restrições nomeadas, só se não existir uma restrição com esse nome em `pg_constraint` para `inspections`. Colunas, índices, RLS e as restrições da `001` não mudam. A `001` não foi tocada.
- **Log da escrita (§4.2):** `_write` usa `sqlstate_label(exc)`, importado de `qc_api.middleware`. Não há outra regex. O resto do caminho (rollback, 422 `Value cannot be stored`, log com rota, `device_id` e SQLSTATE) não mudou.
- **Simulador (§4.3):** o parser passou a ser `NoEchoArgumentParser`, uma subclasse de `ArgumentParser` que sobrescreve `error(message)` (e `parse_args`, para dar a contagem exata de `unrecognized arguments`). `--api-url` e `CLOUD_API_URL` só aceitam ASCII visível, e isso é conferido antes do `urlsplit`. Os números de `--out-of-control-lots` aceitam de 1 a 4 dígitos. O help de `--api-key` e o `README.md` (seção "Simulador") recomendam `SIM_DEVICE_API_KEY` e a forma `--api-key=<valor>`.
- **Testes do autor:** os testes de `infra/tests/` que supunham só a `001` agora calculam a lista de versões a partir de `infra/migrations/`. Há testes novos para a `002`, para o log da escrita e para o simulador.

## Rastreabilidade (critério de aceite → implementação)

Abreviações: `m/` = `infra/tests/test_migrate_db.py`, `s/` = `infra/tests/test_schema_db.py`, `f/` = `infra/tests/test_migration_files.py`, `c/` = `infra/tests/test_cli.py` (todos os de banco marcados `db`), `a/` = `api/tests/test_inspections.py` (marcado `db`), `sim/` = `scripts/tests/test_simulate.py`.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `infra/migrations/002_contract_checks.sql` | `m/::test_default_dir_starts_with_init_and_contract_checks`, `m/::test_apply_on_empty_schema` (versões, uma linha por versão, SHA-256 de cada arquivo, linha da `002`), `m/::test_002_creates_the_four_check_constraints` (`contype = 'c'`), `s/::test_contract_check_constraints_exist`, `f/::test_repository_migrations_are_valid`, `c/::test_cli_apply_then_status` |
| CA-02 | idem | `m/::test_apply_is_idempotent`, `m/::test_running_sql_file_again_changes_nothing[002_contract_checks.sql]` (arquivo executado 2 vezes, snapshot de colunas, restrições, índices e RLS igual), `m/::test_manual_001_and_002_then_runner_does_not_fail`, `m/::test_002_keeps_an_existing_constraint_with_the_same_name` |
| CA-03 | idem | `s/::test_contract_checks_refuse` (os 9 casos do CA-03 mais `received_at` `-infinity` e `10000-01-01`), `s/::test_contract_checks_accept_limits` |
| CA-04 | idem | `s/::test_inspection_id_check_mirrors_pydantic_uuid4` (256 pares `V`/`W` contra `TypeAdapter(UUID4)`; aceitos exatamente `48`, `49`, `4a`, `4b`), `s/::test_model_version_check_mirrors_contract` (a lista do CA-04 contra `MODEL_VERSION_PATTERN`) |
| CA-05 | idem | `m/::test_002_refuses_invalid_rows_with_counts_only` (4 linhas, uma delas violando 2 regras: mensagem exata com as contagens, sem valores; só `001` em `schema_migrations`; nenhuma das 4 restrições; linhas mantidas; depois de apagar, `["002"]`), `m/::test_002_applies_over_valid_rows`, `m/::test_002_file_run_by_hand_also_refuses_invalid_rows`, `f/::test_contract_checks_message_has_only_counts` |
| CA-06 | `api/src/qc_api/routers/inspections.py` | `a/::test_write_log_uses_sqlstate_label[integrity-without-sqlstate\|data-without-sqlstate\|check-violation]` (422 com o corpo exato, `WARNING` com `sqlstate=-`, `-` e `23514`, sem `sqlstate=None`). Sem a correção, os 2 primeiros falham (conferido). |
| CA-07 | `scripts/simulate.py` (`NoEchoArgumentParser`, `redact_usage_error`) | `sim/::test_usage_errors_never_echo_the_value` (16 casos: os 12 do CA-07 mais `--lots=<v>`, `--lot-size-min`, `--dry-run=<v>` e dois valores soltos com espaço; código 2, sem o valor no stdout, no stderr e no `caplog`, sem `Traceback`, com a mensagem esperada), `sim/::test_redact_usage_error`, `sim/::test_parser_is_the_no_echo_subclass`, `sim/::test_help_mentions_the_equals_form` (`--help`: código 0, `usage:`) |
| CA-08 | `scripts/simulate.py` (help de `--api-key`, `_HelpFormatter`), `README.md` | `sim/::test_help_mentions_the_equals_form`, `sim/::test_help_never_splits_the_equals_form`, `sim/::test_readme_documents_the_equals_form`, `sim/::test_key_starting_with_dash_works_with_equals`, `sim/::test_key_starting_with_dash_works_from_env`, `sim/::test_key_starting_with_dash_after_space_is_refused_without_echo` |
| CA-09 | `scripts/simulate.py` (`_api_url`) | `sim/::test_api_url_with_invisible_or_non_ascii_character_is_refused` (os 7 casos do CA-09 mais espaço no início e `\n` no fim), `sim/::test_cloud_api_url_with_control_character_is_refused`, `sim/::test_api_url_with_invalid_idna_label_is_refused`, `sim/::test_visible_ascii_api_url_still_sends` |
| CA-10 | `scripts/simulate.py` (`_LOT_NUMBER`) | `sim/::test_out_of_control_lot_numbers_have_at_most_4_digits`, `sim/::test_leading_zeros_are_still_accepted` (saída de `3,0007` idêntica à de `3,7` com `--seed 42`) |
| CA-11 | `scripts/simulate.py` | coberto pelos testes do CA-07, CA-09 e CA-10 acima (todos verificam código 2) e pelos testes do CA-08 da SPEC-014 em `scripts/tests/acceptance/test_spec_014.py`, que continuam passando |
| CA-12 | (manual, tester) | não se aplica ao autor |

## Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest -q                                                      # sem banco
TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q   # com banco
TEST_DATABASE_URL=... uv run pytest -q infra/tests --ignore=infra/tests/acceptance api/tests/test_inspections.py scripts/tests/test_simulate.py
```

Resultado das minhas execuções no fim da rodada (`13a5b29`):

- `ruff check .`: limpo. `ruff format --check .`: 113 arquivos já formatados.
- `pytest -q` sem banco: **1992 passed, 587 skipped**, 0 falhas.
- `pytest -q` com banco: **2568 passed, 6 failed, 5 errors**. Todas as falhas e todos os erros estão em `infra/tests/acceptance/test_spec_003.py`. Eles supõem só a `001` em `infra/migrations/`. A lista está na seção "Testes de aceite de SPECs anteriores" abaixo, e um dos casos é a SPEC_ISSUE-01.

## Decisões tomadas dentro do escopo da SPEC

1. **Um único bloco `do $$` na `002`.** A conferência e os 4 `alter table` ficam no mesmo bloco. A SPEC pede que a conferência venha antes de qualquer `alter table`, e isso continua valendo. No mesmo bloco, a recusa também desfaz tudo quando o arquivo roda à mão, num `psql` sem `ON_ERROR_STOP` ou fora de transação (teste `m/::test_002_file_run_by_hand_also_refuses_invalid_rows`). Com dois blocos, o `alter table` rodaria mesmo depois da recusa e falharia com o `Failing row contains (...)` do servidor.
2. **`%` no `raise exception`.** Como a SPEC previa (§7), o executor roda o arquivo sem parâmetros e o psycopg não interpreta o `%`. O `MigrationError` traz a mensagem do servidor seguida de `CONTEXT: PL/pgSQL function inline_code_block line N at RAISE`, que não tem valores de linha.
3. **`redact_usage_error` é pública e testável.** `error()` passa toda mensagem por ela:
   - para `unrecognized arguments: ...`, devolve a contagem;
   - para os outros casos, troca cada literal entre aspas no formato `%r` (aspas simples ou duplas, com escapes) por `(not shown)`, junto com o `: ` que o precede.

   Isso cobre `invalid <tipo> value`, `ignored explicit argument` e `invalid choice`. `parse_args` foi sobrescrito para passar a contagem exata (`len(extras)`), mesmo quando um valor tem espaços; a contagem por `split()` em `error()` fica só como reserva. As mensagens próprias do simulador não têm aspas e saem iguais.
4. **Help sem quebra em hífen.** `_HelpFormatter` quebra as linhas do help com `break_on_hyphens=False` e `break_long_words=False`. Sem isso, o `textwrap` podia partir `--api-key=<value>` em `--api-` / `key=<value>`, conforme a largura do terminal (`COLUMNS`), e o CA-08 ficaria dependente do ambiente.
5. **URL: conferência sobre o valor cru, de `--api-url` ou de `CLOUD_API_URL`.** O CA-09 exige recusar `"https://example.com/\t"`, que o `strip()` anterior aceitava. Por isso a conferência de ASCII visível vem antes de qualquer `strip`, e vale também para `CLOUD_API_URL` ("ou `CLOUD_API_URL`", §4.3.3). Um valor vazio ou só com espaços continua dando a mensagem `no API URL` (teste da SPEC-014 com `CLOUD_API_URL="  "`). Consequência: uma `CLOUD_API_URL` com espaço ou `\n` no fim passa a ser recusada, com `invalid --api-url (not shown)`.
6. **URL: host conferido como o httpx o codifica.** `https://xn--zz.com` é ASCII visível e passa pelo `urlsplit`. Mesmo assim, o httpx levantava `idna.IDNAError` na primeira requisição, com traceback e código 1. Para cumprir a §4.3.5 ("nenhum caminho de uso inválido sai com código 1 nem mostra traceback"), `_api_url` lê `httpx.URL(url).host` dentro do mesmo `try`. O `IDNAError` é um `ValueError`, e a mensagem é a mesma `invalid --api-url (not shown)`. As validações anteriores não mudaram.

## Testes de aceite de SPECs anteriores (para o tester)

Com a `002` em `infra/migrations/`, `infra/tests/acceptance/test_spec_003.py` falha com banco nestes casos:

| Teste | Resultado | Coberto pela autorização da §3.1 item 1? |
|---|---|---|
| fixture `ca01_db` (`assert apply_migrations(empty_db) == ["001"]`) | causa os 5 `ERROR` de setup abaixo | sim |
| `test_ca01_apply_on_empty_schema` | FAILED | sim |
| `test_ca02_second_apply_is_noop` | ERROR (fixture) | sim |
| `test_ca03_rerunning_sql_file_changes_nothing` | ERROR (fixture) | só a fixture; o corpo passa depois do ajuste dela |
| `test_ca21_cli_status_lists_applied` | ERROR (fixture) | só a fixture; o corpo passa depois do ajuste dela |
| `test_extra_schema_migrations_columns` | ERROR (fixture) | sim (é o teste da estrutura de `schema_migrations`) |
| `test_extra_manual_then_runner` | FAILED | sim |
| `test_extra_pending_on_empty_schema` | FAILED | sim |
| `test_extra_concurrent_runs_apply_once` | FAILED | sim |
| `test_extra_cli_apply_success_hides_url` | FAILED | sim |
| `test_extra_cli_uses_database_url_env` | FAILED | sim |
| `test_extra_new_migration_after_existing` | ERROR (fixture); continua falhando depois do ajuste da fixture | **não**: ver SPEC_ISSUE-01 |

Nenhum outro teste de aceite falha: `api/tests/acceptance/` (incluindo a SPEC-004), `scripts/tests/acceptance/test_spec_014.py` e as demais suítes passam com banco e sem banco.

**Nota para o CA-07:** os casos `--start`, `--out-of-control-lots` e `--model-version` só mostram o nome da própria opção se o `device_id` for válido. O simulador confere `--device-id` (ou `SIM_DEVICE_ID`) antes das outras opções, então o teste precisa definir `SIM_DEVICE_ID=sim-01` (como fiz em `sim/::test_usage_errors_never_echo_the_value`). Com `--device-id sim-01` no `argv`, o caso `["--device-id", S]` também funciona, porque o último valor prevalece.

## SPEC_ISSUE (se houver)

**SPEC_ISSUE-01 (afeta só o trabalho do tester; não bloqueia o código desta rodada).**

`test_extra_new_migration_after_existing` (`infra/tests/acceptance/test_spec_003.py`, SPEC-003) usa a fixture `ca01_db` e, em seguida, um diretório temporário com a cópia da `001` e um arquivo novo `002_more.sql`. Depois do ajuste autorizado de `ca01_db`, que passa a aplicar todas as versões do diretório padrão, a `002` já está registrada com o checksum de `002_contract_checks.sql`. Aí `pending_migrations(ca01_db, tmp_path)` levanta `MigrationError: checksum mismatch for 002` (reproduzido num banco de rascunho). O teste não está na lista da §3.1 item 1, e a SPEC diz que "os testes que usam um diretório temporário com a cópia da 001 não mudam". Com o texto atual, o tester não tem autorização para fazê-lo passar.

Saídas possíveis, a decidir pelo architect ou pelo humano (não implementei nenhuma):
- (a) autorizar o tester a trocar, nesse teste, `002_more.sql` por um número livre calculado (a próxima versão depois das do diretório padrão) e a copiar para o diretório temporário todos os arquivos de `infra/migrations/`, mantendo a asserção "a nova migração é aplicada depois das existentes";
- (b) autorizar a troca da fixture desse teste por `empty_db`, aplicando antes só a cópia da `001`.

Fiz o ajuste equivalente ao (a) no teste do autor `c/::test_cli_failed_migration_exits_1`, que tinha o mesmo problema.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando, com banco e sem banco
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] `infra/migrations/001_init.sql` não foi alterado
- [x] Nenhuma credencial fictícia como literal em URL, conninfo ou header nos testes novos (as chaves são geradas com `secrets` em tempo de execução)
- [x] Nenhum teste novo roda o pytest em subprocesso
