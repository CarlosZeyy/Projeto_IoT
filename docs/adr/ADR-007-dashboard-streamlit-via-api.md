# ADR-007: Fazer o dashboard em Streamlit + Plotly, lendo os dados só pela API

| Campo | Valor |
|---|---|
| Status | Aceito |
| Data | 2026-10-12 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-003, ADR-006, ADR-008, ADR-012, ADR-013, SPEC-005, SPEC-006, SPEC-013, SPEC-015, R-03, R-06, R-12, N-10 |

## Contexto

O supervisor precisa ver:

- totais e a distribuição dos 5 graus;
- a taxa de defeito e a série temporal;
- a carta p por lote;
- o histórico paginado e a página "Sobre o modelo";
- o selo de dados simulados (RF-09 a RF-13, R-06).

A matéria é de Python, e a dupla quer o mínimo de JavaScript: o único HTML/JS do projeto é a página de captura do celular (ADR-003). O dashboard precisa ser hospedado de graça (ADR-008) e não pode depender de torch nem onnxruntime (R-12).

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) Streamlit + Plotly, lendo tudo pela `qc-api` com `READ_API_KEY` | Só Python; gráficos interativos; hospedagem gratuita no Streamlit Community Cloud; a regra de negócio (métricas, SPC, `is_defective`) fica num único lugar, a API | Uma chamada HTTP a mais por tela; cold start da API somado ao do dashboard; layout menos flexível |
| B React/Next.js | Interface rica e rápida | Muito JavaScript e outro build; foge do foco em Python; outra hospedagem |
| C Streamlit lendo o Postgres direto | Menos latência; sem endpoints de leitura | `DATABASE_URL` em mais um lugar (R-03); SPC e métricas duplicados em SQL no dashboard; o RLS sem políticas exigiria uma credencial privilegiada no dashboard |
| D Grafana | Painéis prontos; alertas | Mais um serviço para hospedar e configurar; carta p com limites variáveis por lote é difícil de montar; foge do Python |

## Decisão

O dashboard é um app **Streamlit** com gráficos **Plotly**. Ele lê os dados **somente** pelos endpoints de leitura da `qc-api`, enviando `READ_API_KEY` no header `X-API-Key`. O layout é livre dentro da SPEC-013 (N-10).

## Consequências

- **Positivas:**
  - o SPC e as métricas são calculados uma vez só, na API (SPEC-005, SPEC-006), e testados lá;
  - o dashboard não tem nenhuma credencial de banco;
  - CORS fica fechado, porque o Streamlit chama a API pelo servidor, não pelo navegador.
- **Negativas / custos aceitos:**
  - a primeira tela após a hibernação pode levar cerca de 1 min (Render) mais o despertar do Streamlit; o checklist da demo acorda os dois antes (`docs/deployment-plan.md` §5);
  - a `READ_API_KEY` é compartilhada entre a API e o dashboard e só dá leitura.
- **O que passa a ser obrigatório:**
  - `qc-dashboard` depende só de streamlit, plotly, pandas, httpx e `qc-contracts` (para os rótulos PT-BR, ADR-012); não depende de psycopg, torch nem onnxruntime (R-12);
  - `API_BASE_URL` e `READ_API_KEY` ficam em Streamlit → Secrets, nunca no Git (R-03);
  - o selo "simulado" fica visível sempre que houver `source=simulated` no filtro, e o SPC usa `live` por padrão (R-06, ADR-013).

## Quando revisitar

- Se o Streamlit Community Cloud não conseguir instalar a dependência local `packages/contracts` e o fallback da SPEC-015 também falhar.
- Se o professor recusar o uso de HTML/JS ou exigir um front-end específico (pergunta 2 de `docs/professor-questions.md`).
- Se uma tela do dashboard levar mais de 5 s com a API já acordada.
