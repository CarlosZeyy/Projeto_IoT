# SPEC-035 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-035](../../docs/specs/SPEC-035-ml-origem-das-imagens.md) |
| Rodada | r1 |
| Autor | ml-engineer |
| Branch | `spec/SPEC-035-origem-das-imagens` |
| Commits | `e50bab3`, `851ef7d`, `33bcf5c` (+ o commit deste relatório) |

## Resumo

- O `qc_ml.data` aceita o `item_id` externo (`X[SNOT]-NNNN`). O `load_manifest` passou a ler e validar `DATASET_DIR/sources.csv` e o registro `ml/external_sources.csv` (lista fechada de licenças do ADR-020) e ganhou as colunas `origin`, `contributor` e `source_id`.
- O `qc_ml.split` põe toda imagem externa no treino, fora dos estratos. Ele recusa uma peça externa em val/test (no `previous`, no `history`, no `item_history` e no `rows_for`) e aplica o teto `max_external_fraction` (0,30), com comparação exata por `Fraction`.
- O relatório de dados e o `metrics.json` (`counts.<split>.by_origin` e `by_source`) mostram a contagem por origem. A entrada do CHANGELOG ganhou a seção `### Dados`.
- Subcomando novo `python -m qc_ml.report release-notes`. Ele gera as notas do Release com os créditos e sai com 2 quando uma fonte usada no treino não está no registro.
- `TrainConfig.external_sources`, `make_synthetic_dataset` com peças de conhecido e imagens externas, `ml/external_sources.csv` só com o cabeçalho e a seção "Origem das imagens" no `ml/README.md`.
- Não houve treino: nenhum `metrics.json` novo de modelo real.
- Nenhum SPEC_ISSUE.

## Rastreabilidade (critério de aceite → implementação)

Arquivos de teste: `ml/tests/test_sources.py` (S), `ml/tests/test_split_external.py` (X) e `ml/tests/test_origin_reports.py` (R).

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `ml/src/qc_ml/data.py` (`ITEM_ID_PATTERN`, `item_type_letter`, `is_external_item`, `_row_problems`); `ml/src/qc_ml/split.py` (`IMAGE_FILE_PATTERN`) | S `test_ca01_item_id_pattern`, `test_prefix_of_external_item` (5 casos); `ml/tests/test_maintenance.py::test_item_id_pattern_is_defined_once` |
| CA-02 | `data.py` (`load_manifest`, `_read_sources`) | S `test_ca02_origin_columns` |
| CA-03 | `data.py` | S `test_ca03_without_sources`, `test_default_registry_is_the_repository_one` |
| CA-04 | `data.py` (`_read_sources`, `_source_row_problems`, `_sources_manifest_problems`, `main`) | S `test_ca04_sources_problems` (19 casos: os 13 do CA e variações), `test_ca04_own_image_marked_external`, `test_contributor_line_for_external_item`, `test_ca04_missing_column`, `test_ca04_validate_cli_counts`, `test_validate_cli_ok_with_sources`, `test_external_without_registry_is_unknown_source`, `test_load_sources`, `test_load_sources_absent` |
| CA-05 | `data.py` (`_read_registry`, `_registry_row_problems`, `load_external_sources`) | S `test_ca05_registry_problems` (22 casos, inclusive os 6 de `invalid_license`), `test_ca05_duplicate_source_id`, `test_ca05_header_only_registry_without_externals`, `test_registry_is_validated_even_when_unused`, `test_load_external_sources_values` |
| CA-06 | `data.py` | S `test_ca06_excluded_external_image`, `test_excluded_lines_are_not_checked` |
| CA-07 | `split.py` (`make_split`) | X `test_ca07_externals_in_train_and_own_split_unchanged`, `test_small_stratum_counts_only_own_items` |
| CA-08 | `split.py` (`make_split`, `_counts`, `write_split`) | X `test_ca08_new_externals_go_to_train` |
| CA-09 | `split.py` (`_check_external_history`, `item_history`, `rows_for`, `main`) | X `test_ca09a_cli_refuses_external_in_test`, `test_ca09b_c_make_split_and_rows_for`, `test_ca09_history_and_item_history`, `test_external_of_previous_resolved_by_file_name` |
| CA-10 | `split.py` (`_check_max_external_fraction`, `_fraction_argument`, `make_split`) | X `test_ca10_ceiling_is_accepted`, `test_ca10_above_ceiling`, `test_ca10_invalid_ceiling_argument` (`0`, `1.5`, `abc`, `-0.1`, `nan`, `inf`, vazio), `test_ceiling_argument_accepts_one`, `test_make_split_rejects_invalid_ceiling`, `test_ceiling_comparison_is_exact`, `test_no_train_images_no_ceiling` |
| CA-11 | `data.py` (`build_data_report`, `image_origins`) | R `test_ca11_data_report`, `test_data_report_without_split_or_externals`; `ml/tests/test_data.py::test_report` (conjunto de chaves atualizado) |
| CA-12 | `ml/src/qc_ml/evaluate.py` (`split_counts`), `config.py`, `thresholds.py`, `train.py` | R `test_ca12_metrics_counts`, `test_ca12_thresholds_fail_without_the_registry`, `test_split_counts_without_origin_columns`, `test_config_external_sources_field` |
| CA-13 | `ml/src/qc_ml/report.py` (`data_section`, `source_lines`, `changelog_entry`, `main`) | R `test_ca13_changelog_data_section`, `test_data_section_fraction_rounds_up`, `test_changelog_registry_problem_fails` |
| CA-14 | `ml/external_sources.csv` | S `test_ca14_repository_registry` |
| CA-15 | `ml/src/qc_ml/synthetic.py` | S `test_ca15_default_generator_unchanged`, `test_generator_layout`, `test_generator_contributors_only`, `test_generator_limits` |
| CA-16 | `report.py` (`release_notes`, `_release_notes_main`, `_write_stdout`) | R `test_ca16_release_notes`, `test_ca16_stdout_bytes_in_subprocess` |
| CA-17 | `report.py` (`ReleaseNotesError`, `shown_source_id`) | R `test_ca17_source_not_in_registry_blocks`, `test_ca17_header_only_registry_blocks`, `test_ca17_invalid_source_id_is_not_echoed`, `test_ca17_order_of_two_sources` |
| CA-18 | `report.py` | R `test_ca18_release_notes_without_externals[empty]` e `[old-metrics]` |
| CA-19 | `report.py` | R `test_ca19_release_notes_errors` (7 casos: os 5 do CA, mais `metrics.json` que não é objeto e `by_source` que não é objeto), `test_release_notes_default_registry`, `test_release_notes_function_is_pure` |
| CA-20 | `ml/README.md` | R `test_ca20_readme_section` |

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1).

## Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
uv run pytest -q ml/tests
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q

# Parte com torch (só ml/tests), e depois volta ao ambiente do CI
uv sync --all-packages --extra train --locked
uv run pytest -q ml/tests
uv sync --all-packages --locked
```

Resultados (2026-10-24, depois do último commit de código):

- `ruff check .`: limpo. `ruff format --check .`: 230 arquivos formatados.
- `uv run pytest -q ml/tests` sem torch: **521 passed, 23 skipped**.
- Com o extra `train`: **560 passed, 2 skipped** (os 2 são do `model.onnx` real, que não existe neste checkout). Cobre o `train.py` com o `load_manifest(..., external_sources=...)` e o `training_config.json` com o campo novo. Depois, `uv sync --all-packages --locked` voltou o `.venv` ao estado do CI (torch ausente, conferido).
- Suíte completa com banco (`CI=true` e `TEST_DATABASE_URL`): **5882 passed, 54 skipped**, 1 aviso que não vem do `ml/`.

Os testes de aceite das SPECs 011, 012 e 031 passam sem nenhuma alteração.

## Decisões tomadas dentro do escopo da SPEC

1. **`n_external_images` no `split_v<N>.json`** fica em `counts.n_external_images = {"train", "val", "test"}`. É a mesma forma das chaves que já existem (`counts.images` e `counts.items`, cada uma com um valor por split). A SPEC diz "nas contagens por split" sem fixar o caminho, e essa é a forma que não muda a estrutura atual.
2. **Ordem das checagens de `sources.csv`:**
   - Linha com `image_path` inválido: só `invalid_image_path`.
   - Linha repetida: só `duplicate_source_row`, na segunda ocorrência.
   - Linha de imagem excluída: entra no `duplicate_source_row` e no `source_unknown_image` (arquivo inteiro), mas não nas checagens de linha nem no `duplicate_input`.
   - O `external_item_mismatch` só é conferido nas linhas sem outro problema.
   - Com `missing_column` ou `unreadable_csv` no `sources.csv`, o `missing_source` não é conferido, para não gerar um problema por imagem externa a partir de um arquivo ilegível.
3. **Registro com fonte inválida:** o `source_id` de uma linha com outro problema (por exemplo, `license` recusada) ainda conta como conhecido para o `sources.csv`. Assim o erro aparece uma vez, no registro (`invalid_license`), em vez de virar também um `unknown_source_id` por imagem. Com o `source_id` fora do formato (CA-05, `Synthetic`), as imagens também acusam `unknown_source_id`.
4. **`load_sources(dataset_dir, registry)`** faz as checagens que não precisam do manifest e lê o `exclusions.csv` para ignorar as linhas excluídas. Devolve as linhas mantidas, com `attrs["sources_sha256"]`. Os três problemas que precisam do manifest (`source_unknown_image`, `external_item_mismatch`, `missing_source`) só são conferidos pelo `load_manifest`. É o mesmo padrão do `load_exclusions` com o `exclusion_unknown_image`. O `load_manifest` usa as mesmas funções internas, sem chamar o `load_sources`, para não reportar duas vezes os problemas do `exclusions.csv`.
5. **`load_external_sources` com arquivo ausente** devolve `{}`, a regra "registro ausente = registro vazio" do `load_manifest` e do `release-notes`.
6. **Seção `### Dados`:** entra depois da tabela e da linha "Peças no teste por grau" e antes de "### O que mudou". Ela aparece quando algum split de `counts` tem `by_origin`. A fração é calculada exatamente (`ceil(Fraction · 10⁴)`). Com `n_train = 0`, a fração aparece como `—`.
7. **`source_id` inválido no CHANGELOG:** a linha usa o mesmo `shown_source_id` do `release-notes`. Um `source_id` do `metrics.json` fora do formato do §4.3 aparece como `` `<invalid source_id>` ``, e o valor não é ecoado no `CHANGELOG.md`, que vai para o Git. Um id fora do formato nunca está no registro, então a linha termina sempre com "licença não encontrada no registro". Para os ids válidos, o texto é exatamente o do §4.6.
8. **`release-notes`:**
   - O stdout é escrito em bytes UTF-8 (`sys.stdout.buffer`), para ser igual ao arquivo, byte a byte, mesmo com `LC_ALL=C` (testado em subprocesso).
   - O `--output` é gravado de forma atômica (arquivo temporário no mesmo diretório e `os.replace`), depois de todas as validações. Em erro, não sobra arquivo temporário (conferido no CA-19).
   - Um `counts.train.by_source` que não é objeto JSON, ou um `metrics.json` que não é objeto, sai com 2. A SPEC não lista esses dois casos, mas gerar notas a partir deles daria créditos errados.
9. **`TrainConfig.external_sources`:** aceita `null` ou um texto não vazio. O texto vazio é recusado (`ConfigError`), porque `Path("")` apontaria para o diretório atual. O campo não está em `HYPERPARAMETER_FIELDS`, então não entra em `deviations_from_defaults`.
10. **Gerador sintético:**
    - As peças próprias vêm primeiro no plano, então as imagens delas não mudam com `c` e `k` (testado).
    - O `external_sources.csv` só é criado com `k > 0`. Com `c > 0` e `k = 0`, sai só o `sources.csv`; o `load_manifest` aceita, porque registro ausente = registro vazio.
    - O título da fonte sintética, que a SPEC não fixa, é `Synthetic dataset`.
    - Limites: `c ≤ 99` (as peças de conhecido vão até 999) e `5k ≤ 9999`.
11. **`ml/tests/test_maintenance.py::test_item_id_pattern_is_defined_once`** (teste de autor da SPEC-031) comparava o `IMAGE_FILE_PATTERN` com o texto literal `[SNOT]-[0-9]{3}`. Agora ele confere que o padrão é montado a partir do `ITEM_ID_PATTERN`, como exige a §4.1.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (sem torch e com o extra `train`)
- [x] `.env.example` atualizado (se houver variável nova): não se aplica, nenhuma variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhuma imagem real: só dados sintéticos em `tmp_path` (R-14); nenhum valor com cara de segredo
