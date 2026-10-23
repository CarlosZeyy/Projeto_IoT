# ADR-020: Admitir no dataset fotos de conhecidos e imagens externas licenciadas, com as externas só no treino

| Campo | Valor |
|---|---|
| Status | Proposto |
| Data | 2026-10-20 |
| Decisores | Dupla (decisão do humano, Carlos, em 2026-10-19, e lista de licenças em 2026-10-23; redigido pelo agente architect) |
| Relacionados | ADR-001 (a consequência sobre o uso opcional do MVTec AD deixa de valer, decisão 3), ADR-003, ADR-004, ADR-014 (complementado, não substituído), SPEC-010, SPEC-011, SPEC-012, SPEC-016, SPEC-025, SPEC-035, SPEC-036, R-02, R-11, R-13, R-14, N-11 |

## Contexto

Até aqui, o dataset só cresce pela página `/capture` (modo coleta, SPEC-010; `docs/dataset-protocol.md` §9). Em 2026-10-19, o humano decidiu que a dupla não vai tirar todas as fotos por ela:

1. **Fotos de conhecidos**, tiradas em outros celulares e recebidas como arquivo (por exemplo, pelo WhatsApp como "documento"). Valem como fotos próprias: podem ir para treino, validação e teste, seguindo a R-11. O `item_id` e o grau são atribuídos pela dupla com a rubrica, nunca por quem fotografou.
2. **Imagens de datasets públicos ou da internet**, só com licença que permita uso acadêmico e com a fonte e a licença registradas. Entram **só no treino**, nunca na validação nem no teste, porque o teste final tem de refletir a demo. São complemento, não base.

Fatos que pesam na decisão:

- Uma foto recebida como documento chega como saiu do celular: JPEG de 12 a 50 MP, de 3 a 15 MB, com EXIF (GPS, aparelho, data), quase sempre com a rotação na tag `Orientation` e, nos Android com "foto com movimento", com um vídeo depois do EOI. A rota de coleta recusa tudo isso: aceita no máximo 3 MiB e 4 M pixels (SPEC-007 §4.7) e recusa com 415 a rotação EXIF (SPEC-025 §4.8). O `qc_preprocess.load_image` recusa mais de 40 M pixels e mais de 64 marcadores de scan (SPEC-024), o que inclui boa parte das fotos com vídeo anexado.
- A página `/capture` não grava a foto original: o canvas aplica a rotação, reduz o lado maior a 1280 px e reencoda em JPEG q=0,9 (`docs/architecture.md` §6.1, ADR-003). As fotos da demo passam pelo mesmo caminho.
- O manifest tem 9 colunas fixas, e a borda recusa um manifest com outro cabeçalho (SPEC-010 §4.2). Acrescentar colunas exige reescrever todas as linhas já gravadas, senão a SPEC-011 acusa `malformed_row`.
- Nenhum dataset público encontrado tem os 5 graus da rubrica. O mais próximo do problema (MVTec AD, `screw` e `metal_nut`) é CC BY-NC-SA 4.0 (<https://www.mvtec.com/company/research/datasets/mvtec-ad>, consultado em 2026-10-20), e por isso fica fora da lista de licenças (decisão 3). A tabela das fontes avaliadas está na SPEC-035, Anexo A.
- O `model.onnx` é publicado num GitHub Release público (SPEC-012 §4.9), que qualquer pessoa pode baixar e reutilizar, inclusive para fins comerciais. Isso não combina com uma fonte NonCommercial (CC BY-NC, CC BY-NC-SA). E não está assentado se um modelo treinado com uma fonte ShareAlike (CC BY-SA, CC BY-NC-SA) é "material adaptado" que herda a licença. Por esses dois motivos, o humano excluiu as NonCommercial e as ShareAlike em 2026-10-23 (decisão 3).

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) Fotos de conhecidos como peças comuns; externas com `item_id` próprio (`X<tipo>-NNNN`), sempre no treino; origem e fonte num arquivo à parte (`sources.csv`), com o manifest inalterado; importação que normaliza a imagem como a página `/capture` | O teste e a validação continuam só do domínio da demo; a regra de integridade depende só do `item_id`, que já está em toda linha; o modo coleta e os testes das SPECs 010 e 025 não mudam; fotos de celulares diferentes ficam no mesmo formato das da página | Mais um arquivo para manter coerente com o manifest; a ligação entre os dois arquivos não é atômica (uma queda de energia entre as gravações deixa a foto sem origem, o que a validação acusa nas externas) |
| B Externas em treino **e** validação (o rascunho da SPEC-016 §4) | Mais dados para escolher época e limiares | Os limiares (`decision.json`) e o early stopping passam a ser escolhidos num domínio que não é o da demo; contraria a decisão do humano |
| C Nenhuma imagem externa | Nada muda | Recusa o pedido do humano; `other` e `perfect` continuam dependendo só das fotos da dupla |
| D Colunas novas no manifest (`origin`, `license`, `source_url`) | Um arquivo só | Exige migrar o manifest inteiro (as linhas antigas têm 9 campos) e mudar o cabeçalho que a borda confere; a licença e a URL se repetiriam em cada linha de uma mesma fonte |
| E Gravar os bytes recebidos sem os segmentos privados, como a rota de coleta (SPEC-025), e recusar a rotação EXIF | Reaproveita a regra existente | Recusaria a maior parte das fotos de celular (rotação EXIF, mais de 4 M pixels, vídeo anexado); e as fotos aceitas teriam outra resolução e outra compressão que as da página e as da demo |

## Decisão

1. **Fotos de conhecidos** são peças físicas comuns (`S-`, `N-`, `O-` com 3 dígitos), rotuladas pela dupla com a rubrica, e seguem o split por `item_id` sem regra própria. Como o teste fica congelado no `split_v1` (ADR-014), só as que forem importadas **antes** do `split_v1` podem cair no teste; as importadas depois vão para treino e validação. Recomenda-se numerá-las a partir de 500 (`S-501`), para separá-las das peças da dupla no catálogo.
2. **Imagens externas** recebem `item_id` próprio, `XS-NNNN`, `XN-NNNN` ou `XO-NNNN` (4 dígitos), e vão **sempre** para o treino, em todas as versões do split. Nunca entram na validação nem no teste: o `qc_ml.split.rows_for` recusa uma imagem externa em `val` ou `test`. Ficam fora da estratificação e das metas de volume (`docs/dataset-protocol.md` §4). A fração de imagens externas no treino tem teto de **30%** (padrão; acima dele, o split sai com erro).
3. **Licenças aceitas** (identificadores SPDX, lista fechada, decisão do humano de 2026-10-23): `CC0-1.0`, `PDDL-1.0`, `CC-BY-4.0`, `MIT`, `Apache-2.0` e `BSD-3-Clause`. Ficam **fora** as NonCommercial (NC) e as ShareAlike (SA), como `CC-BY-NC-4.0`, `CC-BY-SA-4.0` e `CC-BY-NC-SA-4.0`, porque o `model.onnx` é publicado num GitHub Release público (Contexto). Com isso, ficam fora também o MVTec AD, o MVTec Screws e os espelhos deles. Nenhuma licença "NoDerivatives" (ND), "desconhecida" ou "todos os direitos reservados". Cada fonte tem uma linha no registro `ml/external_sources.csv`, que entra no Git sem nenhuma imagem e serve de arquivo de atribuições.
4. **Formato:** o `manifest.csv` não muda. A origem e a fonte de cada imagem importada ficam em `DATASET_DIR/sources.csv`. A linha do manifest sem linha em `sources.csv` vale como `capture`.
5. **Importação:** uma CLI da borda (`python -m qc_edge.importer`, SPEC-036) é o único caminho de entrada de um arquivo que não veio da página. Ela normaliza a imagem como a página faz: aplica a rotação EXIF, reduz o lado maior a 1280 px e reencoda em JPEG q=90, sem metadados.
6. **Privacidade (R-14):** a remoção dos metadados é automática; a ausência de pessoas, rostos, documentos e endereços é checagem humana obrigatória antes da importação. Os arquivos recebidos ficam numa pasta de entrada fora do `DATASET_DIR`, nunca vão para o backup e são apagados depois da importação. O conhecido consente com o uso e pode retirar as fotos até a entrega.

## Consequências

- **Positivas:**
  - o número do `metrics.json` continua medido só no domínio da demo, e os limiares continuam escolhidos nele;
  - a integridade depende só do `item_id` (prefixo `X`), e não de um arquivo que pode ficar dessincronizado;
  - nenhuma linha antiga do manifest muda, e o modo coleta continua igual.
- **Negativas / custos aceitos:**
  - as fotos de conhecidos trafegam pelo aplicativo de mensagens antes de chegar ao notebook. Isso acontece fora do sistema e não fere a R-02, que trata do que o PartQC envia à nuvem, mas é declarado no relatório, como o Drive e o Colab (ADR-004);
  - o reencode perde um pouco de qualidade em relação ao original, como a página já perde;
  - as imagens externas inflam a contagem de peças; o relatório de dados as separa;
  - sem as fontes NonCommercial e ShareAlike, nenhuma fonte externa permitida entre as avaliadas traz dano funcional (SPEC-035, Anexo A): o grau `unusable` depende só das peças da dupla e de conhecidos (`docs/dataset-protocol.md` §2, passo 5);
  - a consequência do ADR-001 sobre o uso opcional do MVTec AD como negativo de `other` deixa de valer (nota de 2026-10-23 no ADR-001).
- **O que passa a ser obrigatório:**
  - `qc_ml.data` aceita `X[SNOT]-[0-9]{4}`, lê e valida `sources.csv` e `ml/external_sources.csv` (SPEC-035);
  - o split põe toda imagem externa no treino, falha se uma peça externa aparecer em `val` ou `test` em qualquer versão, e respeita o teto (SPEC-035);
  - o `metrics.json` mostra, por split, a contagem de imagens por origem, e a entrada do CHANGELOG cita as fontes externas com a licença (SPEC-035);
  - a CLI de importação (SPEC-036) e o passo a passo do `docs/dataset-protocol.md` §10;
  - a SPEC-016 segue esta decisão para as imagens públicas de ferramentas (só treino, prefixo `XT-`).

## Quando revisitar

- Se o teto de 30% impedir o uso de uma fonte que a dupla considere necessária, ou se o QWK de validação piorar ao acrescentar externas (comparação entre duas versões do modelo no CHANGELOG).
- Se o professor recusar o uso de imagens públicas ou de fotos de terceiros (pergunta sugerida ao humano na SPEC-035).
- Se uma fonte do registro tiver a licença alterada ou contestada: a fonte sai (exclusão das imagens, `docs/dataset-protocol.md` §8.1) e o modelo seguinte é treinado sem ela.
- Se a dupla quiser usar imagens externas na validação ou no teste: exige um ADR novo.
- Se a dupla quiser usar uma fonte NonCommercial ou ShareAlike (por exemplo, para ter `unusable` externo): exige um ADR novo, que trate da licença e da publicação do modelo no Release.

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-23 | Decisão 3: lista de licenças reduzida a `CC0-1.0`, `PDDL-1.0`, `CC-BY-4.0`, `MIT`, `Apache-2.0` e `BSD-3-Clause`; NonCommercial e ShareAlike proibidas (inclusive o MVTec AD). Contexto, Consequências (o `unusable` sem fonte externa permitida; nota no ADR-001), Relacionados e Quando revisitar ajustados. Confirmados sem mudança de texto: a normalização com a rotação EXIF aplicada e o reencode (decisão 5), o teto de 30% (decisão 2) e a faixa 500–999 só como recomendação (decisão 1). | Decisão do humano de 2026-10-23 (o `model.onnx` é publicado num GitHub Release público) | Architect, a pedido do humano |
