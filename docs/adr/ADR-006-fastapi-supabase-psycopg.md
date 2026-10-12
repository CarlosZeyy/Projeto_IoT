# ADR-006: Usar FastAPI + Postgres do Supabase, acessado com psycopg 3 pelo pooler

| Campo | Valor |
|---|---|
| Status | Aceito |
| Data | 2026-10-12 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-002, ADR-007, ADR-008, ADR-010, SPEC-003, SPEC-004, SPEC-005, SPEC-006, SPEC-015, R-01, R-03, R-05, R-12 |

## Contexto

A nuvem precisa de:

- uma API REST que receba inspeções de forma **idempotente** (R-05), com lote de 1 a 100 itens atômico (422 e nada gravado se um item for inválido);
- leituras com filtros e agregações para métricas e SPC.

O banco precisa ser gerenciado, gratuito e sem cartão (R-01). O plano Free do Supabase oferece 500 MB de banco e 2 projetos ativos, e **pausa o projeto após 1 semana sem atividade**. Fonte: <https://supabase.com/pricing> (verificado em 2026-10-12).

O pooler do Supabase em **modo transaction** (Supavisor, porta 6543) **não suporta prepared statements**. Fonte: <https://supabase.com/docs/guides/database/connecting-to-postgres> (verificado em 2026-10-12).

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) FastAPI + psycopg 3 direto no Postgres do Supabase, via `DATABASE_URL` do pooler; RLS ligado sem políticas | SQL explícito, transações e `INSERT ... ON CONFLICT DO NOTHING RETURNING` para a idempotência; o lote é atômico numa transação; as chaves públicas do Supabase não leem nada | Gerenciar o pool e as migrações SQL à mão; atenção aos prepared statements no pooler |
| B FastAPI + `supabase-py` (API REST/PostgREST) | SDK pronto, sem string de conexão | Sem transação de vários comandos; upsert idempotente e agregações ficam limitados ou viram funções RPC; precisa da chave `service_role` no servidor |
| C SQLite no host da API | Zero dependência externa | O disco do Render free é efêmero: os dados se perdem a cada deploy ou hibernação (ADR-008) |
| D Neon (Postgres serverless) | Postgres gerenciado com plano gratuito | Limites e exigência de cartão não avaliados em profundidade (exige verificação); sem vantagem clara sobre o Supabase, que já era a escolha da v0 (D-06); fica como alternativa |

## Decisão

A API é **FastAPI** com endpoints **síncronos** (`def`), usando um `psycopg_pool.ConnectionPool` de psycopg 3 conectado ao Postgres do Supabase pela connection string do **pooler** em `DATABASE_URL`. O SDK `supabase-py` não é usado. O RLS fica **habilitado sem políticas** em `devices` e `inspections`.

## Consequências

- **Positivas:**
  - a idempotência e a atomicidade do lote ficam garantidas pelo próprio Postgres;
  - a chave `service_role` não é necessária no MVP;
  - um `SELECT 1` no `/health` também mantém o projeto ativo (ADR-008).
- **Negativas / custos aceitos:**
  - endpoints síncronos usam o threadpool do FastAPI, o que basta para a carga da demo;
  - as migrações são SQL puro e podem rodar de novo sem erro. São aplicadas pelo runner mínimo `infra/migrate.py` (stdlib + psycopg, com a tabela `schema_migrations`; ver SPEC-003) ou à mão (SQL Editor ou `psql`). Nada de Alembic ou ORM.
- **O que passa a ser obrigatório:**
  - `DATABASE_URL` só no ambiente do servidor da API, nunca no Git nem no dashboard (R-03);
  - conexões com `prepare_threshold=None` (prepared statements desligados) no modo transaction;
  - migrações aditivas em `infra/migrations/NNN_descricao.sql`, com RLS conferido após aplicar (SPEC-003);
  - a lógica de SPC é uma função pura em `qc_api.services.spc` (SPEC-006); o endpoint só consulta e serializa;
  - dois projetos Supabase (`partqc-dev` e `partqc-prod`), para não misturar dados (`docs/deployment-plan.md` §1).

## Quando revisitar

- Se o Supabase passar a exigir cartão no plano Free, ou reduzir o limite de 2 projetos ativos.
- Se o banco de produção passar de 400 MB (80% do limite).
- Se o pooler em modo transaction causar erros que não se resolvam com `prepare_threshold=None` (avaliar o modo session ou o Neon).
