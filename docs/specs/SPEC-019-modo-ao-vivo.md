# SPEC-019: Fase 3 — modo vídeo ao vivo (HTTPS na LAN)

| Campo | Valor |
|---|---|
| Status | In Review |
| Rodada atual | r2 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-008, SPEC-025, SPEC-030, SPEC-041 (e SPEC-007, SPEC-009, SPEC-024). Sem mudança de contrato |
| Semana alvo | Logo depois da SPEC-041 (`041 → 019`). O portão da Fase 3 (M3, 22/11) deixa de bloquear esta SPEC (ADR-024, decisão 5; `docs/plan.md` §4, 2026-11-01) |
| Requisitos cobertos | PRD §4.3; RNF-02, RNF-05; R-02, R-03, R-06, R-14 |
| ADRs relevantes | ADR-003 (opção B, prevista para a Fase 3), ADR-002, ADR-004, ADR-009, ADR-024 |

> **Aprovada pelo humano em 2026-10-24** (PR #45), no pacote das Fases 2 e 3, com os ADRs 021 e 022 `Aceito`. Revista pelo architect em 2026-10-24 e em 2026-11-01 (ver o Histórico).
>
> **Reaprovada pelo humano em 2026-11-01** ("Sim, codar agora"): o teste do certificado passa a ser depois do merge. Ver o Histórico.
>
> **Reaprovada pelo orquestrador sob o ADR-019 em 2026-11-01:** SPEC_ISSUE-01 a 09. Ver o Histórico.
>
> **Reaprovada pelo humano em 2026-11-01:** SPEC_ISSUE-10, 11 e 12. Ver o Histórico.

## 1. Contexto

O MVP usa foto por disparo (`<input capture>`, N-09, ADR-003), que funciona em HTTP na LAN. O vídeo contínuo exige `getUserMedia`, que o navegador só libera em **contexto seguro** (HTTPS ou `localhost`) (<https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia>, citado no ADR-003). Túnel público é proibido (R-02, `docs/architecture.md` §8). Resta o HTTPS local com uma CA própria (`mkcert`, licença BSD-3-Clause, <https://github.com/FiloSottile/mkcert>, consultado pelo architect em 2026-10-24). Segundo o README do mkcert, nos celulares é preciso instalar o `rootCA.pem`: no iOS, como perfil e com "confiança total" ativada; no Android, o README só fala de apps em modo de desenvolvimento, e o architect não encontrou fonte oficial que confirme se o Chrome do Android confia numa CA instalada pelo usuário. Por isso o teste nos dois celulares é um passo humano, feito **depois do merge** (§3.3): a implementação não espera por ele e assume o risco descrito lá.

A ideia original (`docs/archive/ideia-original.md`) previa a máquina de estados `IDLE → DETECTING → EMIT → WAIT_REMOVAL`.

## 2. Objetivo

Na página `/live`, servida por HTTPS na LAN, o celular mostra o vídeo da câmera traseira com o resultado sobreposto e registra **uma** inspeção por peça quando a classificação fica estável, pelo mesmo caminho da foto (decisão, outbox e `captures/`).

## 3. Escopo

### 3.1 Dentro

- HTTPS opcional da borda: `EDGE_TLS_CERT` e `EDGE_TLS_KEY` (§4.1).
- `edge/src/qc_edge/live.py`: `LiveStateMachine` e `LiveSessions` (§4.2 e §4.3).
- Rota `POST /api/live/frame` e página `GET /live?t=<token>` (`edge/src/qc_edge/templates/live.html` e `edge/src/qc_edge/static/live.js`) (§4.4 e §4.5).
- Console: o QR code e o link usam `https://` quando o TLS está ligado. Só com o TLS ligado, o console oferece também o QR do `/live`. O console mostra a última latência por quadro e o p95 dos últimos 100 quadros (§4.4).
- `edge/README.md` (seção "Vídeo ao vivo (HTTPS)": `mkcert`, instalação da CA nos celulares, onde guardar o certificado e a chave) e `.env.example`.
- Testes do autor em `edge/tests/` (fora de `acceptance/`).
- **Tester:** `edge/tests/acceptance/test_spec_019.py`.

### 3.2 Fora

- Gravação de vídeo; envio de quadros para a nuvem (proibido, R-02); detecção com caixas (PRD §4.4).
- Classe `empty` no modelo: não adotada. A "mesa vazia" é o resultado `unknown` (classe `other` ou confiança baixa), que o modelo já produz (pergunta 3 do rascunho).
- Túnel público: proibido (R-02).

### 3.3 Trabalho humano

1. **Depois do merge:** gerar a CA e o certificado com `mkcert <ip-lan> 127.0.0.1 localhost` no notebook, instalar o `rootCA.pem` nos dois celulares e conferir, com a própria `/live` da borda já mergeada, se o navegador de cada celular abre `getUserMedia`. Registrar o navegador, a versão e o resultado. Este teste não bloqueia o loop nem o merge.
2. Executar o CA-12 (manual), depois do passo 1.

**Risco aceito pelo humano em 2026-11-01:** se nenhum celular aceitar o certificado, o modo vídeo não funciona na apresentação. A foto por disparo continua igual (CA-14), a apresentação usa só ela, e o CA-12 fica registrado como não atendido, com o resultado do passo 1. Nada é revertido.

## 4. Requisitos detalhados

### 4.1 HTTPS da borda

- `EDGE_TLS_CERT` e `EDGE_TLS_KEY`: caminhos de arquivos PEM. Os dois vazios (padrão) = HTTP, como hoje. Só um preenchido, arquivo inexistente ou ilegível, ou a chave com permissão de leitura para grupo ou outros (`mode & 0o077 != 0`) → erro na subida com código 2 e uma mensagem que cita a variável, sem o conteúdo do arquivo. "Ilegível" é o arquivo que não abre para leitura: o conteúdo do PEM não é conferido na configuração (CA-09), e um PEM inválido faz o `uvicorn` falhar na subida, sem servir nenhuma rota.
- Com os dois, o uvicorn sobe com `ssl_certfile` e `ssl_keyfile`. O console continua só para loopback (SPEC-025), agora em `https://127.0.0.1:<porta>`.
- O `edge/README.md` manda guardar o certificado e a chave em `edge/data/tls/` (já ignorado pelo Git), com a chave em `0600`. A chave nunca entra no repositório (R-03).

### 4.2 Máquina de estados (`LiveStateMachine`)

```python
class LiveStateMachine:
    def __init__(self, window: int = 10, min_agree: int = 8, min_confidence: float = 0.80,
                 empty_frames: int = 3) -> None
    def feed(self, result: InferenceResult, frame: bytes, inspected_at: datetime) -> LiveStep
    def reset(self) -> None
# LiveStep: state ("IDLE" | "DETECTING" | "EMIT" | "WAIT_REMOVAL"), stability (0..1),
#           emit: (InferenceResult, bytes, datetime) | None
```

- `InferenceResult` é o de `qc_edge.inference` (SPEC-007), que traz o `latency_ms` usado na inspeção (§4.4).
- `LiveStep.state` é o estado depois do passo. No passo que emite, é `EMIT`, e o `feed` seguinte já parte de `WAIT_REMOVAL`.
- `IDLE`: um resultado com tipo diferente de `unknown` passa a `DETECTING` e entra na janela.
- `DETECTING`: a janela guarda os últimos `window` resultados. O passo é `EMIT` quando a janela está cheia e o par `(object_type, grade)` mais frequente cumpre as quatro condições:
  1. é o único mais frequente: um empate no topo não é classificação estável, então não há `EMIT`, e a janela segue rolando;
  2. não é `(unknown, None)`: a mesa vazia nunca gera inspeção, mas um tipo conhecido sem grau, como `(drill, None)`, emite;
  3. tem pelo menos `min_agree` quadros;
  4. a média de `type_confidence` desses quadros é `>= min_confidence`.

  No `EMIT`, `emit` traz o quadro **mais recente** desse par, e o estado seguinte é `WAIT_REMOVAL`. `empty_frames` resultados `unknown` seguidos voltam a `IDLE` e limpam a janela.
- `WAIT_REMOVAL`: nada é emitido; a janela de resultados continua rolando, só para a `stability`; `empty_frames` resultados `unknown` seguidos voltam a `IDLE` e limpam a janela.
- `stability` = quadros do par mais frequente / `window` (0 em `IDLE`), calculada sobre a janela de resultados. O par `(unknown, None)` também conta, e num empate vale a contagem empatada.
- Os bytes dos quadros ficam só em memória. A janela só guarda os bytes dos quadros que podem ser emitidos: os de resultado `unknown` e os recebidos em `WAIT_REMOVAL` não são guardados. Os guardados são descartados ao sair da janela, no `reset` e no fim da sessão.

### 4.3 Sessões (`LiveSessions`)

- Uma sessão por identificador `session` enviado pela página (`re.fullmatch(r"[A-Za-z0-9_-]{16,64}", valor)`), gerado no navegador com `crypto.getRandomValues`.
- No máximo `LIVE_MAX_SESSIONS` sessões (padrão 4). Uma sessão sem quadro há mais de 60 s é descartada. Com o máximo atingido, uma sessão nova recebe 429 `{"detail": "too many live sessions"}`.
- Trocar o `lot_id` dentro da sessão chama `reset`.
- A inatividade é medida com o `clock` do `create_app` (SPEC-007).
- O `feed` e o `reset` de uma sessão, e a criação e a expiração de sessões, são serializados por lock: duas requisições simultâneas da mesma sessão nunca emitem duas vezes. A gravação da inspeção fica fora desse lock.

### 4.4 Rota `POST /api/live/frame`

- `multipart/form-data`: `image` (só JPEG, pelo conteúdo: PNG recebe 415, diferente da captura, porque a janela guarda os bytes e não a imagem decodificada que a reencodagem do PNG exige), `lot_id`, `session`; header `X-Session-Token`. Ordem dos erros igual à da `/api/capture` (SPEC-007 §4.1): token (401) → tamanho (413) → campos (422) → limitador de decodificações (503 `server busy`, SPEC-007 §4.6, compartilhado com a captura) → imagem (415) → modelo (503 `model not loaded`) → sessões (429).
- Limites próprios: `image` ≤ `LIVE_MAX_BYTES` = 1 048 576 bytes; requisição ≤ `LIVE_MAX_REQUEST_BYTES` = 1 310 720 bytes (o middleware de `Content-Length` da SPEC-007 aplica esse limite a esta rota, e as outras continuam com `CAPTURE_MAX_REQUEST_BYTES`); ≤ `LIVE_MAX_PIXELS` = 1 000 000 pixels, conferidos pelo cabeçalho antes de decodificar; depois, as regras do `qc_preprocess.load_image`.
- Infere sem criar inspeção. `InferenceError` → 500 `{"detail": "inference failed"}`, como na captura (SPEC-007 §4.5, passo 5), sem chamar `feed`: o quadro não entra na janela, e o estado da sessão não muda.
- No passo `EMIT`, cria **uma** inspeção pelo mesmo caminho da `/api/capture` no modo `inspect` (decisão, `InspectionCreate` com o `source` da SPEC-041 §4.7, ou seja, `simulated` para um modelo provisório e `live` para os outros, `inspection_id` novo, o quadro emitido salvo em `captures/AAAA-MM-DD/<inspection_id>.jpg`, `sink.put` antes de responder), com o `inspected_at` e a latência do quadro emitido.
- **Falha ao gravar no passo `EMIT`:** a resposta é a da captura (`SinkError` → 503 `{"detail": "failed to persist inspection"}`, com a foto apagada; outra falha, como disco cheio → 500), e a rota chama o `reset` da sessão. A próxima janela estável emite de novo, com `inspection_id` novo. Continua havendo uma inspeção por peça, porque a tentativa que falhou não gravou nada.
- Resposta 200: `{"state", "stability", "result": {"object_type", "grade", "type_confidence", "labels_pt": {"object_type", "grade", "verdict"}}, "inspection": <InspectionCreate em JSON> | null}`.
  - `result` é sempre um objeto, com o resultado do quadro **atual**, porque toda resposta 200 passou pela inferência. `labels_pt` é montado como na captura.
  - Num resultado `unknown`, `result.grade` e `labels_pt.grade` são `null`, e `labels_pt.object_type` e `labels_pt.verdict` são `desconhecido`, que é o que o overlay mostra.
  - `inspection` só vem no passo `EMIT`, com o quadro emitido, que pode ser diferente do atual (CA-01).
- **Latência (CA-12, passo 6):** a borda guarda o `latency_ms` de cada quadro inferido, de todas as sessões, numa memória dos últimos 100. O console mostra, no elemento `id="live-latency"`, a última latência e o p95 em ms (posto mais próximo: `sorted(v)[ceil(0,95 × n) − 1]`); sem quadros, mostra `—`. Esse valor não vai à resposta da rota nem à nuvem.
- Com um modelo provisório, `result.labels_pt.verdict` recebe o mesmo sufixo ` (modelo provisório)` da captura (SPEC-041 §4.7), para o overlay também avisar.
- Com `--stub-model`, a rota funciona e o sink é o `InMemorySink` (nada vai para a nuvem, R-06).

### 4.5 Página `/live`

- `GET /live?t=<token>`: sem token válido → 401, como a `/capture`. Com ou sem token, a resposta leva os headers da `/capture` (`Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`), porque o token está na URL.
- O HTML fica em `edge/src/qc_edge/templates/live.html`, renderizado pela rota, que passa o `LIVE_FPS`, e nunca em `static/`, servido sem token. O JS fica em `edge/src/qc_edge/static/live.js`, sem segredo (ADR-003, SPEC-007 §4.4). Sem framework.
- A página tem o campo de lote, como a `/capture`, porque a rota exige `lot_id`.
- Se `window.isSecureContext` for falso, a página mostra `O vídeo ao vivo exige HTTPS (configure EDGE_TLS_CERT e EDGE_TLS_KEY).` e não pede a câmera.
- `getUserMedia({video: {facingMode: "environment"}})`; captura a `LIVE_FPS` quadros por segundo (padrão 2), com o lado maior em até 640 px e JPEG com qualidade 0,8; no máximo uma requisição em andamento (os quadros que chegam nesse meio são descartados, não enfileirados); overlay em `<canvas>` com o rótulo PT-BR, a confiança, o estado e a barra de estabilidade; no `EMIT`, mostra o resultado da inspeção por 2 s.

### 4.6 Configuração

| Variável | Padrão | Regra |
|---|---|---|
| `EDGE_TLS_CERT`, `EDGE_TLS_KEY` | vazios | §4.1 |
| `LIVE_WINDOW` | 10 | inteiro de 3 a 30 |
| `LIVE_MIN_AGREE` | 8 | inteiro de 1 a `LIVE_WINDOW` |
| `LIVE_MIN_CONFIDENCE` | 0.80 | número de 0,50 a 0,99 |
| `LIVE_EMPTY_FRAMES` | 3 | inteiro de 1 a 10 |
| `LIVE_MAX_SESSIONS` | 4 | inteiro de 1 a 8 |
| `LIVE_FPS` | 2 | inteiro de 1 a 5 (passado à página) |

Valor fora da regra → erro na subida com código 2.

## 5. Critérios de aceite

Contexto comum: resultados de inferência montados pelo teste (`InferenceResult`, de `qc_edge.inference`, SPEC-007); borda com o modelo dummy da SPEC-008 e um sink em memória nos CAs de rota; JPEGs gerados com Pillow.

- **CA-01 (emissão)** — *Dado* uma `LiveStateMachine` padrão, *quando* recebe 10 resultados com 8 `screw/fair` (confiança de tipo média 0,85) e 2 `screw/poor`, nesta ordem: 1 `poor`, 8 `fair`, 1 `poor`, *então* exatamente o 10º passo é `EMIT`, `emit` traz o 9º quadro (o `fair` mais recente) e o estado seguinte é `WAIT_REMOVAL`.
- **CA-02 (sem emissão)** — *Dado* 10 resultados com só 7 iguais, ou 8 iguais com confiança média 0,79, *quando* processados, *então* nenhum passo é `EMIT`.
- **CA-03 (remoção)** — *Dado* o estado `WAIT_REMOVAL` do CA-01, *quando* chegam mais 20 resultados `screw/fair` com confiança 0,9, *então* nenhum `EMIT`; *quando* chegam então 2 resultados `unknown` e 1 `screw/fair`, *então* o estado continua `WAIT_REMOVAL`; e 3 `unknown` seguidos levam a `IDLE`, depois do que 10 resultados `nut/good` com confiança 0,9 geram um novo `EMIT`.
- **CA-04 (troca de lote)** — *Dado* uma sessão com 9 quadros `screw/fair` na janela, *quando* o próximo quadro chega com outro `lot_id`, *então* a janela recomeça: com quadros `screw/fair` de confiança 0,9 no lote novo, o primeiro `EMIT` acontece no 10º quadro contado a partir da troca (inclusive), e não antes.
- **CA-05 (rota, erros)** — *Dado* a borda, *quando* `POST /api/live/frame` é chamado, em casos separados, sem token, com `image` de 1 048 577 bytes, com o header `Content-Length: 1310721`, com `session="curto"`, com `lot_id="lote 1"`, com um GIF, com um PNG válido e com um JPEG de 1001×1000 px, *então* as respostas são, respectivamente, 401, 413, 413, 422, 422, 415, 415 e 415, e o modelo dummy não é chamado em nenhum caso.
- **CA-06 (rota, uma inspeção por peça)** — *Dado* o modelo dummy configurado para devolver `screw/fair` com confiança 0,9, *quando* a mesma sessão envia 30 quadros válidos, *então* exatamente uma resposta tem `inspection` não nulo, o sink tem uma inspeção, `captures/` tem um arquivo `<inspection_id>.jpg`, e o `inspection_id` da resposta é o do sink.
- **CA-07 (R-02)** — *Dado* o CA-06 com o sink sendo o outbox SQLite, *quando* o `payload` gravado é lido, *então* ele valida como `InspectionCreate` e não tem nenhum campo com bytes de imagem; e o número de arquivos em `captures/` é igual ao número de inspeções emitidas.
- **CA-08 (sessões)** — *Dado* `LIVE_MAX_SESSIONS=2` e o `clock` do `create_app` controlado pelo teste, *quando* três sessões enviam quadros válidos, A em t = 0 s, B em t = 30 s e C em t = 31 s, *então* C recebe 429; *quando* C envia de novo em t = 61 s (A está há 61 s sem quadro, e B, há 31 s), *então* C recebe 200.
- **CA-09 (TLS, configuração)** — *Dado* `EDGE_TLS_CERT` preenchido e `EDGE_TLS_KEY` vazio, ou a chave com modo `0o644`, ou um caminho inexistente, *quando* a borda sobe, *então* sai com código 2 e a mensagem cita a variável; *dado* dois arquivos existentes em `tmp_path` (o conteúdo não é conferido na configuração), com a chave em `0o600`, *então* os argumentos do uvicorn montados pela borda têm `ssl_certfile` e `ssl_keyfile` com esses caminhos, e as URLs dos dois QRs do console (`/capture` e `/live`) começam com `https://`.
- **CA-10 (página)** — *Dado* `GET /live` sem token, *então* 401; com token, *então* 200 com `text/html`, e o HTML referencia `live.js` e tem o campo `lot_id`; nas duas respostas, `Cache-Control: no-store` e `Referrer-Policy: no-referrer`; `GET /static/live.html` sem token responde 404; e o arquivo `live.js` contém `isSecureContext`, `getUserMedia` e `facingMode`.
- **CA-11 (configuração)** — *Dado* `LIVE_WINDOW=2`, `LIVE_MIN_AGREE=11` (com `LIVE_WINDOW=10`), `LIVE_MIN_CONFIDENCE=1.2` ou `LIVE_MAX_SESSIONS=0`, *quando* a borda sobe, *então* sai com código 2.
- **CA-12 (manual, dupla)** — 1. Gerar o certificado com `mkcert` para o IP da LAN, `127.0.0.1` e `localhost`, e configurar `EDGE_TLS_CERT`/`EDGE_TLS_KEY`; 2. instalar a CA nos dois celulares (passo 1 do §3.3); 3. abrir `/live` pelo QR do console e conceder a câmera; 4. inspecionar 5 peças seguidas, tirando cada uma da mesa entre elas; 5. conferir 5 inspeções na nuvem (ou no console, sem nuvem) e 5 arquivos em `captures/`; 6. registrar a latência por quadro observada no console (`live-latency`). Pode ser feito com o modelo provisório (SPEC-041), com as inspeções `simulated` e a latência só como indicativo.
- **CA-13 (R-06, modelo provisório)** — *Dado* o modelo dummy num diretório `partqc-mnv3-provisional-v1`, devolvendo `screw/fair` com confiança 0,9, *quando* a mesma sessão envia 30 quadros válidos, *então* a resposta com `inspection` não nulo tem `inspection.source = "simulated"`, o sink guarda `source = simulated` e `result.labels_pt.verdict` termina em ` (modelo provisório)`. *Dado* o mesmo modelo em `partqc-mnv3-v1`, *então* `inspection.source = "live"`, sem sufixo.
- **CA-14 (foto por disparo sem TLS)** — *Dado* `EDGE_TLS_CERT` e `EDGE_TLS_KEY` vazios, *quando* a borda sobe, *então* os argumentos do uvicorn não têm `ssl_certfile` nem `ssl_keyfile`, a URL do QR do console começa com `http://`, o console não contém `/live?`, e `POST /api/capture` no modo `inspect` com o token válido responde 200 e grava uma inspeção no sink, como antes desta SPEC.
- **CA-15 (mesa vazia nunca emite)** — *Dado* `LiveStateMachine(window=10, min_agree=3, empty_frames=10)`, *quando* recebe 1 `screw/fair` e, em seguida, 9 resultados `unknown` com confiança 0,95, *então* nenhum passo é `EMIT`, e o 10º passo tem `state = "DETECTING"` e `stability = 0.9`; *quando* recebe mais 1 `unknown`, *então* o estado é `IDLE`, com `stability = 0`. *Dado* uma máquina padrão, *quando* recebe 10 resultados `drill` sem grau com confiança 0,9, *então* o 10º passo é `EMIT`.
- **CA-16 (empate)** — *Dado* `LiveStateMachine(window=10, min_agree=5)`, *quando* recebe 10 resultados com confiança 0,9, alternando `screw/poor` e `screw/fair`, nesta ordem, *então* nenhum passo é `EMIT`; *quando* recebe mais 1 `screw/fair`, *então* esse 11º passo é `EMIT`, e `emit` traz o 11º quadro.
- **CA-17 (`result` nunca é nulo)** — *Dado* o modelo dummy configurado para devolver a classe `other`, *quando* uma sessão envia 3 quadros válidos, *então* as 3 respostas são 200, com `state = "IDLE"`, `stability = 0`, `inspection = null`, `result.object_type = "unknown"`, `result.grade = null`, `result.labels_pt.grade = null` e `result.labels_pt.object_type = result.labels_pt.verdict = "desconhecido"`, e o sink e `captures/` ficam vazios. No CA-06, todas as 30 respostas têm `result` não nulo.
- **CA-18 (falha ao gravar)** — *Dado* o modelo dummy devolvendo `screw/fair` com confiança 0,9 e um sink cujo `put` lança `SinkError` só na 1ª chamada, *quando* a mesma sessão envia 30 quadros válidos, *então* o 10º recebe 503 `{"detail": "failed to persist inspection"}`, o 20º recebe 200 com `inspection` não nulo, os demais recebem 200 com `inspection` nulo, e o sink e `captures/` têm exatamente uma inspeção, com o `inspection_id` da resposta do 20º.
- **CA-19 (falha de inferência)** — *Dado* um inferenciador que lança `InferenceError` só no 5º quadro e devolve `screw/fair` com confiança 0,9 nos demais, *quando* a mesma sessão envia 11 quadros válidos, *então* o 5º recebe 500 `{"detail": "inference failed"}`, e o primeiro `inspection` não nulo vem no 11º (o quadro que falhou não entra na janela).
- **CA-20 (latência no console)** — *Dado* `GET /` em loopback sem nenhum quadro, *então* `id="live-latency"` mostra `—`. *Dado* um inferenciador que devolve `latency_ms` 300 nos 2 primeiros quadros e 100 nos 18 seguintes, *quando* uma sessão envia esses 20 quadros válidos, *então* `id="live-latency"` mostra a última latência `100 ms` e o p95 `300 ms`, e nenhuma resposta da rota tem a chave `p95`.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Máquina de estados (cada transição, janela, estabilidade); sessões e expiração; rota (ordem dos erros, limites, emissão); TLS e configuração | `edge/tests/` |
| Aceite (tester) | Um por CA automatizado | `edge/tests/acceptance/test_spec_019.py` |
| Manual (dupla), depois do merge | §3.3, passo 1, e CA-12 | descritos acima |

## 7. Riscos e notas para o implementador

- **Limitador compartilhado:** a 2 fps por sessão, o vídeo disputa os 2 slots de decodificação com a captura (SPEC-007 §4.6). O 503 `server busy` faz a página descartar o quadro, e o operador da foto vê "Borda ocupada"; é aceitável para a demo.
- **Memória:** no pior caso, `LIVE_MAX_SESSIONS × LIVE_WINDOW × LIVE_MAX_BYTES` de quadros em memória: 4 × 10 × 1 MiB = 40 MiB com os padrões, e 8 × 30 × 1 MiB = 240 MiB nos tetos do §4.6.
- **Latência:** cada quadro passa pela inferência; a RNF-02 (p95 ≤ 300 ms) vale por quadro e é medida no CA-12.
- **Argumentos do uvicorn:** isole a montagem deles numa função pura, para o CA-09 conferir sem subir o servidor nem gerar certificado. Nenhuma dependência nova.

## 8. Definição de pronto

- [ ] Todos os CAs automatizados com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED e security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `edge/README.md` e `.env.example` atualizados; `docs/architecture.md` §6.1 e §6.4 pelo architect
- [ ] PR aberto com os relatórios; merge conforme R-09. O CA-12 manual e o §3.3 ficam pendentes no merge, marcados no quadro, e são registrados depois dele

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-24 | SPEC revista para a aprovação, com a regra de escopo mantida (Fase 3 só se a Fase 2 fechar no prazo). Decisões do architect: HTTPS opcional por `EDGE_TLS_CERT`/`EDGE_TLS_KEY`, com a chave em `0600` fora do Git; máquina de estados com janela, maioria, confiança e remoção definidas, emitindo o quadro mais recente do par; sessões por identificador da página, com teto e expiração; limites próprios da rota (1 MiB, 1 M pixels) e a ordem de erros da `/api/capture`, com o limitador compartilhado; "mesa vazia" = `unknown` (sem classe `empty`); teste humano da CA nos dois celulares antes de `In Dev` (o README do mkcert, consultado em 2026-10-24, não confirma o Chrome do Android); dependências das SPECs 025 e 030; CAs CA-01 a CA-11 testáveis e CA-12 manual. A SPEC continua `Draft`. | Decisão do humano de 2026-10-24 (projeto inteiro, todas as fases) | Orquestrador, a pedido do humano |
| 2026-10-24 | Aprovada pelo humano (`Draft` → `Ready`) com o pacote das Fases 2 e 3 e a ordem proposta; a regra de escopo da Fase 3 continua (só depois do portão da Fase 2, 22/11). | Respostas do humano de 2026-10-24 (PR #45) | Orquestrador, a pedido do humano |
| 2026-10-24 | Limpeza de consistência pós-aprovação, sem mudança de requisito, CA, valor ou escopo: o aviso do topo passa a registrar a aprovação, mantendo a regra de escopo da Fase 3. | Status `Ready` desde o PR #45; sobrava o aviso da fase de rascunho | Architect, a pedido do orquestrador |
| 2026-11-01 | O teste humano do certificado (§3.3) sai de "antes de `In Dev`" e passa a ser depois do merge, sem bloquear o loop, com o risco registrado; o CA-12 fica pendente no merge (§8). A Semana alvo deixa de depender do portão da Fase 3: a ordem é `041 → 019`. Nota da SPEC-041: `source` e sufixo do veredito iguais aos da captura para um modelo provisório (§4.4) e CA-13 novo; CA-14 novo, para a foto por disparo continuar igual sem TLS. Dependência nova da SPEC-041. Status continua `Ready`. **Classificação ADR-019: exige humano (X-5: CA, comportamento e dependência novos; X-7: R-06; não há `SPEC_ISSUE`, então E-1 não se cumpre).** | Resposta do humano de 2026-11-01, relatada pelo orquestrador ("Sim, codar agora"), à pergunta: "a SPEC é corrigida para o teste vir depois do merge; risco: se nenhum celular aceitar o certificado, o modo vídeo não funciona na apresentação, mas a foto por disparo continua igual"; humano pediu para terminar o projeto. Os CAs 13 e 14 e a dependência da SPEC-041 são texto do architect, que decorre do ADR-024 e dessa resposta | Orquestrador, a pedido do humano |
| 2026-11-01 | Os CAs 13 e 14 foram apresentados ao humano por resumo e aprovados. A Semana alvo e os ADRs relevantes passam a citar o ADR-024, cuja decisão 5 tira a Fase 3 da dependência do prazo da Fase 2. Nenhum requisito, CA ou valor muda. O status e o aviso do topo não mudam, e a classificação ADR-019 continua a da linha anterior. | Resposta do humano de 2026-11-01, relatada pelo orquestrador (ADR-024, resposta 8) | Orquestrador, a pedido do humano |
| 2026-11-01 | Reaprovada pelo humano: teste do certificado depois do merge, Fase 3 sem esperar o prazo da Fase 2 (ADR-024) e CAs 13 e 14. | Respostas do humano de 2026-11-01, nesta sessão | Orquestrador, a pedido do humano |
| 2026-11-01 | Correção do SPEC_ISSUE-01 (§4.2 e contexto comum do §5). Antigo: "`feed(self, result: DecisionResult, ...)`", "`emit: (DecisionResult, bytes, datetime)`" e "`DecisionResult` da SPEC-008". Novo: `InferenceResult`, de `qc_edge.inference` (SPEC-007). Evidência: o nome `DecisionResult` não existe; `Decision` (`edge/src/qc_edge/decision.py:91`) não tem `latency_ms`, e `InferenceResult` (`edge/src/qc_edge/inference.py:50`) tem o que o §4.4 pede. Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão). E-1: SPEC_ISSUE-01. E-2: toca só este arquivo. E-3: aprovada e `Blocked` por este `SPEC_ISSUE`. E-4 tipo 1: corrige o nome de um tipo que não existe. E-5: só os trechos citados. X-1 a X-4: nada de SPEC nova, ADR, outro documento ou contrato. X-5: a assinatura pedida não muda de forma, e o tipo já existe. X-6: nenhum CA muda de sentido. X-7 e X-9: não toca regra inegociável; primeira correção do trecho. | SPEC_ISSUE-01 de `reviews/SPEC-019/r1-dev-report.md` | Orquestrador (loop da SPEC-019) |
| 2026-11-01 | Correção do SPEC_ISSUE-02 (§4.2 e CA-15 novo). Antigo: "o par `(object_type, grade)` mais frequente tem pelo menos `min_agree` quadros". Novo: as quatro condições do §4.2, com a 2: "não é `(unknown, None)`". A `stability` continua contando esse par, e um tipo conhecido sem grau continua emitindo. Evidência: §2 ("uma inspeção por peça"), §3.2 (`unknown` é a mesa vazia) e o exemplo do relatório, com `LIVE_MIN_AGREE=3` e `LIVE_EMPTY_FRAMES=10`, valores que o §4.6 aceita. Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão). E-3: `Blocked` por este `SPEC_ISSUE`. E-4 tipos 1 e 3: a regra de emissão passa a dizer o que o §2 e o §3.2 já pedem, e o CA-15 cobre só isso. X-5: nenhum comportamento novo, só retira uma emissão que contrariava o §2. X-6: nenhum CA sai. X-7: não toca regra inegociável. X-9: primeira correção do trecho. | SPEC_ISSUE-02 de `reviews/SPEC-019/r1-dev-report.md` | Orquestrador (loop da SPEC-019) |
| 2026-11-01 | Correção do SPEC_ISSUE-03 (§4.2 e CA-16 novo). Antigo: "o par `(object_type, grade)` mais frequente", sem regra de empate. Novo: condição 1 do §4.2, "é o único mais frequente: um empate no topo não é classificação estável, então não há `EMIT`, e a janela segue rolando". Evidência: "o mais frequente" não define um par quando dois empatam, e a escolha mudaria o veredito (`poor` é defeito, `fair` não, ADR-013). Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão). E-3: `Blocked` por este `SPEC_ISSUE`. E-4 tipos 1 e 3: a classificação "estável" do §2 exclui o empate, e o CA-16 cobre só isso. X-5: não há comportamento novo, porque o caso não tinha resultado definido. X-6: nenhum CA sai. X-7: a regra de defeito não muda. X-9: primeira correção do trecho. | SPEC_ISSUE-03 de `reviews/SPEC-019/r1-dev-report.md` | Orquestrador (loop da SPEC-019) |
| 2026-11-01 | Correção do SPEC_ISSUE-04 (§4.4, resposta 200, e CA-17 novo). Antigo: `"result": {"object_type", "grade", "type_confidence", "labels_pt": {...}} \| null`. Novo: `result` sempre objeto, com o resultado do quadro atual, sem o `\| null`; `labels_pt` com as chaves da captura; no `unknown`, `desconhecido`; `inspection` traz o quadro emitido, que pode ser outro. Evidência: toda resposta 200 passou pela inferência, e no CA-01 o quadro atual (`poor`) difere do emitido (`fair`). Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão). E-3: `Blocked` por este `SPEC_ISSUE`. E-4 tipos 1 e 3: esclarece um formato que não tinha regra. X-4: a resposta é da borda ao celular, fora do `qc-contracts`. X-5: nenhum campo novo. X-6: nenhum CA sai. X-7: o sufixo de provisório e o CA-13 não mudam. X-9: primeira correção do trecho. | SPEC_ISSUE-04 de `reviews/SPEC-019/r1-dev-report.md` | Orquestrador (loop da SPEC-019) |
| 2026-11-01 | Correção do SPEC_ISSUE-05 (§4.4 e CA-18 novo). Antigo: nada sobre a máquina de estados quando a gravação falha. Novo: "**Falha ao gravar no passo `EMIT`:** a resposta é a da captura (...), e a rota chama o `reset` da sessão. A próxima janela estável emite de novo, com `inspection_id` novo." Evidência: em `WAIT_REMOVAL`, a peça ficaria sem registro até ser retirada, contra o §2; `create_app` já responde 503 e apaga a foto (`edge/src/qc_edge/app.py:543-549`). Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão). E-3: `Blocked` por este `SPEC_ISSUE`. E-4 tipos 1 e 3: aplica o §2 ao caso de falha, com o `reset` já público, e o CA-18 cobre só isso. X-5: nenhuma assinatura ou rota nova. X-6: nenhum CA sai. X-7: se for lido como toque na R-05, a regra fica igual, porque a tentativa que falhou não gravou nada, e está coberto pela resposta 11 do ADR-024. X-9: primeira correção do trecho. | SPEC_ISSUE-05 de `reviews/SPEC-019/r1-dev-report.md` | Orquestrador (loop da SPEC-019) |
| 2026-11-01 | Correção do SPEC_ISSUE-06, atribuído pelo architect à primeira observação do relatório (§3.1, §4.5 e CA-10). §4.5, antigo: "HTML e JS em `edge/src/qc_edge/static/` (ADR-003), sem framework". Novo: HTML em `templates/live.html`, renderizado pela rota, JS em `static/live.js`, e os headers da `/capture` na resposta. CA-10, novo: headers, campo `lot_id` e `GET /static/live.html` → 404. Evidência: `static/` é servido sem token (`edge/src/qc_edge/app.py:404`), o que contraria "sem token válido → 401"; a `/capture` usa `templates/`; o ADR-003 só isola o JS em `static/`; e um arquivo estático não receberia o `LIVE_FPS` (§4.6). Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão), com a E-1 dependendo do adendo em `reviews/SPEC-019/r1-dev-report.md` que registra este ID; sem o adendo, exige humano. E-4 tipos 1 e 3: faz valer o 401 já pedido. X-5: o arquivo é o mesmo, em outra pasta. X-6: a autenticação fica mais estrita. X-7: não toca regra inegociável. X-9: primeira correção do trecho. | Observação do `reviews/SPEC-019/r1-dev-report.md` (`/static/live.html`) | Orquestrador (loop da SPEC-019) |
| 2026-11-01 | Correção do SPEC_ISSUE-07, atribuído pelo architect à decisão local 4 do relatório (§4.2). Antigo: "a janela guarda os últimos `window` resultados (com os bytes do quadro)" e "Os bytes dos quadros ficam só em memória e são descartados ao sair da janela, no `reset` e no fim da sessão." Novo: a janela só guarda os bytes dos quadros que podem ser emitidos, e `WAIT_REMOVAL` não os guarda. Evidência: com o SPEC_ISSUE-02, `unknown` nunca é emitido, e `WAIT_REMOVAL` não emite nada. Classificação ADR-019: elegível (E-1 a E-5 cumpridos; X-7 coberta pela resposta 11 do ADR-024), com a E-1 dependendo do adendo em `reviews/SPEC-019/r1-dev-report.md` que registra este ID; sem o adendo, exige humano. E-4 tipo 1: nenhum comportamento observável muda. X-5: nada novo. X-6: nenhum CA muda. X-7: o trecho protege quadros em memória (R-02, R-14), e a regra fica mais rígida, com menos imagens em memória. O reviewer e o portão de segurança conferem, e o orquestrador avisa o humano. X-9: primeira correção do trecho. | Decisão local 4 do `reviews/SPEC-019/r1-dev-report.md` | Orquestrador (loop da SPEC-019) |
| 2026-11-01 | Correção do SPEC_ISSUE-08, atribuído pelo architect às decisões locais 1 e 5 do relatório (§4.4 e CA-05). §4.4, antigo: "`image` (JPEG)" e "(o middleware de `Content-Length` da SPEC-007 cobre a rota)". Novo: "só JPEG, pelo conteúdo: PNG recebe 415" e "aplica esse limite a esta rota, e as outras continuam com `CAPTURE_MAX_REQUEST_BYTES`". CA-05, antigo: 6 casos. Novo: mais `Content-Length: 1310721` → 413 e PNG válido → 415. Evidência: o middleware só tem um limite global, de 3,5 MiB (`edge/src/qc_edge/app.py:400`), e o CA-05 passaria sem o limite de 1 310 720 bytes; o `load_image` aceita PNG. Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão), com a E-1 dependendo do adendo em `reviews/SPEC-019/r1-dev-report.md` que registra este ID; sem o adendo, exige humano. E-4 tipos 1 e 3. X-5: nenhuma variável ou rota nova; o limite já estava pedido. X-6: nenhum limite afrouxa, e nenhum caso sai. X-7: não toca regra inegociável. X-9: primeira correção do trecho. | Decisões locais 1 e 5 do `reviews/SPEC-019/r1-dev-report.md` | Orquestrador (loop da SPEC-019) |
| 2026-11-01 | Correção do SPEC_ISSUE-09, atribuído pelo architect à decisão local 2 do relatório (§4.3 e CA-08). CA-08, antigo: "*quando* o relógio da sessão avança 61 s sem quadro numa das duas primeiras, *então* o terceiro passa a receber 200". Novo: A em t = 0 s, B em t = 30 s e C em t = 31 s → 429; C em t = 61 s → 200. §4.3: a inatividade usa o `clock` do `create_app`. Evidência: com um relógio único, avançar 61 s venceria as duas sessões, e não "uma das duas". Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão), com a E-1 dependendo do adendo em `reviews/SPEC-019/r1-dev-report.md` que registra este ID; sem o adendo, exige humano. E-4 tipos 1 e 2: forma de verificação ajustada, com a mesma intenção. X-5: o `clock` já existe. X-6: os 60 s e o 429 não mudam. X-7: não toca regra inegociável. X-9: primeira correção do trecho. | Decisão local 2 do `reviews/SPEC-019/r1-dev-report.md` | Orquestrador (loop da SPEC-019) |
| 2026-11-01 | Correção do SPEC_ISSUE-10, atribuído pelo architect à decisão local 6 do relatório (§3.1, §4.4, CA-12 e CA-20 novo). §3.1, antigo: sem latência no console. Novo: "O console mostra a última latência por quadro e o p95 dos últimos 100 quadros (§4.4)", com a regra do p95 no §4.4 e o CA-20. Evidência: o CA-12, passo 6, e o §7 pedem a latência por quadro no console, e nada a mostra: a resposta da rota só a traz no `EMIT`, e o log de requisições inclui o envio pela rede, fora da RNF-02. Classificação ADR-019: exige humano (X-5: saída nova no console, com cálculo e CA próprios). A alternativa sem código novo é tirar o passo 6 do CA-12, mas ela enfraquece o CA (X-6) e também iria ao humano. | Decisão local 6 do `reviews/SPEC-019/r1-dev-report.md` | Orquestrador (loop da SPEC-019) |
| 2026-11-01 | Correção do SPEC_ISSUE-11, atribuído pelo architect à segunda observação do relatório (§8). Antigo: "`docs/architecture.md` §6.1 pelo architect". Novo: "§6.1 e §6.4 pelo architect". Evidência: o §6.4 lista as variáveis da borda, e faltarão `EDGE_TLS_*` e `LIVE_*`. Classificação ADR-019: exige humano (X-3: aponta uma mudança necessária em `docs/architecture.md`; a causa é o §4.6 já aprovado, e não esta correção, mas, na dúvida, a classificação é esta). | Observação do `reviews/SPEC-019/r1-dev-report.md` (`docs/architecture.md`) | Orquestrador (loop da SPEC-019) |
| 2026-11-01 | Correção do SPEC_ISSUE-12, com achados da conferência pedida pelo orquestrador, fora do relatório. (a) §4.4 e CA-19 novo: antigo, nada sobre `InferenceError`; novo, 500 `inference failed`, sem `feed`, como a SPEC-007 §4.5, passo 5. (b) §4.3: antigo, nada sobre concorrência; novo, `feed`, `reset` e sessões serializados por lock, porque os 2 slots de decodificação (SPEC-007 §4.6) permitem duas requisições simultâneas da mesma sessão, e isso poderia gerar dois `EMIT`, contra o §2. (c) §4.2: antigo, sem definição; novo, `LiveStep.state` é o estado depois do passo, e a janela de resultados continua rolando em `WAIT_REMOVAL`, como o "limpam a janela" já supunha. (d) §4.5: antigo, a página não tinha lote; novo, campo de lote, porque a rota exige `lot_id`. (e) §3.1, CA-09 e CA-14: antigo, "o console oferece também o QR do `/live`"; novo, só com o TLS ligado, porque sem ele a página não abre a câmera e o CA-14 pede o console como antes. (f) §4.1: antigo, "ilegível" sem definição; novo, o arquivo que não abre para leitura, com o PEM inválido falhando no `uvicorn`, como o CA-09 já supunha. (g) §7: antigo, "no pior caso (...) 40 MiB"; novo, 40 MiB com os padrões e 240 MiB nos tetos do §4.6. Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão), com a E-1 dependendo do adendo em `reviews/SPEC-019/r1-dev-report.md` que registra este ID e os itens (a) a (g); sem o adendo, exige humano. E-4 tipos 1 e 3: cada item esclarece um trecho, sem mudar o comportamento pedido, e o CA-19 cobre só o (a). X-5: nenhuma rota, variável ou arquivo novos. X-6: nenhum limite muda, e nenhum caso sai. X-7: não toca regra inegociável. X-9: primeira correção destes trechos. | Conferência do architect, a pedido do orquestrador ("confira se há outras contradições do mesmo tipo") | Orquestrador (loop da SPEC-019) |
| 2026-11-01 | Decisões locais 2 (relógio para trás), 3 (limpeza no `lifespan`) e 7 (`Host` sem porta com `EDGE_PORT=443` e TLS) do relatório aceitas como implementação, sem mudar requisito nem classificação. A 7 fica só para o `Host` de loopback na porta 443 com TLS, e o portão de segurança a confere contra a SPEC-025 §4.1. | `reviews/SPEC-019/r1-dev-report.md` | Orquestrador (loop da SPEC-019) |
| 2026-11-01 | Correção dos SPEC_ISSUE-01 a 09 aprovada pelo orquestrador sob o ADR-019 e, na 07, a resposta 11 do ADR-024 (commit do architect 77e3e12). | `reviews/SPEC-019/r1-dev-report.md` | Orquestrador (ADR-019) |
| 2026-11-01 | Correção dos SPEC_ISSUE-10, 11 e 12 reaprovada pelo humano (commit do architect 77e3e12). | Resposta do humano de 2026-11-01, nesta sessão | Orquestrador, a pedido do humano |
