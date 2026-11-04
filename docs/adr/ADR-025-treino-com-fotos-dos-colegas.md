# ADR-025: Treinar o modelo oficial com as fotos dos colegas: três ferramentas novas sem grau, piso sem porcas e `split_v1` antecipado

| Campo | Valor |
|---|---|
| Status | Aceito (aprovado pelo humano em 2026-11-04, na sessão do orquestrador; respostas na última seção) |
| Data | 2026-11-04 |
| Decisores | Dupla (decisão do humano, Carlos, em 2026-11-04, na sessão do orquestrador; redigido pelo agente architect) |
| Relacionados | ADR-024 (decisões 3 e 6 alteradas em parte), ADR-014, ADR-020, ADR-021 e ADR-022 (complementados, não substituídos), ADR-001, SPEC-044, SPEC-045, SPEC-041, SPEC-036, SPEC-021, SPEC-016, SPEC-012 (CA-28), SPEC-008 (CA-16), PRD §4.1 e §7, R-02, R-04, R-11, R-14, N-11 |

## Contexto

**Pedido do humano** (Carlos, 2026-11-04, texto literal relatado pelo orquestrador): "esquece a porca, tem varias outras ferramentas lá, use elas, adicione martelo, nivel, entre outras ferramentas que estão nas imagens, faça a analise das imagens você mesmo e faça o treino do modelo, esqueça essas porcas" e "quero esse projeto funcionando com essas imagens que temos ai mesmo".

**Fatos de 2026-11-04** (leitura de `ml/data/manifest.csv`, `ml/data/sources.csv` e do código, sem executar nada, porque o architect não tem shell):

- `ml/data/` tem 223 fotos de três colegas (`c01`, `c02`, `c03`), importadas pela SPEC-036, com 180 `item_id`, todas com `labeler=a` (o Carlos). Nenhuma porca e nenhuma imagem externa. O orquestrador relata `qc_ml.data validate` sem problemas. A pasta de entrada com os originais e o plano (`~/partqc-entrada/colegas/`, fora do repositório) ainda existe. Não há `split_v1` nem modelo oficial.
- A maioria das peças tem **1 foto**. O protocolo pede de 3 a 5 ângulos (N-11), e o piso do ADR-024 pede 3 fotos por peça (o código não confere isso).
- `python -m qc_ml.split` recusa o `split_v1` só pelos 5 estratos `nut/*`: `FLOOR_STRATA` é (`screw`, `nut`) × 5 graus mais `other` (`ml/src/qc_ml/split.py`).
- **O orquestrador olhou as fotos** (folhas de miniaturas), a pedido explícito do humano, **contra a decisão 6 do ADR-024 (`Aceito`)**: um agente que olha uma imagem a envia ao provedor do modelo, e por isso fotos próprias e de conhecidos "nunca" podiam ser vistas. Isso aconteceu antes de qualquer ADR mudar a regra. O resultado está em `~/partqc-entrada/curadoria-agente-20261104.md`, fora do repositório:
  - 3 ferramentas hoje rotuladas `other`: martelo (7 peças), chave de boca, estrela, combinada, L de soquete e grifo (8 peças) e nível (2 peças);
  - 3 tipos errados: `T-506` e `T-546` (`adjustable_wrench`) e `T-542` (`pliers`) são chaves do segundo grupo. Com isso, `adjustable_wrench` fica sem nenhuma imagem;
  - **vazamento (R-11):** o `c02` fotografou a mesma ferramenta ou o mesmo parafuso várias vezes, e cada foto virou uma peça. Com as fusões propostas ("na dúvida, funde"), os 180 `item_id` viram 114 peças. Sem elas, fotos da mesma peça cairiam no treino e no teste;
  - nenhuma pessoa ou rosto; mãos parciais, sem identificação, em `O-534` e `O-535`.
- O `docs/dataset-protocol.md` §10.2 manda dizer ao conhecido que a foto "fica só no notebook e nos backups pessoais da dupla". A visualização por agente não estava nesse combinado.
- **O que o código já faz** (`ml/src/qc_ml/`, `edge/src/qc_edge/`):
  - `derive_model_labels` só põe na cabeça de tipo os tipos com imagem no treino. `nut` e `adjustable_wrench` ficam fora do modelo sem código novo, e a borda carrega um `labels.json` sem `nut`;
  - `qc_ml.data` deriva as "ferramentas elétricas" do grupo sem grau do contrato (`GRADE_FORBIDDEN_OBJECT_TYPES` menos `unknown`). Um tipo novo nesse grupo viraria "elétrico" no ML e mudaria o gerador sintético e os aceites da SPEC-021;
  - no `split_v1`, toda ferramenta é estratificada por (tipo, grau dominante). Com poucas peças, cada estrato fica com menos de 3 e vai inteiro para o treino: o alicate (7 peças em 4 graus) e a chave Phillips (7 peças em 5 graus) ficariam sem validação e sem teste. A extensão do ADR-022 já usa o tipo inteiro como estrato para a ferramenta sem grau;
  - o `--defer-types` não vale no `split_v1`;
  - a importação não muda `item_id` nem tipo de uma foto já importada, e o `labels_overrides.csv` só troca grau.

**Projeção com as decisões abaixo** (contagem feita no manifest, com a curadoria aplicada; o split real confirma):

| Tipo | Peças | No teste | Observação |
|---|---|---|---|
| `screw` | 47 (`perfect` 16, `good` 5, `fair` 7, `poor` 12, `unusable` 7) | 7 (2, 1, 1, 2, 1) | graus do Carlos |
| `other` | 23 | 3 | pregos, ferramentas de jardim, limas, paquímetro etc. |
| `hammer`, `wrench` | 7 e 8 | 1 cada | tipos novos, sem grau |
| `spirit_level` | 2 | 0 | tipo novo, sem grau, só no treino |
| `pliers`, `flat_screwdriver`, `phillips_screwdriver` | 7, 8 e 7 | 1 cada | estrato pelo tipo inteiro (decisão 8) |
| `allen_key`, `drill`, `saw`, `cordless_screwdriver` | 1, 2, 1 e 1 | 0 | só no treino |
| `nut`, `adjustable_wrench`, `angle_grinder` | 0 | — | fora do modelo |
| **Total** | **114 peças, 223 fotos** | **15 peças** | |

Mesmo com **todas** as peças de teste certas, o limite inferior do intervalo exato de 95% (Clopper-Pearson, `0,025^(1/n)`, o cálculo do Anexo do ADR-024) fica em **78,2%** na acurácia de tipo (15 peças), **29,2%** no recall de "defeituoso" (3 peças) e **2,5%** no recall de `unusable` (1 peça).

## Opções consideradas

### 1. Tipos novos (R-04; o ADR-021 manda dizer o grupo de grau)

| Opção | Prós | Contras |
|---|---|---|
| A (recomendada) `hammer`, `wrench` e `spirit_level` no grupo **sem grau** (`GRADE_FORBIDDEN_OBJECT_TYPES`), prefixo `T`, `qc-contracts` 0.7.0 (minor), migração `007` | Não precisa de grau humano, que o Carlos não deu; mesmo caminho já testado das ferramentas elétricas | Esses tipos nunca têm grau. Passar para "grau opcional" depois é outra mudança minor (SPEC) |
| B Grupo "grau opcional", como as ferramentas manuais | O grau futuro não muda o contrato | O dataset exige grau nas manuais (SPEC-016): o Carlos teria de graduar cerca de 30 fotos, e nenhum tipo cumpriria o critério de grau (60 fotos por grau) |
| C Deixar tudo em `other` | Nada muda | Contraria o pedido |
| D A, mais a tesoura de poda (3 peças) | Mais um tipo na demo | Uma peça de treino só; o `other` perde exemplos difíceis |

### 2. Piso sem porcas e tipos sem imagem suficiente

| Opção | Prós | Contras |
|---|---|---|
| A (recomendada) Piso = `screw` × 5 graus + `other` (6 estratos, lista fixa). `nut` continua no contrato e no grupo de grau obrigatório. Tipo sem imagem não entra no modelo (comportamento atual, fixado por CA). Tipo com imagem e menos de 3 peças entra no modelo **só com treino**, sem validação nem teste, declarado | Simples; o nível pedido aparece no modelo | Classes sem nenhuma medida; um tipo com 1 peça física aprende aquela peça e o fundo |
| B Piso dinâmico: os graus de todo tipo de grau obrigatório presente | Exigiria porcas se elas aparecessem | Uma foto de porca bloquearia o split |
| C Tipos com menos de 3 peças fora do modelo (adiados), como decidido pelo humano em 2026-10-24 ("só entram no modelo os tipos com no mínimo 3 peças físicas", `docs/plan.md` §4) | Nenhuma classe sem teste; o tipo pode ter teste depois, pela extensão (ADR-022) | O nível, pedido pelo humano, fica fora do modelo, como a chave Allen, a serra, a furadeira e a parafusadeira |

### 3. Alcance da R-02 para as fotos dos colegas vistas por agente

| Opção | Prós | Contras |
|---|---|---|
| A (recomendada) Exceção única, registrada: as 223 fotos de 2026-11-04, vistas pelo orquestrador a pedido do humano. A decisão 6 do ADR-024 continua para todo o resto, inclusive fotos futuras dos mesmos colegas. Os colegas são avisados e podem retirar as fotos (§10.7) | Registra o que aconteceu sem abrir um precedente | Depende de regra de operação, não de código |
| B Fotos de conhecidos podem ser vistas por agente sempre que o humano pedir | Mais rápido | Amplia o envio de fotos de terceiros ao provedor; contraria o combinado do §10.2 |
| C Descartar a curadoria do agente | Nenhum uso do que foi enviado | As fotos já foram enviadas; perde a correção do vazamento (R-11) e dos tipos errados |

### 4. Como aplicar as correções do dataset

| Opção | Prós | Contras |
|---|---|---|
| A (recomendada) Reimportar do zero, pela importação da SPEC-036, com um plano corrigido gerado do plano original (Anexo A da SPEC-045). Não há `split_v1`, então nenhuma peça muda de conjunto | Nenhum código novo de correção; o manifest, os caminhos e o `sources.csv` ficam coerentes; a origem de cada mudança fica no `notes` | Depende dos originais na pasta de entrada (existem); o `ml/data` atual é descartado |
| B Editar o manifest e mover os arquivos à mão | Rápido | Quebra a regra de que só a borda escreve o manifest; caminho, `item_id` e `sources.csv` podem divergir |
| C CLI nova de reetiquetagem (`item_id` e tipo) | Reutilizável | Código e testes para um uso único |

### 5. Data de corte

A (recomendada): gerar o `split_v1` logo que a SPEC-045 estiver na `main`, o dataset reimportado e o passo da decisão 6 feito, sem esperar 15/11. B: manter 15/11, à espera de fotos que ninguém planeja tirar.

### 6. Rotulagem dupla e QWK (ADR-014; ADR-024, "Quando revisitar")

| Opção | Prós | Contras |
|---|---|---|
| A (recomendada) O segundo membro da dupla grada às cegas 20% das fotos de parafuso, estratificadas por grau (cerca de 17 das 84; cerca de 10 min na tela local de rotulagem), antes do split. Com QWK < 0,6, o split espera a decisão do humano | Cumpre o ADR-014; dá o teto de referência do QWK do modelo | Depende do segundo membro |
| B Dispensar, com a limitação declarada no relatório e no CHANGELOG | Nada a esperar | Nenhuma medida da subjetividade dos graus; contraria o ADR-014 e o PRD §7 (linha de concordância) |

Um agente não serve de segundo rotulador: o orquestrador viu os graus do Carlos nas miniaturas (não é cego), e a decisão 3 não autoriza ver as fotos de novo.

### 7. Limitações

Sem alternativa: são declaradas (decisão 7).

### 8. Estrato das ferramentas no `split_v1`

A (recomendada): o mesmo estrato da extensão do ADR-022 (o tipo inteiro para a ferramenta que o modelo não gradua: as elétricas, as três novas e as manuais fora do critério de grau). Os dados sem ferramentas dão o mesmo split de hoje. B: manter (tipo, grau dominante), e alicate e chave Phillips ficam sem teste.

## Decisão

Opção recomendada em cada item, sujeita às respostas do humano no fim:

1. **Tipos novos:** `hammer` (martelo, inclui marreta e martelo de pedreiro), `wrench` (chave de aperto: boca, estrela, combinada, L de soquete e grifo) e `spirit_level` (nível), nesta ordem, depois de `cordless_screwdriver`, no grupo **sem grau**. Rótulos PT-BR: `martelo`, `chave de aperto`, `nível`. No dataset, prefixo `T` e grau vazio obrigatório, sem rubrica. `qc-contracts` 0.7.0 (minor), migração `007` e todos os componentes na SPEC-044. O `adjustable_wrench` (chave inglesa) continua no contrato, sem imagem.
2. **Piso e tipos sem imagem:** o piso do `split_v1` passa a ser `screw` × 5 graus + `other`, uma lista fixa (SPEC-045). As porcas continuam no contrato, no grupo de grau obrigatório, na rubrica e no pipeline, sem dados. Tipo sem imagem não entra no modelo. Tipo com menos de 3 peças entra só no treino, sem teste. A CLI passa a aceitar `--defer-types` no `split_v1`, para o humano poder adiar um tipo no PR do split (opção C) sem outro ADR.
3. **R-02:** exceção única para as 223 fotos vistas em 2026-11-04, por decisão do humano, e não por interpretação do architect. A decisão 6 do ADR-024 continua valendo para todo o resto: nenhum agente abre foto própria nem de conhecido, inclusive para conferir as correções desta decisão. O humano avisa os três colegas e oferece a retirada (§10.7). O texto da R-02 não muda.
4. **Correções do dataset:** reimportação do zero com um plano corrigido, pelas regras do Anexo A da SPEC-045. As peças retipadas de `O-5NN` viram `T-6NN`, mantendo os dois dígitos finais. As peças fundidas ficam com o menor `item_id` do grupo, e o `notes` de cada linha alterada guarda o `item_id` e o tipo antigos. **O tipo e as fusões são do agente; o grau continua sendo o do Carlos, por imagem.** Os graus das 3 fotos retipadas para `wrench` são descartados, porque o tipo não tem grau. O `labeler` continua `a`.
5. **Data de corte:** o `split_v1` sai depois do merge da SPEC-045, da reimportação e do passo do item 6, por PR, sem esperar 15/11. Foto que chegar depois vai só para treino e validação. Um tipo sem linha no `split_v1` (por exemplo, `nut`) continua "novo" e pode ganhar teste pela extensão do ADR-022.
6. **Concordância:** o segundo membro da dupla grada às cegas 20% das fotos de parafuso antes do split (`ml/reports/agreement.json`). Com QWK < 0,6, o split espera a decisão do humano.
7. **Limitações declaradas** no relatório, nos slides e na entrada do CHANGELOG do modelo:
   - fundo correlacionado com o colega (`c01` papel branco, `c02` toalha estampada, `c03` concreto ou barril) e, em parte, com o tipo: o modelo pode aprender o fundo;
   - a maioria das peças tem 1 foto, abaixo dos 3 do piso do ADR-024, que fica dispensado só neste dataset;
   - teste de cerca de 15 peças, com 7 parafusos e 1 a 2 peças por grau: nenhuma meta do PRD §7 pode ser afirmada como propriedade do sistema (limites acima);
   - nenhuma métrica de porca, e as métricas de grau só de parafuso;
   - tipos com 1 ou 2 peças (nível, chave Allen, furadeira, serra, parafusadeira) sem nenhuma medida;
   - o tipo e as fusões vieram de um agente, por miniaturas. As fusões são conservadoras (menos peças, nenhum vazamento conhecido);
   - peças fundidas com graus diferentes entre as fotos (por exemplo, o grupo `S-509`, com `perfect`, `good` e `fair`): o grau é por foto e o estrato é o grau dominante, como no ADR-014;
   - os colegas fotografaram com outros celulares, à distância e com a luz deles: a demo pode ter outro domínio.
8. **Estrato no `split_v1`:** a mesma regra da extensão do ADR-022, numa função única, na SPEC-045.

## Consequências

- **Positivas:**
  - o modelo oficial pode ser treinado já, com métricas honestas e o tamanho do teste declarado. O CA-28 da SPEC-012 e o CA-16 da SPEC-008 podem ser fechados com ele;
  - o vazamento por `item_id` repetido sai antes do primeiro split;
  - as porcas podem voltar depois sem ADR novo, pela extensão do teste (ADR-022).
- **Negativas / custos aceitos:**
  - 223 fotos de terceiros foram ao provedor do modelo, fora do combinado com eles (§10.2);
  - o `ml/data` atual é descartado e refeito; os originais ficam na pasta de entrada até o fim da reimportação e depois são apagados (ADR-020, decisão 6);
  - o teste é muito pequeno (Contexto), e uma métrica `atingida` no CHANGELOG não afirma nada sem o número de peças;
  - a projeção e as fusões não foram conferidas por um humano, salvo a resposta 3.
- **O que passa a ser obrigatório:**
  - SPEC-044: contrato 0.7.0, migração `007`, API, borda, dashboard e as constantes do `qc_ml.data`, com as ferramentas elétricas como uma lista explícita, separada das três novas;
  - SPEC-045: piso fixo sem porcas, estrato único, `--defer-types` no `split_v1`, fixture sem porca, procedimento de reimportação (Anexo A), concordância, split por PR e treino;
  - nenhum agente abre foto da dupla ou de conhecidos (decisão 3);
  - o relatório e o CHANGELOG trazem as limitações da decisão 7.
- **Textos que acompanham o aceite** (pelo orquestrador, como nos ADRs 018, 019, 023 e 024):
  - status do ADR-024: "Aceito; decisões 3 e 6 alteradas em parte pelo ADR-025";
  - N-11 em `docs/rules.md`, coluna Fonte: "`docs/dataset-protocol.md`; ADR-020; ADR-024; ADR-025";
  - PRD §4.1: "Tipos de objeto: parafuso e porca de aço […]", acrescentar "(a partir do ADR-025, o modelo oficial é treinado sem porcas, por falta de fotos; a porca continua no contrato)"; PRD §7, linha "Acurácia de tipo (parafuso/porca/outro)" → "Acurácia de tipo (todos os tipos do modelo)";
  - ADR-001: nota de que o dataset do modelo oficial não tem porcas (ADR-025).

## Quando revisitar

- Se um colega pedir a retirada das fotos: a §10.7 vale, inclusive depois do `split_v1`, com o aviso `excluded_previous_image`.
- Se chegarem fotos de porca: `--extend-test-types nut` (ADR-022), quando houver 3 peças por grau.
- Se o QWK ficar abaixo de 0,6: o split espera a decisão do humano (decisão 6).
- Se o humano quiser que um agente veja fotos próprias ou de conhecidos de novo: exige um ADR novo.
- Se o professor recusar fotos de terceiros ou o teste pequeno (perguntas 9 e 10 de `docs/professor-questions.md`).

## Perguntas ao humano (para o aceite)

1. Aceita os três tipos no grupo sem grau, com os nomes `hammer`, `wrench` e `spirit_level` e os rótulos `martelo`, `chave de aperto` e `nível`? **Recomendação:** sim. `spirit_level` evita confusão com "nível de log" e "nível de grau" no código; `level` também funciona. A tesoura de poda fica em `other`.
2. Tipos com 1 ou 2 peças (nível, chave Allen, furadeira, serra, parafusadeira): entram no modelo só com treino, ou ficam adiados, como na regra de 2026-10-24? **Recomendação:** entram, porque o pedido inclui o nível e não há fotos novas previstas; a limitação vai para o relatório. O `--defer-types` no `split_v1` deixa trocar no PR do split.
3. A visualização das 223 fotos fica como exceção única, com os colegas avisados e a opção de retirada? **Recomendação:** sim. E confirmar, olhando no tamanho real, as fotos de `O-534` e `O-535` (mãos parciais): sem anel nem tatuagem, ficam; senão, saem pela §8.1.
4. Aceita as correções de tipo e as fusões do agente sem conferir uma a uma? **Recomendação:** sim; se quiser conferir, a lista está no Anexo A da SPEC-045 (cerca de 10 min na tela local).
5. Quem é o segundo rotulador, e a rotulagem dupla acontece antes do split? **Recomendação:** o segundo membro da dupla, antes do split. Se não der até o dia seguinte ao merge da SPEC-045, o humano decide dispensar (opção 6B), e o relatório declara isso.
6. Antecipa o `split_v1` para logo depois desses passos? **Recomendação:** sim.

### Respostas do humano (2026-11-04, na sessão do orquestrador)

- **Aceite do ADR-025 e das SPECs 044 e 045** (perguntas 1, 2, 4 e 6 e as da §9 das duas SPECs). A pergunta resumia: os três tipos sem grau, contrato 0.7.0, migração `007` em produção logo após o merge; o piso parafuso × 5 graus + `other`; tipos com 1 ou 2 peças só no treino; as correções por reimportação (180 → 114 peças); o `split_v1` já; a exceção única à decisão 6 do ADR-024. Resposta: **"Aprovar tudo"**.
- **Pergunta 5, rotulagem dupla.** Resposta: **"Dispensar e declarar"** (opção 6B). O split não espera. O relatório, o CHANGELOG e os slides declaram que não houve concordância entre rotuladores neste modelo.
- **Pergunta 3, aviso aos colegas.** Resposta: **"Sim, eu aviso"**. O aviso a `c01`, `c02` e `c03`, com a opção de retirada, e a conferência de `O-534` e `O-535` no tamanho real ficam pendentes com o humano e não bloqueiam a implementação.
