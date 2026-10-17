# ADR-017: Limitar a carta p aos últimos lotes válidos, com a linha de base na história inteira

| Campo | Valor |
|---|---|
| Status | Aceito (aprovado pelo humano em 2026-10-17) |
| Data | 2026-10-17 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-013 (complementado, não substituído), ADR-007, ADR-008, SPEC-006, SPEC-013, SPEC-015, SPEC-017, SPEC-026, R-04, R-06 |

## Contexto

A rota `GET /api/v1/metrics/spc` (SPEC-006) devolve **um ponto por lote válido** e **um item de `excluded_lots` por lote pequeno**, sem limite. É a única rota de leitura sem teto: a listagem tem `limit ≤ 500` e a série temporal tem 5 000 buckets (SPEC-005).

O security-devops mediu o custo (SEC-06-01, severidade média, `reviews/SPEC-006/r1-security-report.md`), com 1 milhão de linhas num banco local:

| Cenário | Tempo | Corpo | Pico de memória do processo |
|---|---|---|---|
| 2 000 lotes de 500 (grande, realista) | 0,52 s | 393 KB | 67 MB |
| 200 000 lotes de 5 | 8,1 s | 34,6 MB | 405 MB |
| 1 000 000 de lotes de 1 (`min_lot_size=5`) | 19,5 s | 30,8 MB | 803 MB |

- O custo dominante está no processo Python (cerca de 1,7 KB por ponto e 0,8 KB por lote excluído), não no banco: no pior caso, a agregação no Postgres levou 5,0 s. Por isso, um `statement_timeout` (SEC-05-01, SPEC-015) não resolve o problema.
- O plano gratuito do Render tem **512 MB de RAM e 0,1 CPU** por web service (<https://render.com/docs/compute-plans>, tabela "Web service plans", linha `free`, verificado pelo architect em 2026-10-17). Com cerca de 550 000 lotes de 1 linha, que qualquer portador de uma chave de dispositivo consegue gravar em uns 5 500 `POST /batch`, a chamada **padrão** do dashboard passa de 512 MB. O processo é morto, e a ingestão cai junto, a cada visita ao painel.
- O volume real do projeto é de dezenas de lotes. O teto não pode mudar a carta nessa escala.

O ADR-013 define que `p̄` é calculado nos **primeiros** `baseline_lots` lotes válidos (fase I). Qualquer corte precisa dizer o que acontece com essa base.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) Mostrar os **últimos** `max_points` lotes válidos (parâmetro 2…500, padrão 100) e no máximo 50 lotes excluídos (os mais recentes), com os totais na resposta. A base de `p̄` continua nos primeiros `baseline_lots` lotes válidos da **história inteira**. O corte é feito no SQL | Memória e corpo limitados, qualquer que seja a história; a linha central não muda com o corte (o ADR-013 continua valendo); com até 100 lotes válidos, a resposta é a mesma de hoje; o dashboard mostra o mais recente, que é o que o supervisor acompanha | Precisa de 3 campos opcionais novos na resposta (contrato 0.3.0, R-04); os lotes da base podem ficar fora da janela mostrada |
| B Janela `from`/`to` (obrigatória ou com padrão), com a base de `p̄` dentro da janela | Combina com o filtro de período do dashboard | Não limita a contagem: uma janela de 7 dias pode ter 550 000 lotes; `p̄` muda conforme a janela, e a mesma peça pode estar "em controle" numa consulta e fora em outra |
| C 422 quando a história passa do teto, como o `MAX_BUCKETS` da série temporal | Sem campo novo; explícito | A carta padrão do dashboard quebra exatamente quando há mais dados; quem polui os dados derruba a página |
| D Paginar os pontos (`limit`/`offset`) | Acesso a toda a história | Uma carta de controle não é lida em páginas; continua precisando dos totais e de uma regra para a base |
| E Manter como está e só pôr `statement_timeout` (SPEC-015) | Nenhuma mudança de contrato | Não limita a memória do Python, que é o risco medido |

## Decisão

1. A rota `GET /api/v1/metrics/spc` ganha o parâmetro `max_points` (inteiro de 2 a 500, padrão 100). `points` traz só os **últimos** `max_points` lotes válidos, em ordem crescente de `(started_at, lot_id)`. Acima do teto, a rota **trunca** e responde 200. Nunca responde 422 por excesso de lotes.
2. `p̄` continua sendo calculado sobre os **primeiros** `baseline_lots` lotes válidos da história inteira da consulta (mesma `source` e mesmo `object_type`), mesmo quando eles ficam fora da janela. A regra do ADR-013 não muda.
3. `excluded_lots` traz no máximo os **50** lotes excluídos mais recentes (`MAX_EXCLUDED_LOTS`), em ordem crescente.
4. `SpcResponse` ganha 3 campos opcionais, com padrão `null`: `max_points` (o teto usado), `valid_lots_total` e `excluded_lots_total` (as contagens antes do corte). É uma mudança minor: `qc-contracts` vai para 0.3.0 (R-04, skill `contrato-api`).
5. O corte é feito **no SQL**, com uma única agregação por requisição e `order by ... limit`. O Python recebe no máximo `baseline_lots + max_points + 50` lotes e uma linha de totais.
6. A ordem das partes usa `lot_id collate "C"` nos desempates, que é a ordem de `str` do Python para os caracteres de `LOT_ID_PATTERN`.

## Consequências

- **Positivas:**
  - memória e corpo da rota ficam limitados (cerca de 650 lotes no pior caso), qualquer que seja o volume gravado;
  - com até 100 lotes válidos e até 50 excluídos, os valores são idênticos aos de hoje, e os CAs da SPEC-006 continuam valendo;
  - a linha central é estável: mudar `max_points` não muda `p̄` nem os limites de nenhum ponto.
- **Negativas / custos aceitos:**
  - a agregação no banco continua linear no número de linhas da origem (5 s no pior caso local). Isso fica coberto pelo `statement_timeout` da SPEC-015;
  - os lotes da base podem não aparecer na carta quando a história tem mais de `max_points` lotes. O dashboard avisa quando há corte;
  - o contrato muda (0.3.0), com ajustes autorizados em testes de aceite de SPECs anteriores (SPEC-026 §3.1).
- **O que passa a ser obrigatório:**
  - a SPEC-026 implementa esta decisão e precisa estar `Done` **antes de a SPEC-013 entrar em `In Dev`**. Por consequência, também antes do deploy (SPEC-015);
  - o dashboard (SPEC-013) envia `max_points`, mostra quando a carta foi cortada (`valid_lots_total > len(points)`) e trata os 3 campos como opcionais;
  - os alertas (SPEC-017) usam a mesma seleção limitada e nunca recalculam a história inteira em Python;
  - uma SPEC que adicione tipos ao `ObjectType` (Fase 2, SPEC-016) diz se eles entram na carta.

## Quando revisitar

- Se a dupla ou o professor pedir uma carta de um período específico (por exemplo, "só a sessão de hoje"): a janela `from`/`to` volta à mesa, com uma regra explícita para a base de `p̄`.
- Se uma sessão real passar de 500 lotes, ou se o dashboard precisar de mais de 50 excluídos.
- Se o projeto adotar as regras de Western Electric 2 a 4 (sequências), que podem precisar de lotes anteriores à janela.
- Se o Render mudar a memória do plano gratuito.
