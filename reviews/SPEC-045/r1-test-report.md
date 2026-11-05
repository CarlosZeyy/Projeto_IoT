# SPEC-045 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-045](../../docs/specs/SPEC-045-treino-com-fotos-dos-colegas.md) |
| Rodada | r1 (código do §3.1; a operação do §4.7 é depois do merge) |
| Tester | tester |
| Commit testado | `0f928c1` (código em `cc72fb4` e `ecf95e5`), mais o commit deste relatório com os testes de aceite |
| **Veredicto** | **PASS** |

Os testes foram escritos a partir dos CAs (caixa-preta), antes de ler a implementação. Só depois li o diff de `ml/src/qc_ml/split.py` e `synthetic.py` para procurar casos de borda. Todos os dados são sintéticos, em `tmp_path`. Nenhum teste nem comando meu leu `ml/data/`, `~/partqc-entrada/` ou o backup, e nenhuma foto foi aberta (§4.5, R-14).

## Cobertura dos critérios de aceite

Arquivo: `ml/tests/acceptance/test_spec_045.py`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_floor_is_the_fixed_list_without_nuts` | ✅ |
| CA-02 | `test_ca02_split_v1_without_nuts` | ✅ |
| CA-03 | `test_ca03_below_the_floor_is_refused`, `test_ca03_allow_below_floor_records_the_warning` | ✅ |
| CA-04 | `test_ca04_nut_is_split_but_not_part_of_the_floor` | ✅ |
| CA-05 | `test_ca05_split_stratum_cases` | ✅ |
| CA-06 | `test_ca06_tools_in_split_v1_by_whole_type` | ✅ |
| CA-07 | `test_ca07_same_split_without_tools` | ✅ |
| CA-08 | `test_ca08_defer_types_in_split_v1`, `test_ca08_deferred_type_without_images` | ✅ |
| CA-09 | `test_ca09_type_without_images_is_out_of_the_model` | ✅ |
| CA-10 | `test_ca10_thresholds_and_evaluate_without_nut` | ✅ |
| CA-11 | `test_ca11_generator_include_nut` | ✅ |
| CA-12 | `test_ca12_dataset_is_out_of_git` | ✅ |
| CA-13 | operação depois do merge (ml-engineer executa, tester confere no test-report da operação) | ⏳ pendente |
| CA-14 | manual, dupla: concordância **dispensada** pelo humano (ADR-025, resposta 5, opção 6B); a dispensa vai declarada no PR do split | ⏳ pendente (registro no PR do split) |
| CA-15 | manual: `split_v1` por PR | ⏳ pendente |
| CA-16 | manual: modelo oficial, CHANGELOG, Release e borda (depende do CA-15 da SPEC-044) | ⏳ pendente |

Os CAs 13 a 16 acontecem depois do merge (§4.7 e §8 da SPEC) e não contam como falha nesta rodada.

**CA-07, valor esperado.** Calculei o SHA-256 no merge-base `555c4b64e9f597756a3ea614d5e3ecaeb24590a6` (merge do PR #75, SPEC-044), num worktree destacado desse commit fora do repositório, com o `PYTHONPATH` apontando para o `ml/src` dele (conferi que `qc_ml.split` e `qc_ml.synthetic` vinham do worktree e que o `synthetic.py` dele não tem `include_nut`). Para `make_synthetic_dataset(items_per_stratum=3, images_per_item=3)` e a seed padrão (42): `7f18e97f68e275e26be2ae8042f0473467afce6d478f7fbb43f0d420bc6eddc9`. O valor e o commit estão no teste. Pelo mesmo procedimento, fixei mais 4 datasets num teste extra (abaixo); os 10 hashes que calculei (5 datasets × seeds 42 e 1) são iguais no merge-base e no `HEAD`.

## Ajustes em aceites de SPECs anteriores (`docs/architecture.md` §10; SPEC-045 §3.1)

A §3.1 cita nominalmente o CA-02 e o CA-03 da SPEC-041, as asserções sobre o conteúdo de `FLOOR_STRATA` e as asserções de que `--defer-types` é ignorado no `split_v1`. Os dois `extra` da SPEC-041 que a §3.1 não cita (`excluded_item` e `dominant_grade`) usam `nut/fair` como estrato retirado, como os CAs 02 e 03; a troca é a mesma, `nut/fair` → `screw/fair`, e a intenção (uma peça excluída conta como ausente; o grau dominante decide o estrato) não muda. Aplico a regra geral do §10 a eles. Nenhuma outra linha dos arquivos antigos mudou, e nenhum `test_caNN_` foi removido ou renomeado.

| Arquivo | Teste | Asserção antes → depois | Requisito |
|---|---|---|---|
| `ml/tests/acceptance/test_spec_041.py` | constante `FLOOR_STRATA` (usada por `test_extra_every_stratum_is_listed_when_only_externals_exist` e `test_extra_floor_problems_do_not_count_externals`) | 11 estratos (`screw/*`, `nut/*`, `other/none`) → 6 estratos (`screw/*`, `other/none`), ordenados | §3.1 (tamanho e conteúdo de `FLOOR_STRATA`), §4.1, CA-01 |
| `ml/tests/acceptance/test_spec_041.py` | `test_ca02_missing_stratum_is_refused_and_nothing_is_written` | retira uma peça `nut`/`fair` e espera `split_v1 below the floor: nut/fair` (única linha) → retira uma peça `screw`/`fair` e espera `split_v1 below the floor: screw/fair` (única linha) | §3.1 (CA-02 da SPEC-041), §4.1 |
| `ml/tests/acceptance/test_spec_041.py` | `_below_floor_ds` (auxiliar de `test_ca03_allow_below_floor_records_the_warning` e `test_extra_running_again_with_the_same_data_writes_no_new_version`) | retira uma peça `nut`/`fair` → retira uma peça `screw`/`fair` | §3.1 (CA-03 da SPEC-041), §4.1 |
| `ml/tests/acceptance/test_spec_041.py` | `test_ca03_allow_below_floor_records_the_warning` | `{"code": "below_floor", "stratum": "nut/fair"}` e `small_stratum` citando `nut/fair` → `screw/fair` nos dois | §3.1 (CA-03 da SPEC-041), §4.1 |
| `ml/tests/acceptance/test_spec_041.py` | `test_extra_many_strata_are_listed_in_lexicographic_order` | retira `S-005`, `O-001`, `N-003`, `N-002` e espera `["nut/fair", "nut/good", "other/none", "screw/unusable"]` → retira `S-005`, `O-001`, `S-003`, `S-002` e espera `["other/none", "screw/fair", "screw/good", "screw/unusable"]` (mantém 4 estratos fora de ordem na entrada, que é a intenção do teste) | §3.1 (conteúdo de `FLOOR_STRATA`), §4.1 |
| `ml/tests/acceptance/test_spec_041.py` | `test_extra_excluded_item_counts_as_missing` | exclui uma peça `nut`/`fair` e espera `nut/fair` → exclui uma peça `screw`/`fair` e espera `screw/fair` | §4.1 (mesma troca do CA-02, regra geral do §10) |
| `ml/tests/acceptance/test_spec_041.py` | `test_extra_dominant_grade_decides_the_stratum` | muda o grau dominante das peças `nut`/`fair` e espera `nut/fair` → das peças `screw`/`fair` e espera `screw/fair` (comentário acompanha) | §4.1 (mesma troca do CA-02, regra geral do §10) |
| `ml/tests/acceptance/test_spec_016.py` | `test_extra_split_v1_ignores_the_lists` → **renomeado** `test_extra_split_v1_defers_the_listed_type` | com `--defer-types pliers` no `split_v1`, esperava alicate no split e `deferred_types == []` → espera nenhum alicate no split e `deferred_types == ["pliers"]`; `test_extended_types == []` não muda | §3.1 (`--defer-types` ignorado no `split_v1`), §4.3, CA-08 |

Nos aceites das SPECs 011 e 021, nenhuma asserção verifica que `--defer-types` é ignorado no `split_v1` nem que uma manual sem grau fica estratificada por grau no `split_v1` (procurei por `defer`, `split_v1`, `small_stratum` e estratos): nada a ajustar. Os aceites das SPECs 011, 016, 021, 040 e 044 passam sem mudança.

## Suíte completa

Rodada única com banco, `CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q -p no:cacheprovider` (contêiner `partqc-pg`), sem torch (ambiente do CI):

```text
11096 passed, 168 skipped, 1 warning in 1055.96s (0:17:35)
(saída 0; os pulos são os marcadores docker, mqtt, telemetria e os testes que exigem torch;
 o aviso é o StarletteDeprecationWarning do fastapi.testclient, que já existia)
```

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
334 files already formatted
```

`ml/tests/acceptance/test_spec_045.py` sozinho: 38 passed em cerca de 28 s. `test_spec_041.py` e `test_spec_016.py` ajustados: 165 passed, 2 skipped (torch), 12 deselected (`slow`).

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Automatizados em `test_spec_045.py` (`test_extra_*`), todos passando:

| Caso | Resultado |
|---|---|
| `split_v1` igual ao do merge-base em mais 4 datasets (padrão; 5 por estrato com seed 7; com conhecidos; com elétricas e só identificadas), seed 42 | iguais byte a byte (§4.2, último item) |
| `--defer-types other` e `--defer-types screw` no `split_v1` | saída 2, `split_v1 below the floor: other/none` e os 5 `screw/*`, nada gravado (§4.3, último item) |
| `--defer-types bolt` no `split_v1` | saída 2, `unknown object type: bolt`, sem traceback, nada gravado |
| Valores estranhos: `Spirit_Level`, `nível` (unicode) e `spirit_level` com um espaço antes | os dois primeiros saem com 2 e `unknown object type: …`; o terceiro é aparado e aceito como `spirit_level` |
| `--defer-types spirit_level,hammer` | `deferred_types == ["hammer", "spirit_level"]` (ordem de `KNOWN_OBJECT_TYPES`); só `wrench` fica no split |
| `--extend-test-types spirit_level` no `split_v1` | sem efeito: `split_v1.csv` igual ao sem a flag; aviso no log citando `--extend-test-types` |
| `--defer-types hammer --extend-test-types hammer` no `split_v1` | saída 0, `hammer` adiado, `test_extended_types` vazio (o `extend` não tem efeito no `split_v1`; no `split_v2` o mesmo par é recusado, `object type in both …`) |
| `split_v1` sem `--defer-types` | `deferred_types == []` |
| Rodar de novo com o mesmo `--defer-types spirit_level` depois do `split_v1` | saída 0, `split unchanged: split_v1`, nada muda (ADR-022, decisão 4: adiar de novo é uma decisão) |
| Leitores do split depois do adiamento no `split_v1` | `assign_splits` dá `None` às imagens de `spirit_level`, sem erro; `rows_for(…, "test")` não traz nenhuma |
| `small_stratum` de tipo inteiro (2 peças de cada só identificada) | os avisos citam `hammer/none`, `wrench/none` e `spirit_level/none` (§4.2) |
| Elétricas no `split_v1` (3 peças por tipo) | 1 peça de cada em cada split (`<tipo>/none`) |
| Manual **graduada** no `split_v1` (alicate com 5 peças × 12 fotos por grau, `graded` verdadeiro) | continua estratificada por grau: em cada grau, 3/1/1 peças em treino/validação/teste |
| `split_stratum` com o `tool_grade_coverage` real de um dataset sem ferramentas, e com `nut` | as 5 manuais dão `<tipo>/none`; elétricas e só identificadas também; `nut` devolve o estrato recebido |
| Dataset sem porcas com 1 externa por estrato | saída 0, as externas só em `train`, sem `below_floor` |
| Gerador sem porcas com conhecidos e externas | nenhum `N-`/`XN-`; os `S-`, `O-`, `XS-`, `XO-` iguais aos da saída com porcas; o `sources.csv` só cita imagens do manifest, todo arquivo existe e `python -m qc_ml.data validate` sai com 0 |
| Fixture `tiny_model_no_nut` | `labels.json` com os 5 tipos e as 3 só identificadas da §3.1; `model.sha256` confere com o `model.onnx`; os 6 arquivos estão no Git |
| `ml/README.md` | tem a seção "Modelo oficial com as fotos dos colegas (ADR-025)", com `--defer-types` e o `plano-v2.csv` |

Manuais (scripts no scratchpad, fora do repositório):

- `--defer-types bolt,nut` e `nut,bolt`: o valor desconhecido tem precedência (`unknown object type: bolt`) sobre `deferred type without images`.
- `--defer-types nut --allow-below-floor`: sai com 2 (`deferred type without images: nut`); a flag do piso não contorna essa recusa.
- `--defer-types screw --allow-below-floor`: grava um `split_v1` sem nenhum parafuso, com 5 avisos `below_floor` e `deferred_types == ["screw"]`. É o que o §4.3 e a flag permitem; a flag exige decisão registrada (ADR-024).
- `--defer-types ""`: equivale a não passar a flag.
- `--defer-types spirit_level,spirit_level`: `deferred_types == ["spirit_level"]`, sem duplicata.

Não rodei o `make_tiny_fixture.py --identified-tools-no-nut`, porque exige torch e grava na pasta versionada da fixture; a consistência da fixture está coberta acima, e o teste do autor marcado `slow` cobre o script.

### Observação (não bloqueia)

- **Texto do aviso do `--extend-test-types` no `split_v1`.** O §4.3 diz "com o aviso de hoje no log". O autor trocou o texto (dev-report, decisão 4) de `--extend-test-types and --defer-types are not used for split_v1: …` para `--extend-test-types is not used for split_v1: every type present and not deferred is split normally`, porque o texto antigo passou a ser falso para o `--defer-types`. Nenhum CA confere o texto. Fica para o reviewer.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
- [x] Não abri nenhuma foto, nem li `ml/data/`, `~/partqc-entrada/` ou o backup.
- [x] Uma única suíte com banco por vez; sem push.
