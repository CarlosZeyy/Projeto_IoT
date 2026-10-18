# SPEC-011 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-011](../../docs/specs/SPEC-011-ml-dados-split.md) |
| Rodada | r1 |
| Autor | ml-engineer |
| Branch | `spec/SPEC-011-ml-dados-split` |
| Commits | `247071e` (feat(ml): manifest, exclusões, split e concordância), `95608d7` (feat(ml): augmentations e `PartsDataset`), `342a8ea` (docs(ml): README), `8074d9c` (test(ml): contagens da CLI para `too_many_jpeg_scans`), mais o commit deste relatório |

## Resumo

- `ml/src/qc_ml/errors.py`: `ManifestProblem` (`code`, `file`, `line`, `image_path`, `message`), `ManifestError` (`problems`; `str()` com um problema por linha), `SplitError` e `SplitIntegrityError` (subclasse de `SplitError`).
- `ml/src/qc_ml/data.py` (módulo):
  - `load_manifest`, `load_exclusions`, `find_raw_images` (órfãos) e `build_data_report`;
  - CLI `python -m qc_ml.data validate|report`, com as linhas `count <code>: <n>` em ordem alfabética depois dos problemas;
  - os CSVs são lidos só com `csv.reader` sobre `io.StringIO(texto, newline="")`, nunca por linhas (SEC-10-03).
- `ml/src/qc_ml/split.py`:
  - `make_split` (estratos por tipo e grau dominante, `round_half_up` com `Decimal`, congelamento do teste, `excluded_previous_image`), `load_split` (confere o `.sha256`), `rows_for`, `assign_splits` e `check_item_integrity`;
  - CLI `python -m qc_ml.split`, que grava `split_v<N>.json`, `.sha256` e, por último, `.csv`, cada um de forma atômica.
- `ml/src/qc_ml/agreement.py`: QWK (`sklearn.metrics.cohen_kappa_score`, pesos quadráticos, `labels=[0..4]`) entre o grau **original** do manifest e `labels_second.csv`, com exclusões e `n_excluded_pairs`.
- `ml/src/qc_ml/augment.py`: `train_transform` só com Pillow e numpy, na ordem e com os parâmetros da §4.5.
- `ml/src/qc_ml/dataset.py`: `PartsDataset` (torch), com `set_epoch`. No treino, aplica `train_transform` com `default_rng([seed, epoch, i])` e depois `qc_preprocess.preprocess`; na avaliação, só `preprocess`.
- `ml/src/qc_ml/synthetic.py`: `make_synthetic_dataset` (layout da SPEC-010, JPEG baseline 256×256) e o auxiliar `add_synthetic_item`.
- `ml/README.md`: os comandos `validate`, `report`, `split` e `agreement`.

## Rastreabilidade (critério de aceite → implementação)

Abreviações dos testes do autor (todos em `ml/tests/`): `d/` = `test_data.py`, `s/` = `test_split.py`, `a/` = `test_agreement.py`, `au/` = `test_augment.py`, `sy/` = `test_synthetic.py`, `ds/` = `test_dataset.py`, `nt/` = `test_no_torch.py`. Os arquivos de produção estão em `ml/src/qc_ml/`.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `data.py` (`load_manifest`, `RESULT_COLUMNS`), `synthetic.py` | `d/::test_loads_the_synthetic_dataset`; `sy/::test_layout_and_manifest` |
| CA-02 | `data.py` (`_row_problems`: `missing_file`) | `d/::test_missing_file` |
| CA-03 | `data.py` (`_image_problem`) | `d/::test_unreadable_image_only_with_verify` |
| CA-04 | `data.py` (`_item_conflicts`, `ITEM_PREFIX_TYPES`) | `d/::test_item_type_conflict_and_prefix_mismatch` |
| CA-05 | `data.py` (`_row_problems`; `line` = número do registro) | `d/::test_grade_on_other_and_missing_grade_with_lines`, `::test_problem_line_is_the_record_number` |
| CA-06 | `data.py` (`ITEM_ID_PATTERN`, `ANGLE_PATTERN`, `GRADES`) | `d/::test_invalid_values`, `::test_item_id_with_unicode_digits_is_invalid`, `::test_tool_prefix_is_not_accepted_yet` |
| CA-07 | `data.py` (uma `ManifestError`, `print_problems`, `main`) | `d/::test_all_problems_in_one_error_and_cli`, `::test_str_of_error_has_one_problem_per_line` |
| CA-08 | `data.py` (`_read_overrides`, `grade_original`, `overridden`) | `d/::test_override_changes_the_grade` |
| CA-09 | `data.py` (`_read_overrides`: vale a última linha; `override_unknown_image`) | `d/::test_last_override_wins_and_unknown_image`, `::test_override_problems` |
| CA-10 | `data.py` (override aplicada antes das validações de linha) | `d/::test_override_fills_a_missing_grade` |
| CA-11 | `data.py` (`build_data_report`, `main report`) | `d/::test_report`, `::test_report_without_split`, `::test_report_with_outdated_split` |
| CA-12 | `split.py` (`make_split`, `check_item_integrity`) | `s/::test_items_never_cross_splits` |
| CA-13 | `split.py` (`_allocate`, `round_half_up`) | `s/::test_each_stratum_has_14_3_3`, `::test_round_half_up`, `::test_three_items_get_one_each` |
| CA-14 | `split.py` (`_allocate`: `small_stratum`) | `s/::test_small_stratum_goes_to_train` |
| CA-15 | `split.py` (`split_csv_bytes`, `write_split`, `main`) | `s/::test_cli_files_are_reproducible`, `::test_same_seed_same_split_other_seed_differs` |
| CA-16 | `split.py` (`make_split` com `previous`) | `s/::test_freeze_with_new_items_and_new_images` |
| CA-17 | `split.py` (`_same_split`, `main`) | `s/::test_unchanged_writes_nothing` |
| CA-18 | `split.py` (`SplitError` antes de qualquer gravação) | `s/::test_missing_test_image_is_an_error` |
| CA-19 | `split.py` (`load_split`) | `s/::test_load_split_detects_edits` |
| CA-20 | `split.py` (`rows_for`, `assign_splits`) | `s/::test_rows_for` |
| CA-21 | `agreement.py` (`compute_agreement`, `main`) | `a/::test_known_values` |
| CA-22 | `agreement.py` | `a/::test_inverted_ratings` |
| CA-23 | `agreement.py` (problemas → saída 2, nada gravado) | `a/::test_unknown_image_is_exit_2`, `::test_invalid_grade_and_no_pairs` |
| CA-24 | `augment.py` (`train_transform`) | `au/::test_deterministic_size_and_mode` e os demais de `au/` |
| CA-25 | `dataset.py` (`PartsDataset`) | `ds/::test_eval_items_are_the_shared_preprocessing` (ver "Como rodar": passou com torch instalado) |
| CA-26 | `agreement.py` (import do sklearn adiado; ver decisões), demais módulos sem torch | `nt/::test_modules_import_without_torch` |
| CA-27 | nenhum arquivo de imagem criado em `ml/`; testes em `tmp_path` | `nt/::test_no_images_tracked_under_ml` |
| CA-28 | `data.py` (`JPEG_SCANS_TEXT`, `MOTION_PHOTO_HINT`) | `d/::test_too_many_jpeg_scans_is_its_own_code`, `::test_too_many_jpeg_scans_cli_counts` |
| CA-29 | `data.py` (`parse_csv`) | `d/::test_manifest_is_read_as_csv_not_by_lines` |
| CA-30 | `data.py` (`find_raw_images`, `orphan_image`) | `d/::test_orphan_image_with_and_without_verify`, `::test_find_raw_images_does_not_follow_symlinks` |
| CA-31 | `data.py` (`_read_exclusions`, `load_exclusions`), `agreement.py` | `d/::test_exclusion_removes_the_row`, `::test_exclusion_problems`, `::test_excluded_image_override_is_ignored`, `::test_excluded_row_does_not_hide_duplicates`; `a/::test_excluded_images_leave_both_files` |
| CA-32 | `split.py` (`excluded_previous_image`) | `s/::test_excluded_test_image_leaves_the_split` |

## Como rodar e verificar

```bash
uv sync --all-packages
uv run pytest -q ml/tests                       # 85 passed, 1 skipped (test_dataset.py sem torch)
uv run ruff check . && uv run ruff format --check .
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

Resultados desta rodada:
- **Suíte inteira, ambiente do CI** (`uv sync --all-packages --locked`, sem torch): `4510 passed, 2 skipped` (o `test_dataset.py` sem torch e o CA-16 manual da SPEC-008). `ruff check` e `ruff format --check` limpos.
- **CA-25 com torch:** `uv sync --all-packages --extra train --locked` instalou o torch 2.14.1 sem problemas. Os 3 testes de `ml/tests/test_dataset.py` e os 2 de `test_no_torch.py` **passaram** com torch instalado. Depois, o `.venv` voltou ao estado do CI (`uv sync --all-packages --locked`, que remove o torch). Para rodar o CA-25 de novo: `uv sync --all-packages --extra train`.
- **Atenção, ambiente com o extra `train`:** a suíte inteira tem 3 falhas em `edge/tests/test_publisher_real_api.py` (SPEC-009), sem relação com esta SPEC. O `timm` puxa o `huggingface-hub` 2.2.0, que puxa o `httpx2`. Com o `httpx2` instalado, o `starlette.testclient` passa a usá-lo, e o `httpx` do publisher recusa o stream (`assert isinstance(response.stream, SyncByteStream)`). Sem o extra (CI), as 3 passam. Ver "Observações para o orquestrador".

CLIs exercitadas de ponta a ponta, por `python -m` e num diretório temporário fora do repositório:
- `split`: v1, depois `split unchanged`;
- CA-18: saída 2, a imagem citada no stderr e nenhum arquivo novo;
- CA-32: `split_v2` com o aviso e saída 0;
- `report`: `n_excluded = 1`;
- CA-28: `validate` com as duas linhas `count` na ordem.

## Decisões tomadas dentro do escopo da SPEC

- **Saída das CLIs.** O `validate` imprime os problemas e as contagens em **stdout**, porque é a saída do comando (CA-07, CA-28, CA-30). Nas CLIs `split` e `agreement`, os erros e os problemas do manifest vão para **stderr**, e as mensagens de sucesso (`split written: ...`, `split unchanged: split_v<N>`, `agreement written: ...`) vão para stdout. Erro de argumento → saída 2 (o `SystemExit` do argparse é convertido). Toda CLI expõe `main(argv) -> int`.
- **Formato do `ManifestProblem`:**
  - `file` é o nome do CSV onde o problema foi achado: `manifest.csv`, `labels_overrides.csv` ou `exclusions.csv`. O `orphan_image` usa `manifest.csv` (falta a linha), com `line=None`;
  - `str(problem)` é `<arquivo>:<registro>: <code>: <image_path>: <mensagem>`, ou `<arquivo>: ...` sem registro;
  - o `item_type_conflict` sai uma vez por peça, no registro da primeira linha cujo tipo difere do primeiro tipo da peça, e a mensagem cita o `item_id` e os registros.
- **Códigos extras, defensivos e fora da tabela da §4.1.** Nenhum CA os produz com o dataset sintético:
  - `malformed_row`: registro com número de campos diferente do cabeçalho;
  - `unreadable_csv`: CSV que não é UTF-8 ou não é CSV válido;
  - `invalid_image_path`: `image_path` absoluto, com `..`, `.`, componente vazio, `\` ou NUL, no manifest ou em `exclusions.csv`. Ele impede que o pipeline leia arquivos fora do `DATASET_DIR`.

  Um BOM no início do manifest gera `missing_column`, com a dica "(the file starts with a BOM)".
- **Números de registro:** o cabeçalho é o registro 1. Registros vazios são pulados sem receber número, como no `csv.DictReader`. Uma célula com `\n` entre aspas não desloca a numeração (`d/::test_problem_line_is_the_record_number`).
- **Colunas do resultado:** exatamente as 9 do manifest, mais `grade_original` e `overridden`. Colunas extras do arquivo são ignoradas. As colunas de texto usam `dtype=object`, para o grau ausente continuar `None` no pandas 3 (cujo `str` padrão viraria `NaN`). `angle` é `int64`, e `overridden` é `bool`.
- **Overrides:**
  - vale a última linha **válida** para o mesmo `image_path`;
  - uma linha com grau inválido gera `invalid_grade` (em `labels_overrides.csv`) e não é aplicada;
  - uma linha sem `reason` gera `override_missing_reason`, mas é aplicada, para não gerar um `missing_grade` em cascata;
  - um grau vazio na override vale como "sem grau";
  - o `labeler` da linha do manifest não muda.
- **Exclusões:**
  - `load_exclusions` faz as validações que não dependem do manifest: `missing_column`, `exclusion_invalid_reason` (vazio incluso), `invalid_image_path` e `excluded_file_present` (`os.path.lexists`, que também pega um link simbólico);
  - `exclusion_unknown_image` precisa do manifest e é conferido só por `load_manifest`;
  - uma imagem excluída com `reason` inválido também sai do resultado, para não gerar problemas em cascata;
  - `n_excluded` conta os `image_path` excluídos que existem no manifest.
- **Órfãos:**
  - a extensão é comparada **sem diferenciar maiúsculas** (`.jpg` e `.JPG`). É mais estrito que o texto e pega uma cópia vinda do app da câmera;
  - nenhum link simbólico **abaixo** de `raw/` é seguido, nem diretório nem arquivo. O próprio `raw/` é seguido se for um link, porque é o diretório do dataset escolhido pela dupla (por exemplo, num disco externo).
- **Metadados do relatório:** `build_data_report(df, split_df)` mantém a assinatura da SPEC e lê `manifest_sha256` e `n_excluded` de `df.attrs` (gravados por `load_manifest`) e `split_file` (só o nome do arquivo) e `split_sha256` de `split_df.attrs` (gravados por `load_split`). Sem split, `counts` traz só a chave `total`; com split, `train`, `val`, `test` e `total`. Os 5 graus de `screw`/`nut` aparecem sempre, mesmo zerados, para que `below_target` e `below_minimum` listem também as combinações sem nenhuma imagem.
- **Split:**
  - em cada estrato, a ordem permutada vai primeiro para o teste (`n_test`), depois para a validação (`n_val`) e o resto para o treino;
  - `rng.permutation` roda em **todo** estrato, inclusive nos pequenos, para o consumo do gerador não depender do tamanho dos estratos;
  - com proporções atípicas, a alocação garante ao menos 1 peça no treino.
- **Peças novas com split congelado:**
  - a fração de validação é `0,15 / 0,85` (70:15), com o mesmo `round_half_up`;
  - com 3 ou mais peças novas no estrato, há no mínimo 1 em validação; com menos de 3, todas vão para o treino, com aviso `small_stratum`;
  - li "a mesma regra de arredondamento" como a mesma regra de alocação da §4.4, sem o teste. Isso não muda o CA-16: 5 peças dão 1 em validação pelas duas leituras.
- **Formato dos avisos:** dicionários com `code`, como `{"code": "small_stratum", "stratum": "screw/fair", "n_items": 2}`, `{"code": "excluded_previous_image", "image_path": ..., "split": "test"}` e `{"code": "missing_previous_image", ...}`.
- **Integridade:** `make_split` e `rows_for` levantam `SplitIntegrityError` se uma peça cair em dois splits. `make_split` também a levanta se uma imagem do split anterior mudasse de conjunto, ou se o split anterior já tiver uma peça em dois conjuntos.
- **Arquivos do split:**
  - o `split_v<N>.json` tem `split_file`, `seed`, `ratios`, `parent`, `manifest_sha256`, `counts` (`images` e `items` por split) e `warnings`;
  - **não** tem `generated_at`, para dois runs iguais darem o mesmo JSON;
  - a ordem de gravação é `.json`, `.sha256` e, por último, `.csv`: um `.csv` em disco sempre tem os outros dois;
  - `load_split` aceita o `.sha256` com o formato `<hex>  <nome>` e compara só o hex.
- **`ml/splits/` não foi criado.** O `split_v1` só deve sair dos dados reais da S3 (§7 da SPEC), e é a dupla que roda e commita (plano de testes, "Manual").
- **`ModelLabels`/`DEFAULT_LABELS`** (`object_types = ("screw","nut","other")` e os 5 graus) ficam em `qc_ml.data`, porque a SPEC não define o tipo de `labels`. O `PartsDataset` aceita qualquer objeto com `object_types`.
- **Dataset sintético:**
  - os graus seguem em rodízio dentro de cada tipo: `S-001` perfect, `S-002` good, `S-003` fair, `S-004` poor, `S-005` unusable, `S-006` perfect etc. Assim o `S-003` tem imagens `fair`, como o CA-08 pressupõe;
  - os timestamps são únicos e crescentes a partir de 2026-10-22T14:00:00Z, com `labeler=a` e `capture_device=synthetic`;
  - `make_synthetic_dataset` recusa um `root` que já tenha `manifest.csv`;
  - `add_synthetic_item` serve para os testes de congelamento (CA-16).
- **Augment:**
  - a ordem das 4 operações do `ColorJitter` é sorteada pelo `rng`, como no torchvision;
  - o matiz é girado no espaço HSV do Pillow;
  - o fallback do `RandomResizedCrop` é o do torchvision (corte central com a razão limitada);
  - o blur usa `GaussianBlur(radius=sigma)`, porque o raio do Pillow é o desvio-padrão.
- **CA-26 e o scipy:**
  - com `sys.modules["torch"] = None`, **`import scipy.stats` quebra** com `AttributeError: 'NoneType' object has no attribute 'Tensor'`. A checagem de array-API do scipy 1.18.1 (vendorizada em `array_api_compat`) lê `sys.modules["torch"]` e só trata `KeyError`;
  - o `sklearn` importa o `scipy.stats`, então `qc_ml.agreement` importa `sklearn.metrics` **dentro** de `compute_agreement`, com um comentário explicando o motivo;
  - no CI real, sem torch instalado, a chave não existe e o import funciona de qualquer jeito.

  O tester deve saber que um teste do CA-26 que importe o `sklearn` ou o `scipy.stats` no mesmo subprocesso falha por esse motivo, e não por causa do `qc_ml`.
- **Versão do `qc-ml`:** continua `0.0.0`. A SPEC não pede aumento, e mudar a versão alteraria o `uv.lock`, que está fora dos caminhos do ml-engineer. Nenhuma dependência foi adicionada: `pandas`, `numpy`, `scikit-learn`, `pillow` e o extra `train` já estavam no `ml/pyproject.toml` e no lock. As dependências de `api/`, `dashboard/` e `edge/` não mudaram (R-12).
- **Testes de aceite de SPECs anteriores:** nenhum foi afetado.

## SPEC_ISSUE (se houver)

Nenhum.

## Observações para o orquestrador (não bloqueiam esta SPEC)

1. **Extra `train` × testes reais da borda (ambiente local).** Com `uv sync --all-packages --extra train`, o `httpx2` (via `timm` → `huggingface-hub`) faz o `starlette.testclient` trocar de cliente HTTP. Com isso, 3 testes de `edge/tests/test_publisher_real_api.py` falham. O CI não instala o extra e não é afetado. A SPEC-012 exige torch localmente (CA-07 `slow`), e quem rodar a suíte inteira com o extra instalado vai ver essas 3 falhas. Cabe ao developer (dono de `edge/`), via SPEC, decidir se ajusta os testes ou o transporte. Por ora, o `.venv` ficou **sem** o extra, no estado do CI.
2. **SPEC-012, CA-27 (aviso antecipado).** O mesmo mecanismo do CA-26 (`sys.modules["torch"] = None`) vai quebrar o import de qualquer módulo que importe `sklearn` ou `scipy.stats` no nível do módulo, como os prováveis `thresholds` e `evaluate`. A saída é a mesma usada aqui (import adiado), ou então o architect pode preferir trocar o mecanismo do CA.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (`ml/tests`: 85 passed, 1 skipped sem torch; com torch, os 3 de `test_dataset.py` passaram)
- [x] Suíte inteira no ambiente do CI: 4510 passed, 2 skipped
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nada de `ml/data/` lido, copiado ou commitado; nenhuma imagem em `ml/` no Git
