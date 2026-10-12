# Protocolo de dataset

Como gerar as peças, fotografar, rotular e organizar os dados. Vale para a dupla e para o agente `ml-engineer`. As regras de integridade (R-11) são inegociáveis; os limiares da rubrica podem ser calibrados no piloto (N-03), sempre registrando a mudança aqui com a data.

## 1. Rubrica de grau v0 — parafusos e porcas

**Como medir a área oxidada:** estime a % da **área visível** da peça coberta por óxido (laranja ou marrom), olhando a foto no tamanho real. Na dúvida entre dois graus, escolha o **mais severo** e anote em `notes`.

| Grau (código) | PT-BR | Critério | Exemplos |
|---|---|---|---|
| `perfect` | perfeito | Nenhuma oxidação visível e nenhum dano. Brilho metálico uniforme | Peça nova, da embalagem |
| `good` | bom | Oxidação em **pontos isolados**, < 5% da área. Sem crosta. Rosca e cabeça íntegras | Peça com 1–2 pontos alaranjados |
| `fair` | mediano | Oxidação superficial em **5–25%** da área, sem crosta nem pitting. Rosca íntegra | Manchas laranja espalhadas |
| `poor` | ruim | Oxidação em **> 25%** da área, **ou** crosta/escamação, **ou** pitting visível. Ainda funcional (rosca e geometria intactas) | Peça majoritariamente marrom |
| `unusable` | inutilizável | **Dano funcional:** rosca espanada ou amassada, haste torta, cabeça/fenda destruída, trinca, porca deformada, **ou** corrosão que impede o uso (rosca tomada por crosta) | Parafuso entortado no torno de bancada |

**Precedência:** se houver qualquer dano funcional, o grau é `unusable`, independentemente da ferrugem. A seguir, crosta ou pitting levam a `poor`, mesmo com área < 25%.

**Fonte de inspiração:** escala de enferrujamento "Ri" da ISO 4628-3 e o banco de dados UMaine Corrosion Condition Rating. Os limiares acima são do projeto e **não** reproduzem a norma.

**Calibração (piloto da S1):**
1. Cada membro rotula às cegas 30 fotos variadas.
2. Calcule o QWK entre os dois.
3. Se ficar abaixo de 0,6, discutam os casos divergentes, ajustem os textos e limiares desta tabela e repitam o processo.
4. Registre o resultado em `ml/reports/agreement.json` e no histórico de alterações abaixo.

### 1.1 Rubrica para ferramentas manuais (Fase 2, rascunho)

Mesma escala e mesma precedência. Exemplos de dano funcional:
- ponta de chave de fenda ou Phillips gasta ou arredondada;
- mordente do alicate quebrado ou desalinhado;
- rosca sem-fim da chave inglesa travada ou espanada;
- chave Allen com ponta arredondada.

A SPEC-016 finaliza esta parte.

## 2. Geração das peças (corrosão controlada)

**Material:**
- Parafusos e porcas de **aço carbono comum ou oxidado preto**, M6–M10, cerca de 40 parafusos e 40 porcas.
- **Evite zincado (prateado/amarelado) e inox:** praticamente não enferrujam em vinagre. Se só houver zincado, retire a camada antes com lixa ou com um banho prolongado de vinagre puro.
- Vinagre de álcool, sal de cozinha, potes plásticos, luvas, papel toalha e fita crepe com caneta para os IDs.
- Água oxigenada 10 volumes acelera o processo, mas é opcional. A mistura com vinagre é irritante: use luvas, ambiente ventilado e **não** guarde em pote fechado.

**Procedimento:**
1. Identifique cada peça antes de começar: `S-001`… para parafusos e `N-001`… para porcas, com fita no pote ou saquinho, **nunca** na peça (a fita apareceria na foto).
2. Separe cerca de 8 peças de cada tipo que **nunca** vão para o banho (grau `perfect`).
3. Prepare o banho: vinagre + 1 colher de sopa de sal por copo (+ água oxigenada opcional). Mergulhe por 30 a 60 min e depois deixe as peças **secando ao ar** sobre papel toalha. A ferrugem aparece na secagem.
4. Escalone: retire grupos após 6 h, 24 h e 72 h de exposição ao ar úmido. Repita o banho se necessário. A meta é ter peças em `good`, `fair` e `poor`.
5. Para `unusable`, aplique dano mecânico controlado a parte das peças, de qualquer nível de ferrugem: amassar a rosca com alicate, entortar a haste no torno de bancada, destruir a fenda, deformar a porca.
6. **Fotografe a mesma peça em vários estágios.** Isso é desejável: o `item_id` continua o mesmo e o split garante que ela fique inteira em um só conjunto.

**Começar na S1 (até 18/10).** A corrosão leva dias.

## 3. Protocolo de captura (modo coleta da borda)

- **Fundo:** folha A4 lisa (branca ou cinza-claro), sempre a mesma. Para a classe `other`, varie o fundo e o objeto.
- **Distância:** cerca de 20 cm, com a peça ocupando 40–70% da foto. Marque a posição do celular com fita na mesa.
- **Luz:** luz ambiente mais uma luminária fixa. Faça uma parte das fotos com outra luz (janela, outra lâmpada) para dar robustez. Evite flash direto, que estoura o brilho do metal.
- **Ângulos:** de 3 a 5 por peça e por estágio, de 0 a 4 (`angle`): topo, lateral, 45° e o outro lado.
- **Celulares:** os dois da dupla, em proporções parecidas.
- **Privacidade:** sem rostos nem pessoas no quadro (R-14).
- **Classe `other` (negativos):** objetos variados (moeda, tampinha, caneta, chave de casa, pregos, arruela, a mesa vazia) e, opcionalmente, as categorias do MVTec AD, respeitando a licença CC BY-NC-SA 4.0, com atribuição, para uso acadêmico. Mínimo de 150 imagens de pelo menos 30 objetos diferentes.

## 4. Metas de volume

| Tipo | Por grau | Peças físicas por grau | Total aproximado |
|---|---|---|---|
| Parafuso | ≥ 120 imagens | ≥ 12 (mínimo 8) | ≥ 600 |
| Porca | ≥ 120 imagens | ≥ 12 (mínimo 8) | ≥ 600 |
| `other` | — | ≥ 30 objetos | ≥ 150 |

Marcos de coleta:
- **S2:** cerca de 500 imagens.
- **S3:** cerca de 1.200 imagens.

Se algum grau ficar abaixo da meta, registre em `ml/reports/` e use pesos de classe.

**Por que 12 peças por grau:** com o split 70/15/15 por peça, 8 peças deixam cerca de 1 peça por grau no teste, e as métricas ficam muito instáveis. Com 12 ou mais, sobram cerca de 2. Mesmo assim, o teste é pequeno: por isso o `metrics.json` traz intervalos de confiança por bootstrap (skill `ml-pipeline`). Como a mesma peça passa por vários estágios de corrosão, a estratificação usa o grau **dominante** da peça e é aproximada; o relatório de dados mostra a distribuição real por split.

## 5. Manifest (`DATASET_DIR/manifest.csv`)

| Coluna | Tipo | Exemplo | Observação |
|---|---|---|---|
| `image_path` | str | `raw/screw/fair/S-012__2__20261022T141503Z.jpg` | relativo a `DATASET_DIR` |
| `item_id` | str | `S-012` | `^[SNOT]-\d{3}$` (S = parafuso, N = porca, O = other, T = ferramenta na Fase 2) |
| `object_type` | str | `screw` | `screw`, `nut`, `other` (+ Fase 2) |
| `grade` | str | `fair` | vazio para `other` |
| `labeler` | str | `a` ou `b` | quem rotulou |
| `angle` | int | `2` | 0–4 |
| `captured_at` | str | `2026-10-22T14:15:03Z` | UTC |
| `capture_device` | str | user-agent resumido | só para análise |
| `notes` | str | `dúvida fair/poor` | opcional |

Uma linha por imagem. As correções de rótulo **não** reescrevem a linha original: entram em `labels_overrides.csv` (`image_path,grade,labeler,reason`), aplicado pelo pipeline (SPEC-011).

## 6. Rotulagem dupla e concordância

- Sorteie 20% das imagens, estratificadas por grau. O segundo membro rotula às cegas, gerando `labels_second.csv`.
- Calcule o QWK e a matriz de confusão entre os rotuladores (script da SPEC-011) e salve em `ml/reports/agreement.json`.
- Quando os dois discordam, o rótulo final é decidido em conjunto e entra em `labels_overrides.csv`.

## 7. Split e integridade (R-11)

- O split é **agrupado por `item_id`** (`StratifiedGroupKFold` ou equivalente): 70% treino, 15% validação e 15% teste, estratificado por tipo e grau dentro do possível. A seed fica fixada e o hash do split é salvo.
- **Teste final:** congelado na primeira geração do split (S3). Novas peças entram **só** em treino e validação, salvo se a dupla decidir, com um ADR, recriar o teste.
- Opcional, mas recomendado: um teste de "condição de demo", com 50 fotos capturadas no local e no dia do ensaio (S7), relatado separadamente.

## 8. Armazenamento

- `DATASET_DIR` (padrão `ml/data/`) **não** vai para o Git.
- Backup no Google Drive pessoal de um dos membros, compactado por data, que também é a forma de levar os dados ao Colab.
- Nunca suba imagens para a nuvem do projeto (R-02).

## Histórico de alterações

| Data | Mudança | Por quê |
|---|---|---|
| 2026-10-12 | Rubrica v0 | Versão inicial |
