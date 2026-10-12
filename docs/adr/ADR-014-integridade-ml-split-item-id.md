# ADR-014: Dividir os dados por `item_id` (70/15/15), congelar o teste e exigir concordância entre rotuladores

| Campo | Valor |
|---|---|
| Status | Aceito |
| Data | 2026-10-12 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-001, ADR-004, ADR-005, SPEC-010, SPEC-011, SPEC-012, R-11 |

## Contexto

O dataset é pequeno (cerca de 1.200 imagens) e altamente **correlacionado**:

- cada peça física (`item_id`) é fotografada de 3 a 5 ângulos;
- a mesma peça é fotografada em **vários estágios** de corrosão (`docs/dataset-protocol.md` §2, passo 6).

Num split aleatório por foto, o modelo veria a mesma peça no treino e no teste e "decoraria" o objeto, inflando as métricas. Além disso, os graus são subjetivos: sem medir a concordância entre os dois rotuladores, não se sabe o teto de desempenho possível. A integridade das métricas é uma regra inegociável (R-11).

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) Split **agrupado por `item_id`**, 70/15/15, estratificado por (tipo, grau dominante), seed fixa, teste congelado a partir do `split_v1`; dupla rotulagem de 20% com QWK | Sem vazamento entre peças; métricas honestas; teste comparável entre versões do modelo | Menos controle da proporção exata por grau; o teste fica com poucas peças por grau (cerca de 1 a 2) |
| B Split aleatório por imagem | Proporções exatas por classe; mais simples | **Vazamento**: fotos e estágios da mesma peça em treino e teste; métricas otimistas e inválidas |
| C Só validação cruzada k-fold (sem teste separado) | Usa todos os dados para avaliar | Sem um conjunto intocado para o número final; tentação de escolher hiperparâmetros olhando o resultado agregado |

## Decisão

O split é **agrupado por `item_id`** (`StratifiedGroupKFold` ou equivalente), na proporção **70/15/15**, com seed fixa. O arquivo `split_v<N>.csv` e o seu hash são versionados. O **teste é congelado** a partir do `split_v1` (S3): peças novas entram só no treino e na validação, salvo um ADR que recrie o teste. **Todas** as escolhas (limiares do `decision.json`, época, hiperparâmetros, CE × CORN) são feitas **só na validação**. As métricas são reportadas **como foram medidas**, sem arredondar para cima nem omitir classes. Uma amostra de **20%**, estratificada por grau, é rotulada às cegas pelo segundo membro, e o QWK entre os rotuladores precisa ser **≥ 0,6** (mínimo; desejável ≥ 0,8).

## Consequências

- **Positivas:**
  - o número do `metrics.json` é defensável perante o professor;
  - versões do modelo são comparáveis no mesmo teste;
  - o QWK entre rotuladores dá o teto de referência para o QWK do modelo.
- **Negativas / custos aceitos:**
  - poucas peças por grau no teste: as métricas por grau têm variância alta, e isso é declarado no relatório;
  - a dupla rotulagem custa horas de trabalho na S3.
- **O que passa a ser obrigatório:**
  - um teste automatizado que falha se a interseção de `item_id` entre os splits não for vazia (SPEC-011);
  - o `training_config.json` registra a versão do manifest e o hash do split (RNF-07);
  - `ml/reports/agreement.json` com o QWK e a matriz de confusão entre os rotuladores; as divergências vão para `labels_overrides.csv`, sem reescrever o manifest;
  - o `metrics.json` traz todas as métricas da skill `ml-pipeline` §5, incluindo `n_images` e `n_items` por split;
  - o teste de "condição de demo" (50 fotos da S7), se feito, é relatado separadamente.

## Quando revisitar

- Se o QWK entre rotuladores ficar abaixo de 0,6 após a calibração: parar o treino e rever a rubrica (N-03) antes de qualquer split.
- Se algum grau tiver menos de 3 peças físicas no total, o que torna impossível tê-lo nos três splits.
- Se a dupla precisar recriar o teste (por exemplo, por erro de rótulo sistemático): exige um ADR novo.
