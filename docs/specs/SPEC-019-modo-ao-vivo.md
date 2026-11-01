# SPEC-019: Fase 3 — modo vídeo ao vivo (HTTPS na LAN)

| Campo | Valor |
|---|---|
| Status | In Dev |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-008, SPEC-025, SPEC-030, SPEC-041 (e SPEC-007, SPEC-009, SPEC-024). Sem mudança de contrato |
| Semana alvo | Logo depois da SPEC-041 (`041 → 019`). O portão da Fase 3 (M3, 22/11) deixa de bloquear esta SPEC (ADR-024, decisão 5; `docs/plan.md` §4, 2026-11-01) |
| Requisitos cobertos | PRD §4.3; RNF-02, RNF-05; R-02, R-03, R-06, R-14 |
| ADRs relevantes | ADR-003 (opção B, prevista para a Fase 3), ADR-002, ADR-004, ADR-009, ADR-024 |

> **Aprovada pelo humano em 2026-10-24** (PR #45), no pacote das Fases 2 e 3, com os ADRs 021 e 022 `Aceito`. Revista pelo architect em 2026-10-24 e em 2026-11-01 (ver o Histórico).
>
> **Reaprovada pelo humano em 2026-11-01** ("Sim, codar agora"): o teste do certificado passa a ser depois do merge. Ver o Histórico.

## 1. Contexto

O MVP usa foto por disparo (`<input capture>`, N-09, ADR-003), que funciona em HTTP na LAN. O vídeo contínuo exige `getUserMedia`, que o navegador só libera em **contexto seguro** (HTTPS ou `localhost`) (<https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia>, citado no ADR-003). Túnel público é proibido (R-02, `docs/architecture.md` §8). Resta o HTTPS local com uma CA própria (`mkcert`, licença BSD-3-Clause, <https://github.com/FiloSottile/mkcert>, consultado pelo architect em 2026-10-24). Segundo o README do mkcert, nos celulares é preciso instalar o `rootCA.pem`: no iOS, como perfil e com "confiança total" ativada; no Android, o README só fala de apps em modo de desenvolvimento, e o architect não encontrou fonte oficial que confirme se o Chrome do Android confia numa CA instalada pelo usuário. Por isso o teste nos dois celulares é um passo humano, feito **depois do merge** (§3.3): a implementação não espera por ele e assume o risco descrito lá.

A ideia original (`docs/archive/ideia-original.md`) previa a máquina de estados `IDLE → DETECTING → EMIT → WAIT_REMOVAL`.

## 2. Objetivo

Na página `/live`, servida por HTTPS na LAN, o celular mostra o vídeo da câmera traseira com o resultado sobreposto e registra **uma** inspeção por peça quando a classificação fica estável, pelo mesmo caminho da foto (decisão, outbox e `captures/`).

## 3. Escopo

### 3.1 Dentro

- HTTPS opcional da borda: `EDGE_TLS_CERT` e `EDGE_TLS_KEY` (§4.1).
- `edge/src/qc_edge/live.py`: `LiveStateMachine` e `LiveSessions` (§4.2 e §4.3).
- Rota `POST /api/live/frame` e página `GET /live?t=<token>` (`edge/src/qc_edge/static/live.html` e `live.js`) (§4.4 e §4.5).
- Console: o QR code e o link usam `https://` quando o TLS está ligado, e o console oferece também o QR do `/live`.
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

- `EDGE_TLS_CERT` e `EDGE_TLS_KEY`: caminhos de arquivos PEM. Os dois vazios (padrão) = HTTP, como hoje. Só um preenchido, arquivo inexistente ou ilegível, ou a chave com permissão de leitura para grupo ou outros (`mode & 0o077 != 0`) → erro na subida com código 2 e uma mensagem que cita a variável, sem o conteúdo do arquivo.
- Com os dois, o uvicorn sobe com `ssl_certfile` e `ssl_keyfile`. O console continua só para loopback (SPEC-025), agora em `https://127.0.0.1:<porta>`.
- O `edge/README.md` manda guardar o certificado e a chave em `edge/data/tls/` (já ignorado pelo Git), com a chave em `0600`. A chave nunca entra no repositório (R-03).

### 4.2 Máquina de estados (`LiveStateMachine`)

```python
class LiveStateMachine:
    def __init__(self, window: int = 10, min_agree: int = 8, min_confidence: float = 0.80,
                 empty_frames: int = 3) -> None
    def feed(self, result: DecisionResult, frame: bytes, inspected_at: datetime) -> LiveStep
    def reset(self) -> None
# LiveStep: state ("IDLE" | "DETECTING" | "EMIT" | "WAIT_REMOVAL"), stability (0..1),
#           emit: (DecisionResult, bytes, datetime) | None
```

- `IDLE`: um resultado com tipo diferente de `unknown` passa a `DETECTING` e entra na janela.
- `DETECTING`: a janela guarda os últimos `window` resultados (com os bytes do quadro). Quando ela está cheia, o par `(object_type, grade)` mais frequente tem pelo menos `min_agree` quadros e a média de `type_confidence` desses quadros é `>= min_confidence`, o passo é `EMIT`: `emit` traz o quadro **mais recente** desse par, e o estado seguinte é `WAIT_REMOVAL`. `empty_frames` resultados `unknown` seguidos voltam a `IDLE` e limpam a janela.
- `WAIT_REMOVAL`: nada é emitido; `empty_frames` resultados `unknown` seguidos voltam a `IDLE` e limpam a janela.
- `stability` = quadros do par mais frequente / `window` (0 em `IDLE`).
- Os bytes dos quadros ficam só em memória e são descartados ao sair da janela, no `reset` e no fim da sessão.

### 4.3 Sessões (`LiveSessions`)

- Uma sessão por identificador `session` enviado pela página (`re.fullmatch(r"[A-Za-z0-9_-]{16,64}", valor)`), gerado no navegador com `crypto.getRandomValues`.
- No máximo `LIVE_MAX_SESSIONS` sessões (padrão 4). Uma sessão sem quadro há mais de 60 s é descartada. Com o máximo atingido, uma sessão nova recebe 429 `{"detail": "too many live sessions"}`.
- Trocar o `lot_id` dentro da sessão chama `reset`.

### 4.4 Rota `POST /api/live/frame`

- `multipart/form-data`: `image` (JPEG), `lot_id`, `session`; header `X-Session-Token`. Ordem dos erros igual à da `/api/capture` (SPEC-007 §4.1): token (401) → tamanho (413) → campos (422) → limitador de decodificações (503 `server busy`, SPEC-007 §4.6, compartilhado com a captura) → imagem (415) → modelo (503 `model not loaded`) → sessões (429).
- Limites próprios: `image` ≤ `LIVE_MAX_BYTES` = 1 048 576 bytes; requisição ≤ `LIVE_MAX_REQUEST_BYTES` = 1 310 720 bytes (o middleware de `Content-Length` da SPEC-007 cobre a rota); ≤ `LIVE_MAX_PIXELS` = 1 000 000 pixels, conferidos pelo cabeçalho antes de decodificar; depois, as regras do `qc_preprocess.load_image`.
- Infere sem criar inspeção. No passo `EMIT`, cria **uma** inspeção pelo mesmo caminho da `/api/capture` no modo `inspect` (decisão, `InspectionCreate` com o `source` da SPEC-041 §4.7, ou seja, `simulated` para um modelo provisório e `live` para os outros, `inspection_id` novo, o quadro emitido salvo em `captures/AAAA-MM-DD/<inspection_id>.jpg`, `sink.put` antes de responder), com o `inspected_at` e a latência do quadro emitido.
- Resposta 200: `{"state", "stability", "result": {"object_type", "grade", "type_confidence", "labels_pt": {...}} | null, "inspection": <InspectionCreate em JSON> | null}`. `inspection` só no passo `EMIT`.
- Com um modelo provisório, `result.labels_pt.verdict` recebe o mesmo sufixo ` (modelo provisório)` da captura (SPEC-041 §4.7), para o overlay também avisar.
- Com `--stub-model`, a rota funciona e o sink é o `InMemorySink` (nada vai para a nuvem, R-06).

### 4.5 Página `/live`

- `GET /live?t=<token>`: sem token válido → 401, como a `/capture`. HTML e JS em `edge/src/qc_edge/static/` (ADR-003), sem framework.
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

Contexto comum: resultados de decisão montados pelo teste (`DecisionResult` da SPEC-008); borda com o modelo dummy da SPEC-008 e um sink em memória nos CAs de rota; JPEGs gerados com Pillow.

- **CA-01 (emissão)** — *Dado* uma `LiveStateMachine` padrão, *quando* recebe 10 resultados com 8 `screw/fair` (confiança de tipo média 0,85) e 2 `screw/poor`, nesta ordem: 1 `poor`, 8 `fair`, 1 `poor`, *então* exatamente o 10º passo é `EMIT`, `emit` traz o 9º quadro (o `fair` mais recente) e o estado seguinte é `WAIT_REMOVAL`.
- **CA-02 (sem emissão)** — *Dado* 10 resultados com só 7 iguais, ou 8 iguais com confiança média 0,79, *quando* processados, *então* nenhum passo é `EMIT`.
- **CA-03 (remoção)** — *Dado* o estado `WAIT_REMOVAL` do CA-01, *quando* chegam mais 20 resultados `screw/fair` com confiança 0,9, *então* nenhum `EMIT`; *quando* chegam então 2 resultados `unknown` e 1 `screw/fair`, *então* o estado continua `WAIT_REMOVAL`; e 3 `unknown` seguidos levam a `IDLE`, depois do que 10 resultados `nut/good` com confiança 0,9 geram um novo `EMIT`.
- **CA-04 (troca de lote)** — *Dado* uma sessão com 9 quadros `screw/fair` na janela, *quando* o próximo quadro chega com outro `lot_id`, *então* a janela recomeça: com quadros `screw/fair` de confiança 0,9 no lote novo, o primeiro `EMIT` acontece no 10º quadro contado a partir da troca (inclusive), e não antes.
- **CA-05 (rota, erros)** — *Dado* a borda, *quando* `POST /api/live/frame` é chamado, em casos separados, sem token, com `image` de 1 048 577 bytes, com `session="curto"`, com `lot_id="lote 1"`, com um GIF e com um JPEG de 1001×1000 px, *então* as respostas são, respectivamente, 401, 413, 422, 422, 415 e 415, e o modelo dummy não é chamado em nenhum caso.
- **CA-06 (rota, uma inspeção por peça)** — *Dado* o modelo dummy configurado para devolver `screw/fair` com confiança 0,9, *quando* a mesma sessão envia 30 quadros válidos, *então* exatamente uma resposta tem `inspection` não nulo, o sink tem uma inspeção, `captures/` tem um arquivo `<inspection_id>.jpg`, e o `inspection_id` da resposta é o do sink.
- **CA-07 (R-02)** — *Dado* o CA-06 com o sink sendo o outbox SQLite, *quando* o `payload` gravado é lido, *então* ele valida como `InspectionCreate` e não tem nenhum campo com bytes de imagem; e o número de arquivos em `captures/` é igual ao número de inspeções emitidas.
- **CA-08 (sessões)** — *Dado* `LIVE_MAX_SESSIONS=2`, *quando* três identificadores de sessão diferentes enviam quadros válidos, *então* o terceiro recebe 429; *quando* o relógio da sessão avança 61 s sem quadro numa das duas primeiras, *então* o terceiro passa a receber 200.
- **CA-09 (TLS, configuração)** — *Dado* `EDGE_TLS_CERT` preenchido e `EDGE_TLS_KEY` vazio, ou a chave com modo `0o644`, ou um caminho inexistente, *quando* a borda sobe, *então* sai com código 2 e a mensagem cita a variável; *dado* dois arquivos existentes em `tmp_path` (o conteúdo não é conferido na configuração), com a chave em `0o600`, *então* os argumentos do uvicorn montados pela borda têm `ssl_certfile` e `ssl_keyfile` com esses caminhos, e a URL do QR do console começa com `https://`.
- **CA-10 (página)** — *Dado* `GET /live` sem token, *então* 401; com token, *então* 200 com `text/html`, e o HTML referencia `live.js`; e o arquivo `live.js` contém `isSecureContext`, `getUserMedia` e `facingMode`.
- **CA-11 (configuração)** — *Dado* `LIVE_WINDOW=2`, `LIVE_MIN_AGREE=11` (com `LIVE_WINDOW=10`), `LIVE_MIN_CONFIDENCE=1.2` ou `LIVE_MAX_SESSIONS=0`, *quando* a borda sobe, *então* sai com código 2.
- **CA-12 (manual, dupla)** — 1. Gerar o certificado com `mkcert` para o IP da LAN, `127.0.0.1` e `localhost`, e configurar `EDGE_TLS_CERT`/`EDGE_TLS_KEY`; 2. instalar a CA nos dois celulares (passo 1 do §3.3); 3. abrir `/live` pelo QR do console e conceder a câmera; 4. inspecionar 5 peças seguidas, tirando cada uma da mesa entre elas; 5. conferir 5 inspeções na nuvem (ou no console, sem nuvem) e 5 arquivos em `captures/`; 6. registrar a latência por quadro observada no console. Pode ser feito com o modelo provisório (SPEC-041), com as inspeções `simulated` e a latência só como indicativo.
- **CA-13 (R-06, modelo provisório)** — *Dado* o modelo dummy num diretório `partqc-mnv3-provisional-v1`, devolvendo `screw/fair` com confiança 0,9, *quando* a mesma sessão envia 30 quadros válidos, *então* a resposta com `inspection` não nulo tem `inspection.source = "simulated"`, o sink guarda `source = simulated` e `result.labels_pt.verdict` termina em ` (modelo provisório)`. *Dado* o mesmo modelo em `partqc-mnv3-v1`, *então* `inspection.source = "live"`, sem sufixo.
- **CA-14 (foto por disparo sem TLS)** — *Dado* `EDGE_TLS_CERT` e `EDGE_TLS_KEY` vazios, *quando* a borda sobe, *então* os argumentos do uvicorn não têm `ssl_certfile` nem `ssl_keyfile`, a URL do QR do console começa com `http://`, e `POST /api/capture` no modo `inspect` com o token válido responde 200 e grava uma inspeção no sink, como antes desta SPEC.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Máquina de estados (cada transição, janela, estabilidade); sessões e expiração; rota (ordem dos erros, limites, emissão); TLS e configuração | `edge/tests/` |
| Aceite (tester) | Um por CA automatizado | `edge/tests/acceptance/test_spec_019.py` |
| Manual (dupla), depois do merge | §3.3, passo 1, e CA-12 | descritos acima |

## 7. Riscos e notas para o implementador

- **Limitador compartilhado:** a 2 fps por sessão, o vídeo disputa os 2 slots de decodificação com a captura (SPEC-007 §4.6). O 503 `server busy` faz a página descartar o quadro, e o operador da foto vê "Borda ocupada"; é aceitável para a demo.
- **Memória:** no pior caso, `LIVE_MAX_SESSIONS × LIVE_WINDOW × LIVE_MAX_BYTES` = 4 × 10 × 1 MiB = 40 MiB de quadros em memória.
- **Latência:** cada quadro passa pela inferência; a RNF-02 (p95 ≤ 300 ms) vale por quadro e é medida no CA-12.
- **Argumentos do uvicorn:** isole a montagem deles numa função pura, para o CA-09 conferir sem subir o servidor nem gerar certificado. Nenhuma dependência nova.

## 8. Definição de pronto

- [ ] Todos os CAs automatizados com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED e security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `edge/README.md` e `.env.example` atualizados; `docs/architecture.md` §6.1 pelo architect
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
