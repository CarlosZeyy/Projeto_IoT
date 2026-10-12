# SPEC-003 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-003](../../docs/specs/SPEC-003-schema-banco.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `df5b3c7` (implementação em `31d984c`, fixtures em `01f8f9d`) |
| **Veredicto** | **PASS** |

Os testes foram escritos a partir da SPEC (caixa-preta) antes da leitura de `infra/migrate.py` e `001_init.sql`. Depois da leitura, só acrescentei testes exploratórios; nenhum teste de CA mudou.

Arquivos:

- `infra/tests/acceptance/test_spec_003.py`: 114 testes, todos marcados `acceptance` e `db` (45 dos CAs, 69 extras e exploratórios).
- `infra/tests/acceptance/ca22_guard_probe.py`: sonda do CA-22. O nome não segue `test_*.py`, então a coleta normal a ignora; o CA-22 a executa num subprocesso do pytest.

Isolamento: os testes que precisam de um `public` vazio (CA-01/02/03/16/17/18/21 e extras do executor) usam um banco temporário `partqc_test_acc003`, criado no mesmo servidor no início do módulo e removido no fim (`drop database ... with (force)`). O `migrated_db` da sessão não é afetado. Os testes de schema usam as fixtures da SPEC (`clean_db` → `migrated_db` → `db_conninfo`). Depois da suíte, o servidor ficou só com `postgres`, `partqc_test` e os templates, e não restou nenhum papel `partqc%`.

## Cobertura dos critérios de aceite

Prefixo dos caminhos: `infra/tests/acceptance/test_spec_003.py::`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_apply_on_empty_schema` (retorno `["001"]`, 3 tabelas e `checksum` = SHA-256 do arquivo) | ✅ |
| CA-02 | `test_ca02_second_apply_is_noop` | ✅ |
| CA-03 | `test_ca03_rerunning_sql_file_changes_nothing` (arquivo inteiro numa transação; compara colunas, defaults, colunas geradas, restrições com `pg_get_constraintdef`, índices com `indexdef`, RLS, políticas e `schema_migrations`) | ✅ |
| CA-04 | `test_ca04_indexes_and_column_types` (4 índices com as colunas certas; conjunto exato das 16 colunas com `format_type`) | ✅ |
| CA-05 | `test_ca05_enum_checks_match_contract[3]` (literais de `pg_get_constraintdef` = valores dos enums de `qc_contracts`) | ✅ |
| CA-06 | `test_ca06_enum_values_outside_contract_rejected[3]` (`CheckViolation`, SQLSTATE 23514 e o nome da restrição) | ✅ |
| CA-07 | `test_ca07_grade_null_iff_unknown_rejected[2]`, `test_ca07_unknown_without_grade_fields_accepted` | ✅ |
| CA-08 | `test_ca08_ranges_and_formats_rejected[6]` (também confere o nome da restrição da tabela da §4.1) | ✅ |
| CA-09 | `test_ca09_is_defective_matches_contract` (itera `Grade` e compara com `qc_contracts.is_defective`; 6 linhas) | ✅ |
| CA-10 | `test_ca10_is_defective_cannot_be_written[True/False]` | ✅ |
| CA-11 | `test_ca11_duplicate_inspection_id` (`UniqueViolation`; `on conflict do nothing returning` sem linha; total 1) | ✅ |
| CA-12 | `test_ca12_foreign_keys` | ✅ |
| CA-13 | `test_ca13_device_rejections[3]`, `test_ca13_device_defaults` | ✅ |
| CA-14 | `test_ca14_rls_enabled_without_force_and_policies` | ✅ |
| CA-15 | `test_ca15_rls_blocks_role_without_policies` (papel `partqc_rls_probe` criado de forma tolerante e removido com `drop owned by` + `drop role`; contagens 0/0; `insert` → 42501; o dono continua vendo as 3 linhas) | ✅ |
| CA-16 | `test_ca16_failed_migration_rolls_back` | ✅ |
| CA-17 | `test_ca17_checksum_mismatch` | ✅ |
| CA-18 | `test_ca18_invalid_file_name_rejected_before_applying` (`schema_migrations` ausente, `devices` ausente) | ✅ |
| CA-19 | `test_ca19_cli_without_url_exits_2` | ✅ |
| CA-20 | `test_ca20_cli_closed_port_does_not_leak_password` | ✅ |
| CA-21 | `test_ca21_cli_status_lists_applied` (linha com `001` e `applied`; `pending_migrations` → `[]`) | ✅ |
| CA-22 | `test_ca22_guard_refuses_non_test_database[db_conninfo/clean_db]` (subprocesso do pytest com `TEST_DATABASE_URL=.../partqc_prod` apontando para um listener TCP local que conta conexões: código ≠ 0, mensagem da trava na saída, `1 error`, nenhum `passed` e **0 conexões aceitas**. Num controle manual com nome `partqc_test_ctrl`, o mesmo listener registrou 1 conexão, o que confirma que a medição funciona.) | ✅ |
| CA-23 | `test_ca23_latency_ms_int4_ceiling` (2147483647 aceito e lido igual; 2147483648 como parâmetro → `NumericValueOutOfRange`, 22003; total continua 1) | ✅ |

## Suíte completa

```text
# TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test, sem CI
uv run pytest -q                    -> 957 passed in 49.45s
# sem TEST_DATABASE_URL e sem CI
uv run pytest -q                    -> 773 passed, 184 skipped in 34.79s
                                       (184 = 70 testes db do autor + 114 de aceite, motivo "TEST_DATABASE_URL not set")
# CI=true com TEST_DATABASE_URL
uv run pytest -q                    -> 957 passed in 52.26s
# CI=true sem TEST_DATABASE_URL (política da SPEC-001, comportamento esperado)
uv run pytest -q                    -> "ERROR: TEST_DATABASE_URL is required when CI=true", exit 4
# ordem alternativa (aceite antes dos testes do autor)
uv run pytest -q infra/tests/acceptance infra/tests tests -> 486 passed

uv run ruff check .                 -> All checks passed!
uv run ruff format --check .        -> 51 files already formatted
```

Postgres: contêiner `partqc-pg` (Postgres 16), banco `partqc_test`.

## Bugs encontrados

Nenhum bug contra a SPEC. Uma observação de robustez, de severidade baixa, que não bloqueia:

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | baixa (observação; fora do contrato da §4.1) | §4.2 (rollback) | 1. Diretório com `001_init.sql` e `002_cm.sql` = `create table t_cm(id int); commit; select from nao_existe;`. 2. `apply_migrations(url, dir)` num schema vazio. | Ou o executor recusa arquivos com controle de transação, ou a migração inteira é desfeita. | Levanta `MigrationError("... failed and was rolled back: UndefinedTable ...")` e `002` não é registrada, mas `t_cm` **continua existindo**: o `commit;` do próprio arquivo encerra a transação do executor. A mensagem "rolled back" fica incorreta, e uma nova execução falharia em `create table t_cm`. A §4.1 proíbe `BEGIN`/`COMMIT` nos arquivos, então isso é uso fora do contrato. Fica como sugestão para uma SPEC futura: rejeitar ou avisar quando o arquivo tiver controle de transação. |

## Testes exploratórios (além dos critérios)

Os testes automatizados abaixo estão em `test_spec_003.py` e todos passam:

- Arquivo `001_init.sql` sem `BEGIN`/`COMMIT`/`ROLLBACK`, sem `force row level security`, sem `create policy` e sem `password` (§4.1, §4.3).
- `inspections`: nulidade de cada coluna de §5, `received_at default now()`, `is_defective` `GENERATED ALWAYS` e PK em `inspection_id`. `devices`: tipos e nulidade exatos das 4 colunas. `schema_migrations`: 4 colunas com tipos e `not null`, `filename = '001_init.sql'` e `applied_at` com fuso.
- As 7 restrições nomeadas da §4.1 existem.
- Limites inclusivos aceitos: confianças 0 e 1, `grade_score` 0 e 4, `latency_ms` 0, `lot_id` com 40 caracteres e com `_`/`-`, `nut`, `simulated`.
- Rejeitados com `CheckViolation`: confianças −0,01, 1,01 e −0,5; `grade_score` −0,1; `lot_id` com 41 caracteres, vazio, com acento (`Lóte1`) e com `\n` no fim; `model_sha256` maiúsculo, com 65 caracteres ou com não-hex; `grade_confidence` nulo com `grade` presente; `Screw` e `LIVE` (maiúsculas); `NaN` em `type_confidence` e `grade_score`.
- `device_id` rejeitado: `ab`, 33 caracteres, com espaço, com `\n` no fim, `édge-01`, vazio. Aceito: `abc`, 32 caracteres, `0-9`.
- `update ... set is_defective` falha. `is_defective` acompanha um `update` de `grade` (`fair` → `poor` passa a `true`). `received_at` volta com fuso.
- Executor: arquivo aplicado à mão e depois `migrate.py` (retorna `["001"]` sem erro); `pending_migrations` num schema vazio retorna `["001"]` sem criar nada; ordenação numérica (`001`, `002`, `010`, com a 010 dependendo da 002); nova migração depois das existentes; falha na 002 impede a 003; checksum divergente impede uma 002 nova; números repetidos e nomes inválidos (`2_short`, `003_Upper`, `004-dash`, `0005_four_digits`, `006_ação`, `007_.sql`) não aplicam nada; 4 threads concorrentes aplicam uma única vez (uma retorna `["001"]` e as outras `[]`, com 1 linha em `schema_migrations`); nenhum advisory lock fica preso depois da execução; o conteúdo com `%`, `%s` e `%(x)s` é gravado literalmente, sem interpolação (§4.3).
- Segredos (R-03): `apply_migrations` e `pending_migrations` com URL, conninfo `key=value` e URL com `connect_timeout`, todos com senha e porta fechada. Nem a senha nem a conninfo aparecem no traceback completo, inclusive nas exceções encadeadas. CLI com a senha em `DATABASE_URL` → exit 1, sem vazamento. CLI contra um banco inexistente no servidor real, com senha → exit 1, sem senha e sem URL na saída. CLI com sucesso e senha na URL (o servidor usa trust e ignora a senha) → exit 0, sem a senha na saída.
- CLI: aplica usando `DATABASE_URL` do ambiente; `--status` num schema vazio lista `001 pending` e não cria nada; checksum divergente → exit 1 com `checksum mismatch for 001`; migração quebrada → exit 1; `--bogus` e um argumento posicional extra → exit 2; `DATABASE_URL` só com espaços → exit 2, com a mensagem citando `DATABASE_URL`.
- Fixture `clean_db`: dados gravados num teste não aparecem no seguinte.

Sondagens manuais (script temporário, banco `partqc_test_explore003` criado e removido):

| Caso | Resultado |
|---|---|
| Migração vazia ou só com comentário | Aplicada e registrada (a SPEC não define esse caso; aceitável). |
| Arquivo UTF-8 com BOM | `MigrationError` (`syntax error at or near "﻿create"`), nada registrado. Observação: o arquivo é lido como `utf-8`, não `utf-8-sig`. Editores no Windows podem gravar BOM, mas a dupla usa Linux. Não é bug contra a SPEC. |
| Arquivo em Latin-1 | `MigrationError("... is not valid UTF-8")`, sem traceback cru. |
| `002_x.SQL` (extensão maiúscula) | Rejeitado como nome inválido antes de aplicar (decisão 8 do dev report). |
| `000_zero.sql` | Aceito e ordenado antes da `001` (permitido pela regex). |
| `README.txt` no diretório | Ignorado. |
| `--migrations-dir` inexistente | CLI → exit 2. Função → `MigrationError`. |
| URL malformada (`not a url ===`, `[::1:5432`) | Exit 2, `invalid database URL (not shown)`. |
| Host inexistente (DNS) | Exit 1, `could not connect to the database at nohost.invalid:5432 (OperationalError)`, sem senha. |
| `--status` no banco do CA-01 | `INFO 001 applied 001_init.sql` / `INFO 1 applied, 0 pending`, exit 0. |
| Reaplicação pela CLI | `INFO no pending migrations`, exit 0. |
| `commit;` dentro do arquivo | Ver T-01. |

Notas de interpretação:

- **CA-22, "o teste falha":** a trava usa `pytest.fail` dentro da fixture, e o pytest reporta isso como **error** de setup (`1 error`), não como `failed`. Para mim, "o teste falha" quer dizer "não passa, com a mensagem da trava e código de saída ≠ 0", e o teste de aceite aceita `1 failed` ou `1 error`. Não abri um SPEC_ISSUE. O ponto já está no dev report e fica aqui para o reviewer.
- **CA-21, "lista 001 como aplicada":** a SPEC não fixa o formato. O teste exige uma linha com `001` e `applied` e sem `pending`.
- **CA-10:** o teste exige só que o `insert` falhe e que nenhuma linha seja gravada, sem exigir um SQLSTATE específico. Na prática, o erro é `GeneratedAlways`.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
