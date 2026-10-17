# SPEC-007: Gateway de borda, página de captura e pareamento

| Campo | Valor |
|---|---|
| Status | Done |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-002, SPEC-023, SPEC-024 (`qc-preprocess` 0.3.0) |
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
- `edge/src/qc_edge/limits.py`: limites próprios da rota de captura e `load_capture_image` (§4.7).
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
               background: Sequence[BackgroundService] = (), clock: Callable[[], datetime] = utc_now,
               max_concurrent_decodes: int = 2, decode_wait_s: float = 10.0) -> FastAPI
```

O `lifespan` chama `start()` de cada `BackgroundService` na subida e `stop()` em ordem inversa no desligamento. SPECs seguintes podem acrescentar parâmetros só por palavra-chave, com padrão.

- `max_concurrent_decodes` (inteiro ≥ 1) e `decode_wait_s` (> 0) configuram o limitador de decodificações (§4.6). Fora da faixa → `ValueError` em `create_app`. Não há variável de ambiente para eles: a CLI usa os padrões.
- **Checagem da flag na subida (SEC-04):** a primeira coisa que o `lifespan` faz, antes de iniciar os `BackgroundService`, é verificar `PIL.ImageFile.LOAD_TRUNCATED_IMAGES`. Se for verdadeira, levanta `RuntimeError` com uma mensagem que contém `LOAD_TRUNCATED_IMAGES`, e o app não sobe.

### 4.3 CLI `qc-edge` e rede

- `main()`: carrega `EdgeSettings`, monta `inferencer` e `sink`, verifica a flag (abaixo), registra no log a URL do console (`http://127.0.0.1:<porta>/`) e roda `uvicorn` em `EDGE_HOST:EDGE_PORT` com `proxy_headers=False`.
- **Flag na CLI (SEC-04):** depois de montar `inferencer` e `sink` (quando todos os módulos da borda, inclusive o `onnxruntime` da SPEC-008, já foram importados) e **antes** de chamar `uvicorn`, se `PIL.ImageFile.LOAD_TRUNCATED_IMAGES` for verdadeira, `main()` registra um erro que contém `LOAD_TRUNCATED_IMAGES` e sai com código 1, sem chamar o `uvicorn`. Nenhum módulo de `qc_edge` altera a flag. Nesta SPEC: `inferencer=None`, `sink=InMemorySink()`; a flag `--stub-model` usa `StubInferencer` e, com ela, **nada é publicado na nuvem** (regra que a SPEC-009 deve manter, por R-06: resultado falso não pode subir como `live`).
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

**Página `/capture`**: HTML + JS puro, sem framework, sem build, sem recurso externo (CDN), `capture.js` ≤ 200 linhas. Campos: `lot_id` (persistido em `localStorage`), seletor de modo inspeção/coleta (coleta desabilitado até a SPEC-010), botão grande "Fotografar" = `<input type="file" accept="image/*" capture="environment">`. O JS redimensiona para no máximo 1280 px no lado maior (sem ampliar), com `createImageBitmap(file, {imageOrientation: "from-image"})` quando disponível (fallback `<img>`), e reencoda em JPEG q=0,9 via canvas. Envia **sempre** a imagem reencodada: se a reencodagem falhar (ex.: `canvas.toBlob` devolve `null`), mostra "Não foi possível preparar a foto. Tente de novo." e não envia o arquivo original, que passaria dos limites da rota (§4.7). Envia `multipart/form-data` com o token lido de `?t=` no header `X-Session-Token`; desabilita o botão durante o envio. Cartão de resultado com os rótulos de `labels_pt`, cor por veredito (aprovada verde, reprovada vermelho, desconhecido cinza, `needs_review` com borda amarela e "Revisar"), latência da borda (`latency_ms`) e tempo total medido no celular. Mensagens PT-BR para 401, 413, 415, 422, 503 e falha de rede.

### 4.5 `POST /api/capture` (modo `inspect`)

Campos: `image` (arquivo), `lot_id`, `mode`. Handler síncrono (`def`, roda no threadpool). Ordem: token (401) → tamanho (413) → campos (422) → limitador (503 `server busy`, §4.6) → imagem (415) → modelo (503).

1. `image` > `CAPTURE_MAX_BYTES` (3 MiB, 3 145 728 bytes, §4.7) → 413; um middleware também rejeita `Content-Length` > `CAPTURE_MAX_REQUEST_BYTES` (3,5 MiB, 3 670 016 bytes) com 413 antes de ler o corpo.
2. `lot_id` fora de `qc_contracts.LOT_ID_PATTERN` (`^[A-Za-z0-9_-]{1,40}$`, validado com `re.fullmatch` ou com o `pattern` do Pydantic, nunca com `re.match`/`re.search`), `mode` fora de `inspect|collect`, ou campo ausente → 422.
3. Conteúdo: `qc_edge.limits.load_capture_image(bytes)` (§4.7: até 4 M pixels, checados pelo cabeçalho antes de decodificar; depois, `qc_preprocess.load_image`, com as regras das SPECs 002, 023 e 024: só JPEG/PNG pelo conteúdo, até 40 M pixels, proporção de no máximo 10:1, JPEG com no máximo 64 marcadores de scan, EXIF), chamado **dentro** do limitador de §4.6 — `InvalidImageError` → 415. O nome e o content-type enviados pelo cliente são ignorados. O `RuntimeError` que o `load_capture_image` (ou o `load_image`) levanta quando `PIL.ImageFile.LOAD_TRUNCATED_IMAGES` está ligada **não** é tratado como 415: é erro de configuração do servidor e resulta em 500, sem stack trace. Nenhum módulo de `qc_edge` liga essa flag.
4. `inferencer is None` → 503 `{"detail": "model not loaded"}`.
5. Gera `inspection_id = uuid4()` e `inspected_at = clock()` (UTC); `inferencer.infer(img)`; `InferenceError` → 500 `{"detail": "inference failed"}`, nada gravado.
6. Salva em `EDGE_DATA_DIR/captures/<AAAA-MM-DD de inspected_at>/<inspection_id>.jpg` (JPEG: bytes como recebidos; PNG: reencodado JPEG q=90). Nome sempre gerado pelo servidor.
7. Monta `qc_contracts.InspectionCreate` (`source=live`, `device_id` e `ModelInfo` da config/inferenciador) e chama `sink.put` **antes** de responder; `SinkError` → 503 `{"detail": "failed to persist inspection"}` e a foto é apagada.
8. 200: `{"inspection": <InspectionCreate em JSON>, "labels_pt": {"object_type", "grade", "verdict"}, "approved": bool | null}`. `approved = None` se `grade is None`, senão `not is_defective(grade)`; `verdict` ∈ "aprovada", "reprovada", "desconhecido". Rótulos vêm de `qc_contracts.labels`.

`mode=collect` nesta SPEC responde 501; o comportamento final é da SPEC-010 (não há CA para isso aqui).

### 4.6 Limitador de decodificações (SEC-02)

A maior imagem aceita pelo `load_image` custa até cerca de 300 MB durante `load_image` + `preprocess` (pico medido de 343 MB a 40 M pixels, `reviews/SPEC-023/r1-security-report.md`), e o threadpool do Starlette atende até 40 requisições ao mesmo tempo.

**Dimensionamento** (SEC-24-02 de `reviews/SPEC-024/r1-security-report.md`):

- **Só com os limites do `load_image`** (corpo de 10 MiB, 40 M pixels), o pior caso aceito por decodificação foi **medido** em cerca de **2,5 s de CPU e 360 MB**. Ele combina 64 scans repetidos (~2 s), a inundação de segmentos vazios sem nenhum scan (2,6 M segmentos APP1: 2,37 s e 362 MB) e o pico de ~300 MB da imagem de 40 M pixels. Com 2 slots, seriam ~720 MB de pico.
- **Com os limites da rota (§4.7: 3 MiB e 4 M pixels)**, o pior caso foi **medido** pelo security-devops desta SPEC (seção "Decisão sobre o RV-01" de `reviews/SPEC-007/r1-security-report.md`; notebook de 4 núcleos, Pillow 12.3.0): a inundação de 786 k segmentos APP1 vazios custa **~4 s de CPU e ~90 MB acima da base (pico de 133 MB no processo) por requisição**. O custo vem do laço de marcadores do Pillow, que roda duas vezes (~2 s na sondagem e ~2 s no `load_image`). A decodificação de pixels, cortada pelos 4 M pixels, fica abaixo de 0,2 s. A estimativa anterior (~1,4 s e ~110 MB por slot) acertou a memória e subestimou a CPU em ~2,8×. O laço segura o GIL, então os 2 slots se **serializam** e ocupam ~1 núcleo (duas inundações simultâneas levam ~8,5 s cada), com ~180 MB acima da base. Por isso, mais slots não ajudariam, e menos slots só aumentariam a fila das requisições legítimas.
- Os padrões ficam: `max_concurrent_decodes=2` e `decode_wait_s=10`.
- **Consequência aceita** (medida no servidor real, com os padrões, no mesmo relatório): quem tiver o token de sessão e estiver no hotspot da dupla consegue manter os dois slots ocupados com ~0,5 requisição por segundo por slot. Com 2 inundações em curso, a requisição legítima recebe 200 em ~6,7 s (acima dos 3 s da RNF-03 só enquanto dura o ataque); com 6 ou mais, recebe 503 `server busy` em ~10 s. Com 45 inundações simultâneas, as requisições que esperam o slot ocupam threads do threadpool (limite de 40), compartilhado com o console, o `/capture` e o `/api/status`: a captura legítima recebe 503 em ~18,7 s, e o `/api/status` leva ~2 s (SEC-03; a espera fora do threadpool é da SPEC-025). É uma degradação, e não uma queda do notebook.
- **Decisão futura (não muda esta SPEC):** depois do passo 6 do CA-20, se o maior arquivo real dos dois celulares ficar bem abaixo de 3 MiB, uma SPEC posterior pode baixar `CAPTURE_MAX_BYTES` e `CAPTURE_MAX_REQUEST_BYTES` para cerca de 2× o maior arquivo medido. O custo da inundação cai na mesma proporção (ex.: 1 MiB → ~1,3 s). Um limite de segmentos e marcadores no `qc-preprocess` também é possível, mas exige SPEC própria do pacote, porque o §7 proíbe interpretar segmentos à mão na borda. A decisão fica registrada em `docs/plan.md` §3.

**Mecanismo:**

- `create_app` cria **um** `threading.BoundedSemaphore(max_concurrent_decodes)` por app.
- No `POST /api/capture`, depois da validação dos campos (422) e antes do passo 3, o handler chama `acquire(timeout=decode_wait_s)`:
  - não conseguiu → 503 `{"detail": "server busy"}`; nada é salvo, o inferenciador não é chamado e o sink não recebe nada;
  - conseguiu → executa os passos 3 a 7 (decodificação, inferência, gravação da foto e `sink.put`) e libera o semáforo num `finally`, inclusive em erro.
- **Regra para a borda (`architecture.md` §9):** toda chamada a `load_capture_image` (§4.7), e portanto a `qc_preprocess.load_image`, em `qc_edge` acontece com esse semáforo. A sondagem do cabeçalho também fica dentro dele. A SPEC-010 (modo coleta, "mesmas regras da SPEC-007") usa o mesmo limitador.
- A página do celular mostra o 503 `server busy` como "Borda ocupada. Tente de novo." (rótulo PT-BR em `capture.js`).

### 4.7 Limites próprios da rota de captura (SEC-24-02)

A página `/capture` sempre envia a foto reencodada pelo `capture.js` (§4.4): no máximo 1280 px no lado maior, ou seja, no máximo 1 638 400 pixels (1280×1280). Os limites do `load_image` (10 MiB e 40 M pixels) existem para o ML, que lê as fotos originais do celular. Na rota, eles só servem a quem não usa a página. Por isso, a rota tem limites próprios, mais apertados, em `edge/src/qc_edge/limits.py`:

```python
CAPTURE_MAX_BYTES: int = 3_145_728          # 3 MiB: campo image (413)
CAPTURE_MAX_REQUEST_BYTES: int = 3_670_016  # 3,5 MiB: Content-Length da requisição (413, middleware)
CAPTURE_MAX_PIXELS: int = 4_000_000         # largura × altura (415)
def load_capture_image(data: bytes) -> PIL.Image.Image
```

`load_capture_image` faz, nesta ordem:

1. Se `PIL.ImageFile.LOAD_TRUNCATED_IMAGES` for verdadeira, levanta `RuntimeError` com `LOAD_TRUNCATED_IMAGES` na mensagem. A flag continua sendo a primeira verificação, como no `load_image`.
2. **Sondagem do cabeçalho:** uma função privada abre `PIL.Image.open(io.BytesIO(data), formats=("JPEG", "PNG"))` num bloco `with`, lê só o `size`, **sem** chamar `.load()`, e devolve só `(largura, altura)`. Assim, a memória da sondagem é liberada antes do passo 4. Toda exceção levantada nessa abertura vira `qc_preprocess.InvalidImageError` (`raise ... from exc`): com bytes hostis, o Pillow levanta `UnidentifiedImageError`, `OSError`, `SyntaxError`, `ValueError`, `DecompressionBombError` e outras. É o único `except Exception` permitido, e só em volta dessa chamada.
3. Se `largura × altura > CAPTURE_MAX_PIXELS`, levanta `InvalidImageError` com uma mensagem que contém `capture pixel limit`.
4. Devolve `qc_preprocess.load_image(data)`, com todas as regras das SPECs 002, 023 e 024.

**Por que 3 MiB e 4 M pixels:**

- 4 M pixels dão uma folga de cerca de 2,4× sobre o máximo da página (1280×1280).
- Um JPEG q=0,9 de 1280×1280 fica na ordem de centenas de KB a 2 MB, mesmo com textura forte. É uma estimativa: o CA-20 registra os tamanhos reais.
- Os dois limites cortam juntos os resíduos medidos (§4.6): a área corta o custo por scan e o pico de memória da decodificação (cerca de 10×), e o corpo limita as inundações de segmentos (custo medido na §4.6).
- Não mexem no `qc-preprocess` nem no ML, e não dependem de o canvas gerar JPEG baseline (a objeção da SPEC-024 §7 era à recusa de JPEG progressivo).
- A paridade do ADR-004 continua valendo: a rota só rejeita mais imagens, e toda imagem aceita passa pelo mesmo `load_image` e pelo mesmo `preprocess`.

O modo `collect` (SPEC-010) usa a mesma função e os mesmos limites.

## 5. Critérios de aceite

- **CA-01** — *Dado* `EDGE_PORT=70000` (ou `DEVICE_ID=Edge_01`, ou `DEVICE_ID` igual a `"edge-01\n"`, com quebra de linha final, ou `EDGE_SESSION_TOKEN` com 10 caracteres), *quando* `main()` é chamado, *então* sai com código 2 e a mensagem cita a variável inválida.
- **CA-02** — *Dado* `EDGE_SESSION_TOKEN` ausente, *quando* o app é criado duas vezes, *então* cada token tem ≥ 43 caracteres URL-safe e os dois são diferentes; *dado* `EDGE_SESSION_TOKEN` com 40 caracteres, *então* é ele o aceito em `X-Session-Token`.
- **CA-03** — *Dado* `StubInferencer` retornando `screw`/`good`, *quando* envio JPEG válido com `lot_id=L-001`, `mode=inspect` e token válido, *então* recebo 200; `inspection` tem os 14 campos do contrato, `source="live"`, `device_id` da config, `inspection_id` UUID v4, `inspected_at` com fuso UTC; `approved=true`; `labels_pt={"object_type":"parafuso","grade":"bom","verdict":"aprovada"}`; existe `captures/<data>/<inspection_id>.jpg`; o sink contém exatamente 1 item igual a `inspection`.
- **CA-04** — *Dado* o stub retornando `nut`/`poor`, *então* `approved=false` e `verdict="reprovada"`; *dado* o stub retornando `unknown` (grau nulo), *então* `approved=null`, `labels_pt.grade=null` e `verdict="desconhecido"`.
- **CA-05** — *Dado* um sink cujo `put` lança `SinkError`, *quando* envio uma foto válida, *então* recebo 503, nenhum arquivo fica em `captures/` e o sink está vazio.
- **CA-06** — *Dado* requisição sem `X-Session-Token` ou com token errado, *quando* chamo `POST /api/capture` ou `GET /api/status`, *então* recebo 401, `StubInferencer` tem 0 chamadas e nenhum arquivo é criado.
- **CA-07** — *Dado* token válido, *quando* envio `image` com 3 145 729 bytes, *então* recebo 413, `StubInferencer` tem 0 chamadas e nada é salvo; *quando* envio uma requisição com o header `Content-Length: 3670017`, *então* recebo 413 e `StubInferencer` tem 0 chamadas; e *quando* envio um JPEG válido de 64×48 completado com bytes `00` depois do EOI (`FF D9`) até exatamente 3 145 728 bytes, *então* recebo 200.
- **CA-08** — *Dado* token válido, *quando* envio um arquivo de texto chamado `foto.jpg`, um GIF válido, um JPEG truncado, um PNG válido de 100×1001 px (proporção acima de 10:1, SPEC-023), um JPEG válido 64×48 com um segmento COM de 64 pares `FF DA` logo depois do SOI (65 marcadores, SPEC-024) ou um JPEG válido de 2001×2000 px (4 002 000 pixels, acima do limite da rota, §4.7), *então* recebo 415 com `{"detail": ...}`, `StubInferencer` tem 0 chamadas e nada é salvo.
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
- **CA-20 (manual)** — Topologia preferida: 1. ligar `qc-edge` com `--stub-model` e liberar a porta conforme `edge/README.md`; 2. no celular A (Android, Chrome) e depois no celular B (o outro celular da dupla, navegador padrão), ler o QR do console na mesma Wi-Fi; 3. tocar "Fotografar": abre a câmera **traseira** (direto ou após escolher "Câmera" no seletor do Android, ADR-003; registrar qual); 4. fotografar 10 peças; 5. conferir em cada uma o cartão de resultado em menos de 3 s (tempo total exibido) e 10 linhas novas no console; 6. no notebook, registrar no test-report o tamanho do maior arquivo em `EDGE_DATA_DIR/captures/` de cada celular (deve ficar abaixo de 3 145 728 bytes, §4.7).
- **CA-21 (manual)** — Plano B: 1. ligar o hotspot do celular A e conectar o notebook a ele; 2. recarregar o console e usar o QR do novo IP; 3. repetir os passos 3–5 do CA-20 com 3 fotos em cada celular.
- **CA-22 (security, SEC-02)** — *Dado* `create_app(..., max_concurrent_decodes=2, decode_wait_s=0.5)` e um inferenciador de teste cujo `infer` registra o número de chamadas simultâneas e bloqueia até um `threading.Event` ser liberado, *quando* 4 requisições válidas são enviadas em paralelo (4 threads) e o evento só é liberado depois que 2 respostas chegaram, *então* exatamente 2 respostas são 503 com `{"detail": "server busy"}`, as outras 2 são 200, o máximo de chamadas simultâneas a `infer` é 2, o sink tem 2 itens e `captures/` tem exatamente 2 arquivos.
- **CA-23 (SEC-02)** — *Dado* o mesmo inferenciador com `max_concurrent_decodes=2` e `decode_wait_s=5`, *quando* 4 requisições válidas são enviadas em paralelo e o evento é liberado 0,3 s depois do envio, *então* as 4 respostas são 200 e o máximo de chamadas simultâneas a `infer` é 2; e *dado* um inferenciador que lança `InferenceError` na 1ª chamada, *quando* 3 requisições são enviadas em sequência com `max_concurrent_decodes=1`, *então* as respostas são 500, 200 e 200 (o semáforo é liberado depois do erro); e `create_app(..., max_concurrent_decodes=0)` ou `decode_wait_s=0` levanta `ValueError`.
- **CA-24 (security, SEC-04)** — *Dado* `PIL.ImageFile.LOAD_TRUNCATED_IMAGES = True` (via `monkeypatch.setattr`), *quando* `main()` é chamado com `uvicorn.run` substituído por um espião, *então* sai com código 1, a saída de log contém `LOAD_TRUNCATED_IMAGES` e o espião não é chamado; e *quando* um `TestClient(create_app(...))` entra no bloco `with`, *então* levanta `RuntimeError` cuja mensagem contém `LOAD_TRUNCATED_IMAGES`. Com a flag em `False`, os dois sobem normalmente.
- **CA-25 (security, SEC-04)** — *Dado* os arquivos `*.py` de `git ls-files` cujo caminho não tem nenhum componente `tests`, *quando* analisados com `ast`, *então* nenhum contém atribuição (`Assign`, `AugAssign` ou `AnnAssign`) a um alvo `Name` ou `Attribute` chamado `LOAD_TRUNCATED_IMAGES`, nem chamada `setattr(<qualquer>, "LOAD_TRUNCATED_IMAGES", <qualquer>)`.
- **CA-26 (security, SEC-24-02)** — *Dado* o módulo `qc_edge.limits`, *então* `CAPTURE_MAX_BYTES == 3_145_728`, `CAPTURE_MAX_REQUEST_BYTES == 3_670_016` e `CAPTURE_MAX_PIXELS == 4_000_000`. *Dado* um JPEG válido de 2000×2000 px e outro de 2001×2000 px, ambos aceitos por `qc_preprocess.load_image`, *quando* passam por `load_capture_image`, *então* o primeiro devolve uma imagem `RGB` de 2000×2000 e o segundo levanta `InvalidImageError` cuja mensagem contém `capture pixel limit`; e, com `PIL.ImageFile.ImageFile.load` envolvido por um espião que chama o original (`monkeypatch`), o espião tem 0 chamadas no caso 2001×2000 (a checagem vem antes de decodificar). Via `POST /api/capture`, o 2000×2000 recebe 200 e o 2001×2000 recebe 415.
- **CA-27 (security, SEC-24-02)** — *Dado* `load_capture_image`, *quando* recebe `b"not an image"`, `b""` ou um GIF válido, *então* levanta `InvalidImageError` (nunca outra exceção); *quando* recebe o JPEG 64×48 com COM de 64 pares `FF DA` do CA-08, *então* levanta `InvalidImageError` cuja mensagem contém `JPEG scans` (as regras do `load_image` continuam valendo); e, *dado* `PIL.ImageFile.LOAD_TRUNCATED_IMAGES = True` (via `monkeypatch.setattr`), *quando* recebe o JPEG de 2001×2000 do CA-26, *então* levanta `RuntimeError` cuja mensagem contém `LOAD_TRUNCATED_IMAGES` (a flag vem antes da sondagem).

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | config, token, `detect_lan_ips`, rotas com `StubInferencer`/`InMemorySink`, `load_capture_image` (limite exato de pixels, ordem flag → sondagem → `load_image`) | `edge/tests/` |
| Aceite (tester) | Um por CA automatizável (`httpx.ASGITransport` com `client=` para simular a origem; `tmp_path` como `EDGE_DATA_DIR`; socket simulado com `monkeypatch`; nos CA-22 e CA-23, threads com `TestClient` e um inferenciador de teste controlado por `threading.Event`) | `edge/tests/acceptance/test_spec_007.py` |
| Manual (dupla) | CA-20 e CA-21, resultado no test-report | celulares reais |

Sem rede real nos testes. Mock só de fronteiras: socket, relógio e o inferenciador (stub).

## 7. Riscos e notas para o implementador

- O `uvicorn` aplica `X-Forwarded-For` de `127.0.0.1` por padrão; por isso `proxy_headers=False` e a checagem de headers no console.
- `<input capture>` funciona em HTTP (não exige contexto seguro), diferente de `getUserMedia` (SPEC-019).
- **SEC-05 (filtros de `warnings`):** no Python 3.12, `warnings.catch_warnings` altera estado global e não é seguro entre threads. O `load_image` não depende disso (o limite efetivo é a checagem explícita de `MAX_PIXELS`), e nenhuma decisão de segurança da borda pode depender de filtros de `warnings`.
- A checagem da flag na subida (§4.2 e §4.3) fecha a janela entre a leitura da flag no `load_image` e a nova consulta do Pillow dentro do `.load()` (SEC-04): como nenhum módulo do processo altera a flag (CA-25), ela não muda depois da subida.
- **Sondagem do §4.7:** não tente ler a largura e a altura interpretando os segmentos do JPEG à mão. Use o `Image.open` do Pillow, que é o mesmo parser do `load_image`, e não chame `.load()` nem `.draft()` na sondagem. Gerar os JPEGs de 2000×2000 e 2001×2000 dos CAs em cor sólida mantém os arquivos pequenos (dezenas de KB).
- **JPEG aritmético (SEC-24-02, item c):** hoje, o libjpeg-turbo empacotado na wheel do Pillow 12.3.0 não decodifica JPEG com codificação aritmética, e o `load_image` o recusa com `InvalidImageError` em ~10 ms. Isso limita o custo de scans sem dados. Ao subir o Pillow no `uv.lock`, em qualquer SPEC, siga a regra de `docs/architecture.md` §9 (reconferir essa recusa).
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
| 2026-10-12 | Mudanças: (a) dependência da SPEC-024 (`qc-preprocess` 0.3.0, limite de 64 marcadores de scan no JPEG), com o caso novo no CA-08; (b) §4.6 nova: limitador de decodificações (`BoundedSemaphore`, padrão 2, espera de 10 s, 503 `server busy`), com os parâmetros `max_concurrent_decodes` e `decode_wait_s` em `create_app` e a ordem do §4.5 atualizada; (c) checagem de `LOAD_TRUNCATED_IMAGES` na subida, no `lifespan` e na CLI (código 1); (d) CAs novos: CA-22 e CA-23 (limitador), CA-24 (flag na subida) e CA-25 (nenhum código fora de `tests/` altera a flag); (e) §7 com a regra sobre filtros de `warnings`. Nenhum outro requisito muda. SPEC marcada como "Aguardando reaprovação humana". | SEC-01, SEC-02, SEC-04 e SEC-05 de `reviews/SPEC-023/r1-security-report.md`, e a nota sobre a janela da flag de `reviews/SPEC-023/r1-review-report.md` | Orquestrador, a pedido do humano |
| 2026-10-12 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
| 2026-10-12 | Mudanças: (a) §4.6: dimensionamento do limitador com o custo medido (~2,5 s e ~360 MB por decodificação só com os limites do `load_image`; ~1,4 s e ~110 MB estimados com os da rota), mantendo os padrões 2 e 10 s; (b) §4.7 nova, adotada pelo architect: limites próprios da rota em `qc_edge/limits.py` (corpo de 3 MiB, `Content-Length` de 3,5 MiB e 4 M pixels checados pelo cabeçalho antes de decodificar), com `load_capture_image`; a §4.5 (passos 1 e 3) passa a usá-la; (c) §4.4: o `capture.js` nunca envia o arquivo original; (d) o CA-07 trocou o limite de 10 MiB pelo de 3 MiB e ganhou os casos do `Content-Length` e da fronteira exata; o CA-08 ganhou o JPEG de 2001×2000; o CA-20 ganhou o passo 6 (tamanho real das fotos); CAs novos: CA-26 e CA-27 (`load_capture_image`); (e) §7: notas sobre a sondagem e sobre a recusa do JPEG aritmético ao subir o Pillow. SPEC marcada como "Aguardando reaprovação humana". | SEC-24-02 de `reviews/SPEC-024/r1-security-report.md` | Orquestrador, a pedido do humano |
| 2026-10-12 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
| 2026-10-13 | Só texto, com a SPEC em PR (r1): (a) §4.6: a estimativa por slot (~1,4 s e ~110 MB) dá lugar aos valores medidos (~4 s de CPU e ~90 MB acima da base, pico de 133 MB, com os 2 slots serializados pelo GIL em ~1 núcleo); a "consequência aceita" passa a citar os tempos medidos e o efeito no console e no `/api/status`; a redução opcional de `CAPTURE_MAX_BYTES` depois do CA-20 fica registrada como decisão futura; (b) §4.7: o "cerca de 3×" das inundações passa a remeter à medição. Nenhum requisito, limite, padrão ou CA muda, por isso a SPEC **não** volta para reaprovação. As demais pendências dos portões r1 foram encaminhadas: SEC-01, SEC-03, SEC-04, SEC-05, SEC-07, a parte de `captures/` do SEC-06, RV-04 e RV-05 → SPEC-025; a parte de `DATASET_DIR` do SEC-06 → SPEC-010. | SEC-02 (= RV-01) e SEC-03 de `reviews/SPEC-007/r1-security-report.md` | Orquestrador, a pedido do humano |
