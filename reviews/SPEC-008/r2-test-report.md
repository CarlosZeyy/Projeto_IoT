# SPEC-008 — r2 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-008](../../docs/specs/SPEC-008-edge-inferencia-decisao.md) |
| Rodada | r2 |
| Tester | tester |
| Commit testado | `8c53c20` (implementação do developer na r2: `241bbec`, `e943e9e` e `c8e12ec`; o commit do tester só altera `edge/tests/acceptance/test_spec_008.py` e acrescenta este relatório) |
| **Veredicto** | **PASS** |

Os 22 critérios automatizáveis (CA-01 a CA-15 e CA-17 a CA-23) têm teste e todos passam. O CA-16 é manual e continua pendente, porque o modelo real da SPEC-012 ainda não existe. Isso não é falha. A suíte inteira passa (4182 passed, 1 skipped), e o `ruff check` e o `ruff format --check` estão limpos. O T-01 e o SPEC_ISSUE-01 da r1 estão resolvidos. Não encontrei bug novo.

Escrevi os testes dos CAs 19 a 23 a partir da SPEC reaprovada, antes de ler o diff da r2. O modelo dummy continua sendo o meu (`build_dummy_onnx`, §6). Ele ganhou o parâmetro `input_shape` (padrão `["N",3,224,224]`; variante dinâmica `["N",3,"H","W"]` para o CA-22). As imagens continuam sintéticas e geradas em memória (R-14). Depois de ler a implementação, não precisei corrigir nenhum teste.

## Cobertura dos critérios de aceite

Arquivo: `edge/tests/acceptance/test_spec_008.py`. Ele tem 35 funções `test_caNN_*` e 38 `test_extra_*`, ou **113 casos** depois da parametrização: 112 passam e 1 é pulado (CA-16).

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 a CA-14, CA-17, CA-18 | Os mesmos da r1 (ver `r1-test-report.md`), sem mudança de asserção. O CA-17 passou a incluir os 3 testes do CA-19 no subconjunto que ele mede | ✅ |
| CA-15 | `test_ca15_latency_p95_with_the_dummy_model` | ✅ |
| CA-16 | `test_ca16_real_model_latency` (`slow`; pulado sem `QC_REAL_MODEL_DIR`) | ⏸ **pendente** (manual; o modelo real ainda não existe). Não conta como falha. Passos na r1 |
| CA-19 (a) | `test_ca19_a_softmax_unusable_score_is_clamped_to_4`: confere antes que o `Σ i·p_i` bruto do vetor da SPEC passa de 4. Depois exige `screw`, `unusable`, `grade_score == 4.0`, `grade_confidence == 1.0` (igualdade exata), `needs_review` falso, `type_confidence == 0.98` e um `InspectionCreate` aceito | ✅ |
| CA-19 (b) | `test_ca19_b_type_confidence_above_1_is_clamped`: `screw`, `type_confidence == 1.0` exato, `good`, `InspectionCreate` aceito | ✅ |
| CA-19 (c) | `test_ca19_c_grade_confidence_above_1_and_negative_score_are_clamped`: confere que o `grade_score` bruto é negativo, depois `perfect`, `grade_confidence == 1.0` e `grade_score == 0.0` exatos, `InspectionCreate` aceito | ✅ |
| CA-20 | `test_ca20_confident_unusable_output_through_the_route`: confere a pré-condição da §6 (em float32, `p4 == 1.0` e `p3 > 0`, soma bruta > 4). Com o modelo dummy, `POST /api/capture` responde 200 com `grade == "unusable"` e `grade_score == 4.0`, e o sink tem exatamente 1 item com `grade_score == 4.0` e 1 foto em `captures/` | ✅ |
| CA-21 | `test_ca21_symlink_gives_the_name_of_the_target` (`atual → dummy-v1` dá `ModelInfo("dummy-v1", sha)`) e `test_ca21_symlink_to_a_target_with_an_invalid_name` (`atual → Dummy_V1` dá `ModelLoadError`) | ✅ |
| CA-22 | `test_ca22_crop_incompatible_with_a_fixed_input_fails_at_load` (entrada `[N,3,224,224]` com `resize_shorter=288` e `crop=256` dá `ModelLoadError` com `model.onnx` na mensagem) e `test_ca22_dynamic_input_accepts_the_crop` (entrada `[N,3,H,W]`: carrega, e o `infer` de um JPEG 1280×960 dá `screw`/`good`) | ✅ |
| CA-23 | `test_ca23_blank_model_dir_exits_2`: `MODEL_DIR="   "`, `main()` com o espião do `uvicorn.run`, cwd num `tmp_path` sem diretório `"   "`. Resultado: código 2, espião não chamado, `MODEL_DIR` nos registros de log (`caplog`) | ✅ |

### Testes da r1 alterados (SPEC §6)

Os testes são do mesmo arquivo de aceite da SPEC-008, então a regra de SPECs anteriores do `architecture.md` §10 não se aplica. A §6 diz o que fazer com eles. Registro aqui as mudanças.

| Teste da r1 | O que fiz | Motivo |
|---|---|---|
| `test_bug_t01_decision_stays_inside_the_contract[softmax-unusable-score-above-4]` e `[type-confidence-above-1-within-tolerance]` | **Removidos**, substituídos pelo CA-19 (a) e (b). O CA-19 é mais forte: exige os valores limitados exatos e não aceita mais recusar a saída | A SPEC escolheu a opção (a) do SPEC_ISSUE-01. Os testes neutros da r1 (que aceitavam (a) ou (b)) ficaram mais fracos que os CAs. A propriedade geral virou o extra `test_extra_onnxruntime_softmax_outputs_always_fit_the_contract`, descrito abaixo |
| `test_bug_t01_capture_with_a_confident_unusable_output` | **Removido**, substituído pelo CA-20 (200 obrigatório, `grade_score == 4.0` na resposta e no sink, 1 foto) | Idem |
| `test_extra_symlinked_model_dir_uses_the_link_name` (esperava `partqc-link-v2`, o nome do link) | **Reescrito** como `test_extra_symlinked_model_dir_uses_the_target_name`. Ele passa pelo `main()` com `MODEL_DIR=<link partqc-link-v2 → dummy-v1>` e exige `dummy-v1` na inspeção da captura e no `/api/status` | Invalidado de propósito pela §4.2, item 3, e pelo CA-21 (vale o nome do alvo) |
| `test_ca17_decision_coverage_at_least_80` | Acrescentei os 3 nós do CA-19 à lista explícita que ele roda em subprocesso. Ele continua sem rodar diretórios inteiros nem a si mesmo | A lista cobre agora o ramo do limite (§4.1, item 6). A intenção do CA continua a mesma |

## Suíte completa

Ambiente: Python 3.12, `uv`, contêiner `partqc-pg` (Postgres), notebook i3-1115G4.

```text
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
4182 passed, 1 skipped, 1 warning in 234.77s (0:03:54)
SKIPPED: test_ca16_real_model_latency (QC_REAL_MODEL_DIR not set; CA-16 manual)
warning: StarletteDeprecationWarning do fastapi.testclient (já existia)

uv run pytest edge/tests -q --cov=qc_edge.decision --cov=qc_edge.onnx_inferencer
1231 passed, 1 skipped
edge/src/qc_edge/decision.py           92   0  100%
edge/src/qc_edge/onnx_inferencer.py   222   6   97%

uv run ruff check .            -> All checks passed!
uv run ruff format --check .   -> 156 files already formatted
```

O autor relatou 1 failed, 4156 passed e 1 skipped, com a falha no teste que a SPEC invalidou. Conta: 4157 − 88 casos da r1 + 113 casos da r2 = 4182. Os testes de aceite das outras SPECs (007, 010, 025 e as demais) passam sem ajuste.

## Bugs encontrados

Nenhum.

O T-01 da r1 está corrigido. O vetor real de `Softmax` float32 agora gera `grade_score = 4.0`, e a rota responde 200 em vez do 500 não tratado (CA-19 e CA-20).

## Testes exploratórios (além dos critérios)

Os testes novos da r2 estão automatizados como `test_extra_*` e passam. Os extras da r1 continuam passando, exceto o reescrito (ver a tabela acima).

- **Limite às faixas (§4.1, item 6):**
  - `test_extra_clamp_also_applies_to_an_unknown_type_confidence`: com `type_probs=[0, 0, 1.0000009]` (`other`), o resultado é `unknown` com `type_confidence == 1.0`, e o `InspectionCreate` aceita;
  - `test_extra_review_margin_compares_the_raw_type_confidence`: `type_threshold=0.9000005`, então `type_threshold + REVIEW_MARGIN` fica entre 1,0 e o valor bruto 1,0000009. Só a comparação com o valor bruto dá `needs_review=false`, e é o que sai, com `type_confidence == 1.0`. Prova que o limite vem depois da comparação da margem;
  - `test_extra_unusable_threshold_compares_the_raw_probability`: `unusable_threshold=0` e `p4` bruto = −5e-7. O resultado é `perfect`, não `unusable`, então a comparação usa o valor bruto, não o limitado;
  - `test_extra_onnxruntime_softmax_outputs_always_fit_the_contract`: 3000 saídas reais de um nó `Softmax` do `onnxruntime` do lock, em float32, para o tipo (3 classes) e o grau (5), com logits dominantes de margem entre 0 e 25. Todas passam pelo `decide` e pelo `InspectionCreate` sem erro. O teste confirma que a amostra contém casos com `Σ i·p_i` bruto > 4, ou seja, o caso do T-01 aparece de fato.
- **Link simbólico e resolução (§4.2, item 3):**
  - `test_extra_swapping_the_link_changes_the_version`: o link fixo `current` apontado para `partqc-mnv3-v1` e depois para `partqc-mnv3-v2` gera duas versões e dois sha diferentes. A primeira instância continua usando o próprio modelo depois da troca;
  - `test_extra_chain_and_relative_links`: um link relativo, uma cadeia de links (`Chain_Link → rel-link → dummy-v1`, em que o primeiro nome é inválido pela regex) e a barra final dão `dummy-v1`;
  - `test_extra_dot_dot_components_are_resolved`: `dummy-v1/sub/..` e `dummy-v1/../dummy-v1` dão `dummy-v1`;
  - `test_extra_model_dir_that_is_not_a_directory` (link quebrado, link para arquivo, arquivo comum) e `test_extra_link_loop_is_a_load_error` (laço `loop-a ↔ loop-b`): todos dão `ModelLoadError` citando `MODEL_DIR`;
  - à mão: um caminho com byte NUL no construtor dá `ModelLoadError("MODEL_DIR: not a directory")`.
- **`crop` no aquecimento (§4.2, item 7):**
  - `test_extra_fixed_input_of_256_loads_with_crop_256`: entrada fixa `[N,3,256,256]` com `crop=256` carrega e infere `screw`/`good`. Com o aquecimento fixo em 224 da r1, falharia;
  - `test_extra_fixed_input_of_256_fails_at_load_with_the_default_crop`: a mesma entrada com o `crop` padrão (224) dá `ModelLoadError` com `model.onnx`. Na r1, carregava e falhava em todo `infer`;
  - `test_extra_crop_mismatch_exits_2_through_the_cli`: o caso do CA-22 pelo `main()` sai com código 2, sem chamar o `uvicorn.run`, e com `model.onnx` no log.
- **`MODEL_DIR` não aparado (§4.4):**
  - `test_extra_whitespace_model_dir_values_exit_2` com `" "`, `"\t"` e `" \n "`: código 2, `MODEL_DIR` no log;
  - `test_extra_model_dir_with_spaces_around_a_valid_path_is_not_stripped`: um caminho válido com um espaço antes ou depois sai com código 2. É consequência direta de "o valor não é aparado". A dupla deve saber disso ao editar o `.env`;
  - `MODEL_DIR=""` continua subindo sem modelo (extra da r1, `test_extra_without_model_dir_the_edge_starts_without_model`).
- **Observado à mão, sem teste:**
  - com entradas `numpy` float32, os valores devolvidos são `float` do Python (`type_confidence = 0.9800000190734863`), e o `InspectionCreate` aceita;
  - o `README.md` da borda e o `.env.example` descrevem a resolução do link, o valor só com espaços e o `crop` no aquecimento.

## SPEC_ISSUE (se houver)

Nenhum. O SPEC_ISSUE-01 da r1 foi resolvido pela correção da SPEC, reaprovada pelo humano, e a r2 cumpre o texto novo.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
