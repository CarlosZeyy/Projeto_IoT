# SPEC-008 — r2 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-008](../../docs/specs/SPEC-008-edge-inferencia-decisao.md) |
| Rodada | r2 |
| Reviewer | reviewer |
| Diff revisado | `origin/main...1df19b8` (merge-base `6cabd9d`; a `main` local está atrás da `origin/main` e incluiria a SPEC-028, já mergeada) |
| Test report | r2-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante, alto, médio ou baixo. O SPEC_ISSUE-01 e o T-01 da r1 estão resolvidos conforme o texto reaprovado da SPEC. Os 22 CAs automatizáveis têm implementação e teste de aceite que os exercitam. O CA-16 é manual e, pela Definição de pronto, só é registrado quando o modelo real da SPEC-012 existir.

## Achados

Nenhum.

### Verificações pedidas pelo orquestrador

**1. Troca de testes de aceite da própria SPEC-008 (r1 → r2), commit `19074b8` (`Agent: tester`).**

| Teste da r1 | O que mudou | Conferência |
|---|---|---|
| `test_bug_t01_decision_stays_inside_the_contract[softmax-unusable-score-above-4]` e `[type-confidence-above-1-within-tolerance]` | Removidos, substituídos por `test_ca19_a_*` e `test_ca19_b_*` | A §6 diz: "O tester decide se os mantém como extras ou se os troca pelos testes do CA-19 e do CA-20". Os testes novos são **mais fortes** que os antigos: os da r1 aceitavam recusar a saída (`InvalidModelOutputError` → `return`); o CA-19 exige os valores exatos (`grade_score == 4.0`, `type_confidence == 1.0`) e um `InspectionCreate` válido. O `test_ca19_a` também confere a pré-condição (`Σ i·p_i` bruto > 4). Legítimo |
| `test_bug_t01_capture_with_a_confident_unusable_output` | Removido, substituído por `test_ca20_confident_unusable_output_through_the_route` | O teste antigo aceitava 200 **ou** 500 `inference failed`. O CA-20 exige 200, `grade == "unusable"`, `grade_score == 4.0` na resposta e no sink, 1 item no sink e 1 foto. Legítimo e mais forte |
| `test_extra_symlinked_model_dir_uses_the_link_name` | Reescrito como `test_extra_symlinked_model_dir_uses_the_target_name` (pelo `main()`: captura e `/api/status` com `dummy-v1`) | A §6 o declara **invalidado** pela §4.2, item 3, e pelo CA-21, e manda removê-lo ou reescrevê-lo. Registrado no r2-test-report. Legítimo |
| `test_ca17_decision_coverage_at_least_80` | Só acrescentou os 3 nós do CA-19 à lista explícita do subprocesso | A intenção do CA continua a mesma. Continua sem rodar diretório inteiro nem a si mesmo (`architecture.md` §10) |

Nenhum `test_caNN_` foi removido (`grep` das linhas removidas do diff: só `test_bug_t01_*` e o `test_extra_` acima). As 52 funções de teste da r1 viraram 73. O commit toca só `edge/tests/acceptance/test_spec_008.py` e o r2-test-report. Como os testes são do mesmo arquivo de aceite da SPEC, a regra de SPECs anteriores do `architecture.md` §10 não se aplica, como a própria §6 diz. Mesmo assim, o tester registrou a tabela de mudanças. Nenhum teste de aceite de outra SPEC foi tocado (`git diff --stat origin/main...HEAD`: o único arquivo em `tests/acceptance/` é `edge/tests/acceptance/test_spec_008.py`).

**2. R-12 e o `uv.lock`.**

- `edge/pyproject.toml`: `onnx` entra só em `[dependency-groups] dev` do `qc-edge` (commit `57013ba`, `Agent: developer`). O `uv.lock` ganha só a aresta de dev (`[package.dev-dependencies]` e `[package.metadata.requires-dev]`). O `onnx` 1.23.2 já estava no lock pelo extra `train` do `qc-ml`, então nenhum pacote novo foi resolvido.
- `uv lock --check`: OK.
- `uv tree --package qc-api --frozen` e `uv tree --package qc-dashboard --frozen`: nenhum `onnx`, `onnxruntime`, `torch` ou `timm`. `tests/test_dependency_isolation.py` está verde na suíte.
- O CI roda `uv sync --all-packages --frozen` (`.github/workflows`, linha 44). `uv export --all-packages --frozen` mostra `onnx==1.23.2` e nenhum torch, e `uv sync --all-packages --frozen --dry-run` no venv local dá "Would make no changes". Portanto, o venv em que rodei a suíte é o mesmo do CI, e o CI terá o `onnx` para o helper dos testes sem trazer torch.
- O `onnxruntime` do `qc-edge` já existia (SPEC-007/ADR-014), e o código de produção não importa `onnx`: só `edge/tests/dummy_model.py` e o arquivo de aceite.

**3. R-07 pelos trailers `Agent:`.** Os 18 commits de `6cabd9d..HEAD` têm `Refs: SPEC-008` e `Agent:`. Cruzei cada um com os arquivos tocados (`git show --stat`):

| Papel | Commits | Arquivos |
|---|---|---|
| developer | `57013ba`, `bd42973`, `d27a0f7`, `2ce2629`, `2da8506`, `241bbec`, `e943e9e`, `c8e12ec`, `d82ef2b` | `edge/src/**`, `edge/tests/` fora de `acceptance/`, `edge/pyproject.toml`, `uv.lock`, `.env.example`, `edge/README.md` e os dev-reports. Nenhum arquivo em `tests/acceptance/` |
| tester | `16c7f2c`, `19074b8` | Só `edge/tests/acceptance/test_spec_008.py` e os test-reports. Nenhum código de produção |
| architect (commit feito pelo orquestrador, porque o architect não tem shell) | `eb35361` | Só `docs/specs/SPEC-008-*.md`, `docs/architecture.md` (§6.2 passo 4 e §7) e `docs/plan.md` |
| orchestrator | `d56ab75`, `bc9be98`, `169d6e8`, `d8cf29d`, `8c53c20`, `1df19b8` | Só status em `docs/plan.md` e na SPEC (e a marcação de `Done` da SPEC-028 no primeiro commit da branch, como manda o `CLAUDE.md`). O `d8cf29d` registra a reaprovação humana no Histórico, sem mudar o conteúdo da SPEC |

Ninguém cruzou a fronteira. A identidade de todos os commits é `Carlos Moises <179777237+CarlosZeyy@users.noreply.github.com>` (R-13).

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Ver "Rastreabilidade" abaixo. Nada fora do escopo da §3.1. Nenhum CA alterado pelo autor; as mudanças de SPEC vieram do architect, com a reaprovação humana registrada no Histórico (R-08). As decisões do autor da r1 (chaves exatas nos JSONs, `overrides` por nome da variável ou do limiar, bytes do modelo lidos uma vez para evitar TOCTOU) estão no r1-dev-report e não contrariam a SPEC. A mais restritiva, recusar chave desconhecida no `decision.json` e no `labels.json`, é compatível com a SPEC-012 (linhas 65, 85 e 158: "exatamente" as 3 chaves) e com o `architecture.md` §7 |
| 2. Regras inegociáveis | ✅ | R-01: `onnx` é Apache-2.0 e só de dev. R-02: nada sai da LAN (o sink continua `InMemorySink`). R-03: busca no diff por `key`, `secret`, `token`, `password`, `postgres://`, `eyJ`, `PRIVATE`: só nomes de variáveis e o `postgresql://postgres@localhost` sem senha do comando de teste; `.env.example` sem variável nova, só comentários atualizados. R-04: nenhuma mudança em `packages/contracts`; a borda passou a respeitar as faixas que o contrato 0.3.0 já define. R-05 e R-06: sem mudança (o `--stub-model` continua sem publicar). R-07: ver acima. R-11: N/A (sem treino). R-12: ver acima. R-13: ✅ |
| 3. Corretude | ✅ | `decide` (`edge/src/qc_edge/decision.py:123-173`) compara sempre os valores brutos e só limita no `return` (linhas 165-172), exatamente como a §4.1, item 6. Os casos `max(0.0, -0.0)` e `-5e-7` dão `0.0`. A resolução do `MODEL_DIR` (`onnx_inferencer.py:234-245`) cobre caminho inexistente, link quebrado, laço (`RuntimeError`) e byte NUL (`ValueError`), sempre com `ModelLoadError` citando `MODEL_DIR` e sem ecoar o caminho. A ordem da construção (`onnx_inferencer.py:327-357`) segue a §4.2: resolução, arquivos, integridade, nome, labels, preprocessing, limiares, sessão. O `re.fullmatch` com `^...$` recusa nome com `\n` final. O aquecimento usa `[1, 3, crop, crop]` (`onnx_inferencer.py:277-282`). O `MODEL_DIR` não é aparado (`Path("   ")` não é diretório → código 2). `infer` é seguro entre threads (sessão do `onnxruntime` e estado imutável). Erros do `onnxruntime` viram `ModelLoadError` na carga e `InferenceError` no `infer`, sem `except: pass` |
| 4. Testes | ✅ | r2-test-report PASS, com todos os CAs automatizáveis cobertos. Os testes não são tautológicos: o CA-19 e o CA-20 conferem que o caso bruto realmente passa da faixa antes de verificar o limite, e os extras `test_extra_review_margin_compares_the_raw_type_confidence` e `test_extra_unusable_threshold_compares_the_raw_probability` falhariam se o limite viesse antes das comparações. O modelo dummy do tester é próprio (§6) e sem torch. Nenhuma rede externa. Cobertura de `qc_edge.decision`: 100%. O CA-17 roda o pytest em subprocesso só com caminhos explícitos, sem banco. Sem credencial literal em URL |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos (156 arquivos). Type hints nas funções públicas, sem `print`, sem duplicação de `qc_contracts` (usa `GRADE_ORDER`, `MODEL_VERSION_PATTERN`, `ObjectType`) nem de `qc_preprocess` (`PreprocessParams.from_json`, `preprocess`). `edge/README.md` e `.env.example` descrevem o link simbólico, o `MODEL_DIR` só com espaços, os limiares e a seção "Trocar o modelo" |
| 6. Segurança | N/A | A SPEC não tem tag `security` |

### Rastreabilidade (CAs novos da r2)

| CA | Implementação | Teste de aceite (tester) | Teste do autor |
|---|---|---|---|
| CA-19 (a), (b), (c) | `decision.py:118-120`, `:165-172` | `test_ca19_a_*`, `test_ca19_b_*`, `test_ca19_c_*` (`test_spec_008.py:1208-1241`) | `test_decision.py` (vetores do CA, numpy float32, `InspectionCreate`) |
| CA-20 | `decision.py`; rota da SPEC-007 sem mudança | `test_ca20_confident_unusable_output_through_the_route` (`:1247`) | `test_model_integration.py::test_confident_unusable_softmax_output_is_stored_with_score_4` |
| CA-21 | `onnx_inferencer.py:234-257`, `:329` | `test_ca21_symlink_gives_the_name_of_the_target` e `test_ca21_symlink_to_a_target_with_an_invalid_name` (`:1274-1291`) | `test_onnx_inferencer.py` (cadeia, link relativo, `..`, leitura do diretório resolvido) |
| CA-22 | `onnx_inferencer.py:260-291`, `:350` | `test_ca22_crop_incompatible_with_a_fixed_input_fails_at_load` e `test_ca22_dynamic_input_accepts_the_crop` (`:1306-1322`) | `test_onnx_inferencer.py` (espião confere `(1, 3, 256, 256)` no aquecimento) |
| CA-23 | `config.py` (`MODEL_DIR: Path \| None`, só `""` é ignorado) e `cli.py:107-124` | `test_ca23_blank_model_dir_exits_2` (`:1328`, com `chdir` para um `tmp_path` sem diretório `"   "`) | `test_model_integration.py::test_blank_model_dir_is_not_stripped_and_exits_2` |

CA-01 a CA-18 não mudaram na r2 e continuam com os mesmos testes da r1, todos passando.

### Execuções do reviewer (read-only)

```text
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q -p no:cacheprovider
4182 passed, 1 skipped, 1 warning in 245.22s
SKIPPED: edge/tests/acceptance/test_spec_008.py:765 (QC_REAL_MODEL_DIR not set; CA-16 manual)
warning: StarletteDeprecationWarning do fastapi.testclient (já existia)

uv run ruff check .            -> All checks passed!
uv run ruff format --check .   -> 156 files already formatted
uv lock --check                -> OK
uv tree --package qc-api / qc-dashboard --frozen  -> sem onnx, onnxruntime, torch ou timm
uv sync --all-packages --frozen --dry-run         -> Would make no changes
```

### Observações para o orquestrador (não são achados)

- **CI ainda não rodou na r2.** A branch remota `origin/spec/SPEC-008-edge-inferencia-decisao` está em `eb35361` (o commit do architect). Os commits da r2 (`d8cf29d` em diante) ainda não foram enviados. O portão R-09 exige os checks do PR verdes depois do push.
- **CA-16 (manual):** fica pendente até o modelo real da SPEC-012. A Definição de pronto diz "CA-16 registrado quando o modelo real existir", então não impede o merge desta rodada. Os passos estão no r1-test-report.
- **`main` local desatualizada:** `git diff main...HEAD` mostra também a SPEC-028, já mergeada no PR #26. Revisei contra a `origin/main` (merge-base `6cabd9d`).

## Pontos positivos

- O limite às faixas do contrato foi implementado no único ponto certo (o `return` de `decide`), com comentário que cita a §4.1, item 6, e com testes que provam que as comparações usam os valores brutos.
- A integridade do modelo é conferida sobre os mesmos bytes entregues ao `onnxruntime` (sem TOCTOU), e todas as mensagens de carga citam o arquivo ou `MODEL_DIR`, nunca o caminho completo.
- O tester reescreveu os testes da r1 com asserções mais fortes que as originais e acrescentou um teste de propriedade com 3000 saídas reais de `Softmax` do `onnxruntime` travado, que confirma que o caso do T-01 aparece na amostra e é tratado.
- A separação de papéis está limpa em todos os 18 commits.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
