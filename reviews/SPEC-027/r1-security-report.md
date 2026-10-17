# SPEC-027 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-027](../../docs/specs/SPEC-027-manutencao-api-banco-simulador.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `main...798fb63` |
| **Veredicto** | **FAIL** |

O único motivo do FAIL é o SEC-01, que corresponde ao RV-01 do review-report. A migração `002`, o log da escrita e os SEC-01, SEC-02 e SEC-04 da SPEC-014 estão corretos. O SEC-03 da SPEC-014 está fechado para os casos que ele cita, mas sobra um caso da mesma classe, que é o SEC-01 deste relatório. Os demais achados (SEC-02 a SEC-04) são baixos ou informativos e não exigem mudança nesta SPEC.

## Decisão sobre o RV-01 (r2, não pendência)

O RV-01 **exige uma r2** desta SPEC. Eu o classifico como **alta** (categoria input), um grau acima da média do reviewer. Os motivos:

1. **É um bug confirmado contra um requisito escrito da própria SPEC.** O §2 diz que o simulador "nunca [...] sai com traceback por uso inválido", e o §4.3.5 diz que "nenhum caminho de uso inválido sai com código 1 nem mostra traceback". Reproduzi o defeito no `HEAD` com quatro hosts, sem rede, porque a falha acontece no codec, antes do DNS. Pela tabela de severidades de `reviews/README.md`, um "bug provável" é **alta**, e este bug está reproduzido. Não é bloqueante, porque nenhum CA o cobre: o CA-11 enumera os seus `argv`.
2. **Esta é a SPEC que fecha essa classe de defeito.** O SEC-03 da SPEC-014 (URL inválida → traceback e código 1) está no escopo dela, e o developer já fechou o caso irmão `xn--zz` (decisão 6 do dev-report). Marcar a SPEC como `Done` com um caso conhecido aberto deixaria o §4.3.5 falso no próprio entregável.
3. **A correção é pequena e local.** São uma linha em `_api_url` e alguns casos de teste. A rodada atual é a r1, e o limite é 3 (R-10).
4. **Uma pendência sairia mais cara.** Ela exigiria uma SPEC nova (architect e aprovação humana) só para essa linha. Além disso, a SPEC-015 depende da SPEC-027 justamente pelo "simulador corrigido" e vai usá-lo em produção.

O impacto direto em segurança é baixo, e isso fica registrado: no Python 3.12.15 do projeto, o traceback não mostra o host, o caminho nem a chave (conferido abaixo). A gravidade vem do defeito diante do requisito, não de um vazamento.

## Superfície analisada

- **Banco:** `infra/migrations/002_contract_checks.sql`. É um único bloco `do $$`, com a conferência das linhas existentes e 4 `check` nomeados em `inspections`. O executor `infra/migrate.py` não mudou.
- **API:** `api/src/qc_api/routers/inspections.py`. Só o campo SQLSTATE do `logger.warning` de `_write` muda. Nenhuma rota, autenticação, CORS ou dependência nova.
- **Simulador:** `scripts/simulate.py`. Mudam o parser (`NoEchoArgumentParser`, `redact_usage_error`, `_HelpFormatter`), `_api_url` (só ASCII visível e o host do httpx) e `_LOT_NUMBER` (`[0-9]{1,4}`). O `README.md` (seção "Simulador") também muda.
- **Entradas externas:** `argv`, `CLOUD_API_URL`, `SIM_DEVICE_ID` e `SIM_DEVICE_API_KEY` (simulador); linhas gravadas fora da API (banco).
- **Testes:** os testes de aceite e os do autor nos três componentes, e os ajustes autorizados em `test_spec_003.py` e `test_spec_004.py`.
- **Dependências e deploy:** nenhuma mudança em `pyproject.toml`, `uv.lock` ou `.env.example`. O deploy não muda nesta SPEC. A `002` vai para produção pelo CA-19 da SPEC-015.

### Verificações feitas (só leitura)

- **Testes da SPEC com banco:** `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q -p no:cacheprovider infra/tests api/tests/acceptance/test_spec_027.py api/tests/test_inspections.py scripts/tests` deu **744 passed** e 1 warning (o `StarletteDeprecationWarning` que já existia). Não rodei a suíte inteira: o tester e o reviewer já a rodaram (2735 passed). A lista de bancos do Postgres local antes e depois é a mesma (`partqc_test`, `postgres`, `template0`, `template1`), então nenhum banco temporário ficou para trás.
- **Fuzz do parser sem eco (SEC-01 da SPEC-014):** foram 564 combinações de `argv`, todas com `--dry-run` e `S = "Z" + secrets.token_urlsafe(32)` gerado na hora:
  - os 13 nomes de opção, nas formas `--opt v`, `--opt=v` e `--opt v v`;
  - o valor solto, `--api-keyy v`, `--api-keyy=v`, `-xv`, `-x v`, `--dry-run=v`, `--help=v` e `-hv`;
  - 12 variações do valor (`'`, `"`, `\`, `\x01`, espaço, `\n`, `ä`, prefixos `-` e `--`).

  Resultado: o código foi sempre 0 ou 2, sem `Traceback`, e nem `S` nem os primeiros 12 caracteres dele apareceram no stdout ou no stderr.
- **Reprodução do RV-01:** rodei `simulate.py` em subprocesso, com uma chave gerada por `secrets` e os hosts `exa..mplemark.invalid`, `.examplemark.invalid`, um rótulo de 64 caracteres e `examplemark.invalid..`, todos com o caminho `/pathtok`. Nos 4 casos: `exit=1` e a última linha `encoding with 'idna' codec failed`. O stderr não tem `examplemark`, `pathtok`, `qqqq` nem a chave.
- **Caminho do host até o socket:** o httpx entrega ao httpcore o `raw_host`, que é ASCII (`httpx/_transports/default.py:241`). O httpcore faz `decode("ascii")` (`httpcore/_sync/connection.py:117`) e chama `socket.create_connection`, que codifica com o codec `idna`.
- **Varredura de segredos no diff:** procurei conninfo ou URL com `:senha@`, `password=`, `eyJ`, `sk_`, `service_role`, chaves privadas e `X-API-Key` literal. Não há nenhuma ocorrência em código ou testes; a única linha encontrada é o texto do review-report que descreve essa mesma busca.
- **Trailers:** os 15 commits de `main..HEAD` têm a identidade `CarlosZeyy` (noreply), e cada `Agent:` confere com os arquivos tocados (developer, tester, architect, reviewer e orchestrator).

## Achados

| ID | Severidade | Categoria (auth, input, secrets, deps, deploy, privacy) | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-01 (= RV-01) | **alta** | input | `scripts/simulate.py:406-424` (`_api_url`); o erro escapa em `:571-574` (`_check_health`) e em `send`/`main` | Um host ASCII visível com rótulo vazio ou com mais de 63 caracteres passa por `_api_url`: `exa..mple.com`, `.example.com`, `example.com..` (dois pontos no fim) e rótulos de 64 caracteres. Na primeira requisição, o `socket` codifica o host com o codec `idna` e levanta `UnicodeError`. Esse erro não é `httpx.RequestError`, então sai com traceback e código 1, contra o §2 e o §4.3.5. O código 1 é reservado para "item gerado inválido", o que também engana quem lê o código de saída, como o operador ou o passo 6 do deploy na SPEC-015. Não há vazamento: no 3.12.15, o stderr não mostra o host, o caminho nem a chave. O comportamento já existia na `main`. | **r2 (developer):** dentro do mesmo `try` de `_api_url`, conferir o host **na forma que chega ao socket**: `httpx.URL(url).raw_host.decode("ascii").encode("idna")`. O `UnicodeError` é um `ValueError` e cai em `invalid --api-url (not shown)`, com código 2. Prefira o `raw_host` ao `.host` sugerido pelo reviewer: o `.host` devolve a forma Unicode de um rótulo `xn--` (ex.: `xn--nxasmq6b.com` vira `βόλοσ.com`), e o `encode("idna")` dela passa pelo nameprep do IDNA 2003, que recusa caracteres posteriores ao Unicode 3.2. Isso daria recusa falsa de um domínio IDNA 2008 válido, que o socket nunca vê nessa forma. Os testes do autor devem ter: recusa (código 2, 0 requisições na API falsa, sem `Traceback`) para `exa..mple.com`, `.example.com`, `example.com..` e um rótulo de 64 caracteres; aceitação para `example.com.`, um rótulo de 63 caracteres, `https://[::1]` (com `https://`, porque `::1` não está em `LOCAL_HOSTS` e o `http://` é recusado), `xn--nxasmq6b.com`, `localhost` e `127.0.0.1`. **r2 (tester):** incluir esses hosts como extras do CA-11 em `scripts/tests/acceptance/test_spec_027.py` (o texto do CA não muda) e corrigir a OBS-04 do test-report (RV-02). |
| SEC-02 | baixa | deploy | `infra/migrations/002_contract_checks.sql:66-115` | A idempotência é por nome, como pede o §4.1 item 2. Se já existir em `inspections` uma restrição com um dos 4 nomes e outra definição (por exemplo, criada à mão no SQL Editor), a `002` a mantém sem aviso e é registrada como aplicada. Com uma regra mais fraca, a lacuna de leitura que a SPEC fecha continuaria aberta. Em produção a tabela está vazia e não há restrição manual, então o risco é teórico. | Nenhuma nesta SPEC. Na SPEC-015 (CA-14/CA-19), depois da migração em produção, conferir `select conname, pg_get_constraintdef(oid) from pg_constraint where conrelid = 'inspections'::regclass and conname like 'inspections\_%\_check' order by 1;` contra a tabela do §4.1. |
| SEC-03 | info | deploy | `infra/migrations/002_contract_checks.sql` | Efeito em produção: cada `add constraint` toma `ACCESS EXCLUSIVE` em `inspections` e varre a tabela. No Supabase vazio (CA-19 da SPEC-015), isso é instantâneo, e a conferência passa direto. Se um dia a `002` for aplicada com dados e com a API no ar, as escritas esperam pela varredura, o que é aceitável no volume do projeto. `'inspections'::regclass` e os nomes sem schema dependem do `search_path`, como na `001`. O passo 1 do CA-19 já confere `current_schema() = public`. Privilégios: o bloco não cria função, não usa `security definer` e não muda `grant`, RLS ou políticas. Ele precisa ser executado pelo dono da tabela, que é o mesmo papel que aplicou a `001`. | Nenhuma. |
| SEC-04 | info | input | `scripts/simulate.py` (traceback do RV-01) | A ausência do host no traceback do `UnicodeError` foi conferida só no Python 3.12.15. Uma versão futura do codec `idna` pode passar a citar o trecho recusado. O R-12 fixa o 3.12, e a correção do SEC-01 elimina o caminho de qualquer forma. | Nenhuma além do SEC-01. |

## Pontos conferidos a pedido do orquestrador

### Migração `002`

| Ponto | Resultado |
|---|---|
| Privilégios | ✅ Sem `grant`, `revoke`, `security definer`, função persistente ou mudança de RLS. A `001` (`enable row level security` nas duas tabelas, sem `force`) fica igual. O snapshot do tester e o `test_running_sql_file_again_changes_nothing[002_contract_checks.sql]` do autor confirmam que colunas, índices, RLS e políticas não mudam. |
| Nada de valores de linha | ✅ O `raise exception` só tem as 5 contagens (`bigint`) como parâmetros. O `MigrationError` repete `str(exc)` do servidor: a mensagem acima e `CONTEXT: PL/pgSQL function inline_code_block line N at RAISE`, sem `DETAIL` e sem `Failing row contains`. No caso de concorrência (linha inválida gravada entre a contagem e o `alter table`), o Postgres responde `check constraint "..." of relation "inspections" is violated by some row`, também sem valores. Os testes do CA-05 e os extras conferem a ausência de `MODEL_X`, do UUID v1, de `edge-01` e de `Failing row` em `str`, `repr` e na causa. |
| Atomicidade | ✅ Conferência e `alter table` estão no mesmo `do $$`, que é uma única instrução. Pelo executor, a transação é desfeita e nada vai para `schema_migrations` (CA-05). À mão (SQL Editor, `psql` sem `ON_ERROR_STOP` ou em autocommit), a recusa também não deixa restrição pela metade. O arquivo não tem `BEGIN`/`COMMIT`, e o executor roda sem parâmetros, então o `%` não é interpolado pelo psycopg. |
| SQL | ✅ É SQL estático, sem interpolação. As regexes são iguais às da tabela do §4.1. O operador `~` do Postgres compara faixas `[a-z]` por ponto de código, não por collation, e `$` só casa no fim do texto, então `'sim-v0\n'` é recusado (CA-03). |
| Efeito em produção | ✅ (SEC-02, SEC-03) A tabela está vazia, a conferência passa e o lock é instantâneo. O `search_path` é conferido no CA-19. |

### Simulador (SEC-01 a SEC-04 da SPEC-014)

| SEC da SPEC-014 | Estado |
|---|---|
| SEC-01 (eco do argparse) | **Fechado.** `parse_args` dá a contagem exata de `unrecognized arguments`, e `error()` troca todo literal `%r` por `(not shown)`. O fuzz de 564 combinações não teve eco, código 1 nem traceback. As mensagens próprias do simulador não têm aspas e continuam sem valores. A regex `_QUOTED_VALUE` tem alternativas disjuntas (`[^'\\]` ou `\\.`), sem retrocesso exponencial. |
| SEC-02 (chave começando com `-`) | **Fechado.** O help (com `_HelpFormatter`, que não quebra `--api-key=<value>`) e o README documentam `SIM_DEVICE_API_KEY` e `--api-key=`. O CA-08 cobre os dois caminhos com uma chave gerada que começa com `-`. |
| SEC-03 (URL com controle → traceback) | **Fechado para os casos citados** (controle, espaço, `DEL`, não ASCII, ANSI): recusa antes do `urlsplit`, com código 2 e sem eco (CA-09). O caso `xn--zz` também está fechado (decisão 6). **Resíduo da mesma classe: SEC-01 deste relatório.** |
| SEC-04 (lote com milhares de dígitos) | **Fechado.** `_LOT_NUMBER = [0-9]{1,4}` com `fullmatch`, antes do `int()`. O CA-10 cobre 5 000 dígitos, `12345` e `0007`. |

### "Erros de banco no log" na escrita (`docs/architecture.md` §4)

✅ O `logger.warning` de `_write` registra só a rota, o `device_id` e `sqlstate_label(exc)`, que é a mesma função do middleware: 5 caracteres `[0-9A-Z]` ou `-`. Não há `str(exc)`, `exc.diag.*`, `exc_info` nem traceback. A regra permite também a classe da exceção, e a ausência dela não viola nada. O CA-06 cobre `sqlstate=-` para as exceções sem SQLSTATE e `23514` para a `CheckViolation`, e o tester o validou por mutação. A resposta continua 422 `{"detail": "Value cannot be stored"}`, sem a mensagem do servidor.

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota; comparação em tempo constante | N/A: nenhuma rota ou autenticação mudou. O CA-06 usa a chave de `edge-01` pelo caminho normal. |
| Entradas validadas | ❌ por causa do SEC-01: host com rótulo vazio ou longo. O resto está ✅: banco com os 4 `check`, parser sem eco, URL só com ASCII visível e lotes com até 4 dígitos. Imagem e `extra="forbid"`: N/A, porque o contrato não muda. |
| SQL sempre parametrizado | ✅ A migração é estática e o caminho de escrita não mudou. |
| RLS ligado; `DATABASE_URL`/`service_role` só na API | ✅ RLS intocado. Nenhuma variável nova. |
| CORS | N/A (sem mudança). |
| Logs sem segredos e sem imagem | ✅ Log da escrita só com rota, `device_id` e SQLSTATE. O simulador não repete a chave nem valores digitados. A mensagem da migração só tem contagens. |
| Dependências novas | N/A: nenhuma (`pyproject.toml` e `uv.lock` sem mudança). |
| Deploy | N/A nesta SPEC. Efeito da `002` em produção avaliado no SEC-02 e no SEC-03, e a aplicação é pelo CA-19 da SPEC-015. Sem recurso novo nem cartão (R-01). |
| R-03 nos testes | ✅ Nenhuma credencial literal em URL, conninfo ou header. As chaves vêm de `secrets`, e a conninfo temporária é montada com `make_conninfo`. |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma. `httpx` 0.28.1 e `psycopg` já estavam no `uv.lock`. |

## Ações pendentes para o humano

- Nenhuma nesta rodada. Na SPEC-015 (CA-14/CA-19), incluir a consulta do SEC-02 depois de migrar a produção.

## Declaração

- [x] Não editei código; não sou autor desta SPEC. Só escrevi este relatório. Os scripts de verificação ficaram no scratchpad da sessão, fora do repositório.
