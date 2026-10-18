# SPEC-008 — r2 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-008](../../docs/specs/SPEC-008-edge-inferencia-decisao.md) |
| Rodada | r2 |
| Autor | developer |
| Branch | `spec/SPEC-008-edge-inferencia-decisao` |
| Commits | `241bbec`, `e943e9e`, `c8e12ec` (+ o commit deste relatório) |

## Resumo

- `decide()` limita os números devolvidos às faixas do contrato **depois** de todas as comparações (§4.1, item 6): `type_confidence` e `grade_confidence` a `[0, 1]` e `grade_score` a `[0, 4]`. As comparações continuam com os valores brutos. Isso corrige o T-01 e o SPEC_ISSUE-01 da r1.
- `OnnxInferencer` resolve o `MODEL_DIR` no início da construção (`Path(model_dir).resolve(strict=True)`), antes do item 1, e lê todos os arquivos do diretório resolvido. O `model_version` passa a ser o nome do diretório alvo (§4.2, item 3). Caminho inexistente, link quebrado, laço de links ou byte NUL dão `ModelLoadError("MODEL_DIR: not a directory")`.
- O aquecimento usa zeros `[1, 3, crop, crop]`, com o `crop` do `preprocessing.json` (§4.2, item 7). Um `crop` incompatível com uma entrada fixa falha na carga, com uma mensagem que cita `model.onnx`.
- `MODEL_DIR` não é aparado (§4.4). O código já se comportava assim, porque o `env_ignore_empty` do `EdgeSettings` só ignora `""` e o `Path("   ")` não é um diretório. Agora há testes do comportamento, e as docstrings, o `edge/README.md` e o `.env.example` o descrevem.
- O helper `edge/tests/dummy_model.py` ganhou `input_shape` (`FIXED_INPUT_SHAPE`, que é o padrão, e `DYNAMIC_INPUT_SHAPE = ("N", 3, "H", "W")`) para o CA-22.

## Rastreabilidade (critério de aceite → implementação)

CA-01 a CA-18 não mudaram. A tabela completa está no `r1-dev-report.md`. Abaixo estão os CAs novos e os que a r2 tocou.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-04 (valores dentro das faixas não mudam) | `edge/src/qc_edge/decision.py` | `edge/tests/test_decision.py::test_values_inside_the_ranges_are_not_changed` e `test_review_margin_boundary_and_grade_score` (da r1) |
| CA-17 | `decision.py` | Só com a suíte do autor (`test_decision`, `test_onnx_inferencer`, `test_model_integration`): `decision.py` tem 92 statements, 0 faltando, **100%**. `onnx_inferencer.py` fica em 97% |
| CA-19 (a) | `decision.py` (`_clamp`, `MAX_GRADE_SCORE`, `decide`) | `test_decision.py::test_float32_softmax_unusable_is_clamped_to_4` (com `grade_score == 4.0`, `grade_confidence == 1.0` e `needs_review` falso), `test_float32_softmax_unusable_from_numpy_is_clamped` (vetores float32 do numpy) |
| CA-19 (b) | idem | `test_decision.py::test_type_confidence_above_1_is_clamped`, `test_type_confidence_above_1_is_clamped_for_unknown` |
| CA-19 (c) | idem | `test_decision.py::test_grade_confidence_above_1_and_negative_score_are_clamped` |
| CA-19 (`InspectionCreate` aceita) | idem | `test_decision.py::test_decision_is_accepted_by_the_contract`, ampliado com os três pares do CA-19 e com `[0, 0, 1.0000009]` |
| §4.1, item 6 (comparações com os valores brutos) | idem | `test_decision.py::test_comparisons_use_the_raw_values`: com `unusable_threshold=0` e `p4 = -5e-7` bruto, o grau vem do argmax (`perfect`). Se a comparação usasse o valor limitado, daria `unusable` |
| CA-20 | `decision.py`; rota da SPEC-007 sem mudança | `edge/tests/test_model_integration.py::test_confident_unusable_softmax_output_is_stored_with_score_4` (200, `grade == "unusable"`, `grade_score == 4.0`, 1 item no sink com `grade_score == 4.0` e 1 foto em `captures/`) |
| CA-21 | `edge/src/qc_edge/onnx_inferencer.py` (`_resolve_model_dir`, `_model_version`, `__init__`) | `test_onnx_inferencer.py::test_symlink_gives_the_name_of_the_target` (link, cadeia de links, link relativo e barra final), `test_symlink_to_a_directory_with_an_invalid_name` (`atual → Dummy_V1`), `test_valid_link_name_does_not_rescue_an_invalid_target`, `test_dot_dot_components_are_resolved`, `test_files_are_read_from_the_resolved_directory`, `test_broken_link_or_link_loop_names_model_dir`; `test_model_integration.py::test_symlinked_model_dir_sends_the_target_name` (via `main()`: log, `/api/status` e inspeção com `partqc-mnv3-v1`) |
| CA-22 | `onnx_inferencer.py` (`_create_session(model, type_count, crop)`) | `test_onnx_inferencer.py::test_crop_incompatible_with_a_fixed_input_fails_at_load` (`model.onnx: warm-up inference failed`), `test_warm_up_uses_the_crop_of_preprocessing` (o aquecimento envia `(1, 3, 256, 256)`), `test_dynamic_input_accepts_any_crop` (JPEG 1280×960 → `screw`/`good`), `test_fixed_input_with_the_default_crop_still_loads` |
| CA-23 | `edge/src/qc_edge/cli.py` e `config.py` (só docstring e comentário; o comportamento já existia) | `test_model_integration.py::test_blank_model_dir_is_not_stripped_and_exits_2` (`"   "`, `" "`, `"\t"`, `" \n "`: código 2, espião do `uvicorn.run` não chamado, log com `cannot load the model: MODEL_DIR: not a directory`), `test_blank_model_dir_is_kept_by_the_settings`, `test_empty_model_dir_means_no_model` (`""` → sobe sem modelo) |

## Resposta à rodada anterior (a partir de r2)

| Achado (relatório, ID) | O que mudou |
|---|---|
| `r1-test-report.md`, T-01 (`grade_score` > 4 e confiança > 1 viram 500 não tratado) | §4.1, item 6, em `decide` (`241bbec`). Os três `test_bug_t01_*` do tester passam sem mudança. A rota responde 200 com `grade_score = 4.0` (CA-20) |
| `r1-test-report.md`, SPEC_ISSUE-01 | Resolvido pelo architect com a opção (a), reaprovada pelo humano. Implementado como descrito na SPEC: limite só nos valores devolvidos, comparações com os valores brutos |
| `r1-test-report.md`, exploratórios: link simbólico usava o nome do link | §4.2, item 3 (`e943e9e`): vale o nome do diretório resolvido. Ver a nota sobre o `test_extra_symlinked_model_dir_uses_the_link_name` abaixo |
| `r1-test-report.md`, exploratórios: `MODEL_DIR="   "` não citado pela SPEC | §4.4: o comportamento (código 2) já era o pedido. Agora tem testes e documentação (`c8e12ec`) |
| `r1-dev-report.md`, observação sobre o `crop` ≠ 224 no aquecimento | §4.2, item 7 (`e943e9e`): o aquecimento usa o `crop` do `preprocessing.json` |

## Como rodar e verificar

```bash
uv sync --all-packages
uv run pytest edge/tests -q
uv run pytest -q edge/tests/test_decision.py edge/tests/test_onnx_inferencer.py \
  edge/tests/test_model_integration.py --cov=qc_edge.decision --cov-report=term-missing
uv run ruff check . && uv run ruff format --check .
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

Resultados nesta rodada:

- `ruff check`: `All checks passed!`. `ruff format --check`: 156 arquivos já formatados.
- `uv lock --check`: OK. Nenhuma dependência mudou.
- Suíte completa, com `CI=true` e o banco `partqc-pg`: **1 failed, 4156 passed, 1 skipped**, 1 warning, que já existia (`StarletteDeprecationWarning` do `fastapi.testclient`).
  - O skip é o CA-16, manual, que roda sem `QC_REAL_MODEL_DIR`.
  - A falha, a única, é `edge/tests/acceptance/test_spec_008.py::test_extra_symlinked_model_dir_uses_the_link_name` (`assert 'dummy-v1' == 'partqc-link-v2'`). Esse teste verifica o comportamento da r1 (vale o nome do link). A §4.2, item 3, e o CA-21 o **invalidaram** de propósito, e a §6 da SPEC manda o tester removê-lo ou reescrevê-lo na r2. Não alterei o arquivo de aceite (R-07).
  - Os testes de aceite das SPECs 007, 010 e 025 e os demais da SPEC-008, inclusive os `test_bug_t01_*`, passam.

## Decisões tomadas dentro do escopo da SPEC

1. **Mensagem única para o `MODEL_DIR` que não resolve.** Caminho inexistente, link quebrado, laço de links (`RuntimeError` no Python 3.12), byte NUL (`ValueError`) e caminho que não é diretório dão a mesma `ModelLoadError("MODEL_DIR: not a directory")`, que já era a da r1. A mensagem cita a variável, nunca o caminho, como na convenção do `qc-edge`.
2. **Ordem da construção.** Ela segue a §4.2: resolução (início do item 3), arquivos (1), integridade (2), validação do nome (3), labels (4), preprocessing (5), limiares (6) e sessão com aquecimento (7). Por isso um diretório com nome inválido e hash divergente continua dando `ModelIntegrityError`, como na r1 (`test_integrity_is_checked_before_the_other_files`).
3. **`_clamp` e `MAX_GRADE_SCORE = float(GRADE_COUNT - 1)`** ficam em `qc_edge.decision`. O limite vale também para `type_confidence` quando o resultado é `unknown`, porque a §4.1, item 6, não faz exceção.
4. **Constante `WARMUP_SHAPE` removida.** A forma agora depende do `crop`, e `_create_session` recebe o `crop` como parâmetro.
5. **Teste de leitura do diretório resolvido.** Um espião de `Path.open` confere que todo arquivo aberto na construção está no diretório alvo, não no link.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando. A única falha da suíte completa é o teste de aceite que a SPEC invalidou, descrito acima
- [x] `.env.example` atualizado (nenhuma variável nova; o comentário de `MODEL_DIR` cita o link e o valor só com espaços)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
