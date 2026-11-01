# ADR-024: Separar o modelo provisório de ensaio do modelo oficial e fixar o piso do `split_v1`

| Campo | Valor |
|---|---|
| Status | Aceito (aprovado pelo humano em 2026-11-01, nesta sessão; respostas na última seção) |
| Data | 2026-10-31; decisão 4 reescrita e decisões 5 e 6 acrescentadas em 2026-11-01 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-004, ADR-014 e ADR-020 (complementados, não substituídos), ADR-003 (condição da Fase 3 substituída), ADR-022, SPEC-008, SPEC-011, SPEC-012, SPEC-019, SPEC-035, SPEC-036, SPEC-041, PRD §4.3 e §8, R-02, R-06, R-11, R-14, N-07, N-11 |

## Contexto

Fatos conferidos em 2026-10-31:

- O dataset próprio tem **zero** fotos, e não há `model.onnx`, Release nem `split_v1`. O CA-28 da SPEC-012 e o CA-16 da SPEC-008 estão pendentes.
- A dupla espera fotos de colegas, sem data. Os 120 PNGs recebidos são desenhos gerados por computador e não entram no dataset. O humano pediu para finalizar o quanto antes e autorizou buscar conteúdo externo livre. O ensaio (M4) é em 29/11, e a entrega, entre 30/11 e 04/12.
- `docs/dataset-protocol.md` §2 registra, em 2026-10-12, que a dupla já tem parafusos e porcas novos e parafusos velhos e enferrujados. **A coleta do piso abaixo não depende, em princípio, dos colegas.** O que falta confirmar é a pergunta 3.
- Há candidatos externos em `~/partqc-entrada/candidatos/`, fora do repositório (`LEIAME.md`): 250 recortes M2, 124 YCB e as folhas da SDNET. As três fontes já estão em `ml/external_sources.csv`. Licenças reconferidas em 2026-10-31, todas CC BY 4.0: <https://data.mendeley.com/public-api/datasets/2y6mcsyrpy>, <https://data.mendeley.com/public-api/datasets/cxnj6cp4rb> e <https://ycb-benchmarks.s3.amazonaws.com/index.html>.
- O PRD §4.3 e §8 e o ADR-003 ("Quando revisitar") condicionam a Fase 3 ao fechamento da Fase 2 no prazo (22/11). As SPECs 020 e 021 já foram adiantadas por decisão do humano de 2026-10-26 (`docs/plan.md` §4). Falta a 019.
- Um agente que olha uma imagem a envia ao provedor do modelo. Por isso, sugerir graus e conferir recortes por agente toca a R-02 (decisão 6).

O que o código faz hoje (leitura de `ml/src/qc_ml/`):

- **O pipeline oficial não roda só com externas.** Sem peça própria, `make_split` sai com `external fraction in train`. Com `--max-external-fraction 1.0`, ele grava um split sem validação nem teste, e o `train` para em `the train and val splits must both have images`. O `rows_for` recusa externa em `val` e `test`.
- **Armadilha irreversível.** A CLI grava o `split_v1` com qualquer número de peças, mesmo com teste vazio (estrato com menos de 3 peças vai todo para o treino, com o aviso `small_stratum`, e a saída é 0). A partir daí, peças novas só vão para treino e validação. Um `split_v1` gerado cedo demais congela um teste pobre ou vazio, e só um ADR o recria (ADR-014).
- **A borda grava `source=live` fixo** (`edge/src/qc_edge/app.py`). Um modelo sem valor oficial, carregado por `MODEL_DIR`, publicaria inspeções `live`, que entram na carta p, na taxa de defeito e nos alertas.

## Opções consideradas

| Opção | O que permite afirmar ao professor | Risco de misturar com o PRD §7 | Custo e prazo |
|---|---|---|---|
| A. Manter as regras e esperar as fotos | Tudo o que o PRD pede, **se** as fotos chegarem | Nenhum | Sem data. Nenhum modelo até lá; pode chegar ao M4 sem nada para mostrar além do stub |
| B. Reduzir as metas de volume (o piso abaixo), sem mais nada | Métricas oficiais medidas em poucas peças, com a incerteza declarada | Baixo: mesmo pipeline, mesmo teste. O risco é ler um número de 11 peças como garantia | **Sozinha não resolve:** com zero fotos, qualquer meta continua zero. Não dá ensaio antes das fotos |
| B2. Baixar as metas de **métrica** do PRD §7 | Nada a mais | Alto: muda a régua para caber no resultado | Rejeitada |
| C. Modelo provisório só com externas, isolado, sem métrica | Que o fluxo celular → borda → nuvem → painel roda com uma rede ONNX treinada de verdade. **Nada** sobre a qualidade da inspeção | Alto sem isolamento (nome, `metrics.json`, `source=live`, graus sugeridos por agente). Baixo com as guardas da decisão | Depende só de um agente sugerir os graus dos candidatos. Código novo pequeno (SPEC-041) |
| D. Abrir o pipeline oficial para externas (teto 100%, externas em validação e teste) | Números que parecem do PRD, mas medem outro domínio | **Máximo:** o `metrics.json` deixa de refletir a demo. Contraria o ADR-020 e o espírito da R-11 | Rejeitada |
| E. Rede sem treino (MobileNetV3 só com ImageNet, ou a fixture `tiny_model`) | Que a tubulação funciona; a latência da arquitetura | Baixo com o mesmo isolamento | Sem rótulo nenhum, mas o resultado é aleatório e não ensaia o treino e o export. Sem valor como reserva da demo |
| **F (escolhida). C + piso:** duas trilhas, com as regras do modelo oficial intactas | Trilha 1: o fluxo, desde já. Trilha 2: métricas oficiais, com o tamanho do teste declarado | Baixo: as guardas impedem a mistura por construção | Sugestões e conferência de privacidade por um agente; depois, a coleta do piso. O teste só congela na data de corte |

## Decisão

1. **Duas trilhas.** O modelo **oficial** continua sendo o único com `metrics.json`, Release e comparação com o PRD §7. R-11, ADR-014, ADR-020 e as metas de métrica do PRD §7 não mudam, e as metas de volume do `docs/dataset-protocol.md` §4 continuam como metas.
2. **Modelo provisório**, só para ensaiar o fluxo:
   - **Nome:** contém `-provisional-` (`partqc-mnv3-provisional-v1`). O nome decide sozinho, como o prefixo `X` do ADR-020.
   - **Dados:** só imagens externas (`X…`), rotuladas como no item 4, em `DATASET_DIR` próprio, **fora de `ml/data/` e fora de qualquer repositório Git**, entrando pela importação da SPEC-036. O teto de 30% não se aplica a esse conjunto, porque ele nunca passa pelo `make_split`. **Nenhuma foto própria** entra nele, para nenhuma peça do futuro teste ser vista por esse modelo.
   - **Treino:** só a fase A, sem split, sem validação e sem teste, com limiares fixos (0,50 / 0,50 / 0,60). **Não existe métrica de qualidade desse modelo:** o processo não gera `metrics.json`, e o relatório dele só traz contagens e a perda de treino.
   - **Distribuição:** fica só no notebook. Sem Release e sem entrada no CHANGELOG. Os artefatos ficam fora do repositório.
   - **Na borda:** toda inspeção feita com ele sai com `source=simulated` (R-06), então fica fora do SPC padrão, da taxa `live` e dos alertas, e aparece com o selo de simulado. O celular e o console avisam que o modelo é provisório.
3. **Piso e data de corte do modelo oficial:**
   - **Piso:** o `split_v1` só é gerado com **3 peças físicas por tipo × grau** e **3 objetos `other`**, com pelo menos **3 fotos por peça** (33 peças, 99 fotos; cálculo no Anexo). A CLI do split passa a recusar menos que isso.
   - **Data de corte:** o `split_v1` sai na data de corte (**15/11/2026**) e não antes, salvo decisão do humano. Atingir o piso habilita o split; não obriga a gerá-lo. O motivo é que toda peça que chega depois do `split_v1` só melhora treino e validação, nunca o teste.
   - **Sem o piso na data:** não há modelo oficial. A apresentação mostra o fluxo com o modelo provisório e declara que não há métricas oficiais. Nenhum número substitui as do PRD §7.
4. **No conjunto provisório, e só nele, o grau é uma sugestão de agente, e um agente confere a privacidade.** Fora dele, nada muda: no dataset oficial, o grau continua sendo da dupla, com a rubrica, a rotulagem dupla e o QWK, e a conferência de privacidade continua humana (`docs/dataset-protocol.md` §1, §10.1 e §10.5, ADR-014).
   - **Como:** um agente aplica a rubrica a cada recorte e escreve `grade` e `labeler` no plano de importação. O rótulo da fonte (OK/NG) e o `sugestoes.csv` são só pistas. O recorte que não dá para decidir sai do plano. O plano fica fora do repositório.
   - **Marca:** o `labeler` é o valor fixo **`agent-suggestion`** em todas as linhas do conjunto. O modo coleta não aceita esse valor, e o `qc_ml.provisional` recusa um conjunto com qualquer outro.
   - **Proibição:** esses recortes **nunca entram em `ml/data/` nem em outro dataset oficial**, nem com rótulo novo. Eles não aproveitam o teto de 30% do ADR-020. O código barra o `labeler` em duas pontas: a importação só o aceita com `--provisional-set` e fora de qualquer repositório Git, e o `load_manifest` o recusa por padrão, seja qual for o `DATASET_DIR`, o que para `qc_ml.data`, `split`, `train`, `thresholds`, `evaluate` e `pipeline`.
   - **Conferência de privacidade:** antes da importação, um agente confere as folhas de contato dos recortes do plano e descarta o que tiver pessoa, placa ou documento. O humano assume essa conferência ao aprovar (resposta 9). Vale só para imagens públicas, fora de `ml/data/` e do Git. O `--privacy-checked` registra que ela foi feita, e o código dessa opção não muda.
   - **Só imagens públicas:** o agente só recebe recortes e folhas de contato das fontes registradas, nunca fotos da dupla ou de conhecidos (decisão 6).
5. **A Fase 3 deixa de esperar o prazo da Fase 2** (resposta 8). As SPECs da Fase 3 não dependem mais de a Fase 2 fechar até 22/11 (M3). Esta decisão substitui essa condição no PRD §4.3 e §8 e no ADR-003 ("Quando revisitar"), sem ADR separado. O conteúdo das fases (N-07) não muda.
6. **Alcance da R-02 para imagens vistas por agente: decisão do humano** (resposta 10), e não interpretação do architect. A R-02 protege as fotos capturadas no projeto e as de conhecidos. Imagens de datasets públicos podem ser vistas por um agente. Fotos próprias e de conhecidos, nunca.

## Consequências

- **Positivas:**
  - o fluxo pode ser ensaiado antes de existir qualquer foto própria, e o treino e o export são exercitados de verdade;
  - nenhum caminho do código leva um resultado provisório ao `metrics.json`, ao CHANGELOG, ao Release ou à carta `live`;
  - o `split_v1` deixa de poder congelar um teste vazio por engano.
- **Negativas / custos aceitos:**
  - o domínio das externas é distante da demo (microinspeção M2, peças montadas da SDNET). **O modelo provisório pode errar muito com as fotos do celular**, e isso é esperado;
  - **o grau do provisório é pouco confiável**, porque nenhum humano o decidiu. Isso é aceitável só porque esse modelo não gera métrica: o que ele mostra de grau no ensaio não avalia nada;
  - a proibição é garantida pelo `labeler`, não pelo conteúdo: se alguém reimportar um desses recortes com `labeler` `a` ou `b`, o código não percebe. Nesse caso, ela é só uma regra do protocolo;
  - **a conferência de privacidade do provisório pode deixar escapar algo** que um olhar no tamanho real pegaria, porque um agente olha folhas de contato. O humano assume esse risco, aceitável só porque são imagens públicas, fora de `ml/data/` e do Git;
  - as imagens públicas vistas por um agente vão ao provedor do modelo (decisão 6). Nada no código impede um agente de abrir uma foto própria: a proibição é uma regra de operação;
  - no piso, o teste tem 11 peças. **Nem um acerto total permite afirmar as metas do PRD §7** (Anexo);
  - os resultados do ensaio ficam no mesmo balde `simulated` do simulador. A convenção é usar lotes `ENSAIO-…`.
- **O que passa a ser obrigatório** (SPEC-041):
  - `TrainConfig`, `qc_ml.report changelog` e `release-notes` recusam uma versão provisória;
  - `qc_ml.provisional` recusa foto própria, `labeler` diferente de `agent-suggestion`, caminho dentro de repositório Git e versão não provisória;
  - `qc_ml.data.load_manifest` recusa `agent-suggestion` por padrão, no manifest e no `labels_overrides.csv`;
  - `qc_edge.importer` só aceita `agent-suggestion` com `--provisional-set`, fora de repositório Git e em conjunto sem outro `labeler`;
  - `qc_ml.split` recusa um `split_v1` abaixo do piso;
  - a borda força `source=simulated` para uma versão provisória, inclusive no vídeo ao vivo (SPEC-019);
  - `docs/dataset-protocol.md` §10.1, §10.5 e §11 registram as exceções: "o grau é decidido pela dupla" e a conferência humana de privacidade valem para `ml/data/` e todo dataset oficial, e não para o conjunto provisório;
  - nenhum agente recebe foto da dupla ou de conhecidos (decisão 6);
  - o relatório e os slides dizem qual modelo gerou o quê. Métricas que não dependem da qualidade do modelo (demo de 20 peças, RNF-03, RNF-04) podem ser medidas com o provisório, se o relatório disser isso. A latência medida com ele é só indicativa: o **CA-16 da SPEC-008 e o CA-28 da SPEC-012 continuam pendentes** até o modelo oficial.
- **Textos que acompanham o aceite:**
  - N-11 em `docs/rules.md` (pelo orquestrador, como nos ADRs 018, 019 e 023), padrão: "3 a 5 ângulos por peça por estágio, fundo liso; piso do `split_v1` e conjunto provisório no ADR-024"; fonte: "`docs/dataset-protocol.md`; ADR-020; ADR-024";
  - N-07 em `docs/rules.md` (pelo orquestrador): padrão sem mudança; fonte: "ADR-001; ADR-024 (Fase 3 sem esperar o prazo da Fase 2)";
  - nota no PRD §7: "Só o modelo oficial preenche esta tabela (ADR-024)." (aplicada);
  - PRD §4.3 e §8 sem o condicionamento, e nota no ADR-003 (aplicados).

O texto das regras inegociáveis não muda: a R-06 é reforçada; a R-11 fica intacta, porque o conjunto provisório não tem split nem teste; a R-14 vale para o dataset, que continua com a conferência humana, e o conjunto provisório, que não é o dataset, tem a conferência por agente da decisão 4. O alcance da R-02 para imagens vistas por agente é a decisão 6, do humano.

## Quando revisitar

- Se o professor recusar o modelo provisório ou as imagens externas (perguntas 9 e 10 de `docs/professor-questions.md`).
- Se chegarem peças depois do `split_v1` e a dupla quiser um teste maior: exige um ADR novo que recrie o teste (ADR-014), de preferência antes de qualquer leitura do `metrics.json`.
- Se o QWK entre rotuladores ficar abaixo de 0,6 (ADR-014): o `split_v1` espera a revisão da rubrica, mesmo com o piso atingido.
- Se o modelo oficial existir antes do ensaio: o provisório sai do `MODEL_DIR` e os lotes `ENSAIO-…` deixam de ser usados.
- Se alguém quiser usar um recorte do conjunto provisório no dataset oficial, ou um grau sugerido por agente em qualquer modelo com métrica: exige um ADR novo.
- Se aparecer no conjunto provisório uma imagem com pessoa, placa ou documento que o agente deixou passar: a imagem sai, e quem confere volta a ser decisão do humano.

## Anexo: cálculo do piso

Conferido em 2026-10-31 **por leitura do código** (`split.py`, `train.py`, `thresholds.py`, `evaluate.py`, `artifacts.py`), sem executar, porque o architect não tem shell. Os CAs 01 a 05 da SPEC-041 fixam os números. Conferência imediata (saída esperada: 33 imagens em cada split, sem avisos):

```bash
uv run --package qc-ml python - <<'PY'
import tempfile
from pathlib import Path
from qc_ml.data import load_manifest
from qc_ml.split import make_split
from qc_ml.synthetic import make_synthetic_dataset
root = make_synthetic_dataset(Path(tempfile.mkdtemp()) / "ds", items_per_stratum=3, images_per_item=3)
result = make_split(load_manifest(root))
print(result.frame["split"].value_counts().to_dict(), result.warnings)
PY
```

**Regra do código.** O estrato é `(tipo, grau dominante)`. Para `n` peças num estrato (`_allocate`): com `n < 3`, tudo vai para o treino; com `n ≥ 3`, `n_test = n_val = max(1, round_half_up(0,15·n))`, e o resto vai para o treino. Com `n = 3`, são **1/1/1**. O treino falha se um dos 5 graus não tiver imagem (`grade_class_weights`) ou se faltar `other` (`check_labels`). O código não exige número de fotos por peça; os 3 vêm do protocolo (§3, N-11).

| Conjunto | Parafuso por grau | Porca por grau | `other` | Peças | Fotos (3 por peça) | Teste (peças) | O que acontece |
|---|---|---|---|---|---|---|---|
| Só não quebra | 3 em um grau, 1 em outros três | 1 em um grau | 1 | 8 | 24 | 1 | Saída 0, mas o teste tem um grau só: `unusable_recall`, `defective_recall` e `unknown_rate_on_other` ficam `null`. **Não serve** |
| Métricas não nulas | 3 | 3 em um grau só | 3 | 21 | 63 | 7 | Não mede o grau das porcas, e 4 graus ficam com 1 peça no teste. **Não serve** |
| **Piso** | **3** | **3** | **3** | **33** | **99** | **11** | 5 graus e 3 tipos no teste, com 2 peças por grau (1 parafuso e 1 porca) |
| Piso prático | 3 | 3 | 10 | 40 | 120 | 12 | Igual, e some o aviso `few test items for other: 1` (`n = 10` dá 2 no teste) |
| Mínimo atual do §4 | 8 | 8 | 30 | 110 | 330 | 15 | 1 peça por estrato no teste; 5 `other` |
| Meta do §4 | 12 | 12 | 30 | 150 | ≥ 1.350 | 25 | 2 peças por estrato no teste; 5 `other` |

No piso, o split é 11/11/11 peças e 33/33/33 fotos. No máximo **14 imagens externas** cabem no treino (`E ≤ 3N/7`, com `N = 33`: 14/47 = 29,8%; 15/48 = 31,25% é recusado). Com 5 fotos por peça, cabem 23. Fotos a mais não substituem peças: as fotos de uma peça são correlacionadas, e o IC do `metrics.json` reamostra por peça.

Cada peça conta num só estrato, o do grau dominante (empate: o mais severo). No piso, fotografe cada peça em um só estado. Além das fotos, o ADR-014 continua exigindo a rotulagem dupla de 20% (cerca de 18 das 90 fotos com grau) e QWK ≥ 0,6.

**O que o piso permite afirmar:** que o pipeline oficial rodou inteiro; que o split foi por peça e o teste ficou intocado; que os limiares foram escolhidos na validação; e os valores medidos naquelas 11 peças, com `n` declarado, inclusive abaixo da meta.

**O que o piso não permite afirmar:** que alguma meta do PRD §7 foi atingida como propriedade do sistema; recall por grau com alguma precisão (2 peças de `unusable`); o desempenho do grau separado por tipo; robustez a luz, fundo ou celular; comparações entre versões (CE × CORN).

O limite vem da aritmética. Mesmo com **todas** as peças certas, o limite inferior do intervalo exato de 95% (Clopper-Pearson, por peça, `0,025^(1/n)`) fica assim:

| Métrica (meta) | Piso (peças → limite inferior) | Meta do §4 (peças → limite inferior) |
|---|---|---|
| Acurácia de tipo (≥ 95%) | 11 → 71,5% | 25 → 86,3% |
| Recall de "defeituoso" (≥ 90%) | 4 → 39,8% | 8 → 63,1% |
| Recall de `unusable` (≥ 90%) | 2 → 15,8% | 4 → 39,8% |

Atenção ao ler o `metrics.json`: com acerto total, o IC por bootstrap sai `[1,0; 1,0]`, porque toda reamostragem dá 1. Isso **não** é certeza. E o status `atingida` do CHANGELOG usa o valor bruto: no relatório, ele sempre vem acompanhado do número de peças.

## Respostas do humano

Respostas de 2026-11-01, como relatadas pelo orquestrador. Às perguntas 1 a 4, 6 e 7, a resposta foi **"Aprovar tudo"**, com todas as recomendações. O humano também pediu para usar datasets públicos, para ter algo a testar localmente, e deixou o deploy na VPS por último.

1. **Aceita as duas trilhas (opção F)?** Sim.
2. **Qual a data de corte do `split_v1`?** 15/11/2026, uma semana antes do M3 (22/11), para dar tempo de treinar e medir. Antecipe só se a coleta acabar antes e ninguém mais for mandar fotos, porque peça que chega depois não entra no teste.
3. **A dupla pode fotografar as próprias peças agora, sem esperar os colegas? Há peças em `good` e `fair`, ou a corrosão de 6 a 72 h (§2) ainda precisa ser feita?** Vale a recomendação: fotografar já e começar a corrosão esta semana. As fotos dos colegas entram como extra, se chegarem antes do corte. O fato de haver ou não peças em `good` e `fair` continua sem resposta.
4. **Piso de 33 peças na CLI, com a coleta mirando em 40?** Sim.
5. **Quem decide os graus do conjunto provisório?** A recomendação original (um membro da dupla, sem QWK) foi **substituída** pela resposta **"Sugestão do agente"**. A pergunta feita dizia: "só no provisório, com labeler marcando que é sugestão de agente e esses recortes proibidos de entrar em `ml/data/`; rápido, mas o grau do provisório fica pouco confiável, o que é aceitável porque ele não gera métrica; o dataset oficial continua com grau da dupla". Ver a decisão 4.
6. **Resultados do provisório como `source=simulated`?** Sim. A alternativa (`live` com filtro por `model_version`) exigiria mudar a API e poderia contaminar a carta p, se alguém esquecesse o filtro.
7. **Sem o piso na data de corte, apresentar só o fluxo e declarar que não há métricas oficiais?** Sim, avisando o professor com antecedência (pergunta 10).

Perguntas feitas depois, também em 2026-11-01, com o texto como relatado pelo orquestrador:

8. **"Você aprova esses textos e o fim desse condicionamento dentro do próprio ADR-024?"** Os textos: SPEC-041 §4.9 e CAs 23 a 30 e SPEC-019 CAs 13 e 14, apresentados ao humano por resumo. O condicionamento: o PRD diz que a Fase 3 depende do prazo da Fase 2. Resposta: **"Aprovar"**, descrita como "registro a aprovação no ADR-024 e nas SPECs, sem ADR separado; a Fase 3 deixa de esperar o prazo da Fase 2". Ver a decisão 5.
9. **"Quem confere os recortes públicos do conjunto provisório?"** Resposta: **"Agente, só no provisório"**, descrita como "um agente confere as folhas de contato e descarta o que tiver pessoa, placa ou documento, e você assume essa conferência ao aprovar; vale só para imagens públicas fora de `ml/data/` e do Git; pode escapar algo que um olhar no tamanho real pegaria; o dataset oficial continua com conferência humana". Ver a decisão 4.
10. **"Isso é aceitável para imagens de datasets públicos?"** O "isso": pela R-02, um agente que olha imagens as envia ao provedor do modelo. Resposta: **"Sim, só públicas"**, descrita como "fica registrado no ADR-024 que a R-02 protege as fotos capturadas no projeto e as de conhecidos; imagens de datasets públicos podem ser vistas por um agente; fotos próprias e de conhecidos, nunca". Ver a decisão 6.
