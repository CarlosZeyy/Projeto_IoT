# SPEC-019 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-019](../../docs/specs/SPEC-019-modo-ao-vivo.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-019-modo-ao-vivo` |
| Commits | só o deste relatório; nenhum código |

## Resumo

**Implementação não iniciada: parada por `SPEC_ISSUE`, como manda a instrução da rodada.** Li a SPEC inteira, os ADRs citados, as SPECs de que ela depende nos pontos que cita e o código da borda, antes de escrever qualquer código. Encontrei 5 pontos em que a SPEC não diz o que implementar, ou cita algo que não existe. Registrei todos de uma vez, para o architect corrigi-los numa só passada. Nenhum arquivo de produção ou de teste foi alterado.

## Rastreabilidade (critério de aceite → implementação)

Não se aplica nesta entrega: nenhum CA foi implementado.

## SPEC_ISSUE

A classificação pelo ADR-019 é do architect. As correções sugeridas são só sugestões.

### SPEC_ISSUE-01: `DecisionResult` não existe

- **Onde:** §4.2 (assinatura de `feed` e campo `emit`) e o contexto comum do §5, que diz "`DecisionResult` da SPEC-008".
- **Evidência:** o nome só aparece nesta SPEC (busca em `docs/`, `edge/`, `packages/` e `reviews/`). A SPEC-008 define `Decision`, em `edge/src/qc_edge/decision.py:91`, sem `latency_ms`. O que o inferenciador devolve é `InferenceResult`, da SPEC-007, em `edge/src/qc_edge/inference.py:50`, com `latency_ms`.
- **Por que importa:** o §4.4 cria a inspeção "com o `inspected_at` e a latência do quadro emitido", e o `emit` só traz `(resultado, bytes, datetime)`. Com `Decision`, a latência não chega à inspeção. O tester também precisa saber qual tipo montar nos CAs 01 a 04.
- **Correção sugerida:** trocar `DecisionResult` por `InferenceResult` (`qc_edge.inference`, SPEC-007) no §4.2 e no §5.

### SPEC_ISSUE-02: o par `(unknown, None)` pode gerar `EMIT`?

- **Onde:** §4.2, estado `DETECTING`.
- **Lacuna:** a regra de `EMIT` vale para "o par mais frequente" da janela, e a janela guarda todos os resultados, sem excluir `unknown`. Só que `unknown` é a mesa vazia (§3.2), e o objetivo é uma inspeção por peça (§2).
- **Alcance:** com os padrões, não acontece: sem 3 `unknown` seguidos, cabem no máximo 7 em 10, abaixo de `min_agree = 8`. Com valores permitidos pelo §4.6, acontece. Exemplo: `LIVE_MIN_AGREE=3` e `LIVE_EMPTY_FRAMES=10`, com um quadro de peça seguido de 9 `unknown` da classe `other` com confiança alta. Ao pé da letra, isso grava uma inspeção da mesa vazia.
- **Correção sugerida:** `(unknown, None)` nunca emite, mas continua contando para a `stability`.

### SPEC_ISSUE-03: empate no par mais frequente

- **Onde:** §4.2, estado `DETECTING`.
- **Lacuna:** com `LIVE_MIN_AGREE` até a metade da janela, o que o §4.6 permite, dois pares podem empatar. Exemplo: janela de 10, `min_agree = 5`, 5 `screw/fair` e 5 `screw/poor`, ambos com confiança suficiente.
- **Por que importa:** a escolha decide o grau gravado, e aqui também o veredito, porque `poor` é defeito e `fair` não (ADR-013).
- **Correção sugerida:** empate não é classificação estável, então não há `EMIT`, e a janela segue rolando.

### SPEC_ISSUE-04: quando `result` é `null` na resposta 200?

- **Onde:** §4.4, resposta 200, que tipa `result` como objeto `| null`.
- **Lacuna:** para `inspection`, a SPEC diz quando vem preenchido ("só no passo `EMIT`"). Para `result`, não há regra. Toda resposta 200 passa pela inferência, então sempre existe um resultado. As leituras possíveis são "nunca é nulo" e "é nulo no `unknown`" (mesa vazia). Elas mudam o overlay (§4.5) e o que o tester pode verificar.
- **Correção sugerida:** `result` é sempre objeto na resposta 200, sem o `| null`. No `unknown`, o overlay mostra `desconhecido`.

### SPEC_ISSUE-05: falha ao gravar a inspeção no passo `EMIT`

- **Onde:** §4.2 ("o estado seguinte é `WAIT_REMOVAL`") e §4.4 ("mesmo caminho da `/api/capture`", que responde 503 `failed to persist inspection` e apaga a foto).
- **Lacuna:** a SPEC não diz o que acontece com a máquina de estados nessa falha. Se ela seguir para `WAIT_REMOVAL`, a peça continua na mesa e nunca é registrada, a menos que o operador a retire e a recoloque. Isso contraria o §2.
- **Correção sugerida:** a falha chama `reset`, e a próxima janela estável emite de novo. Como a primeira tentativa não gravou nada, continua havendo uma inspeção por peça. A resposta é o mesmo 503.

## Decisões locais previstas para a implementação

Nada aqui pede correção na SPEC. Estão listadas para o architect apontar, nesta mesma passada, o que ele considerar `SPEC_ISSUE`.

1. **Só JPEG na rota:** PNG recebe 415. O §4.4 diz `image` (JPEG), e a janela guarda bytes, não a imagem decodificada de que a captura precisa para reencodar um PNG.
2. **Relógio das sessões (CA-08):** o `clock` que o `create_app` já recebe. Se o relógio voltar para trás, a contagem de inatividade recomeça daquele instante, para uma sessão parada não ocupar vaga por tempo indefinido.
3. **Sessão parada sem nenhum tráfego:** além da limpeza a cada quadro, uma tarefa curta no `lifespan` descarta as sessões vencidas e, no desligamento, todas. Assim, os quadros de um celular que fechou a página não ficam na memória até a próxima requisição (§4.2 e §4.3).
4. **Quadros sem uso:** os bytes dos quadros `unknown` e os do estado `WAIT_REMOVAL` não são guardados, porque nunca são emitidos. A `stability` continua sendo calculada sobre a janela de resultados.
5. **Limites por rota:** o `BodySizeLimitMiddleware` passa a aceitar um limite por caminho, para aplicar `LIVE_MAX_REQUEST_BYTES` só em `/api/live/frame`.
6. **Latência no console (CA-12, passo 6):** uma linha no console com a última latência por quadro e o p95 dos últimos 100 quadros. O §3.1 não lista isso, mas o passo 6 pede a latência "observada no console", e a resposta da rota não a traz fora do `EMIT`.
7. **`EDGE_PORT=443` com TLS:** o `Host` do console passa a ser aceito sem porta, como já acontece na porta 80 sem TLS.

## Observações para o architect

- **`/static/live.html`:** o §3.1 e o §4.5 põem o HTML em `static/`, e esse diretório é servido sem token (SPEC-007). Esse caminho responderá 200 sem token, enquanto `GET /live` responde 401. A página não contém segredo, e a rota de quadros exige o token. A SPEC-019 tem a tag `security`, então vale citar isso ao `security-devops`.
- **`docs/architecture.md`:** o §8 da SPEC cita só o §6.1, mas o §6.4 também lista as variáveis da borda, e faltarão `EDGE_TLS_*` e `LIVE_*`.

## Checagens do autor

- [ ] `uv run ruff check .` e `uv run ruff format --check .`: não rodados, porque nenhum código mudou
- [ ] Testes unitários do autor: não escritos nem rodados
- [ ] `.env.example`: não alterado, porque a implementação não começou
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim

## SPEC_ISSUE levantados na correção (orquestrador)

Encontrados pelo architect ao avaliar as decisões locais e as observações deste relatório, a pedido do orquestrador. O texto antigo, o novo e a evidência de cada um estão no Histórico da SPEC.

- **SPEC_ISSUE-06:** página do `/live` em `static/`, respondendo sem token.
- **SPEC_ISSUE-07:** janela guardava bytes de quadros que nunca seriam gravados (R-14).
- **SPEC_ISSUE-08:** formato e limite de corpo da rota de quadros.
- **SPEC_ISSUE-09:** o CA-08 não conseguia exercitar a janela de cada sessão.
- **SPEC_ISSUE-10:** o CA-12 pedia latência no console, fora do §3.1.
- **SPEC_ISSUE-11:** a Definição de pronto citava só o §6.1 da `architecture.md`.
- **SPEC_ISSUE-12:** erro de inferência, trava por sessão, estado em `WAIT_REMOVAL`, lote, QR do `/live` e textos.
