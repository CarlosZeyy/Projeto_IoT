# ADR-022: Estender o teste congelado uma única vez para cada tipo de objeto novo

| Campo | Valor |
|---|---|
| Status | Proposto |
| Data | 2026-10-24 |
| Decisores | Dupla (redigido pelo agente architect, a pedido do humano, que liberou as Fases 2 e 3 em 2026-10-24) |
| Relacionados | ADR-014 (complementado, não substituído), ADR-020, ADR-021, SPEC-011, SPEC-012, SPEC-016, SPEC-021, SPEC-035, R-11 |

## Contexto

- O ADR-014 congela o teste no `split_v1` (S3): peças novas entram só no treino e na validação, "salvo um ADR que recrie o teste". A skill `ml-pipeline` §2 repete a regra.
- O `split_v1` é gerado só com parafusos, porcas e `other`. As ferramentas manuais (SPEC-016, Fase 2) e as elétricas (SPEC-021, Fase 3) só são fotografadas depois. Sem uma regra nova, elas nunca teriam peça no teste, e o `metrics.json` não poderia medir a identificação delas (pergunta 2 da SPEC-016; pergunta 4 da SPEC-021).
- Recriar o teste inteiro mudaria o conjunto em que parafusos e porcas são medidos e tornaria as versões do modelo incomparáveis (ADR-014, "Consequências").
- O split atual põe todas as peças de um estrato com menos de 3 peças no treino (`small_stratum`, SPEC-011 §4.4). Um tipo com menos de 3 peças físicas não teria teste de qualquer forma.
- As imagens externas (`X…`) ficam sempre no treino (ADR-020), também para as ferramentas (`XT-`).
- As fotos de ferramentas chegam aos poucos, durante semanas. Se um split for gerado no meio da coleta, as peças de ferramenta já existentes iriam para treino e validação, e o tipo perderia a chance de ter teste.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) **Extensão única por tipo novo, pedida explicitamente:** na primeira versão do split em que a dupla pedir (`--extend-test-types`), as peças de um tipo que nunca apareceu em versão anterior são divididas 70/15/15 como no `split_v1`, inclusive para o teste. Antes disso, as imagens desse tipo podem ficar **adiadas** (fora do split, sem uso em treino, validação ou teste). Depois da extensão, o tipo volta à regra do ADR-014 | Parafusos, porcas e `other` continuam medidos nas mesmas peças; o tipo novo tem teste; a dupla escolhe o momento (coleta completa); auditável no `split_v<N>.json` | Mais duas opções na CLI do split; as métricas de identificação mudam de escopo entre versões com e sem ferramentas |
| B Recriar o teste inteiro quando entrarem as ferramentas | Proporções exatas | Perde a comparabilidade com os modelos anteriores (ADR-014) |
| C Ferramentas só no treino e na validação | Nada muda no split | Nenhuma métrica de teste para as ferramentas; a identificação não é medida (R-11) |
| D Extensão automática na primeira vez que o tipo aparece | Sem opção nova | Um split gerado no meio da coleta congela um teste com 0 ou 1 peça do tipo |

## Decisão

1. Um **tipo novo** é um `object_type` sem nenhuma peça em nenhuma versão anterior do split.
2. `python -m qc_ml.split` aceita `--extend-test-types <t1,t2,…>` e `--defer-types <t1,…>`. Um tipo novo presente no dataset tem de estar em exatamente uma das duas listas; senão a CLI sai com 2, sem gravar nada, e cita o tipo.
3. **Extensão:** as peças não externas de cada tipo de `--extend-test-types` são divididas 70/15/15, estratificadas por (tipo, grau dominante) quando o tipo tem grau e só por tipo quando não tem, com a mesma seed e o mesmo procedimento do `split_v1`, e **sem mexer** em nenhuma atribuição anterior. A CLI recusa (saída 2) estender um tipo com menos de 3 peças não externas. As imagens externas do tipo vão para o treino (ADR-020).
4. **Adiamento:** as imagens dos tipos de `--defer-types` ficam fora do `split_v<N>.csv` e não são usadas em treino, validação nem teste. Um tipo adiado continua "novo" na versão seguinte.
5. O `split_v<N>.json` registra `test_extended_types` e `deferred_types`. Depois da extensão, peças novas do tipo seguem o ADR-014 (só treino e validação), e o teste do tipo fica congelado.
6. As métricas de grau do MVP (`grade_*`) continuam calculadas só em `screw`/`nut`, nas mesmas peças de teste. A identificação (`type_accuracy`, `type_confusion`) passa a incluir os tipos novos, e o CHANGELOG registra essa mudança de escopo.

## Consequências

- **Positivas:**
  - parafusos e porcas continuam comparáveis entre todas as versões do modelo;
  - cada tipo novo tem um teste próprio, congelado a partir da extensão;
  - a decisão do momento fica com a dupla e aparece no artefato.
- **Negativas / custos aceitos:**
  - um tipo estendido com poucas peças tem teste pequeno e métrica instável, como já acontece com os graus (ADR-014); o IC por bootstrap e o `n_items_test` mostram isso;
  - a `type_accuracy` de um modelo com ferramentas não é comparável, como número único, à de um modelo sem elas; o CHANGELOG compara pela `type_confusion`.
- **O que passa a ser obrigatório:**
  - as opções `--extend-test-types` e `--defer-types`, as checagens acima e os campos do `split_v<N>.json` (SPEC-016);
  - os passos de treino, limiares e avaliação ignoram as imagens dos tipos adiados, sem acusar split desatualizado (SPEC-016);
  - a dupla só pede a extensão de um tipo quando a coleta dele atingir a meta da SPEC-016 (ou da SPEC-021).

## Quando revisitar

- Se a dupla precisar estender de novo o teste de um tipo já estendido (por exemplo, por erro de rótulo sistemático): exige um ADR novo, como no ADR-014.
- Se o professor recusar métricas de teste com menos de 3 peças por tipo.
