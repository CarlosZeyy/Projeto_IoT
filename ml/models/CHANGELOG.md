# Modelos do PartQC — histórico de versões

Uma entrada por versão de modelo (`partqc-<sigla>-v<N>`, skill `ml-pipeline` §8). A entrada é gerada a partir do `metrics.json` da versão, nunca digitada à mão:

```bash
uv run --package qc-ml python -m qc_ml.report changelog \
    --model-dir ml/models/partqc-mnv3-v2 --previous ml/models/partqc-mnv3-v1 \
    --append ml/models/CHANGELOG.md
```

Formato de cada entrada (SPEC-012 §4.8):

- título `## <versão> — AAAA-MM-DD` (data da avaliação, UTC);
- hashes do modelo, do split e do manifest, os limiares do `decision.json` (escolhidos na **validação**) e a máquina da medição de latência;
- tabela métrica × valor × meta do PRD §7 × status, mais a coluna da versão anterior, se houver. Os valores vêm do `metrics.json` (conjunto de **teste**) e são exibidos com 4 casas e vírgula decimal, nunca a favor da meta (`docs/architecture.md` §7, "Exibição das métricas"): corte para baixo quando maior é melhor, arredondamento para cima quando menor é melhor, IC alargado. O status usa o valor bruto;
- "O que mudou" e "Problemas conhecidos", preenchidos pela dupla. Os avisos do `metrics.json` (`warnings`) entram nos problemas conhecidos.

Uma métrica abaixo da meta continua na tabela, com o status `abaixo da meta` (R-11). A primeira entrada vem do treino real da v1 (CA-28 da SPEC-012).

## partqc-mnv3-v1 — 2026-11-05

- `model_sha256`: `7d295bb68643fd8b61bf1980b1ce1692736f1d35bc9848370b6879a00990e420`
- Split: `split_v1.csv` (`split_sha256` `61346ce5612fbbe0cbb8b2c5926d2703c939702fa276eaa60c16070f22fdd5fe`); `manifest_sha256` `e31c5c927f8d87c7e17224457c222f1b541933c9352cbccd8a7d78d4733f2289`
- Limiares (`decision.json`, escolhidos na validação): `{"type_threshold": 0.5, "unusable_threshold": 0.95, "grade_review_threshold": 0.31}`
- Latência medida em: notebook-borda
- Valores do `metrics.json` (teste), exibidos com 4 casas e nunca a favor da meta (`docs/architecture.md` §7); o status usa o valor bruto.

- Tipos do modelo: screw, other, pliers, allen_key, flat_screwdriver, phillips_screwdriver, saw, drill, cordless_screwdriver, hammer, wrench, spirit_level; sem grau: pliers, allen_key, flat_screwdriver, phillips_screwdriver, saw, drill, cordless_screwdriver, hammer, wrench, spirit_level.
- A `type_accuracy` deste modelo não é comparável, como número único, com a de um modelo sem esses tipos (ADR-022): compare pela `type_confusion`.

| Métrica | Valor | Meta (PRD §7) | Status |
|---|---|---|---|
| `type_accuracy` (acurácia de tipo) | 0,5666 | ≥ 0,95 | abaixo da meta |
| `grade_qwk` (QWK do grau) | 0,3979 | ≥ 0,75 | abaixo da meta |
| `grade_qwk_ci95` (IC 95% do QWK, bootstrap por peça) | [-0,0192; 0,7847] | — | — |
| `grade_off_by_one_accuracy` (acurácia do grau com tolerância ±1) | 0,7000 | ≥ 0,90 | abaixo da meta |
| `grade_mae` (erro absoluto médio do grau, em níveis) | 1,3000 | — | — |
| `unusable_recall` (recall de inutilizável) | 0,0000 | ≥ 0,90 | abaixo da meta |
| `unusable_recall_ci95` (IC 95% do recall de inutilizável) | [0,0000; 0,0000] | — | — |
| `unusable_precision` (precisão de inutilizável) | 0,0000 | — | — |
| `defective_recall` (recall de defeituosa: ruim ou inutilizável) | 1,0000 | ≥ 0,90 | atingida |
| `defective_recall_ci95` (IC 95% do recall de defeituosa) | [1,0000; 1,0000] | — | — |
| `defective_precision` (precisão de defeituosa) | 0,3750 | — | — |
| `unknown_rate_on_other` (taxa de desconhecido em outros objetos) | 1,0000 | — | — |
| `false_unknown_rate` (taxa de falso desconhecido) | 0,0000 | — | — |
| `needs_review_rate` (taxa de revisão) | 0,7334 | — | — |
| `latency_ms_p50` (latência p50 em ms) | 19,1863 | — | — |
| `latency_ms_p95` (latência p95 em ms) | 21,3143 | ≤ 300 | atingida |
| `latency_runs` (medições de latência) | 100 | — | — |

Peças no teste por grau: perfect: 2, good: 1, fair: 1, poor: 2, unusable: 1.

Peças de teste de cada métrica `atingida` (contagens do `metrics.json`; ADR-025, decisão 7):

- `defective_recall` 1,0000 (`atingida`): **3 peças defeituosas** (2 `poor` e 1 `unusable`, 3 imagens), entre os **7 parafusos** (10 imagens) com grau no teste. O IC [1,0000; 1,0000] é degenerado: com 3 peças, toda reamostragem definida dá 1,0. O modelo previu defeito em 8 das 10 imagens de parafuso (colunas `poor` e `unusable` da `grade_confusion`), daí a `defective_precision` de 0,3750: o recall alto vem, em boa parte, de prever defeito quase sempre.
- `latency_ms_p95` 21,3143 ms (`atingida`): 100 medições, depois de 10 aquecimentos, percorrendo em ciclo as **30 imagens das 15 peças** do teste, no `notebook-borda` (CPU, batch 1). Não depende da qualidade do modelo.

Escopo das métricas abaixo da meta: `type_accuracy` nas 15 peças (30 imagens) do teste; `grade_qwk`, `grade_off_by_one_accuracy` e `unusable_recall` nos 7 parafusos (10 imagens), com 1 peça `unusable`.

### Dados

- Validação e teste: 0 e 0 imagens externas (ADR-020).
- Treino: 0 imagens externas de 164 (0,0000).

### O que mudou

- Primeira versão oficial (SPEC-045, CA-16; ADR-025). Não há versão anterior para comparar; o modelo provisório da SPEC-041 não tem métricas e não entra nesta comparação.
- Dados: as 223 fotos de três colegas (`c01`, `c02`, `c03`), reimportadas com as correções do Anexo A da SPEC-045 (114 peças), e o `split_v1` do PR #77 (seed 42; treino 84 peças/164 imagens, validação 15/29, teste 15/30). Nenhuma imagem externa e nenhuma foto da página `/capture`.
- Modelo: `mobilenetv3_large_100` pré-treinado no ImageNet, cabeça de grau `ce`, padrões da skill `ml-pipeline` sem desvios (`training_config.json`). 12 tipos, sem `nut`, `adjustable_wrench` e `angle_grinder` (sem imagem no treino). Só `screw` é graduado.
- Limiares escolhidos na validação (`ml/reports/partqc-mnv3-v1/thresholds_report.json`), com as notas `type_target_not_met` (nenhum `t` em [0,50; 0,85] deixa o falso desconhecido da validação em até 5%; em 0,50, 0,5000 nas 24 imagens de validação que não são `other`) e `review_adjusted` (com 0,60, 0,9412 das imagens de validação de parafuso e `other` iriam para revisão; 0,31 é o valor da grade mais perto de 10%, e ainda deixa 0,3530 da validação em revisão).
- Latência oficial (RNF-02, CA-16 da SPEC-008) medida no `notebook-borda` com `--latency-only`.

### Limitações (ADR-025, decisão 7)

Nenhuma meta do PRD §7 pode ser afirmada como propriedade do sistema com este teste.

- **Fundo correlacionado com o colega** (`c01` papel branco, `c02` toalha estampada, `c03` concreto ou barril) e, em parte, com o tipo: o modelo pode ter aprendido o fundo, e nada aqui separa esse efeito.
- **1 foto por peça na maioria**, abaixo das 3 do piso do ADR-024, dispensado só neste dataset.
- **Teste de 15 peças** (30 imagens), com 7 parafusos e 1 a 2 peças por grau (`n_items_test_by_grade`): os ICs são largos ou degenerados (ver `warnings`).
- **Nenhuma métrica de porca:** não há porca no dataset; as métricas de grau são só de parafuso.
- **Tipos com 1 ou 2 peças sem nenhuma medida:** `spirit_level`, `allen_key`, `drill`, `saw` e `cordless_screwdriver` ficaram só no treino (0 peças no teste). Eles ainda "roubam" previsões: a `type_confusion` mostra 6 imagens de teste previstas como `saw` (3 de `pliers` e 3 de `phillips_screwdriver`).
- **Tipos e fusões decididos por um agente**, por miniaturas (Anexo A da SPEC-045); as fusões são conservadoras. O grau continua sendo o do Carlos, por imagem.
- **Graus divergentes dentro de peças fundidas** (ex.: `S-509`, com `perfect`, `good` e `fair`): o grau é por foto, e o estrato do split é o grau dominante.
- **Outro domínio de captura:** os colegas usaram outros celulares, outra distância e outra luz; a demo pela página `/capture` pode se comportar diferente.
- **Nenhuma concordância entre rotuladores:** a rotulagem dupla foi dispensada pelo humano (ADR-025, opção 6B); não existe `ml/reports/agreement.json` para este modelo.
- **Escopo do `false_unknown_rate`:** o `type_threshold` é escolhido na validação contando as imagens de **todos os tipos menos `other`** (SPEC-016 §4.8), mas o `false_unknown_rate` do teste conta **só `screw`/`nut`** (SPEC-012 §4.7; a SPEC-016 não mudou a avaliação). Aqui, isso é só os 7 parafusos (10 imagens): o 0,0000 do teste não mede a mesma coisa que o 0,5000 da validação e não inclui, por exemplo, as 3 imagens de teste de `hammer` previstas como `other` na `type_confusion`.
- **Nenhuma ferramenta graduada:** pelo critério da SPEC-016 §4.6 (≥ 60 imagens de ≥ 5 peças em cada grau), as 4 ferramentas manuais com imagens ficaram em `ungraded_object_types`. Os graus delas no manifest não entram na loss, a borda não dá grau a elas e `tool_grade_metrics` é `{}`, como a SPEC-016 §4.8 manda.

### Problemas conhecidos

- unusable_recall_ci95: unusable_recall was undefined in 347 of 1000 bootstrap resamples, left out of the interval
- defective_recall_ci95: defective_recall was undefined in 11 of 1000 bootstrap resamples, left out of the interval
- grade good has 1 item(s) in the test split (< 2): its metrics are very uncertain
- grade fair has 1 item(s) in the test split (< 2): its metrics are very uncertain
- grade unusable has 1 item(s) in the test split (< 2): its metrics are very uncertain
- few test items for pliers: 1
- few test items for allen_key: 0
- few test items for flat_screwdriver: 1
- few test items for phillips_screwdriver: 1
- few test items for saw: 0
- few test items for drill: 0
- few test items for cordless_screwdriver: 0
- few test items for hammer: 1
- few test items for wrench: 1
- few test items for spirit_level: 0
- Ver também a seção "Limitações" acima (ADR-025, decisão 7).
