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
