# SPEC-003 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-003](../../docs/specs/SPEC-003-schema-banco.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-003-schema-banco` |
| Commits | `31d984c` (feat(infra): migração e executor), `01f8f9d` (test(infra): fixtures de banco), `4e6a863` (test(infra): runner, CLI e schema com Postgres), `13bf8c1` (docs: comando de migração), mais o commit deste relatório |

## Resumo

- `infra/migrations/001_init.sql` implementa `architecture.md` §5 e a §4.1 da SPEC. O DDL é idempotente (`if not exists`) e o arquivo não tem `BEGIN`/`COMMIT`. Inclui as 7 restrições nomeadas de `inspections`, a coluna gerada `is_defective`, os 4 índices e o RLS ligado sem políticas e sem `force`. `latency_ms` continua `integer`, sem teto no `check`.
- `infra/migrate.py` expõe `apply_migrations` e `pending_migrations`, além de `load_migrations`, `Migration`, `MigrationError`, `DatabaseConnectionError` e `main`. Valida os nomes `NNN_slug.sql` e os números repetidos antes de conectar. Cada migração roda numa transação junto com o `insert` em `schema_migrations` (checksum SHA-256). O executor verifica o checksum das já aplicadas, serializa execuções com `pg_advisory_lock` e conecta com `prepare_threshold=None`. A CLI usa os códigos 0/1/2 e nunca mostra a URL.
- No `conftest.py` da raiz: fixtures `db_conninfo` (com a trava `test` aplicada antes de qualquer conexão), `migrated_db` e `clean_db`. No `pyproject.toml` da raiz: `infra/tests` em `testpaths` e `pythonpath = ["infra"]`.
- Testes do autor em `infra/tests/`: 107 testes, dos quais os de banco são marcados `db`. O `README.md` ganhou a seção "Migrações do banco (SPEC-003)".

## Rastreabilidade (critério de aceite → implementação)

Abreviações: `mf/` = `infra/tests/test_migration_files.py`, `cli/` = `infra/tests/test_cli.py`, `mdb/` = `infra/tests/test_migrate_db.py`, `sdb/` = `infra/tests/test_schema_db.py`, `fx/` = `infra/tests/test_db_fixtures.py`. `migrate.py` = `infra/migrate.py`; `001` = `infra/migrations/001_init.sql`.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `migrate.py` (`apply_migrations`, `_ensure_control_table`, `_apply_one`), `001` | `mdb/::test_apply_on_empty_schema`, `::test_control_table_columns`; `mf/::test_checksum_is_sha256_of_file_bytes` |
| CA-02 | `migrate.py` (`_plan`) | `mdb/::test_apply_is_idempotent`, `::test_new_migration_is_applied_after_existing_ones` |
| CA-03 | `001` (`if not exists`) | `mdb/::test_running_sql_file_again_changes_nothing` (compara colunas, restrições, índices e RLS antes e depois), `::test_manual_then_runner_does_not_fail` |
| CA-04 | `001` | `sdb/::test_column_types`, `::test_device_columns`, `::test_indexes` |
| CA-05 | `001` | `sdb/::test_enum_checks_match_contract`, `::test_named_constraints_exist` |
| CA-06 | `001` (`inspections_*_check`) | `sdb/::test_check_violations[overrides0..2]` |
| CA-07 | `001` (`inspections_grade_null_iff_unknown`, `inspections_grade_fields_null_together`) | `sdb/::test_check_violations[overrides3..7]`, `::test_unknown_without_grade_fields_is_accepted` |
| CA-08 | `001` (`inspections_ranges_check`, `inspections_formats_check`) | `sdb/::test_check_violations[overrides5, 8..19]`, `::test_inclusive_limits_accepted` |
| CA-09 | `001` (`is_defective`) | `sdb/::test_is_defective_matches_contract` (itera `Grade` e usa `qc_contracts.is_defective`) |
| CA-10 | `001` (`generated always ... stored`) | `sdb/::test_is_defective_cannot_be_written` (insert e update → `GeneratedAlways`) |
| CA-11 | `001` (`inspection_id uuid primary key`) | `sdb/::test_duplicate_inspection_id` |
| CA-12 | `001` (`references devices ... on delete restrict`) | `sdb/::test_foreign_keys` |
| CA-13 | `001` (`devices`) | `sdb/::test_device_rejections`, `::test_device_defaults` |
| CA-14 | `001`, `migrate.py` (`_ENABLE_CONTROL_TABLE_RLS`) | `sdb/::test_rls_enabled_without_force_and_without_policies`; `mdb/::test_control_table_has_rls_without_policies` |
| CA-15 | `001` (RLS sem políticas) | `sdb/::test_rls_blocks_role_without_policies` (papel `partqc_rls_probe_dev`, tolerante a resto de execução anterior, removido no fim) |
| CA-16 | `migrate.py` (`_apply_one`) | `mdb/::test_failed_migration_is_rolled_back` (inclui uma 003 que não deve rodar); `cli/::test_cli_failed_migration_exits_1` |
| CA-17 | `migrate.py` (`_plan`) | `mdb/::test_checksum_mismatch_applies_nothing`; `cli/::test_cli_checksum_mismatch_exits_1` |
| CA-18 | `migrate.py` (`load_migrations`, chamada antes de conectar) | `mdb/::test_invalid_filename_touches_nothing`, `::test_duplicate_number_touches_nothing`; `mf/::test_invalid_sql_filename_rejected`, `::test_duplicate_number_rejected`, `::test_ordered_by_number`, `::test_non_sql_files_and_directories_are_ignored` |
| CA-19 | `migrate.py` (`main`) | `cli/::test_missing_url_exits_2_and_names_the_variable`, `::test_blank_url_counts_as_missing`, `::test_invalid_argument_exits_2` |
| CA-20 | `migrate.py` (`_connect`, `_host_port`, `main`) | `cli/::test_closed_port_exits_1_without_leaking_password`, `::test_password_from_env_is_not_leaked`, `::test_malformed_url_exits_2_without_echoing_it`; `mf/::test_host_port_never_contains_secret`, `::test_connection_error_hides_conninfo` |
| CA-21 | `migrate.py` (`_status`, `pending_migrations`) | `cli/::test_cli_apply_then_status`, `::test_cli_status_does_not_create_control_table`; `mdb/::test_apply_on_empty_schema` (`pending_migrations` → `[]`) |
| CA-22 | `conftest.py` (`db_conninfo`, `_database_name`) | `fx/::test_guard_refuses_database_without_test_in_name` (4 URLs, porta fechada), `::test_guard_accepts_test_database_without_connecting`, `::test_fixture_skips_without_url` |
| CA-23 | `001` (`latency_ms integer`) | `sdb/::test_latency_int4_ceiling` |
| §4.1 sem `BEGIN`/`COMMIT`, sem `force`, sem política | `001` | `mf/::test_sql_file_has_no_transaction_control` |
| §4.2 `pg_advisory_lock` | `migrate.py` (`ADVISORY_LOCK_KEY`) | `mdb/::test_concurrent_runs_apply_once` (4 threads, só uma aplica), `::test_advisory_lock_is_released` |
| §4.4 `migrated_db`, `clean_db` | `conftest.py` | `fx/::test_migrated_db_has_tables`, `::test_clean_db_truncates` |

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1).

## Como rodar e verificar

```bash
uv sync --all-packages --frozen
uv run ruff check . && uv run ruff format --check .

# sem banco: os testes db são pulados
env -u TEST_DATABASE_URL -u CI uv run pytest -q

# com o Postgres 16 local de teste
export TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test
uv run pytest -q
uv run pytest infra/tests -q

# CLI
DATABASE_URL=$TEST_DATABASE_URL uv run --package qc-api python infra/migrate.py --status
DATABASE_URL=$TEST_DATABASE_URL uv run --package qc-api python infra/migrate.py
```

Resultados nesta rodada (Postgres 16.15 local):

- `uv run ruff check .`: limpo. `uv run ruff format --check .`: 49 arquivos já formatados.
- `uv run pytest -q` com `TEST_DATABASE_URL`: **843 passed**.
- `uv run pytest -q` sem `TEST_DATABASE_URL` e sem `CI`: **773 passed, 70 skipped** (todos os `db`, com o motivo `TEST_DATABASE_URL not set`).

## Decisões tomadas dentro do escopo da SPEC

1. **`inspections.device_id` é `not null`.** O §5 escreve `device_id text fk→devices` sem dizer se aceita nulo. O Objetivo da SPEC pede que o schema rejeite dados fora do contrato, e no `qc_contracts` `device_id` é obrigatório (`DeviceId`, sem `None`). Uma FK nula deixaria passar uma inspeção sem dispositivo. Nenhum CA depende disso. Se o architect preferir a coluna anulável, basta remover o `not null`.
2. **Restrições de `devices` com nome explícito**, igual ao nome padrão do Postgres: `devices_device_id_check`, `devices_api_key_hash_check`, `devices_api_key_hash_key`. A SPEC não as nomeia; nomear deixa o schema determinístico.
3. **Saída da CLI:** `logging` com INFO no **stdout** (versões aplicadas e a listagem do `--status`) e WARNING/ERROR no **stderr**. Formato `LEVEL mensagem`.
4. **Código 2 também para** URL malformada (o parser do libpq pode ecoar a string, então a mensagem é só `invalid database URL (not shown)`) e para `--migrations-dir` inexistente. Os dois casos são "argumento inválido".
5. **Erros de conexão** viram `DatabaseConnectionError("could not connect to the database at <host>:<port> (<Tipo>)")`, com `from None`, para que nem a mensagem nem o traceback encadeado carreguem a conninfo. Isso vale também para quem chama as funções importadas, não só para a CLI. Os erros de SQL de uma migração viram `MigrationError` com o tipo e a mensagem do servidor, que não contém a URL.
6. **`pending_migrations` e `--status` também verificam o checksum.** Um arquivo aplicado e depois alterado levanta `checksum mismatch for <versão>`, e a CLI sai com 1. Assim o `--status` não diz "tudo aplicado" com um arquivo divergente. Nenhum dos dois cria `schema_migrations` (só leem; `to_regclass`).
7. **Migração registrada cujo arquivo sumiu:** gera só um WARNING e não bloqueia. A SPEC não define esse caso.
8. **Descoberta de arquivos:** consideram-se os arquivos com sufixo `.sql` sem diferenciar maiúsculas (`001_init.SQL` é rejeitado como nome fora do padrão, não ignorado). Outros arquivos e diretórios são ignorados. A validação usa `re.fullmatch` com a regex da SPEC.
9. **Tabela de controle e migrações sem schema qualificado:** tudo vai para o primeiro schema do `search_path` (o `public`), igual ao próprio `001_init.sql`.
10. **Chave do advisory lock:** constante `0x5051_434D_4947` ("PQCMIG" em ASCII). O lock é liberado no `finally`, e também quando a conexão fecha.
11. **Trava do `db_conninfo`:** só conta o nome escrito na conninfo (URL ou `key=value`), sem cair para `PGDATABASE` ou para o nome do usuário. Uma URL sem nome de banco é recusada. A comparação `'test' in nome` diferencia maiúsculas. A falha usa `pytest.fail(..., pytrace=False)` dentro da fixture, e o pytest a reporta como **ERROR no setup** ("1 error"), não como "failed". Sem `TEST_DATABASE_URL`, a fixture faz `skip` com o mesmo motivo da política da SPEC-001.
12. **Teste da trava sem tocar no banco:** `infra/tests/db_conninfo_probe.py` não segue o padrão `test_*.py`, então a coleta normal o ignora. `test_db_fixtures.py` o roda num subprocesso do pytest, com URLs que apontam para a porta 1 (fechada).
13. **Isolamento dos testes que precisam de schema vazio:** a fixture local `empty_schema`, em `test_migrate_db.py` e `test_cli.py`, recria o `public` e, no teardown, o recria de novo e reaplica as migrações. Assim o `migrated_db` da sessão continua válido para os testes seguintes, inclusive os de aceite.
14. **Papel de RLS dos testes do autor:** `partqc_rls_probe_dev`, distinto do `partqc_rls_probe` do CA-15, para não colidir com o teste de aceite.
15. **`.env.example`:** nenhuma variável nova. Só acrescentei ao comentário de `DATABASE_URL` que ela também é a URL padrão do `infra/migrate.py`.

## SPEC_ISSUE (se houver)

Nenhum bloqueante. Uma nota para o tester e o architect, sem mudar nada:

- **CA-22, "o teste falha":** uma falha dentro de fixture aparece no pytest como **error** de setup ("1 error"), não como "failed". A mensagem da trava aparece na saída e o código de saída é diferente de 0. Se o CA exigir literalmente o desfecho `failed`, isso precisa ser esclarecido.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (com e sem `TEST_DATABASE_URL`)
- [x] `.env.example` atualizado (se houver variável nova): nenhuma variável nova; comentário de `DATABASE_URL` ajustado
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
