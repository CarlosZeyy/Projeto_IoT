# ADR-013: Usar carta p por lote do operador, com defeito = `poor` + `unusable`

| Campo | Valor |
|---|---|
| Status | Aceito |
| Data | 2026-10-12 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-001, ADR-005, ADR-007, SPEC-002, SPEC-006, SPEC-013, SPEC-014, SPEC-017, R-06, N-06 |

## Contexto

O SPC é a principal entrega de Indústria 4.0 do projeto (RF-10). É preciso definir:

- o que é "defeituoso" numa escala de 5 graus (ADR-001);
- qual carta usar;
- o que é o subgrupo.

A v0 usava lotes fixos de 50 inspeções consecutivas, o que não corresponde a nenhum lote físico. Na demo e no uso real, o operador inspeciona grupos de tamanhos diferentes (um pote de peças, uma caixa). Com pouca coleta, alguns lotes serão pequenos. Objetos `unknown` não têm grau.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) Carta **p** com subgrupo = `lot_id` informado pelo operador, `n` variável e limites por lote; defeito = `poor` + `unusable` | Lote com sentido físico (rastreabilidade); aceita `n` variável; defeito alinhado à rubrica (perda de função ou corrosão severa) | Limites "em degraus" mais difíceis de ler; depende de o operador informar o lote corretamente |
| B Lotes fixos de 50 inspeções consecutivas (v0) | `n` constante; simples | O lote não corresponde a nada físico; a demo precisaria de 50 peças por ponto |
| C Carta **np** | Leitura direta em contagem | Exige `n` constante, o que os lotes do operador não garantem |
| D Carta X̄ do `grade_score` | Usa a informação ordinal inteira | Assume uma escala intervalar que o grau não tem; depende da calibração do modelo; pode entrar depois como gráfico secundário |
| E Defeito = só `unusable` | Critério inequívoco | Taxa muito baixa: com lotes pequenos, p̄ ≈ 0 e a carta fica sem sinal |
| F Defeito = `fair` ou pior | Mais sensível | Reprova peças funcionais com oxidação superficial; foge da rubrica |

## Decisão

A regra de defeito é `is_defective(grade) = grade in {poor, unusable}`, implementada uma única vez em `qc_contracts`. O SPC é uma **carta p** com:

- **subgrupo** = `lot_id`, com os lotes ordenados pelo menor `inspected_at`;
- **lotes excluídos** com `n < min_lot_size` (padrão 5);
- **p̄** calculado nos primeiros `baseline_lots` lotes válidos (padrão 20; com menos, usa todos);
- **limites por lote**: `p̄ ± 3·√(p̄(1−p̄)/nᵢ)`, com LCL truncado em 0;
- **regra 1 apenas** no MVP (ponto fora dos limites);
- `unknown` fora do cálculo, e `source = live` por padrão.

A fórmula completa está em `docs/architecture.md` §3.4.

## Consequências

- **Positivas:**
  - a carta reflete os lotes reais da demo;
  - o simulador (SPEC-014) gera lotes fora de controle verificáveis;
  - a regra de defeito é a mesma no banco (coluna gerada `is_defective`), na API e no dashboard.
- **Negativas / custos aceitos:**
  - os lotes da linha de base são avaliados contra a linha central que eles próprios definem (fase I), e com menos de 20 lotes isso vale para todos. É aceito para a demo;
  - as regras de Western Electric 2 a 4 ficam de fora no MVP.
- **O que passa a ser obrigatório:**
  - `compute_p_chart(lots, baseline_lots, min_lot_size)` é uma função pura com testes unitários (SPEC-006);
  - com menos de 2 lotes válidos, a resposta é `points = []` e `p_bar = null`, com `message`;
  - os dados `simulated` só entram no SPC por filtro explícito e aparecem identificados (R-06);
  - o `lot_id` é obrigatório na captura (`^[A-Za-z0-9_-]{1,40}$`);
  - mudar a regra de defeito exige ADR e aumento da versão do contrato (R-04).

## Quando revisitar

- Se, na demo interna da S4, os lotes reais tiverem mediana de `n` abaixo de 5: rever `min_lot_size` (N-06).
- Se o professor pedir as regras de Western Electric ou uma carta para variável contínua.
- Se a taxa de defeito real da coleta ficar abaixo de 2%, o que deixaria a carta sem sinal: rever a definição de defeito.
