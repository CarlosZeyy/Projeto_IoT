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

### 1.1 Rubrica para ferramentas manuais (Fase 2, SPEC-016)

Vale a partir do merge da SPEC-016 (Parte A), quando o modo coleta passa a aceitar as ferramentas (`T-…`). Texto da SPEC-016 §4.11, que é a fonte.

| Grau | Critério para ferramentas manuais |
|---|---|
| `perfect` | sem oxidação nem desgaste visível |
| `good` | oxidação em pontos isolados (< 5% da área) ou marcas leves de uso; tudo funciona |
| `fair` | oxidação superficial em 5–25% da área, sem crosta; tudo funciona |
| `poor` | oxidação em > 25% da área, crosta ou pitting; ainda funciona |
| `unusable` | dano funcional: ponta de chave de fenda ou Phillips gasta ou arredondada; mordente do alicate quebrado ou desalinhado; rosca sem-fim da chave inglesa travada ou espanada; chave Allen com ponta arredondada |

Mesma precedência do §1 (dano funcional primeiro). O protocolo de captura das ferramentas está no §3.

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
- **Classe `other` (negativos):** objetos variados (moeda, tampinha, caneta, chave de casa, pregos, arruela, a mesa vazia) e, opcionalmente, imagens públicas com licença da lista da §10.4, importadas por ela: só no treino e com a fonte registrada. Mínimo de 150 imagens de pelo menos 30 objetos diferentes, **sem contar as externas**.
- **Fotos que não passam pela página** (de conhecidos ou de datasets públicos): só pela importação da §10, nunca copiadas para `raw/`.
- **Ferramentas manuais (Fase 2, SPEC-016 §4.11; vale a partir do merge da SPEC-016, Parte A):** fundo liso maior que a ferramenta (cartolina ou A3), a ferramenta ocupando 40–70% da foto (cerca de 30 a 50 cm), de 3 a 5 ângulos, sem mãos nem pessoas no quadro (R-14). O grau segue a rubrica do §1.1.

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

**O que conta para as metas** (ADR-020): as fotos da página e as de conhecidos (peças físicas reais, §10.2). As imagens externas (§10.4) **não** contam: cada uma é uma "peça" sem relação com as peças da dupla, e elas nunca vão para a validação nem para o teste. O relatório de dados (SPEC-035) e a tabela de cobertura do console (SPEC-036) já as separam.

**Por que 12 peças por grau:** com o split 70/15/15 por peça, 8 peças deixam cerca de 1 peça por grau no teste, e as métricas ficam muito instáveis. Com 12 ou mais, sobram cerca de 2. Mesmo assim, o teste é pequeno: por isso o `metrics.json` traz intervalos de confiança por bootstrap (skill `ml-pipeline`). Como a mesma peça passa por vários estágios de corrosão, a estratificação usa o grau **dominante** da peça e é aproximada; o relatório de dados mostra a distribuição real por split.

## 5. Manifest (`DATASET_DIR/manifest.csv`)

| Coluna | Tipo | Exemplo | Observação |
|---|---|---|---|
| `image_path` | str | `raw/screw/fair/S-012__2__20261022T141503Z.jpg` | relativo a `DATASET_DIR` |
| `item_id` | str | `S-012` | `^[SNOT]-\d{3}$` (S = parafuso, N = porca, O = other, T = ferramenta na Fase 2). A partir da SPEC-035, também `^X[SNOT]-\d{4}$` para as imagens externas (§10.3) |
| `object_type` | str | `screw` | `screw`, `nut`, `other` (+ Fase 2) |
| `grade` | str | `fair` | vazio para `other` |
| `labeler` | str | `a` ou `b` | quem rotulou |
| `angle` | int | `2` | 0–4 |
| `captured_at` | str | `2026-10-22T14:15:03Z` | UTC |
| `capture_device` | str | user-agent resumido | só para análise |
| `notes` | str | `dúvida fair/poor` | opcional |

Uma linha por imagem. Numa imagem importada (§10), `captured_at` é o instante da importação, e não o da foto (o EXIF é descartado), e `capture_device` é `qc-edge-import`.

**Origem da imagem (`sources.csv`, a partir das SPECs 035 e 036).** O manifest não muda. A importação grava, no mesmo diretório, uma linha de `sources.csv` por imagem importada: `image_path,origin,contributor,source_id,source_ref,input_sha256`, com `origin` igual a `contributor` (foto de conhecido, `contributor` = código `c01`, `c02`…) ou `external` (imagem externa, `source_id` = a fonte em `ml/external_sources.csv` e `source_ref` = o arquivo dentro da fonte). A imagem sem linha em `sources.csv` veio da página (`capture`). O `input_sha256` é o hash do arquivo recebido e impede importar o mesmo arquivo duas vezes. O formato completo está na SPEC-035 §4.2. Nunca edite o `sources.csv` à mão.

As correções de rótulo **não** reescrevem a linha original: entram em `labels_overrides.csv` (`image_path,grade,labeler,reason`), aplicado pelo pipeline (SPEC-011).

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
- **Origem da imagem** (ADR-020, SPEC-035):
  - as **fotos de conhecidos** seguem as mesmas regras das peças da dupla. Só as importadas **antes** do `split_v1` podem cair no teste; as importadas depois são peças novas e vão para treino e validação;
  - as **imagens externas** (`item_id` `X…`) vão **sempre** para o treino, em todas as versões do split, e ficam fora da estratificação. O split sai com erro se uma delas aparecer em validação ou teste em qualquer versão, e se a fração delas no treino passar do teto (padrão 30%, registrado no `split_v<N>.json`).
- Opcional, mas recomendado: um teste de "condição de demo", com 50 fotos capturadas no local e no dia do ensaio (S7), relatado separadamente.

## 8. Armazenamento

- `DATASET_DIR` (padrão `ml/data/`) **não** vai para o Git.
- Backup no Google Drive pessoal de um dos membros, compactado por data, que também é a forma de levar os dados ao Colab.
- Nunca suba imagens para a nuvem do projeto (R-02).
- No notebook, o modo coleta cria os diretórios de `DATASET_DIR` com `0700` e os arquivos com `0600` (SPEC-010).

**Antes do primeiro backup no Drive (prazo, SEC-10-01 e SEC-10-08 de `reviews/SPEC-010/r1-security-report.md`).** O primeiro backup no Drive só acontece **depois** do merge da SPEC-025, que grava as fotos da coleta sem EXIF (GPS, aparelho, data), XMP e trailer (vídeo do Motion Photo) e traz a varredura abaixo. Até lá:
- a cópia de segurança fica só em mídia local da dupla (disco externo ou pendrive), nunca no Drive nem em outro serviço;
- coletar só pela página `/capture`, que reencoda a foto pelo canvas e já descarta os metadados; não enviar fotos à rota por script nem copiar fotos do app da câmera para `raw/`. A partir do merge das SPECs 035 e 036, a importação (§10) é o único outro caminho de entrada.

**Antes de cada backup no Drive** (inclusive o primeiro):
1. `uv run --package qc-edge python -m qc_edge.privacy --dataset-dir ml/data` → `0 with private data`. Se houver achados, repetir com `--fix` e rodar de novo sem `--fix`. Um arquivo `invalid` é apagado e registrado em `exclusions.csv` (§8.1, `reason=other`). O mesmo vale para um arquivo `orientation`, que o `--fix` não corrige: é uma foto com rotação EXIF (o normal numa foto em retrato do app da câmera), e tirar o EXIF dela faria o treino lê-la girada (SPEC-025 §4.8). Refotografe a peça pela página `/capture`. **Até o merge da SPEC-030** (SEC-25-01 e SEC-25-02 de `reviews/SPEC-025/r2-security-report.md`): confira também o código de saída da varredura (`echo $?` logo depois dela → `0`), e não só a última linha, porque um nome de arquivo com controles pode imitar o resumo; e confira que `find ml/data/raw -type f ! -name '*.jpg'` não lista nada, porque hoje a varredura não confere `.JPG`, `.jpeg` nem outras extensões. Só copie para `raw/` arquivos renomeados para `.jpg` em minúsculas;
2. depois da SPEC-011: `uv run --package qc-ml python -m qc_ml.data validate --dataset-dir ml/data` sem problemas (nenhum `orphan_image`, `missing_file` nem `excluded_file_present`);
3. conferir que nenhuma foto nova tem pessoa no quadro (R-14); se tiver, seguir a §8.1 antes de compactar;
4. compactar `ml/data/` inteiro (com `manifest.csv`, `labels_overrides.csv`, `exclusions.csv` e `sources.csv`) e subir o arquivo com a data no nome. A pasta de entrada da importação (§10.6) **nunca** entra no backup: os arquivos dela têm EXIF.

### 8.1 Remover uma foto do dataset (pessoa no quadro, R-14)

Quem notar uma foto com pessoa identificável no dataset (ou outra foto que precise sair):
1. apagar o arquivo: `rm ml/data/<image_path>`;
2. acrescentar a linha `<image_path>,person` (ou `,other`) a `ml/data/exclusions.csv`, criando o arquivo com o cabeçalho `image_path,reason` se ele não existir. Não editar nem apagar a linha do `manifest.csv`;
3. rodar `python -m qc_ml.data validate` (depois da SPEC-011): não pode haver `excluded_file_present`;
4. **backups:** apagar do Drive todo arquivo compactado que contenha a foto, subir um novo, gerado depois do passo 1, e excluir os antigos de forma permanente na lixeira do Drive. Pela ajuda do Google Drive, um arquivo na lixeira "continua ocupando espaço" e só é excluído de forma permanente "após 30 dias", e quem tinha acesso compartilhado continua com acesso até a exclusão definitiva (<https://support.google.com/drive/answer/2375102?hl=pt-BR>, consultado em 2026-10-17). Apagar também as cópias locais (pendrive, disco externo) e, se houver, a cópia descompactada no Colab;
5. se a foto estava no split de teste, o próximo `python -m qc_ml.split` a tira do teste com o aviso `excluded_previous_image` (§7). Se a peça for refotografada depois, com o mesmo `item_id`, as fotos novas voltam ao conjunto em que ela estava. Isso vale também quando o split foi gerado entre a exclusão e a refotografia (§7, "Uma peça nunca muda de conjunto").

## 9. Fotos de inspeção (`EDGE_DATA_DIR/captures/`)

As fotos do modo inspeção são outra coisa: servem para conferir uma inspeção depois, e não para treinar.

- **Não fazem parte do dataset.** Não têm rótulo humano nem `item_id`. Nunca são copiadas para `DATASET_DIR` nem para o backup do Drive (§8), nem importadas pela §10. O dataset só cresce pelo modo coleta (§3) e pela importação de fotos de conhecidos e de imagens externas (§10).
- **Ficam só no notebook da borda** (R-02), com diretórios `0700` e arquivos `0600` (SPEC-025). O nome do arquivo é o `inspection_id`, o que permite achar a foto de uma inspeção mostrada no dashboard.
- **Pessoa no quadro (R-14):** uma foto com pessoa identificável é apagada assim que for notada (`rm <EDGE_DATA_DIR>/captures/<AAAA-MM-DD>/<inspection_id>.jpg`). O registro na nuvem não muda, porque não contém imagem.
- **Retenção:** as fotos ficam guardadas até a entrega do projeto (04/12/2026). Depois da apresentação, a dupla apaga a pasta inteira (`rm -rf <EDGE_DATA_DIR>/captures`). Entre as sessões, a pasta pode ser limpa a qualquer momento: nada na borda nem na nuvem depende dela.

## 10. Fotos que não vêm da página `/capture` (ADR-020)

Vale a partir do merge das SPECs 035 e 036. Até lá, nenhum arquivo recebido entra em `ml/data/`: guarde-o só na pasta de entrada (§10.6).

### 10.1 Origens

| Origem | O que é | Splits | Conta para as metas (§4) |
|---|---|---|---|
| `capture` | foto da página `/capture`, pela dupla | treino, validação e teste (§7) | sim |
| `contributor` | foto de um conhecido, tirada em outro celular e recebida como arquivo | treino, validação e teste (§7); teste só se importada antes do `split_v1` | sim |
| `external` | imagem de dataset público ou da internet, com licença aceita | **só treino**, sempre | não |

Em todas as origens, o `item_id` e o grau são decididos pela dupla, com a rubrica (§1). Nunca use o rótulo de quem fotografou nem o da fonte externa.

### 10.2 Fotos de conhecidos

- **Peça física:** cada peça do conhecido é uma peça nova, com `item_id` novo (§10.3). A mesma peça em vários ângulos ou estágios mantém o `item_id`, como no §2, passo 6. Se a peça for depois entregue à dupla, ela continua com o mesmo `item_id` nas fotos da página.
- **Guia para quem fotografa** (mandar junto com o pedido): fundo liso e claro (uma folha A4), cerca de 20 cm, peça ocupando boa parte da foto, sem flash, de 3 a 5 ângulos, **sem pessoas, mãos com anel ou tatuagem, rostos, documentos, telas ou endereços no quadro**. Enviar pelo WhatsApp como **documento** (a opção "foto" comprime). No iPhone, usar o formato "Mais compatível" (JPEG), porque o HEIC é recusado.
- **Consentimento:** antes de usar, explicar ao conhecido que a foto é para um projeto acadêmico, fica só no notebook e nos backups pessoais da dupla, perde os metadados (localização, aparelho, data) e pode ser retirada até a entrega (04/12/2026). O "sim" fica na própria conversa; nada disso entra no repositório.
- **Código do conhecido:** cada conhecido recebe um código `c01`, `c02`… (coluna `contributor`). A relação entre código e pessoa fica só com a dupla, fora do repositório e fora de `ml/data/`. Nenhum nome, telefone ou apelido entra no dataset, no plano de importação ou num relatório.

### 10.3 Numeração (`item_id`)

| Faixa | Uso | Regra |
|---|---|---|
| `S-001`…`S-499`, `N-001`…`N-499`, `O-001`…`O-499` | peças da dupla | recomendação |
| `S-500`…`S-999`, `N-500`…`N-999`, `O-500`…`O-999` | peças de conhecidos | recomendação: deixa claro no catálogo de quem é a peça |
| `XS-0001`…`XS-9999`, `XN-…`, `XO-…` | imagens externas | **obrigatória** (SPEC-035): o prefixo `X` decide sozinho que a imagem fica no treino |
| `T-…`, `XT-…` | ferramentas (Fase 2) | recusadas até a SPEC-016; as fotos ficam na pasta de entrada |

Cada imagem externa é, em geral, uma "peça" própria (`XS-0001`, `XS-0002`…). Se a fonte tiver várias fotos do mesmo objeto, elas podem dividir o `item_id`.

### 10.4 Imagens externas

- **Licença:** só as da lista da SPEC-035 §4.3 (`CC0-1.0`, `PDDL-1.0`, `CC-BY-4.0`, `MIT`, `Apache-2.0`, `BSD-3-Clause`). Nada NonCommercial nem ShareAlike (`CC-BY-NC-4.0`, `CC-BY-SA-4.0`, `CC-BY-NC-SA-4.0`, ODbL), porque o modelo é publicado num Release público (ADR-020, decisão do humano de 2026-10-23). Nada "NoDerivatives", "desconhecida", "todos os direitos reservados" ou "coletado da internet" sem licença por imagem. Confira a licença na **página oficial** da fonte, e não num espelho.
- **Registro antes de importar:** acrescente a fonte a `ml/external_sources.csv` (título, URL, licença, URL da licença, texto de crédito e data da consulta) por um PR. É o arquivo de atribuições do projeto. Uma fonte nunca sai do registro, mesmo que as imagens dela saiam.
- **Escolha:** a SPEC-035, Anexo A, lista as fontes avaliadas em 2026-10-20 e marca as não permitidas. Nenhuma tem os 5 graus. As mais úteis entre as permitidas: corrosão real (SDNET 2025 → `fair`/`poor` pela rubrica), peças sem defeito para `perfect` e pregos e arruelas para `other`. Nenhuma fonte permitida avaliada traz dano funcional: o `unusable` vem só das peças da dupla e de conhecidos (§2, passo 5). Não importe duas cópias da mesma fonte (ex.: um dataset e um espelho dele no Kaggle).
- **Datasets de detecção** (várias peças por foto): recorte cada peça **fora** de `ml/data/`, na pasta de entrada, e use como `source_ref` o arquivo original e o número da caixa (ex.: `images/0042.jpg#3`).
- **Complemento, não base:** o split recusa mais de 30% de imagens externas no treino (padrão). Elas não contam para as metas (§4).

### 10.5 Privacidade (R-14): o que é automático e o que é humano

| Verificação | Quem faz |
|---|---|
| Tirar EXIF (GPS, aparelho, data), XMP, IPTC, comentários e o vídeo da "foto com movimento" | automático: a importação reencoda a foto sem metadados e confere o resultado (SPEC-036 §4.3) |
| Rotação, tamanho (lado maior em até 1280 px), formato (só JPEG e PNG) e limites de pixels e de scans | automático (SPEC-036 §4.3) |
| Conferir o dataset gravado antes de cada backup | automático: `python -m qc_edge.privacy` (§8) |
| Pessoa, rosto, mão identificável, documento, tela, placa, endereço ou reflexo no quadro | **humano**, antes da importação, olhando cada foto no tamanho real. A importação exige `--privacy-checked` como confirmação de que isso foi feito |
| Consentimento do conhecido e retirada | **humano** (§10.2 e §10.7) |
| Licença e crédito da fonte externa | **humano**, ao registrar a fonte (§10.4); a importação recusa fonte sem registro ou com licença fora da lista |

### 10.6 Passo a passo da importação

1. Salve os arquivos recebidos numa **pasta de entrada fora de `ml/data/`** (ex.: `~/partqc-entrada/`). A importação recusa uma pasta de entrada dentro do dataset.
2. Olhe cada foto (§10.5). Uma foto com pessoa, documento ou endereço não é importada: apague-a.
3. Preencha o plano CSV (`file,item_id,object_type,grade,labeler,angle,origin,contributor,source_id,source_ref,notes`, exemplo no `edge/README.md`). Se usar planilha, exporte como CSV UTF-8 e confira as células de `notes` e `source_ref` que começam com `=`, `+`, `-` ou `@` (§5).
4. `uv run --package qc-edge python -m qc_edge.importer --dataset-dir ml/data --inbox <pasta> --plan <plano> --privacy-checked --dry-run` e confira as linhas `failed`.
5. Rode sem `--dry-run`. Se parar no meio, rode de novo: o que já entrou é pulado.
6. `python -m qc_edge.privacy --dataset-dir ml/data` (`0 with private data`) e `python -m qc_ml.data validate --dataset-dir ml/data` (sem problemas).
7. Apague os arquivos da pasta de entrada (e as cópias baixadas no celular). Eles têm EXIF e nunca entram no backup (§8).

### 10.7 Remoção e retirada

- **Uma foto importada que precisa sair:** como qualquer outra (§8.1). A linha de `sources.csv` fica e é ignorada.
- **Um conhecido pede para retirar as fotos:** todas as imagens com o código dele em `sources.csv` (e todas as fotos das peças dele) seguem a §8.1, com `reason=other`, inclusive nos backups. Se alguma estava no teste, o split seguinte a tira com o aviso `excluded_previous_image` (§7), sem recriar o teste.
- **A licença de uma fonte externa muda ou é contestada:** todas as imagens dessa `source_id` seguem a §8.1 (`reason=other`); a fonte continua no registro, e o modelo seguinte é treinado sem ela.
- **`missing_source` no `validate`** (uma queda de energia entre a gravação do manifest e a do `sources.csv`): siga a §8.1 para essa imagem e importe o arquivo de novo.

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
| 2026-10-19 | §8, passo 1: até o merge da SPEC-030, conferir o código de saída da varredura e o `find ml/data/raw -type f ! -name '*.jpg'` antes de cada backup | SEC-25-01 e SEC-25-02 de `reviews/SPEC-025/r2-security-report.md` (R-14): a varredura imprime o nome cru e não confere `.JPG`/`.jpeg` |
| 2026-10-20 | §10 nova: fotos de conhecidos e imagens externas (origens, guia e consentimento, numeração com o prefixo `X` para as externas, licenças, registro de fontes, privacidade automática e humana, passo a passo da importação, retirada). §3: `other` com imagens públicas só pela importação; §4: externas não contam para as metas; §5: `item_id` externo, `captured_at` e `capture_device` das importadas e `sources.csv`; §7: externas sempre no treino e fotos de conhecidos no teste só antes do `split_v1`; §8: `sources.csv` no backup, pasta de entrada nunca; §9: o dataset cresce também pela importação | Decisão do humano de 2026-10-19; ADR-020 (`Proposto`), SPECs 035 e 036 (`Draft`). Vale a partir do merge das duas SPECs |
| 2026-10-23 | §10.4: lista de licenças sem NonCommercial nem ShareAlike (`CC0-1.0`, `PDDL-1.0`, `CC-BY-4.0`, `MIT`, `Apache-2.0`, `BSD-3-Clause`); "Escolha" sem o MVTec AD (o `unusable` fica sem fonte externa permitida). §3: classe `other` sem o MVTec AD como exemplo | Decisão do humano de 2026-10-23 (o `model.onnx` é publicado num Release público; ADR-020, decisão 3). Architect, a pedido do humano |
| 2026-10-24 | §1.1: a rubrica das ferramentas manuais deixa de ser rascunho e passa a ser o texto da SPEC-016 §4.11 (tabela por grau, mesma precedência do §1). §3: protocolo de captura das ferramentas manuais (SPEC-016 §4.11). Vale a partir do merge da SPEC-016 (Parte A). As ferramentas elétricas (SPEC-021, Fase 3) não entram aqui agora: a SPEC-021 não manda copiar a captura delas na aprovação, e a Fase 3 só roda depois do portão da Fase 2. Limpeza de consistência pós-aprovação, sem mudança de requisito | SPEC-016 `Ready` desde o PR #45 (2026-10-24); a §4.11 dela manda copiar o texto para cá quando ela virasse `Ready`. Architect, a pedido do orquestrador |
