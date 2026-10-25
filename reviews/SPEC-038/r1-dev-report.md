# SPEC-038 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-038](../../docs/specs/SPEC-038-manutencao-borda-deploy.md) |
| Rodada | r1 |
| Autor | developer (Parte A, `edge/`); a Parte B (security-devops) é acrescentada no fim deste arquivo |
| Branch | `spec/SPEC-038-manutencao-borda-deploy` (encadeada na SPEC-017, sobre a 018, a 016 e a 036) |
| Commits | `c1317fb` (outbox e CLI de reenvio), `e0f1090` (importação, varredura e README), mais o commit deste relatório |

## Parte A (developer)

### Resumo

- `qc_edge.outbox`: `fetch_due` e `dead_items` conferem o tipo e o formato de cada coluna lida, na ordem da §4.1. No `fetch_due`, a linha `pending` inválida vira `dead` com `last_error = INVALID_ROW_ERROR` (`"invalid outbox row"`), por `rowid`, sob o lock e numa única transação; no `dead_items`, é pulada sem escrita. Os dois avisos vão para o logger `qc_edge.outbox` só com `rowid` e coluna.
- `qc_edge.requeue`: `ValueError`/`TypeError` em volta de `list_dead`/`requeue_dead` sai com 1 e loga só a classe (§4.1); a abertura separa `OperationalError` (`cannot open --outbox-path (...)`), `NotAnOutboxError`/`DatabaseError` (a mensagem de hoje) e outro `sqlite3.Error`, todos com 2 (§4.2).
- `qc_edge.importer`: `image.info.clear()` antes do `save` (§4.3); `limit_pil_logging()` no `main` (§4.4); remoção dos diretórios criados na linha, do mais interno para o mais externo, numa falha dos passos 4 a 6 (§4.5); reconferência do hash sob o lock, com a mesma regra de `exclusions.csv` da fase 1 (§4.6); recusa da pasta de entrada e do plano dentro de um repositório Git (§4.7).
- `qc_edge.privacy`: `limit_pil_logging()` (definida aqui e importada pelo importador) no `main` (§4.4).
- `edge/README.md`: as duas seções da §4.8.

### Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 (listagem com linha inválida) | `edge/src/qc_edge/outbox.py` (`dead_items`, `_dead_item`, `_read_*`), `edge/src/qc_edge/requeue.py` | `edge/tests/test_requeue.py::test_cli_listing_skips_an_invalid_row` (5 casos do CA); `edge/tests/test_outbox.py::test_dead_items_skips_an_invalid_row_and_writes_nothing`, `::test_dead_items_accepts_a_null_last_error` |
| CA-02 (reenvio e laço, R-05) | `edge/src/qc_edge/outbox.py` (`fetch_due`, `_pending_item`) | `edge/tests/test_requeue.py::test_invalid_rows_never_stop_the_publish_loop`; `edge/tests/test_outbox.py::test_requeue_of_an_invalid_created_at_goes_back_to_dead` |
| CA-03 (`pending` adulterado) | `edge/src/qc_edge/outbox.py` (`fetch_due`) | `edge/tests/test_outbox.py::test_fetch_due_marks_an_invalid_pending_row_dead` (12 casos: texto, BLOB, inteiro, real, data que estoura em UTC), `::test_fetch_due_reports_the_first_invalid_column`, `::test_fetch_due_accepts_what_sqlite_converts`, `::test_fetch_due_with_invalid_rows_inside_the_limit` (limite de 100), `::test_fetch_due_marks_dead_in_one_transaction`, `::test_fetch_due_without_invalid_rows_writes_nothing`, `::test_requeue_fixes_attempts_and_next_attempt_at` |
| CA-04 (defesa em profundidade) | `edge/src/qc_edge/requeue.py` (`main`) | `edge/tests/test_requeue.py::test_cli_value_and_type_errors_exit_with_1_without_the_message` |
| CA-05 (mensagens de abertura) | `edge/src/qc_edge/requeue.py` (`main`) | `edge/tests/test_requeue.py::test_cli_unopenable_file_is_not_called_not_an_outbox`, `::test_cli_files_that_are_not_an_outbox_keep_their_message`, `::test_cli_other_sqlite_error_on_open` |
| CA-06 (PNG com `comment`) | `edge/src/qc_edge/importer.py` (`normalize_imported_image`) | `edge/tests/test_importer.py::test_png_comment_is_not_copied` (`tEXt`, `zTXt`, `iTXt`), `::test_png_comment_reduced_image_is_not_copied`, `::test_png_with_comment_is_imported` |
| CA-07 (logger `PIL`) | `edge/src/qc_edge/privacy.py` (`limit_pil_logging`, `main`), `edge/src/qc_edge/importer.py` (`main`) | `edge/tests/test_importer.py::test_limit_pil_logging`, `::test_importer_main_keeps_exif_tags_out_of_the_debug_log`, `::test_privacy_main_keeps_exif_tags_out_of_the_debug_log`, `::test_main_never_lowers_a_higher_pil_level` |
| CA-08 (rollback dos diretórios) | `edge/src/qc_edge/importer.py` (`_store_locked`, `_write_row`, `_remove_dirs`) | `edge/tests/test_importer.py::test_failed_row_removes_the_directories_it_created` (`sources.csv`, `manifest.csv`, imagem), `::test_failed_row_keeps_a_directory_that_existed`, `::test_directory_that_cannot_be_removed_stays` |
| CA-09 (execução simultânea) | `edge/src/qc_edge/importer.py` (`_check_headers`, `_store_locked`, `run_import`, `_AlreadyImported`) | `edge/tests/test_importer.py::test_two_runs_of_the_same_plan_store_the_photo_once`, `::test_a_hash_excluded_meanwhile_is_imported_again`, `::test_bad_exclusions_under_the_lock_stops_the_import` |
| CA-10 (repositório Git) | `edge/src/qc_edge/importer.py` (`inside_git_repository`, `load_plan`) | `edge/tests/test_importer.py::test_inside_git_repository` (diretório, arquivo, link pendurado), `::test_inbox_inside_a_git_repository_is_refused`, `::test_plan_inside_a_git_repository_is_refused`, `::test_inbox_is_checked_before_the_plan`, `::test_inbox_inside_the_dataset_is_checked_first`, `::test_dataset_and_registry_inside_a_repository_are_accepted` |
| CA-11 (README) | `edge/README.md` | (conferido pelo tester; os textos `invalid outbox row`, `rowid`, `fora do repositório` e `repositório Git` estão nas seções da §4.8) |

### Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
uv run pytest -q edge/tests/test_outbox.py edge/tests/test_requeue.py edge/tests/test_importer.py
uv run pytest -q   # suíte inteira, sem TEST_DATABASE_URL e sem CI=true
```

### Decisões tomadas dentro do escopo da SPEC

1. **Logger dos avisos.** O módulo `qc_edge.outbox` já usava o logger `qc_edge` (aviso do WAL). Para não mudar esse aviso, os dois avisos novos vão para um logger próprio, `row_logger = logging.getLogger("qc_edge.outbox")`, como a §4.1 pede.
2. **"A conversão funciona".** A validação de `created_at` e `next_attempt_at` roda o próprio `parse_timestamp` de hoje (`fromisoformat` + `astimezone(UTC)`) e trata `ValueError` e `OverflowError` como inválido. Assim, um texto como `0001-01-01T00:00:00+05:00`, que o `fromisoformat` aceita mas cuja conversão para UTC estoura, também vira `dead` em vez de derrubar o ciclo. Para os valores que a tabela da §4.1 descreve, o resultado é o mesmo (a definição de "linha válida" exige que "a conversão funcione"). `attempts` exige `int` (e não `bool`, que o `sqlite3` nunca devolve).
3. **Escrita no `fetch_due`.** A leitura, a validação e o `UPDATE ... WHERE rowid = ? AND status = 'pending'` (um `executemany`, um `COMMIT`) acontecem sob o mesmo `threading.Lock`; os avisos são registrados depois do commit, fora do lock. Sem linha inválida, nada é escrito (teste com `set_trace_callback`).
4. **Sinal de "já importado" sob o lock (§4.6).** `_store_locked` levanta a exceção interna `_AlreadyImported` depois do `item_type_conflict` (a ordem da frase da §4.6), e o `run_import` a trata como a linha marcada na fase 1 (`skipped <file>: already imported`, conta em `skipped`). Um `exclusions.csv` com outro cabeçalho ou ilegível nesse ponto vira `_ImportStopped` com `exclusions header mismatch`/`exclusions unreadable` (as mensagens da fase 1), código 1; um `OSError` na leitura cai no caminho de E/S de hoje (`failed to write dataset`, código 1).
5. **Rollback dos diretórios (§4.5).** Os passos 4 (imagem) a 6 foram movidos para `_write_row`, sem mudança de lógica; `_store_locked` envolve a chamada num `try/except BaseException` que chama `_remove_dirs(created)` depois de a imagem e o manifest já terem sido desfeitos, ainda sob o lock. `fsync_dir` só do pai de cada diretório efetivamente removido.
6. **`limit_pil_logging`** fica em `qc_edge.privacy` (o importador já importa `printable_path` de lá) e não em `qc_edge.jpeg` (§7 da SPEC).
7. **`inside_git_repository(path)`** é pública em `qc_edge.importer` e recebe o caminho já resolvido: `load_plan` passa o `realpath` da pasta de entrada e o pai do `realpath` do plano. A verificação acontece logo depois da regra "fora do dataset" e antes de `DATASET_NOT_DIR` e de qualquer leitura, na ordem da §4.7.
8. **Fixture `restore_pil_logger_level` (autouse) em `edge/tests/conftest.py`.** Os `main` do importador e da varredura agora sobem o nível do logger `PIL` quando o raiz está em DEBUG (o `caplog.set_level(logging.DEBUG)` de vários testes). A fixture devolve o nível de antes ao fim de cada teste, para não vazar estado global entre testes (vale também para os de aceite, que herdam o `conftest.py`, sem mudar nenhum deles).

### Observações (não bloqueiam)

- **`inspection_id` fora da forma canônica.** Pela tabela da §4.1, um `inspection_id` `str` que o `uuid.UUID` aceita é válido, mesmo em maiúsculas ou com chaves. Nesse caso (só com edição à mão), `mark_sent`/`mark_retry` usam `str(UUID)` (minúsculas) no `WHERE` e não acham a linha, que é reenviada a cada ciclo sem nunca virar `sent` (a idempotência da API evita duplicata, R-05, e os outros itens seguem). É o comportamento de antes da SPEC-038, e a SPEC define a validade assim; não mudei. Se o architect quiser, basta exigir `str(UUID(v)) == v` numa SPEC futura.
- **Falha no próprio `make_private_dirs`.** A §4.5 usa a lista devolvida por `make_private_dirs`; se o `mkdir` de um diretório interno falhar depois de criar os externos, a lista não volta e os externos vazios ficam (como antes). É um caso de E/S raro e fora do texto da §4.5.

### Testes de aceite de SPECs anteriores afetados (`docs/architecture.md` §10)

Nenhum. A suíte inteira (inclusive `edge/tests/acceptance/test_spec_009.py`, `test_spec_034.py` e `test_spec_036.py`) passa sem mudança: os testes de aceite da SPEC-036 usam `tmp_path`, fora de qualquer repositório Git, e o CA-16 da SPEC-009 (cobertura de `qc_edge.outbox` ≥ 80%) continua passando com os testes novos em `edge/tests/test_outbox.py`. Os dois testes de `infra/tests/acceptance/test_spec_032.py` citados na §3.1 dependem da Parte B (`handle_errors`) e não são afetados pela Parte A.

### SPEC_ISSUE

Nenhum.

### Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (suíte inteira sem banco: 6965 passed, 1097 skipped, 0 failed)
- [x] `.env.example` sem mudança na Parte A (nenhuma variável nova)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim; nada em `infra/`, `.gitignore`, `.dockerignore`, `.env.example` nem `docs/deployment-plan.md`
- [x] Imagens dos testes geradas pelo Pillow; marcadores gerados com `secrets`; nada lido de `~/partqc-entrada/`
