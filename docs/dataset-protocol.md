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

**Peças que a dupla já tem (2026-10-12):** parafusos e porcas novos, parafusos e pregos velhos e enferrujados, e ferramentas manuais.
- Os **novos** cobrem `perfect` (e `good`, se tiverem pontos de oxidação).
- Os **velhos e enferrujados** tendem a cair em `poor`/`unusable`. O grau vem **sempre da rubrica** (§1), nunca da idade da peça.
- A corrosão induzida abaixo serve principalmente para **completar `good` e `fair`**, que costumam faltar.
- **Pregos** entram como **negativos difíceis da classe `other`** (`item_id` `O-xxx`): parecem parafusos e ensinam o modelo a separar os dois. Se a dupla quiser inspecionar pregos como um tipo próprio, isso vira uma SPEC com a tag `contrato` (novo valor de enum).
- **Ferramentas** são catalogadas (`T-xxx`) e fotografadas desde já para a Fase 2 (SPEC-016), mas ficam fora do treino do MVP.
- Pode ser que uma parte das peças velhas seja zincada (prateada); ainda assim valem para `perfect`/`good`, se estiverem conservadas.


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
- **Configuração da câmera:** desligue a "foto com movimento" (Motion Photo do Android) e qualquer recurso parecido que anexe vídeo ou áudio à foto, nos dois celulares, antes de começar. Ela anexa um vídeo de alguns MB depois do fim do JPEG. Esses bytes contêm pares `FF DA` por acaso (~16 por MiB), e o `qc_preprocess.load_image` recusa todo JPEG com mais de 64 deles no arquivo (SPEC-024). A partir de ~3 a 4 MiB de vídeo, a foto é recusada. O pipeline acusa o caso com o problema `too_many_jpeg_scans` (SPEC-011). Para resolver, **refotografe** com o recurso desligado. Não corte o arquivo à mão. Isso vale para as fotos tiradas direto no app da câmera (por exemplo, antes da SPEC-010). As fotos do modo coleta passam pela página `/capture`, que reencoda a imagem e descarta tudo o que vem depois dela.
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

Uma imagem que precisa **sair** do dataset (por exemplo, com uma pessoa no quadro) também não reescreve o manifest: o arquivo é apagado e o `image_path` entra em `exclusions.csv` (`image_path,reason`, com `reason` igual a `person` ou `other`), no mesmo diretório do manifest. O pipeline tira essas linhas antes de validar e de gerar o split (SPEC-011). O passo a passo está na §8.1.

**Não abra o `manifest.csv` numa planilha** (LibreOffice, Google Planilhas): um `notes` que comece com `=`, `+`, `-` ou `@` pode ser avaliado como fórmula. Para ler, use o pandas ou o `csv` do Python. Se for inevitável, importe **todas** as colunas como texto e nunca salve o arquivo pela planilha (SEC-10-04 de `reviews/SPEC-010/r1-security-report.md`). Pelo mesmo motivo, não conte linhas com `wc -l` nem `grep`: textos antigos podem ter separadores de linha Unicode (SEC-10-03).

## 6. Rotulagem dupla e concordância

- Sorteie 20% das imagens, estratificadas por grau. O segundo membro rotula às cegas, gerando `labels_second.csv`.
- Calcule o QWK e a matriz de confusão entre os rotuladores (script da SPEC-011) e salve em `ml/reports/agreement.json`.
- Quando os dois discordam, o rótulo final é decidido em conjunto e entra em `labels_overrides.csv`.

## 7. Split e integridade (R-11)

- O split é **agrupado por `item_id`** (`StratifiedGroupKFold` ou equivalente): 70% treino, 15% validação e 15% teste, estratificado por tipo e grau dentro do possível. A seed fica fixada e o hash do split é salvo.
- **Teste final:** congelado na primeira geração do split (S3). Novas peças entram **só** em treino e validação, salvo se a dupla decidir, com um ADR, recriar o teste.
- **Imagem excluída (§8.1):** sai do split seguinte, inclusive do teste, com o aviso `excluded_previous_image` no `split_v<N>.json` (SPEC-011). Isso não é recriar o teste: nenhuma imagem muda de conjunto, e a exclusão é decidida pela foto (R-14), nunca pelo resultado do modelo. O relatório de métricas cita o aviso.
- **Uma peça nunca muda de conjunto:** a peça que já esteve em treino, validação ou teste, em **qualquer** versão do split, continua nesse conjunto em todas as versões seguintes. Isso vale mesmo que todas as fotos dela tenham sido excluídas, um split tenha sido gerado sem ela e ela volte refotografada com o mesmo `item_id` (§2, passo 6). Para isso, o `python -m qc_ml.split` lê **todos** os `split_v*` anteriores e confere o hash de cada um (SPEC-011 §4.4). Ele sai com erro, sem gravar nada, se faltar uma versão na numeração, se um hash não conferir ou se uma peça aparecer em dois conjuntos ao longo das versões.
- **Os `split_v*` antigos não se apagam nem se editam.** Se um faltar ou não conferir, restaure-o do Git. Um conflito de peça entre versões indica split editado à mão ou `item_id` reaproveitado para outra peça física: pare e investigue. Corrigir um split antigo que mexa no teste é recriar o teste e exige ADR.
- Opcional, mas recomendado: um teste de "condição de demo", com 50 fotos capturadas no local e no dia do ensaio (S7), relatado separadamente.

## 8. Armazenamento

- `DATASET_DIR` (padrão `ml/data/`) **não** vai para o Git.
- Backup no Google Drive pessoal de um dos membros, compactado por data, que também é a forma de levar os dados ao Colab.
- Nunca suba imagens para a nuvem do projeto (R-02).
- No notebook, o modo coleta cria os diretórios de `DATASET_DIR` com `0700` e os arquivos com `0600` (SPEC-010).

**Antes do primeiro backup no Drive (prazo, SEC-10-01 e SEC-10-08 de `reviews/SPEC-010/r1-security-report.md`).** O primeiro backup no Drive só acontece **depois** do merge da SPEC-025, que grava as fotos da coleta sem EXIF (GPS, aparelho, data), XMP e trailer (vídeo do Motion Photo) e traz a varredura abaixo. Até lá:
- a cópia de segurança fica só em mídia local da dupla (disco externo ou pendrive), nunca no Drive nem em outro serviço;
- coletar só pela página `/capture`, que reencoda a foto pelo canvas e já descarta os metadados; não enviar fotos à rota por script nem copiar fotos do app da câmera para `raw/`.

**Antes de cada backup no Drive** (inclusive o primeiro):
1. `uv run --package qc-edge python -m qc_edge.privacy --dataset-dir ml/data` → `0 with private data`. Se houver achados, repetir com `--fix` e rodar de novo sem `--fix`. Um arquivo `invalid` é apagado e registrado em `exclusions.csv` (§8.1, `reason=other`). O mesmo vale para um arquivo `orientation`, que o `--fix` não corrige: é uma foto com rotação EXIF (o normal numa foto em retrato do app da câmera), e tirar o EXIF dela faria o treino lê-la girada (SPEC-025 §4.8). Refotografe a peça pela página `/capture`;
2. depois da SPEC-011: `uv run --package qc-ml python -m qc_ml.data validate --dataset-dir ml/data` sem problemas (nenhum `orphan_image`, `missing_file` nem `excluded_file_present`);
3. conferir que nenhuma foto nova tem pessoa no quadro (R-14); se tiver, seguir a §8.1 antes de compactar;
4. compactar `ml/data/` inteiro (com `manifest.csv`, `labels_overrides.csv` e `exclusions.csv`) e subir o arquivo com a data no nome.

### 8.1 Remover uma foto do dataset (pessoa no quadro, R-14)

Quem notar uma foto com pessoa identificável no dataset (ou outra foto que precise sair):
1. apagar o arquivo: `rm ml/data/<image_path>`;
2. acrescentar a linha `<image_path>,person` (ou `,other`) a `ml/data/exclusions.csv`, criando o arquivo com o cabeçalho `image_path,reason` se ele não existir. Não editar nem apagar a linha do `manifest.csv`;
3. rodar `python -m qc_ml.data validate` (depois da SPEC-011): não pode haver `excluded_file_present`;
4. **backups:** apagar do Drive todo arquivo compactado que contenha a foto, subir um novo, gerado depois do passo 1, e excluir os antigos de forma permanente na lixeira do Drive. Pela ajuda do Google Drive, um arquivo na lixeira "continua ocupando espaço" e só é excluído de forma permanente "após 30 dias", e quem tinha acesso compartilhado continua com acesso até a exclusão definitiva (<https://support.google.com/drive/answer/2375102?hl=pt-BR>, consultado em 2026-10-17). Apagar também as cópias locais (pendrive, disco externo) e, se houver, a cópia descompactada no Colab;
5. se a foto estava no split de teste, o próximo `python -m qc_ml.split` a tira do teste com o aviso `excluded_previous_image` (§7). Se a peça for refotografada depois, com o mesmo `item_id`, as fotos novas voltam ao conjunto em que ela estava. Isso vale também quando o split foi gerado entre a exclusão e a refotografia (§7, "Uma peça nunca muda de conjunto").

## 9. Fotos de inspeção (`EDGE_DATA_DIR/captures/`)

As fotos do modo inspeção são outra coisa: servem para conferir uma inspeção depois, e não para treinar.

- **Não fazem parte do dataset.** Não têm rótulo humano nem `item_id`. Nunca são copiadas para `DATASET_DIR` nem para o backup do Drive (§8). O dataset só cresce pelo modo coleta (§3).
- **Ficam só no notebook da borda** (R-02), com diretórios `0700` e arquivos `0600` (SPEC-025). O nome do arquivo é o `inspection_id`, o que permite achar a foto de uma inspeção mostrada no dashboard.
- **Pessoa no quadro (R-14):** uma foto com pessoa identificável é apagada assim que for notada (`rm <EDGE_DATA_DIR>/captures/<AAAA-MM-DD>/<inspection_id>.jpg`). O registro na nuvem não muda, porque não contém imagem.
- **Retenção:** as fotos ficam guardadas até a entrega do projeto (04/12/2026). Depois da apresentação, a dupla apaga a pasta inteira (`rm -rf <EDGE_DATA_DIR>/captures`). Entre as sessões, a pasta pode ser limpa a qualquer momento: nada na borda nem na nuvem depende dela.

## Histórico de alterações

| Data | Mudança | Por quê |
|---|---|---|
| 2026-10-12 | Rubrica v0 | Versão inicial |
| 2026-10-12 | Uso das peças existentes; pregos como `other` | A dupla já tem peças novas e enferrujadas, pregos e ferramentas |
| 2026-10-12 | §3: desligar a "foto com movimento" e recursos parecidos na câmera | O vídeo anexado ao JPEG faz o `load_image` recusar a foto pelo limite de marcadores de scan (SEC-24-03 de `reviews/SPEC-024/r1-security-report.md`) |
| 2026-10-13 | §8: permissões do `DATASET_DIR`; §9 nova: fotos de inspeção fora do dataset, permissões, remoção de foto com pessoa e retenção até a entrega (04/12/2026) | SEC-06 de `reviews/SPEC-007/r1-security-report.md` (R-14) |
| 2026-10-17 | §5: `exclusions.csv` e aviso de não abrir o manifest em planilha nem contar linhas com `wc -l`/`grep`; §7: imagem excluída sai do split, inclusive do teste, sem recriar o teste; §8: primeiro backup no Drive só depois do merge da SPEC-025 (até lá, cópia só local e coleta só pela página) e checklist antes de cada backup (`python -m qc_edge.privacy`, `validate`, conferência visual); §8.1 nova: remoção de foto do dataset e dos backups | SEC-10-01, SEC-10-03, SEC-10-04 e SEC-10-08 de `reviews/SPEC-010/r1-security-report.md` (R-14) |
| 2026-10-18 | §8, passo 1: o achado `orientation` (foto com rotação EXIF) não é corrigido pelo `--fix`; a foto é apagada, registrada em `exclusions.csv` e refeita pela página `/capture` | SPEC_ISSUE-01 de `reviews/SPEC-025/r1-review-report.md` (paridade treino/borda, ADR-004) |
| 2026-10-18 | §7: uma peça nunca muda de conjunto em relação a qualquer versão anterior do split (o split lê e confere todos os `split_v*`); os `split_v*` antigos não se apagam nem se editam. §8.1, passo 5: a peça refotografada volta ao conjunto em que estava, mesmo com um split gerado entre a exclusão e a refotografia | SPEC_ISSUE-01 de `reviews/SPEC-011/r2-review-report.md` (T-02: a peça de teste voltava como peça nova e ia para o treino, contra a R-11 e o ADR-014) |
