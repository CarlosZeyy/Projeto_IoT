# SPEC-045 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-045](../../docs/specs/SPEC-045-treino-com-fotos-dos-colegas.md) |
| Rodada | r1 (só o código do §3.1; a operação do §4.7 é depois do merge) |
| Autor | ml-engineer |
| Branch | `spec/SPEC-045-treino-com-fotos-dos-colegas` |
| Commits | `cc72fb4` (código, testes e fixture), `ecf95e5` (`ml/README.md`) e o commit deste relatório |

## Resumo

- **Piso (§4.1):** `FLOOR_STRATA` passa a ser a lista fixa `screw` × 5 graus + `("other", "none")`. A forma de `floor_problems` e da CLI não muda.
- **Estrato (§4.2):** a função pública nova `split_stratum` substitui a `extension_strata` interna. Ela é usada no `split_v1` e na extensão do ADR-022. Com dados só de `screw`, `nut` e `other`, o `split_v1` sai byte a byte igual ao do commit base: conferi o SHA-256 em 4 datasets.
- **`--defer-types` no `split_v1` (§4.3):**
  - as imagens dos tipos adiados saem antes da alocação, e o `deferred_types` é gravado na ordem de `KNOWN_OBJECT_TYPES`;
  - um tipo listado sem imagem dá a linha `deferred type without images: <tipo>` e saída 2;
  - `--extend-test-types` continua sem efeito no `split_v1`, com um aviso no log;
  - o piso é conferido depois do adiamento.
- **Gerador:** `make_synthetic_dataset(…, include_nut=True)`. Com `False`, nenhuma peça `nut` é criada (`N-`, `N-501`… e `XN-`). A saída padrão é byte a byte a de antes.
- **Fixture:** `make_tiny_fixture.py --identified-tools-no-nut` gera `ml/tests/fixtures/tiny_model_no_nut/` (5 tipos, as 3 só identificadas sem grau). Ela foi gerada pelo script com torch 2.14.1 e tem 841 198 bytes.
- **README:** seção nova "Modelo oficial com as fotos dos colegas (ADR-025)", com o passo a passo do §4.7. A concordância aparece como **dispensada e declarada** (opção 6B, resposta do humano à pergunta 5 do ADR-025). Também corrigi os trechos do README que a SPEC tornou falsos: piso, `split_v1` e listas, estrato, gerador e fixtures.

Não houve treino nesta rodada: não existe `metrics.json` de modelo para reportar. Nenhum agente abriu foto: os testes usam só dados sintéticos em `tmp_path`, e nada leu `ml/data/` nem `~/partqc-entrada/`.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor (`ml/tests/`) |
|---|---|---|
| CA-01 | `ml/src/qc_ml/split.py` (`FLOOR_STRATA`) | `test_no_nut.py::test_floor_strata_is_the_fixed_list_without_nuts`, `::test_floor_problems_ignore_the_nut_strata`; `test_split_floor.py::test_floor_problems_sorted_and_counts_only_own_items` |
| CA-02 | `split.py` (`FLOOR_STRATA`, `floor_problems`, `main`); `ml/src/qc_ml/synthetic.py` | `test_no_nut.py::test_split_v1_without_nuts_at_the_floor` |
| CA-03 | `split.py` (`main`, `floor_problems`) | `test_no_nut.py::test_below_the_floor_cites_the_screw_stratum`; `test_split_floor.py::test_ca02_below_floor_refused_and_nothing_written`, `::test_ca03_flag_writes_the_warnings` |
| CA-04 | `split.py` (`FLOOR_STRATA`, `make_split`) | `test_no_nut.py::test_a_nut_is_split_but_is_not_part_of_the_floor` |
| CA-05 | `split.py` (`split_stratum`) | `test_no_nut.py::test_split_stratum_cases`, `::test_split_stratum_keeps_the_strata_of_screw_and_other` |
| CA-06 | `split.py` (`make_split` com `split_stratum` no `split_v1`) | `test_no_nut.py::test_tools_in_split_v1_by_whole_type`, `::test_graded_hand_tool_keeps_the_grade_strata` |
| CA-07 | `split.py` (`split_stratum` devolve o estrato recebido para `screw`/`nut`/`other`; o `rng` não muda) | `test_no_nut.py::test_split_v1_unchanged_without_hand_tools` (4 casos, hashes do commit base) |
| CA-08 | `split.py` (`type_decision_problems`, `make_split`, `main`, `DEFERRED_WITHOUT_IMAGES`) | `test_no_nut.py::test_defer_types_in_split_v1_then_extend`, `::test_deferred_type_without_images_in_split_v1`, `::test_defer_types_order_of_known_object_types`, `::test_extend_test_types_has_no_effect_in_split_v1`, `::test_type_decision_problems_for_split_v1`, `::test_make_split_defers_in_split_v1`, `::test_deferring_screw_or_other_is_below_the_floor`; `test_tools_split.py::test_split_v1_defers_and_ignores_the_extension`, `::test_make_split_checks_the_extension` |
| CA-09 | nenhum código novo (`derive_model_labels`, como diz o §1) | `test_no_nut.py::test_derive_model_labels_without_nuts` |
| CA-10 | `ml/scripts/make_tiny_fixture.py`; `ml/tests/fixtures/tiny_model_no_nut/` (sem mudança em `train`, `thresholds`, `evaluate`, `export` e `report`, §4.4) | `test_no_nut.py::test_thresholds_and_evaluate_without_nuts`, `::test_fixture_no_nut_files_labels_and_parity`, `::test_make_tiny_fixture_identified_tools_no_nut` (torch, *slow*) |
| CA-11 | `synthetic.py` (`include_nut`) | `test_no_nut.py::test_include_nut_true_is_the_default_byte_for_byte`, `::test_include_nut_false_keeps_the_other_ids_and_names` |
| CA-12 | nenhum código (`.gitignore` já cobre `ml/data/`) | conferido à mão: `git ls-files ml/data` vazio; `git check-ignore` lista os 3 caminhos do CA |
| CA-13 a CA-16 | operação e manuais depois do merge; passo a passo no `ml/README.md` | — |

Extensão (§4.2, "usada [...] na extensão"): `test_no_nut.py::test_extension_uses_split_stratum`. Os testes de extensão que já existiam (`test_tools_split.py`, `test_power_tools.py`, `test_identified_tools.py` e `test_maintenance_040.py`) passam sem mudança.

## Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
uv run pytest ml edge -q
uv run pytest ml/tests/test_no_nut.py ml/tests/test_split_floor.py ml/tests/test_tools_split.py -q
# fixture (com torch):
uv sync --all-packages --extra train
uv run --package qc-ml python ml/scripts/make_tiny_fixture.py --identified-tools-no-nut
```

## Resultado dos testes

- `uv run ruff check .`: limpo. `uv run ruff format --check .`: 333 arquivos já formatados.
- `uv run pytest ml edge -q`, no ambiente do CI (sem torch): **8 failed, 5157 passed, 63 skipped** em 602 s. As 8 falhas são todas de aceites antigos que a SPEC muda de propósito (tabela abaixo). Nenhum teste de `edge/` falhou.
- Os testes do autor que mudam, mais o arquivo novo: 58 passed (rodados com torch instalado, inclusive `test_make_tiny_fixture_identified_tools_no_nut`).
- `ml/tests` sem os aceites, antes de ajustar os testes do autor: só os 6 testes do autor listados em "Testes do autor alterados" falharam. Os outros 725 passaram.

### Aceites antigos que a SPEC muda de propósito (para o tester, §3.1)

| Teste | Motivo |
|---|---|
| `ml/tests/acceptance/test_spec_016.py::test_extra_split_v1_ignores_the_lists` | Afirma que `--defer-types` é ignorado no `split_v1`. Agora o tipo adiado sai do `split_v1` (§4.3). |
| `ml/tests/acceptance/test_spec_041.py::test_ca02_missing_stratum_is_refused_and_nothing_is_written` | Tira uma peça `nut/fair` e espera a recusa. `nut/fair` saiu do piso; passa a ser `screw/fair` (§3.1). |
| `ml/tests/acceptance/test_spec_041.py::test_ca03_allow_below_floor_records_the_warning` | Espera `below_floor` de `nut/fair`; passa a ser `screw/fair` (§3.1). |
| `ml/tests/acceptance/test_spec_041.py::test_extra_many_strata_are_listed_in_lexicographic_order` | Espera `["nut/fair", "nut/good", "other/none", "screw/unusable"]`; agora sai `["other/none", "screw/unusable"]` (conteúdo do `FLOOR_STRATA`). |
| `ml/tests/acceptance/test_spec_041.py::test_extra_every_stratum_is_listed_when_only_externals_exist` | Compara com o `FLOOR_STRATA` local de 11 estratos (linha 88); passa aos 6 do CA-01. |
| `ml/tests/acceptance/test_spec_041.py::test_extra_floor_problems_do_not_count_externals` | Idem (`floor_problems == FLOOR_STRATA` de 11). |
| `ml/tests/acceptance/test_spec_041.py::test_extra_excluded_item_counts_as_missing` | Exclui as peças `nut/fair` e espera a recusa por `nut/fair`. Pela mesma intenção, passa a ser `screw/fair`. |
| `ml/tests/acceptance/test_spec_041.py::test_extra_dominant_grade_decides_the_stratum` | Muda o grau dominante das peças `nut/fair` e espera a recusa por `nut/fair`. Pela mesma intenção, passa a ser `screw/fair`. |

Observação para o tester e o orquestrador (não bloqueia): o §3.1 cita nominalmente o CA-02 e o CA-03 da SPEC-041 e "uma asserção sobre o tamanho ou o conteúdo de `FLOOR_STRATA`". Os dois últimos `extra` da tabela usam `nut/fair` como os CAs 02 e 03, e a troca é a mesma, `nut/fair` → `screw/fair`, com a intenção mantida. O comportamento do código está fixado sem ambiguidade pelo §4.1.

### Testes do autor alterados (eram do comportamento antigo)

- `test_split_floor.py`:
  - `test_floor_problems_sorted_and_counts_only_own_items`: espera 6 problemas, com `other/none` primeiro e nenhum `nut/*`;
  - `test_floor_problems_uses_the_dominant_grade`: agora com `screw/perfect`, empate perfect/good por foto, que vai para o mais severo;
  - `test_ca02_below_floor_refused_and_nothing_written` e `test_ca03_flag_writes_the_warnings`: `nut/fair` → `screw/fair`.
- `test_tools_split.py`:
  - `test_split_v1_ignores_the_lists` vira `test_split_v1_defers_and_ignores_the_extension`. Adiar todas as manuais dá o mesmo `split_v1` do dataset sem ferramentas, e `--extend-test-types` não tem efeito;
  - `test_make_split_checks_the_extension`: o último bloco confere o adiamento no `split_v1`.

## Decisões tomadas dentro do escopo da SPEC

1. **Hashes do CA-07 no teste do autor.** Calculei os hashes com o código do commit base (`c6134f1`, que tem o mesmo `qc_ml` do merge-base `555c4b6`) antes de qualquer edição. São 4 datasets: os 2 padrões, um com elétricas e só identificadas, e um com externas e de conhecido (`--allow-below-floor`, e `--max-external-fraction 1` no caso com externas). O tester refaz o cálculo dele, como manda o CA-07.
2. **`split_stratum` com uma ferramenta manual fora de `coverage`:** conta como não graduada (`(tipo, "none")`). O `tool_grade_coverage` sempre traz as 5 manuais, então isso não muda nada na prática; só evita um `KeyError`.
3. **`make_split` sem `previous`:** aplica `defer_types` e ignora `extend_test_types`. Um valor fora de `KNOWN_OBJECT_TYPES` em qualquer das duas listas agora levanta `SplitError` também no `split_v1`, como a CLI já recusava. Um tipo nas duas listas no `split_v1` é adiado (o `extend` não tem efeito), sem erro.
4. **Aviso do `--extend-test-types` no `split_v1`.** O texto passou a ser `--extend-test-types is not used for split_v1: every type present and not deferred is split normally`, e o aviso só sai quando a flag é usada. O texto antigo dizia que `--defer-types` também era ignorado, o que deixou de ser verdade. Nenhum aceite confere esse texto.
5. **`deferred type without images`:** uma linha por tipo, na ordem em que aparece em `--defer-types`, e só depois da checagem de valor desconhecido (que tem precedência, como antes).
6. **Gerador com `include_nut=False`:** as peças de porca continuam no plano interno, mas não são gravadas. Os carimbos de tempo avançam sobre elas, então as outras peças ficam com o mesmo `item_id` e o mesmo nome de arquivo da saída padrão. Os pixels dessas peças mudam, porque o gerador aleatório é um só. O CA-11 pede só os `item_id`.
7. **Novas peças a partir do `split_v2`:** continuam no estrato do grau dominante (`item_strata`), porque a SPEC manda usar o `split_stratum` só no `split_v1` e na extensão.
8. **Plano corrigido (Anexo A):** nenhum código no repositório. A SPEC (§3.2 e §4.7, passo 2) e o ADR-025 (decisão 4) mandam gerá-lo com um script fora do repositório, na operação.
9. **Concordância:** nada no código depende dela. O README registra a dispensa (opção 6B) e o que o PR do split, o CHANGELOG e os slides devem declarar.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhuma foto aberta; nenhum teste lê `ml/data/`, a pasta de entrada ou o backup
- [x] Sem push
