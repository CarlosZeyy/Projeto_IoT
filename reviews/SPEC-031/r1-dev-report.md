# SPEC-031 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-031](../../docs/specs/SPEC-031-manutencao-ml.md) |
| Rodada | r1 |
| Autor | ml-engineer |
| Branch | `spec/SPEC-031-manutencao-ml` |
| Commits | `625e48d`, `5e7d721`, `177d75f`, `dcd278b`, `3bdd80c`, `c041309` (+ o commit deste relatório) |

## Resumo

- A paridade recusa valores não finitos: `ok=False`, `max_abs_diff=inf`, `argmax_equal=False` e `non-finite values` na mensagem. O máximo das diferenças passou a usar `np.maximum`, que propaga o `NaN`.
- `Predictions` recusa probabilidades não finitas ou fora de [0, 1], com mensagem que cita só o campo.
- O extra `train` tem o teto `torch<2.15`. O `uv.lock` foi regenerado só por `uv lock`.
- O export registra no log os avisos de depreciação do `torch.onnx.export` em vez de ignorá-los. O modelo exportado continua byte a byte igual (§ "Como rodar").
- `qc_ml.split` usa o `ITEM_ID_PATTERN` de `qc_ml.data`.
- O README e o notebook dizem que o `split_v1` vem antes do Colab, e o notebook exporta a rede mínima antes do treino.
- Não houve treino nesta SPEC: nenhum `metrics.json` novo.
- **Há dois SPEC_ISSUE:**
  - a §4.2 torna inválidas as entradas que o CA-18 da SPEC-012 prescreve;
  - o teto do `torch` quebra um teste de autor da SPEC-001, fora do meu caminho.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `ml/src/qc_ml/parity.py` (`check_parity`) | `ml/tests/test_parity.py::test_parity_non_finite_values_fail[nan-reference-at-argmax]` (inclui `main` → 2 e mensagem no stderr) |
| CA-02 | `ml/src/qc_ml/parity.py` | `test_parity.py::test_parity_non_finite_values_fail[nan-both-sides]`, `[inf-reference]`, `::test_parity_non_finite_onnx_output_fails` (só o lado do ONNX, com sessão real e um `NaN` injetado), `::test_parity_finite_result_unchanged`, `::test_ca12_tiny_fixture_parity`, `::test_ca13_perturbed_fixture_fails` |
| CA-03 | `ml/src/qc_ml/predict.py` (`Predictions.__post_init__`) | `ml/tests/test_predict.py::test_predictions_refuse_invalid_probabilities` (os 4 casos do CA, mais `-inf`, `1 + 1e-12` e `-1e-300`), `::test_predictions_accept_exact_bounds`, `::test_predictions_accept_float32_softmax_rounding`, `::test_predictions_accept_empty` |
| CA-04 | `ml/pyproject.toml`, `uv.lock` | `ml/tests/test_maintenance.py::test_torch_ceiling_in_train_extra_and_lock`. A parte da R-12 já é coberta pelos testes existentes de `api/` e `dashboard/`, que passam. |
| CA-05 | `ml/src/qc_ml/export.py` (`export_onnx`, `_log_export_warnings`) | Parte estática: `test_maintenance.py::test_export_does_not_ignore_warnings`. Com torch (`slow`): `ml/tests/test_export_warnings.py::test_export_logs_captured_warnings[DeprecationWarning]`, mais `FutureWarning` e `UserWarning` |
| CA-06 | `ml/notebooks/train_colab.ipynb` | `ml/tests/test_notebook.py::test_notebook_checks_the_export_and_the_split_before_training` e `::test_notebook_is_clean` |
| CA-07 | `ml/README.md` | `test_maintenance.py::test_readme_colab_flow_starts_with_split_v1` |
| CA-08 | sem mudança de código (`thresholds.py`, comportamento atual) | `ml/tests/test_thresholds.py::test_no_screw_nut_in_val` (acrescida a asserção de que `type_target_not_met` não aparece) |
| CA-09 | `ml/src/qc_ml/split.py` | `test_maintenance.py::test_item_id_pattern_is_defined_once` |

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1).

## Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q

# Parte slow (torch), só ml/tests, e depois volta ao ambiente do CI
uv sync --all-packages --extra train
uv run pytest -q ml/tests
uv sync --all-packages --locked
```

**`uv.lock` (§4.7).** Comando executado: `uv lock` (saída: `Resolved 115 packages`), depois de trocar `"torch"` por `"torch<2.15"` em `ml/pyproject.toml`. O arquivo não foi editado à mão. Resultado de `git diff --stat uv.lock`:

```text
 uv.lock | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)
```

A única linha alterada é o `requires-dist` do `qc-ml`, que passou de `{ name = "torch", marker = "extra == 'train'" }` para `{ name = "torch", marker = "extra == 'train'", specifier = "<2.15" }`. Nenhuma versão resolvida mudou: o `torch` continua `2.14.1`, e `uv lock --check` passa.

**Export inalterado.** Com o extra `train`, `uv run --package qc-ml python ml/scripts/make_tiny_fixture.py --out <scratchpad>/export_check` sai com 0 (é o comando da célula nova do notebook). O `model.sha256` gerado (`7bae76ae…0339a`) é igual ao da fixture versionada em `ml/tests/fixtures/tiny_model/`. A fixture não foi regenerada nem alterada.

O log mostra, como `WARNING`, os dois avisos reais do torch 2.14.1:

- `torch.onnx.export: You are using the legacy TorchScript-based ONNX export. ...`
- `torch.onnx.export: The feature will be removed. ...`

**Faixa real das probabilidades.** O `model.onnx` da fixture rodou no onnxruntime com 384 entradas aleatórias, em escalas de 0,1 a 1e4. As saídas ficaram em [0,0; 1,0] exatos, como a §4.2 prevê para o caminho real.

## Decisões tomadas dentro do escopo da SPEC

1. **`np.maximum` em vez de `np.fmax`** no acúmulo de `max_abs_diff`. A §4.1 pede "uma forma que não descarta `NaN`". O `np.fmax` descarta (§7), e o `np.maximum` propaga. A checagem de finitude vem antes e é o que dá `ok=False`, então o resultado com valores finitos é idêntico ao de antes (`test_parity_finite_result_unchanged`).
2. **Ordem na paridade:** primeiro as formas dos dois pares, depois a finitude, depois as diferenças. Antes, a forma do par `grade` só era conferida depois do cálculo do par `type`. O resultado de uma forma errada é o mesmo de hoje. Com valores não finitos e `model_sha256` diferente, a mensagem cita os dois problemas (`non-finite values …; … model_sha256 differs`).
3. **Avisos que não são de depreciação.** `catch_warnings(record=True)` captura todos os avisos emitidos dentro do export, não só os de depreciação. Para não sumir com eles (antes eles apareciam), cada aviso capturado que não é `DeprecationWarning` também vira `WARNING` no `qc_ml.export`, no formato `torch.onnx.export (<Categoria>): <mensagem>`. Nenhum aviso é reemitido. Dentro do bloco, o filtro é `simplefilter("always")`, para registrar o aviso mesmo com um filtro `"error"` ativo fora dele (cenário do CA-05). Não há `simplefilter("ignore")`.
4. **`IMAGE_FILE_PATTERN` de `qc_ml.split`.** Esse padrão também continha `[SNOT]-[0-9]{3}` literal num `re.compile`, o que o CA-09 proíbe em `split.py`. Agora ele é montado a partir de `ITEM_ID_PATTERN.pattern`. A regex resultante é idêntica, caractere a caractere (verificado em `test_item_id_pattern_is_defined_once`), então o comportamento do split não muda.
5. **Notebook.**
   - Célula de markdown (`### Checagem do export`) e célula de código novas logo depois da instalação, antes do dataset e do pipeline. A célula de código roda `!python ml/scripts/make_tiny_fixture.py --out /tmp/export_check` com `assert _exit_code == 0`, no mesmo padrão das outras.
   - A célula da seção 5 ganhou a condição do `split_v1`, com `python -m qc_ml.split`.
   - Para quem lê o notebook de cima para baixo, entrou também o item 4 em "Antes de rodar" (`split_v1` já na `main`).
   - O JSON segue no mesmo formato (indentação 1, UTF-8 sem escape).
6. **README.**
   - O passo 0 traz o comando completo do split, os três arquivos que vão por PR, a nota sobre o download do torch 2.14.x no Colab (§7) e a checagem do export.
   - Na seção do pipeline, entraram duas frases sobre a paridade com valores não finitos e a validação de `Predictions`.
7. **Teste do autor ajustado:** o helper `_review_preds` de `ml/tests/test_thresholds.py` gerava confiança de grau até 1,0475, com resto negativo, e a §4.2 passou a recusar isso. Agora a confiança é `min(start + 0.005·i, 1.0)`. As imagens afetadas ficam acima de qualquer limiar de revisão, então o resultado esperado (0,35 / 0,60) é o mesmo.

## SPEC_ISSUE (se houver)

**SPEC_ISSUE-01 — a §4.2 contradiz o texto do CA-18 da SPEC-012.**

O CA-18 da SPEC-012 prescreve, no segundo caso, "confiança de grau `0.5525 + 0.005·i`" para 100 imagens. Para i ≥ 90, a confiança passa de 1 (chega a 1,0475), e as demais probabilidades da linha ficam negativas. Com a §4.2 desta SPEC, `Predictions` recusa essas entradas com `ValueError: grade_probs has values outside [0, 1]`. Por isso, `ml/tests/acceptance/test_spec_012.py::test_ca18_review_threshold_targets_10pct` falha, e eu não posso alterar esse arquivo. A SPEC-031 não emenda o CA-18 nem prevê o efeito.

Sugestão para o architect: emendar o CA-18 da SPEC-012 para "confiança de grau `min(0.5525 + 0.005·i, 1)`". O resultado esperado não muda: continuam 10 imagens abaixo de 0,60 e `grade_review_threshold = 0.60`. Foi assim que ajustei o meu teste de autor equivalente. Depois, o tester ajusta o teste de aceite.

**SPEC_ISSUE-02 — a §4.3 item 1 quebra um teste de autor fora do caminho do ml-engineer.**

`tests/test_dependency_isolation.py::test_ml_train_extra_declares_training_stack` é um teste de autor da SPEC-001 (commit `702d915`, `Agent: developer`), na raiz do repositório. Ele compara as strings declaradas no extra `train` com igualdade exata:

```python
assert declared == {"torch", "torchvision", "timm", "onnx", "coral-pytorch"}
```

Com `"torch<2.15"`, que o CA-04 exige literalmente, o teste falha. O arquivo está fora de `ml/**`, fora do escopo da §3.1 e fora da exceção de caminho da §4.7, que só cobre o `uv.lock`. Além disso, é um teste de outro autor. Por isso não o alterei.

Sugestão: a SPEC autoriza o ajuste. Uma opção é estender a §4.7 para o ml-engineer trocar a asserção da linha 73 por uma comparação de nomes, que ignore o especificador, como já faz o `tests/acceptance/test_spec_001.py::test_ca08_…`, que passa. A outra é delegar a mudança de uma linha ao developer.

**Não é SPEC_ISSUE, mas também quebra um aceite antigo (fica para o tester):** `ml/tests/acceptance/test_spec_012.py::test_ca17_unusable_threshold_for_recall_90pct`. O texto do CA-17 é válido: com `p_unusable = 0.45`, `fair` = 0. O que falha é a construção no teste, `1.0 - 0.55 - p`, que dá `-5.55e-17` em ponto flutuante e é recusada pela §4.2. Basta montar como `1.0 - (0.55 + p)`, que dá `0.0` exato para `p = 0.45`, ou arredondar.

Os outros testes de aceite antigos passam.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor de `ml/tests` passando:
  - suíte completa sem torch (`CI=true TEST_DATABASE_URL=… uv run pytest -q`): **3 failed, 5726 passed, 53 skipped**. As 3 falhas são:
    - `tests/test_dependency_isolation.py::test_ml_train_extra_declares_training_stack` (SPEC_ISSUE-02);
    - `ml/tests/acceptance/test_spec_012.py::test_ca18_review_threshold_targets_10pct` (SPEC_ISSUE-01);
    - `ml/tests/acceptance/test_spec_012.py::test_ca17_unusable_threshold_for_recall_90pct` (construção do teste, para o tester).
  - com torch (`--extra train`), só `ml/tests`: 2 failed, 404 passed, 2 skipped (inclui os 3 testes `slow` de `test_export_warnings.py`). As 2 falhas são as do SPEC_ISSUE-01 e do CA-17 acima, ambas em `ml/tests/acceptance/test_spec_012.py`. O ambiente voltou para `uv sync --all-packages --locked`.
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhum `.onnx` novo no Git e nenhum dado em `ml/data/`. Os testes usam cópias da fixture em `tmp_path`, e o export de verificação foi gravado no scratchpad da sessão.

## Adendo do developer (§4.8)

| Campo | Valor |
|---|---|
| Autor | developer |
| Commit | `bde95df` (`bde95df18be8de8172aec448b61023ed72fc7ae4`), só `tests/test_dependency_isolation.py` |

**Mudança.** Em `test_ml_train_extra_declares_training_stack`, a igualdade exata das strings do extra `train` (antiga linha 73) passou a ser igualdade exata dos **nomes** dos requisitos. O nome é o prefixo de cada string que casa `[A-Za-z0-9._-]+`, em minúsculas, então o especificador de versão, o marcador e os extras ficam de fora. O conjunto esperado continua `{"torch", "torchvision", "timm", "onnx", "coral-pytorch"}`, com `==`, nem mais nem menos. Entrou o `import re`, e não se usa `packaging`. Nenhuma outra linha do arquivo mudou: as asserções sobre o `uv.lock` ficaram iguais.

**Resultado de `uv run pytest -q tests/test_dependency_isolation.py`:**

```text
..............                                                           [100%]
14 passed in 0.06s
```

`uv run ruff check .` e `uv run ruff format --check .`: limpos (`All checks passed!`, `226 files already formatted`).

SPEC_ISSUE: nenhum.
