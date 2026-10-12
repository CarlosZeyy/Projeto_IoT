# SPEC-019: Fase 3 — modo vídeo ao vivo (HTTPS)

| Campo | Valor |
|---|---|
| Status | Draft |
| Rodada atual | — |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-008 (e SPEC-007, SPEC-009) |
| Semana alvo | S8 (só se a Fase 2 fechar no prazo) |
| Requisitos cobertos | PRD §4.3; RNF-02, RNF-05 |
| ADRs relevantes | ADR-003, ADR-002, ADR-009 |

> **Rascunho.** Precisa de refinamento do `architect`, de decisão humana sobre o HTTPS (§6) e de aprovação humana antes de virar `Ready`.

## 1. Contexto

O MVP usa foto por disparo (`<input capture>`, N-09, ADR-003), que funciona em HTTP na LAN. Um modo de vídeo contínuo exige `getUserMedia`, que o navegador só libera em **contexto seguro** (HTTPS ou `localhost`). A ideia original (`docs/archive/ideia-original.md`) previa a máquina de estados `IDLE → DETECTING → EMIT → WAIT_REMOVAL`.

## 2. Objetivo

Na página `/live`, o celular mostra o vídeo da câmera traseira com o resultado sobreposto e registra **uma** inspeção por peça quando a classificação fica estável.

## 3. Escopo

### 3.1 Dentro

- Página `/live?t=<token>` em `edge/src/qc_edge/static/`: `getUserMedia({video: {facingMode: "environment"}})`, captura de quadros a 2 fps (JPEG, lado maior 640 px), overlay em `<canvas>` com rótulo PT-BR, confiança, estado e barra de estabilidade.
- Rota `POST /api/live/frame` (token de sessão): infere sem criar inspeção e devolve o resultado e o estado.
- `edge/src/qc_edge/live.py`: máquina de estados por sessão.
- HTTPS na LAN: instruções e configuração (`EDGE_TLS_CERT`, `EDGE_TLS_KEY`).

### 3.2 Fora

- Gravação de vídeo; envio de quadros para a nuvem (proibido, R-02); detecção com caixas (PRD §4.4).

## 4. Requisitos-chave (preliminares)

- **Estados:** `IDLE` → (quadro com tipo ≠ `unknown`) → `DETECTING` → (regra de estabilidade) → `EMIT` → `WAIT_REMOVAL` → (3 quadros seguidos `unknown`/`other`, ou seja, mesa vazia) → `IDLE`.
- **Estabilidade:** nos últimos N = 10 quadros, o mesmo `(object_type, grade)` em ≥ 80% (≥ 8) **e** confiança média de tipo ≥ `LIVE_MIN_CONFIDENCE` (padrão 0,80). No `EMIT`, cria **uma** inspeção pelo mesmo caminho da foto (decisão, outbox, `inspection_id` novo) e salva só aquele quadro em `captures/`.
- Os outros quadros ficam só em memória e são descartados. Trocar o lote zera a janela.
- Latência: cada quadro dentro da RNF-02 (p95 ≤ 300 ms); se a fila acumular, a página descarta quadros em vez de enfileirar.
- **HTTPS:**
  - **(a) mkcert:** CA local instalada nos dois celulares, certificado para o IP da LAN; os dados não saem da rede;
  - túnel público (ex.: `cloudflared`) é **proibido**: os quadros passariam pela infraestrutura do provedor e violariam a R-02 (decisão de 2026-10-12, `architecture.md` §8).

## 5. Critérios de aceite (preliminares)

- **CA-01 (preliminar)** — *Dado* uma sequência de 10 resultados com 8 `screw/fair` (confiança média 0,85) e 2 `screw/poor`, *quando* alimentada na máquina de estados, *então* ocorre exatamente 1 `EMIT` com `screw/fair` e 1 inspeção no outbox.
- **CA-02 (preliminar)** — *Dado* 7 de 10 quadros iguais, ou confiança média 0,79, *quando* processados, *então* nenhum `EMIT` ocorre.
- **CA-03 (preliminar)** — *Dado* o estado `WAIT_REMOVAL`, *quando* chegam mais 20 quadros da mesma peça, *então* nenhuma inspeção nova é criada; após 3 quadros `unknown`, o estado volta a `IDLE`.
- **CA-04 (preliminar)** — *Dado* `POST /api/live/frame` sem token válido, *quando* chamado, *então* a resposta é 401; com imagem > 2 MB ou que não é imagem, 413/422.
- **CA-05 (preliminar, R-02)** — *Dado* 100 quadros processados, *quando* `captures/` e o outbox são inspecionados, *então* há no máximo tantas imagens quantas inspeções emitidas, e nenhum payload do publisher contém bytes de imagem.
- **CA-06 (manual)** — 1. Gerar o certificado com mkcert para o IP da LAN; 2. instalar a CA nos dois celulares; 3. abrir `/live` e conceder a câmera; 4. inspecionar 5 peças seguidas; 5. conferir 5 inspeções na nuvem.

## 6. Perguntas em aberto

1. ~~Túnel × R-02~~ **Resolvido em 2026-10-12:** túnel público é proibido. HTTPS só com mkcert (CA local).
2. A instalação de CA de usuário funciona nos navegadores dos dois celulares da dupla? (Testar antes de implementar.)
3. A classe `other` cobre bem a "mesa vazia" para a detecção de remoção, ou é preciso uma classe `empty`?
4. 2 fps é suficiente para a demo? Ajustar N e o limiar de 80% depois de um teste?
