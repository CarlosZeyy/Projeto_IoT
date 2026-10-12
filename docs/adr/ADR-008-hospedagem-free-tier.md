# ADR-008: Hospedar em free tier sem cartão: Render (API), Supabase (banco) e Streamlit Community Cloud (dashboard)

| Campo | Valor |
|---|---|
| Status | Aceito |
| Data | 2026-10-12 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-002, ADR-006, ADR-007, ADR-009, SPEC-009, SPEC-015, R-01, R-03, N-05 |

## Contexto

R-01 proíbe qualquer serviço que exija cartão de crédito. A nuvem precisa de três peças: a API (`qc-api`, sem ML, R-12), o Postgres e o dashboard. Os limites de free tier mudam com frequência, por isso o `docs/deployment-plan.md` registra a data de cada verificação. Todos os fatos abaixo foram verificados em 2026-10-12:

| Serviço | Limites relevantes | Fonte |
|---|---|---|
| Render (web service free) | Dorme após 15 min sem tráfego; acorda em cerca de 1 min; 750 horas de instância por mês | <https://render.com/docs/free> |
| Koyeb (Hobby) | 1 web service, 512 MB, 0,1 vCPU, dorme após 1 h, sem cartão | <https://www.koyeb.com/pricing> |
| Supabase (Free) | 500 MB, 2 projetos ativos, pausa após 1 semana sem atividade | <https://supabase.com/pricing> |
| Streamlit Community Cloud | Dorme após 12 h sem tráfego; repositório privado exige permissão extra no GitHub | <https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app> |
| Fly.io | Sem plano gratuito: período de teste e depois cartão | <https://docs.fly.io/about/pricing> |
| Oracle Cloud Free Tier | "most users need a mobile phone number and a credit card to create an account" | <https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm> |

O Google Cloud Run (Free Tier do Google Cloud) exige uma conta de faturamento, e quem é novo a obtém pelo Free Trial, que pede "a credit card or other payment method". Fonte: <https://docs.cloud.google.com/free/docs/free-cloud-features> (verificado em 2026-10-12).

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) Render (API) + Supabase (banco) + Streamlit CC (dashboard), com Koyeb como reserva da API | Tudo sem cartão; deploy a partir do GitHub; blueprint `render.yaml` | Hibernação nos três; cold start de cerca de 1 min na API; pausa do banco após 1 semana parado |
| B Koyeb como principal | Dorme só após 1 h | Só 0,1 vCPU; apenas 1 serviço; fica como reserva |
| C Fly.io, Cloud Run ou Oracle Always Free | Sem hibernação (Oracle) ou mais recursos | Exigem cartão no cadastro ou para a cobrança (violam R-01) |
| D API no próprio notebook, exposta por túnel | Sem hibernação | Não é nuvem (enfraquece a frente Cloud); depende do notebook ligado; acesso remoto instável |

## Decisão

A API roda num **web service free do Render**, o banco no **Supabase Free** e o dashboard no **Streamlit Community Cloud**, com o **Koyeb Hobby** como reserva da API (N-05). Um workflow do GitHub Actions chama `GET /api/v1/health` **a cada 3 dias**; esse endpoint faz `SELECT 1`, o que impede a pausa do Supabase. O cold start da API é absorvido pelo **outbox** da borda (SPEC-009).

## Consequências

- **Positivas:** custo R$ 0; a borda não depende de a nuvem estar acordada para inspecionar (RF-07, RNF-10).
- **Negativas / custos aceitos:**
  - a primeira chamada após 15 min parada demora cerca de 1 min (timeout de 5 s no publisher → backoff e reenvio);
  - o keep-alive de 3 dias não evita a hibernação do Render; só evita a pausa do banco;
  - os limites podem mudar sem aviso durante o semestre.
- **O que passa a ser obrigatório:**
  - todo serviço ou dependência nova é conferido contra o `docs/deployment-plan.md`, com fonte e data (R-01);
  - `.github/workflows/keepalive.yml` com `KEEPALIVE_URL` em GitHub Secrets (SPEC-015);
  - a API sobe só com `uv sync --package qc-api --frozen --no-dev` (sem ML, R-12);
  - o checklist pré-demo acorda a API, o banco e o dashboard 30 min antes (`docs/deployment-plan.md` §5).

## Quando revisitar

- Se qualquer um dos serviços passar a exigir cartão (R-01): trocar para a reserva (Koyeb) ou para outro sem cartão, com ADR novo.
- Se o deploy no Render falhar por falta de memória.
- Se o Supabase for pausado apesar do keep-alive.
- Se as 750 h/mês forem atingidas antes da apresentação.
