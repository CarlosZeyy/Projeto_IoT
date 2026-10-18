# SPEC-025: Manutenção da borda (Host do console, rede, limitador, permissões e modo coleta)

| Campo | Valor |
|---|---|
| Status | Ready |
| Rodada atual | — |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-007, SPEC-010 (`Done`) |
| Semana alvo | S3 (`Done` antes do merge da SPEC-009 **e** antes do primeiro backup do dataset no Drive) |
| Requisitos cobertos | RF-01, RF-08, RNF-03, RNF-05, RNF-06 (e R-02, R-14) |
| ADRs relevantes | ADR-002, ADR-003 |

## 1. Contexto

Fecha as pendências dos portões r1 da SPEC-007 (`reviews/SPEC-007/r1-review-report.md` e `r1-security-report.md`) que mudam o comportamento do `qc-edge`, uma pendência de testes da SPEC-004 e as pendências de código da borda deixadas pelo portão r1 da SPEC-010 (`reviews/SPEC-010/r1-review-report.md` e `r1-security-report.md`). Altera o que a SPEC-007 definiu em `docs/architecture.md` §6.1, §6.4, §8 e §9 e o que a SPEC-010 definiu em §6.3.

| Pendência | Severidade | O que entra aqui |
|---|---|---|
| SEC-01 | média, **prazo: `Done` antes do merge da SPEC-009** | O console valida o header `Host` (§4.1) |
| SEC-03 (= RV-02) | baixa | A espera por um slot de decodificação deixa de ocupar thread do threadpool (§4.2) |
| SEC-04 (= RV-03) | informativa | `EDGE_HOST` só aceita IPv4 (§4.3) |
| SEC-06 (parte de `captures/`) | baixa | Permissões `0700`/`0600` das fotos de inspeção (§4.4). A parte de `DATASET_DIR` é da SPEC-010; a retenção está em `docs/dataset-protocol.md` §9 |
| RV-05 | baixa | Argumento desconhecido na CLI → código 2 (§4.5) |
| SEC-05, SEC-07, RV-04 | baixa / informativa | `edge/README.md` e `.env.example` (§4.6) |
| RV-02 de `reviews/SPEC-004/r2-review-report.md` | baixa | Docstrings desatualizadas em dois testes de aceite (§4.7) |
| SEC-10-01 (= RV-03 da SPEC-010) | baixa, **prazo: `Done` antes do primeiro backup do dataset no Drive** | O modo coleta grava o JPEG sem EXIF, XMP, IPTC, comentário e dados depois do EOI (§4.8); varredura e correção do dataset já gravado (§4.9) |
| SEC-10-02 (= RV-04 da SPEC-010) | baixa | `fsync` dos diretórios na gravação da coleta (§4.10) |
| SEC-10-03 | baixa | `notes` recusa separadores de linha e controles bidi; `capture_device` sem caracteres de controle (§4.11) |
| RV-02 (= O-01) da SPEC-010 | baixa | Os CAs de permissão usam também um `umask` que tira bits do dono (`0o277`) e um que não tira nada (`0o000`) (CA-09 e CA-15) |

**Por que o SEC-10-01 tem prazo.** Um JPEG enviado direto à rota (fora da página `/capture`, que reencoda pelo canvas) é gravado no dataset byte a byte, com o EXIF (GPS, aparelho, data local), o XMP e qualquer trailer depois do EOI (um Motion Photo leva o vídeo, com áudio). O dataset vai para o Drive pessoal e para o Colab (`docs/dataset-protocol.md` §8). Depois do primeiro backup, uma foto com a localização da casa de um membro da dupla já estaria fora do notebook. Até esta SPEC estar `Done`, o backup fica só local (`docs/dataset-protocol.md` §8). Enquanto o `qc-edge` roda, o operador pode abrir no navegador do notebook uma página hostil cujo domínio é "religado" (DNS rebinding) para `127.0.0.1`. A página passa a ter a mesma origem do console: a conexão vem mesmo do loopback e não traz header de proxy, então as checagens da SPEC-007 §4.4 passam, e o console responde 200 com o token no corpo (medido no servidor real). Com o token, a página chama `POST /api/capture` na mesma origem e injeta inspeções. Hoje elas param no `InMemorySink`. A partir da SPEC-009, subiriam para a nuvem como `source=live` e contaminariam o SPC. As fotos não vazam (nenhuma rota as serve). A proteção dos navegadores contra acesso à rede local varia com o navegador e a versão, por isso não conta como mitigação.

**Por que uma SPEC própria, e não uma emenda da SPEC-008.** A SPEC-008 não tem a tag `security` e trata de inferência. Além disso, a SPEC-009 não depende da SPEC-008, então o prazo "antes do merge da SPEC-009" só fica garantido se a SPEC-009 depender desta (o que foi feito no cabeçalho dela). Os demais itens tocam os mesmos arquivos (`app.py`, `config.py`, `cli.py`, `edge/README.md`) e cabem numa entrega curta.

## 2. Objetivo

O console só responde a um `Host` de loopback, a espera por um slot não trava o console nem o `/api/status`, as fotos de inspeção ficam legíveis só pelo dono, a CLI recusa argumentos desconhecidos, o `edge/README.md` ensina a abrir a porta só para a sub-rede da dupla, e o modo coleta grava fotos sem metadados de localização, com os diretórios sincronizados no disco e sem caracteres que quebrem a leitura do manifest.

## 3. Escopo

### 3.1 Dentro

- `edge/src/qc_edge/security.py`: função `is_allowed_console_host` (§4.1).
- `edge/src/qc_edge/app.py`: checagem do `Host` no console (§4.1); limitador assíncrono no `POST /api/capture`, nos dois modos (§4.2); permissões de `captures/` (§4.4); filtro do `capture_device` (§4.11).
- `edge/src/qc_edge/config.py`: `EDGE_HOST` só IPv4 (§4.3); `EDGE_DATA_DIR` criado com `0700` (§4.4).
- `edge/src/qc_edge/cli.py`: argumentos desconhecidos → código 2 (§4.5).
- `edge/src/qc_edge/jpeg.py`: `strip_private_segments`, `jpeg_private_findings` e `JpegStructureError` (§4.8).
- `edge/src/qc_edge/collect.py`: gravação do JPEG sem segmentos privados (§4.8), `fsync` dos diretórios (§4.10) e filtro de `notes` (§4.11).
- `edge/src/qc_edge/privacy.py`: CLI `python -m qc_edge.privacy` (§4.9).
- `edge/README.md` e `.env.example` (§4.6 e §4.12).
- Testes do autor em `edge/tests/` (fora de `acceptance/`). O autor pode ajustar os próprios testes que dependiam do `Host` padrão do cliente de teste, de `EDGE_HOST` IPv6, do `parse_known_args`, da gravação do JPEG da coleta byte a byte ou dos caracteres aceitos em `notes` e `capture_device`.
- **Tester desta SPEC:**
  - `edge/tests/acceptance/test_spec_025.py` (testes novos);
  - os ajustes de manutenção listados na §4.7, e nada além deles, em `edge/tests/acceptance/test_spec_007.py`, `edge/tests/acceptance/test_spec_010.py`, `tests/acceptance/test_spec_022.py` e `packages/contracts/tests/acceptance/test_spec_023.py`.

### 3.2 Fora

- Checar o `Host` nas rotas com token (`/capture`, `/api/capture`, `/api/status`): não adotado (§7).
- Baixar `CAPTURE_MAX_BYTES`/`CAPTURE_MAX_REQUEST_BYTES`: decisão futura, depois do passo 6 do CA-20 da SPEC-007 (`docs/plan.md` §3). Limite de marcadores no `qc-preprocess`: SPEC própria do pacote, se for preciso.
- Filtrar as bridges do Docker em `detect_lan_ips`: não agora; só o aviso no README (§4.6).
- Permissões de `DATASET_DIR` e dos arquivos do modo coleta → SPEC-010 (já entregue). Retenção das fotos de inspeção → `docs/dataset-protocol.md` §9 (já escrita).
- Remover metadados das fotos de inspeção (`captures/`): não adotado. Elas nunca saem do notebook (`docs/dataset-protocol.md` §9), e o modo `inspect` continua gravando o JPEG como chegou (SEC-10-01).
- Linhas sem arquivo, arquivos sem linha, `exclusions.csv` (foto com pessoa) e leitura do manifest só com `csv`/`pandas` → SPEC-011. O procedimento humano de backup e de remoção → `docs/dataset-protocol.md` §8.
- Cota de disco e limite de taxa do modo coleta (SEC-10-07) e prazo no `flock` (SEC-10-06): não adotados.
- Suporte a IPv6 na borda: não planejado. HTTPS → SPEC-019.

## 4. Requisitos detalhados

### 4.1 Console: validação do `Host` (SEC-01)

```python
# qc_edge/security.py
def is_allowed_console_host(host: str | None, port: int) -> bool
```

- Devolve `True` se, e só se, `host` (comparado sem diferenciar maiúsculas) for exatamente um destes valores: `127.0.0.1:<port>`, `localhost:<port>` ou `[::1]:<port>`. Quando `port == 80`, também aceita `127.0.0.1`, `localhost` e `[::1]` sem porta (o navegador omite a porta padrão).
- Qualquer outro valor (outro nome, outra porta, nome com ponto final como `localhost.`, IP da LAN, valor vazio, `None`) → `False`. Nada de `strip()`, de resolução de nome ou de prefixo/sufixo.
- No `GET /`, a condição da SPEC-007 §4.4 passa a ter três partes. O console responde só se:
  1. `request.client.host` ∈ {`127.0.0.1`, `::1`} (como antes);
  2. não há `X-Forwarded-For`, `Forwarded` nem `CF-Connecting-IP` (como antes);
  3. a requisição tem **exatamente um** header `Host` e `is_allowed_console_host(<valor>, settings.EDGE_PORT)` é verdadeiro. Zero ou dois ou mais headers `Host` → recusa.
- Recusa → 403 com o mesmo HTML e os mesmos headers de hoje (`FORBIDDEN_HTML`, `PAGE_HEADERS`). O corpo nunca contém o token. As três checagens vêm **antes** de `detect_lan_ips()` e de qualquer render.
- O log da recusa (nível `WARNING`) diz só o motivo (`console refused: host not allowed`), sem o valor do `Host`, que vem do cliente.
- A URL que a CLI registra (`http://127.0.0.1:<porta>/`) continua válida. Os links `/?ip=<ip>` do console são relativos e mantêm o `Host`.
- As rotas `/capture`, `/static/*`, `/api/capture` e `/api/status` **não** mudam: o celular acessa pelo IP da LAN.

### 4.2 Limitador: espera fora do threadpool (SEC-03)

Hoje o handler síncrono espera o `threading.BoundedSemaphore` dentro de uma thread do threadpool, que tem limite de 40 e é compartilhado com o console, o `/capture` e o `/api/status`. Com 45 capturas esperando, o `/api/status` levou ~2 s e a captura legítima recebeu 503 em ~18,7 s, e não em ~10 s (SEC-03).

- O handler de `POST /api/capture` passa a ser `async def`. A ordem da SPEC-007 §4.5 e da SPEC-010 não muda: token (401) → tamanho (413) → campos (422, inclusive os de coleta da SPEC-010 §4.1) → limitador (503 `server busy`) → imagem (415) → modelo (503, só `inspect`) → resto.
- `create_app` cria **um** `anyio.Semaphore(max_concurrent_decodes, max_value=max_concurrent_decodes)` por app (fora de um event loop, o anyio 4.15 devolve um adaptador que se liga ao loop no primeiro uso). O `threading.BoundedSemaphore` sai.
- A espera pelo slot acontece no event loop, com prazo de `decode_wait_s` (por exemplo, `anyio.move_on_after`). Sem slot no prazo → 503 `{"detail": "server busy"}`, como antes: nada é salvo, o inferenciador não é chamado e o sink não recebe nada.
- Com o slot, os passos 3 a 7 da SPEC-007 §4.5 (`load_capture_image`, inferência, gravação da foto e `sink.put`) rodam numa **única** chamada `await anyio.to_thread.run_sync(...)`, e o slot é liberado num `finally` **depois** que essa chamada retorna, inclusive em erro. No modo coleta, a mesma chamada única faz `load_capture_image`, a remoção dos segmentos privados (§4.8) e a gravação do `DatasetWriter` (SPEC-010 §4.2). Nenhuma dessas operações bloqueantes roda no event loop.
- Se o cliente desconectar durante a chamada, o slot só é liberado quando a thread termina. É o padrão do `anyio.to_thread.run_sync` (`abandon_on_cancel=False`), que não deve ser alterado. Assim, o semáforo continua limitando as decodificações reais.
- Os parâmetros `max_concurrent_decodes` e `decode_wait_s`, os padrões (2 e 10 s), o `ValueError` fora da faixa e a regra "toda chamada a `load_capture_image` em `qc_edge` acontece com o slot" não mudam. O limitador é **um só** para os modos `inspect` e `collect`. Como a SPEC-010 já está `Done`, a mudança vale para os dois modos.

### 4.3 `EDGE_HOST` só IPv4 (SEC-04)

- `EDGE_HOST` precisa ser um IPv4 literal: `ipaddress.IPv4Address(valor)` sem exceção. O padrão continua `0.0.0.0`. IPv6 (`::`, `::1`, `fe80::1`), nomes (`localhost`) e qualquer outro texto → `qc-edge` sai com código 2 e a mensagem cita `EDGE_HOST`, sem o valor (como na SPEC-007 §4.1).
- **Motivo:** com `EDGE_HOST=::`, o uvicorn abre o socket só IPv6 (`IPV6_V6ONLY`): a URL que o log manda abrir (`http://127.0.0.1:<porta>/`) recusa a conexão, e o celular, que usa o IPv4 do QR (`detect_lan_ips` é só IPv4), não conecta. Aceitar o IPv4 mapeado não é necessário.

### 4.4 Permissões das fotos de inspeção (SEC-06, R-14)

As permissões abaixo são **exatas**, seja qual for o `umask` do processo. Como o `umask` só remove bits, o código aplica `chmod`/`fchmod` explícito depois de criar.

| Caminho | Modo | Quando |
|---|---|---|
| `EDGE_DATA_DIR` | `0700` | só quando o `qc-edge` o cria (na validação da config). Se já existir, não é alterado |
| `EDGE_DATA_DIR/captures/` | `0700` | criado na subida (`lifespan`, depois da checagem da flag `LOAD_TRUNCATED_IMAGES`) se não existir; se já existir com outro modo, recebe `0700` na subida |
| `captures/<AAAA-MM-DD>/` | `0700` | ao ser criado |
| `captures/<dia>/<inspection_id>.jpg` | `0600` | ao ser criado (JPEG gravado como chegou ou PNG reencodado) |

- **Arquivo da foto:** criado de forma exclusiva, como o `open("xb")` de hoje, e já com o modo final. Por exemplo, `os.open` com as flags `O_WRONLY`, `O_CREAT` e `O_EXCL` e o modo `0o600`, seguido de `os.fchmod(fd, 0o600)` e `os.fdopen(fd, "wb")`.
- Um `OSError` ao aplicar o modo (por exemplo, num sistema de arquivos sem permissões POSIX) gera um `WARNING` com o caminho e o `strerror`, e o `qc-edge` segue. As fotos não saem da máquina de qualquer forma (R-02).
- Os diretórios de dia criados antes desta SPEC (`0755`) não são corrigidos um a um: `captures/` com `0700` já impede outra conta de atravessá-los.

### 4.5 CLI: argumento desconhecido → código 2 (RV-05)

- `main(argv: Sequence[str] | None = None)`. Com `None`, os argumentos são `sys.argv[1:]` (comportamento do `argparse`).
- Se sobrar qualquer argumento desconhecido, `main()` registra um erro `unknown command-line argument(s): <lista>` e sai com código 2, **sem** carregar a config e sem chamar o `uvicorn`. A lista traz só os nomes das opções: para cada item que começa com `-`, o texto antes do primeiro `=`, e só se ele casar (com `re.fullmatch`) com `--?[a-z][a-z0-9-]{0,30}`. Os demais itens (posicionais ou opções fora desse formato) entram só na contagem (`N other`). **Nunca** o valor: `--token=<segredo>` digitado por engano, ou um segredo passado como argumento solto, não pode ir para o log nem para o stderr.
- O `argparse` não pode imprimir a própria mensagem de erro com os argumentos (ex.: `unrecognized arguments: --token=...`): use `parse_known_args` e trate a sobra, ou equivalente.
- `-h`/`--help` continua imprimindo a ajuda e saindo com 0. `--stub-model` não muda.

### 4.6 `edge/README.md` e `.env.example` (SEC-04, SEC-05, SEC-07, RV-04)

1. **Variáveis:** a linha de `EDGE_HOST` diz "IPv4 literal (ex.: `0.0.0.0`, `127.0.0.1`); IPv6 e nomes são recusados (código 2)". No `.env.example`, o comentário de `EDGE_HOST` diz "IPv4 literal", e o de `EDGE_SESSION_TOKEN` recomenda deixá-lo vazio.
2. **Console:** o texto diz que ele abre em `http://127.0.0.1:<porta>/` ou `http://localhost:<porta>/` e que outro nome ou IP na barra de endereço recebe 403.
3. **Firewall** (seção reescrita): a porta é aberta **só para a sub-rede** da Wi-Fi de casa ou do hotspot, **só durante a sessão**, e a regra é desfeita no fim.
   - Descobrir a sub-rede: `ip -4 route show scope link`, na linha da interface Wi-Fi ou do hotspot (ex.: `192.168.43.0/24 dev wlan0 ...`). Ignorar `docker0`, `br-*` e `virbr*`.
   - ufw: `sudo ufw allow proto tcp from <sub-rede> to any port 8000`; desfazer com `sudo ufw delete allow proto tcp from <sub-rede> to any port 8000`. Avisar que a regra do ufw **persiste** até ser apagada.
   - firewalld (só runtime, **sem** `--permanent`): `sudo firewall-cmd --zone=<zona> --add-rich-rule='rule family="ipv4" source address="<sub-rede>" port port="8000" protocol="tcp" accept'`; desfazer com `--remove-rich-rule='<mesma regra>'`.
   - nftables: `sudo nft add rule inet filter input ip saddr <sub-rede> tcp dport 8000 accept` (ou `insert`, se a chain terminar em `drop`/`reject`); desfazer pelo `handle`, como hoje.
   - Nenhum comando de liberação do README pode abrir a porta sem origem (`ufw allow 8000/tcp`, `--add-port=8000/tcp` e `tcp dport 8000 accept` sem `saddr` saem), e o README não usa `--permanent`.
   - Frase explícita: não rodar o `qc-edge` com a porta aberta numa rede que não seja da dupla (ex.: Wi-Fi do campus).
4. **Plano B (hotspot):** o passo do firewall passa a dizer que a regra tem de ser refeita com a sub-rede do hotspot, porque o IP mudou.
5. **Seção nova `## Segurança na operação`**, com estes itens:
   - deixar `EDGE_SESSION_TOKEN` vazio, para que um token novo seja gerado a cada subida (reiniciar invalida os QR antigos);
   - não projetar o console (QR e URL com o token) na apresentação; se ele foi projetado, reiniciar o `qc-edge`;
   - hotspot sempre com senha WPA2 ou WPA3;
   - se o QR ou a lista de IPs mostrar um endereço `172.17.x.x`, `172.18.x.x` ou vizinho, é uma bridge do Docker (a sondagem UDP falhou, ex.: sem rota padrão): usar o link do IP da Wi-Fi ou do hotspot, conferido com `ip -4 addr`;
   - o bind padrão `0.0.0.0` também escuta nas bridges do Docker; a regra de firewall por sub-rede é o que limita quem alcança a porta.

Fontes da sintaxe: `firewalld.richlanguage(5)` (<https://firewalld.org/documentation/man-pages/firewalld.richlanguage.html>) e `ufw(8)` (<https://manpages.ubuntu.com/manpages/noble/en/man8/ufw.8.html>), consultadas em 2026-10-13. O developer confere os comandos no notebook antes de escrever.

### 4.7 Manutenção de testes (tester)

O tester desta SPEC faz só estas edições fora do `test_spec_025.py`. Se outro teste de aceite existente precisar mudar para a suíte passar, vale a regra "Testes de aceite de SPECs anteriores" de `docs/architecture.md` §10 (ajuste registrado na tabela do test-report, só quando decorre de um requisito escrito nesta SPEC); fora dela, ele registra `SPEC_ISSUE` e para.

1. **`edge/tests/acceptance/test_spec_007.py`** (efeito colateral das §4.1 e §4.5; nenhum CA da SPEC-007 muda):
   - as requisições ao console (`GET /`) passam a usar a URL base `http://127.0.0.1:<EDGE_PORT>` (ou o header `Host: 127.0.0.1:<EDGE_PORT>`), no lugar de `http://testserver`;
   - as chamadas a `qc_edge.cli.main()` dentro do processo do pytest passam a ser `main([])`, ou a usar `monkeypatch.setattr(sys, "argv", ["qc-edge"])`, para não herdar os argumentos do pytest;
   - um teste que hoje espere `EDGE_HOST` IPv6 aceito passa a esperar código 2.
2. **`tests/acceptance/test_spec_022.py`** (RV-02 da SPEC-004): na docstring do módulo, o trecho `(CA-01 to CA-16).` vira `(CA-01 to CA-14 and CA-16; CA-15 is checked by CI and by the test report, docs/architecture.md section 10).`
3. **`packages/contracts/tests/acceptance/test_spec_023.py`** (RV-02 da SPEC-004): na docstring do módulo, o trecho `CA-03 to CA-06\nand CA-13.` vira `CA-03 to CA-06\n(CA-13 is checked by CI and by the test report, docs/architecture.md section 10).`
4. **`edge/tests/acceptance/test_spec_010.py`** (efeito colateral das §4.8 e §4.11; nenhum CA da SPEC-010 muda de intenção). Nenhum ajuste é esperado: o console já usa `Host` de loopback, os JPEGs dos testes são gerados pelo Pillow (sem APP1, APP13, COM nem trailer, então continuam gravados byte a byte, §4.8) e nenhum teste envia `notes` ou `User-Agent` com os caracteres da §4.11. Se algum teste dessa SPEC verificar exatamente o comportamento substituído (bytes de um JPEG com metadados ou trailer gravados como chegaram; `notes` com `Zl`, `Zp` ou `Cf` aceito; `capture_device` com controle gravado como chegou), o tester só troca a asserção afetada, pela regra de §10.

Nos itens 2 e 3, só a docstring muda, e a contagem de testes coletados de cada arquivo continua a da `main`.

### 4.8 Modo coleta: JPEG sem segmentos privados (SEC-10-01, R-14)

```python
# qc_edge/jpeg.py
class JpegStructureError(ValueError): ...
def strip_private_segments(data: bytes) -> bytes
def jpeg_private_findings(data: bytes) -> frozenset[str]   # subconjunto de {"app1", "app13", "com", "trailer"}
```

- **Varredura estrutural**, nunca busca de bytes soltos. Um `FF D9` pode aparecer dentro de um APPn ou COM, ou numa miniatura do EXIF (nota da SPEC-011 §7). A partir do SOI (`FF D8`), percorrer os marcadores em ordem:
  - bytes `FF` de preenchimento antes de um marcador são copiados como estão;
  - RSTn (`FF D0`–`FF D7`) e TEM (`FF 01`) não têm comprimento e são copiados;
  - todo outro marcador tem 2 bytes de comprimento (big-endian, ≥ 2, incluindo os próprios 2 bytes);
  - **APP1 (`FF E1`, EXIF e XMP), APP13 (`FF ED`, IPTC) e COM (`FF FE`) não são copiados.** Os demais segmentos (APP0/JFIF, APP2/ICC, APP14/Adobe, DQT, SOFn, DHT, DRI, SOS etc.) são copiados como estão;
  - depois do cabeçalho de cada SOS, os dados de entropia são copiados até o próximo marcador: `FF 00` e `FF D0`–`FF D7` fazem parte dos dados; qualquer outro `FF xx` encerra os dados e volta à leitura de marcadores;
  - no EOI (`FF D9`), copiar o EOI e parar. Nada do que vem depois dele é gravado.
- **Sem nada a remover** (nenhum APP1, APP13 nem COM, e o EOI é o fim do arquivo), a saída é **idêntica, byte a byte**, à entrada. É o caso das fotos que passam pela página `/capture` e dos JPEGs gerados pelo Pillow.
- Os dados de entropia não mudam, então a imagem decodificada é a mesma, pixel a pixel. Não há reencode.
- `jpeg_private_findings` faz a mesma varredura e devolve o que `strip_private_segments` removeria: `app1`, `app13`, `com` e `trailer` (bytes depois do EOI). Os nomes são fixos; a função nunca devolve nem registra o conteúdo dos segmentos.
- **Erro estrutural** (não começa com SOI, comprimento menor que 2 ou além do fim, arquivo termina antes do EOI) → `JpegStructureError`, cuja mensagem não contém bytes do arquivo.
- **Na rota** (só `mode=collect`): depois de `load_capture_image` aceitar a imagem (as regras de tamanho, pixels e scans valem sobre os bytes **recebidos**), e se a imagem for JPEG, o `DatasetWriter` grava `strip_private_segments(data)` no lugar de `data`. É a única mudança do passo 4 da SPEC-010 §4.2 ("JPEG: bytes recebidos"). `JpegStructureError` → 415 `{"detail": "invalid image: unsupported JPEG structure"}`, dentro do slot e sem gravar nada. O PNG continua reencodado em JPEG q=90 (o Pillow não copia metadados sem o parâmetro `exif`).
- O modo `inspect` (`captures/`) **não muda**: continua gravando o JPEG como chegou (§3.2).

### 4.9 Varredura do dataset: `python -m qc_edge.privacy` (SEC-10-01)

`python -m qc_edge.privacy --dataset-dir <D> [--fix]` (`main(argv: Sequence[str] | None = None) -> int`) confere as imagens já gravadas, inclusive as coletadas antes desta SPEC ou copiadas à mão.

- Percorre os arquivos regulares `*.jpg` sob `<D>/raw/`, em ordem de caminho, sem seguir links simbólicos (`os.walk(..., followlinks=False)`, ignorando links). Para cada um, chama `jpeg_private_findings`; `JpegStructureError` vira o achado `invalid`.
- Para cada arquivo com achado, imprime uma linha `<caminho relativo a D, com />: <achados separados por vírgula, em ordem alfabética>`. No fim, `checked <n> images, <k> with private data`. A saída nunca mostra o conteúdo dos metadados (GPS, aparelho, data) nem caminhos absolutos.
- **Sem `--fix`:** só lê. Código `0` se `k = 0`; `1` se houver achados.
- **Com `--fix`:** segurando o `flock` de `<D>/manifest.csv.lock` (o mesmo lock da SPEC-010 §4.2, criado com `0600` se não existir), reescreve cada arquivo com achado, exceto `invalid`, com `strip_private_segments`: temporário no mesmo diretório criado com `0600` (seja qual for o `umask`), `fsync`, `os.replace` sobre o original e `fsync` do diretório (§4.10). Imprime `fixed <caminho relativo>` por arquivo. O `manifest.csv` não muda (o `image_path` continua o mesmo). Código `0` se nada sobrar além de arquivos limpos; `1` se sobrar algum `invalid` (que a dupla apaga e registra em `exclusions.csv`, `docs/dataset-protocol.md` §8.1).
- `<D>` inexistente ou que não é diretório, ou argumento desconhecido → código 2, com a mesma regra de não eco da §4.5 (só nomes de opção no formato permitido).
- Os erros vão para o `logging`; as linhas acima são a saída da CLI (stdout).
- Não faz nenhuma conexão de rede (R-02).

### 4.10 Modo coleta: `fsync` dos diretórios (SEC-10-02)

Na gravação do `DatasetWriter` (SPEC-010 §4.2), com `fsync_dir(path)` = `os.open(path, os.O_RDONLY | os.O_DIRECTORY)`, `os.fsync` e `os.close`:

1. depois de criar cada diretório (inclusive `DATASET_DIR`, quando é a borda que o cria), `fsync_dir` do diretório **pai** dele;
2. depois do `rename` da imagem, `fsync_dir` do diretório da imagem, **antes** de acrescentar a linha ao manifest;
3. quando o `manifest.csv` é criado nesta coleta, `fsync_dir(DATASET_DIR)` depois do `fsync` do manifest.

Um `OSError` num `fsync_dir` (por exemplo, `EINVAL` num sistema de arquivos sem suporte) gera um `WARNING` com o caminho relativo e o `strerror`, e a coleta segue. A ordem dos passos 1 a 5 da SPEC-010 §4.2, o rollback e as respostas não mudam. O `--fix` da §4.9 usa o mesmo `fsync_dir`.

### 4.11 Modo coleta: `notes` e `capture_device` (SEC-10-03)

- `notes`: além das regras da SPEC-010 §4.1, recusa (422, antes de tocar o disco) qualquer caractere cuja `unicodedata.category` esteja em {`Cc`, `Cs`, `Cf`, `Zl`, `Zp`}. Isso inclui U+2028/U+2029 (separadores de linha e de parágrafo), os controles bidi (U+202A–U+202E, U+2066–U+2069, U+200E, U+200F, U+061C) e o hífen suave U+00AD. O texto aceito continua gravado sem alteração.
- `capture_device`: cada caractere do `User-Agent` cuja categoria esteja em {`Cc`, `Cs`, `Cf`, `Zl`, `Zp`} é trocado por um espaço (U+0020), e só **depois** o valor é cortado nos 60 primeiros caracteres. Os outros caracteres não mudam. O `User-Agent` não recusa a coleta.
- Com isso, `str.splitlines()` do manifest gravado depois desta SPEC conta exatamente uma linha por registro. Linhas antigas continuam valendo; a SPEC-011 lê o manifest só com `csv`/`pandas`.

### 4.12 `edge/README.md` (seção "Modo coleta")

Acrescentar, nesta ordem:

1. o modo coleta grava o JPEG sem EXIF, XMP, IPTC, comentário e dados depois do EOI (§4.8), sem reencodar;
2. antes de **cada** backup do dataset no Drive, rodar `uv run --package qc-edge python -m qc_edge.privacy --dataset-dir ml/data` e, havendo achados, repetir com `--fix` (que pode rodar com o `qc-edge` ligado, porque usa o mesmo lock da coleta); o procedimento completo está em `docs/dataset-protocol.md` §8;
3. um aviso de que fotos copiadas à mão para `raw/` (por exemplo, do app da câmera) passam pela mesma varredura.

## 5. Critérios de aceite

Contexto comum: `EdgeSettings` com `EDGE_PORT=8000` e `EDGE_DATA_DIR` e `DATASET_DIR` em `tmp_path`; `StubInferencer` (SPEC-007) e `InMemorySink`; o token de sessão gerado nos testes (nunca literal). "Console de loopback" = `httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))`. "Coleta válida" = os campos do CA-01 da SPEC-010 (`S-012`, `screw`, `fair`, `a`, ângulo 2). "JPEG com metadados" = um JPEG 64×48 gerado pelo Pillow com `exif` contendo o IFD GPS (`GPSLatitude`), com um segmento APP1 de XMP (prefixo `http://ns.adobe.com/xap/1.0/\x00`), um APP13 (prefixo `Photoshop 3.0\x00`) e um COM com um marcador gerado no teste, inseridos logo depois do SOI, e seguido, depois do EOI, de `b"\x00\x00\x00\x18ftypmp42"` e 200 000 bytes `b"\x00"`.

- **CA-01** — *Dado* o console de loopback, *quando* `GET /` é enviado com `Host` igual a `127.0.0.1:8000`, `localhost:8000`, `LOCALHOST:8000` e `[::1]:8000`, *então* cada resposta é 200 e contém `<svg`.
- **CA-02 (security, SEC-01)** — *Dado* o console de loopback e um espião em `qc_edge.netinfo.detect_lan_ips`, *quando* `GET /` é enviado com `Host` igual a `attacker.example:8000`, `127.0.0.1` (sem porta), `127.0.0.1:8001`, `localhost.:8000`, `127.0.0.1.nip.io:8000` ou `192.168.0.42:8000`, e, via ASGI cru, com `Host` vazio, sem nenhum header `Host` e com dois headers `Host` (`127.0.0.1:8000` e `attacker.example:8000`), *então* cada resposta é 403, nenhum corpo contém o token, o espião tem 0 chamadas e nenhum registro de log contém `attacker.example`.
- **CA-03** — *Dado* `EDGE_PORT=80` e o console de loopback, *quando* `GET /` é enviado com `Host` igual a `127.0.0.1`, `localhost`, `[::1]` e `127.0.0.1:80`, *então* cada resposta é 200; com `attacker.example`, 403. E `is_allowed_console_host(None, 8000)` e `is_allowed_console_host("", 80)` devolvem `False`.
- **CA-04 (security, SEC-01, servidor real)** — *Dado* `qc-edge --stub-model` rodando em subprocesso com `EDGE_HOST=127.0.0.1`, uma porta livre `p` e `EDGE_DATA_DIR` temporário, *quando* `GET http://127.0.0.1:<p>/` é enviado com `Host: attacker.example:<p>`, *então* a resposta é 403 e não contém o token; e, com o `Host` padrão do cliente (`127.0.0.1:<p>`), 200 com `<svg`. O processo é encerrado no fim.
- **CA-05** — *Dado* `ASGITransport(client=("192.168.0.50", 50000))` e o token válido, *quando* `GET /capture?t=<token>` é enviado com `Host: 192.168.0.42:8000` e `POST /api/capture` (JPEG válido, `lot_id=L-001`, `mode=inspect`) com `Host: 10.0.0.7:8000`, *então* as respostas são 200 e 200 (as rotas com token não checam o `Host`).
- **CA-06 (SEC-04)** — *Dado* `EDGE_HOST` igual a `::`, `::1`, `fe80::1` ou `localhost`, *quando* `main([])` é chamado com `uvicorn.run` substituído por um espião, *então* sai com código 2, a saída de log cita `EDGE_HOST` e o espião não é chamado; *dado* `0.0.0.0`, `127.0.0.1` ou `192.168.0.10`, *então* o espião é chamado 1 vez com `host` igual ao valor.
- **CA-07 (security, SEC-03)** — *Dado* `create_app(..., max_concurrent_decodes=1, decode_wait_s=3)` e um inferenciador de teste cujo `infer` registra o máximo de chamadas simultâneas, verifica que **não** há event loop rodando na thread (`asyncio.get_running_loop()` levanta `RuntimeError`) e bloqueia até um `threading.Event` ser liberado, *quando* 1 captura válida ocupa o slot (o teste espera o `infer` começar) e, em seguida, 45 capturas válidas são enviadas em paralelo, *então*:
  - um `GET /api/status` com o token, enviado 0,5 s depois das 45, responde 200 em menos de 1,0 s;
  - cada uma das 45 recebe 503 `{"detail": "server busy"}` em no máximo 5,0 s (`decode_wait_s` + 2 s) depois do próprio envio;
  - depois que o evento é liberado, a primeira captura recebe 200, o máximo de chamadas simultâneas a `infer` é 1, o sink tem 1 item e `captures/` tem exatamente 1 arquivo `.jpg`.

  As requisições podem usar threads com `TestClient` ou tarefas com `httpx.AsyncClient(transport=httpx.ASGITransport(app=app))` no mesmo event loop.
- **CA-08 (SEC-03)** — *Dado* um espião em `qc_edge.limits.load_capture_image` (que chama o original) que registra se há event loop rodando na thread, *quando* uma captura válida, uma com GIF (415) e uma coleta válida (`mode=collect`) são enviadas, *então* o espião é chamado 3 vezes, nas três sem event loop rodando na thread; e, *dado* `max_concurrent_decodes=1` e um inferenciador que lança `InferenceError` na 1ª chamada, *quando* 3 capturas são enviadas em sequência, *então* as respostas são 500, 200 e 200 (o slot é liberado depois do erro).
- **CA-09 (security, SEC-06, R-14)** — *Dado* `os.umask(u)`, com `u` em `0o022`, `0o077`, `0o000` e `0o277` (uma execução por valor; o `0o277` tira bits do próprio dono e só passa com o `chmod`/`fchmod` explícito; RV-02 de `reviews/SPEC-010/r1-review-report.md`), com o umask original restaurado no fim, e `EDGE_DATA_DIR` inexistente, *quando* a config é carregada, o app sobe e são aceitas uma captura JPEG e uma PNG, *então* `stat.S_IMODE` dá `0o700` para `EDGE_DATA_DIR`, `captures/` e `captures/<dia>/`, e `0o600` para os 2 arquivos `.jpg`. *Dado* `EDGE_DATA_DIR` já existente com `0o755` e `captures/` já existente com `0o755`, *quando* o app sobe (`with TestClient(app)`), *então* `captures/` fica com `0o700` e `EDGE_DATA_DIR` continua `0o755`.
- **CA-10 (RV-05)** — *Dado* `uvicorn.run` substituído por um espião, *quando* `main(["--stub-modle"])`, `main(["--token=<marcador>"])` (marcador gerado no teste) e `main(["<marcador-posicional>"])` são chamados, *então* cada um sai com código 2, o espião não é chamado, a saída de log do 1º contém `--stub-modle`, e nem o log (`caplog`) nem o stdout/stderr (`capsys`) contêm algum dos marcadores; e `main([])` e `main(["--stub-model"])` chamam o espião 1 vez cada.
- **CA-11 (SEC-04, SEC-05, SEC-07, RV-04)** — *Dado* o texto de `edge/README.md`, *então*:
  - toda linha **dentro de um bloco de código** (entre cercas ```` ``` ````) que contém `ufw allow`, `firewall-cmd` com `--add-` ou `nft add rule`/`nft insert rule` contém também `from <sub-rede>`, `source address=` ou `saddr` (no README, `<sub-rede>` pode ser o marcador literal ou um exemplo como `192.168.43.0/24`; o teste procura a palavra `from` seguida de espaço);
  - nenhuma linha dentro de bloco de código contém `--permanent`, e o texto contém `ip -4 route show scope link`;
  - há uma seção cujo título é `## Segurança na operação`, e o trecho dela até o próximo título de nível 2 contém `EDGE_SESSION_TOKEN`, `WPA2` e `172.17.`;
  - a linha da tabela de variáveis que começa com `` | `EDGE_HOST` `` contém `IPv4` e não contém `ou IPv6`;
  - o trecho da seção cujo título contém `Modo coleta`, até o próximo título de nível igual ou superior, contém `python -m qc_edge.privacy`, `--fix` e `dataset-protocol.md` (§4.12).

  *Dado* `.env.example`, *então* a linha de comentário imediatamente acima de `EDGE_HOST=` contém `IPv4`.
- **CA-12 (manutenção, RV-02 da SPEC-004)** — *Dado* `ast.get_docstring` dos módulos `tests/acceptance/test_spec_022.py` e `packages/contracts/tests/acceptance/test_spec_023.py`, *então* a primeira não contém `CA-01 to CA-16` e contém `CA-15 is checked by CI`, e a segunda não contém `and CA-13` e contém `CA-13 is checked by CI`; e `uv run pytest --collect-only -q <arquivo>`, com cada caminho explícito, coleta nos dois arquivos o mesmo número de testes da `main`.
- **CA-13 (security, SEC-10-01, R-14)** — *Dado* o JPEG com metadados, *quando* é enviado numa coleta válida, *então* a resposta é 200 e o arquivo gravado em `DATASET_DIR`: não contém `b"Exif\x00\x00"`, `b"http://ns.adobe.com/xap/1.0/"`, `b"Photoshop 3.0"`, o marcador do COM nem `b"ftypmp42"`; termina com `b"\xff\xd9"`; tem `len(Image.open(<arquivo>).getexif()) == 0`; e decodifica para os mesmos pixels do JPEG enviado (`np.array_equal` dos dois `np.asarray(Image.open(...).convert("RGB"))`). *Dado* um JPEG gerado pelo Pillow sem esses segmentos e sem trailer, *então* o arquivo gravado é igual, byte a byte, ao enviado. *Dado* o JPEG com metadados enviado com `mode=inspect`, *então* o arquivo em `captures/` é igual, byte a byte, ao enviado (o modo `inspect` não muda).
- **CA-14 (SEC-10-01)** — *Dado* `strip_private_segments` e `jpeg_private_findings`, *quando* recebem o JPEG com metadados, *então* `jpeg_private_findings` devolve `frozenset({"app1", "app13", "com", "trailer"})` e o resultado de `strip_private_segments` dá `frozenset()`; *dado* um JPEG com um APP1 cujo conteúdo contém `b"\xff\xd9"` no meio, *então* a saída ainda contém todos os segmentos DQT, SOF, DHT e SOS da entrada e decodifica para os mesmos pixels; *dado* `b"not a jpeg"`, os 100 primeiros bytes de um JPEG válido (sem EOI) e um JPEG com um segmento APP0 de comprimento 1, *então* as duas funções levantam `JpegStructureError`, e a mensagem não contém bytes da entrada.
- **CA-15 (security, SEC-10-01, R-14)** — *Dado* `DATASET_DIR` com `manifest.csv` e três imagens em `raw/screw/fair/`: `a.jpg` (JPEG do Pillow, limpo), `b.jpg` (só com o EXIF GPS) e `c.jpg` (só com o trailer), mais um link simbólico `raw/screw/fair/d.jpg` para um JPEG com metadados fora de `DATASET_DIR`, *quando* `main(["--dataset-dir", <D>])` roda, *então* o código é 1, o stdout tem exatamente as linhas `raw/screw/fair/b.jpg: app1` e `raw/screw/fair/c.jpg: trailer` e termina com `checked 3 images, 2 with private data`, não contém `<D>` absoluto nem o valor de latitude, e nenhum arquivo muda (bytes iguais). *Quando*, em seguida, `main(["--dataset-dir", <D>, "--fix"])` roda com `os.umask(u)` para `u` em `0o022` e `0o277` (uma execução por valor, cada uma com o dataset recriado; umask restaurado no fim), *então* o código é 0, o stdout tem `fixed raw/screw/fair/b.jpg` e `fixed raw/screw/fair/c.jpg`, `b.jpg` e `c.jpg` não têm achados, decodificam para os mesmos pixels de antes e têm modo `0o600`, `a.jpg`, `manifest.csv` e o alvo do link ficam iguais byte a byte, e nenhum arquivo temporário sobra; e uma nova execução sem `--fix` sai com 0 e `checked 3 images, 0 with private data`. *Dado* `--dataset-dir` inexistente, ou um argumento `--token=<marcador>` gerado no teste, *então* o código é 2 e o marcador não aparece no stdout, no stderr nem no log.
- **CA-16 (SEC-10-01)** — *Dado* um JPEG em que `strip_private_segments` levanta `JpegStructureError` mas que `load_capture_image` aceita (o teste substitui `qc_edge.jpeg.strip_private_segments` por uma função que levanta), *quando* é enviado numa coleta válida, *então* a resposta é 415 com `{"detail": "invalid image: unsupported JPEG structure"}`, `DATASET_DIR` não ganha imagem nem linha no manifest, e uma captura seguinte (`mode=inspect`) recebe 200 (o slot foi liberado).
- **CA-17 (SEC-10-02)** — *Dado* `DATASET_DIR` inexistente e um espião em `os.fsync` (que chama o original) que registra, para cada chamada, o caminho do descritor (`os.readlink(f"/proc/self/fd/{fd}")`), *quando* uma coleta válida é feita, *então* a lista registrada contém, nesta ordem relativa: o pai de `DATASET_DIR`, `DATASET_DIR`, `raw`, `raw/screw` (fsync dos pais dos diretórios criados, em qualquer ordem entre si), um arquivo dentro de `raw/screw/fair/`, `raw/screw/fair`, `manifest.csv` e `DATASET_DIR` (o manifest foi criado nesta coleta). *Dado* o mesmo espião levantando `OSError(errno.EINVAL, ...)` só quando o descritor é de diretório, *então* a coleta responde 200, a linha está no manifest, a imagem existe e há um registro `WARNING` por diretório recusado.
- **CA-18 (security, SEC-10-03)** — *Dado* `notes` com um destes caracteres no meio de um texto válido: U+2028, U+2029, U+202E, U+2066, U+200F ou U+00AD, *quando* é enviado numa coleta válida, *então* cada resposta é 422 e `DATASET_DIR` continua vazio; com `notes="dúvida fair/poor"`, 200 e o texto gravado igual. *Dado* um `User-Agent` enviado em bytes (ASGI cru) como `b"Phone\x85X\tY" + b"z" * 70`, *quando* a coleta é feita, *então* o `capture_device` do manifest é `"Phone X Y" + "z" * 51` (60 caracteres, com os dois controles trocados por espaço antes do corte), e `manifest.csv.read_text().splitlines()` tem exatamente 2 linhas (cabeçalho e registro).

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | `is_allowed_console_host` (tabela de casos), console com `Host`, limitador assíncrono, validação de `EDGE_HOST`, modos de arquivo, CLI; varredura de JPEG (marcadores, `FF D9` dentro de APPn, RSTn, preenchimento, progressivo com vários SOS), `--fix`, `fsync_dir`, filtros de `notes` e `capture_device` | `edge/tests/` |
| Aceite (tester) | Um por CA; mais as edições de manutenção da §4.7 | `edge/tests/acceptance/test_spec_025.py` e os arquivos da §4.7 |

- Sem rede externa. O servidor do CA-04 escuta só em `127.0.0.1`, como o CA-19 da SPEC-007.
- Mock só de fronteiras: socket (`detect_lan_ips`), `uvicorn.run`, o inferenciador e, nos CA-16 e CA-17, `strip_private_segments` e `os.fsync` (espiões que chamam o original, salvo o caso de erro).
- Os JPEGs com metadados são montados no teste (Pillow + bytes inseridos), nunca fotos reais (R-14). O CA-17 usa `/proc/self/fd`, disponível no Linux do notebook e do CI.
- O CA-12 roda o pytest em subprocesso só com caminhos de arquivo explícitos e sem banco (`docs/architecture.md` §10).
- O `umask` é estado global do processo: o teste do CA-09 o restaura num `finally`.

## 7. Riscos e notas para o implementador

- **Por que só o console checa o `Host`:** é a única rota que entrega o token sem pedir o token. Nas outras, uma página hostil religada não tem o token e recebe 401. Restringir o `Host` delas aos IPs de `detect_lan_ips()` quebraria o celular sempre que a lista mudasse entre o render do QR e a requisição (troca de rede, bridges do Docker), sem ganho real.
- **Testes de outras SPECs:** depois desta SPEC, todo teste que chama o console precisa de `Host` de loopback (URL base `http://127.0.0.1:8000`). Isso vale para o CA-18 da SPEC-008 e o CA-15 da SPEC-010. O `TestClient` usa `http://testserver` e o cliente `testclient`, então o console já respondia 403 por ele. Use `ASGITransport(client=("127.0.0.1", ...))` com a URL base de loopback.
- **Limitador:** não troque o `anyio.Semaphore` por um `asyncio.Semaphore` criado em `create_app`, que se liga ao primeiro event loop que o usa: os testes sobem vários `TestClient` com o mesmo app. Não use `limit_concurrency` do uvicorn: ele recusaria também o console durante uma rajada.
- `anyio.to_thread.run_sync` usa o mesmo limitador de threads do Starlette (40). Só quem tem o slot (no máximo `max_concurrent_decodes`) ocupa thread, então o console e o `/api/status` continuam com folga.
- **Ordem da subida:** a criação e o `chmod` de `captures/` ficam no `lifespan`, depois da checagem de `LOAD_TRUNCATED_IMAGES` e antes dos `BackgroundService`. Com `httpx.ASGITransport` (que não roda o `lifespan`), a primeira gravação cria `captures/` com `0700` do mesmo jeito.
- **`umask` e `mkdir(mode=0o700)`:** o `mode` do `mkdir` também passa pelo `umask`. O `chmod` explícito é o que torna o modo exato.
- O ufw guarda as regras entre reinícios. O firewalld sem `--permanent` e o `nft` pela linha de comando não guardam.
- **Remoção dos segmentos (§4.8):** a limitação de scans do `load_image` (SPEC-024) vale sobre os bytes recebidos, antes da remoção, e a saída nunca tem mais marcadores que a entrada. Não use o Pillow para "limpar" (reencode muda os pixels e a qualidade, RV-03 da SPEC-010). APP2 (perfil ICC) e APP14 (Adobe, que define a conversão de cor) ficam: remover o APP14 pode mudar as cores decodificadas.
- **`jpeg_private_findings` × SPEC-011:** a SPEC-011 não repete esta varredura; ela acusa linha sem arquivo e arquivo sem linha. A varredura de privacidade antes do backup é a CLI da §4.9 (`docs/dataset-protocol.md` §8).
- **`fsync` de diretório (§4.10):** em btrfs, o `fsync` de um arquivo não garante o `rename` de outro; sem a §4.10, uma queda de energia pode deixar no manifest uma linha sem imagem (SEC-10-02). A SPEC-011 continua acusando os dois casos como controle compensatório.
- **`User-Agent` em latin-1:** o h11 aceita bytes 0x80–0xFF e o Starlette decodifica em latin-1, então os controles C1 (U+0080–U+009F) chegam como `Cc`. U+2028 e os controles bidi não chegam por esse caminho, mas a regra da §4.11 é a mesma para não depender disso.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `edge/README.md` e `.env.example` atualizados
- [ ] PR aberto com os relatórios; merge **antes** do merge da SPEC-009 e **antes** do primeiro backup do dataset no Drive (`docs/dataset-protocol.md` §8)

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-13 | SPEC criada (Draft). | SEC-01, SEC-03, SEC-04, SEC-05, SEC-06 (parte de `captures/`) e SEC-07 de `reviews/SPEC-007/r1-security-report.md`; RV-04 e RV-05 de `reviews/SPEC-007/r1-review-report.md`; RV-02 de `reviews/SPEC-004/r2-review-report.md` | Orquestrador, a pedido do humano |
| 2026-10-13 | `Draft` → `Ready`. Aprovação humana, com 422 para a classe 23 e retenção das fotos até a entrega. | Aprovação humana | Humano (Carlos) |
| 2026-10-17 | Mudanças: (a) título e cabeçalho (depende da SPEC-010, já `Done`; prazo também antes do primeiro backup do dataset no Drive); (b) §1 com as pendências de código da SPEC-010; (c) §3 com os arquivos novos e o que fica fora; (d) §4.2: ordem sem o 501 e o limitador assíncrono valendo para os dois modos; (e) §4.7: ajustes em testes antigos pela regra de `architecture.md` §10, com o item 4 (`test_spec_010.py`); (f) §4.8 nova: o modo coleta grava o JPEG sem APP1, APP13, COM e dados depois do EOI, sem reencodar (415 em erro estrutural; o modo `inspect` não muda); (g) §4.9 nova: CLI `python -m qc_edge.privacy` (varredura e `--fix`); (h) §4.10 nova: `fsync` dos diretórios na coleta; (i) §4.11 nova: `notes` recusa `Cf`, `Zl` e `Zp`, e `capture_device` troca controles por espaço antes do corte; (j) §4.12 nova: README do modo coleta; (k) CA-08 inclui uma coleta, CA-09 ganha os umasks `0o000` e `0o277`, CA-11 confere o README; CAs novos CA-13 a CA-18; §6, §7 e §8 atualizadas. Nenhum outro CA muda. SPEC marcada como "Aguardando reaprovação humana". | SEC-10-01, SEC-10-02 e SEC-10-03 de `reviews/SPEC-010/r1-security-report.md`; RV-02 (O-01), RV-03 e RV-04 de `reviews/SPEC-010/r1-review-report.md` | Orquestrador, a pedido do humano |
| 2026-10-18 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
