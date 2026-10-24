# SPEC-036 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-036](../../docs/specs/SPEC-036-importacao-de-fotos.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-036-importacao-de-fotos` |
| Commits | `3b73f98`, `a680c7c`, `2f10eca`, `4eba5a6` (+ o commit deste relatório) |

## Resumo

- `edge/src/qc_edge/importer.py` (novo) implementa `python -m qc_edge.importer`. A fase 1 valida o plano inteiro e o dataset sem gravar nada: cada célula, cada arquivo de entrada (dentro da pasta de entrada, regular, nunca link simbólico, até 40 MiB, SHA-256), as linhas entre si e contra o manifest, os cabeçalhos e o registro. A fase 2 normaliza uma imagem por vez fora do lock (`normalize_imported_image`: orientação lida antes, remoção estrutural, `load_image` sobre os bytes limpos, rotação pela tabela do `exif_transpose`, redução inteira com LANCZOS, JPEG q=90 sem metadados e conferência). Depois grava com os gravadores da coleta: `flock` por linha, `0700`/`0600`, temporário + `fsync` + `rename`, manifest antes do `sources.csv` e rollback.
- `qc_edge.jpeg.exif_orientation` (novo). O `has_exif_rotation` passou a delegar a ele, com o mesmo comportamento (os testes da SPEC-025 continuam passando).
- `qc_edge.collect`: o leitor do manifest, o leitor genérico de CSV do dataset, o `append_csv_row`/`rollback_append` e os filtros de texto viraram funções do módulo, que o `DatasetWriter` e o importador usam. A rota de coleta não muda (o CA-14 tem teste do autor). A cobertura ignora os `item_id` externos, e `count_external_images` é novo.
- O console mostra `<p id="external-images">Imagens externas (só treino): <n></p>` logo depois da tabela de cobertura.
- `edge/README.md`: seção "Importar fotos de fora da página (SPEC-036)".
- Nenhuma variável de ambiente nova. Nenhuma dependência nova.
- **Dois SPEC_ISSUE** (abaixo). Nenhum dos dois muda o que foi implementado, mas os dois afetam a escrita dos testes de aceite (CA-15 e CA-04).

## Rastreabilidade (critério de aceite → implementação)

Arquivos de teste do autor: `edge/tests/test_importer.py` (I), `edge/tests/test_jpeg.py` (J), `edge/tests/test_collect.py` (C) e `edge/tests/test_collect_route.py` (R).

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `importer.py` (`normalize_imported_image`, `reduced_size`, `_Importer`), `jpeg.py` (`exif_orientation`) | I `test_phone_photo_is_rotated_reduced_and_clean`, `test_contributor_photo_is_imported`, `test_rotation_table_matches_exif_transpose` (8 valores), `test_orientation_only_in_the_xmp_is_applied`, `test_reduced_size_integer_rounding`, `test_reduced_size_rounds_half_up`; J `test_exif_orientation_*` |
| CA-02 | `importer.py` (`normalize_imported_image`) | I `test_motion_photo_trailer_is_dropped_before_load_image`, `test_too_many_scans_after_the_cleaning` |
| CA-03 | `importer.py` | I `test_external_png_is_imported`, `test_png_rgba_becomes_rgb_jpeg`, `test_other_without_grade_goes_to_the_underscore_directory` |
| CA-04 | `importer.py` (`load_plan`, `_read_plan`, `_file_problem`, `_row_problems`, `_load_registry`) | I `test_contributor_row_problems` (30 casos), `test_external_row_problems` (9), `test_registry_license_not_allowed` (ND, NC-SA, SA, vazio), `test_symlink_in_the_inbox`, `test_directory_symlink_leaving_the_inbox`, `test_directory_and_fifo_are_invalid`, `test_file_too_large_is_never_read` (arquivo esparso), `test_cross_row_problems`, `test_item_type_conflict_inside_the_plan`, `test_every_problem_is_listed_once_per_line`, `test_missing_column`, `test_reordered_header`, `test_header_with_bom`, `test_plan_not_utf8`, `test_plan_above_5_mib`, `test_malformed_row`, `test_too_many_rows`, `test_cell_values_are_never_echoed` |
| CA-05 | `importer.py` (`main`, `load_plan`, `_read_dataset`) | I `test_privacy_checked_is_required_before_reading`, `test_unknown_argument_is_not_echoed`, `test_inbox_must_be_outside_the_dataset` (dentro, igual, contém), `test_inbox_through_a_symlink_into_the_dataset`, `test_inbox_must_exist`, `test_dataset_dir_that_is_a_file`, `test_registry_missing_only_matters_with_external_rows`, `test_registry_unreadable`, `test_dataset_headers` (manifest, sources, exclusions) |
| CA-06 | `importer.py` (`run_import`) | I `test_rejected_images_do_not_stop_the_import`, `test_unsupported_images`, `test_image_too_small`, `test_smallest_side_of_256_is_accepted`, `test_unsupported_jpeg_structure`, `test_normalization_check_failed`, `test_normalization_check_compares_the_size` |
| CA-07 | `importer.py` (`_read_dataset`, `_Importer._store_locked`) | I `test_rerun_skips_and_excluded_image_is_imported_again` |
| CA-08 | `importer.py` (`_Importer.store`) | I `test_same_name_waits_one_second`, `test_name_still_taken_after_three_attempts` |
| CA-09 | `importer.py` (`_store_locked`), `collect.py` (`append_csv_row`, `rollback_append`) | I `test_sources_write_failure_rolls_back_the_manifest` (com e sem manifest anterior), `test_manifest_write_failure_removes_the_image`, `test_image_write_failure_stops`, `test_io_error_log_has_no_absolute_path`, `test_header_changed_between_validation_and_writing_stops`, `test_item_type_registered_meanwhile_fails_the_row`; C `test_append_and_rollback`, `test_append_adds_a_missing_final_line_break` |
| CA-10 | `importer.py` + `collect.py`/`fsutil.py` (modos exatos) | I `test_modes_whatever_the_umask` (`0o022`, `0o277`), `test_existing_dataset_dir_keeps_its_mode` |
| CA-11 | `importer.py` (sem rede; entradas só lidas, com `O_NOFOLLOW`) | I `test_inputs_are_never_changed_and_no_network` (com `privacy.main` no fim) |
| CA-12 | `importer.py` (`run_import`, `dry_run`) | I `test_dry_run_creates_nothing`, `test_dry_run_on_an_existing_dataset_changes_nothing` |
| CA-13 | `collect.py` (`compute_coverage`, `count_external_images`, `DatasetWriter.external_images`), `app.py` (`_coverage_html`) | C `test_coverage_ignores_external_images`, `test_count_external_images_without_manifest`, `test_writer_external_images`; R `test_console_shows_the_external_images`, `test_console_external_images_without_manifest`, `test_console_external_images_with_unreadable_manifest`; I `test_imported_externals_stay_out_of_the_coverage` |
| CA-14 | `collect.py` (`ITEM_ID_PATTERN` inalterado) | R `test_collect_route_refuses_an_external_item_id` |
| CA-15 | `importer.py` (`SOURCES_COLUMNS`, `ALLOWED_LICENSES`) | I `test_formats_equal_to_qc_ml` (compara com `qc_ml.data.SOURCE_COLUMNS`, ver SPEC_ISSUE-01), `test_default_registry_is_the_one_of_the_repository` |
| CA-16 | `edge/README.md` | conferido à mão: a seção tem `python -m qc_edge.importer`, `--privacy-checked`, `--dry-run`, `sources.csv`, `python -m qc_edge.privacy` e `dataset-protocol.md` |
| CA-17 | manual | não se aplica (dupla) |

Também: I `test_printed_file_names_are_escaped`, `test_input_changed_after_validation`, `test_empty_plan_imports_nothing`, `test_help_exits_with_zero` e `test_module_entry_point` (`python -m qc_edge.importer` num subprocesso).

## Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
uv run pytest -q edge/tests
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

## Decisões tomadas dentro do escopo da SPEC

Casos que a SPEC não detalha. Nenhum muda contrato, regra, ADR nem o comportamento descrito na SPEC.

1. **Mensagens de saída 2 não listadas na SPEC** (texto fixo, sem valor): `--inbox must be an existing directory`, `--dataset-dir must be a directory` (caminho existente que não é diretório), `cannot read --plan`, `external sources registry unreadable` (cabeçalho diferente, registro com outro número de campos, `source_id` repetido ou CSV que não é UTF-8), `manifest unreadable` (o mesmo texto da coleta), `sources unreadable`, `exclusions header mismatch`, `exclusions unreadable` e `cannot read the dataset files`. O `exclusions.csv` é lido com o cabeçalho exato `image_path,reason` (SPEC-011), porque a retomada depende dele.
2. **Plano acima de 5 MiB** → `plan line 1: unreadable_csv (-)`, sem ler o resto.
3. **Ordem das checagens:** argumentos → `--privacy-checked` → pasta de entrada (existe; fora do dataset) → `--dataset-dir` → cabeçalhos de `manifest.csv`, `sources.csv` e `exclusions.csv` → estrutura do plano → registro (só com linha `external`) → regras por linha → regras entre linhas.
4. **Linhas de problema na saída de erro:** são escritas direto no `stderr`, uma por linha, ordenadas por linha do plano e pela ordem das colunas. O `logging` só registra `plan refused: <n> problem(s), nothing written` (nunca um valor). Os testes de aceite devem procurar a linha em `err.splitlines()` sem exigir que só elas existam, porque o handler do log também escreve no `stderr`.
5. **Releitura na fase 2:** o arquivo de entrada é lido de novo (com `O_NOFOLLOW` e `O_NONBLOCK`, só arquivo regular, até 40 MiB) e o SHA-256 é conferido com o da fase 1. Se o arquivo sumiu ou mudou, a linha falha com `failed <file>: input changed since validation`, as outras seguem e o código é 1. Isso evita gravar no `sources.csv` um hash que não é o da imagem gravada. Na fase 1, um arquivo que passa no `lstat` mas não pode ser lido (permissão, troca por FIFO) é `invalid_file`.
6. **`item_type_conflict` descoberto sob o lock** (§4.4, passo 2; a coleta gravou entre duas linhas): a linha falha com `failed <file>: item_id already registered with another object_type` (o texto da coleta) e as outras seguem. Um cabeçalho que mudou nesse meio-tempo para a importação com código 1 (`failed <file>: manifest header mismatch` / `sources header mismatch`).
7. **Parada por E/S:** imprime `failed <file>: failed to write dataset` (o texto da coleta) e, em seguida, o total. As linhas seguintes não são impressas.
8. **Validação por coluna com a origem inválida:** com `origin` fora de `contributor`/`external`, o `item_id` só é recusado se não casar nenhum dos dois formatos, e `contributor`/`source_id`/`source_ref` não são conferidos (o problema é o `invalid_origin`). Com o `object_type` desconhecido, o `grade` só é recusado se for um valor fora dos 5 graus. O `item_prefix_mismatch` só é conferido quando o `item_id` casa algum dos dois formatos.
9. **Logs de erro de E/S** usam só o `strerror` ou o nome do tipo da exceção, nunca `str(exc)`, que pode trazer o caminho absoluto (teste `test_io_error_log_has_no_absolute_path`).
10. **Refatoração do `collect.py`:** o `DatasetWriter._read_manifest` e o `_append` passaram a chamar `read_manifest_entries` e `append_csv_row`, com o mesmo comportamento. `_valid_notes` virou `valid_notes` (pública), e `has_forbidden_char` é novo. O `MIN_SHORT_SIDE` vem de `PreprocessParams().resize_shorter` (256), sem número duplicado.
11. **Para o tester (CA-09):** a linha do `manifest.csv` e a do `sources.csv` são escritas com `os.write` sobre um descritor aberto no próprio arquivo (`collect._write_all`, chamado por `append_csv_row`). A imagem é gravada por `collect.write_private_file_atomically`, importada pelo `importer`. O teste do autor injeta o `ENOSPC` num `os.write` cujo descritor aponta para `sources.csv` ou `manifest.csv` (`/proc/self/fd`).

## SPEC_ISSUE (se houver)

**SPEC_ISSUE-01 — nome da constante do `qc_ml` no §4.2 e no CA-15.** O §4.2 e o CA-15 comparam `qc_edge.importer.SOURCES_COLUMNS == qc_ml.data.SOURCES_COLUMNS`. Mas a constante que a SPEC-035 (já mergeada) criou no `qc_ml.data` se chama `SOURCE_COLUMNS`, no singular (`ml/src/qc_ml/data.py:78`, usada em `ml/tests/test_sources.py`, `test_split_external.py` e `synthetic.py`). `qc_ml.data.SOURCES_COLUMNS` não existe. Escrito ao pé da letra, o CA-15 levanta `AttributeError`, e o developer não pode mexer em `ml/`. A implementação segue a SPEC no lado da borda (`qc_edge.importer.SOURCES_COLUMNS`), e o conteúdo das duas tuplas é igual (o teste do autor compara com `qc_ml.data.SOURCE_COLUMNS`). Correção sugerida (pequena, ADR-019): no §4.2 e no CA-15, trocar `qc_ml.data.SOURCES_COLUMNS` por `qc_ml.data.SOURCE_COLUMNS`. A alternativa seria um alias no `qc_ml.data`, mas é trabalho do ml-engineer, fora desta SPEC. Nenhuma das duas muda o código desta rodada.

**SPEC_ISSUE-02 — a coluna de alguns códigos em `plan line <n>: <code> (<coluna>)`.** O CA-04 exige a linha exata `plan line 2: <code> (<coluna>)`. Para a maior parte dos códigos, a tabela do §4.2 diz a coluna. Para estes, não diz: `item_type_conflict`, `duplicate_file` e `duplicate_input` (os três estão no CA-04), e os códigos de registro ou arquivo inteiro (`malformed_row`, `unreadable_csv`, `too_many_rows`), além do `missing_column` quando o cabeçalho tem todas as colunas, mas fora de ordem ou com uma a mais. O que foi implementado:

| Código | Coluna mostrada |
|---|---|
| `item_type_conflict` | `item_id` |
| `duplicate_file`, `duplicate_input` | `file` |
| `missing_column` | o nome de cada coluna ausente, uma linha por coluna (no CA-04: `plan line 1: missing_column (notes)`); `-` quando nenhuma falta (ordem errada ou coluna a mais) |
| `malformed_row`, `unreadable_csv`, `too_many_rows` | `-` |
| `source_fields_mismatch` | `source_id` ou `source_ref`, a que estiver preenchida (as duas, se as duas estiverem) |
| `item_prefix_mismatch` | `object_type` (como na tabela) |

Correção sugerida (pequena, ADR-019): registrar esta tabela no §4.2, ou outra escolha que o architect prefira. Se a escolha for outra, o ajuste no código é só na coluna passada a `add(...)` no `load_plan`.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando: `uv run pytest -q edge/tests` → 1786 passed, 5 skipped. Suíte completa sem banco: 5516 passed, 724 skipped. Suíte completa com `CI=true` e `TEST_DATABASE_URL`: 6186 passed, 54 skipped (30 de Docker, 21 sem o extra `train`, que traz o torch, e 3 do modelo real, que não está no Git)
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim. Os testes de aceite das SPECs anteriores do `edge/` (007, 008, 009, 010, 025, 030) continuam passando sem ajuste
