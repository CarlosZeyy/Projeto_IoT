# SPEC-022 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-022](../../docs/specs/SPEC-022-manutencao-setup.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `417107d` (implementação + dev report); testes de aceite em `2a6bdc5` e `f90438c`; reexecução sobre `820f8bb` (SPEC corrigida em `afa4173`) |
| **Veredicto** | **PASS** (final, após a reexecução; a primeira emissão foi FAIL só pelo SPEC_ISSUE-01, já resolvido; ver "Reexecução após SPEC_ISSUE-01") |

Os testes foram escritos a partir da SPEC (caixa-preta) antes da leitura do código do hook. O código só foi lido depois, para o CA-18 e para entender a divergência do CA-06.

## Cobertura dos critérios de aceite

Arquivo: `tests/acceptance/test_spec_022.py` (marcador `acceptance`), com 39 testes coletados.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| (oráculo) | `test_texts_match_spec_quotes`: os textos literais usados no CA-12/13/14 são exatamente as citações `>` da SPEC | ✅ |
| CA-01 | `test_ca01_notebook_edit_with_allowed_file_path_is_denied` | ✅ |
| CA-02 | `test_ca02_both_path_keys_present_are_denied` (os 5 casos da tabela) | ✅ 5/5 |
| CA-03 | `test_ca03_tool_name_not_a_string` (ausente, `42`, `null`) e `test_ca03_unknown_tool_name` (`Bash`, `write`, `""`) | ✅ 6/6 |
| CA-04 | `test_ca04_expected_field_missing_or_empty` (os 6 casos da tabela) | ✅ 6/6 |
| CA-05 | `test_ca05_well_formed_events_allowed` (os 8 casos, inclusive o relativo com `cwd`; o processo do hook roda em `.claude/hooks/`, então só o `cwd` do evento resolve o caminho) | ✅ 8/8 |
| CA-06 | `test_ca06_role_denial_unchanged` | ✅ (na primeira emissão: SPEC_ISSUE-01, resolvido em `afa4173`) |
| CA-07 | `test_ca07_hook_imports_only_stdlib` e `test_ca07_spec001_hook_tests_still_pass` (roda `pytest -q tests/acceptance/test_spec_001.py -k "ca11 or … or ca17"` em subprocesso) | ✅ |
| CA-08 | `test_ca08_ci_postgres_trust_without_password` | ✅ |
| CA-09 | `test_ca09_env_example` | ✅ |
| CA-10 | `test_ca10_no_postgres_password_outside_docs_and_reviews` (sequências montadas por concatenação; rodado de novo depois do commit, com o próprio arquivo de teste já rastreado) | ✅ |
| CA-11 | `test_ca11_readme_local_postgres_commands` | ✅ |
| CA-12 | `test_ca12_readme_workspace_trust_before_limitation` (títulos dentro de bloco de código são ignorados) | ✅ |
| CA-13 | `test_ca13_architect_commits_section_and_frontmatter` | ✅ |
| CA-14 | `test_ca14_reviews_readme_architect_commits_after_role_tracking` (também confere o "logo depois" da §4.3: é o parágrafo imediatamente seguinte) | ✅ |
| CA-15 | `test_ca15_ruff_and_full_suite_without_ci_and_db_url` (ruff check, ruff format --check e a suíte inteira sem `CI`/`TEST_DATABASE_URL`, com o próprio teste desmarcado na execução interna para evitar recursão) | ✅ |
| CA-16 | `test_ca16_db_smoke_with_passwordless_url` (marcador `db`: confere que a URL não tem senha e roda `pytest -q -rs tests/test_db_smoke.py`) | ✅ com contêiner temporário (ver abaixo); pendência manual na porta 55432 |
| CA-17 (manual) | CI no PR | ⏳ pendente: depende do PR (orquestrador/humano) |
| CA-18 (manual) | conferido com git (ver abaixo) | ✅ |

Atualização do CA-20 da SPEC-001 (§3.1): `tests/acceptance/test_spec_001.py::test_ca20_env_example` passou a esperar `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`, no commit próprio `2a6bdc5` (`Agent: tester`). Com isso, esse arquivo deixou de conter a URL antiga, e o CA-10 passa.

Mutação (sanidade dos testes): rodei os testes CA-01…CA-06 contra a versão do hook da `main`, copiada para uma raiz falsa no scratchpad, fora do repositório. Resultado: `18 failed, 9 passed`. Os 9 que passam são o CA-05 (8) e o CA-06 (1), que verificam comportamento que não deveria mudar. Contra o hook do `HEAD`, o resultado foi `27 passed`.

### CA-16: como foi verificado

Por instrução do orquestrador, o contêiner `partqc-pg` (porta 55432, criado com senha) **não** foi tocado. Usei o comando da §4.2 com outro nome e outra porta:

```bash
docker run -d --name partqc-pg-spec022-tester -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=partqc_test -p 127.0.0.1:55436:5432 postgres:16
export TEST_DATABASE_URL=postgresql://postgres@localhost:55436/partqc_test
uv run pytest -q -rs tests/test_db_smoke.py                         # 1 passed in 0.07s, rc=0, nenhum skip
uv run pytest -q -rs tests/acceptance/test_spec_022.py -k ca16      # 1 passed, rc=0
docker rm -f partqc-pg-spec022-tester                               # removido
```

- A porta temporária ficou só em loopback: `docker port` → `127.0.0.1:55436`, e a conexão pelo IP da LAN (`192.168.1.116:55436`) foi recusada.
- Exploratório, só leitura: a URL nova na porta 55432 contra o `partqc-pg` atual falha com `fe_sendauth: no password supplied`, como a nota do README prevê.
- **Pendência manual (humano):** recriar o `partqc-pg` com `docker rm -f partqc-pg` e o `docker run` do README, e rodar `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q -rs tests/test_db_smoke.py`. O esperado é `1 passed`, sem skip.

### CA-18 (manual), conferido localmente

1. `git diff --stat main...HEAD -- .claude/` mostra só `.claude/agents/architect.md` (2 linhas, +1/−1) e `.claude/hooks/guard_paths.py`. ✅
2. `git diff main...HEAD -- .claude/hooks/guard_paths.py` não toca em `ROLES`. Também comparei por `ast` o valor de `ROLES` na `main` e no `HEAD`: idêntico. ✅
3. `git diff -U0 main...HEAD -- .claude/agents/architect.md` mostra uma única linha alterada (39); o frontmatter vai até a linha 16. Comparei o frontmatter da `main` e do `HEAD`: idêntico. ✅
4. Os commits que tocam `.claude/` e `reviews/README.md` são `9701352` e `9e652d3`, ambos com `Agent: developer`. O `r1-dev-report.md` traz os dois scripts `python3 - <<'EOF'` na íntegra. ✅

## Suíte completa

Sem `CI` e `TEST_DATABASE_URL` no ambiente (`env -u CI -u TEST_DATABASE_URL`), no commit `f90438c`:

```text
uv run ruff check .            -> All checks passed!          (rc=0)
uv run ruff format --check .   -> 24 files already formatted  (rc=0)
uv run pytest -q               -> 268 passed, 3 skipped in 20.38s (rc=0)
  SKIPPED tests/acceptance/test_spec_001.py:174  TEST_DATABASE_URL not set   (CA-04 da SPEC-001, db)
  SKIPPED tests/acceptance/test_spec_022.py:575  TEST_DATABASE_URL not set   (CA-16, db)
  SKIPPED tests/test_db_smoke.py:11              TEST_DATABASE_URL not set   (db)
```

Com o banco temporário e `CI=true` (simulando o CI):

```text
TEST_DATABASE_URL=postgresql://postgres@localhost:55436/partqc_test CI=true uv run pytest -q -rs
-> 271 passed in 21.28s (rc=0), nenhum skip
```

## Bugs encontrados

Nenhum bug de implementação contra a SPEC.

## Testes exploratórios (além dos critérios)

Hook rodado direto, com o processo em `/tmp` e caminhos absolutos:

| Caso | Resultado |
|---|---|
| Python 3.14 (`/usr/bin/python3`) e Python 3.10.22 (uv): `Write` permitido, CA-01 e `Bash` | Mesmo comportamento nas duas versões (0 / 2 `both` / 2 `unknown tool_name 'Bash'`). Compatível com ≥ 3.10 ✅ |
| Ordem §4.1: `{"tool_name":"Bash"}` sem `tool_input`; `tool_input: []` | `event has no tool_input object` (regra 2 antes da 3/4) ✅ |
| Ordem: sem `tool_name` e com as duas chaves | `event has no tool_name string` (regra 3 antes da 5) ✅ |
| `Write` com só `notebook_path: null` | `both` (presença da chave, regra 5 antes da 6) ✅ |
| `tool_name` `WRITE`, `" Write"`, `Read`, `ÉDIT`, `"Wrïte\u0000"`, `["Write"]` | `unknown tool_name` com `repr` (Unicode preservado) ou `no tool_name string` (lista) ✅ |
| Eventos reais com chaves extras (`old_string`/`new_string`, `edits`, `new_source`/`cell_id`/`edit_mode`) | Permitidos (0) ✅ |
| Caminho com acento e espaço (`api/ç ã/x.py`) | Permitido ✅ |
| `api/../.claude/x.py` (developer) | Negado por papel, com o caminho normalizado `.claude/x.py` ✅ |
| `file_path` = `"\t\n"` | `missing or empty for Write` ✅ |
| Chave parecida (`File_Path`) junto do `file_path` | Permitido. A regra 5 é sensível a maiúsculas, como o mapa; não é a outra chave ✅ |
| Stdin `[]`, `null`, vazio | `event is not a JSON object` / `stdin is not valid JSON` ✅ |
| **Chave duplicada no JSON:** `{"tool_name":"Bash",…,"tool_name":"Write"}` | Permitido (0): o `json` do Python fica com o último valor. No sentido inverso, negado. **Observação, não é bug:** a SPEC não trata chaves duplicadas, e o Claude Code gera o evento (não é entrada do agente). Fica registrado para o reviewer avaliar se vale uma nota futura. |

Outras observações (fora dos CAs, sem impacto no veredicto):

- No `ci.yml`, `ports: - 5432:5432` publica a porta em todas as interfaces do runner efêmero do GitHub. A SPEC não pede mudança, e o comentário do YAML já limita o `trust` ao CI. Só registro.
- Os comentários do `ci.yml` e do `.env.example` não citam a variável de senha nem a URL antiga (o CA-10 cobre isso).

## SPEC_ISSUE

**SPEC_ISSUE-01 — RESOLVIDO em `afa4173`** (ver "Reexecução após SPEC_ISSUE-01"). Texto original:

**SPEC_ISSUE-01 (CA-06 contradiz a §4.1/§3.2).** O preâmbulo da §5 define que "'stderr contém X' significa que o stderr contém `guard_paths: blocked: X`". Aplicado ao CA-06, isso exige `guard_paths: blocked: role 'developer' may not write 'ml/notebooks/train.ipynb'`. Só que a §4.1 ("Todo o resto da §4.6 da SPEC-001 permanece: … mensagem `role '<papel>' may not write '<caminho>'` na negação por papel"), a §3.2 (as mensagens de negação por papel ficam fora do escopo) e o próprio CA-06 ("a negação por papel não mudou") mantêm o formato da SPEC-001 §4.6, **sem** `blocked:`: `guard_paths: role '<papel>' may not write '<caminho relativo>' (SPEC-001, R-07)`.

- Obtido: `guard_paths: role 'developer' may not write 'ml/notebooks/train.ipynb' (SPEC-001, R-07)`, código 2.
- O hook está correto em relação à §4.1/§3.2. O CA-06, lido ao pé da letra com o preâmbulo, não pode ser cumprido sem violar a §3.2.
- O teste de aceite verifica o formato inalterado da SPEC-001 (código 2 e a linha completa acima) e passa. A divergência fica explicada na docstring do teste. O teste não foi ajustado a um comportamento errado: ele segue o formato que a SPEC manda preservar.
- Correção sugerida (architect): restringir o preâmbulo da §5 aos CAs com mensagens de `GuardError` (CA-01…CA-04), ou reescrever o CA-06 como "o stderr contém `guard_paths: role 'developer' may not write 'ml/notebooks/train.ipynb'`". Nenhuma mudança de código é necessária. Na r2, basta reexecutar este teste.

Pela regra do papel (CA impossível de testar como está escrito → `SPEC_ISSUE` → FAIL), o veredicto da primeira emissão foi **FAIL**, apesar de todos os testes passarem. Ele foi substituído pelo veredicto da reexecução abaixo.

## Reexecução após SPEC_ISSUE-01

O architect corrigiu a SPEC no commit `afa4173` (`Agent: architect`), e o humano reaprovou a correção (`820f8bb`, `Agent: orchestrator`, `Blocked` → `In Test`, ainda na r1). O preâmbulo da §5 ficou assim: a leitura "stderr contém X" = `guard_paths: blocked: X` vale só para os CA-01 a CA-04; no CA-06, X aparece literalmente, no formato inalterado da SPEC-001 §4.6, sem `blocked:`. Nenhum CA, requisito ou comportamento mudou.

- **Coerência dos testes com o texto atual:**
  - Reli a §5. Os CA-01 a CA-04 continuam conferindo `guard_paths: blocked: <mensagem>`.
  - O CA-06 confere o código 2 e o texto literal `role 'developer' may not write 'ml/notebooks/train.ipynb'`, além da linha completa no formato da SPEC-001 §4.6 (`guard_paths: role … (SPEC-001, R-07)`).
  - As citações `>` da §4.3/§4.4 não mudaram, então `test_texts_match_spec_quotes` segue válido sem ajuste.
  - A única alteração em `tests/acceptance/test_spec_022.py` foi a docstring do CA-06, que deixou de citar o SPEC_ISSUE como aberto. As asserções não mudaram.
- **Código:** `git diff --stat 4f9f9ab 820f8bb` mostra só `docs/specs/SPEC-022-manutencao-setup.md`. Nenhum arquivo de produção, CI, README ou `.env.example` mudou, então não refiz o CA-16 com contêiner. O resultado anterior (`1 passed`, nenhum skip, na porta temporária 55436) continua valendo, e a verificação na porta 55432 segue como pendência manual do humano.
- **Suíte, sem `CI` e sem `TEST_DATABASE_URL`, sobre `820f8bb` + docstring:**

```text
uv run ruff check .            -> All checks passed!          (rc=0)
uv run ruff format --check .   -> 24 files already formatted  (rc=0)
uv run pytest -q -rs           -> 268 passed, 3 skipped in 19.65s (rc=0)
  SKIPPED tests/acceptance/test_spec_001.py:174  TEST_DATABASE_URL not set   (db)
  SKIPPED tests/acceptance/test_spec_022.py:574  TEST_DATABASE_URL not set   (CA-16, db)
  SKIPPED tests/test_db_smoke.py:11              TEST_DATABASE_URL not set   (db)
uv run pytest -q tests/acceptance/test_spec_022.py -> 38 passed, 1 skipped (CA-16, db)
```

**Veredicto final da r1: PASS.**
- Todos os CAs automatizáveis (CA-01 a CA-16) têm teste e passam; o CA-16 passou contra o Postgres em `trust` temporário.
- A suíte inteira passa e o ruff está limpo.
- O CA-18 foi conferido.
- Não há bugs nem SPEC_ISSUE abertos.
- Pendências manuais: o CA-17, no PR, e o CA-16 na porta 55432, depois que o humano recriar o `partqc-pg`.

## Pendências manuais

- CA-16 na porta 55432: recriar o `partqc-pg` (humano), como descrito acima.
- CA-17: conferir o workflow `ci` verde no PR, sem `SKIPPED … TEST_DATABASE_URL not set` no log do `uv run pytest -q`.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` (`tests/acceptance/test_spec_022.py` novo; `tests/acceptance/test_spec_001.py`, CA-20, por atribuição da §3.1) e este relatório.
- [x] O contêiner `partqc-pg` não foi alterado; o temporário `partqc-pg-spec022-tester` foi removido.
