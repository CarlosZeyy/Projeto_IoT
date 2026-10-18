# SPEC-011 — r3 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-011](../../docs/specs/SPEC-011-ml-dados-split.md) (corrigida em `60ce217`, reaprovada) |
| Rodada | r3 (última, R-10) |
| Tester | tester |
| Commit testado | `d709b21` (implementação em `5e30539`) |
| **Veredicto** | **PASS** |

O veredicto é PASS:
- os 35 CAs têm teste de aceite e passam (o CA-25 com torch, na r1; no CI ele é pulado, como manda a §6);
- a suíte inteira passa no ambiente do CI, sem nenhum `xfail` nem falha;
- o ruff está limpo;
- não encontrei bug novo.

O T-02 da r2 virou um teste normal e passa. O histórico do split (§4.4) se comportou como o texto manda em todos os casos explorados: lacuna, hash divergente ou `.sha256` ausente numa versão que não é a última, conflito (inclusive de maioria) e o filtro do RV-06.

Arquivo de aceite: `ml/tests/acceptance/test_spec_011.py`, com:
- 37 funções `test_caNN_*`: os 32 da r1, mais `test_ca33_*`, três `test_ca34_*` (um por caso a, b e c) e `test_ca35_*`;
- 61 `test_extra_*`;
- nenhum `test_bug_*`.

São **114 casos**. Sem torch (CI), 112 passam e 2 são pulados por `importorskip("torch")`: o CA-25 e o `test_extra_parts_dataset_train_mode`.

## Mudanças no arquivo de aceite nesta rodada

| Arquivo | Teste | Antes → depois | Motivo |
|---|---|---|---|
| `ml/tests/acceptance/test_spec_011.py` | `test_extra_split_versions_use_numeric_order` | **Antes:** criava `split_v1`, `split_v9` e `split_v10` (lacuna de 2 a 8) e esperava saída 0 com `split unchanged: split_v10`. **Depois:** cria as versões 1 a 10 completas, cada uma com `.sha256` válido, e espera a mesma saída. A intenção, ordem numérica e não lexicográfica, continua verificada: com ordem lexicográfica, a última versão seria a v9 | §4.4 nova, passo 3 da CLI: as versões têm de ser exatamente `1…M`, e uma lacuna sai com 2 (`split history incomplete`). A lacuna agora é coberta pelo CA-34 (a) e pelo `test_extra_history_gap_in_the_middle` |
| idem | `test_bug_t02_rephoto_after_an_intermediate_split_keeps_test` | Renomeado para `test_extra_t02_rephoto_after_an_intermediate_split_keeps_test`, sem o `xfail(strict=False)`. As asserções não mudaram | §6 nova: o teste vira teste normal. O CA-33 tem um teste próprio, que segue o texto do CA (dataset do CA-12, peça de teste e de validação) |
| idem | 5 testes de CA novos e 10 `test_extra_*` novos | Inclusão | CA-33 a CA-35 e a exploração pedida pelo orquestrador |

Nenhum `test_caNN_*` existente mudou. Nenhum teste de aceite de outra SPEC foi tocado. Todo arquivo apagado pelos testes novos passa por `safe_unlink`, que confere que o caminho resolvido está dentro do diretório do teste em `tmp_path`.

## Cobertura dos critérios de aceite

Prefixo: `ml/tests/acceptance/test_spec_011.py::`. Os testes dos CA-01 a CA-32 são os da r1, sem alteração (descrição em `r1-test-report.md`).

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_load_synthetic_manifest` | ✅ |
| CA-02 | `test_ca02_missing_file` | ✅ |
| CA-03 | `test_ca03_unreadable_image_only_with_verify` | ✅ |
| CA-04 | `test_ca04_item_type_conflict` | ✅ |
| CA-05 | `test_ca05_grade_on_other_and_missing_grade_lines` | ✅ |
| CA-06 | `test_ca06_invalid_values` | ✅ |
| CA-07 | `test_ca07_all_problems_in_one_error_and_cli` | ✅ |
| CA-08 | `test_ca08_override_changes_the_grade` | ✅ |
| CA-09 | `test_ca09_last_override_wins_and_unknown_image` | ✅ |
| CA-10 | `test_ca10_override_fills_missing_grade` | ✅ |
| CA-11 | `test_ca11_data_report` | ✅ |
| CA-12 | `test_ca12_items_never_cross_splits` | ✅ |
| CA-13 | `test_ca13_each_stratum_14_3_3` | ✅ |
| CA-14 | `test_ca14_small_stratum_goes_to_train` | ✅ |
| CA-15 | `test_ca15_cli_reproducible_and_seed_matters` | ✅ |
| CA-16 | `test_ca16_frozen_test_with_new_items_and_images` | ✅ |
| CA-17 | `test_ca17_unchanged_writes_nothing` | ✅ |
| CA-18 | `test_ca18_missing_test_image_is_an_error` | ✅ |
| CA-19 | `test_ca19_load_split_detects_hand_edits` | ✅ |
| CA-20 | `test_ca20_rows_for_outdated_split` | ✅ |
| CA-21 | `test_ca21_agreement_known_values` | ✅ |
| CA-22 | `test_ca22_agreement_inverted` | ✅ |
| CA-23 | `test_ca23_agreement_unknown_image` | ✅ |
| CA-24 | `test_ca24_train_transform_deterministic` | ✅ |
| CA-25 | `test_ca25_parts_dataset_eval_items` | ✅ com torch (r1). Pulado no CI. A r2 e a r3 não tocaram `dataset.py`, `augment.py` nem o pré-processamento |
| CA-26 | `test_ca26_modules_import_without_torch` | ✅ |
| CA-27 | `test_ca27_no_images_tracked_under_ml` | ✅ |
| CA-28 | `test_ca28_too_many_jpeg_scans` | ✅ |
| CA-29 | `test_ca29_manifest_read_as_csv_not_by_lines` | ✅ |
| CA-30 | `test_ca30_orphan_image` | ✅ |
| CA-31 | `test_ca31_exclusions` | ✅ |
| CA-32 | `test_ca32_excluded_test_image_leaves_the_split` | ✅ |
| CA-33 | `test_ca33_rephoto_after_an_intermediate_split`. Dataset do CA-12. `P_t` (parafuso em teste) e `P_v` (porca em validação) têm todas as imagens apagadas e registradas em `exclusions.csv`. A CLI grava o `split_v2`, sem nenhuma imagem das duas peças. Depois entram 2 imagens novas de cada uma (mesmo `item_id`, tipo e grau, nomes novos da SPEC-010, JPEG válido, linha nova no manifest) e a CLI roda de novo. Resultado: as duas execuções saem com 0; o `split_v3.csv` existe; as fotos novas de `P_t` estão em `test` e as de `P_v` em `val`; todas as linhas do v2 mantêm o split no v3; o conjunto de `item_id` em teste do v3 é igual ao do v1 | ✅ |
| CA-34 | Fixture `history_state`: o `split_v1`, depois o `split_v2` com 5 peças novas `screw/fair`, depois mais 1 peça nova com 2 imagens. Em cada caso, `--splits-dir` é comparado (nomes e bytes) antes e depois, e nenhum `split_v3.*` existe:<br>(a) `test_ca34_history_gap`: `split_v1.csv` apagado, com o `.sha256` e o `.json` mantidos → saída 2, `split history incomplete` e `split_v1.csv`;<br>(b) `test_ca34_hash_mismatch_in_an_old_version`: 1 linha `test` → `train` no v1, sem refazer o hash → saída 2 com `split_v1.csv`;<br>(c) `test_ca34_conflict_in_the_history`: todas as linhas de uma peça de teste trocadas para `val` no v1, com o hash refeito (o teste confere que o v2 continua com a peça em `test`) → saída 2 com o `item_id`, `split_v1.csv` e `split_v2.csv`; e `item_history([load_split(v1), load_split(v2)], load_manifest(root))` levanta `SplitIntegrityError` com o `item_id` | ✅ |
| CA-35 | `test_ca35_make_split_with_history`. `P` e `Q` em teste no `v1`, e `v2` sem as imagens de `P` (excluídas). O `df3` tem 2 linhas novas de `P`. Resultados:<br>`history={P: "test"}`: as 2 linhas novas vão para `test`, e todas as linhas do `v2` mantêm o split;<br>`{P: "test", Q: "train"}`: `SplitIntegrityError` com `Q`;<br>`{P: "holdout"}`: `SplitError`;<br>sem `previous`: `SplitError` | ✅ |

## Suíte completa

Ambiente do CI (`import torch` falha):

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
4638 passed, 4 skipped, 1 warning in 291.33s (0:04:51)
  skipped: ml/tests/test_dataset.py (sem torch), CA-16 manual da SPEC-008, CA-25 e
           test_extra_parts_dataset_train_mode desta SPEC (sem torch)
  o aviso não vem de ml/tests

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
182 files already formatted
```

O autor relatou `4617 passed, 4 skipped, 1 xpassed, 1 failed`. A diferença de +21 vem toda do arquivo de aceite:

| Origem | Casos |
|---|---|
| T-02 (antes XPASS, agora teste normal) | +1 |
| Teste de ordem numérica (antes falhava, agora ajustado) | +1 |
| Testes dos CAs novos: CA-33, CA-34 (3) e CA-35 | +5 |
| Testes exploratórios novos (10 funções, uma parametrizada em 4) | +14 |

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Todos estão automatizados em `test_extra_*` e passam.

- **Lacuna no meio** (`test_extra_history_gap_in_the_middle`): com o v1 e o v3 presentes e o `split_v2.csv` ausente, a saída é 2, com `split history incomplete` e `split_v2.csv`, e nada é gravado.
- **`.sha256` ausente numa versão antiga** (`test_extra_history_old_version_without_sha256`): com o v1 sem `.sha256` e o v2 válido, a saída é 2, com `split_v1` na mensagem, e nada é gravado.
- **Conflito de maioria nunca resolvido** (`test_extra_history_conflict_is_never_resolved`):
  - cenário: a peça está em `test` no v1 e no v2 e em `val` no v3, com os hashes válidos;
  - a saída é 2, citando a peça e o `split_v3.csv`, e nada é gravado;
  - ou seja, o pipeline não escolhe a maioria nem a versão mais nova.
- **Conflito dentro de um só `DataFrame` sem `attrs`** (`test_extra_item_history_conflict_inside_one_frame_without_attrs`):
  - `item_history([frame], df)` levanta `SplitIntegrityError` com o `item_id`;
  - a mensagem traz a posição `#…` no lugar do nome do arquivo;
  - o autor usa índice a partir de 0 (decisão registrada no r3-dev-report); o teste só exige o `#`.
- **Valores do `item_history`** (`test_extra_item_history_values_and_unresolvable_images`):
  - com duas versões iguais, devolve exatamente `item_id → split` de todas as peças;
  - uma imagem sem linha e com nome fora do padrão da SPEC-010 é ignorada;
  - uma lista vazia dá `{}`.
- **Entrada do `history` sem imagens em `df`** (`test_extra_history_entry_without_images_is_ignored`): `{"S-999": "test"}` é ignorada, e o resultado é igual ao v1. Um `history={}` sem `previous` não dá erro.
- **RV-06, filtro da fonte 2** (`test_extra_rv06_invalid_excluded_item_id_falls_back_to_the_file_name[bogus|S-1||s-001]`):
  - com `df.attrs["excluded_items"]` inválido para as imagens antigas de uma peça de teste, a fonte 2 é ignorada;
  - a peça é achada pelo nome do arquivo, e a foto nova vai para `test`.
- **RV-06 pela CLI** (`test_extra_rv06_through_the_cli`):
  - cenário: as linhas excluídas de uma peça de teste têm o `item_id` reescrito para `X-1` no manifest; o `load_manifest` aceita, porque linhas excluídas não são validadas;
  - a sequência é exclusão → v2 → refotografar → v3, e a foto nova vai para `test`.
- **Precedência da fonte 2 sobre a 3** (`test_extra_valid_excluded_item_id_wins_over_the_file_name`):
  - cenário: um `excluded_items` com um `item_id` **válido** de outra peça (`S-098`);
  - esse valor tem precedência sobre o nome do arquivo, como a §4.4 manda;
  - consequência: a peça passa por nova e vai para `train`/`val`;
  - é o comportamento especificado, e o teste documenta a precedência. O risco de um `item_id` válido e errado numa linha excluída foi aceito no RV-06, porque a borda valida o `item_id` (SPEC-010).
- **Arquivos soltos e zero à esquerda** (`test_extra_stray_files_and_leading_zero_are_ignored`):
  - cenário: `split_v2.sha256` e `split_v2.json` sem o `.csv`, `split_v01.csv` e `split_v0.csv`;
  - nenhum deles conta como versão; a CLI sai com 0 e `split unchanged: split_v1`.
- **Sem mudança, com histórico mais longo** (`test_extra_unchanged_with_a_longer_history`): com o v1 e o v2, uma nova execução dá `split unchanged: split_v2`, e o diretório fica igual byte a byte.
- **Testes exploratórios da r2** (`test_extra_rephotographed_item_keeps_its_split[test|val|train]`, remoção sem exclusão, fonte do nome do arquivo, conflitos e `scope: "new_items"`): continuam passando com o histórico.
- **Testes exploratórios da r1:** continuam passando. A descrição está em `r1-test-report.md`.

Observação (não é bug): no CA-34 (b), a mensagem de erro traz `split error: split_v1.csv: …`. No (c), traz o `item_id` e os dois arquivos, com os splits em ordem alfabética.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
- [x] Todo arquivo apagado pelos testes novos passa por `safe_unlink`, que confere que o caminho está dentro de `tmp_path`.
