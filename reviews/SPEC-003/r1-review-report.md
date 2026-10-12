# SPEC-003 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-003](../../docs/specs/SPEC-003-schema-banco.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `main...dfdc56a`. Código da SPEC: `31d984c..dfdc56a`. Os commits `9bdd894`, `0f21199`, `c531b19` e `d89f99b` são revisões de SPECs (architect) e marcações de status (orchestrator); deles, só a separação de papéis foi conferida. |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Motivo do veredicto: os 23 CAs estão implementados e cada um tem um teste de aceite que o exercita de verdade contra o Postgres 16. Não há achado bloqueante nem alto. O único achado médio (RV-01) é um defeito da própria SPEC, que manda usar `pg_advisory_lock` de sessão e ao mesmo tempo ser compatível com o pooler em modo transaction. O developer seguiu o texto da SPEC. O achado fica registrado como SPEC_ISSUE-01 e precisa ser resolvido antes da SPEC-015 (aplicação em produção), não nesta SPEC.

Reprodução feita pelo reviewer (somente leitura):

- `uv run ruff check .`: "All checks passed!". `uv run ruff format --check .`: "51 files already formatted".
- `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q`: **957 passed**.
- `env -u TEST_DATABASE_URL -u CI uv run pytest -q`: **773 passed, 184 skipped** (todos `db`).
- Sonda própria: `load_migrations` num diretório com `١٢٣_x.sql` (dígitos arábico-índicos) aceita o arquivo com `version='١٢٣'` (RV-03). `conninfo_to_dict` resolve `postgresql://h/partqc_test?dbname=prod` como `prod`, então a trava do `db_conninfo` olha o nome efetivo que o libpq vai usar, e não o texto do caminho da URL.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | média (SPEC_ISSUE-01) | `infra/migrate.py:240`, `infra/migrate.py:249-250`; SPEC-003 §4.2; `docs/deployment-plan.md:48-50` | O lock é `pg_advisory_lock` **de sessão**, pego num comando em autocommit. Pelo pooler do Supabase em modo transaction (Supavisor, porta 6543), cada transação pode cair num backend diferente. O lock fica preso no backend A, que volta ao pool ainda com ele, e o `pg_advisory_unlock` do `finally` pode rodar no backend B: retorna `false` com um WARNING e não libera nada. Uma execução seguinte, num backend diferente de A, fica bloqueada em `pg_advisory_lock` **sem prazo**, porque não há `lock_timeout` nem `statement_timeout`. O `.env.example` e o `deployment-plan.md` (passo 2) mandam rodar `migrate.py` com a `DATABASE_URL`, que é a URL do pooler em modo transaction. O código cumpre a SPEC ao pé da letra; o problema é a SPEC exigir lock de sessão e compatibilidade com o modo transaction ao mesmo tempo. Nada disso aparece nos testes, que usam conexão direta. | Decisão do architect (SPEC_ISSUE-01), antes da SPEC-015. Opções: (a) documentar que as migrações rodam pela conexão direta ou pelo pooler em **modo session** (porta 5432), e nunca pela 6543, ajustando o `deployment-plan.md`; ou (b) trocar por `pg_advisory_xact_lock` dentro da transação de cada migração, refazendo o plano depois de pegar o lock. Nos dois casos, convém um `lock_timeout` (ou `pg_try_advisory_lock` com tentativas), para que um lock preso vire erro com código 1 e não um travamento. |
| RV-02 | baixa | `infra/migrate.py:212-226` | O T-01 do test-report foi confirmado pela leitura do código. Um `commit;` (ou `begin;`/`rollback;`) dentro de um arquivo de migração encerra a transação do executor. O que veio antes do `commit` fica gravado, a migração não é registrada e a mensagem diz "failed and was rolled back", o que é falso. A §4.1 proíbe controle de transação no arquivo, então isso é uso fora do contrato. Não bloqueia. | Numa SPEC futura: recusar, antes de aplicar, arquivos com controle de transação no nível do comando (o teste `test_extra_sql_file_has_no_transaction_control_force_or_policies` já tem a heurística), ou comparar `txid_current()` antes e depois de executar o arquivo e, se mudar, falhar com uma mensagem honesta. |
| RV-03 | baixa | `infra/migrate.py:48` | `re.compile(r"^\d{3}_...")` sem `re.ASCII`: em Python, `\d` aceita qualquer dígito Unicode. `١٢٣_x.sql` passa, e a versão gravada em `schema_migrations` vira `'١٢٣'`. A regex é a da SPEC, e o risco prático é mínimo. | Usar `[0-9]{3}` ou `re.ASCII`, que é o que a SPEC claramente quer dizer. Acrescentar um caso ao `test_invalid_sql_filename_rejected`. |
| RV-04 | baixa | `infra/migrate.py:105-106`, `:135`, `:91-95`, `:213` | O arquivo é lido duas vezes: em `load_migrations`, para o checksum, e em `_apply_one`, para executar. Se ele mudar entre as duas leituras, o checksum gravado não corresponde ao SQL executado, e na execução seguinte não aparece nenhum `checksum mismatch`. A janela é pequena, mas o objetivo do checksum é justamente essa garantia. | Ler os bytes uma única vez em `load_migrations`, guardar o conteúdo no `Migration` e calcular o checksum desses mesmos bytes. |
| RV-05 | baixa (SPEC_ISSUE-02) | `infra/migrations/001_init.sql:21` | `inspections.device_id` é `not null` (decisão 1 do dev-report). O `architecture.md` §5 escreve só `device_id text fk→devices`. A decisão é coerente com o Objetivo da SPEC (rejeitar o que está fora do contrato, em que `device_id` é obrigatório), é fácil de desfazer e está registrada com justificativa. Mesmo assim, o documento de arquitetura e o schema real ficam diferentes. | O architect ratifica a decisão e acrescenta `not null` ao `device_id` em `architecture.md` §5. Também pode acrescentar o `unique` de `api_key_hash`, que a SPEC já exige e o §5 não mostra. Não exige mudança de código. |

### Avaliação das interpretações do test-report

- **CA-22 ("o teste falha"): aceita.** No pytest, um `pytest.fail` dentro de fixture é sempre reportado como `error` de setup. Não há como uma fixture produzir `failed`. O que o CA exige de fato é que o teste não passe, que a mensagem da trava apareça e que **nenhum comando chegue ao banco**, e o teste do tester comprova isso com força: subprocesso do pytest, listener TCP que conta conexões (0 aceitas, com controle positivo de 1 conexão para um nome com `test`), código de saída diferente de 0, `1 error` e nenhum `passed`. Ele também cobre o caminho perigoso, `clean_db → migrated_db → db_conninfo`, que é o que faria `drop schema public cascade`. Como a SPEC só admite essa leitura no pytest, não abro SPEC_ISSUE. Numa próxima revisão da SPEC, o architect pode escrever "falha no setup (error)".
- **CA-21 ("lista 001 como aplicada"): aceita.** A SPEC não fixa o formato. A saída real é `INFO 001 applied 001_init.sql` e `INFO 1 applied, 0 pending`. O teste exige uma linha com `001` e `applied`, nenhuma linha com `001` e `pending`, exit 0 e `pending_migrations(...) == []`. Isso falharia se a CLI listasse a 001 como pendente ou não a listasse.
- **CA-10 (sem SQLSTATE específico): aceita.** O CA diz só "falha". O teste confere a falha e que nenhuma linha foi gravada, e o teste do autor confirma `GeneratedAlways`.

### Avaliação das decisões do dev-report que vão além do texto da SPEC

| Decisão | Avaliação |
|---|---|
| 1. `device_id not null` | Aceita, ver RV-05 (só falta atualizar a documentação). |
| 2. Restrições de `devices` com nome explícito (iguais aos nomes padrão do Postgres) | Aceita. O schema fica determinístico e nada muda em relação ao comportamento padrão. |
| 3. INFO no stdout; WARNING/ERROR no stderr | Aceita. O `logging` é o que a SPEC pede, e a divisão é convencional. |
| 4. Exit 2 para URL malformada e para `--migrations-dir` inexistente | Aceita. Os dois casos são "argumento inválido" (§4.2). A mensagem `invalid database URL (not shown)` evita o eco do parser do libpq (R-03). |
| 5. `DatabaseConnectionError ... from None` | Aceita e boa. Elimina o vazamento da conninfo pela exceção encadeada, inclusive para quem chama as funções importadas. Os testes do tester verificam o traceback completo. |
| 6. `pending_migrations` e `--status` também verificam o checksum | Aceita. Coerente com "1 = falha de checksum", e evita um `--status` que diria "tudo aplicado" para um arquivo divergente. Nenhum dos dois cria `schema_migrations`. |
| 7. Migração registrada com o arquivo ausente: só WARNING | Aceita. A SPEC não trata esse caso, e o comportamento não é destrutivo. Fica como sugestão para o architect definir isso quando a primeira migração for removida ou renomeada (hoje uma renomeação com o mesmo número e o mesmo conteúdo passa sem aviso). |
| 8. `.sql` sem diferenciar maiúsculas (`.SQL` é rejeitado, não ignorado) | Aceita. Falhar fechado é o mais seguro. |
| 9. Tabelas sem schema qualificado (primeiro schema do `search_path`) | Aceita para o MVP: igual ao `001_init.sql` e ao `public` do Supabase. Fica para o security-devops avaliar se convém fixar o `search_path` na conexão do executor. |
| 10. Chave constante do advisory lock | Aceita. O problema do lock em si está em RV-01. |
| 11. Trava pelo nome escrito na conninfo, sem fallback para `PGDATABASE`/usuário; URL sem nome é recusada | Aceita e boa. Falha fechada. A verificação usa o mesmo parser do libpq, então `?dbname=` na query também é considerado (confirmado pela sonda). |
| 12–14. Sonda fora do padrão `test_*.py`, `empty_schema` que restaura o schema, papel `partqc_rls_probe_dev` distinto do do CA-15 | Aceitas. Isolamento correto, e a ordem alternativa da suíte (aceite antes dos testes do autor) passa. |
| 15. `.env.example`: só o comentário | Aceita. Não há variável nova. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Os 23 CAs e as §4.1–4.4 estão implementados, e nada passa do escopo: sem rotas, sem pool, sem script de registro. Nenhum CA foi alterado. A rastreabilidade CA → arquivo/teste está no dev-report. As decisões fora do texto estão registradas, e só a 1 pede atualização de documentação (RV-05). |
| 2. Regras inegociáveis | ✅ | R-01: nenhuma dependência nova (o `psycopg` já existia em `api/pyproject.toml` e no grupo de dev da raiz); `uv.lock` inalterado. R-02: N/A. R-03: a busca no diff só encontrou as credenciais de teste da lista de permissão (`u:s3cr3t-pw@127.0.0.1`, `password=s3cr3t-pw` contra a porta 1) e o marcador `<user>:<password>` do `.env.example`; a URL nunca é registrada em log. R-04: nenhum payload alterado, e os `check` espelham os enums, com o CA-05 guardando contra deriva. R-05: PK em `inspection_id` e `on conflict do nothing` cobertos pelo CA-11. R-06: `inspections_source_check`. R-07: cada commit tem trailer `Agent:`. O developer (`31d984c`, `01f8f9d`, `4e6a863`, `13bf8c1`, `871307e`) não tocou em `tests/acceptance/`. O tester (`ebbdd02`) tocou só em `infra/tests/acceptance/` e no test-report. O orchestrator (`c531b19`, `d89f99b`, `df5b3c7`, `dfdc56a`) só mudou status e registrou aprovações. O architect (`9bdd894`, `0f21199`) só tocou em `docs/`. R-11: N/A. R-12: sem torch/onnxruntime, Python 3.12. R-13: todos os commits são `Carlos Moises <…CarlosZeyy@users.noreply.github.com>`, em Conventional Commits. |
| 3. Corretude | ✅ (com achados) | A coluna gerada, as restrições, o NaN (rejeitado, porque `NaN between 0 and 1` é falso no Postgres) e o `\n` final nas regex (rejeitado, porque o `$` do POSIX não aceita newline final) foram verificados pelos testes do tester. Os `except Exception` em `_host_port`, `_connect`, `main` e `_database_name` não engolem erros: relançam um erro sanitizado ou falham fechado. As datas são `timestamptz`. RV-01 (lock no pooler), RV-02, RV-03 e RV-04 são as ressalvas. |
| 4. Testes | ✅ | Test-report PASS, com um teste por CA, e os testes não são tautológicos: o CA-03 compara um snapshot completo do catálogo; o CA-05 compara com os enums; o CA-09 itera `Grade` e usa `qc_contracts.is_defective`; o CA-15 usa um papel real `NOBYPASSRLS` com `SET LOCAL ROLE`; o CA-22 conta conexões TCP. Não há mock de banco nem rede externa (o "host inexistente" foi só sondagem manual). A RNF-09 não se aplica a `infra/`. |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos. Sem `print`, com type hints nas funções públicas e funções curtas. O README ganhou o comando de migração (DoD), e o `.env.example` foi ajustado. |
| 6. Segurança | N/A | Fica para o portão do security-devops (a SPEC tem a tag `security`). Pontos de partida: RV-01, decisão 9 (`search_path`) e RLS em `schema_migrations` (CA-14). |

## Pontos positivos

- A trava do `db_conninfo` decide antes de qualquer conexão e falha fechada: sem nome, nome ilegível ou `PGDATABASE` não contam. O tester provou com um listener que nenhum byte chega ao servidor.
- O cuidado com R-03 vai além do CA-20: `from None` nas exceções de conexão, URL malformada sem eco e testes que inspecionam o traceback completo, inclusive as exceções encadeadas.
- O DDL é idempotente, e o CA-03 compara colunas, defaults, expressões geradas, `pg_get_constraintdef`, `indexdef`, RLS e políticas antes e depois.
- Os testes de aceite usam um banco temporário próprio (`<db>_acc003`), não sujam o `migrated_db` da sessão e não deixam papéis nem bancos para trás.

## SPEC_ISSUE (se houver)

- **SPEC_ISSUE-01 (RV-01, média):** a §4.2 exige `pg_advisory_lock` (lock de sessão) e diz que a conexão deve ser "compatível com o pooler em modo transaction". Pelo Supavisor na porta 6543, um lock de sessão pode ficar preso num backend do pool e travar a próxima execução indefinidamente. O `deployment-plan.md` manda rodar o `migrate.py` com essa URL. O architect precisa decidir, **antes da SPEC-015**, entre: migrar pela conexão direta ou pelo pooler em modo session (e documentar isso), ou trocar por `pg_advisory_xact_lock` por migração. Nos dois casos, com um prazo de espera pelo lock.
- **SPEC_ISSUE-02 (RV-05, baixa):** ratificar `inspections.device_id not null` e atualizar `architecture.md` §5 (e, se quiser, o `unique` de `devices.api_key_hash`) para ficar igual ao schema implementado.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
