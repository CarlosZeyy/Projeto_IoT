# qc-edge — gateway de borda (SPEC-007, SPEC-008, SPEC-009, SPEC-010, SPEC-018, SPEC-025, SPEC-030, SPEC-034, SPEC-036, SPEC-038)

O notebook roda o `qc-edge` na rede local. O celular lê o QR code do console, abre a página `/capture`, fotografa a peça e recebe o resultado. As fotos ficam só no notebook, em `EDGE_DATA_DIR/captures/` (modo inspeção) ou em `DATASET_DIR/raw/` (modo coleta) (R-02, R-14). Nada é servido dessas pastas e nada delas sobe para a nuvem.

Estado atual:

- o inferenciador real é o `onnxruntime` na CPU, carregado de `MODEL_DIR` (SPEC-008, seção "Trocar o modelo"). Sem `MODEL_DIR` e sem `--stub-model`, o modo inspeção responde 503 `model not loaded`;
- cada inspeção aceita é gravada no outbox SQLite (`OUTBOX_PATH`) antes da resposta ao celular, e um laço em segundo plano a envia para a `qc-api` quando `DEVICE_API_KEY` e `CLOUD_API_URL` estão definidos (SPEC-009, seção "Envio para a nuvem"). Só o JSON do resultado sobe; a foto nunca (R-02);
- o modo coleta (SPEC-010) monta o dataset: funciona sem modelo e não chama o inferenciador nem o sink (seção "Modo coleta").

## Como rodar

```bash
uv sync --package qc-edge                                         # ou: uv sync --all-packages
cp .env.example .env                                              # uma vez; ajuste o bloco qc-edge
uv run --env-file .env --package qc-edge qc-edge --stub-model     # resultado falso, para testar a captura
uv run --package qc-edge qc-edge                                  # sem .env: tudo no padrão, sem modelo
MODEL_DIR=ml/models/partqc-mnv3-v1 uv run --package qc-edge qc-edge   # com o modelo real
```

- O `qc-edge` não lê o `.env` sozinho: use `--env-file .env` ou exporte as variáveis.
- Abra o console **no próprio notebook**, em <http://127.0.0.1:8000/> ou <http://localhost:8000/> (troque `8000` pelo seu `EDGE_PORT`). Ele só responde ao loopback (`127.0.0.1`/`::1`), recusa com 403 requisições com `X-Forwarded-For`, `Forwarded` ou `CF-Connecting-IP` e só aceita o header `Host` `127.0.0.1:<porta>`, `localhost:<porta>` ou `[::1]:<porta>`: outro nome ou IP na barra de endereço (inclusive o IP da LAN do próprio notebook) recebe 403. Isso impede que uma página hostil aberta no navegador do notebook leia o token por DNS rebinding (SPEC-025). O console mostra o QR code, a URL de pareamento, os outros IPs da máquina (links `/?ip=...`), o estado do modelo e do sink e as 10 últimas inspeções da sessão. Ele recarrega a cada 5 s, e os IPs são detectados de novo a cada recarga (útil ao trocar para o hotspot).
- `--stub-model` responde sempre parafuso/bom (`model_version = stub-v0`). É só para desenvolvimento: as inspeções ficam só na memória, nunca vão para o outbox e **nunca** são publicadas na nuvem (R-06, seção "Envio para a nuvem"). Ele tem precedência sobre `MODEL_DIR`: com os dois, o log avisa (`--stub-model takes precedence: MODEL_DIR is not loaded`) e o diretório não é carregado.
- Códigos de saída: `2` para configuração inválida (a mensagem cita a variável, nunca o valor), argumento desconhecido na linha de comando (o log cita só o nome da opção, nunca o valor: `unknown command-line argument(s): --stub-modle`) ou `MODEL_DIR` que não carrega (o log mostra `cannot load the model: ...` com o nome do arquivo); `1` se `PIL.ImageFile.LOAD_TRUNCATED_IMAGES` estiver ligada no processo (SEC-04).
- O log do servidor nunca mostra o token nem o `DEVICE_API_KEY`. O access log do uvicorn fica desligado, porque imprimiria a query `?t=<token>`. No lugar dele, o `qc-edge` registra uma linha por requisição, com método, rota, status e duração, sem a query.

## Variáveis (`.env`, bloco `qc-edge`)

| Variável | Padrão | Regra |
|---|---|---|
| `EDGE_HOST` | `0.0.0.0` | IPv4 literal (ex.: `0.0.0.0`, `127.0.0.1`); IPv6 e nomes são recusados (código 2) |
| `EDGE_PORT` | `8000` | 1 a 65535 |
| `EDGE_SESSION_TOKEN` | gerado a cada subida (`secrets.token_urlsafe(32)`, 43 caracteres) | deixe vazio (recomendado; seção "Segurança na operação"). Se definido, no mínimo 32 caracteres. É segredo: fica fora do Git |
| `DEVICE_ID` | `edge-01` | `^[a-z0-9-]{3,32}$` (sem quebra de linha final) |
| `EDGE_DATA_DIR` | `edge/data` (relativo ao diretório atual) | criado com `0700` se não existir (um diretório que já existe não é alterado); está no `.gitignore` |
| `DATASET_DIR` | `ml/data` (relativo ao diretório atual) | modo coleta; se existir, tem de ser um diretório. Não é criado na subida: a primeira coleta o cria com `0700`. `ml/data/` está no `.gitignore`; outro caminho deve ficar fora do repositório |
| `MODEL_DIR` | vazio (sem modelo) | diretório do modelo (seção "Trocar o modelo"); o nome do diretório resolvido (alvo do link, se for um link simbólico) é o `model_version`. Definido mas inválido, inclusive só com espaços → código 2 |
| `TYPE_THRESHOLD`, `UNUSABLE_THRESHOLD`, `GRADE_REVIEW_THRESHOLD` | vazio (vale o `decision.json`) | opcionais; número de 0 a 1 que sobrescreve o limiar do `decision.json` (seção "Limiares de decisão"). Fora de `[0, 1]` ou não numérico → código 2 citando a variável. Sem `MODEL_DIR`, são ignorados (com aviso no log) |
| `DEVICE_API_KEY` | vazio | segredo (R-03): chave do dispositivo, gerada por `scripts/register_device.py` e mostrada uma única vez. Vazio = nada é enviado à nuvem. Só ASCII visível (sem espaço nem acento); outro valor → código 2 citando a variável, nunca o valor |
| `CLOUD_API_URL` | vazio | URL base da `qc-api`, sem `/api/v1` no fim (ex.: `https://<seu-servico>.onrender.com`). `https://` obrigatório; `http://` só com `localhost` ou `127.0.0.1` (testes locais). Sem usuário/senha, query ou fragmento. Outro valor → código 2 citando `CLOUD_API_URL`. Vazio = nada é enviado |
| `OUTBOX_PATH` | `EDGE_DATA_DIR/outbox.sqlite3` | arquivo SQLite do outbox (ignorado com `--stub-model`: nem aberto nem criado); as pastas que faltarem são criadas com `0700` e o arquivo novo com `0600`. Se não abrir (ex.: é um diretório) → código 2 citando `OUTBOX_PATH` |
| `HEARTBEAT_INTERVAL_S` | `60` | segundos entre dois heartbeats (seção "Heartbeat"); inteiro de 10 a 3600, ou `0` para desligar. Outro valor (ex.: `5`, `abc`) → código 2 citando a variável, com ou sem `--stub-model` |

Variável vazia vale como não definida (o padrão vale).

## Rotas

| Rota | Acesso | O que faz |
|---|---|---|
| `GET /` | só loopback, sem headers de proxy, `Host` de loopback | console do operador (HTML, sem JS), com a cobertura do dataset |
| `GET /capture?t=<token>` | token na query | página do celular; token errado → 401 "Sessão inválida. Leia o QR code no console." |
| `GET /static/capture.js`, `/static/capture.css` | livre | arquivos da página (sem segredo, sem recurso externo) |
| `POST /api/capture` | header `X-Session-Token` | `multipart/form-data` com `image`, `lot_id` e `mode`; no modo `collect`, `item_id`, `object_type`, `grade`, `labeler`, `angle` e `notes` no lugar do `lot_id` |
| `GET /api/status` | header `X-Session-Token` | `device_id`, `contract_version`, `model` (`loaded`, `model_version`, `model_sha256`, `thresholds`), `sink` |

Ordem das respostas de `POST /api/capture`: token (401) → tamanho (413) → campos (422) → limitador (503 `server busy`) → imagem (415) → modelo (503 `model not loaded`). Depois: falha do inferenciador → 500 `inference failed`; falha do sink → 503 `failed to persist inspection` (a foto é apagada). O modo `collect` segue a mesma ordem até a imagem (415) e depois grava no dataset (seção "Modo coleta").

Limites da rota (`qc_edge/limits.py`, SPEC-007 §4.7):

- campo `image` de até 3 MiB (3 145 728 bytes);
- `Content-Length` de até 3,5 MiB (3 670 016 bytes), conferido antes de ler o corpo;
- até 4 M pixels, conferidos pelo cabeçalho antes de decodificar;
- depois, as regras do `qc_preprocess.load_image`: só JPEG/PNG pelo conteúdo, proporção de até 10:1, JPEG com até 64 marcadores de scan.

No máximo 2 decodificações acontecem ao mesmo tempo, nos dois modos. Quem passa disso espera até 10 s e recebe 503 `server busy`. A espera não ocupa thread do servidor, então o console e o `/api/status` continuam respondendo durante uma rajada de capturas (SPEC-025). A página do celular sempre reduz a foto para no máximo 1280 px no lado maior e a reencoda em JPEG (q = 0,9) antes de enviar.

A foto aceita é salva em `EDGE_DATA_DIR/captures/<AAAA-MM-DD em UTC>/<inspection_id>.jpg`, com nome sempre gerado pelo servidor. Um JPEG é salvo como chegou; um PNG é reencodado em JPEG q = 90. `captures/` e as pastas de dia ficam com `0700` e as fotos com `0600`, seja qual for o `umask` (só o dono lê; `captures/` recebe `0700` a cada subida). Se o `chmod` falhar, o log mostra um `WARNING` e a captura segue. Retenção e remoção dessas fotos: `docs/dataset-protocol.md` §9.

## Trocar o modelo (SPEC-008)

O modelo é um diretório com os artefatos de `docs/architecture.md` §7. O **nome do diretório é o `model_version`** gravado em cada inspeção (`^[a-z0-9.-]{3,40}$`, ex.: `partqc-mnv3-v1`): ao copiar o modelo para o notebook, preserve o nome `ml/models/<model_version>/`.

O `MODEL_DIR` é resolvido antes de tudo (links simbólicos, `.` e `..`; a barra final não conta), e os arquivos são lidos do diretório resolvido. Por isso o `model_version` é o nome do **diretório alvo**, e não o do link: com `MODEL_DIR=ml/models/atual` e o link `atual → partqc-mnv3-v1`, as inspeções levam `partqc-mnv3-v1`. Trocar o modelo apontando um link de nome fixo para outro diretório funciona, e cada inspeção continua com a versão real. Um link para um diretório com nome fora da regex (ex.: `Dummy_V1`) impede a subida, mesmo que o nome do link seja válido.

`MODEL_DIR` vazio (`MODEL_DIR=`) significa "sem modelo". O valor não é aparado: um `MODEL_DIR` só com espaços conta como definido e, como não é um diretório, a subida sai com código 2 (`cannot load the model: MODEL_DIR: not a directory`). Um caminho inexistente, um link quebrado ou um laço de links dão a mesma mensagem.

| Arquivo | O que a borda confere na subida |
|---|---|
| `model.onnx` | carrega no `onnxruntime` (CPU), tem uma entrada `image` e as saídas `type_probs` e `grade_probs`; uma inferência de aquecimento com zeros `[1, 3, crop, crop]`, com o `crop` do `preprocessing.json` (a mesma forma que cada inferência envia; `[1,3,224,224]` com o `crop` padrão), tem de devolver as formas `[1, T]` (T = número de tipos do `labels.json`) e `[1, 5]`. Um `crop` que a entrada do modelo não aceita (ex.: `crop=256` com entrada fixa `[N,3,224,224]`) falha aqui, na subida, e não em cada captura; um modelo com dimensões espaciais dinâmicas aceita qualquer `crop` |
| `model.sha256` | o primeiro token (64 hexadecimais, maiúsculas ou minúsculas; aceita a saída do `sha256sum`, `<hash>  model.onnx`) é igual ao SHA-256 do `model.onnx`. Senão: `model.onnx does not match model.sha256: expected <12 caracteres>, got <12 caracteres>` |
| `labels.json` | exatamente as chaves `object_types` e `grades`; `grades` exatamente `["perfect","good","fair","poor","unusable"]`; `object_types` sem repetição, só com `other` e os tipos do contrato (`screw`, `nut`), nunca `unknown` |
| `preprocessing.json` | lido por `qc_preprocess.PreprocessParams.from_json` |
| `decision.json` | exatamente as chaves `type_threshold`, `unusable_threshold` e `grade_review_threshold`, cada uma um número de 0 a 1 |

Qualquer falha impede a subida com código 2 e uma mensagem com o nome do arquivo. O hash é calculado sobre os mesmos bytes que o `onnxruntime` carrega, então trocar o `model.onnx` depois da conferência não tem efeito até a próxima subida.

Para trocar de modelo:

1. Baixe ou copie o diretório inteiro para `ml/models/<model_version>/` (o `model.onnx` não vai para o Git; ele vem do GitHub Release, conforme a SPEC-012):
   ```bash
   gh release download model-partqc-mnv3-v1 -p model.onnx -D ml/models/partqc-mnv3-v1
   (cd ml/models/partqc-mnv3-v1 && sha256sum -c model.sha256)   # tem de mostrar "model.onnx: OK"
   ```
2. Aponte `MODEL_DIR` para ele (no `.env` ou na linha de comando) e reinicie o `qc-edge`. O modelo só é lido na subida.
3. Confira no console (<http://127.0.0.1:8000/>) a linha **Modelo** (`carregado: <model_version> (sha256 <12 primeiros caracteres>)`) e os **Limiares de decisão**, ou no log da subida (`model loaded: model_version=... sha256=...` e uma linha `threshold ...` por limiar).

### Limiares de decisão

A regra de decisão (`qc_edge.decision.decide`, `docs/architecture.md` §6.2, passo 4) usa três limiares. Os valores vêm do `decision.json` do modelo (escolhidos na validação, SPEC-012) e podem ser sobrescritos por variável de ambiente, para ajuste na demo sem trocar o modelo:

| Limiar | Variável | Efeito |
|---|---|---|
| `type_threshold` | `TYPE_THRESHOLD` | abaixo dele (comparação estrita: igual ao limiar não é `unknown`), o resultado é `unknown`; abaixo dele + 0,10, a inspeção é marcada para revisão (`needs_review`) |
| `unusable_threshold` | `UNUSABLE_THRESHOLD` | `grade_probs[unusable]` maior ou igual a ele decide `unusable`, mesmo que outro grau tenha probabilidade maior |
| `grade_review_threshold` | `GRADE_REVIEW_THRESHOLD` | `grade_confidence` abaixo dele marca a inspeção para revisão |

O console e o `/api/status` (`model.thresholds`, `{nome: {"value", "source"}}`) mostram o valor efetivo de cada limiar e a origem: `decision.json` ou `env`.

As comparações usam as probabilidades exatamente como o modelo as devolve. Só depois delas, os números gravados na inspeção são limitados às faixas do contrato: `type_confidence` e `grade_confidence` a `[0, 1]` e `grade_score` a `[0, 4]` (SPEC-008 §4.1, item 6). O `Softmax` em float32 dá, por exemplo, `p(unusable) = 1.0` com `p(poor) ≈ 6e-8`, o que faria `grade_score` passar um pouco de 4; a inspeção sai com `grade_score = 4.0`. O limite nunca muda o tipo, o grau nem o `needs_review`.

## Modo coleta (SPEC-010)

Serve para montar o dataset seguindo o `docs/dataset-protocol.md` (§3 captura, §4 metas, §5 manifest). Não precisa de modelo: rode `uv run --env-file .env --package qc-edge qc-edge`, sem `--stub-model`.

Na página do celular, escolha **coleta** no seletor de modo e preencha:

| Campo | Regra (a borda responde 422 se não bater) |
|---|---|
| Peça (`item_id`) | `S-000` (parafuso), `N-000` (porca), `T-000` (ferramenta manual) ou `O-000` (outro), com o prefixo do tipo escolhido: `T-` só com uma das 5 ferramentas, e as ferramentas só com `T-` (SPEC-016) |
| Tipo (`object_type`) | parafuso, porca, alicate, chave inglesa, chave Allen, chave de fenda, chave Phillips ou outro |
| Grau (`grade`) | um dos 5 graus para parafuso, porca e as ferramentas (rubrica das ferramentas no `docs/dataset-protocol.md`); desabilitado e vazio para "outro" |
| Rotulador (`labeler`) | `a` ou `b` |
| Ângulo (`angle`) | 0 a 4 |
| Observações (`notes`) | opcional, até 200 caracteres, sem quebra de linha, tabulação, separador de linha ou parágrafo (U+2028/U+2029) nem caracteres de formatação invisíveis (controles bidi, hífen suave) |

Ferramentas manuais (SPEC-016): numere as peças a partir de `T-001`, em sequência entre todas as ferramentas (cada chave Allen de um jogo é uma peça); o grau é obrigatório na coleta, mesmo que o modelo ainda não gradue aquela ferramenta (o `labels.json` diz quais ele não gradua, ADR-021). Fundo liso maior que a ferramenta (cartolina ou A3), a ferramenta ocupando de 40% a 70% da foto, de 3 a 5 ângulos, sem mãos nem pessoas no quadro. Não danifique ferramenta para fotografar `unusable`.

O lote é ignorado nesse modo. Os campos ficam guardados no navegador (`localStorage`) entre as fotos e depois de recarregar a página. A cada foto salva, o ângulo avança 1; depois do 4, volta a 0 e a página mostra "Peça completa — troque o item_id". O cartão mostra "Salvo: <item_id>, ângulo <n> (fotos desta peça: <total>)". Lembrete fixo: **sem pessoas no quadro** (R-14).

Cada foto vira:

- um arquivo `DATASET_DIR/raw/<object_type>/<grade ou _>/<item_id>__<angle>__<AAAAMMDDTHHMMSSZ>.jpg` (UTC). JPEG é salvo sem metadados (abaixo); PNG é reencodado em JPEG q = 90;
- uma linha em `DATASET_DIR/manifest.csv` (UTF-8 sem BOM), com as colunas `image_path,item_id,object_type,grade,labeler,angle,captured_at,capture_device,notes`. `capture_device` são os 60 primeiros caracteres do `User-Agent` do celular, com os caracteres de controle e de formatação trocados por espaço antes do corte.

Privacidade das fotos do dataset (SPEC-025, R-14):

1. O modo coleta grava o JPEG **sem** EXIF (GPS, aparelho, data), XMP, IPTC, comentário e dados depois do fim da imagem (EOI, onde fica o vídeo de uma "foto com movimento"), **sem reencodar**: os segmentos são removidos pela estrutura dos marcadores e os pixels não mudam. Como a rotação EXIF fica no APP1, um JPEG com rotação nunca passa por essa remoção (item 4), e o `qc_preprocess.load_image` dá a mesma imagem para a foto enviada e para o arquivo gravado. Um JPEG cuja estrutura a borda não consegue percorrer recebe 415 `invalid image: unsupported JPEG structure` e nada é gravado.
2. Antes de **cada** backup do dataset no Drive, rode `uv run --package qc-edge python -m qc_edge.privacy --dataset-dir ml/data` (troque `ml/data` pelo seu `DATASET_DIR`). Ele lista cada imagem de `raw/` com metadados (`raw/screw/fair/<arquivo>.jpg: app1`; os achados possíveis são `app1`, `app13`, `com`, `trailer`, `orientation` e `invalid`) e termina com `checked <n> images, <k> with private data`; sai com `0` se `k = 0` e `1` se houver achados. Havendo achados, repita com `--fix`, que reescreve só essas imagens sem os segmentos (o `manifest.csv` não muda) e pode rodar com o `qc-edge` ligado, porque usa o mesmo lock da coleta. Uma imagem `invalid` ou `orientation` não é corrigida (o código continua `1`): apague-a e registre-a em `exclusions.csv`. O procedimento completo está em `docs/dataset-protocol.md` §8 e §8.1.
3. Fotos copiadas à mão para `raw/` (por exemplo, do app da câmera) não passam pela rota e chegam com todos os metadados: elas passam pela mesma varredura, então rode o comando acima (e o `--fix`) depois de copiar. A varredura confere os arquivos `.jpg` e `.jpeg` em qualquer caixa (`.JPG`, `.Jpeg`; o `--fix` mantém o nome) e acusa como `invalid`, sem ler, qualquer outro arquivo de `raw/` (`.png`, `.heic`, sem extensão etc.; o `--fix` não o toca e o procedimento é o do `invalid` no item 2). Ela ignora só os temporários da própria borda (nome começando com `.` e terminando com `.tmp`) e não segue links simbólicos. Os caminhos saem com os caracteres de controle e invisíveis escapados (por exemplo, `\x0a` para uma quebra de linha no nome), e um arquivo que não pode ser lido aparece como `<caminho>: unreadable` e deixa o código em `1` (SPEC-030).
4. Uma foto com rotação EXIF (`Orientation` de 2 a 8, o normal numa foto em retrato do app da câmera; também vale o `tiff:Orientation` do XMP) recebe 415 `invalid image: EXIF orientation not supported` na coleta e o achado `orientation` na varredura (por exemplo, `raw/screw/fair/<arquivo>.jpg: app1, orientation`), que o `--fix` não corrige: tirar o EXIF dela faria o treino lê-la girada (ADR-004). Apague-a, registre-a em `exclusions.csv` e refotografe a peça pela página `/capture`, que aplica a rotação pelo canvas e nunca envia esse caso (`docs/dataset-protocol.md` §8).

Respostas além das da tabela de rotas:

| Situação | Resposta | O que fazer |
|---|---|---|
| JPEG com rotação EXIF (`Orientation` de 2 a 8), enviado direto à rota | 415 `invalid image: EXIF orientation not supported` | fotografar pela página `/capture` (item 4 acima); nada é gravado |
| a mesma peça já está no manifest com outro tipo | 409 `item_id already registered with another object_type` | conferir o `item_id` (a mesma peça com outro **grau** é permitida: estágios de corrosão) |
| foto da mesma peça e ângulo no mesmo segundo | 409 `capture already exists, try again` | fotografar de novo |
| `manifest.csv` com cabeçalho diferente do esperado | 500 `manifest header mismatch` | corrigir o arquivo no notebook; nada é gravado até lá |
| `manifest.csv` com linhas ilegíveis (não UTF-8) | 500 `manifest unreadable` | idem |
| falha de disco ao gravar | 500 `failed to write dataset` | a foto não fica pela metade nem sem linha no manifest |

As gravações passam por um lock de processo e por um `flock` em `DATASET_DIR/manifest.csv.lock` (só POSIX). Cada diretório novo e a imagem renomeada recebem `fsync` do diretório antes da linha do manifest, para que uma queda de energia não deixe uma linha sem imagem (se o sistema de arquivos não aceitar, o log mostra um `WARNING` e a coleta segue). Tudo o que a coleta **cria** sob `DATASET_DIR` (o próprio `DATASET_DIR`, quando é ela que o cria, `raw/`, as pastas de tipo e grau) fica com `0700`, e as imagens, o `manifest.csv` e o `manifest.csv.lock` com `0600`, seja qual for o `umask`. O que já existia não é alterado. Se o `chmod` falhar, o log mostra um `WARNING` com o caminho e a coleta segue.

O console (<http://127.0.0.1:8000/>) mostra a tabela de cobertura (`imagens/meta` e `peças/meta`) por tipo e grau: 120 imagens e 12 peças por grau (mínimo 8) para parafuso e porca; 60 imagens e 5 peças por grau para cada ferramenta manual (o critério de grau da SPEC-016, opcional; a meta de identificação é de 90 imagens e 6 peças por ferramenta, mínimo 3, somando os graus); e, para "outro", 150 imagens e 30 objetos. Em verde, as células que atingiram as duas metas. Sem `manifest.csv`, a tabela fica zerada. As imagens externas importadas (`XS-0001`, `XN-…`, `XT-…`, `XO-…`, seção abaixo) não contam na tabela: logo abaixo dela, o console mostra só o total, em "Imagens externas (só treino): <n>".

O `DATASET_DIR` nunca vai para o Git nem para a nuvem do projeto (R-02). O backup é o do `docs/dataset-protocol.md` §8 (Drive pessoal, compactado por data). Correções de rótulo e dupla rotulagem são da SPEC-011 (`labels_overrides.csv`), nunca editando a linha original.

## Importar fotos de fora da página (SPEC-036)

Serve para colocar no dataset as fotos que **não** passam pela página `/capture` (ADR-020): fotos de conhecidos, tiradas em outros celulares e recebidas como arquivo (origem `contributor`), e imagens de datasets públicos com licença aceita (origem `external`, só treino). É o único caminho de entrada desses arquivos: nunca os copie para `raw/` (`docs/dataset-protocol.md` §8). O passo a passo completo, com o guia para quem fotografa, o consentimento, a numeração e as licenças, está em `docs/dataset-protocol.md` §10.

1. **Pasta de entrada e plano fora do repositório e fora do `DATASET_DIR`** (ex.: `~/partqc-entrada/`, nunca dentro do checkout do projeto nem de `ml/data/`). A CLI recusa com `inbox must be outside the dataset` uma pasta igual ao dataset, dentro dele ou que o contenha: os arquivos recebidos têm EXIF e não podem ir para o backup. Desde a SPEC-038, ela também recusa, com código `2` e antes de ler qualquer coisa, a pasta de entrada (`inbox must be outside any git repository`) e o plano (`plan must be outside any git repository`) dentro de um repositório Git, isto é, quando a pasta (depois de resolver os links simbólicos) ou alguma pasta acima dela tem uma entrada `.git` (diretório ou arquivo, como numa worktree). O repositório é público, e um `git add -A` publicaria as fotos de terceiros com EXIF e GPS, porque o `.gitignore` não cobre todos os formatos de celular nem o plano CSV. Se a sua pasta pessoal for um repositório Git (dotfiles), use uma pasta fora dela (por exemplo, num disco externo).
2. **Olhe cada foto** no tamanho real: sem pessoa, rosto, mão identificável, documento, tela ou endereço (`docs/dataset-protocol.md` §10.5). A opção `--privacy-checked` é a confirmação de que isso foi feito; sem ela, a CLI sai com `2` sem ler nada.
3. **Plano CSV** (UTF-8 sem BOM, até 5.000 linhas), com o cabeçalho exato abaixo. `file` é o caminho relativo à pasta de entrada (com `/`, sem `..`, nunca um link simbólico, até 40 MiB). Uma linha `contributor` usa `S-`/`N-`/`T-`/`O-` com 3 dígitos (sugestão: a partir de 500) e o código do conhecido (`c01`), com `source_id` e `source_ref` vazios. Uma linha `external` usa `XS-`/`XN-`/`XT-`/`XO-` com 4 dígitos, `contributor` vazio, a fonte registrada em `ml/external_sources.csv` (licença da lista do ADR-020) e o arquivo dentro da fonte em `source_ref`. Ferramentas manuais (SPEC-016): `T-`/`XT-` só com `pliers`, `adjustable_wrench`, `allen_key`, `flat_screwdriver` ou `phillips_screwdriver`, e essas só com `T-`/`XT-` (senão, `item_prefix_mismatch`); o grau é obrigatório, como na coleta.

   ```csv
   file,item_id,object_type,grade,labeler,angle,origin,contributor,source_id,source_ref,notes
   IMG_20261022_101500.jpg,S-501,screw,fair,a,2,contributor,c01,,,dúvida fair/poor
   sdnet/0001.png,XS-0001,screw,perfect,b,0,external,,fonte-teste,dataset/train/0001.png,
   IMG_20261023_090000.jpg,T-501,flat_screwdriver,good,a,1,contributor,c01,,,
   ```

   Se montar o plano numa planilha, exporte como CSV UTF-8 e confira as células de `notes` e `source_ref` que começam com `=`, `+`, `-` ou `@`, que a planilha pode ter transformado em fórmula.
4. **Rode primeiro com `--dry-run`**, que valida tudo e normaliza cada imagem sem criar nem alterar nada no dataset, e confira as linhas `failed`:

   ```bash
   uv run --package qc-edge python -m qc_edge.importer --dataset-dir ml/data \
       --inbox ~/partqc-entrada --plan ~/partqc-entrada/plano.csv --privacy-checked --dry-run
   ```

   Depois, o mesmo comando sem `--dry-run`. `--external-sources <arquivo>` troca o registro (padrão: `ml/external_sources.csv` do repositório; só é lido se o plano tiver linha `external`).

O que acontece:

- **Validação do plano inteiro antes de gravar.** Qualquer problema sai com `2`, nada é gravado e a saída de erro tem uma linha `plan line <n>: <código> (<coluna>)` por problema, sem repetir o valor da célula. O mesmo `item_id` com outro tipo (no plano ou no manifest), o mesmo arquivo duas vezes e dois arquivos iguais também são problemas.
- **Normalização, como a página faz:** a rotação EXIF é aplicada, o EXIF (GPS, aparelho, data), o XMP, o IPTC, os comentários e o vídeo da "foto com movimento" são descartados, o lado maior fica com no máximo 1280 px e a imagem é reencodada em JPEG q = 90, sem metadados (o perfil de cor também sai). O resultado é conferido antes de gravar. HEIC, WebP e outros formatos são recusados (`unsupported image`), assim como imagens cujo lado menor ficaria abaixo de 256 px (`image too small`).
- **Gravação como a da coleta:** mesmo nome e mesma pasta (`raw/<tipo>/<grau ou _>/<item_id>__<ângulo>__<AAAAMMDDTHHMMSSZ>.jpg`), mesmo lock, `0700`/`0600`. O `manifest.csv` ganha a linha com `captured_at` igual ao instante da importação e `capture_device = qc-edge-import`, e o `DATASET_DIR/sources.csv` (`image_path,origin,contributor,source_id,source_ref,input_sha256`) ganha a origem, com o SHA-256 do arquivo recebido. Os arquivos da pasta de entrada nunca são alterados nem apagados.
- **Saída:** uma linha por linha do plano (`imported <arquivo> -> <image_path>`, `skipped <arquivo>: already imported`, `failed <arquivo>: <motivo>` ou, no `--dry-run`, `would import <arquivo>`) e o total `imported <n>, skipped <k>, failed <f>`. Código `0` sem falha, `1` com alguma linha `failed` (uma imagem recusada não para as outras; uma falha de disco para na hora, sem deixar imagem sem linha) e `2` para argumentos, plano, registro ou cabeçalho.
- **Retomada:** rodar o mesmo plano de novo pula (`skipped`) o que já entrou, pelo SHA-256 do arquivo recebido. Uma foto excluída por engano (registrada em `exclusions.csv`) pode ser importada de novo. A conferência é repetida sob o lock, linha a linha, então duas execuções simultâneas do mesmo plano não gravam a mesma foto duas vezes: a segunda pula a linha com `skipped <arquivo>: already imported` (SPEC-038).
- **Falha de disco no meio de uma linha:** além da imagem e da linha do manifest, as pastas criadas para aquela linha (por exemplo, `raw/screw/fair/`) são removidas se tiverem ficado vazias; as que já existiam antes nunca são removidas (SPEC-038).
- **PNG com comentário:** um PNG com chunk de texto `comment` (comum em datasets públicos) é importado sem o comentário; nenhum metadado da entrada vai para o JPEG gravado (SPEC-038).

Depois de importar, rode `uv run --package qc-edge python -m qc_edge.privacy --dataset-dir ml/data` (deve terminar com `0 with private data`) e `uv run --package qc-ml python -m qc_ml.data validate --dataset-dir ml/data` (sem problemas), e só então apague os arquivos da pasta de entrada (`docs/dataset-protocol.md` §10.6).

## Envio para a nuvem (SPEC-009)

Fluxo (`docs/architecture.md` §6.2, passos 6 e 8): a captura grava o `InspectionCreate` no outbox SQLite (`OUTBOX_PATH`) e só depois responde ao celular. Uma thread em segundo plano lê os pendentes a cada 2 s e os publica em `POST {CLOUD_API_URL}/api/v1/inspections/batch`, em lotes de até 100, com o header `X-API-Key` e timeout de 5 s por operação (conexão, escrita, cada leitura). Além disso, cada envio tem um prazo total de 15 s e lê no máximo 512 KiB de resposta; estourar qualquer um dos dois (`request deadline exceeded` ou `response too large`) é tratado como falha temporária e a linha é tentada de novo (SPEC-030). O corpo é sempre JSON (`BatchCreate` de `qc_contracts`): nunca imagem, nunca multipart (R-02). `qc_edge.publisher` é o único módulo da borda que fala HTTP com a nuvem.

Onde ficam as inspeções e quando o envio fica ligado (SPEC-009 §4.4):

| Situação | Onde ficam as inspeções | Envio | Conectividade |
|---|---|---|---|
| sem `--stub-model`, com `DEVICE_API_KEY` e `CLOUD_API_URL` | outbox (`OUTBOX_PATH`) | ligado | `online`, `offline` ou `auth_error` |
| sem `--stub-model`, faltando qualquer um dos dois | outbox (`OUTBOX_PATH`), como pendentes | desligado (o log avisa qual falta) | `disabled` |
| com `--stub-model` (com ou sem chave e URL) | **só na memória** (somem quando o processo termina) | **sempre desligado** | `disabled` |

**Com `--stub-model`, nada vai para o outbox nem para a nuvem** (R-06: resultado falso não sobe como `live`). O `qc-edge` não abre, não cria e não valida o `OUTBOX_PATH`: as inspeções do stub (`model_version = stub-v0`) ficam só na memória do processo, e nenhuma subida posterior, com ou sem a flag, consegue publicá-las. Linhas que já existiam no outbox ficam intactas e só saem numa subida sem a flag. A subida registra um aviso `--stub-model: inspections are kept only in memory and are never written to the outbox nor sent to the cloud`. A validação de `CLOUD_API_URL` e `DEVICE_API_KEY` é a mesma com ou sem a flag.

Se você rodou um build anterior desta branch (SPEC-009 r1, antes da correção do SPEC_ISSUE-01) com `--stub-model`, o `outbox.sqlite3` pode ter linhas `stub-v0` pendentes: apague o arquivo antes da primeira subida com chave e URL. Só afeta máquinas de desenvolvimento; nada disso chegou à `main`.

O que o laço faz com a resposta da nuvem:

- `created` ou `duplicate` → a linha vira `sent` (a idempotência por `inspection_id` da API garante que um reenvio não duplica, R-05). Conectividade `online` e "Último envio" atualizado;
- rede fora, timeout, 5xx, 429, outro 4xx ou resposta malformada → a linha continua pendente e é tentada de novo em `min(60, 2^n × U(0,8; 1,2))` s (`n` = tentativas anteriores: ~1 s, ~2 s, ~4 s… até 60 s). Conectividade `offline`. O cold start do Render (~1 min) aparece assim e é absorvido pelo backoff;
- 422 ou 413 → o lote é dividido ao meio até isolar a inspeção recusada, que vira `dead` (nunca mais é enviada) com o resumo da recusa em `last_error` (ex.: `HTTP 422: Value cannot be stored` ou `HTTP 422: 2 validation errors`). O corpo da resposta nunca vai para o log nem para o outbox, porque o 422 do FastAPI repete o que foi enviado;
- 401 ou 403 → conectividade `auth_error`, um erro no log (`check DEVICE_API_KEY and restart qc-edge`) e **nenhuma** requisição até reiniciar o `qc-edge`. Corrija a chave (ou registre o dispositivo de novo com `scripts/register_device.py --rotate`) e reinicie; as pendentes saem na subida seguinte.

Com o outbox vazio, o laço consulta `GET /api/v1/health` (sem chave) logo na subida e depois a cada 60 s sem contato com a nuvem, para atualizar `online`/`offline`. Se o relógio do notebook voltar no tempo (NTP depois de uma suspensão, ajuste manual), o health check roda no ciclo seguinte e as linhas em espera são tentadas logo, em vez de esperar o tamanho do salto (SPEC-030).

O console mostra **Pendentes**, **Com falha definitiva** (`dead`), **Conectividade com a nuvem** e **Último envio**; o `/api/status` traz os mesmos campos em `sink`. O log nunca mostra o `DEVICE_API_KEY` nem o corpo das respostas.

O outbox nunca apaga linhas (o volume da demo é pequeno) e sobrevive a uma queda do processo: cada gravação é confirmada (`synchronous=FULL`, WAL) antes da resposta. Para ver as inspeções `dead`:

```bash
sqlite3 edge/data/outbox.sqlite3 "select inspection_id, attempts, last_error from outbox where status = 'dead'"
```

(troque o caminho pelo seu `OUTBOX_PATH`). Para listá-las e reenviá-las, use o comando da seção seguinte.

### Reenviar itens `dead` (SPEC-034)

Um item `dead` é uma inspeção que a nuvem recusou com 422 ou 413 e que o laço isolou por bissecção: fica no outbox com o motivo em `last_error` e o laço nunca mais a envia sozinho. O caso típico é uma recusa geral numa divergência de versão do contrato (todos os itens de um ciclo viram `dead`). O console só mostra a contagem (**Com falha definitiva**); o reenvio é um passo consciente do operador, no terminal, e nunca é automático.

Depois de uma atualização da API ou da borda que corrija a recusa:

```bash
# 1. conferir (só lê; não altera nada)
uv run --package qc-edge python -m qc_edge.requeue --outbox-path edge/data/outbox.sqlite3

# 2. reenviar (devolve os itens a pending)
uv run --package qc-edge python -m qc_edge.requeue --outbox-path edge/data/outbox.sqlite3 --yes
```

(troque o caminho pelo seu `OUTBOX_PATH`).

- Sem `--yes`, o comando imprime uma linha por item `dead`, `<inspection_id> <created_at UTC> attempts=<n> <last_error ou ->`, e no fim `<k> dead item(s); run again with --yes to requeue`. Com `--yes`, imprime `requeued <k> item(s)` (código 0, inclusive com `k = 0`).
- `--id <inspection_id>` (repetível) restringe a listagem e o reenvio a esses itens. Ids que não existem ou que não estão `dead` são ignorados; um item `sent` nunca volta.
- Cada item reenviado volta a `pending` com `attempts=0` (o backoff recomeça) e sem `last_error`; o `payload` não muda. O laço o envia no próximo ciclo, revalidado pelo contrato vigente. Se a nuvem ainda o recusar, ele volta a `dead` com o motivo novo em `last_error`.
- A idempotência por `inspection_id` da API impede duplicatas na nuvem, mesmo que parte dos itens já tenha chegado lá (R-05).
- Pode rodar com o `qc-edge` ligado (o outbox está em WAL; o comando espera até 5 s por um lock). O arquivo nunca é criado: caminho inexistente, que não é arquivo regular ou que não é um outbox sai com código 2; uma falha do SQLite durante a leitura ou a alteração (por exemplo, o lock não liberado em 5 s) sai com código 1.
- A saída nunca mostra o `payload` (lote, dispositivo, confianças) nem o `DEVICE_API_KEY`, e o comando não faz nenhuma requisição de rede: só altera o arquivo. Argumento desconhecido ou `--id` que não é UUID sai com código 2, e o log mostra só os nomes das opções, nunca os valores.
- Um arquivo que não pode ser aberto (permissão, pasta sem escrita para o `-shm`, E/S) sai com código 2 e `cannot open --outbox-path (OperationalError)`; um arquivo que não é SQLite ou não tem a tabela do outbox sai com código 2 e `--outbox-path is not an outbox file (<Classe>)` (SPEC-038).
- **Linha inválida** (editada à mão ou corrompida, por exemplo um `created_at` que não é data ou um `attempts` que não é inteiro): a listagem a pula e imprime só os itens válidos, com um aviso no log (stderr) que cita só o `rowid` e a coluna, nunca o valor (`invalid dead row skipped (rowid=<n>, column=<coluna>)`). Se uma linha `pending` estiver inválida, o laço a move para `dead` com `last_error = invalid outbox row` (aviso `invalid outbox row marked dead (rowid=<n>, column=<coluna>)`) e continua enviando os outros itens. O `--yes` corrige `attempts` e `next_attempt_at` (zera as tentativas e agenda para agora), e a linha sobe normalmente. Com `inspection_id` ou `created_at` inválidos, o laço a devolve a `dead` com `invalid outbox row` no ciclo seguinte: ela precisa ser corrigida ou retirada à mão no `sqlite3` (SPEC-038).

### Heartbeat (SPEC-018)

Quando o envio está ligado (sem `--stub-model`, com `DEVICE_API_KEY` e `CLOUD_API_URL`, a primeira linha da tabela acima) e `HEARTBEAT_INTERVAL_S` não é `0`, uma segunda thread envia um heartbeat logo na subida e depois a cada `HEARTBEAT_INTERVAL_S` segundos (padrão 60) para `POST {CLOUD_API_URL}/api/v1/devices/<DEVICE_ID>/heartbeat`, com o header `X-API-Key`, o timeout de 5 s, o prazo de 15 s e o teto de 512 KiB do envio. O corpo é o `HeartbeatCreate` de `qc_contracts`: versão e sha256 do modelo carregado (nulos sem modelo), versão do `qc-edge`, tempo ligado (`uptime_s`, pelo relógio monotônico) e as contagens de pendentes e `dead` do outbox. Nada de imagem nem de dado pessoal (R-02). A página "Dispositivos" do dashboard mostra o dispositivo como online enquanto o último heartbeat tiver menos de 180 s, pela hora do servidor.

- O heartbeat **não** passa pelo outbox: uma falha (rede fora, timeout, 5xx, 404 de uma API anterior à SPEC-018) vira um `WARNING` `heartbeat failed: ...` no log, e o laço tenta de novo no ciclo seguinte, sem afetar as inspeções.
- 401 ou 403 → um único `ERROR` (`check DEVICE_API_KEY and restart qc-edge; heartbeats are paused`) e nenhum heartbeat até reiniciar o `qc-edge`, como o envio.
- Com `--stub-model`, sem a chave ou sem a URL, ou com `HEARTBEAT_INTERVAL_S=0`, não há heartbeat (R-06). O simulador (`scripts/simulate.py`) também não envia heartbeat.

### Demo offline (CA-17 da SPEC-009, manual)

Registre o resultado no test-report da SPEC-009.

1. Borda ligada com `DEVICE_API_KEY` válida e `CLOUD_API_URL` da API publicada, e `MODEL_DIR` do modelo real (sem `--stub-model`). Confira no console: conectividade `online`, pendentes `0`.
2. Desligue o Wi-Fi do notebook (no plano B, os dados móveis do celular; o celular continua falando com a borda pela LAN do hotspot).
3. Inspecione 3 peças. O console mostra `offline` e pendentes `3`.
4. Religue a rede.
5. Em até 90 s, o console mostra `online` e pendentes `0`, e as 3 inspeções aparecem no dashboard.

O que registrar: horários dos passos 2 a 5, o que o console mostrou em cada um e os `inspection_id` das 3 inspeções no dashboard.

## Firewall no Arch

A porta é aberta **só para a sub-rede** da Wi-Fi de casa ou do hotspot da dupla, **só durante a sessão**, e a regra é desfeita no fim. **Não rode o `qc-edge` com a porta aberta numa rede que não seja da dupla** (por exemplo, a Wi-Fi do campus): o token protege a captura, mas ninguém de fora deve nem alcançar a porta.

1. Descubra a sub-rede da Wi-Fi ou do hotspot:

   ```bash
   ip -4 route show scope link
   ```

   Use a linha da interface Wi-Fi ou do hotspot, por exemplo `192.168.43.0/24 dev wlan0 proto kernel src 192.168.43.17`: a sub-rede é `192.168.43.0/24`. Ignore as linhas de `docker0`, `br-*` e `virbr*` (bridges do Docker e de máquinas virtuais). Nos comandos abaixo, troque `<sub-rede>` por esse valor.

2. Descubra qual firewall está ativo (normalmente só um responde `active`):

   ```bash
   systemctl is-active ufw firewalld nftables
   ```

### ufw

```bash
sudo ufw allow proto tcp from <sub-rede> to any port 8000          # libera só para a sub-rede
sudo ufw status numbered                                            # confere
sudo ufw delete allow proto tcp from <sub-rede> to any port 8000   # desfaz, no fim da sessão
```

A regra do ufw **persiste** (inclusive depois de reiniciar o notebook) até ser apagada com o `delete`. Não esqueça de desfazê-la no fim da sessão.

### firewalld

Só regra de runtime: ela some no próximo reload ou reboot, e não é gravada na configuração.

```bash
firewall-cmd --get-active-zones        # zona da interface Wi-Fi ou do hotspot
sudo firewall-cmd --zone=<zona> --add-rich-rule='rule family="ipv4" source address="<sub-rede>" port port="8000" protocol="tcp" accept'
sudo firewall-cmd --zone=<zona> --list-rich-rules                  # confere
sudo firewall-cmd --zone=<zona> --remove-rich-rule='rule family="ipv4" source address="<sub-rede>" port port="8000" protocol="tcp" accept'
```

O `--remove-rich-rule` recebe exatamente a mesma regra do `--add-rich-rule`.

### nftables

```bash
sudo nft list ruleset                                                          # descubra a tabela e a chain de entrada
sudo nft add rule inet filter input ip saddr <sub-rede> tcp dport 8000 accept   # ajuste "inet filter input"
```

O `add` coloca a regra no fim da chain. Se a chain terminar com um `drop` ou `reject`, use a mesma regra com `insert` no lugar de `add`, para ela ficar no início:

```bash
sudo nft insert rule inet filter input ip saddr <sub-rede> tcp dport 8000 accept
```

Para desfazer:

```bash
sudo nft -a list chain inet filter input                    # mostra o "handle" de cada regra
sudo nft delete rule inet filter input handle <número>
```

Regras criadas com `nft` na linha de comando somem no reboot (a menos que você salve o ruleset).

## Plano B: hotspot do celular (apresentação)

1. No celular A, ligue o roteador Wi-Fi/hotspot, com senha WPA2 ou WPA3.
2. No notebook, conecte-se a ele:
   ```bash
   nmcli dev wifi list                                   # confira o SSID
   nmcli --ask dev wifi connect <SSID>                   # pede a senha no terminal (fora do histórico)
   ```
3. Se o `qc-edge` já estiver rodando, não precisa reiniciar: espere o console recarregar (5 s). O QR code passa a usar o IP novo (os outros aparecem como links `/?ip=...`). Se aparecer o aviso "Nenhum IP de rede local foi detectado", a conexão ainda não subiu.
4. Refaça a regra do firewall com a sub-rede **do hotspot** (seção Firewall): o IP do notebook mudou, e a regra da Wi-Fi de casa não vale para a nova rede. Desfaça a regra antiga.
5. No celular, leia o QR **novo** (o IP mudou; o token continua o mesmo enquanto o processo estiver rodando).
6. Para voltar à rede de casa: `nmcli con up <nome da conexão de casa>`.

Plano C (`docs/architecture.md` §8): ancoragem USB. O celular ligado pelo cabo cria uma rede só entre os dois; o QR usa o IP do notebook nessa interface. Túneis públicos (Cloudflare e afins) são **proibidos**, porque as fotos passariam por fora da LAN (R-02).

## Segurança na operação

- Deixe `EDGE_SESSION_TOKEN` **vazio**: assim, um token novo é gerado a cada subida, e reiniciar o `qc-edge` invalida os QR codes antigos.
- **Não projete o console** (QR code e URL com o token) na apresentação. Se ele foi projetado, reinicie o `qc-edge` para trocar o token.
- O hotspot do celular sempre com senha WPA2 ou WPA3.
- Se o QR code ou a lista de IPs do console mostrar um endereço `172.17.x.x`, `172.18.x.x` ou vizinho, é uma bridge do Docker (a sondagem UDP falhou, por exemplo, sem rota padrão): use o link do IP da Wi-Fi ou do hotspot, conferido com `ip -4 addr`.
- O bind padrão `0.0.0.0` também escuta nas bridges do Docker. A regra de firewall por sub-rede (seção Firewall) é o que limita quem alcança a porta.
- O console só abre com `127.0.0.1`, `localhost` ou `[::1]` na barra de endereço do próprio notebook. Um 403 com outro endereço é o comportamento esperado.

## Teste manual com os celulares (CA-20 e CA-21)

Registre o resultado no test-report da SPEC-007. Use um lote diferente por celular (ex.: `CEL-A` e `CEL-B`) para separar as linhas no console.

### CA-20: mesma Wi-Fi (topologia preferida)

1. No notebook, na mesma Wi-Fi dos celulares: libere a porta 8000 (seção Firewall) e rode `uv run --env-file .env --package qc-edge qc-edge --stub-model`. Abra <http://127.0.0.1:8000/>.
2. Antes do celular A, marque o tempo: `touch /tmp/partqc-marca-a`.
3. No celular A (Android, Chrome), leia o QR do console. Anote o navegador e a versão.
4. Digite o lote `CEL-A` e toque em **Fotografar**. Anote se a câmera **traseira** abriu direto ou depois de escolher "Câmera" no seletor do Android (ADR-003).
5. Fotografe 10 peças. Em cada uma, confira o cartão de resultado (veredito, tipo, grau) e o **Total** em ms, que deve ficar abaixo de 3000 ms. Anote o maior total.
6. Confira no console 10 linhas novas com o lote `CEL-A` (ele mostra as 10 últimas).
7. No notebook, o maior arquivo do celular A (deve ficar abaixo de 3 145 728 bytes):
   ```bash
   find edge/data/captures -name '*.jpg' -newer /tmp/partqc-marca-a -printf '%s %p\n' | sort -n | tail -1
   ```
   (troque `edge/data` pelo seu `EDGE_DATA_DIR`, se for outro).
8. `touch /tmp/partqc-marca-b` e repita os passos 3 a 7 no celular B (o outro celular da dupla, navegador padrão), com o lote `CEL-B` e `-newer /tmp/partqc-marca-b`.

### CA-21: hotspot (plano B)

1. Siga a seção "Plano B" (hotspot do celular A, notebook conectado a ele).
2. Recarregue o console e use o QR do novo IP.
3. Repita os passos 3 a 6 do CA-20 com 3 fotos em cada celular (o celular B se conecta ao hotspot do celular A).

O que registrar, por celular: modelo do aparelho, navegador e versão, câmera direta ou via seletor, o maior "Total" (ms), o tamanho do maior arquivo (bytes) e qualquer erro exibido.

## Teste manual do modo coleta (CA-17 da SPEC-010)

Registre o resultado no test-report da SPEC-010. Use um `DATASET_DIR` descartável para não misturar com o dataset real:

1. No notebook: libere a porta (seção Firewall) e rode `DATASET_DIR=/tmp/partqc-coleta uv run --package qc-edge qc-edge` (sem `--env-file`, sem `--stub-model` e sem `MODEL_DIR`: a coleta não precisa de modelo nem da nuvem). Abra <http://127.0.0.1:8000/>: o modelo aparece como "não carregado" e a tabela de cobertura está zerada.
2. No celular, leia o QR, escolha **coleta** e preencha `S-001`, parafuso, perfeito, rotulador `a`, ângulo 0.
3. Tire 5 fotos. Confira em cada uma o cartão "Salvo: S-001, ângulo n (fotos desta peça: n+1)" e o ângulo avançando 0 → 1 → 2 → 3 → 4. Depois da quinta, o ângulo volta a 0 e aparece "Peça completa — troque o item_id".
4. Recarregue a página no celular: o modo e os campos continuam preenchidos.
5. Troque o tipo para "outro": o grau fica desabilitado e vazio.
6. No notebook:
   ```bash
   ls -l /tmp/partqc-coleta/raw/screw/perfect/      # 5 arquivos S-001__<0..4>__<ts>.jpg, -rw-------
   wc -l /tmp/partqc-coleta/manifest.csv            # 6 linhas: cabeçalho + 5
   stat -c '%a %n' /tmp/partqc-coleta /tmp/partqc-coleta/raw /tmp/partqc-coleta/manifest.csv
   ```
   e, no console, a linha parafuso/perfeito com `5/120` e `1/12`.
7. No fim, apague a pasta de teste: `rm -rf /tmp/partqc-coleta`.

O que registrar: modelo do celular e navegador, se os campos sobreviveram ao recarregamento, a sequência de ângulos e a saída dos comandos do passo 6.
