# ADR-001: Inspecionar parafusos e porcas de aço em 5 graus de estado, com dataset próprio

| Campo | Valor |
|---|---|
| Status | Aceito |
| Data | 2026-10-12 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-004, ADR-005, ADR-014, SPEC-010, SPEC-011, SPEC-016, SPEC-021, R-11, R-14, N-03, N-07 |

## Contexto

A especificação v0 (`docs/archive/ideia-original.md`) classificava frutas frescas ou estragadas com um dataset do Kaggle. Para a matéria de Indústria 4.0, o domínio ficava distante de uma linha de produção, e a tarefa binária não sustentava um SPC com significado de processo. A dupla quer um domínio industrial, com dados que ela mesma consiga gerar a custo R$ 0 (R-01) até a S3.

Não há dataset público com **5 graus ordinais** de estado para parafusos e porcas:

- **MVTec AD** (categorias `screw` e `metal_nut`) tem licença CC BY-NC-SA 4.0. Ele foi feito para **detecção de anomalia**: só separa "bom" de "defeituoso", não tem graus e usa imagens fixas, de cima para baixo. Fonte: <https://www.mvtec.com/company/research/datasets/mvtec-ad> (verificado em 2026-10-12).
- **UMaine Corrosion Condition Rating Database** trata de aço de **pontes**, não de fixadores. Serve só como inspiração para a rubrica. Fonte: <https://composites.umaine.edu/publication/corrosion-condition-rating-database/> (verificado em 2026-10-12).

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) Parafusos e porcas de aço, 5 graus, dataset próprio fotografado com os celulares e corrosão induzida (vinagre + sal) | Domínio industrial; graus ordinais permitem SPC e QWK; mesmo celular e fundo no treino e na demo (pouca mudança de domínio); custo quase zero | Coleta e rotulagem manuais; graus subjetivos; a corrosão leva dias e precisa começar na S1 |
| B Frutas frescas/estragadas (v0, Kaggle) | Dataset pronto; treino rápido | Fora do contexto industrial; só binário ou 6 classes; fotos de estúdio diferentes da câmera do celular |
| C Dataset industrial público (MVTec AD `screw`/`metal_nut`) | Imagens de qualidade, referência acadêmica | Sem graus; só anomalia; enquadramento fixo; licença não comercial com ShareAlike |
| D Casting product dataset (peças fundidas) | Pronto e industrial | Binário (ok/defeito); não há como gerar novas peças nem demonstrar ao vivo |

## Decisão

O domínio do MVP é **parafuso e porca de aço**, cada um classificado em `perfect`, `good`, `fair`, `poor` e `unusable` segundo a rubrica v0 de `docs/dataset-protocol.md`, com dataset **próprio** capturado pela dupla. O escopo é **em camadas**:

- **MVP:** parafusos e porcas.
- **Fase 2:** ferramentas manuais, com identificação obrigatória e grau só se houver dados (SPEC-016).
- **Fase 3:** ferramentas elétricas, só identificação (SPEC-021).
- **Fora do escopo:** tornos e fresadoras.

## Consequências

- **Positivas:** o problema tem cara de linha de produção; a ordem dos graus permite métricas ordinais (QWK, ±1) e a regra de defeito do SPC (ADR-013); a demo usa peças reais trazidas pela dupla.
- **Negativas / custos aceitos:**
  - dependência de um processo físico lento (corrosão escalonada em 6 h, 24 h e 72 h);
  - risco de rótulos inconsistentes entre os rotuladores, mitigado pela rubrica e pelo QWK (ADR-014);
  - volume pequeno (cerca de 1.200 imagens), com risco de poucos exemplos nos extremos.
- **O que passa a ser obrigatório:**
  - comprar aço carbono comum, evitando zincado e inox, e iniciar a corrosão na S1 (`docs/dataset-protocol.md` §2);
  - rubrica com % de área e precedência do dano funcional; mudanças nos limiares só via N-03, registradas no histórico do protocolo;
  - cada peça física tem `item_id` (`S-`, `N-`, `O-`, `T-`) e o split é por `item_id` (R-11, ADR-014);
  - classe `other` com pelo menos 150 imagens de 30 objetos; uso opcional do MVTec AD só como negativo, com atribuição e para fins acadêmicos;
  - sem pessoas identificáveis nas fotos (R-14);
  - todo tipo novo de objeto entra no contrato com aumento de versão (R-04).

## Quando revisitar

- Se, ao fim da S2, houver menos de 500 imagens ou algum grau tiver menos de 4 peças físicas.
- Se o QWK entre os rotuladores ficar abaixo de 0,6 depois de duas rodadas de calibração da rubrica.
- Se o professor recusar o dataset próprio ou o escopo em camadas (`docs/professor-questions.md`, perguntas 3 e 6).
