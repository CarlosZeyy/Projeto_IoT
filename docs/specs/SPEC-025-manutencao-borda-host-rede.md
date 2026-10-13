# SPEC-025: Manutenção da borda (Host do console, rede, limitador e permissões)

| Campo | Valor |
|---|---|
| Status | Draft |
| Rodada atual | — |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-007 |
| Semana alvo | S3 (antes do merge da SPEC-009) |
| Requisitos cobertos | RF-01, RNF-03, RNF-05, RNF-06 (e R-14) |
| ADRs relevantes | ADR-002, ADR-003 |

## 1. Contexto

Fecha as pendências dos portões r1 da SPEC-007 (`reviews/SPEC-007/r1-review-report.md` e `r1-security-report.md`) que mudam o comportamento do `qc-edge`, e uma pendência de testes da SPEC-004. Altera o que a SPEC-007 definiu em `docs/architecture.md` §6.1, §6.4, §8 e §9.

| Pendência | Severidade | O que entra aqui |
|---|---|---|
| SEC-01 | média, **prazo: `Done` antes do merge da SPEC-009** | O console valida o header `Host` (§4.1) |
| SEC-03 (= RV-02) | baixa | A espera por um slot de decodificação deixa de ocupar thread do threadpool (§4.2) |
| SEC-04 (= RV-03) | informativa | `EDGE_HOST` só aceita IPv4 (§4.3) |
| SEC-06 (parte de `captures/`) | baixa | Permissões `0700`/`0600` das fotos de inspeção (§4.4). A parte de `DATASET_DIR` é da SPEC-010; a retenção está em `docs/dataset-protocol.md` §9 |
| RV-05 | baixa | Argumento desconhecido na CLI → código 2 (§4.5) |
| SEC-05, SEC-07, RV-04 | baixa / informativa | `edge/README.md` e `.env.example` (§4.6) |
| RV-02 de `reviews/SPEC-004/r2-review-report.md` | baixa | Docstrings desatualizadas em dois testes de aceite (§4.7) |

**Por que o SEC-01 tem prazo.** Enquanto o `qc-edge` roda, o operador pode abrir no navegador do notebook uma página hostil cujo domínio é "religado" (DNS rebinding) para `127.0.0.1`. A página passa a ter a mesma origem do console: a conexão vem mesmo do loopback e não traz header de proxy, então as checagens da SPEC-007 §4.4 passam, e o console responde 200 com o token no corpo (medido no servidor real). Com o token, a página chama `POST /api/capture` na mesma origem e injeta inspeções. Hoje elas param no `InMemorySink`. A partir da SPEC-009, subiriam para a nuvem como `source=live` e contaminariam o SPC. As fotos não vazam (nenhuma rota as serve). A proteção dos navegadores contra acesso à rede local varia com o navegador e a versão, por isso não conta como mitigação.

**Por que uma SPEC própria, e não uma emenda da SPEC-008.** A SPEC-008 não tem a tag `security` e trata de inferência. Além disso, a SPEC-009 não depende da SPEC-008, então o prazo "antes do merge da SPEC-009" só fica garantido se a SPEC-009 depender desta (o que foi feito no cabeçalho dela). Os demais itens tocam os mesmos arquivos (`app.py`, `config.py`, `cli.py`, `edge/README.md`) e cabem numa entrega curta.

## 2. Objetivo

O console só responde a um `Host` de loopback, a espera por um slot não trava o console nem o `/api/status`, as fotos de inspeção ficam legíveis só pelo dono, a CLI recusa argumentos desconhecidos e o `edge/README.md` ensina a abrir a porta só para a sub-rede da dupla.

## 3. Escopo

### 3.1 Dentro

- `edge/src/qc_edge/security.py`: função `is_allowed_console_host` (§4.1).
- `edge/src/qc_edge/app.py`: checagem do `Host` no console (§4.1); limitador assíncrono no `POST /api/capture` (§4.2); permissões de `captures/` (§4.4).
- `edge/src/qc_edge/config.py`: `EDGE_HOST` só IPv4 (§4.3); `EDGE_DATA_DIR` criado com `0700` (§4.4).
- `edge/src/qc_edge/cli.py`: argumentos desconhecidos → código 2 (§4.5).
- `edge/README.md` e `.env.example` (§4.6).
- Testes do autor em `edge/tests/` (fora de `acceptance/`). O autor pode ajustar os próprios testes que dependiam do `Host` padrão do cliente de teste, de `EDGE_HOST` IPv6 ou do `parse_known_args`.
- **Tester desta SPEC:**
  - `edge/tests/acceptance/test_spec_025.py` (testes novos);
  - os ajustes de manutenção listados na §4.7, e nada além deles, em `edge/tests/acceptance/test_spec_007.py`, `tests/acceptance/test_spec_022.py` e `packages/contracts/tests/acceptance/test_spec_023.py`.

### 3.2 Fora

- Checar o `Host` nas rotas com token (`/capture`, `/api/capture`, `/api/status`): não adotado (§7).
- Baixar `CAPTURE_MAX_BYTES`/`CAPTURE_MAX_REQUEST_BYTES`: decisão futura, depois do passo 6 do CA-20 da SPEC-007 (`docs/plan.md` §3). Limite de marcadores no `qc-preprocess`: SPEC própria do pacote, se for preciso.
- Filtrar as bridges do Docker em `detect_lan_ips`: não agora; só o aviso no README (§4.6).
- Permissões de `DATASET_DIR` e dos arquivos do modo coleta → SPEC-010. Retenção das fotos de inspeção → `docs/dataset-protocol.md` §9 (já escrita).
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

- O handler de `POST /api/capture` passa a ser `async def`. A ordem da SPEC-007 §4.5 não muda: token (401) → tamanho (413) → campos (422) → `mode=collect` (501, até a SPEC-010) → limitador (503 `server busy`) → imagem (415) → modelo (503) → resto.
- `create_app` cria **um** `anyio.Semaphore(max_concurrent_decodes, max_value=max_concurrent_decodes)` por app (fora de um event loop, o anyio 4.15 devolve um adaptador que se liga ao loop no primeiro uso). O `threading.BoundedSemaphore` sai.
- A espera pelo slot acontece no event loop, com prazo de `decode_wait_s` (por exemplo, `anyio.move_on_after`). Sem slot no prazo → 503 `{"detail": "server busy"}`, como antes: nada é salvo, o inferenciador não é chamado e o sink não recebe nada.
- Com o slot, os passos 3 a 7 da SPEC-007 §4.5 (`load_capture_image`, inferência, gravação da foto e `sink.put`) rodam numa **única** chamada `await anyio.to_thread.run_sync(...)`, e o slot é liberado num `finally` **depois** que essa chamada retorna, inclusive em erro. Nenhuma dessas operações bloqueantes roda no event loop.
- Se o cliente desconectar durante a chamada, o slot só é liberado quando a thread termina. É o padrão do `anyio.to_thread.run_sync` (`abandon_on_cancel=False`), que não deve ser alterado. Assim, o semáforo continua limitando as decodificações reais.
- Os parâmetros `max_concurrent_decodes` e `decode_wait_s`, os padrões (2 e 10 s), o `ValueError` fora da faixa e a regra "toda chamada a `load_capture_image` em `qc_edge` acontece com o slot" não mudam. O limitador é **um só** para os modos `inspect` e `collect`. Se a SPEC-010 já estiver `Done` quando esta for implementada, a mudança vale também para o modo coleta.

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

O tester desta SPEC faz só estas edições fora do `test_spec_025.py`. Se qualquer outro teste existente precisar mudar para a suíte passar, ele registra `SPEC_ISSUE` e para.

1. **`edge/tests/acceptance/test_spec_007.py`** (efeito colateral das §4.1 e §4.5; nenhum CA da SPEC-007 muda):
   - as requisições ao console (`GET /`) passam a usar a URL base `http://127.0.0.1:<EDGE_PORT>` (ou o header `Host: 127.0.0.1:<EDGE_PORT>`), no lugar de `http://testserver`;
   - as chamadas a `qc_edge.cli.main()` dentro do processo do pytest passam a ser `main([])`, ou a usar `monkeypatch.setattr(sys, "argv", ["qc-edge"])`, para não herdar os argumentos do pytest;
   - um teste que hoje espere `EDGE_HOST` IPv6 aceito passa a esperar código 2.
2. **`tests/acceptance/test_spec_022.py`** (RV-02 da SPEC-004): na docstring do módulo, o trecho `(CA-01 to CA-16).` vira `(CA-01 to CA-14 and CA-16; CA-15 is checked by CI and by the test report, docs/architecture.md section 10).`
3. **`packages/contracts/tests/acceptance/test_spec_023.py`** (RV-02 da SPEC-004): na docstring do módulo, o trecho `CA-03 to CA-06\nand CA-13.` vira `CA-03 to CA-06\n(CA-13 is checked by CI and by the test report, docs/architecture.md section 10).`

Nos itens 2 e 3, só a docstring muda, e a contagem de testes coletados de cada arquivo continua a da `main`.

## 5. Critérios de aceite

Contexto comum: `EdgeSettings` com `EDGE_PORT=8000` e `EDGE_DATA_DIR` em `tmp_path`; `StubInferencer` (SPEC-007) e `InMemorySink`; o token de sessão gerado nos testes (nunca literal). "Console de loopback" = `httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))`.

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
- **CA-08 (SEC-03)** — *Dado* um espião em `qc_edge.limits.load_capture_image` (que chama o original) que registra se há event loop rodando na thread, *quando* uma captura válida e uma com GIF (415) são enviadas, *então* o espião é chamado 2 vezes, nas duas sem event loop rodando na thread; e, *dado* `max_concurrent_decodes=1` e um inferenciador que lança `InferenceError` na 1ª chamada, *quando* 3 capturas são enviadas em sequência, *então* as respostas são 500, 200 e 200 (o slot é liberado depois do erro).
- **CA-09 (security, SEC-06, R-14)** — *Dado* `os.umask(0o022)` (e, numa segunda execução, `os.umask(0o077)`), com o umask original restaurado no fim, e `EDGE_DATA_DIR` inexistente, *quando* a config é carregada, o app sobe e são aceitas uma captura JPEG e uma PNG, *então* `stat.S_IMODE` dá `0o700` para `EDGE_DATA_DIR`, `captures/` e `captures/<dia>/`, e `0o600` para os 2 arquivos `.jpg`. *Dado* `EDGE_DATA_DIR` já existente com `0o755` e `captures/` já existente com `0o755`, *quando* o app sobe (`with TestClient(app)`), *então* `captures/` fica com `0o700` e `EDGE_DATA_DIR` continua `0o755`.
- **CA-10 (RV-05)** — *Dado* `uvicorn.run` substituído por um espião, *quando* `main(["--stub-modle"])`, `main(["--token=<marcador>"])` (marcador gerado no teste) e `main(["<marcador-posicional>"])` são chamados, *então* cada um sai com código 2, o espião não é chamado, a saída de log do 1º contém `--stub-modle`, e nem o log (`caplog`) nem o stdout/stderr (`capsys`) contêm algum dos marcadores; e `main([])` e `main(["--stub-model"])` chamam o espião 1 vez cada.
- **CA-11 (SEC-04, SEC-05, SEC-07, RV-04)** — *Dado* o texto de `edge/README.md`, *então*:
  - toda linha **dentro de um bloco de código** (entre cercas ```` ``` ````) que contém `ufw allow`, `firewall-cmd` com `--add-` ou `nft add rule`/`nft insert rule` contém também `from <sub-rede>`, `source address=` ou `saddr` (no README, `<sub-rede>` pode ser o marcador literal ou um exemplo como `192.168.43.0/24`; o teste procura a palavra `from` seguida de espaço);
  - nenhuma linha dentro de bloco de código contém `--permanent`, e o texto contém `ip -4 route show scope link`;
  - há uma seção cujo título é `## Segurança na operação`, e o trecho dela até o próximo título de nível 2 contém `EDGE_SESSION_TOKEN`, `WPA2` e `172.17.`;
  - a linha da tabela de variáveis que começa com `` | `EDGE_HOST` `` contém `IPv4` e não contém `ou IPv6`.

  *Dado* `.env.example`, *então* a linha de comentário imediatamente acima de `EDGE_HOST=` contém `IPv4`.
- **CA-12 (manutenção, RV-02 da SPEC-004)** — *Dado* `ast.get_docstring` dos módulos `tests/acceptance/test_spec_022.py` e `packages/contracts/tests/acceptance/test_spec_023.py`, *então* a primeira não contém `CA-01 to CA-16` e contém `CA-15 is checked by CI`, e a segunda não contém `and CA-13` e contém `CA-13 is checked by CI`; e `uv run pytest --collect-only -q <arquivo>`, com cada caminho explícito, coleta nos dois arquivos o mesmo número de testes da `main`.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | `is_allowed_console_host` (tabela de casos), console com `Host`, limitador assíncrono, validação de `EDGE_HOST`, modos de arquivo, CLI | `edge/tests/` |
| Aceite (tester) | Um por CA; mais as edições de manutenção da §4.7 | `edge/tests/acceptance/test_spec_025.py` e os 3 arquivos da §4.7 |

- Sem rede externa. O servidor do CA-04 escuta só em `127.0.0.1`, como o CA-19 da SPEC-007.
- Mock só de fronteiras: socket (`detect_lan_ips`), `uvicorn.run` e o inferenciador.
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

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `edge/README.md` e `.env.example` atualizados
- [ ] PR aberto com os relatórios; merge humano **antes** do merge da SPEC-009

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-13 | SPEC criada (Draft). | SEC-01, SEC-03, SEC-04, SEC-05, SEC-06 (parte de `captures/`) e SEC-07 de `reviews/SPEC-007/r1-security-report.md`; RV-04 e RV-05 de `reviews/SPEC-007/r1-review-report.md`; RV-02 de `reviews/SPEC-004/r2-review-report.md` | Orquestrador, a pedido do humano |
