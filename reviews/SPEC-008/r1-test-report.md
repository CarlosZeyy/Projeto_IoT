# SPEC-008 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-008](../../docs/specs/SPEC-008-edge-inferencia-decisao.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `bc9be98` (implementação do developer; o commit do tester só acrescenta `edge/tests/acceptance/test_spec_008.py` e este relatório) |
| **Veredicto** | **FAIL** |

Motivo do FAIL: os 17 critérios automatizáveis (CA-01 a CA-15, CA-17 e CA-18) têm teste e todos passam. O CA-16 é manual e fica pendente, porque o modelo real ainda não existe. Mas a suíte inteira termina com **3 falhas**, todas nos testes `test_bug_t01_*`. Eles reproduzem o T-01: uma saída de modelo que a §4.1, item 1, aceita gera um `grade_score` acima de 4 (ou uma confiança acima de 1). O `InspectionCreate` recusa esses valores, e a rota responde com um 500 não tratado. A correção exige uma decisão que a SPEC não tomou, por isso também abri o **SPEC_ISSUE-01**.

Escrevi os testes a partir da SPEC, antes de ler a implementação. O modelo dummy é meu (`build_dummy_onnx`, §6: `ReduceMean` → `Reshape [N,1]` → `Mul` por 0 → `Add` de constantes, opset 17, `ir_version` 8). Não usei o helper do autor. As imagens são sintéticas e geradas em memória (gradiente com ruído, sem pessoas, R-14). Depois de ler o código, só corrigi dois defeitos meus: o `PreprocessParams.to_json(path)` grava em arquivo e não devolve string, e uma asserção errada no CA-17 casava com o nome do `tmp_path`. Também acrescentei testes exploratórios e os `test_bug_t01_*`.

## Cobertura dos critérios de aceite

Arquivo: `edge/tests/acceptance/test_spec_008.py`. Ele tem 26 funções `test_caNN_*`, 24 `test_extra_*` e 2 `test_bug_t01_*`, ou **88 casos** depois da parametrização: 84 passam, 3 falham (T-01) e 1 é pulado (CA-16).

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_other_type_is_unknown_without_review` | ✅ |
| CA-02 | `test_ca02_low_type_confidence_is_unknown_and_needs_review` | ✅ |
| CA-03 | `test_ca03_type_threshold_is_strict` | ✅ |
| CA-04 | `test_ca04_review_margin_boundary_and_grade_score` (`grade_score` = 1,6 ± 1e-9) | ✅ |
| CA-05 | `test_ca05_unusable_threshold_is_inclusive` (0,4 → `unusable`; 0,39 → `perfect`) | ✅ |
| CA-06 | `test_ca06_grade_review_threshold` (0,6 → `false`; 0,59 → `true`) | ✅ |
| CA-07 | `test_ca07_invalid_outputs_raise` (6 casos: soma 1,5, `NaN` no tipo e no grau, negativo no tipo e no grau, 4 graus; e `InvalidModelOutputError` ⊂ `InferenceError`) | ✅ |
| CA-08 | `test_ca08_infer_with_the_dummy_model` (JPEG 1280×960 → `screw`/`good`, `latency_ms` inteiro ≥ 0, `ModelInfo("dummy-v1", sha)`), `test_ca08_capture_route_with_the_dummy_model` (`POST /api/capture`: item no sink com `model_version="dummy-v1"` e o sha) e `test_ca08_cli_loads_model_dir` (o mesmo caminho subindo pelo `main()` com `MODEL_DIR`) | ✅ |
| CA-09 | `test_ca09_hash_mismatch_raises_integrity_error` (12 caracteres do esperado e do obtido; `ModelIntegrityError` ⊂ `ModelLoadError`), `test_ca09_cli_exits_2_on_hash_mismatch` (`main()` → 2, `uvicorn.run` não chamado) e `test_ca09_real_process_exits_2` (processo real `qc-edge`, não a suíte: código 2) | ✅ |
| CA-10 | `test_ca10_invalid_labels` (`pliers`, `unknown`, graus trocados no início e no fim) | ✅ |
| CA-11 | `test_ca11_missing_decision_json` e `test_ca11_decision_threshold_out_of_range` (`type_threshold=1.2`); as duas mensagens citam `decision.json` | ✅ |
| CA-12 | `test_ca12_env_override_wins` (0,7 → 0,55, origem `env`; os outros dois continuam `decision.json`), `test_ca12_env_override_through_the_cli` (`TYPE_THRESHOLD=0.55` no ambiente → `/api/status`) e `test_ca12_invalid_env_threshold_exits_2[1.5\|abc]` (código 2, log com `TYPE_THRESHOLD`) | ✅ |
| CA-13 | `test_ca13_type_output_shape_mismatch` (`[N,4]` com 3 rótulos) e `test_ca13_input_not_named_image` | ✅ |
| CA-14 | `test_ca14_invalid_model_output_is_500_and_nothing_stored` (500 `{"detail": "inference failed"}`, sink vazio, `captures/` vazio) | ✅ |
| CA-15 | `test_ca15_latency_p95_with_the_dummy_model` (50 execuções, p95 por posto mais próximo) | ✅ (aqui: p50 = 5 ms, p95 = 5 ms) |
| CA-16 | `test_ca16_real_model_latency` (`slow`; pulado sem `QC_REAL_MODEL_DIR`) | ⏸ **pendente** (manual; o modelo real da SPEC-012 ainda não existe). Não conta como falha |
| CA-17 | `test_ca17_decision_coverage_at_least_80` | ✅ (ver abaixo) |
| CA-18 | `test_ca18_console_and_status_show_model_and_thresholds` (via `main()` com `MODEL_DIR` e `GRADE_REVIEW_THRESHOLD=0.65`: `/api/status` com `model.thresholds` exato; console com versão, 12 caracteres do sha, os três nomes, os valores e as origens `decision.json` e `env`) | ✅ |

### Notas sobre os CAs

- **CA-16 (manual):**
  - Passos para a dupla: `QC_REAL_MODEL_DIR=ml/models/<model_version> uv run pytest -m slow edge/tests/acceptance/test_spec_008.py -s`.
  - O teste faz 1 aquecimento, roda `infer` 50 vezes e exige p95 ≤ 300 ms.
  - Ele imprime p50, p95, o número de imagens e a CPU no stderr (e em `record_property`). Registrar esses valores no test-report da rodada em que o modelo existir.
  - Imagens: o teste usa as fotos de `edge/tests/fixtures/` (`.jpg`, `.jpeg` ou `.png`) quando a pasta existe. Ela ainda não existe e fica fora da área de escrita do tester (R-07). Sem ela, o teste usa 5 JPEGs sintéticos de 1280×960 gerados em memória. Para a latência, o conteúdo pouco importa, porque o pré-processamento sempre reduz a imagem para 224×224. Se a dupla quiser medir com fotos de peças, basta copiar algumas para `edge/tests/fixtures/` no notebook da demo, sem pessoas (R-14) e sem commitar, se forem reais (`architecture.md` §7).
- **CA-17:** pela regra de `architecture.md` §10, o teste não roda nenhum diretório inteiro. Ele roda o pytest em subprocesso só com caminhos explícitos: `edge/tests/test_decision.py` e os 7 nós CA-01 a CA-07 deste arquivo. Ele nunca roda a si mesmo nem outro teste que chame o pytest. Exige então ≥ 80% de `qc_edge/decision.py` no JSON do `pytest-cov`. Esse subconjunto dá um limite inferior da cobertura das duas suítes completas. Medições feitas à mão:
  - `uv run pytest edge/tests --cov=qc_edge.decision --cov=qc_edge.onnx_inferencer`, com as suítes do autor e de aceite: `decision.py` 89 statements, 0 faltando, **100%**; `onnx_inferencer.py` 97%;
  - só os CAs de decisão deste arquivo (`-k ca0`): 93%.

## Suíte completa

Ambiente: Python 3.12.15, `uv`, contêiner `partqc-pg` (Postgres), notebook i3-1115G4 de 4 núcleos.

```text
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
3 failed, 4125 passed, 1 skipped, 1 warning in 233.94s (0:03:53)
FAILED edge/tests/acceptance/test_spec_008.py::test_bug_t01_decision_stays_inside_the_contract[softmax-unusable-score-above-4]
FAILED edge/tests/acceptance/test_spec_008.py::test_bug_t01_decision_stays_inside_the_contract[type-confidence-above-1-within-tolerance]
FAILED edge/tests/acceptance/test_spec_008.py::test_bug_t01_capture_with_a_confident_unusable_output
SKIPPED: test_ca16_real_model_latency (QC_REAL_MODEL_DIR not set)
warning: StarletteDeprecationWarning do fastapi.testclient (já existia)

uv run pytest edge/tests -q --cov=qc_edge.decision --cov=qc_edge.onnx_inferencer
3 failed, 1174 passed, 1 skipped
edge/src/qc_edge/decision.py          89   0  100%
edge/src/qc_edge/onnx_inferencer.py  218   6   97%

uv run ruff check .            -> All checks passed!
uv run ruff format --check .   -> 156 files already formatted
```

O autor relatou 4041 passed. A diferença são os meus 88 casos: +84 passed, +3 failed e +1 skipped. Os testes de aceite das SPECs anteriores (007, 010 e 025, entre outras) passam **sem ajuste**, então não há tabela de ajustes da §10.

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | média | §4.1 (itens 1 e 4) × contrato (`GradeScore` ≤ 4, `Probability` ≤ 1) × SPEC-007 §4.5. Nenhum CA. Ver SPEC_ISSUE-01 | 1. Diretório de modelo dummy com `type_probs=[0.98, 0.01, 0.01]` e `grade_probs=[2.506e-10, 2.235e-10, 7.39e-11, 5.899e-08, 1.0]`. Esse vetor é a saída real de um nó `Softmax` do `onnxruntime` 1.31.0 do lock, em float32, para um grau `unusable` muito confiante. 2. `create_app(EdgeSettings(), OnnxInferencer(dir), InMemorySink())`. 3. `POST /api/capture` com uma foto válida. Atalho: `decide([0.98, 0.01, 0.01], <vetor acima>, labels, thresholds)` | A §4.1, item 1, aceita a saída: valores em [0, 1] e soma 1 ± 1e-3. Portanto ou a inspeção sai válida (200, `unusable`), ou, se a SPEC decidir recusar, sai 500 `{"detail": "inference failed"}` como `InvalidModelOutputError`. Nunca um 500 não tratado | `decide` devolve `grade_score = 4.000000177` (`Σ i·p_i` sem limite). O `InspectionCreate` levanta `ValidationError` (`grade_score: less than or equal to 4`). A rota responde **500 `{"detail": "internal server error"}`**, com stack trace no log e nada salvo. O mesmo ocorre com `type_probs=[1.0000009, 0, 0]`, que a tolerância de 1e-6 aceita: `type_confidence > 1`. Testes que reproduzem: `test_bug_t01_decision_stays_inside_the_contract[...]` (2 casos) e `test_bug_t01_capture_with_a_confident_unusable_output`. Os dois são neutros quanto à correção: passam se `decide` recusar a saída ou se devolver valores dentro do contrato |

**Por que a severidade é média e não baixa:** o vetor não é artificial.

- Num lote de 50 000 linhas de `Softmax` do `onnxruntime` com o logit de `unusable` dominante (margem de 10 a 25), **17 110** linhas (34%) dão `Σ i·p_i > 4`. O motivo é o arredondamento: `p4` vira exatamente `1.0` em float32 enquanto `p3` continua ~6e-8.
- O `type_probs` não passou de 1 em 200 000 linhas, e a confiança acima de 1 só aparece com valores feitos à mão.
- O caso atinge justamente a peça claramente inutilizável, a classe cujo recall a decisão favorece (`architecture.md` §6.2).
- Atenuante: o label smoothing de 0,1 do ADR-005 tende a limitar a confiança do modelo treinado. Por isso a frequência real depende do modelo da SPEC-012.

## Testes exploratórios (além dos critérios)

Todos estão automatizados como `test_extra_*` e passam, salvo indicação.

- **Decisão:**
  - empate no argmax vai para o menor índice, no tipo e no grau;
  - tolerâncias: somas 1,0005 e 0,9995 aceitas, 1,002 e 0,998 recusadas, `1 + 5e-7` aceito, `inf` e 2 tipos para 3 rótulos recusados;
  - entradas `numpy` (float32 e float64) aceitas;
  - `Decision` e `Thresholds` imutáveis (`FrozenInstanceError`).
- **Resultado `unknown` pela rota:** 200, `grade=null`, `approved=null`, e o `InspectionCreate` aceita.
- **`model.sha256`:**
  - formatos aceitos: só o hash, maiúsculas com nome do arquivo, `*model.onnx` (modo binário) e espaço inicial. `model_sha256` sai sempre em minúsculas;
  - arquivo vazio → `ModelLoadError` citando `model.sha256`;
  - um byte trocado no fim do `model.onnx` → `ModelIntegrityError`.
- **Arquivos e versão:**
  - cada um dos 4 outros arquivos ausente → `ModelLoadError` com o nome do arquivo;
  - `model_version` inválido (`Dummy-V1`, `ab`, `dummy_v1`, `modelo-ç1`, 41 caracteres) → `ModelLoadError`;
  - barra final no caminho aceita;
  - link simbólico: vale o nome do link (`partqc-link-v2`), não o do alvo. É coerente com "o nome do diretório é o `model_version`", mas a dupla deve saber disso ao trocar o modelo por link.
- **Conteúdo inválido:**
  - `.onnx` corrompido com hash correto → `ModelLoadError`;
  - `preprocessing.json` inválido → `ModelLoadError` citando o arquivo;
  - `decision.json` sem chave, negativo, string, `NaN` ou `null` → `ModelLoadError` citando o arquivo. Os limites 0 e 1 são aceitos;
  - saída `grade_probs` com 4 graus ou com nome errado → `ModelLoadError`.
- **Concorrência:** 8 threads × 5 `infer`, sem erro e com resultados corretos.
- **Imagens de 1×1, 224×224 e 3000×300 direto no `infer`:** funcionam.
- **Integração (`main()`):**
  - `MODEL_DIR=""` → sobe sem modelo, captura 503 `model not loaded`, `/api/status` com `loaded=false`;
  - `MODEL_DIR` inexistente → código 2;
  - `--stub-model` com `MODEL_DIR` → `stub-v0` e um aviso no log.
- **Limiares por env:**
  - `" 0.55 "`, `1e-1`, `0` e `1` aceitos;
  - `0,55` (vírgula), `nan`, `-0.01` e `inf` → código 2 citando a variável.
- **Observados à mão, sem teste:**
  - `MODEL_DIR="   "` (só espaços) → código 2 (`not a directory`). A §4.4 só fala em "ausente ou vazio". Sair com erro é defensável, mas é um caso de borda que a SPEC não cita;
  - `TYPE_THRESHOLD=""` → ignorado (origem `decision.json`);
  - `UNUSABLE_THRESHOLD=1.5` sem `MODEL_DIR` → código 2;
  - chave de override desconhecida ou valor 2 no construtor → `ModelLoadError` citando a variável.
- **Observação do autor sobre o `crop`:** confirmada pela leitura. O aquecimento usa `[1,3,224,224]` fixo, então um `preprocessing.json` com `crop≠224` passaria na carga e falharia em todo `infer`. Não é defeito contra a SPEC.

## SPEC_ISSUE (se houver)

- **SPEC_ISSUE-01 (§4.1, itens 1 e 4, × contrato `qc-contracts` 0.3.0):**
  - A §4.1 aceita saídas com tolerância (valores em `[0, 1]` ± 1e-6 e soma 1 ± 1e-3). Ela manda calcular `grade_score = Σ i·grade_probs[i]` e usar `type_confidence`/`grade_confidence` como vêm, sem arredondar (§7). Com essas regras, saídas aceitas geram `grade_score > 4` (caso real de `Softmax` float32, T-01) ou confiança `> 1`. O contrato recusa os dois (`GradeScore` ≤ 4, `Probability` ≤ 1). A SPEC não diz o que fazer e cita só a revalidação pelo `InspectionCreate` (§7), que hoje vira um 500 não tratado.
  - Decisão pedida ao architect: (a) limitar os valores ao intervalo do contrato depois das comparações (`grade_score` em `[0, 4]`, confianças em `[0, 1]`); ou (b) tratar a saída como `InvalidModelOutputError` (500 `inference failed`), o que faria peças claramente inutilizáveis falharem; ou (c) outra regra.
  - Os testes `test_bug_t01_*` aceitam (a) e (b) e não precisam mudar com a decisão.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
