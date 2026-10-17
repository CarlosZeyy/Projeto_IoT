# qc-edge — gateway de borda (SPEC-007, SPEC-010)

O notebook roda o `qc-edge` na rede local. O celular lê o QR code do console, abre a página `/capture`, fotografa a peça e recebe o resultado. As fotos ficam só no notebook, em `EDGE_DATA_DIR/captures/` (modo inspeção) ou em `DATASET_DIR/raw/` (modo coleta) (R-02, R-14). Nada é servido dessas pastas e nada delas sobe para a nuvem.

Estado atual:

- o inferenciador real (ONNX) ainda não existe (SPEC-008). Sem `--stub-model`, o modo inspeção responde 503 `model not loaded`;
- as inspeções aceitas vão para um `InMemorySink`, que só guarda em memória e não envia nada para lugar nenhum. O outbox e o envio para a nuvem são da SPEC-009;
- o modo coleta (SPEC-010) monta o dataset: funciona sem modelo e não chama o inferenciador nem o sink (seção "Modo coleta").

## Como rodar

```bash
uv sync --package qc-edge                                         # ou: uv sync --all-packages
cp .env.example .env                                              # uma vez; ajuste o bloco qc-edge
uv run --env-file .env --package qc-edge qc-edge --stub-model     # resultado falso, para testar a captura
uv run --package qc-edge qc-edge                                  # sem .env: tudo no padrão, sem modelo
```

- O `qc-edge` não lê o `.env` sozinho: use `--env-file .env` ou exporte as variáveis.
- Abra o console **no próprio notebook**, em <http://127.0.0.1:8000/>. Ele só responde ao loopback (`127.0.0.1`/`::1`) e recusa com 403 requisições com `X-Forwarded-For`, `Forwarded` ou `CF-Connecting-IP`. O console mostra o QR code, a URL de pareamento, os outros IPs da máquina (links `/?ip=...`), o estado do modelo e do sink e as 10 últimas inspeções da sessão. Ele recarrega a cada 5 s, e os IPs são detectados de novo a cada recarga (útil ao trocar para o hotspot).
- `--stub-model` responde sempre parafuso/bom (`model_version = stub-v0`). É só para desenvolvimento e **nunca** publica na nuvem (R-06).
- Códigos de saída: `2` para configuração inválida (a mensagem cita a variável, nunca o valor); `1` se `PIL.ImageFile.LOAD_TRUNCATED_IMAGES` estiver ligada no processo (SEC-04).
- O log do servidor nunca mostra o token nem o `DEVICE_API_KEY`. O access log do uvicorn fica desligado, porque imprimiria a query `?t=<token>`. No lugar dele, o `qc-edge` registra uma linha por requisição, com método, rota, status e duração, sem a query.

## Variáveis (`.env`, bloco `qc-edge`)

| Variável | Padrão | Regra |
|---|---|---|
| `EDGE_HOST` | `0.0.0.0` | IP literal (IPv4 ou IPv6) |
| `EDGE_PORT` | `8000` | 1 a 65535 |
| `EDGE_SESSION_TOKEN` | gerado a cada subida (`secrets.token_urlsafe(32)`, 43 caracteres) | se definido, no mínimo 32 caracteres. É segredo: fica fora do Git |
| `DEVICE_ID` | `edge-01` | `^[a-z0-9-]{3,32}$` (sem quebra de linha final) |
| `EDGE_DATA_DIR` | `edge/data` (relativo ao diretório atual) | criado se não existir; está no `.gitignore` |
| `DATASET_DIR` | `ml/data` (relativo ao diretório atual) | modo coleta; se existir, tem de ser um diretório. Não é criado na subida: a primeira coleta o cria com `0700`. `ml/data/` está no `.gitignore`; outro caminho deve ficar fora do repositório |
| `DEVICE_API_KEY`, `CLOUD_API_URL`, `MODEL_DIR`, `OUTBOX_PATH`, `TYPE_THRESHOLD`, `UNUSABLE_THRESHOLD`, `GRADE_REVIEW_THRESHOLD` | vazio | lidas agora, validadas nas SPECs 008 e 009 |

Variável vazia vale como não definida (o padrão vale).

## Rotas

| Rota | Acesso | O que faz |
|---|---|---|
| `GET /` | só loopback, sem headers de proxy | console do operador (HTML, sem JS), com a cobertura do dataset |
| `GET /capture?t=<token>` | token na query | página do celular; token errado → 401 "Sessão inválida. Leia o QR code no console." |
| `GET /static/capture.js`, `/static/capture.css` | livre | arquivos da página (sem segredo, sem recurso externo) |
| `POST /api/capture` | header `X-Session-Token` | `multipart/form-data` com `image`, `lot_id` e `mode`; no modo `collect`, `item_id`, `object_type`, `grade`, `labeler`, `angle` e `notes` no lugar do `lot_id` |
| `GET /api/status` | header `X-Session-Token` | `device_id`, `contract_version`, `model`, `sink` |

Ordem das respostas de `POST /api/capture`: token (401) → tamanho (413) → campos (422) → limitador (503 `server busy`) → imagem (415) → modelo (503 `model not loaded`). Depois: falha do inferenciador → 500 `inference failed`; falha do sink → 503 `failed to persist inspection` (a foto é apagada). O modo `collect` segue a mesma ordem até a imagem (415) e depois grava no dataset (seção "Modo coleta").

Limites da rota (`qc_edge/limits.py`, SPEC-007 §4.7):

- campo `image` de até 3 MiB (3 145 728 bytes);
- `Content-Length` de até 3,5 MiB (3 670 016 bytes), conferido antes de ler o corpo;
- até 4 M pixels, conferidos pelo cabeçalho antes de decodificar;
- depois, as regras do `qc_preprocess.load_image`: só JPEG/PNG pelo conteúdo, proporção de até 10:1, JPEG com até 64 marcadores de scan.

No máximo 2 decodificações acontecem ao mesmo tempo. Quem passa disso espera até 10 s e recebe 503 `server busy`. A página do celular sempre reduz a foto para no máximo 1280 px no lado maior e a reencoda em JPEG (q = 0,9) antes de enviar.

A foto aceita é salva em `EDGE_DATA_DIR/captures/<AAAA-MM-DD em UTC>/<inspection_id>.jpg`, com nome sempre gerado pelo servidor. Um JPEG é salvo como chegou; um PNG é reencodado em JPEG q = 90.

## Modo coleta (SPEC-010)

Serve para montar o dataset seguindo o `docs/dataset-protocol.md` (§3 captura, §4 metas, §5 manifest). Não precisa de modelo: rode `uv run --env-file .env --package qc-edge qc-edge`, sem `--stub-model`.

Na página do celular, escolha **coleta** no seletor de modo e preencha:

| Campo | Regra (a borda responde 422 se não bater) |
|---|---|
| Peça (`item_id`) | `S-000` (parafuso), `N-000` (porca) ou `O-000` (outro), com o prefixo do tipo escolhido. `T-` (ferramentas) fica para a SPEC-016 |
| Tipo (`object_type`) | parafuso, porca ou outro |
| Grau (`grade`) | um dos 5 graus para parafuso e porca; desabilitado e vazio para "outro" |
| Rotulador (`labeler`) | `a` ou `b` |
| Ângulo (`angle`) | 0 a 4 |
| Observações (`notes`) | opcional, até 200 caracteres, sem quebra de linha nem tabulação |

O lote é ignorado nesse modo. Os campos ficam guardados no navegador (`localStorage`) entre as fotos e depois de recarregar a página. A cada foto salva, o ângulo avança 1; depois do 4, volta a 0 e a página mostra "Peça completa — troque o item_id". O cartão mostra "Salvo: <item_id>, ângulo <n> (fotos desta peça: <total>)". Lembrete fixo: **sem pessoas no quadro** (R-14).

Cada foto vira:

- um arquivo `DATASET_DIR/raw/<object_type>/<grade ou _>/<item_id>__<angle>__<AAAAMMDDTHHMMSSZ>.jpg` (UTC). JPEG é salvo como chegou; PNG é reencodado em JPEG q = 90;
- uma linha em `DATASET_DIR/manifest.csv` (UTF-8 sem BOM), com as colunas `image_path,item_id,object_type,grade,labeler,angle,captured_at,capture_device,notes`. `capture_device` são os 60 primeiros caracteres do `User-Agent` do celular.

Respostas além das da tabela de rotas:

| Situação | Resposta | O que fazer |
|---|---|---|
| a mesma peça já está no manifest com outro tipo | 409 `item_id already registered with another object_type` | conferir o `item_id` (a mesma peça com outro **grau** é permitida: estágios de corrosão) |
| foto da mesma peça e ângulo no mesmo segundo | 409 `capture already exists, try again` | fotografar de novo |
| `manifest.csv` com cabeçalho diferente do esperado | 500 `manifest header mismatch` | corrigir o arquivo no notebook; nada é gravado até lá |
| `manifest.csv` com linhas ilegíveis (não UTF-8) | 500 `manifest unreadable` | idem |
| falha de disco ao gravar | 500 `failed to write dataset` | a foto não fica pela metade nem sem linha no manifest |

As gravações passam por um lock de processo e por um `flock` em `DATASET_DIR/manifest.csv.lock` (só POSIX). Tudo o que a coleta **cria** sob `DATASET_DIR` (o próprio `DATASET_DIR`, quando é ela que o cria, `raw/`, as pastas de tipo e grau) fica com `0700`, e as imagens, o `manifest.csv` e o `manifest.csv.lock` com `0600`, seja qual for o `umask`. O que já existia não é alterado. Se o `chmod` falhar, o log mostra um `WARNING` com o caminho e a coleta segue.

O console (<http://127.0.0.1:8000/>) mostra a tabela de cobertura (`imagens/meta` e `peças/meta`) por tipo e grau: 120 imagens e 12 peças por grau (mínimo 8) e, para "outro", 150 imagens e 30 objetos. Em verde, as células que atingiram as duas metas. Sem `manifest.csv`, a tabela fica zerada.

O `DATASET_DIR` nunca vai para o Git nem para a nuvem do projeto (R-02). O backup é o do `docs/dataset-protocol.md` §8 (Drive pessoal, compactado por data). Correções de rótulo e dupla rotulagem são da SPEC-011 (`labels_overrides.csv`), nunca editando a linha original.

## Firewall no Arch

Descubra qual firewall está ativo (normalmente só um responde `active`):

```bash
systemctl is-active ufw firewalld nftables
```

### ufw

```bash
sudo ufw allow 8000/tcp            # libera
sudo ufw status                    # confere
sudo ufw delete allow 8000/tcp     # desfaz
```

### firewalld

```bash
firewall-cmd --get-active-zones                       # zona da interface (Wi-Fi ou hotspot)
sudo firewall-cmd --add-port=8000/tcp                 # libera até o próximo reboot/reload
sudo firewall-cmd --permanent --add-port=8000/tcp     # opcional: permanente
sudo firewall-cmd --reload                            # só depois do --permanent
sudo firewall-cmd --remove-port=8000/tcp              # desfaz (runtime)
sudo firewall-cmd --permanent --remove-port=8000/tcp  # desfaz (permanente) + --reload
```

Se a interface estiver numa zona diferente da padrão, acrescente `--zone=<zona>` a cada comando.

### nftables

```bash
sudo nft list ruleset                                       # descubra a tabela e a chain de entrada
sudo nft add rule inet filter input tcp dport 8000 accept   # ajuste "inet filter input"
```

O `add` coloca a regra no fim da chain. Se a chain terminar com um `drop` ou `reject`, use `insert` no lugar de `add` para a regra ficar no início. Para desfazer:

```bash
sudo nft -a list chain inet filter input                    # mostra o "handle" de cada regra
sudo nft delete rule inet filter input handle <número>
```

Regras criadas com `nft` na linha de comando somem no reboot (a menos que você salve o ruleset).

## Plano B: hotspot do celular (apresentação)

1. No celular A, ligue o roteador Wi-Fi/hotspot (com senha).
2. No notebook, conecte-se a ele:
   ```bash
   nmcli dev wifi list                                   # confira o SSID
   nmcli --ask dev wifi connect <SSID>                   # pede a senha no terminal (fora do histórico)
   ```
3. Se o `qc-edge` já estiver rodando, não precisa reiniciar: espere o console recarregar (5 s). O QR code passa a usar o IP novo (os outros aparecem como links `/?ip=...`). Se aparecer o aviso "Nenhum IP de rede local foi detectado", a conexão ainda não subiu.
4. Libere a porta no firewall de novo se a zona do firewalld mudou (veja acima).
5. No celular, leia o QR **novo** (o IP mudou; o token continua o mesmo enquanto o processo estiver rodando).
6. Para voltar à rede de casa: `nmcli con up <nome da conexão de casa>`.

Plano C (`docs/architecture.md` §8): ancoragem USB. O celular ligado pelo cabo cria uma rede só entre os dois; o QR usa o IP do notebook nessa interface. Túneis públicos (Cloudflare e afins) são **proibidos**, porque as fotos passariam por fora da LAN (R-02).

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
