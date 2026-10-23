# SPEC-031 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-031](../../docs/specs/SPEC-031-manutencao-ml.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `0e4d486` (inclui a passada do developer da §4.8, `bde95df`) |
| **Veredicto** | **PASS** |

Os testes foram escritos primeiro a partir da SPEC (caixa-preta), pela interface pública: `check_parity` e `python -m qc_ml.parity`, `Predictions`, `choose_thresholds`, `export_onnx`, os módulos `qc_ml.split` e `qc_ml.data`, e os arquivos `ml/pyproject.toml`, `uv.lock`, `ml/README.md` e o notebook. Só depois li a implementação. As mudanças na fixture `tiny_model` são sempre feitas numa cópia em `tmp_path`, sem rede e sem dado real.

## Cobertura dos critérios de aceite

Arquivo: `ml/tests/acceptance/test_spec_031.py` (30 testes: 14 de CA, contando os parâmetros, e 16 exploratórios `test_extra_*`).

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_nan_reference_at_argmax_fails_parity`: `check_parity` dá `ok=False`, `max_abs_diff == inf` e `non-finite values`. A CLI em subprocesso sai com 2, com a mensagem no stderr, e `main([...])` também retorna 2 | ✅ |
| CA-02 | `test_ca02_nan_input_and_references_fail_and_original_passes`: `inputs[0]`, `type_probs[0,:]` e `grade_probs[0,:]` com `NaN` dão `ok=False` e `non-finite values`; a fixture original dá `ok=True` e `max_abs_diff < 1e-4` | ✅ |
| CA-03 | `test_ca03_predictions_refuse_invalid_probabilities[type-nan, grade-inf, type-negative, grade-above-one]`: `ValueError` com o nome do campo, sem o nome do outro campo. `test_ca03_predictions_accept_valid_bounds_and_empty`: valores em [0, 1], `0.0`/`1.0` exatos e `n = 0` são aceitos | ✅ |
| CA-04 | `test_ca04_torch_ceiling_in_pyproject_and_lock`: o extra `train` tem `"torch<2.15"` (e nenhuma outra entrada `torch`); no `uv.lock`, `torch` está em `2.14.1`, e o `requires-dist` do `qc-ml` tem `specifier = "<2.15"` e `marker = "extra == 'train'"`. Um percurso próprio do grafo do lock mostra que o fecho do `qc-api` e do `qc-dashboard` não contém `torch`, `torchvision`, `timm` nem `onnxruntime`. O teste de CI da R-12 (`tests/test_dependency_isolation.py`, 14 testes) passa na suíte | ✅ |
| CA-05 | Parte estática: `test_ca05_export_has_no_ignore_filter` (`ast`: nenhuma chamada `simplefilter`/`filterwarnings` com `"ignore"`, com controle positivo do detector). Parte com torch (`slow`): `test_ca05_export_logs_deprecation_warning`, com `torch.onnx.export` envolvido para emitir um `DeprecationWarning` marcador depois do original, `simplefilter("error")` ativo, a `TinyNet` de `ml/scripts/make_tiny_fixture.py` e o `caplog` com o registro `WARNING` de `qc_ml.export` `torch.onnx.export: <marcador>` | ✅ (o `slow` foi pulado no CI e passou com o extra `train`, ver abaixo) |
| CA-06 | `test_ca06_notebook_export_check_and_split_before_pipeline`: a célula de código com `make_tiny_fixture.py --out` (índice 9) vem antes da do `python -m qc_ml.pipeline` (índice 15); a célula de markdown 13 contém `split_v1` e `python -m qc_ml.split`; as condições do CA-26 da SPEC-012 continuam valendo em todas as células de código | ✅ |
| CA-07 | `test_ca07_readme_split_v1_before_step_1`: a seção "Do Colab ao Release" foi isolada até o próximo título de nível igual ou superior, sem tratar `#` dentro de blocos de código como título. Ela contém `python -m qc_ml.split` e `split_v1`, e o comando vem antes da primeira linha `1.` | ✅ |
| CA-08 | `test_ca08_no_screw_nut_in_val_note`: com a validação só com imagens `other`, `type_threshold == 0.5`, e as notas têm `no_screw_nut_in_val` e não têm `type_target_not_met` | ✅ |
| CA-09 | `test_ca09_item_id_pattern_defined_once`: `qc_ml.split.ITEM_ID_PATTERN is qc_ml.data.ITEM_ID_PATTERN`, e o `ast` de `split.py` não tem `re.compile` com uma constante que contenha `[SNOT]` (checando todas as subexpressões do argumento, inclusive f-strings) | ✅ |

**Controle negativo.** Rodei o `test_spec_031.py` contra uma cópia do código da base do branch (`3ed113c`, sem a SPEC-031), exportada com `git archive` para o scratchpad e importada por `PYTHONPATH`, sem worktree. Resultado: 22 falham e 7 passam. Todos os CAs de comportamento novo falham (CA-01 a CA-07 e CA-09). Passam só o CA-08, que fixa um comportamento que já existia (§4.4), e os exploratórios de comportamento anterior. A cópia foi apagada depois.

## Ajustes em testes de aceite de SPECs anteriores (`docs/architecture.md` §10)

Aplicação explícita da §3.1 da SPEC-031, motivada pela §4.2. Só a montagem das entradas mudou; nenhuma asserção mudou, e nenhuma outra linha do arquivo mudou (`git diff`: 2 linhas trocadas).

| Arquivo | Teste | Antes → depois | Requisito |
|---|---|---|---|
| `ml/tests/acceptance/test_spec_012.py` | `test_ca17_unusable_threshold_for_recall_90pct` | `1.0 - 0.55 - p` → `1.0 - (0.55 + p)` na probabilidade de `fair`. É o mesmo valor matemático `1 − 0,55 − p`, sem o resto `-5.55e-17` para `p = 0.45` (agora `0.0` exato; os outros 9 valores continuam positivos) | SPEC-031 §4.2 ("Efeito nos CAs da SPEC-012", CA-17) e §3.1 |
| `ml/tests/acceptance/test_spec_012.py` | `test_ca18_review_threshold_targets_10pct` (segundo caso) | `conf = [0.5525 + 0.005 * i ...]` → `conf = [min(0.5525 + 0.005 * i, 1.0) ...]` | SPEC-031 §4.2 ("Efeito nos CAs da SPEC-012", CA-18) e §3.1 |

Os dois testes passam, com as asserções originais (`unusable_threshold == 0.12`, recall 0,9, `unusable_target_not_met` no caso baixo; `grade_review_threshold == 0.60` sem `review_adjusted`).

## Suíte completa

Ambiente do CI (`uv sync --all-packages --locked`, sem torch), com o banco de teste:

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
5758 passed, 54 skipped, 1 warning in 396.41s (0:06:36)
```

- Os 54 testes pulados são os de Docker (`PARTQC_DOCKER_TESTS`), o `slow` do CA-05, os `slow` de torch do ml e os de `ml/models/*` locais, que não existem neste checkout.
- O único warning não vem de `ml/tests` nem de `tests/`: `uv run pytest -q ml/tests tests` dá `778 passed, 26 skipped` sem warnings.
- As 3 falhas do dev-report r1 (`tests/test_dependency_isolation.py::test_ml_train_extra_declares_training_stack`, CA-17 e CA-18 da SPEC-012) agora passam, como pede o §6.

Parte `slow` (com o extra `train`, torch `2.14.1+cu130`), só `ml/tests`, como pede o §6:

```text
$ uv sync --all-packages --locked --extra train
$ uv run pytest -q ml/tests
436 passed, 2 skipped in 172.08s (0:02:52)
$ uv run pytest -q ml/tests/acceptance/test_spec_031.py -k ca05 -rA
WARNING  qc_ml.export:export.py:70 torch.onnx.export: The feature will be removed. Please remove usage of this function
WARNING  qc_ml.export:export.py:70 torch.onnx.export: partqc-spec031-ca05-marker
2 passed, 28 deselected
$ uv sync --all-packages --locked     # .venv de volta ao estado do CI (torch removido)
```

Os 2 pulados com torch são os de modelos locais em `ml/models/*`, que não existem no checkout.

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
227 files already formatted
```

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Automatizados em `test_spec_031.py` (`test_extra_*`), todos passando:

| Caso | Resultado |
|---|---|
| Referência com `+inf` em `type_probs`, `-inf` ou `NaN` em `grade_probs` (fora do argmax) | `ok=False`, `max_abs_diff=inf`, `argmax_equal=False`, `sha256_match=True` ("calculado como hoje") e `non-finite values` |
| Só o lado do ONNX não finito: amostra 2 inteira com `NaN` na entrada e referências finitas | `ok=False`, `inf`, `non-finite values`; a CLI sai com 2, a mensagem vai para o stderr e o stdout fica vazio |
| `NaN` na referência e `model_sha256` de outro modelo | `ok=False`, `sha256_match=False` e `non-finite values` |
| Forma errada da referência (`grade_probs[:, :4]`) | continua `ok=False` com `max_abs_diff=inf` |
| Perturbação finita de 5e-3 | `max_abs_diff` ≈ 5e-3 e sem "non-finite": o resultado com valores finitos não mudou |
| `Predictions` com `-inf`, `-1e-300`, `1 + 1e-12` e `NaN`, e caminhos de imagem com unicode e caminho absoluto | `ValueError` com o nome do campo; a mensagem não cita o valor nem o caminho ou o nome do arquivo |
| `Predictions` com float32, `-0.0` e listas Python; `n = 0` com arrays 1-D vazios | aceitos |
| `ITEM_ID_PATTERN` e `IMAGE_FILE_PATTERN` do split (válidos e inválidos, inclusive `Ｓ-001` de largura total e dígitos arábicos `٠٠١`) | o comportamento do split continua o mesmo (§4.6) |
| Notebook: a checagem do export grava em `/tmp/export_check` (nunca na fixture versionada), vem depois da célula do `pip install ... -e "ml[train]"` e é precedida por uma célula de markdown | ok |
| README: o passo 0 cita `split_v1.csv`, `split_v1.sha256` e `split_v1.json` antes do passo 1, e a seção documenta o download do torch 2.14.x no Colab (§7) | ok |

Manuais, com o extra `train`:

- `uv run --package qc-ml python ml/scripts/make_tiny_fixture.py --out <scratchpad>` (o comando da célula nova do notebook) sai com 0. O `model.sha256` gerado é igual ao da fixture versionada (`7bae76ae…0339a`). Os dois avisos reais do torch 2.14.1 aparecem como `WARNING` de `qc_ml.export`. A saída foi apagada depois.
- `export_onnx` da `TinyNet` com `python -W error` (todos os avisos como erro no processo inteiro) completa sem exceção e registra os dois avisos no log. Isso confirma que o export não quebra num ambiente que trata avisos como erro.

**Observação (sem severidade, não é bug).** Um único pixel `NaN` na entrada, numa posição que a convolução da `TinyNet` (stride 4) não lê, não chega à saída do ONNX, e a paridade passa. Isso é propriedade do modelo, não da `check_parity`, que só compara saídas e referências, como a §4.1 pede. Por isso o exploratório "só o lado do ONNX" usa a amostra inteira com `NaN`.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` (`ml/tests/acceptance/test_spec_031.py`, novo, e as duas linhas de `ml/tests/acceptance/test_spec_012.py` da tabela do §10) e este relatório.
