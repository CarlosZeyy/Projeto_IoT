# SPEC-011 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-011](../../docs/specs/SPEC-011-ml-dados-split.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `0cc1ada` |
| **Veredicto** | **PASS** |

O veredicto é PASS por quatro motivos:
- os 32 CAs têm teste de aceite e todos passam;
- o CA-25, que precisa de torch, passou com o extra `train` instalado e é pulado no ambiente do CI, como a SPEC prevê;
- a suíte inteira passa no ambiente do CI;
- o ruff está limpo.

Encontrei um bug, o T-01 (média). Ele não viola nenhum CA, então não muda o veredicto, mas contraria a regra de congelamento da §4.4. Recomendo corrigi-lo antes do merge ou registrá-lo como decisão.

Arquivo de aceite: `ml/tests/acceptance/test_spec_011.py`, com:
- 32 funções `test_caNN_*`;
- 40 `test_extra_*`;
- 1 `test_bug_t01_*`, com `xfail(strict=False)`.

São **84 casos** depois da parametrização.
- **Sem torch (CI):** 81 passam, 2 são pulados (o CA-25 e o `test_extra_parts_dataset_train_mode`, os dois com `importorskip("torch")`) e 1 é `xfail` (T-01).
- **Com torch:** os 83 casos que não são o T-01 passam.

Escrevi os testes a partir da SPEC, antes de ler a implementação. Depois de lê-la, acrescentei os testes exploratórios do fim do arquivo e o do T-01. Nenhum `test_caNN_*` mudou depois da leitura do código.

Como os testes funcionam:
- **Dados:** todo dataset vem de `make_synthetic_dataset` em `tmp_path`. Ele é gerado uma vez por módulo e copiado para cada teste. As imagens extras são desenhadas com Pillow no próprio teste. Nada é lido de `ml/data/` (R-14).
- **CLIs:** rodam por `main(argv)` (com `capsys`) ou por `python -m` em subprocesso. O CA-07 usa `qc_ml.data validate` e o CA-15 usa `qc_ml.split`, as duas pelo `python -m`. Nenhum teste roda o pytest em subprocesso (§10 da arquitetura).
- **Mocks:** nenhum. Só o sistema de arquivos temporário.
- **Isolamento do fixture próprio:** o arquivo não usa as fixtures do `ml/tests/conftest.py` do autor. Os auxiliares de leitura e escrita do manifest estão no próprio arquivo.

## Cobertura dos critérios de aceite

Prefixo dos testes: `ml/tests/acceptance/test_spec_011.py::`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_load_synthetic_manifest`: 88 linhas, colunas do manifest + `grade_original` + `overridden`, 8 `other` com grau `None`, 44 peças | ✅ |
| CA-02 | `test_ca02_missing_file`: exatamente 1 problema, `missing_file`, com o `image_path` apagado | ✅ |
| CA-03 | `test_ca03_unreadable_image_only_with_verify`: 1 `unreadable_image`; com `verify_images=False`, 88 linhas sem erro | ✅ |
| CA-04 | `test_ca04_item_type_conflict`: `item_type_conflict` citando `S-001` e 1 `item_prefix_mismatch` no registro alterado | ✅ |
| CA-05 | `test_ca05_grade_on_other_and_missing_grade_lines`: `grade_on_other` e `missing_grade` com o número do registro (cabeçalho = 1) e o `image_path` certos | ✅ |
| CA-06 | `test_ca06_invalid_values`: `invalid_grade`, `invalid_angle` e `invalid_item_id` | ✅ |
| CA-07 | `test_ca07_all_problems_in_one_error_and_cli`: uma `ManifestError` com exatamente os 3 códigos; `python -m qc_ml.data validate` sai com 2 e imprime uma linha por problema (código + `image_path`) | ✅ |
| CA-08 | `test_ca08_override_changes_the_grade`: `grade="poor"`, `grade_original="fair"`, `overridden=True`; as outras 87 com `False` | ✅ |
| CA-09 | `test_ca09_last_override_wins_and_unknown_image`: a última override (`poor`) vale; override para imagem inexistente dá `override_unknown_image` | ✅ |
| CA-10 | `test_ca10_override_fills_missing_grade`: grau vazio corrigido por override, sem erro | ✅ |
| CA-11 | `test_ca11_data_report`: CLI `report` com `--split`; todas as chaves da §4.2, `n_images=88`, `n_items=44`, `below_target` com exatamente as 10 combinações (8 imagens e 4 peças cada), `below_minimum` com as 10, hashes do manifest e do split conferidos, soma de `counts` por split = 88, nenhum caminho absoluto no JSON | ✅ |
| CA-12 | `test_ca12_items_never_cross_splits`: interseções de `item_id` dois a dois vazias; cada peça com 1 split só | ✅ |
| CA-13 | `test_ca13_each_stratum_14_3_3`: os 11 estratos (10 `screw`/`nut` × grau + `other`) com 14/3/3 peças | ✅ |
| CA-14 | `test_ca14_small_stratum_goes_to_train`: estrato com 2 peças todo em treino; aviso `small_stratum` com o tipo e o grau do estrato | ✅ |
| CA-15 | `test_ca15_cli_reproducible_and_seed_matters`: dois `split_v1.csv` idênticos byte a byte (`python -m`); `.sha256` = `"<hex>  split_v1.csv\n"` conferido com `hashlib`; com `--seed 7`, ao menos uma peça muda de split | ✅ |
| CA-16 | `test_ca16_frozen_test_with_new_items_and_images`: 5 peças novas `screw/fair` só em treino/val; as 2 imagens novas da peça de teste vão para o teste; as linhas do v1 não mudam; o teste do v2 = o teste do v1 + as 2 imagens; `parent = "split_v1"`; o `load_split` do v2 confere | ✅ |
| CA-17 | `test_ca17_unchanged_writes_nothing`: saída 0, `split unchanged: split_v1`, nenhum `split_v2.csv` e o diretório idêntico byte a byte | ✅ |
| CA-18 | `test_ca18_missing_test_image_is_an_error`: imagem de teste tirada do manifest e do disco → saída 2, imagem citada, diretório de splits intocado | ✅ |
| CA-19 | `test_ca19_load_split_detects_hand_edits`: uma linha `test` → `train` → `SplitError` | ✅ |
| CA-20 | `test_ca20_rows_for_outdated_split`: imagem nova sem split → `SplitError` com `split outdated` | ✅ |
| CA-21 | `test_ca21_agreement_known_values`: `n_pairs=10`, `qwk=32/35` (±1e-4 e igual ao `cohen_kappa_score`), `exact=0.7`, `off_by_one=1.0`, `confusion[0][1]=1`, `meets_*` verdadeiros, todas as chaves da §4.3, hashes dos dois arquivos | ✅ |
| CA-22 | `test_ca22_agreement_inverted`: `qwk=-1.0` (±1e-6), `meets_minimum=false` | ✅ |
| CA-23 | `test_ca23_agreement_unknown_image`: saída 2, imagem citada, `agreement.json` não gravado | ✅ |
| CA-24 | `test_ca24_train_transform_deterministic`: duas saídas com `default_rng(1)` idênticas, 256×256, `RGB`; entrada intocada | ✅ |
| CA-25 | `test_ca25_parts_dataset_eval_items` (`importorskip("torch")`): tensor `(3,224,224)` `float32`, `np.array_equal` com `preprocess(load_image(path), params)[0]`, `type_idx=1`, `grade_idx=3`; `other` → `type_idx=2`, `grade_idx=-1` | ✅ com torch (pulado no CI, como manda a SPEC) |
| CA-26 | `test_ca26_modules_import_without_torch`: subprocesso com `sys.modules["torch"] = None` importa os 5 módulos, sem `ImportError`, e `torch` continua `None` (nada o substituiu); `torchvision` e `timm` não são importados | ✅ |
| CA-27 | `test_ca27_no_images_tracked_under_ml`: `git ls-files ml` sem `.jpg`, `.jpeg` ou `.png` fora de `ml/reports/` | ✅ |
| CA-28 | `test_ca28_too_many_jpeg_scans`: o JPEG sintético tem 1 `FF DA` e termina no EOI; com `+ b"\xff\xda" * 64`, exatamente 1 `too_many_jpeg_scans` (mensagem com `JPEG scans` e `dataset-protocol`) e 1 `unreadable_image`, nenhum outro problema; `validate` sai com 2 e as linhas `count too_many_jpeg_scans: 1` e `count unreadable_image: 1` nessa ordem; com `verify_images=False`, 88 linhas | ✅ |
| CA-29 | `test_ca29_manifest_read_as_csv_not_by_lines`: `notes="a b c‮d"` e `capture_device="Phone\x85X"` escritos com `csv.writer`; `splitlines()` dá mais de 89; `load_manifest` dá 88 linhas e as duas células voltam iguais | ✅ |
| CA-30 | `test_ca30_orphan_image`: com `verify_images` verdadeiro e falso, exatamente 1 problema, `orphan_image`, com o caminho relativo pedido e `line=None`; o `tmpab12cd` é ignorado; `validate` sai com 2 e imprime `count orphan_image: 1` | ✅ |
| CA-31 | `test_ca31_exclusions`: arquivo em disco → `excluded_file_present`; apagado → 87 linhas, sem a imagem; `load_exclusions` correto; `apply_overrides=False` também tira a linha; `n_excluded=1` no relatório; a override da imagem excluída é ignorada; `selfie` → `exclusion_invalid_reason`; caminho fora do manifest → `exclusion_unknown_image`; concordância com a excluída + 9 → saída 0, `n_pairs=9`, `n_excluded_pairs=1` | ✅ |
| CA-32 | `test_ca32_excluded_test_image_leaves_the_split`: saída 0, `split_v2.csv` sem a imagem e com todas as outras linhas do v1 iguais; 1 aviso `excluded_previous_image` com o `image_path` e `split="test"` no `split_v2.json` | ✅ |

## Suíte completa

Ambiente do CI (`uv sync --all-packages --locked`, sem torch):

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
4592 passed, 4 skipped, 1 xfailed, 1 warning in 288.52s (0:04:48)
  skipped: ml/tests/test_dataset.py (sem torch), CA-16 manual da SPEC-008 (QC_REAL_MODEL_DIR),
           CA-25 e test_extra_parts_dataset_train_mode desta SPEC (sem torch)
  xfailed: test_bug_t01_rephotographed_test_item_keeps_test (T-01)
  o aviso não vem de ml/tests (a execução isolada de ml/tests não tem avisos)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
182 files already formatted
```

Com o extra `train`:
- rodei `uv sync --all-packages --extra train` e só `ml/tests` (autor + aceite): `170 passed, 1 xfailed`;
- depois acrescentei o `test_extra_parts_dataset_train_mode` e rodei de novo, com torch, os testes de `PartsDataset` e do CA-26: `3 passed`;
- por fim, voltei o `.venv` ao estado do CI (`uv sync --all-packages --locked`) e confirmei que `import torch` falha;
- conforme o dev-report, não rodei a suíte inteira com o extra, por causa das 3 falhas conhecidas de `edge/tests/test_publisher_real_api.py`, alheias a esta SPEC.

O autor relatou `4510 passed, 2 skipped`. A suíte tem agora +82 passed, +2 skipped e +1 xfailed:
- dos meus 84 casos, 81 passam, 2 são pulados e 1 é `xfail`;
- o caso a mais em relação ao autor vem do teste unitário do commit `8074d9c`, que é provavelmente posterior à contagem do dev-report.

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | média | §4.4, congelamento ("peças já presentes mantêm o split, inclusive as imagens novas de uma peça antiga") e R-11 (teste congelado a partir do `split_v1`). Nenhum CA | 1. Gerar o `split_v1` (CLI) de um dataset sintético. 2. Escolher uma peça de **teste** e apagar **todas** as imagens dela, registrando-as em `exclusions.csv` (`reason=person`, como na §8.1 do protocolo). 3. Refotografar a peça: adicionar 2 imagens novas do mesmo `item_id` ao manifest. 4. Rodar `python -m qc_ml.split` de novo. Teste: `test_bug_t01_rephotographed_test_item_keeps_test` (`xfail(strict=False)`; vira XPASS quando for corrigido) | As imagens novas herdam o split da peça no v1: `test` | As imagens novas vão para `train` (ou `val`), como se fosse uma peça nova. Uma peça física do teste congelado passa a ser usada no treino. Nenhuma imagem muda de split e o v2 não tem a peça em dois conjuntos, por isso nenhum CA falha. Mas o teste perde a peça sem nenhum aviso próprio (só os `excluded_previous_image`), e a peça do teste vira dado de treino. Causa: em `make_split` com `previous`, a peça é "antiga" só se alguma imagem **atual** dela estiver no split anterior (`old = {prev[p] for p in paths if p in prev}`). O `item_id` das imagens excluídas ou ausentes do split anterior não é considerado. Também acontece com uma peça de treino ou val com todas as imagens excluídas, mas aí ela só pode ir para treino ou val e não há vazamento para o teste |

## Testes exploratórios (além dos critérios)

Todos estão automatizados em `test_extra_*` e passam, salvo o T-01.

- **Formato dos arquivos do split:**
  - o CSV não tem `\r` e tem o cabeçalho `image_path,split`;
  - as linhas estão ordenadas por `image_path`;
  - o JSON tem `seed`, `ratios = [0.7, 0.15, 0.15]`, `parent = null`, `manifest_sha256` conferido e `warnings`;
  - nenhum dos três arquivos tem caminho absoluto.
- **Arredondamento e mínimos** (com um `DataFrame` no formato do manifest, sem arquivos):

  | Peças | train/val/test | Observação |
  |---|---|---|
  | 30 | 20/5/5 | 4,5 → 5; o `round` do Python daria 4 |
  | 10 | 6/2/2 | |
  | 4 | 2/1/1 | |
  | 3 | 1/1/1 | |
  | 2 | 2/0/0 | |

- **Grau dominante com empate:** a peça com `good` e `poor` cai no estrato `poor`, o mais severo. O aviso `small_stratum` cita `poor` e não cita `good`.
- **Determinismo:** `make_split` dá o mesmo resultado com o manifest embaralhado.
- **Versões:**
  - com `split_v9` e `split_v10` válidos, a CLI usa o v10 (ordem numérica, não lexicográfica) e imprime `split unchanged: split_v10`;
  - uma terceira geração tem `parent = "split_v2"` e mantém as linhas do v2.
- **Erros da CLI de split** (todos com saída 2 e nenhum arquivo gravado):
  - manifest inválido;
  - diretório do dataset inexistente;
  - split anterior editado à mão (hash divergente).
- **Imagens do split anterior que somem:**
  - imagem de treino tirada do manifest e do disco: o aviso `missing_previous_image` e o v2 sem ela;
  - `load_split` sem o `.sha256`: `SplitError`.
- **`rows_for`:**
  - as 3 partes somam 88 linhas, sem peça repetida entre elas, com as colunas do manifest;
  - um `split_df` com uma peça em dois splits dá `SplitIntegrityError`.
- **Valores inválidos:**
  - `object_type=bolt` dá `invalid_object_type`;
  - `T-001` em `screw` dá `item_prefix_mismatch` (ferramenta ainda não aceita);
  - `angle` igual a `1.5` ou `-1` dá `invalid_angle`;
  - `S-0001`, `s-001` dão `invalid_item_id`;
  - `Fair` dá `invalid_grade`;
  - `image_path` igual a `/etc/passwd`, `../outside.jpg`, `raw/../../outside.jpg` ou `raw//x.jpg` vira problema, sem ler fora do dataset.
- **Regras do manifest:**
  - `duplicate_image_path` aparece mesmo quando a linha repetida está excluída;
  - `override_missing_reason`;
  - com `apply_overrides=False`, a override não se aplica;
  - coluna `angle` ausente: só `missing_column`, e as outras validações abortam;
  - manifest com CRLF: aceito;
  - manifest só com cabeçalho: 0 linhas;
  - manifest em Latin-1 e diretório sem manifest: `validate` sai com 2.
- **Unicode e números de registro:**
  - `notes` com acento, aspas, emoji, `\n` entre aspas e `=SUM(A1:A2)` volta igual;
  - com uma célula de 3 linhas físicas antes, o problema do registro 7 continua citando `line = 7`.
- **Órfãos:**
  - um `.jpg` fora de `raw/` não é órfão;
  - um diretório sob `raw/` que é link simbólico para fora não é seguido;
  - um `.jpg.part` é ignorado;
  - o `image_path` do órfão é relativo, sem o caminho absoluto do dataset.
- **Exclusões:**
  - `reason` vazio dá `exclusion_invalid_reason`;
  - sem `exclusions.csv`, `load_exclusions` devolve `frozenset()`.
- **Saída do `validate`:**
  - `str(ManifestError)` tem um problema por linha;
  - com o manifest válido, sai com 0;
  - as linhas `count` vêm depois de todos os problemas, em ordem alfabética, por exemplo `count invalid_angle: 2`, `count invalid_grade: 1` e `count missing_file: 1`.
- **Relatório:** sem split, `split_sha256 = null`, e o resultado é serializável. Com um split desatualizado, a CLI `report` sai com 2, cita `split outdated` e não grava o arquivo.
- **Concordância:**
  - só pares de `other` (`n_pairs = 0`) dá saída 2, sem arquivo;
  - grau `rusty` no segundo arquivo dá saída 2, sem arquivo;
  - uma override no manifest não muda o primeiro rótulo (usa o grau original).
- **Augmentations:**
  - em 30 seeds sobre uma imagem clara uniforme, nenhum pixel abaixo de 60, ou seja, o preenchimento da rotação não é preto;
  - seeds diferentes dão saídas diferentes;
  - entradas `L`, `RGBA` e `P` saem `RGB` 256×256.
- **`PartsDataset` no modo treino** (com torch): o tensor é igual a `preprocess(train_transform(img, default_rng([seed, epoch, i])))[0]`, é estável na mesma época e muda com `set_epoch(1)`.
- **Dataset sintético:** com `include_other=False`, 1 peça e 1 imagem, dá 10 linhas, o layout `raw/<tipo>/<grau>/...`, JPEG 256×256 e um manifest válido.

Observações para o reviewer (não são bugs):
- **`.JPG` maiúsculo vira `orphan_image`.** A §4.1 diz que os arquivos que não terminam em `.jpg` são ignorados. A implementação compara a extensão sem diferenciar maiúsculas, o que é mais estrito que o texto. A decisão está registrada no dev-report e vai a favor da privacidade (SEC-10-02). Não automatizei esse caso.
- **Peças novas num split congelado.** Elas são alocadas só entre as novas do mesmo estrato, e com menos de 3 vão todas para o treino (`small_stratum`). Se a coleta acrescentar 1 ou 2 peças por vez em cada estrato, a validação não cresce. É a leitura do autor para "a mesma regra de arredondamento"; o CA-16 passa pelas duas leituras.
- **A CLI de concordância também valida o `exclusions.csv`.** Com um `excluded_file_present`, ela sai com 2. É mais estrito que a §4.3, e coerente com a §8.1 do protocolo.
- **Um erro meu, já corrigido.** A primeira versão do `test_extra_image_path_cannot_escape_the_dataset` tinha um auxiliar errado que tentou apagar o arquivo do `image_path` reescrito (`/etc/passwd`). A tentativa falhou com `PermissionError` e o arquivo não foi alterado (conferido). Corrigi o teste antes do commit: agora ele apaga só o arquivo original da linha, dentro de `tmp_path`.

## Testes de aceite de SPECs anteriores

Nenhum ajuste. Nenhum teste de aceite de SPEC anterior falhou.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
