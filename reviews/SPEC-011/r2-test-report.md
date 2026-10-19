# SPEC-011 — r2 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-011](../../docs/specs/SPEC-011-ml-dados-split.md) |
| Rodada | r2 |
| Tester | tester |
| Commit testado | `04eebf3` (correção em `f66c995`) |
| **Veredicto** | **PASS** |

O veredicto é PASS por quatro motivos:
- os 32 CAs continuam com teste de aceite e passam;
- a suíte inteira passa no ambiente do CI;
- o ruff está limpo;
- a correção do RV-01/T-01 funciona no caso pedido.

Como o RV-01 pede, o antigo `test_bug_t01_*` virou um teste normal, sem `xfail`: `test_extra_t01_rephotographed_test_item_keeps_test`.

Encontrei, porém, um bug novo, o **T-02 (alta)**. É uma variante do T-01 que a correção não cobre:
- a peça de teste é excluída e o split é gerado de novo (`split_v2`, como manda o passo 5 da §8.1 do protocolo);
- só depois a peça é refotografada;
- no `split_v3`, as fotos novas vão para o treino.

O T-02 não viola nenhum CA, então não muda o veredicto pelo critério do tester. Mas o efeito é o mesmo que o reviewer classificou como alto no RV-01. Recomendo tratá-lo antes do merge (ver "Bugs" e "SPEC_ISSUE").

Arquivo de aceite: `ml/tests/acceptance/test_spec_011.py`, com:
- 32 `test_caNN_*`;
- 49 `test_extra_*`;
- 1 `test_bug_t02_*`, com `xfail(strict=False)`.

São **95 casos**:
- **sem torch (CI):** 92 passam, 2 são pulados (o CA-25 e o `test_extra_parts_dataset_train_mode`, os dois com `importorskip("torch")`) e 1 é `xfail` (T-02);
- **com `--runxfail`:** o T-02 falha na asserção (`['train', 'train'] != ['test', 'test']`), e não por erro do teste.

## Mudanças no arquivo de aceite nesta rodada

| Teste | Mudança | Motivo |
|---|---|---|
| `test_bug_t01_rephotographed_test_item_keeps_test` | Renomeado para `test_extra_t01_rephotographed_test_item_keeps_test`, sem o `xfail`. As asserções não mudaram. A exclusão agora passa pelo auxiliar `exclude_item`, que só apaga dentro do dataset em `tmp_path` | RV-01 de `r1-review-report.md`: uma regressão tem de voltar a falhar |
| 9 testes novos `test_extra_*` e 1 `test_bug_t02_*` | Exploração da correção (abaixo) | Pedido do orquestrador |
| Auxiliares `safe_unlink`, `exclude_item`, `first_item_in` e `other_grade` | `safe_unlink` resolve o caminho e confere `is_relative_to(dataset)` antes de apagar. Todo teste novo apaga só por ele | Incidente da r1 (`/etc/passwd`), registrado pelo reviewer |

Os 32 `test_caNN_*` não mudaram. Nenhum teste de aceite de SPEC anterior foi tocado.

## Cobertura dos critérios de aceite

Os testes dos CAs são os mesmos da r1, sem alteração. Todos passam no commit `04eebf3`.

| Critério | Teste de aceite (`ml/tests/acceptance/test_spec_011.py::`) | Resultado |
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
| CA-25 | `test_ca25_parts_dataset_eval_items` | ✅ com torch na r1; pulado no CI (`importorskip`). A r2 não tocou `dataset.py`, `augment.py` nem o pré-processamento, então não reinstalei o extra |
| CA-26 | `test_ca26_modules_import_without_torch` | ✅ |
| CA-27 | `test_ca27_no_images_tracked_under_ml` | ✅ |
| CA-28 | `test_ca28_too_many_jpeg_scans` | ✅ |
| CA-29 | `test_ca29_manifest_read_as_csv_not_by_lines` | ✅ |
| CA-30 | `test_ca30_orphan_image` | ✅ |
| CA-31 | `test_ca31_exclusions` | ✅ |
| CA-32 | `test_ca32_excluded_test_image_leaves_the_split` | ✅ |

## Suíte completa

Ambiente do CI (`import torch` falha):

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
4608 passed, 4 skipped, 1 xfailed, 1 warning in 281.48s (0:04:41)
  skipped: ml/tests/test_dataset.py (sem torch), CA-16 manual da SPEC-008, CA-25 e
           test_extra_parts_dataset_train_mode desta SPEC (sem torch)
  xfailed: test_bug_t02_rephoto_after_an_intermediate_split_keeps_test (T-02)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
182 files already formatted
```

O autor relatou `4597 passed, 4 skipped, 1 xpassed`. A diferença é toda do arquivo de aceite:
- +1, do T-01, que passou de XPASS a teste normal;
- +10, dos 9 testes novos (um deles parametrizado em 3);
- o T-02 é o `xfailed`.

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-02 | alta (mesmo efeito do RV-01) | §4.4 (congelamento: "peças já presentes mantêm o split"; "peças novas vão só para treino/val"), R-11 e ADR-014 (teste congelado a partir do `split_v1`). Nenhum CA | 1. Gerar o `split_v1` (CLI). 2. Apagar todas as fotos de uma peça de **teste** e registrá-las em `exclusions.csv` (§8.1, passos 1 e 2). 3. Rodar `python -m qc_ml.split`, como manda o passo 5 da §8.1: grava o `split_v2`, sem a peça, com os avisos `excluded_previous_image`. 4. Refotografar a peça, com o mesmo `item_id`, como manda o passo 1 da §8 do protocolo. 5. Rodar o split de novo: grava o `split_v3`. Teste: `test_bug_t02_rephoto_after_an_intermediate_split_keeps_test` (`xfail(strict=False)`, vira XPASS quando for corrigido) | As fotos novas vão para `test`: a peça estava no teste congelado do v1 | As fotos novas vão para `train`. Reproduzido também por script fora da suíte (`S-001`, teste no v1 → `['train', 'train']` no v3). A peça física sai do teste congelado e vira dado de treino |

**Causa do T-02.** A correção da r2 descobre o `item_id` das imagens do split **anterior**, ou seja, o de maior N:
- pelo `df`;
- por `df.attrs["excluded_items"]`;
- pelo nome do arquivo.

No `split_v2`, as imagens antigas da peça já não existem: saíram com o `excluded_previous_image`. Por isso o v2 não tem nenhuma imagem da peça, e ela volta a ser "peça nova" no v3.

A informação de que a peça estava no teste continua no repositório, em dois lugares:
- no `split_v1.csv`;
- nos avisos `excluded_previous_image` do `split_v2.json`, que têm `image_path` e `split`, com o `item_id` vindo de `excluded_items`.

Mas `make_split` só recebe o último split.

**A ordem do T-02 é a do protocolo.** O passo 5 da §8.1 diz que "o próximo `python -m qc_ml.split` a tira do teste". Isso convida a rodar o split logo depois da exclusão, antes de refotografar. A ordem do T-01 (refotografar antes de rodar o split) funciona. A ordem inversa, igualmente natural, não funciona.

## Testes exploratórios (além dos critérios)

Todos automatizados e passando, salvo o T-02.

**Exploração da correção do RV-01:**
- **Peça excluída inteira e refotografada num grau mais severo** (`test_extra_rephotographed_item_keeps_its_split[test|val|train]`), com porca, 3 fotos novas e um estágio de corrosão seguinte:
  - as fotos novas herdam `test`, `val` e `train`, respectivamente;
  - todas as outras linhas do v1 ficam iguais;
  - os avisos `excluded_previous_image` listam exatamente as fotos antigas, com o split delas;
  - nenhuma peça fica em dois conjuntos no v2.
- **Peça de validação removida do manifest e do disco sem exclusão, depois refotografada** (`test_extra_removed_without_exclusion_val_item_keeps_val`):
  - as fotos novas herdam `val` pelo nome de arquivo da SPEC-010;
  - há um `missing_previous_image` por foto antiga.
- **Peça de teste removida sem exclusão e refotografada** (`test_extra_removed_without_exclusion_test_item_still_errors`):
  - continua a saída 2, citando a imagem, sem gravar nada (CA-18);
  - a foto nova não "legaliza" a remoção.
- **`make_split` sem `df.attrs`** (`test_extra_make_split_without_attrs_uses_file_names`): com `df.attrs = {}`, a peça de teste refotografada continua em `test`, pelo nome de arquivo.
- **Conflito** (`test_extra_old_images_in_two_splits_is_an_integrity_error`): num split anterior montado à mão, as imagens antigas da peça estão em `val` e `train`. O resultado é `SplitIntegrityError` nos dois casos:
  - a imagem em conflito está excluída (fonte `excluded_items`);
  - a imagem foi removida do manifest sem exclusão (fonte: nome do arquivo).
- **Conflito pela CLI** (`test_extra_split_cli_conflict_in_previous_exits_2`): o `split_v1` foi editado e teve o hash refeito à mão, e a peça foi refotografada. A CLI sai com 2, cita a peça e não grava nada.
- **Nome fora do padrão da SPEC-010** (`test_extra_previous_image_with_foreign_name_is_ignored`): uma imagem do split anterior sem linha e com nome fora do padrão dá só `missing_previous_image`, sem erro.
- **RV-03** (`test_extra_small_stratum_of_new_items_has_scope`):
  - 1 peça nova num split congelado gera `small_stratum` com `"scope": "new_items"`;
  - no `split_v1` (regra do CA-14), o aviso não tem esse escopo.

Os testes exploratórios da r1 continuam todos passando. Formato dos arquivos, arredondamento, empate de grau, versões em ordem numérica, travessia de caminho, órfãos, Unicode, concordância e augmentations estão descritos no `r1-test-report.md`.

Observações (não são bugs):
- **Item de linha excluída sem validação.** O `item_id` de uma linha excluída entra em `excluded_items` sem passar pelas validações de linha, porque as linhas excluídas as pulam (§4.1). Um `item_id` errado numa linha excluída daria uma herança errada ou um `SplitIntegrityError` falso. É um risco baixo: a linha foi escrita pela borda, que valida o `item_id` (SPEC-010). Não automatizei esse caso.
- **Herança com grau novo.** Uma peça refotografada com grau diferente do antigo herda o split pelo `item_id`, mesmo mudando de estrato. É o comportamento certo pela R-11, e está coberto pelo teste parametrizado acima.

## SPEC_ISSUE (se houver)

Nenhum registrado pelo tester: nenhum CA ficou impossível de testar. Há, porém, um ponto para o reviewer e o orquestrador.

A §4.4 define `previous` como "o split de maior N" e diz que "peças já presentes mantêm o split". Pela letra, no T-02 a peça não está presente no `split_v2`. Pela intenção (teste congelado a partir do `split_v1`, R-11 por `item_id`, ADR-014), ela deveria continuar no teste.

Se a correção couber na SPEC, há dois caminhos possíveis, sem mudar a assinatura de `make_split`:
- a CLI lê o histórico dos `split_v*.csv`, ou os `excluded_previous_image` dos `split_v*.json`, para saber o split antigo de cada peça;
- ou alguma forma equivalente.

Se o autor concluir que isso exige mudar a interface ou o texto da §4.4, cabe `SPEC_ISSUE` ao architect.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
- [x] Todo arquivo apagado pelos testes novos passa por `safe_unlink`, que confere que o caminho está dentro do dataset em `tmp_path`.
