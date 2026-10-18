# SPEC-027 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-027](../../docs/specs/SPEC-027-manutencao-api-banco-simulador.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `main...b462aee` |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante ou alto. Há 1 achado médio (RV-01) e 2 baixos (RV-02 e RV-03), que não bloqueiam. A SPEC tem a tag `security`, então o próximo passo é o security-devops. O RV-01 é o único que eu recomendo corrigir antes do merge, numa r2 curta ou numa pendência registrada. A escolha fica com o orquestrador e o security-devops.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | média | `scripts/simulate.py:406-424` (`_api_url`) e `:571-574` (`_check_health`) | Um host ASCII com um rótulo vazio ou com mais de 63 caracteres passa por `_api_url`: `https://exa..mple.com` (um erro de digitação plausível), `https://.example.com` ou um rótulo de 64 caracteres. O `urlsplit` e o `httpx.URL(url).host` aceitam esses hosts. Na primeira requisição real, o codec `idna` do Python, que o `socket` usa, levanta `UnicodeError: label empty or too long`. Esse erro não é `httpx.RequestError`, então escapa de `_check_health`, de `send` e de `main`. Resultado: traceback e código 1. Reproduzi com `SIM_DEVICE_API_KEY` gerada e `--api-url https://exa..mple.invalid`, sem rede (a falha acontece antes do DNS): `exit=1` e `UnicodeError` no stderr. Isso contraria o §2 ("nunca ... sai com traceback por uso inválido") e o §4.3.5 ("nenhum caminho de uso inválido sai com código 1 nem mostra traceback"). É a mesma classe do `xn--zz` que a decisão 6 do dev-report já fechou. **Atenuantes:** nenhum CA é violado (o CA-11 enumera os `argv` dele, e todos dão 2); o comportamento já existia na `main` (conferi rodando o `simulate.py` da `main`: `exit=1`); o traceback não mostra a URL nem a chave (busca por `mple` e pela chave no stderr: 0 ocorrências). | Dentro do mesmo `try` de `_api_url`, depois do `httpx.URL(url).host`, conferir o host como o `socket` vai codificá-lo: `host.encode("idna")`. O `UnicodeError` é um `ValueError` e já cai em `invalid --api-url (not shown)` com código 2. Conferi que o codec aceita `localhost`, `127.0.0.1`, `::1`, `api.example.org` e o ponto final (`example.com.`). Incluir nos testes do autor `exa..mple.com`, `.example.com` e um rótulo de 64 caracteres, e o tester acrescenta esses casos ao CA-11. Se o orquestrador preferir não abrir a r2, registrar como pendência para a próxima SPEC de manutenção do simulador. |
| RV-02 | baixa | `reviews/SPEC-027/r1-test-report.md:172` e `:184` (OBS-04) | O test-report diz que os hosts ASCII malformados "nunca saem com código 1 nem com traceback" e que, "com a API real, terminariam em erro de rede (código 5)". A primeira frase só foi verificada com a API falsa (`httpx.MockTransport`), que não passa pelo codec do `socket`. A segunda está errada para `..`, `.example.com` e rótulos com mais de 63 caracteres: o resultado é código 1 com traceback (RV-01). Para `-bad-.example.org`, o codec aceita, e a frase vale (erro de DNS, código 5). | Corrigir a OBS-04 no próximo test-report desta SPEC (r2, se houver) ou citar este RV no PR. Não muda nenhum teste. |
| RV-03 | baixa | `docs/specs/SPEC-027-manutencao-api-banco-simulador.md:111` (CA-07); `scripts/tests/acceptance/test_spec_027.py` | OBS-01 do tester. O CA-07 lista só os `argv`, mas os casos `--start`, `--out-of-control-lots` e `--model-version` só citam a própria opção quando o `device_id` é válido, porque o simulador confere `--device-id` primeiro (ordem da SPEC-014). O tester definiu `SIM_DEVICE_ID=sim-01` como contexto comum. Aceito: é uma pré-condição do "Dado", e não uma mudança do CA. Sem a variável, o código continua 2 e não há eco (o tester conferiu à parte). Mesmo assim, o texto do CA não diz isso. | Nenhuma ação nesta SPEC. Quando o architect mexer de novo na SPEC-027 ou na SPEC-014, deixar explícito no CA-07 o contexto `SIM_DEVICE_ID` válido. |

## Migração `002_contract_checks.sql`

| Ponto | Conferência | Resultado |
|---|---|---|
| Sem `BEGIN`/`COMMIT` | O arquivo não tem `BEGIN`, `COMMIT`, `ROLLBACK` nem `START TRANSACTION` (há também um extra do tester que confere isso). O executor roda o arquivo com `conn.execute(sql)` sem parâmetros (`infra/migrate.py:218`). Por isso o `%` do `raise exception` não passa pelo psycopg, como o §7 previa. | ✅ |
| Conferência prévia | Um `select` com `count(*) filter (...)` por regra e um quinto `filter` com a negação da conjunção das 4 regras. Assim, o total conta linhas, e não violações (extra do tester com uma linha que viola 3 regras: `total=2`). As expressões são as mesmas da tabela do §4.1, caractere por caractere. As colunas são `not null` na `001` (`inspection_id uuid primary key`, `inspected_at`/`received_at timestamptz not null`, `model_version text not null`), então nenhum `not (null)` escapa da contagem. | ✅ |
| Mensagem sem valores | O formato é o exato do §4.1, com as 5 contagens como parâmetros do `raise` (literais adjacentes separados por quebra de linha, que o Postgres concatena). O `MigrationError` traz a mensagem do servidor e `CONTEXT: PL/pgSQL function inline_code_block line N at RAISE`, sem valores de linha. Os testes do CA-05 e os extras conferem a ausência de `MODEL_X`, do UUID v1, do `lot_id` marcador, de `edge-01` e de `Failing row` em `str`, `repr` e na causa. | ✅ |
| Nada pela metade | A conferência e os 4 `alter table` ficam num **único** `do $$`. Pelo executor, a transação é desfeita e nada vai para `schema_migrations` (CA-05). À mão, num `psql` sem `ON_ERROR_STOP` ou em autocommit, o bloco único é uma instrução atômica: com dois blocos, os `alter table` rodariam depois da recusa (decisão 1 do dev-report). O extra do tester compara o snapshot do schema antes e depois, em transação explícita e em autocommit. | ✅ |
| Idempotência | Cada `add constraint` fica atrás de `not exists (select 1 from pg_constraint where conrelid = 'inspections'::regclass and conname = ...)`, como o §4.1 item 2 pede. Na segunda execução, a conferência passa (as restrições já garantem as linhas) e nada é criado. O CA-02 compara `(conname, pg_get_constraintdef)` depois de duas execuções diretas. Restrição preexistente com o mesmo nome: é mantida, e as outras 3 são criadas (teste do autor e extra do tester). | ✅ |
| `001` intocada e nada além do §4.1 | `infra/migrations/001_init.sql` não está no diff. Colunas, índices, RLS e políticas iguais (snapshot do tester). As 4 restrições ficam `convalidated = true`. | ✅ |
| Concorrência | Entre a contagem e o primeiro `alter table` não há lock. O próprio `add constraint` valida a tabela inteira, e a mensagem do Postgres nesse caso (`check constraint ... is violated by some row`) não traz valores. O §7 aceita esse risco. | ✅ |
| Espelho do contrato | A regex de `model_version` é igual a `MODEL_VERSION_PATTERN` (`packages/contracts/src/qc_contracts/schemas.py:28`). O CA-04 compara a restrição com `TypeAdapter(UUID4)` nos 256 pares `V`/`W` e com `re.fullmatch` na lista de `model_version`. Os limites de data passam com a sessão em `America/Sao_Paulo` (extra do tester), porque o `check` compara instantes. | ✅ |

## Ajustes em testes de aceite de SPECs anteriores

Conferi os dois commits do tester contra a §3.1 e a §4.4 da SPEC e contra a regra "Testes de aceite de SPECs anteriores" do `docs/architecture.md` §10. Essa regra ainda está no PR #16 (`spec/SPEC-010-modo-coleta`), e li o texto direto da branch dele. Até ele entrar na `main`, vale a autorização explícita da §3.1, e os dois ajustes cabem nela.

### `infra/tests/acceptance/test_spec_003.py` (`732bf6f`)

| Linha da tabela do test-report | Conferência no diff | Resultado |
|---|---|---|
| Imports e `_default_versions()` | `load_migrations` entra no import, e `_default_versions()` devolve `[m.version for m in load_migrations(MIGRATIONS_DIR)]`. É a "lista calculada no teste" que a §3.1 sugere. | ✅ |
| fixture `ca01_db`, `test_extra_manual_then_runner`, `test_extra_pending_on_empty_schema`, `test_extra_cli_apply_success_hides_url`, `test_extra_cli_uses_database_url_env` | Só o literal `["001"]` virou `_default_versions()`. O `"001" in out` e o `SECRET not in out` da CLI não mudaram. | ✅ |
| `test_ca01_apply_on_empty_schema` | `["001"]` → `_default_versions()`, e a leitura passou a filtrar `where version = '001'`. A asserção `rows == [("001", sha256(001_init.sql))]` continua, como a §3.1 exige ("a verificação do checksum da `001` continua"). | ✅ |
| `test_ca02_second_apply_is_noop`, `test_extra_concurrent_runs_apply_once` | A contagem `1` virou `len(_default_versions())`, e o `repr(["001"])` virou `repr(_default_versions())`. | ✅ |
| `test_extra_schema_migrations_columns` | Só o `where version = '001'` na leitura de uma linha. | ✅ |
| `test_extra_new_migration_after_existing` | É exatamente a saída (a) de `e015926`: cópia de todos os `.sql` do diretório padrão, `<N>_more.sql` com `N = f"{int(versions[-1]) + 1:03d}"` e o mesmo conteúdo, `pending`/`apply == [N]` e versões aplicadas `[*versions, N]`. A intenção (a nova migração é aplicada depois das existentes) continua verificada. | ✅ |

`test_ca03_*` e `test_ca21_*` não mudaram, e nenhuma outra linha do arquivo mudou. Os nomes conferem com a lista da §3.1.

### `api/tests/acceptance/test_spec_004.py` (`efe5d8f`)

| Ponto | Conferência no diff | Resultado |
|---|---|---|
| Porta (§4.4 item 2) | `_free_port` saiu, e `_start_uvicorn` sobe `--port 0` e lê a porta de `Uvicorn running on http://127.0.0.1:(\d+) ` com prazo de 20 s. Uma thread lê a saída o tempo todo e guarda tudo para as asserções finais. Isso também elimina um risco que o código antigo tinha: com `LOG_LEVEL=DEBUG` e `communicate` só no fim, o pipe podia encher e travar o uvicorn. As mensagens `uvicorn exited` e `uvicorn did not start` continuam. | ✅ |
| Timeout (§4.4 item 2) | `timeout=60 if depth == 50_000 else 10` só no `client.post` do laço de profundidade. Os outros pedidos continuam com 10 s. A §4.4 só condiciona ao diagnóstico o item da asserção `ERROR`, não o timeout. | ✅ |
| `" ERROR " not in log` | A condição não mudou. Ganhou só a mensagem `_log_tail(log, ke)`, porque o diagnóstico não mostrou linha `ERROR`. | ✅ |
| Log nas mensagens (§4.4 item 1) | `_log_tail` troca `READ_KEY`, `NO_DB_PASSWORD` e `ke` por marcadores e devolve os últimos 3 000 caracteres. | ✅ |
| Nada mais muda (§4.4 item 3) | Status esperados (`(400, 422)` para `deep-50000`, `(422,)` nos outros, `413`), marcador do corpo, `Traceback`, `ke`, `NO_DB_PASSWORD + "@"`, `READ_KEY`, número de linhas e `last_seen_at`: todos iguais. As únicas outras linhas do diff são a constante `_UVICORN_RUNNING`, o alias `Uvicorn` e a quebra do `client.post` em várias linhas (formatação do ruff por causa do argumento novo). | ✅ |
| Diagnóstico (§4.4 item 1) e CA-12 | 20 execuções com `-rA --tb=long` (mais 20 com CPU saturada), sem falha e sem `ERROR`. A causa estrutural ficou registrada: o uvicorn abre o pool antes do bind, e a porta de `_free_port` ficava livre nessa janela. As 30 execuções do CA-12 terminaram sem falhas, com o comando exato. Não há defeito da API, então não cabe `SPEC_ISSUE` (§4.4 item 4). | ✅ |

**Contagem de testes:** comparei `main` e `HEAD` nos dois arquivos: 59 e 55 funções `test_`, e 14 e 7 `parametrize`, iguais. Na coleta do `HEAD`, são 114 e 81 testes, os números do test-report. **Autor:** os dois arquivos só mudam em commits `Agent: tester`. O developer listou no dev-report os testes que falhariam e o requisito que os invalida, e não tocou em `tests/acceptance/`.

## Decisões do dev-report fora da letra da SPEC

| Decisão | Avaliação |
|---|---|
| 1. Um único `do $$` | **Aceita.** O §4.1 pede "conferência antes de qualquer `alter table`" e não proíbe o bloco único. O bloco único é o que garante o "nada pela metade" fora do executor. |
| 3. `redact_usage_error` pública; `parse_args` sobrescrito para a contagem exata | **Aceita.** O §4.3.1 pede a subclasse com `error()` sobrescrito, e isso está feito. O `parse_args` só troca o `' '.join(extras)` do argparse pela contagem `len(extras)`, que é exata mesmo com espaços nos valores. A regex de literais `%r` cobre aspas simples e duplas com escapes. Testei à parte `--lots=` vazio, um valor com `'` e `"`, `--api-key -<S>`, `-x<S>` e `--seed 1e3`: sempre código 2, sem eco. As mensagens próprias do simulador não têm aspas (inclusive as que citam `DEVICE_ID_PATTERN` e `MODEL_VERSION_PATTERN`), então não são alteradas. |
| 4. Help sem quebra em hífen (`_HelpFormatter`) | **Aceita.** Sem isso, o `textwrap` pode partir `--api-key=<value>` conforme `COLUMNS`, e o CA-08 dependeria do terminal. O `_split_lines` é um método interno do argparse, mas o Python está fixo em 3.12 (R-12). O extra do tester com 4 larguras detecta uma eventual quebra numa versão futura. O efeito colateral (`break_long_words=False`) só permite linhas mais longas que a largura em palavras enormes, o que não acontece no help. |
| 5. `CLOUD_API_URL` com espaço no fim recusada (OBS-05) | **Aceita.** É a letra do §4.3.3 ("`--api-url` (ou `CLOUD_API_URL`) com um caractere fora de `"!"` a `"~"` (espaço, ...)"), e o CA-09 exige recusar `"https://example.com/\t"`, que o `strip()` anterior aceitava. O vazio ou só com espaços continua dando `no API URL`. O impacto prático é pequeno: conferi que `uv run --env-file` já remove os espaços do fim de um valor sem aspas no `.env` (o README usa essa forma). Sobra só uma variável exportada à mão no shell. O README avisa ("só caracteres ASCII visíveis, sem espaço"). `SIM_DEVICE_ID` e `SIM_DEVICE_API_KEY` continuam com `strip()` (`_env`), o que é coerente com a SPEC, que só fala da URL. |
| 6. Host conferido como o httpx o codifica | **Aceita.** A justificativa é o §4.3.5. Não gera recusa falsa, porque o `httpx.Client(base_url=...)` analisa a mesma URL do mesmo jeito: tudo o que essa conferência recusa falharia no cliente, com traceback. A conferência fecha o `xn--zz`, mas não cobre o codec do `socket` (RV-01). |

## Observações do tester (OBS-01 a OBS-05)

| OBS | Avaliação |
|---|---|
| OBS-01 | Aceita como pré-condição do CA-07. Texto do CA a explicitar no futuro (RV-03). |
| OBS-02 | Aceita. O `part.strip()` já existia na `main`, e cada número continua limitado a `[0-9]{1,4}` com `fullmatch` (só dígitos ASCII, sem `_` nem sinal). |
| OBS-03 | Aceita. `-h<valor>` é o comportamento padrão do argparse (help, código 0) e não ecoa o valor. |
| OBS-04 | **Parcialmente incorreta:** com a API real, `..`, `.example.com` e rótulos com mais de 63 caracteres saem com código 1 e traceback, não com 5 (RV-01 e RV-02). |
| OBS-05 | Aceita (decisão 5 acima). |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Os itens do §4.1 ao §4.4 estão implementados, e os 12 CAs estão rastreados no dev-report e no test-report. Nenhum CA foi alterado pelo autor. A única mudança da SPEC na branch é a do architect (`e015926`, SPEC_ISSUE-01, reaprovada pelo humano). As decisões fora da letra estão registradas no dev-report (decisões 1 a 6) e cabem no §4.3.5. Resíduo do §4.3.5: RV-01 (média). |
| 2. Regras inegociáveis | ✅ | R-01, R-02 e R-12: nenhuma dependência nova (sem mudança em `pyproject.toml` ou `uv.lock`), e nada de imagem. R-03: busca no diff por conninfo com senha, `password=`, `eyJ`, chaves privadas e `secret_key` sem ocorrências; as chaves dos testes são geradas com `secrets`; não há variável nova para o `.env.example`. R-04: nenhum payload mudou, e o banco passa a espelhar o contrato. R-05 e R-06: sem mudança. R-07: os trailers `Agent:` de todos os 13 commits conferem com os arquivos (developer: produção, testes do autor e dev-report; tester: só `*/tests/acceptance/` e test-report; architect: só a SPEC; orchestrator: só status). R-13: autor `CarlosZeyy` (noreply) em todos, Conventional Commits, sem citação corporativa. |
| 3. Corretude | ✅ | Migração e log da escrita corretos (seções acima). Simulador: os casos do SEC-01 ao SEC-04 estão fechados. Exceção: RV-01 (host ASCII com rótulo vazio ou longo). |
| 4. Testes | ✅ | Test-report PASS, com todos os CAs automatizados (CA-12 manual registrado). O CA-06 foi validado por mutação (`sqlstate_label` → `str(exc.sqlstate)` derruba o CA-06). Só fronteiras são mockadas. Sem rede, sem pytest em subprocesso e sem credencial literal (a conninfo temporária é montada com `make_conninfo`). O banco temporário `partqc_test_acc027` é removido no fim do módulo. Erro no texto da OBS-04: RV-02. |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos (116 arquivos). README (seção "Simulador") atualizado. Nenhuma regex duplicada: `sqlstate_label` é importada do middleware. |
| 6. Segurança | N/A | Fica com o security-devops (portão `security`). |

## Verificação própria (read-only)

- `uv run ruff check .`: limpo. `uv run ruff format --check .`: 116 arquivos já formatados.
- `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q -p no:cacheprovider`: **2735 passed**, 1 warning (o `StarletteDeprecationWarning` que já existia), em 5 min 46 s, igual ao test-report.
- Amostra do CA-12: 5 execuções seguidas de `uv run pytest -q api/tests/acceptance/test_spec_004.py -k real_server`, todas com `2 passed, 79 deselected` (de 3,0 s a 3,2 s).
- Coleta: 114 testes em `test_spec_003.py` e 81 em `test_spec_004.py`. As contagens de `def test_` e `parametrize` são iguais na `main` e no `HEAD`.
- Reprodução do RV-01 com o `simulate.py` do `HEAD` e o da `main` (os dois dão `exit=1`) e com o `httpx.get` direto (`UnicodeError` para `..`, `.x` e rótulos de 64 e 300 caracteres). Só arquivos no scratchpad, sem rede: a falha acontece no codec, antes do DNS.

## Pontos positivos

- A `002` num bloco único resolve, sem custo, o caso do `psql` sem `ON_ERROR_STOP`, que a SPEC não tinha previsto.
- A troca de `_free_port` por `--port 0` ataca a causa estrutural, que o diagnóstico documentou lendo o `uvicorn/server.py`, e não o sintoma. A leitura contínua da saída ainda elimina um segundo risco de travamento (pipe cheio).
- O dev-report antecipou o SPEC_ISSUE-01 com as duas saídas possíveis, e o tester aplicou a saída aprovada à risca.
- O tester validou o CA-06 por mutação e verificou o `diag.constraint_name` em cada recusa do CA-03. As recusas vêm das restrições novas, e não de outra.

## SPEC_ISSUE (se houver)

Nenhum. O RV-01 é uma lacuna da implementação diante de um requisito que já está escrito (§4.3.5), e não uma ambiguidade da SPEC. O RV-03 é só uma sugestão de texto para o architect, sem efeito nesta rodada.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
