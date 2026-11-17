# SPEC-045 — Operação (§4.7, passo 7): `partqc-mnv3-v2` — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-045](../../docs/specs/SPEC-045-treino-com-fotos-dos-colegas.md) |
| Rodada | operação, segundo modelo oficial (§4.7, passo 7; mesmos critérios do CA-16 do [r1](r1-operacao-test-report.md)) |
| Tester | tester |
| Commit testado | `79b95c2` (branch `ml/partqc-mnv3-v2`, commits `319b8f9` e `79b95c2` do ml-engineer, sobre `main` `234226d`) |
| Ambiente | worktree `.claude/worktrees/ml-v2`, sem torch (só onnxruntime) |
| **Veredicto** | **FAIL**: o `split_v2`, o `metrics.json`, os arquivos e a paridade passam. A entrada do v2 no CHANGELOG tem 2 achados de baixa severidade: falta 1 das 8 limitações da decisão 7 e 3 números de validação estão arredondados a favor |

Nenhum agente abriu foto nesta conferência. Tudo foi feito sobre CSV e JSON, o `model.onnx` (só hash e paridade), o `parity_fixture.npz` (só chaves e formatos) e as CLIs do projeto. O manifest `ml/data/manifest.csv` não existe no worktree. Ele foi **lido**, sem nenhuma escrita, na pasta principal, para checar o hash e o `item_id`. Este relatório traz só contagens, `item_id` e hashes.

O FAIL vale só para o texto do CHANGELOG. Nenhum achado afeta o modelo, o split ou as métricas, nem a aprovação do humano por teste ao vivo. A correção é de documentação, no próprio `ml/models/CHANGELOG.md`, sem treinar de novo.

## Resumo

| Bloco | Resultado |
|---|---|
| `split_v2` | ✅ PASS |
| `metrics.json` do v2 | ✅ PASS |
| Entrada do v2 no `ml/models/CHANGELOG.md` | ❌ FAIL (BUG-01 e BUG-02, ambos de baixa severidade) |
| Arquivos (sha256, nada de `.onnx`/`.pt` versionado, paridade) | ✅ PASS |
| `ruff check` e testes relevantes de `ml/tests` | ✅ PASS |

## `split_v2`

Checagem por CSV de `ml/splits/split_v1.csv` × `ml/splits/split_v2.csv`, mais o código do projeto (`qc_ml.split`) sobre o manifest.

| # | Conferência | Obtido | Resultado |
|---|---|---|---|
| 1 | Linhas `val` do v2 × v1 | 29 × 29, idênticas e na mesma ordem (`image_path` e `split`) | PASS |
| 2 | Linhas `test` do v2 × v1 | 30 × 30, idênticas e na mesma ordem | PASS |
| 3 | Linhas do v1 que mudaram de split no v2 | 0 de 223; as 223 aparecem no v2 na mesma ordem relativa | PASS |
| 4 | Linhas novas | 19, todas `train`: `S-001` `screw/poor` 9, `S-002` `screw/good` 5 e `S-003` `screw/perfect` 5. Nenhum desses `item_id` existe no v1 | PASS |
| 5 | Nas 19 linhas novas do manifest | mesmos `item_id`, tipo e grau; `labeler` `a` | PASS |
| 6 | `item_id` em mais de um split, pelo prefixo do nome do arquivo | nenhum | PASS |
| 7 | `item_id` em mais de um split, pelo `item_id` do manifest | nenhum, nas 117 peças | PASS |
| 8 | `qc_ml.split.check_item_integrity(df, assign_splits(df, load_split("ml/splits/split_v2.csv")))` (ADR-014, código do projeto) | sem `SplitIntegrityError`; 0 linhas sem split | PASS |
| 9 | Manifest × split | 242 × 242 linhas, mesmo conjunto de imagens, 0 repetidas; nenhum `item_id` com dois tipos; prefixo do arquivo = `item_id` nas 242 | PASS |
| 10 | Peças e imagens por split | train 87/183, val 15/29, test 15/30 (igual ao `split_v2.json`) | PASS |
| 11 | `split_v2.sha256` × SHA-256 do CSV | `0437dbc0…f440` nos dois; `load_split` também confere | PASS |
| 12 | `split_v2.json` | `parent` `split_v1`, seed 42, 0 imagens externas, `deferred_types: []`, 3 avisos `small_stratum` só com `scope: new_items` (os 3 parafusos novos) | PASS |
| 13 | `manifest_sha256` do `split_v2.json` × manifest lido | `598991b5…878d` nos dois. É o mesmo do `metrics.json`, do `training_config.json`, do `thresholds_report.json` e do CHANGELOG | PASS |

## `metrics.json` do v2

| # | Conferência | Obtido | Resultado |
|---|---|---|---|
| 1 | `labels` do `metrics.json` × `labels.json` | iguais: 12 tipos, 5 graus, 10 sem grau. O `labels.json` e o `preprocessing.json` são idênticos aos do v1 | PASS |
| 2 | `type_confusion` completa (R-11) | 12 × 12, 30 imagens. Uma linha e uma coluna por tipo do `labels.json`. As linhas sem suporte no teste (`allen_key`, `saw`, `drill`, `cordless_screwdriver` e `spirit_level`) aparecem com zeros; nenhum tipo foi omitido | PASS |
| 3 | Coerência interna | diagonal 18/30 = `type_accuracy` 0,6. Pela `grade_confusion`: `defective_recall` 2/3, `defective_precision` 2/3 e `grade_off_by_one_accuracy` 5/10, todos iguais ao JSON | PASS |
| 4 | IC por bootstrap | `grade_qwk_ci95` [-0,03711; 0,79612], `unusable_recall_ci95` [0,0; 0,0], `defective_recall_ci95` [0,0; 1,0] | PASS |
| 5 | `warnings` | 15 avisos: 2 de bootstrap indefinido (347 e 11 de 1000), 3 de grau com 1 peça no teste e 10 `few test items` | PASS |
| 6 | Latência | `latency_machine: "notebook-borda"`, p50 19,5088 ms, p95 28,2480 ms, `latency_runs` 100 | PASS |
| 7 | Rastreabilidade | `model_version` `partqc-mnv3-v2`, `split_file` `split_v2.csv`, `split_sha256` e `model_sha256` iguais aos dos arquivos | PASS |
| 8 | Teste sem foto do humano | `counts.val.by_origin.capture` = 0 e `counts.test.by_origin.capture` = 0; `counts.train.by_origin.capture` = 19 | PASS |
| 9 | `counts.val` e `counts.test` | idênticos aos do `metrics.json` do v1 | PASS |

## Entrada do v2 no `ml/models/CHANGELOG.md` (linhas 108 a 215)

| # | Conferência | Obtido | Resultado |
|---|---|---|---|
| 1 | Cabeçalho e tabela × gerador | `qc_ml.report changelog --model-dir ml/models/partqc-mnv3-v2 --previous ml/models/partqc-mnv3-v1` foi gerado de novo no scratchpad. As linhas de hashes e limiares e a tabela (com a coluna do v1) são **idênticas** às do CHANGELOG | PASS |
| 2 | Tabela sem arredondar a favor | vem do gerador, que segue o `docs/architecture.md` §7. Exemplos: `grade_qwk` 0,390862 → 0,3908; IC [-0,0372; 0,7962], alargado; `latency_ms_p95` 28,24796 → 28,2480 | PASS |
| 3 | Status pelo valor bruto | só `latency_ms_p95` está `atingida`. `defective_recall` 0,667 < 0,90 fica `abaixo da meta` | PASS |
| 4 | Peças de teste junto de cada métrica `atingida` | `latency_ms_p95`: "30 imagens das 15 peças", 100 medições. A queda do `defective_recall` (atingida no v1) está explicada com "3 peças defeituosas (2 `poor` e 1 `unusable`, 3 imagens) entre os 7 parafusos (10 imagens)". As métricas abaixo da meta também trazem o escopo | PASS |
| 5 | Comparação com o v1 | seção própria: val e teste idênticos, diferenças dentro dos IC, nenhuma conclusão de "melhor" ou "pior". Conferido contra os dois `metrics.json`: 18 × 17 acertos em 30; 5 × 7 em 10; 8 × 2 ferramentas previstas como `screw` (4 `pliers`, 3 `phillips_screwdriver` e 1 `wrench` × 1 `pliers` e 1 `wrench`); 6 × 0 previsões de `saw`; 1 `phillips_screwdriver` prevista como `drill`; `other` 3/3 × 2/3; peça `fair` com 3 de 4 imagens previstas `perfect` no v2 e `poor` no v1; treino 84 → 87 peças e 164 → 183 imagens (parafusos 33 → 36 e 62 → 81) | PASS |
| 6 | Escolha do humano por teste ao vivo | "A escolha do v2 foi do humano, por teste ao vivo na borda (17/11/2026) … Não foi uma escolha por métrica". Inclui a limitação "A escolha por teste ao vivo não é reprodutível nem medida" | PASS |
| 7 | Nenhuma métrica mede o fundo, a luz e o celular do humano | item próprio em "Novas no v2", com a referência a `counts.*.by_origin.capture` = 0 (conferido no item 8 do `metrics.json`) | PASS |
| 8 | Limitações da decisão 7 do ADR-025 | 7 dos 8 itens estão na lista. **Falta o item 8**, sobre o domínio de captura dos colegas (BUG-01) | **FAIL** |
| 9 | Números do texto × artefatos, sem arredondar a favor | `training_config.json` e `thresholds_report.json` conferidos: melhor época 12 de 17 (early stopping com `patience` 5), 24 e 17 imagens de validação, 0,8824 e 0,1765 (arredondados para cima: corretos), `unusable_threshold` 0,95. **3 números de validação estão arredondados a favor** (BUG-02) | **FAIL** |
| 10 | `warnings` em "Problemas conhecidos" | os 15 avisos do `metrics.json`, literais | PASS |
| 11 | Configuração e código | `ml/configs/partqc-mnv3-v2.json` só muda `model_version` e `split_file` em relação ao v1. O `git_commit` do `training_config.json` é `8d07355`. `git diff 8d07355 main -- ml/src packages/preprocess` não mostra nada, e a branch não muda código | PASS |

## Arquivos

| # | Conferência | Obtido | Resultado |
|---|---|---|---|
| 1 | sha256 do `model.onnx` local | `2ed32f21a69c70b65287df3b347648e55c9c91f67e0c006a927251064ca27803` | PASS |
| 2 | × `model.sha256` | igual; formato `^[0-9a-f]{64}\n$` (65 bytes) | PASS |
| 3 | × `release-notes.md`, `metrics.json`, `thresholds_report.json` e CHANGELOG | igual nos quatro. O `parity_fixture.npz` guarda o mesmo `model_sha256` | PASS |
| 4 | `release-notes.md` × gerador | `qc_ml.report release-notes --model-dir ml/models/partqc-mnv3-v2 --output <scratchpad>` produz um arquivo idêntico | PASS |
| 5 | Nenhum `.onnx` real nem `.pt` versionado | `git ls-files` não traz `.pt`, `.pth` nem `.ckpt`. Os únicos `.onnx` são as 4 fixtures de `ml/tests/fixtures/` (SPEC-012). O `model.onnx` do v2 é ignorado (`.gitignore:58`). O diff `main..HEAD` tem 16 arquivos, nenhum peso | PASS |
| 6 | PNG versionados | só `ml/reports/partqc-mnv3-v2/{type,grade}_confusion.png`, com 1352×1302 e 680×630, as mesmas dimensões das matrizes do v1. Não foram abertas; são saídas do `evaluate`, não fotos | PASS |
| 7 | `parity_fixture.npz` | `inputs` (8, 3, 224, 224) float32, `type_probs` (8, 12), `grade_probs` (8, 5) e `model_sha256`, o mesmo formato do v1 | PASS |
| 8 | Paridade (sem torch, só onnxruntime) | `python -m qc_ml.parity --model-dir ml/models/partqc-mnv3-v2` → `parity ok (max_abs_diff=2.98e-07)`, exit 0. `test_ca12_local_models_parity[partqc-mnv3-v2]` PASSED (e `[partqc-mnv3-v1]`) | PASS |
| 9 | Trailers dos commits do autor | `319b8f9` e `79b95c2` com `Agent: ml-engineer` (R-07) | PASS |

## Bugs encontrados

### BUG-01 (baixa): falta na lista de limitações do v2 o item "outro domínio de captura" da decisão 7

**Onde:** `ml/models/CHANGELOG.md`, seção "Limitações (ADR-025, decisão 7)" da entrada `partqc-mnv3-v2` (linhas 176 a 195).

**Passos:**

1. Ler o ADR-025, decisão 7. O último item é: "os colegas fotografaram com outros celulares, à distância e com a luz deles: a demo pode ter outro domínio".
2. Ler a lista da entrada do v2. Ela começa com "**Todas as limitações do v1 continuam valendo**, porque a validação e o teste são os mesmos:".
3. Procurar "domínio", "outros celulares" ou "distância" nessa entrada.

**Esperado:** os 8 itens da decisão 7 na entrada do modelo, como na entrada do v1 ("**Outro domínio de captura:** os colegas usaram outros celulares, outra distância e outra luz; a demo pela página `/capture` pode se comportar diferente").

**Obtido:** a lista tem 7 dos 8 itens. O do domínio de captura sumiu. Isso engana: a frase de abertura promete "todas", e a lista que vem logo depois parece completa. O item novo "Nenhuma métrica mede o fundo, a luz e o celular do humano" cobre parte da ideia, mas não diz que o teste inteiro vem do domínio dos colegas (outros celulares, distância e luz). Essa é justamente a limitação que mais pesa para um modelo escolhido por teste ao vivo com o celular do humano.

**Correção sugerida (para o ml-engineer):** acrescentar o item do v1 à lista do v2.

Severidade baixa: o conteúdo existe na entrada do v1, que a frase de abertura cita.

### BUG-02 (baixa): 3 números de validação arredondados a favor no texto do v2

**Onde:** `ml/models/CHANGELOG.md`, entrada `partqc-mnv3-v2`. O primeiro número está na linha 161 ("Validação:"). O segundo e o terceiro estão nas linhas 161 e 188 ("Escopo do `false_unknown_rate`").

**Regra:** `docs/architecture.md` §7, "Exibição das métricas", que vale para o CHANGELOG:

- QWK com `ROUND_FLOOR`;
- `false_unknown_rate` com `ROUND_CEILING` (menor é melhor).

| Número no CHANGELOG | Valor bruto (artefato) | Pela regra | Direção do erro |
|---|---|---|---|
| "melhor QWK de grau da validação **0,3556** (época 12) no v2" | `best_val_grade_qwk` 0,3555555… (`training_config.json`) | 0,3555 | arredondado para cima: a favor |
| "falso desconhecido da validação **0,4583** em 0,50" (linha 161) | `type_threshold.false_unknown_rate` 0,4583333… (11/24; `thresholds_report.json`) | 0,4584 | arredondado para baixo: a favor |
| "o 0,0000 do teste não mede a mesma coisa que o **0,4583** da validação" (linha 188) | o mesmo | 0,4584 | arredondado para baixo: a favor |

**Esperado:** nenhum número arredondado a favor (R-11; pedido explícito desta conferência).

**Obtido:** 3 ocorrências com 1 unidade na 4ª casa a favor. A diferença é mínima e não muda nenhuma conclusão, mas descumpre a regra.

Os outros números do texto estão certos:

- 0,4259 do v1, cortado;
- 0,8824 e 0,1765, arredondados para cima;
- os números do `metrics.json`, que vêm da tabela gerada.

**Correção sugerida:** 0,3556 → 0,3555 e 0,4583 → 0,4584 (duas vezes).

## Comandos e saídas

```text
$ uv run --package qc-ml python -m qc_ml.parity --model-dir ml/models/partqc-mnv3-v2
parity ok (max_abs_diff=2.98e-07)                                   (exit=0)
$ uv run --package qc-ml python -m qc_ml.parity --model-dir ml/models/partqc-mnv3-v1
parity ok (max_abs_diff=3.28e-07)                                   (exit=0)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
334 files already formatted

$ uv run pytest -q -rs ml/tests/test_parity.py ml/tests/test_split.py \
    ml/tests/test_split_floor.py ml/tests/test_split_external.py ml/tests/test_report.py \
    ml/tests/test_evaluate.py ml/tests/test_no_torch.py ml/tests/acceptance/test_spec_011.py \
    ml/tests/acceptance/test_spec_012.py ml/tests/acceptance/test_spec_045.py
311 passed, 18 skipped in 90.89s
```

Os 18 `skipped` são esperados neste worktree sem torch: 17 por `could not import 'torch'` e 1 por `could not import 'qc_edge.decision'`, porque o pacote da borda não está instalado aqui. A suíte inteira não foi rodada, como pedido. A pasta principal não foi usada para rodar nada.

## Testes exploratórios

- **Ordem do `split_v2`.** As linhas do v1 aparecem no v2 na mesma ordem relativa, e as 19 novas foram intercaladas por caminho. Nenhuma linha antiga foi editada.
- **`small_stratum` do `split_v2.json`.** Os 3 avisos são dos estratos novos (`scope: new_items`, 1 peça cada) e não afetam o teste, que não mudou.
- **Hashes cruzados.** O `split_sha256`, o `manifest_sha256` e o `model_sha256` coincidem em todos os artefatos: `metrics.json`, `training_config.json`, `thresholds_report.json`, `parity_fixture.npz`, `release-notes.md` e CHANGELOG.
- **Latência p95 maior que a do v1** (28,25 × 21,31 ms). Mesma arquitetura e mesmo tamanho de ONNX (16.890.471 bytes nos dois). O CHANGELOG atribui a diferença, "provavelmente", à carga da máquina, sem afirmar a causa. Continua muito abaixo da meta de 300 ms.
- **Release no GitHub e borda.** O Release do v2 e a cópia para o `MODEL_DIR` são passos manuais do orquestrador e do humano, fora desta conferência. O humano já testou o v2 ao vivo e o aprovou.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, testes, CHANGELOG nem artefatos; só escrevi este relatório.
- [x] Não abri nenhuma foto nem os PNG. O relatório não traz caminho de foto, `source_ref` nem `notes`.
- [x] Trabalhei só no worktree `ml-v2`. Na pasta principal, só li o `ml/data/manifest.csv`, para o hash e o `item_id`.
