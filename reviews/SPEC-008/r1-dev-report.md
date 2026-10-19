# SPEC-008 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-008](../../docs/specs/SPEC-008-edge-inferencia-decisao.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-008-edge-inferencia-decisao` |
| Commits | `57013ba`, `bd42973`, `d27a0f7`, `2ce2629` (+ o commit deste relatório) |

## Resumo

- `qc_edge.decision`: `Thresholds`, `ModelLabels`, `Decision`, `decide()`, `InvalidModelOutputError` (subclasse do `InferenceError` da SPEC-007) e `REVIEW_MARGIN = 0.10`. As comparações seguem a §4.1 ao pé da letra: `<` estrito no `type_threshold`, `>=` no `unusable_threshold`, empate no argmax vai para o menor índice e nada é arredondado.
- `qc_edge.onnx_inferencer`: `OnnxInferencer`, `ModelLoadError` e `ModelIntegrityError`. A carga segue a ordem da §4.2 (arquivos, SHA-256, `model_version`, labels, preprocessing, limiares com overrides, sessão CPU com aquecimento que confere as formas). `infer` usa `qc_preprocess.preprocess`, `session.run` e `decide`. Um erro do `onnxruntime` vira `InferenceError`.
- Integração: com `MODEL_DIR`, o `qc-edge` carrega o `OnnxInferencer`; se o diretório for inválido, sai com código 2. `--stub-model` tem precedência e gera um aviso no log. O `EdgeSettings` valida as três variáveis de limiar (número finito em `[0, 1]`). O console e o `/api/status` mostram a versão, os 12 primeiros caracteres do sha e os limiares com a origem (`model.thresholds`).
- Helper de teste `edge/tests/dummy_model.py`, servido pela fixture `dummy_model` do `edge/tests/conftest.py` (vale também para `edge/tests/acceptance/`). Usa `onnx.helper` com opset 17 e `ir_version` 8, sem torch. `onnx` entrou como grupo `dev` do `qc-edge`.
- `edge/README.md` ganhou a seção "Trocar o modelo" (com "Limiares de decisão"), a tabela de variáveis e o `/api/status` revistos. `.env.example` com os comentários de `MODEL_DIR` e dos limiares atualizados.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `edge/src/qc_edge/decision.py` (`decide`) | `edge/tests/test_decision.py::test_other_is_unknown_even_with_high_confidence` |
| CA-02 | idem | `test_decision.py::test_low_type_confidence_is_unknown_and_needs_review` |
| CA-03 | idem | `test_decision.py::test_type_threshold_is_strict` |
| CA-04 | idem | `test_decision.py::test_review_margin_boundary_and_grade_score` |
| CA-05 | idem | `test_decision.py::test_unusable_threshold_is_inclusive` |
| CA-06 | idem | `test_decision.py::test_grade_review_threshold` (0,6 e 0,59) |
| CA-07 | `decision.py` (`_probabilities`) | `test_decision.py::test_invalid_outputs` (soma 1,5, NaN, inf, negativo, 4 e 6 graus, 2 e 4 tipos, não numérico, escalar, lote `[1,3]`), `test_tolerances_accept`, `test_tolerances_refuse` |
| CA-08 | `edge/src/qc_edge/onnx_inferencer.py`, `edge/src/qc_edge/cli.py` | `edge/tests/test_onnx_inferencer.py::test_infer` (JPEG 1280×960), `test_loads_a_valid_directory` (`ModelInfo("dummy-v1", sha)`), `edge/tests/test_model_integration.py::test_model_dir_loads_the_onnx_model` (via `POST /api/capture`, `model_version="dummy-v1"`) e `test_unknown_result_goes_to_the_sink` (item no sink com `dummy-v1`) |
| CA-09 | `onnx_inferencer.py` (`_expected_sha256`, `_read_model`), `cli.py` (`_load_inferencer`) | `test_onnx_inferencer.py::test_hash_mismatch` (12 caracteres de cada, nunca o hash inteiro), `test_model_changed_after_the_hash`, `test_malformed_sha256_file`, `test_integrity_is_checked_before_the_other_files`, `test_sha256_file_formats`; `test_model_integration.py::test_invalid_model_dir_exits_2` (código 2) |
| CA-10 | `onnx_inferencer.py` (`_load_labels`) | `test_onnx_inferencer.py::test_invalid_labels` (`pliers`, `unknown`, graus fora de ordem e outros 11 casos); `test_model_integration.py::test_invalid_model_dir_exits_2` (`pliers`) |
| CA-11 | `onnx_inferencer.py` (`REQUIRED_FILES`, `_load_decision`) | `test_onnx_inferencer.py::test_missing_file` (cada um dos 5), `test_invalid_decision` (`type_threshold=1.2` e outros), `test_decision_with_non_finite_constants`; `test_model_integration.py::test_invalid_model_dir_exits_2` |
| CA-12 | `onnx_inferencer.py` (`_apply_overrides`), `edge/src/qc_edge/config.py` (`Threshold`), `cli.py` (`_threshold_overrides`) | `test_onnx_inferencer.py::test_override_takes_precedence` (0,7 → 0,55, origem `env`), `test_every_override_and_threshold_names`, `test_invalid_override_names_the_variable`; `test_model_integration.py::test_invalid_threshold_variable_exits_2` (`1.5`, `abc`, `-0.1`, `nan`, `inf`, com e sem modelo: código 2 citando `TYPE_THRESHOLD`); `edge/tests/test_config.py::test_invalid_values_name_the_variable` |
| CA-13 | `onnx_inferencer.py` (`_create_session`) | `test_onnx_inferencer.py::test_wrong_type_output_shape` (`[N,4]` com 3 tipos), `test_wrong_input_name`, `test_wrong_grade_output_shape`, `test_wrong_output_name`, `test_not_an_onnx_file`, `test_ir_version_too_new_for_the_locked_runtime`, `test_warm_up_failure` |
| CA-14 | `decision.py` (`InvalidModelOutputError` é `InferenceError`); `app.py` já respondia 500 a `InferenceError` (SPEC-007) | `test_model_integration.py::test_capture_with_invalid_model_output_is_500` (500 `inference failed`, sink vazio, nenhum arquivo novo); `test_onnx_inferencer.py::test_infer_invalid_output` |
| CA-15 | `onnx_inferencer.py` (`infer`) | `test_onnx_inferencer.py::test_latency_p95` (50 execuções, JPEG 1280×960; aqui, p95 de ~6 ms) e `test_infer_latency_covers_preprocess_model_and_decision` (relógio simulado) |
| CA-16 | N/A para o autor (manual/slow, do tester e da dupla) | — |
| CA-17 | `decision.py` | `pytest edge/tests --cov=qc_edge.decision`: **100%** (89 statements, 0 faltando), só com a suíte do autor |
| CA-18 | `edge/src/qc_edge/app.py` (`_model_state`, `_thresholds_status`, `_thresholds_html`), `edge/src/qc_edge/templates/console.html` | `test_model_integration.py::test_console_shows_the_model_and_the_thresholds`, `test_model_dir_loads_the_onnx_model` (`/api/status` com `model.thresholds`), `test_console_without_thresholds`; `edge/tests/test_pages.py::test_status`, `test_status_without_model_and_with_last_success` e `test_console_from_loopback` (ajustados) |

Outros testes do autor: `test_onnx_inferencer.py::test_the_hashed_bytes_are_the_ones_loaded` (os bytes passados ao `InferenceSession` são os que tiveram o hash conferido, com `providers=["CPUExecutionProvider"]`), `test_infer_from_several_threads` (4 threads × 5 chamadas), `test_onnxruntime_error_is_an_inference_error`, `test_preprocess_error_is_an_inference_error`, `test_output_with_an_unexpected_batch_shape`, `test_relative_dot_directory_and_trailing_slash`, `test_invalid_model_version`; `test_model_integration.py::test_stub_model_takes_precedence`, `test_overrides_without_a_model_are_ignored`, `test_missing_model_dir_exits_2`.

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1).

## Como rodar e verificar

```bash
uv sync --all-packages                     # inclui o onnx do grupo dev do qc-edge
uv run pytest edge/tests -q
uv run pytest edge/tests -q --cov=qc_edge.decision --cov-report=term-missing
uv run ruff check . && uv run ruff format --check .
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

Resultado nesta rodada: `ruff check` e `ruff format --check` limpos (155 arquivos). A suíte completa, com `CI=true` e o banco `partqc-pg`, terminou com **4041 passed** e 1 warning, que já existia (`StarletteDeprecationWarning` do `fastapi.testclient`). A suíte do `edge` terminou com 1090 passed. Os testes de aceite das SPECs 007, 010 e 025 passam sem ajuste. Também passaram `uv lock --check` e `uv sync --all-packages --frozen`, o comando do CI.

## Decisões tomadas dentro do escopo da SPEC

1. **Chaves de `overrides`.** O `OnnxInferencer` aceita o nome da variável (`TYPE_THRESHOLD`) ou o nome do limiar (`type_threshold`). O valor pode ser um número ou uma string numérica, como vem do ambiente. A mensagem de erro cita sempre a variável. A mesma variável informada duas vezes (pelos dois nomes) ou uma chave desconhecida gera `ModelLoadError`. O CLI passa os nomes das variáveis. A §4.2 diz "overrides de `TYPE_THRESHOLD`, ..." e não fixa a chave do dict.
2. **Validação dupla dos limiares de env.** O `EdgeSettings` recusa valor fora de `[0, 1]`, não numérico, `nan` ou `inf` (`Field(ge=0, le=1, allow_inf_nan=False)`). A subida sai com código 2 e a mensagem já existente, `invalid configuration: TYPE_THRESHOLD: ...`, que cita a variável e não o valor. Isso vale mesmo sem `MODEL_DIR`. Sem modelo, os overrides válidos são ignorados, com um aviso no log. O `OnnxInferencer` valida de novo, para quem o chama direto.
3. **JSONs com chaves exatas.** O `labels.json` e o `decision.json` recusam chave desconhecida, como já faz o `PreprocessParams.from_json`. Motivo: um limiar novo de um `decision.json` futuro seria ignorado em silêncio. A SPEC-012 já grava exatamente essas chaves.
4. **Integridade sem TOCTOU.** O `model.onnx` é lido uma vez, em blocos de 1 MiB. O SHA-256 é calculado sobre esses bytes, e os mesmos bytes vão para o `InferenceSession` (que aceita `bytes`). Assim, o arquivo executado é o conferido. Custo: o modelo fica na memória duas vezes por um instante, na subida. Um modelo com dados externos ao `.onnx` não carregaria assim, mas o export da SPEC-012 (opset 17, MobileNetV3) não gera esse formato.
5. **`model.sha256` malformado** (vazio, token que não tem 64 hexadecimais, não ASCII, mais de 4 KiB) gera `ModelLoadError` citando `model.sha256`, e não `ModelIntegrityError`. Esse fica só para o hash bem formado que diverge.
6. **Mensagens só com o nome do arquivo**, nunca o caminho completo, como na convenção do `qc-edge` de não ecoar valores de configuração. Ex.: `missing file(s) in MODEL_DIR: decision.json` e `MODEL_DIR: not a directory`. Na mensagem do `preprocessing.json`, o caminho que o `from_json` coloca é trocado pelo nome do arquivo.
7. **`model_version`** = `Path(os.path.abspath(MODEL_DIR)).name`. Isso resolve `.` e a barra final sem seguir links simbólicos. A validação usa `re.fullmatch(MODEL_VERSION_PATTERN)`, importada do contrato.
8. **Entrada e saídas:** a sessão precisa ter exatamente uma entrada, chamada `image`, e conter as saídas `type_probs` e `grade_probs`. Saídas extras não são usadas. Exceções do `onnxruntime` (`Fail`, `InvalidArgument`... derivam de `Exception`, não de `RuntimeError`) viram `ModelLoadError` na carga e `InferenceError` no `infer`, com a classe e a primeira linha da mensagem (até 200 caracteres).
9. **`latency_ms`** mede pré-processamento, modelo e `decide`, na ordem da §4.3. Um erro do pré-processamento (`ValueError`/`TypeError`, como uma imagem fora de RGB) também vira `InferenceError`. Pela rota, isso nunca acontece, porque o `load_image` sempre devolve RGB.
10. **`Thresholds.__post_init__`** valida cada limiar (número real finito em `[0, 1]`, nunca `bool`) e guarda como `float`, conforme o comentário "cada um em [0, 1]" da §4.1. `ModelLabels` continua um dataclass simples: a validação dos rótulos fica na carga do `labels.json`.
11. **`/api/status`:** o formato da SPEC-007 continua igual (`model_sha256` inteiro), acrescido de `model.thresholds` (`{nome: {"value", "source"}}`), que é `null` sem modelo e com o `StubInferencer`, que não tem limiares. O console mostra `carregado: <versão> (sha256 <12 caracteres>)` também para o stub (`000000000000`) e uma lista "Limiares de decisão" com rótulo PT-BR, o nome técnico, o valor (`repr`, com ponto, igual ao do `.env`) e a origem (`decision.json`/`env`, com a explicação em PT-BR). Os `id`s são `model-state`, `model-thresholds` e `threshold-<nome>`. A borda acessa os limiares por duck typing (`getattr`), então o `app.py` não importa o `onnxruntime`.
12. **`short_sha`** fica em `qc_edge.inference`, junto do `ModelInfo`, e é usado pelo erro de integridade, pelo log e pelo console.
13. **`onnx` no grupo `dev` do `qc-edge`** (`[dependency-groups] dev`), e não no grupo `dev` da raiz. O `uv sync --all-packages`, inclusive o `--frozen` do CI, instala o grupo. O `onnx` 1.23.2 já estava no lock pelo extra `train` do `qc-ml`, então o `uv.lock` só ganhou a aresta de dev do `qc-edge`. Nenhum pacote novo foi resolvido. A `tests/lockgraph.py` não segue grupos de dev, e o `qc-api` e o `qc-dashboard` não mudaram (R-12; `tests/test_dependency_isolation.py` verde).
14. **`ir_version` 8** no modelo dummy: o `onnx` 1.23.2 grava IR 14 por padrão, e o `onnxruntime` 1.31.0 do lock recusa com `Unsupported model IR version: 14, max supported IR version: 13` (conferido). O IR 8 é o do opset 17. O `test_ir_version_too_new_for_the_locked_runtime` cobre a recusa.
15. A versão do `qc-edge` continua `0.0.0`, porque a SPEC não pede aumento. Nenhum pacote compartilhado mudou, e o Pillow não foi atualizado.

### Observações para o tester e o reviewer (não bloqueiam)

- **CA-16:** a pasta `edge/tests/fixtures/` citada pelo CA-16 ainda não existe. Como as fotos reais não vão para o Git (R-14, `architecture.md` §7), a escolha do conteúdo (imagens sintéticas ou geradas no teste) fica com o tester.
- **`crop` do `preprocessing.json`:** o aquecimento usa zeros `[1,3,224,224]`, como manda a §4.2, item 7. Um `preprocessing.json` com `crop` diferente de 224 e um modelo de entrada fixa em 224 passaria na carga e falharia em todo `infer` (500 `inference failed`). Não acrescentei uma checagem `crop == 224` porque a SPEC não a pede. Fica registrado caso o architect queira incluí-la numa SPEC futura.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (suíte completa: 4041 passed com `CI=true` e `TEST_DATABASE_URL`)
- [x] `.env.example` atualizado (nenhuma variável nova; comentários de `MODEL_DIR` e dos limiares revistos)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
