# SPEC-003: Schema Supabase, migrações e RLS

| Campo | Valor |
|---|---|
| Status | Ready |
| Rodada atual | — |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-002 |
| Semana alvo | S2 |
| Requisitos cobertos | RF-06 (chave de idempotência), RF-15 (tabela de dispositivos), RNF-06 (RLS), R-04, R-05, R-06 |
| ADRs relevantes | ADR-006 (FastAPI + Supabase + psycopg), ADR-013 (regra de defeito), ADR-008 (Supabase free) |

## 1. Contexto

`docs/architecture.md` §5 define as tabelas `devices` e `inspections`, a coluna gerada `is_defective`, os índices e o RLS sem políticas. Esta SPEC transforma esse desenho na primeira migração e cria um executor mínimo de migrações, usado localmente, nos testes (Postgres 16 de teste da SPEC-001) e na publicação (SPEC-015). As rotas que usam o banco são das SPECs 004–006.

## 2. Objetivo

`infra/migrate.py` aplica `infra/migrations/001_init.sql` a um Postgres 16 vazio, registra a aplicação, é idempotente, e o schema resultante rejeita dados fora do contrato `qc_contracts` (0.1.0; o teto de `latency_ms` da 0.2.0, SPEC-023, coincide com o limite do tipo `integer`), com RLS ligado e sem políticas.

## 3. Escopo

### 3.1 Dentro

- `infra/migrations/001_init.sql`.
- `infra/migrate.py` (CLI + funções importáveis).
- Fixtures de banco compartilhadas no `conftest.py` da raiz: `db_conninfo`, `migrated_db` e `clean_db` (4.4).
- No `pyproject.toml` da raiz: `infra/tests` em `testpaths` e `pythonpath = ["infra"]` em `[tool.pytest.ini_options]`.
- Testes em `infra/tests/`.

### 3.2 Fora

- Rotas, pool de conexões e autenticação (SPEC-004); consultas de leitura (SPEC-005/006).
- Script de registro de dispositivo (SPEC-004).
- Aplicação no Supabase de produção e atualização do `docs/deployment-plan.md` (SPEC-015).
- Tabelas da Fase 2 (heartbeat, SPEC-018).

## 4. Requisitos detalhados

### 4.1 `001_init.sql`

- Implementa `architecture.md` §5 com as definições abaixo; o arquivo **não** contém `BEGIN`/`COMMIT` (a transação é do executor).
- **Decisão: DDL idempotente** (`create table if not exists`, `create index if not exists`; `enable row level security` já é idempotente). Justificativa: o ADR-006 mantém a aplicação manual pelo SQL Editor ou `psql` como caminho válido; com DDL idempotente, uma reaplicação acidental ou a mistura dos dois caminhos (manual e depois `migrate.py`) não quebra nada. O risco de mascarar um schema divergente é mitigado pelos CAs, que verificam o schema completo num banco vazio, e pelo checksum do executor (4.2).
- `devices`: `device_id text primary key` com `check (device_id ~ '^[a-z0-9-]{3,32}$')`; `api_key_hash text not null unique` com `check (api_key_hash ~ '^[0-9a-f]{64}$')`; `created_at timestamptz not null default now()`; `last_seen_at timestamptz` (nulo até a primeira escrita).
- `inspections`: colunas e tipos de §5; `device_id` com `references devices(device_id) on delete restrict`; `received_at default now()`; coluna gerada `is_defective boolean generated always as (coalesce(grade in ('poor','unusable'), false)) stored`.
- Restrições **nomeadas** de `inspections` (os testes as consultam pelo nome):

  | Nome | Expressão |
  |---|---|
  | `inspections_object_type_check` | `object_type in ('screw','nut','unknown')` |
  | `inspections_grade_check` | `grade in ('perfect','good','fair','poor','unusable')` |
  | `inspections_source_check` | `source in ('live','simulated')` |
  | `inspections_grade_null_iff_unknown` | `(object_type = 'unknown') = (grade is null)` |
  | `inspections_grade_fields_null_together` | `(grade is null) = (grade_score is null) and (grade is null) = (grade_confidence is null)` |
  | `inspections_ranges_check` | `type_confidence between 0 and 1`, `grade_confidence between 0 and 1`, `grade_score between 0 and 4`, `latency_ms >= 0` |
  | `inspections_formats_check` | `lot_id ~ '^[A-Za-z0-9_-]{1,40}$'` e `model_sha256 ~ '^[0-9a-f]{64}$'` |

  As cinco últimas são **complementares** a §5 (defesa em profundidade, espelhando os validadores do contrato); não mudam o contrato.
- **Teto de `latency_ms`:** a coluna continua `integer` (§5), com `latency_ms >= 0` em `inspections_ranges_check` e **sem** limite superior no `check`. O próprio tipo já rejeita valores acima de 2 147 483 647 (SQLSTATE `22003`, `numeric_value_out_of_range`, antes de qualquer `check`), e esse é exatamente o teto do contrato 0.2.0 (`qc_contracts.MAX_LATENCY_MS`, SPEC-023). Um `check` com o mesmo limite seria inalcançável. O CA-23 fixa o limite por teste, e a SPEC-004 garante que a API responde 422 antes de chegar ao banco.
- Índices: `inspections_inspected_at_idx (inspected_at)`, `inspections_lot_id_idx (lot_id)`, `inspections_source_inspected_at_idx (source, inspected_at)`, `inspections_device_id_idx (device_id)`.
- `alter table devices enable row level security;` e o mesmo em `inspections`. **Nenhuma** política. **Sem** `force row level security`: o dono das tabelas (usuário da `DATABASE_URL` da API) continua lendo e escrevendo.

### 4.2 `infra/migrate.py`

- Funções públicas:
  - `apply_migrations(conninfo: str, migrations_dir: Path = DEFAULT_DIR) -> list[str]` — aplica as pendentes em ordem e retorna as versões aplicadas nesta execução (ex.: `["001"]`; `[]` se nada pendente);
  - `pending_migrations(conninfo: str, migrations_dir: Path = DEFAULT_DIR) -> list[str]`.
- Arquivos: `NNN_slug.sql` com a regex `^\d{3}_[a-z0-9_]+\.sql$`, ordenados pelo número. Arquivo `.sql` fora do padrão ou número repetido → erro antes de aplicar qualquer coisa.
- Tabela de controle `schema_migrations(version text primary key, filename text not null, checksum text not null, applied_at timestamptz not null default now())`, criada pelo executor se não existir, com RLS ligado e sem políticas.
- Cada migração roda numa transação própria junto com o `insert` em `schema_migrations`; erro → `rollback` da migração inteira, nada registrado, as seguintes não são aplicadas.
- Checksum = SHA-256 do conteúdo do arquivo. Migração já aplicada cujo arquivo mudou → erro `checksum mismatch for <versão>` e nada é aplicado.
- Execuções concorrentes são serializadas com `pg_advisory_lock` (chave constante).
- Conexões psycopg com `prepare_threshold=None` (compatível com o pooler em modo transaction, ADR-006).
- CLI: `uv run --package qc-api python infra/migrate.py [--database-url URL] [--migrations-dir DIR] [--status]`. A URL padrão vem de `DATABASE_URL`. Códigos de saída: `0` sucesso; `1` falha de banco, de migração ou de checksum; `2` uso inválido (sem URL, argumento inválido). `--status` lista aplicadas e pendentes sem aplicar nada.
- Saída via `logging` (INFO: versões aplicadas). **Nunca** escreve a URL nem a senha em log ou mensagem de erro (R-03): erros de conexão mostram só o tipo da exceção e host/porta.

### 4.3 Requisitos de segurança

- Nenhuma credencial no SQL ou no script. `TEST_DATABASE_URL` e `DATABASE_URL` vêm do ambiente.
- SQL do executor sem interpolação de strings além do conteúdo dos próprios arquivos de migração.

### 4.4 Fixtures de teste (`conftest.py` da raiz)

- `db_conninfo` (sessão): lê `TEST_DATABASE_URL` (marcador `db`, política da SPEC-001). **Trava de segurança:** se o nome do banco na URL não contiver `test`, o teste falha com `refusing to use a database whose name does not contain 'test'`.
- `migrated_db` (sessão): `drop schema public cascade; create schema public;`, depois `apply_migrations`; retorna a conninfo.
- `clean_db` (função): `truncate inspections, devices` antes de cada teste que o usa.
- As SPECs 004–006 reutilizam essas fixtures.

## 5. Critérios de aceite

Todos os CAs abaixo são testes marcados `db`, contra o Postgres 16 de teste. "Linha válida" = linha de `inspections` com `device_id='edge-01'` (registrado em `devices`), `object_type='screw'`, `grade='fair'`, `grade_score=2.1`, `type_confidence=0.97`, `grade_confidence=0.66`, `latency_ms=120`, `source='live'` e demais campos válidos.

- **CA-01** — Dado um schema `public` vazio, quando `apply_migrations(conninfo)` roda, então retorna `["001"]`, as tabelas `devices`, `inspections` e `schema_migrations` existem e `schema_migrations` tem uma linha com `version='001'` e `checksum` igual ao SHA-256 do arquivo.
- **CA-02** — Dado o banco do CA-01, quando `apply_migrations` roda de novo, então retorna `[]` e `schema_migrations` continua com 1 linha.
- **CA-03** — Dado o banco do CA-01, quando o conteúdo de `001_init.sql` é executado de novo diretamente (simulando o SQL Editor), então não há erro e o schema não muda (mesmo conjunto de colunas, restrições e índices).
- **CA-04** — Dado o banco migrado, quando se consulta `information_schema`/`pg_indexes`, então existem os 4 índices de 4.1 e as colunas de `inspections` têm os tipos de `architecture.md` §5 (`uuid`, `text`, `timestamptz`, `real`, `boolean`, `integer`).
- **CA-05** — Dado o banco migrado, quando se leem os literais das restrições `inspections_object_type_check`, `inspections_grade_check` e `inspections_source_check` (via `pg_get_constraintdef`), então os conjuntos de valores são **iguais** a `{m.value for m in ObjectType}`, `{m.value for m in Grade}` e `{m.value for m in Source}` de `qc_contracts` (guarda contra deriva do contrato).
- **CA-06** — Dado o banco migrado, quando se insere uma linha válida com `object_type` = `'bolt'`, ou `grade` = `'bad'`, ou `source` = `'test'`, então cada `insert` falha com `CheckViolation` (SQLSTATE `23514`).
- **CA-07** — Dado o banco migrado, quando se insere uma linha com `object_type='unknown'` e `grade='fair'`, ou com `object_type='screw'` e `grade`, `grade_score` e `grade_confidence` nulos, então cada `insert` falha com `CheckViolation`; e com `object_type='unknown'` e os três campos nulos, o `insert` funciona.
- **CA-08** — Dado o banco migrado, quando se insere uma linha válida com `grade_score=null` (mantendo `grade='fair'`), ou `type_confidence=1.5`, ou `grade_score=4.5`, ou `latency_ms=-1`, ou `model_sha256` com 63 caracteres, ou `lot_id='L 001'`, então cada `insert` falha com `CheckViolation`.
- **CA-09** — Dado o banco migrado, quando se insere uma linha para cada membro de `Grade` (com `object_type='screw'`) e uma com `object_type='unknown'` e `grade` nulo, então, para todas as 6 linhas, o valor lido de `is_defective` é igual a `qc_contracts.is_defective(grade)` (iterando o enum, não uma lista fixa).
- **CA-10** — Dado o banco migrado, quando um `insert` informa `is_defective` explicitamente, então falha (coluna gerada).
- **CA-11** — Dado uma linha com `inspection_id = X` já gravada, quando se insere outra com o mesmo `X`, então falha com `UniqueViolation`; e `insert ... on conflict (inspection_id) do nothing returning inspection_id` não retorna linha e o total continua 1 (R-05).
- **CA-12** — Dado o banco migrado, quando se insere uma inspeção com `device_id='ghost-01'` (inexistente em `devices`), então falha com `ForeignKeyViolation`; e `delete from devices where device_id='edge-01'` com inspeções associadas falha com `ForeignKeyViolation`.
- **CA-13** — Dado o banco migrado, quando se insere em `devices` com `device_id='Edge_01'`, ou `api_key_hash` com 10 caracteres, ou um `api_key_hash` já usado por outro dispositivo, então cada `insert` falha (`CheckViolation` ou `UniqueViolation`); `created_at` é preenchido e `last_seen_at` é nulo num `insert` válido.
- **CA-14** — Dado o banco migrado, quando se consulta `pg_class.relrowsecurity` de `devices`, `inspections` e `schema_migrations`, então os três valem `true`, `relforcerowsecurity` vale `false` e `pg_policies` não tem nenhuma linha para essas tabelas.
- **CA-15** — Dado 3 inspeções gravadas e um papel `partqc_rls_probe` (`NOLOGIN NOSUPERUSER NOBYPASSRLS`) com `USAGE` no schema e `SELECT, INSERT` nas duas tabelas, quando, numa transação com `SET LOCAL ROLE partqc_rls_probe`, ele executa `select count(*) from inspections` e `select count(*) from devices`, então ambos retornam `0`; e um `insert` em `inspections` falha com SQLSTATE `42501` (violação de RLS). O papel é removido no fim do teste.
- **CA-16** — Dado um diretório temporário com `001_init.sql` (cópia) e `002_broken.sql` contendo `create table t_ok(id int); select from nao_existe;`, quando `apply_migrations` roda num schema vazio, então levanta erro, `schema_migrations` contém só `001` e a tabela `t_ok` **não** existe.
- **CA-17** — Dado o banco migrado com a cópia de `001_init.sql` num diretório temporário, quando o arquivo é alterado (um comentário acrescentado) e `apply_migrations` roda de novo, então levanta erro contendo `checksum mismatch for 001`.
- **CA-18** — Dado um diretório temporário com `001_init.sql` e um arquivo `abc.sql`, quando `apply_migrations` roda, então levanta erro antes de aplicar qualquer migração (`schema_migrations` não existe ou está vazia).
- **CA-19** — Dado `DATABASE_URL` ausente e sem `--database-url`, quando se roda `python infra/migrate.py`, então o código de saída é `2` e a mensagem cita `DATABASE_URL`.
- **CA-20** — Dado `--database-url postgresql://u:s3cr3t-pw@127.0.0.1:1/x` (porta fechada), quando se roda o CLI, então o código de saída é `1` e nem o stdout nem o stderr contêm `s3cr3t-pw` (R-03).
- **CA-21** — Dado o banco do CA-01, quando se roda o CLI com `--status`, então o código de saída é `0`, a saída lista `001` como aplicada e `pending_migrations` retorna `[]`.
- **CA-22** — Dado `TEST_DATABASE_URL` apontando para um banco chamado `partqc_prod`, quando um teste usa `db_conninfo`, então o teste falha com a mensagem da trava de segurança e nenhum comando é executado no banco.
- **CA-23** — Dado o banco migrado, quando se insere uma linha válida com `latency_ms=2147483647`, então o `insert` funciona e o valor lido é `2147483647`; e quando se insere uma linha válida com `latency_ms=2147483648` (passado como parâmetro do psycopg), então o `insert` falha com `NumericValueOutOfRange` (SQLSTATE `22003`) e a tabela não ganha a linha. (O teste usa os literais; a igualdade com `qc_contracts.MAX_LATENCY_MS` é verificada na API pela SPEC-004.)

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Ordenação e validação de nomes de arquivo (sem banco); aplicação, idempotência, rollback, checksum, restrições, coluna gerada, RLS (com banco) | `infra/tests/` |
| Aceite (tester) | Um teste por CA, marcados `db` | `infra/tests/acceptance/test_spec_003.py` |

Banco: Postgres 16 local (Docker, SPEC-001) ou o serviço do CI. Sem mocks de banco. Os testes de CLI usam `subprocess` com `sys.executable`.

## 7. Riscos e notas para o implementador

- No Supabase, os papéis `anon` e `authenticated` recebem `GRANT` nas tabelas do `public` por padrão; é o RLS sem políticas que os bloqueia (CA-15 reproduz isso localmente).
- `create role` é global no cluster: crie o papel de teste com nome fixo, de forma tolerante a execuções anteriores interrompidas, e remova-o (`drop owned by` + `drop role`) no fim.
- Colunas `real` (float4) arredondam valores (ex.: `0.97` vira `0.9700000286`); compare com tolerância nos testes que leem esses campos.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED e security-report PASS
- [ ] CI verde (com os testes `db` executados, não pulados); `ruff` limpo
- [ ] `README.md` ("Como rodar") com o comando de migração local
- [ ] PR aberto com os relatórios; merge humano

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-12 | Acrescentados a nota "Teto de `latency_ms`" em §4.1 e o CA-23 (2 147 483 647 aceito; 2 147 483 648 → SQLSTATE `22003`). O texto do Objetivo agora cita a versão 0.2.0 do contrato. O `check` não muda, nenhum outro CA muda, e a SPEC não passa a depender da SPEC-023, porque o CA-23 usa literais. SPEC marcada como "Aguardando reaprovação humana"; o Status fica com o humano/orquestrador. | SPEC_ISSUE-02 (RV-03) de `reviews/SPEC-002/r1-review-report.md`: lacuna entre o contrato (`latency_ms` sem teto) e a coluna `integer`; resolvida no contrato pela SPEC-023 | Orquestrador, a pedido do humano |
| 2026-10-12 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
