# ADR-005: Usar um backbone com duas cabeças (tipo e grau), CE com label smoothing e CORN como ablação

| Campo | Valor |
|---|---|
| Status | Aceito |
| Data | 2026-10-12 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-001, ADR-004, ADR-013, ADR-014, SPEC-008, SPEC-012, SPEC-016, R-04, R-11, N-02, N-04 |

## Contexto

Cada foto precisa de duas respostas:

- o **tipo** (`screw`, `nut` ou `other`; ferramentas na Fase 2);
- o **grau**, que é ordinal (`perfect` < `good` < `fair` < `poor` < `unusable`).

O grau não existe para `other`, nem para ferramentas sem dados de grau (SPEC-016). O contrato exige `grade = null` quando `object_type = unknown` (`docs/architecture.md` §3.2). A borda precisa de probabilidades calibradas o bastante para decidir `unknown`, `unusable` e `needs_review` com limiares (N-04).

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) Um backbone com duas cabeças lineares: `type` (softmax, T classes com `other`) e `grade` (5 classes), com a loss de grau mascarada quando não há rótulo | Uma só inferência; as features são compartilhadas (bom para pouco dado); suporta naturalmente objetos sem grau | A loss combinada precisa de peso (λ); o desbalanceamento entre as cabeças precisa ser observado |
| B Dois modelos separados (tipo e grau) | Cada um é otimizado à parte | Duas inferências na borda (latência e memória dobradas); dois artefatos e dois hashes; o modelo de grau vê só parafusos e porcas |
| C Regressão pura do grau (um escalar de 0 a 4) | Respeita a ordem | Arredondamento arbitrário; não dá probabilidade por classe, o que impede o `unusable_threshold` e a `grade_confidence` |
| D Uma cabeça plana de 25 classes (tipo × grau) | Uma só softmax | Classes esparsas; ignora a ordem; "other" sem grau vira caso especial; não escala para a Fase 2 |

## Decisão

O modelo tem **um backbone timm e duas cabeças**. A loss é `CE(type) + λ·CE_masked(grade)`, com λ = 1 e **label smoothing de 0,1** (N-02). A loss de grau é zerada quando o rótulo de grau não existe. **CORN** (`coral-pytorch`, 4 logits) é a ablação da S5. A conversão para probabilidades (softmax, ou CORN → probabilidade por classe) fica **dentro do grafo ONNX**, com as saídas `type_probs [N,T]` e `grade_probs [N,5]`. Os limiares de decisão são escolhidos **na validação** e gravados em `decision.json`.

## Consequências

- **Positivas:**
  - a borda não precisa saber qual loss foi usada: recebe sempre probabilidades;
  - `grade_score = Σ i·p(i)` alimenta as métricas e um eventual gráfico secundário (ADR-013);
  - trocar CE por CORN não muda o contrato nem a borda.
- **Negativas / custos aceitos:**
  - a CE não impõe ordem; erros distantes são penalizados só pela métrica (QWK), não pela loss;
  - mais uma dependência (`coral-pytorch`) no extra `train`, só para a ablação.
- **O que passa a ser obrigatório:**
  - `labels.json` define a ordem das classes; `other` é sempre mapeado para `unknown` no contrato;
  - `decision.json` tem `type_threshold`, `unusable_threshold` e `grade_review_threshold`, escolhidos pelas regras da skill `ml-pipeline` §6, nunca no teste (R-11, ADR-014);
  - a ablação CORN × CE é comparada com as mesmas métricas do `metrics.json` (QWK, ±1, recall de `unusable` e de defeituoso) e registrada em `ml/models/CHANGELOG.md`;
  - um backbone ou loss novos exigem ADR (N-01, N-02).

## Quando revisitar

- Se a ablação CORN superar a CE em QWK de validação por ≥ 0,03 sem perder recall de `unusable`: adotar CORN como padrão (novo ADR).
- Se o recall de `unusable` ficar abaixo de 0,90 **na validação** mesmo com o melhor `unusable_threshold` (o teste nunca motiva escolhas, R-11).
- Se a Fase 2 trouxer uma classe com grau tão desbalanceado que a cabeça compartilhada degrade parafusos e porcas.
