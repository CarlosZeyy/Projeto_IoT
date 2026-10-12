# SPEC-007: Gateway de borda, página de captura e pareamento

| Campo | Valor |
|---|---|
| Status | Ready |
| Rodada atual | — |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-002, SPEC-023 (`qc-preprocess` 0.2.0) |
| Semana alvo | S2 |
| Requisitos cobertos | RF-01, RF-02, RNF-03, RNF-05, RNF-06, RNF-08 |
| ADRs relevantes | ADR-002, ADR-003, ADR-009, ADR-010, ADR-012 |

## 1. Contexto

Implementa a base do `qc-edge` descrita em `docs/architecture.md` §6.1, §6.2 (passos 1, 5, 6 e 7), §6.4, §8 e §9: configuração, console do operador com QR de pareamento, página `/capture` do celular e a rota `POST /api/capture` no modo `inspect`. A inferência real (SPEC-008), o outbox (SPEC-009) e o modo coleta (SPEC-010) entram por **interfaces injetadas** definidas aqui.

## 2. Objetivo

`uv run --package qc-edge qc-edge` sobe o gateway na LAN; o celular lê o QR, fotografa e recebe o resultado (com o inferenciador stub), e a inspeção é entregue ao `InspectionSink` antes da resposta.

## 3. Escopo

### 3.1 Dentro

- `edge/src/qc_edge/config.py`: `EdgeSettings` (pydantic-settings) com as variáveis do §6.4.
- `edge/src/qc_edge/inference.py`: `ModelInfo`, `InferenceResult`, `InferenceError`, Protocol `Inferencer`, `StubInferencer`.
- `edge/src/qc_edge/sink.py`: `SinkStats`, `SinkError`, Protocol `InspectionSink`, `InMemorySink`, Protocol `BackgroundService`.
- `edge/src/qc_edge/netinfo.py` (`detect_lan_ips`), `security.py` (token), `app.py` (`create_app`), `cli.py` (`main`, console script `qc-edge`).
- `edge/src/qc_edge/templates/console.html` e `capture.html`; `edge/src/qc_edge/static/capture.js` (e `capture.css`, opcional).
- `edge/README.md`: como rodar, variáveis, firewall no Arch (ufw, firewalld, nftables) e plano B (hotspot).
- `.env.example` (variáveis da borda) e `.gitignore` (`edge/data/`).

### 3.2 Fora

- `OnnxInferencer` e `decide()` → SPEC-008. `SqliteOutbox`, publisher e laço de envio → SPEC-009.
- Campos e rota do modo `collect` → SPEC-010 (aqui o seletor de modo existe, com "coleta" desabilitado).
- HTTPS e vídeo ao vivo → SPEC-019. MQTT → SPEC-020.

## 4. Requisitos detalhados

### 4.1 Configuração (`EdgeSettings`)

| Variável | Padrão | Validação (erro → `qc-edge` sai com código 2 e mensagem com o nome da variável) |
|---|---|---|
| `EDGE_HOST` | `0.0.0.0` | IP literal |
| `EDGE_PORT` | `8000` | 1–65535 |
| `EDGE_SESSION_TOKEN` | gerado | se definido, ≥ 32 caracteres |
| `DEVICE_ID` | `edge-01` | `qc_contracts.DEVICE_ID_PATTERN` (`^[a-z0-9-]{3,32}$`), com `re.fullmatch` ou com o `pattern` do Pydantic; nunca `re.match`/`re.search` (`architecture.md` §3.2) |
| `EDGE_DATA_DIR` | `edge/data` | criado se não existir |
| `DEVICE_API_KEY`, `CLOUD_API_URL`, `MODEL_DIR`, `DATASET_DIR`, `OUTBOX_PATH`, limiares | — | lidos aqui, validados nas SPECs 008/009/010 |

### 4.2 Interfaces (assinaturas exatas)

```python
@dataclass(frozen=True)
class ModelInfo: model_version: str; model_sha256: str
@dataclass(frozen=True)
class InferenceResult:
    object_type: ObjectType; grade: Grade | None; grade_score: float | None
    type_confidence: float; grade_confidence: float | None; needs_review: bool; latency_ms: int
class InferenceError(Exception): ...
class Inferencer(Protocol):
    @property
    def model_info(self) -> ModelInfo: ...
    def infer(self, image: PIL.Image.Image) -> InferenceResult: ...   # imagem já validada por load_image
class StubInferencer:  # result configurável no construtor; model_info = ModelInfo("stub-v0", "0"*64); conta chamadas
    def __init__(self, result: InferenceResult | None = None) -> None: ...

@dataclass(frozen=True)
class SinkStats:
    pending: int; dead: int; last_success_at: datetime | None
    connectivity: Literal["online", "offline", "auth_error", "disabled"]
class SinkError(Exception): ...
class InspectionSink(Protocol):
    def put(self, inspection: InspectionCreate) -> None: ...   # idempotente por inspection_id; durável ao retornar
    def stats(self) -> SinkStats: ...
class InMemorySink:  # guarda em lista; stats(): pending=len, dead=0, last_success_at=None, connectivity="disabled"
class BackgroundService(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...

def create_app(settings: EdgeSettings, inferencer: Inferencer | None, sink: InspectionSink, *,
               background: Sequence[BackgroundService] = (), clock: Callable[[], datetime] = utc_now) -> FastAPI
```

O `lifespan` chama `start()` de cada `BackgroundService` na subida e `stop()` em ordem inversa no desligamento. SPECs seguintes podem acrescentar parâmetros só por palavra-chave, com padrão.

### 4.3 CLI `qc-edge` e rede

- `main()`: carrega `EdgeSettings`, monta `inferencer` e `sink`, registra no log a URL do console (`http://127.0.0.1:<porta>/`) e roda `uvicorn` em `EDGE_HOST:EDGE_PORT` com `proxy_headers=False`. Nesta SPEC: `inferencer=None`, `sink=InMemorySink()`; a flag `--stub-model` usa `StubInferencer` e, com ela, **nada é publicado na nuvem** (regra que a SPEC-009 deve manter, por R-06: resultado falso não pode subir como `live`).
- Token: `EDGE_SESSION_TOKEN` ou `secrets.token_urlsafe(32)` na subida; comparação com `secrets.compare_digest`. O token **nunca** aparece em log.
- `detect_lan_ips() -> list[str]`: (1) socket UDP `connect` para um endereço privado não roteável (ex.: `10.254.254.254:1`, nenhum pacote é enviado) e `getsockname()`; (2) fallback: IPv4 de `socket.getaddrinfo(socket.gethostname(), None, AF_INET)`. Remove duplicados, `127.0.0.0/8` e `169.254.0.0/16`; lista vazia → `["127.0.0.1"]` e aviso no console. Recalculado a cada render do console (troca para o hotspot).

### 4.4 Rotas

| Rota | Acesso | Resposta |
|---|---|---|
| `GET /` | só loopback | HTML do console |
| `GET /capture?t=<token>` | token na query | `capture.html`; token ausente/errado → 401 com HTML "Sessão inválida. Leia o QR code no console." |
| `GET /static/capture.js` (e `.css`) | livre | arquivos estáticos (sem segredo) |
| `POST /api/capture` | `X-Session-Token` | ver §4.5 |
| `GET /api/status` | `X-Session-Token` | `{"device_id", "contract_version", "model": {"loaded", "model_version", "model_sha256"}, "sink": {"pending", "dead", "last_success_at", "connectivity"}}` |

**Console (`GET /`)**: aceito só se `request.client.host` ∈ {`127.0.0.1`, `::1`} **e** sem os headers `X-Forwarded-For`, `Forwarded` ou `CF-Connecting-IP` (defesa em profundidade contra proxy/túnel, proibidos por `architecture.md` §8; ver também §9); senão 403. Renderizado no servidor, `<meta http-equiv="refresh" content="5">`, sem JS. Mostra: QR em SVG inline (`qrcode` com `qrcode.image.svg.SvgPathImage`) para `http://<ip>:<porta>/capture?t=<token>` usando o primeiro IP detectado; a URL em texto; os outros IPs como links `/?ip=<ip>` (o parâmetro só é aceito se estiver na lista detectada); modelo (carregado ou não, versão); `pending`, `dead`, conectividade e `last_success_at` do sink; as últimas 10 inspeções da sessão (memória, `deque(maxlen=10)`, mais recente primeiro) com hora, lote, tipo e grau em PT-BR.

**Página `/capture`**: HTML + JS puro, sem framework, sem build, sem recurso externo (CDN), `capture.js` ≤ 200 linhas. Campos: `lot_id` (persistido em `localStorage`), seletor de modo inspeção/coleta (coleta desabilitado até a SPEC-010), botão grande "Fotografar" = `<input type="file" accept="image/*" capture="environment">`. O JS redimensiona para no máximo 1280 px no lado maior (sem ampliar), com `createImageBitmap(file, {imageOrientation: "from-image"})` quando disponível (fallback `<img>`), e reencoda em JPEG q=0,9 via canvas. Envia `multipart/form-data` com o token lido de `?t=` no header `X-Session-Token`; desabilita o botão durante o envio. Cartão de resultado com os rótulos de `labels_pt`, cor por veredito (aprovada verde, reprovada vermelho, desconhecido cinza, `needs_review` com borda amarela e "Revisar"), latência da borda (`latency_ms`) e tempo total medido no celular. Mensagens PT-BR para 401, 413, 415, 422, 503 e falha de rede.

### 4.5 `POST /api/capture` (modo `inspect`)

Campos: `image` (arquivo), `lot_id`, `mode`. Handler síncrono (`def`, roda no threadpool). Ordem: token (401) → tamanho (413) → campos (422) → imagem (415) → modelo (503).

1. `image` > 10 MiB (10 485 760 bytes) → 413; um middleware também rejeita `Content-Length` > 10,5 MiB com 413 antes de ler o corpo.
2. `lot_id` fora de `qc_contracts.LOT_ID_PATTERN` (`^[A-Za-z0-9_-]{1,40}$`, validado com `re.fullmatch` ou com o `pattern` do Pydantic, nunca com `re.match`/`re.search`), `mode` fora de `inspect|collect`, ou campo ausente → 422.
3. Conteúdo: `qc_preprocess.load_image(bytes)` (SPEC-002 e SPEC-023: só JPEG/PNG pelo conteúdo, até 40 M pixels, proporção de no máximo 10:1, EXIF) — `InvalidImageError` → 415. O nome e o content-type enviados pelo cliente são ignorados. O `RuntimeError` que o `load_image` levanta quando `PIL.ImageFile.LOAD_TRUNCATED_IMAGES` está ligada **não** é tratado como 415: é erro de configuração do servidor e resulta em 500, sem stack trace. Nenhum módulo de `qc_edge` liga essa flag.
4. `inferencer is None` → 503 `{"detail": "model not loaded"}`.
5. Gera `inspection_id = uuid4()` e `inspected_at = clock()` (UTC); `inferencer.infer(img)`; `InferenceError` → 500 `{"detail": "inference failed"}`, nada gravado.
6. Salva em `EDGE_DATA_DIR/captures/<AAAA-MM-DD de inspected_at>/<inspection_id>.jpg` (JPEG: bytes como recebidos; PNG: reencodado JPEG q=90). Nome sempre gerado pelo servidor.
7. Monta `qc_contracts.InspectionCreate` (`source=live`, `device_id` e `ModelInfo` da config/inferenciador) e chama `sink.put` **antes** de responder; `SinkError` → 503 `{"detail": "failed to persist inspection"}` e a foto é apagada.
8. 200: `{"inspection": <InspectionCreate em JSON>, "labels_pt": {"object_type", "grade", "verdict"}, "approved": bool | null}`. `approved = None` se `grade is None`, senão `not is_defective(grade)`; `verdict` ∈ "aprovada", "reprovada", "desconhecido". Rótulos vêm de `qc_contracts.labels`.

`mode=collect` nesta SPEC responde 501; o comportamento final é da SPEC-010 (não há CA para isso aqui).

## 5. Critérios de aceite

- **CA-01** — *Dado* `EDGE_PORT=70000` (ou `DEVICE_ID=Edge_01`, ou `DEVICE_ID` igual a `"edge-01\n"`, com quebra de linha final, ou `EDGE_SESSION_TOKEN` com 10 caracteres), *quando* `main()` é chamado, *então* sai com código 2 e a mensagem cita a variável inválida.
- **CA-02** — *Dado* `EDGE_SESSION_TOKEN` ausente, *quando* o app é criado duas vezes, *então* cada token tem ≥ 43 caracteres URL-safe e os dois são diferentes; *dado* `EDGE_SESSION_TOKEN` com 40 caracteres, *então* é ele o aceito em `X-Session-Token`.
- **CA-03** — *Dado* `StubInferencer` retornando `screw`/`good`, *quando* envio JPEG válido com `lot_id=L-001`, `mode=inspect` e token válido, *então* recebo 200; `inspection` tem os 14 campos do contrato, `source="live"`, `device_id` da config, `inspection_id` UUID v4, `inspected_at` com fuso UTC; `approved=true`; `labels_pt={"object_type":"parafuso","grade":"bom","verdict":"aprovada"}`; existe `captures/<data>/<inspection_id>.jpg`; o sink contém exatamente 1 item igual a `inspection`.
- **CA-04** — *Dado* o stub retornando `nut`/`poor`, *então* `approved=false` e `verdict="reprovada"`; *dado* o stub retornando `unknown` (grau nulo), *então* `approved=null`, `labels_pt.grade=null` e `verdict="desconhecido"`.
- **CA-05** — *Dado* um sink cujo `put` lança `SinkError`, *quando* envio uma foto válida, *então* recebo 503, nenhum arquivo fica em `captures/` e o sink está vazio.
- **CA-06** — *Dado* requisição sem `X-Session-Token` ou com token errado, *quando* chamo `POST /api/capture` ou `GET /api/status`, *então* recebo 401, `StubInferencer` tem 0 chamadas e nenhum arquivo é criado.
- **CA-07** — *Dado* token válido, *quando* envio `image` com 10 485 761 bytes, *então* recebo 413 e nada é salvo.
- **CA-08** — *Dado* token válido, *quando* envio um arquivo de texto chamado `foto.jpg`, um GIF válido, um JPEG truncado ou um PNG válido de 100×1001 px (proporção acima de 10:1, SPEC-023), *então* recebo 415 com `{"detail": ...}`, `StubInferencer` tem 0 chamadas e nada é salvo.
- **CA-09** — *Dado* token válido, *quando* `lot_id` é `"lote 1"`, `"../x"`, `"L-001\n"` (quebra de linha final) ou 41 caracteres, ou `mode="foo"`, ou falta `image`, *então* recebo 422 e nada é salvo.
- **CA-10** — *Dado* `inferencer=None`, *quando* envio foto válida em `mode=inspect`, *então* recebo 503 `{"detail": "model not loaded"}`.
- **CA-11** — *Dado* um inferenciador que lança `InferenceError`, *quando* envio foto válida, *então* recebo 500 `{"detail": "inference failed"}`, sem stack trace, sem arquivo salvo e sem item no sink.
- **CA-12** — *Dado* upload com nome de arquivo `../../evil.jpg`, *quando* a captura é aceita, *então* o único arquivo novo sob a raiz temporária é `EDGE_DATA_DIR/captures/<data>/<inspection_id>.jpg`.
- **CA-13** — *Dado* 12 capturas feitas, *quando* `GET /` vem de `127.0.0.1` (via `httpx.ASGITransport(client=("127.0.0.1", 50000))`), *então* recebo 200 com um `<svg` do QR, a URL `http://<ip>:8000/capture?t=<token>`, o estado do modelo, o `pending` do sink e exatamente 10 linhas de inspeção, a mais recente primeiro.
- **CA-14** — *Dado* `GET /` vindo de `192.168.1.50`, ou de `127.0.0.1` com header `X-Forwarded-For` ou `CF-Connecting-IP`, *então* recebo 403 e o token não aparece no corpo.
- **CA-15** — *Dado* `GET /capture?t=<válido>`, *então* recebo 200 com `<input type="file" accept="image/*" capture="environment">`, campo de lote e opção de coleta desabilitada; com `t` errado ou ausente, 401; `capture.js` tem ≤ 200 linhas e nenhum dos arquivos da página referencia `http://` ou `https://` externos.
- **CA-16** — *Dado* token válido, *quando* chamo `GET /api/status`, *então* o JSON tem exatamente as chaves de primeiro nível de §4.4 e, dentro de `model` e `sink`, ao menos as chaves listadas (SPECs seguintes podem acrescentar), com `sink.connectivity="disabled"` para `InMemorySink`.
- **CA-17 (R-02)** — *Dado* uma captura feita, *então* `GET /captures/<data>/<id>.jpg` e `GET /data/captures/<data>/<id>.jpg` retornam 404; o objeto entregue ao sink é um `InspectionCreate` cujas chaves de `model_dump()` são exatamente os campos de `architecture.md` §3.2; e nenhum módulo de `qc_edge` importa `httpx`, `requests` ou `urllib.request`, exceto `qc_edge.publisher` (criado na SPEC-009) — verificação estática.
- **CA-18** — *Dado* o socket UDP simulado retornando `192.168.0.42`, *então* `detect_lan_ips()[0] == "192.168.0.42"`; *dado* que o socket falha e `getaddrinfo` devolve `127.0.1.1`, `169.254.3.3` e `10.0.0.7`, *então* o resultado é `["10.0.0.7"]`; *dado* nenhum candidato, *então* `["127.0.0.1"]` e o console mostra o aviso.
- **CA-19 (R-03)** — *Dado* captura de logs desde a subida até 3 capturas (sucesso, 401 e 415), *então* o valor do token e o `DEVICE_API_KEY` configurado não aparecem em nenhuma linha.
- **CA-20 (manual)** — Topologia preferida: 1. ligar `qc-edge` com `--stub-model` e liberar a porta conforme `edge/README.md`; 2. no celular A (Android, Chrome) e depois no celular B (o outro celular da dupla, navegador padrão), ler o QR do console na mesma Wi-Fi; 3. tocar "Fotografar": abre a câmera **traseira** (direto ou após escolher "Câmera" no seletor do Android, ADR-003; registrar qual); 4. fotografar 10 peças; 5. conferir em cada uma o cartão de resultado em menos de 3 s (tempo total exibido) e 10 linhas novas no console.
- **CA-21 (manual)** — Plano B: 1. ligar o hotspot do celular A e conectar o notebook a ele; 2. recarregar o console e usar o QR do novo IP; 3. repetir os passos 3–5 do CA-20 com 3 fotos em cada celular.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | config, token, `detect_lan_ips`, rotas com `StubInferencer`/`InMemorySink` | `edge/tests/` |
| Aceite (tester) | Um por CA automatizável (`httpx.ASGITransport` com `client=` para simular a origem; `tmp_path` como `EDGE_DATA_DIR`; socket simulado com `monkeypatch`) | `edge/tests/acceptance/test_spec_007.py` |
| Manual (dupla) | CA-20 e CA-21, resultado no test-report | celulares reais |

Sem rede real nos testes. Mock só de fronteiras: socket, relógio e o inferenciador (stub).

## 7. Riscos e notas para o implementador

- O `uvicorn` aplica `X-Forwarded-For` de `127.0.0.1` por padrão; por isso `proxy_headers=False` e a checagem de headers no console.
- `<input capture>` funciona em HTTP (não exige contexto seguro), diferente de `getUserMedia` (SPEC-019).
- `pydantic-settings` e `qrcode` entram como dependências do `qc-edge`; nada de torch (R-12).
- `edge/README.md` deve trazer: detectar o firewall ativo (`systemctl is-active ufw firewalld nftables`); `sudo ufw allow 8000/tcp`; `sudo firewall-cmd --add-port=8000/tcp` (e `--permanent` opcional); regra `nft add rule inet filter input tcp dport 8000 accept` (ajustar tabela e chain); como desfazer cada uma; e o passo a passo do plano B (`nmcli dev wifi connect <SSID>`).

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS), CA-20/21 registrados
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `edge/README.md`, `.env.example` e `.gitignore` atualizados
- [ ] PR aberto com os relatórios; merge humano

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-12 | Mudanças: (a) dependência da SPEC-023 (`qc-preprocess` 0.2.0); (b) §4.1 e §4.5, passo 2: `DEVICE_ID` e `lot_id` validados com as constantes de `qc_contracts` e `re.fullmatch` (ou `pattern` do Pydantic); (c) §4.5, passo 3: proporção máxima de 10:1 (415) e `RuntimeError` da flag `LOAD_TRUNCATED_IMAGES` → 500, com nenhum módulo da borda ligando a flag; (d) o CA-01 ganhou `DEVICE_ID="edge-01\n"`; (e) o CA-08 ganhou o PNG 100×1001 e as verificações "0 chamadas ao stub" e "nada salvo", que já decorriam da ordem do §4.5; (f) o CA-09 ganhou `lot_id="L-001\n"`. SPEC marcada como "Aguardando reaprovação humana". | SPEC_ISSUE-01 (RV-02), RV-04 e RV-06 de `reviews/SPEC-002/r1-review-report.md` | Orquestrador, a pedido do humano |
| 2026-10-12 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
