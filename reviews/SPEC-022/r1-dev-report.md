# SPEC-022 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-022](../../docs/specs/SPEC-022-manutencao-setup.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-022-manutencao-setup` |
| Commits | `ebef2a0`, `07a912c`, `38c5f07` (+ o commit deste relatório) |

## Resumo

- **Hook (RV-01):** `target_path()` agora escolhe o campo pelo `tool_name`, com um mapa fixo que diferencia maiúsculas: `Write`/`Edit`/`MultiEdit` → `file_path` e `NotebookEdit` → `notebook_path`. Ela falha fechada, na ordem da §4.1, quando falta `tool_name`, quando o `tool_name` é desconhecido, quando as duas chaves de caminho estão presentes (basta a chave existir) e quando o campo esperado está vazio. A docstring do módulo foi atualizada. `ROLES` não mudou.
- **Postgres sem senha:** o CI usa `POSTGRES_HOST_AUTH_METHOD: trust` e `TEST_DATABASE_URL=postgresql://postgres@localhost:5432/partqc_test`. O `.env.example` e o README ("Testes de banco") usam a URL sem senha, com a porta publicada só em `127.0.0.1` e uma nota para recriar o contêiner antigo.
- **Processo:** atualizei a seção `## Commits` de `.claude/agents/architect.md`, acrescentei o parágrafo "Commits do architect" em `reviews/README.md` e coloquei a nota de workspace trust no README. Os textos são exatamente os da SPEC.
- Testes unitários novos e atualizados em `tests/test_guard_paths.py`, `tests/test_ci_workflow.py` e `tests/test_repo_config.py`.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `.claude/hooks/guard_paths.py` (`target_path`, `PATH_FIELD_BY_TOOL`, `OTHER_PATH_FIELD`) | `tests/test_guard_paths.py::test_notebook_edit_ignores_allowed_file_path_rv01` |
| CA-02 | idem | `tests/test_guard_paths.py::test_both_path_keys_present_fail_closed` (os 5 casos do CA + `MultiEdit` com `notebook_path=null` + `NotebookEdit` com os dois preenchidos) |
| CA-03 | idem | `tests/test_guard_paths.py::test_tool_name_missing_or_unknown_fail_closed` (ausente, `42`, `null`, lista, `Bash`, `write`, `""`, `WRITE`, `" Write"`, `Read`) |
| CA-04 | idem | `tests/test_guard_paths.py::test_expected_field_missing_or_empty_fail_closed` |
| CA-01…04 (ordem da §4.1) | idem | `tests/test_guard_paths.py::test_checks_run_in_spec_order`, `::test_target_path_in_process` |
| CA-05 | idem | `tests/test_guard_paths.py::test_well_formed_events_still_allowed` (os 8 casos do CA) |
| CA-06 | idem (negação por papel sem mudança) | `tests/test_guard_paths.py::test_role_denial_unchanged_for_well_formed_notebook_edit` |
| CA-07 | idem (só biblioteca padrão) | `tests/test_guard_paths.py::test_hook_imports_only_stdlib`; os CA-11…17 da SPEC-001 passam (38 passed, ver abaixo) |
| CA-08 | `.github/workflows/ci.yml` | `tests/test_ci_workflow.py::test_postgres_service_uses_trust_without_password`, `::test_ci_file_has_no_password_material`, `::test_env`, `::test_runner_and_postgres_service` |
| CA-09 | `.env.example` | `tests/test_repo_config.py::test_env_example_has_test_database_block`, `::test_no_postgres_password_material[.env.example]`, `::test_env_example_has_no_secret_values` |
| CA-10 | `.github/workflows/ci.yml`, `.env.example`, `README.md` | Por arquivo: `tests/test_ci_workflow.py::test_ci_file_has_no_password_material`, `tests/test_repo_config.py::test_no_postgres_password_material[README.md]`. A varredura de todo o `git ls-files` é teste de aceite (tester). Ver a nota sobre `tests/acceptance/test_spec_001.py` abaixo. |
| CA-11 | `README.md` ("Testes de banco") | `tests/test_repo_config.py::test_readme_local_postgres_is_trust_on_loopback` |
| CA-12 | `README.md` ("Hook de guarda de caminhos") | `tests/test_repo_config.py::test_readme_workspace_trust_note_before_limitation` (conferi também a igualdade literal com a citação da SPEC por script; ver "Como rodar") |
| CA-13 | `.claude/agents/architect.md` (só `## Commits`) | `tests/test_repo_config.py::test_architect_commits_section_names_the_orchestrator`, `::test_agent_frontmatter_has_guard_hook[architect]` |
| CA-14 | `reviews/README.md` (só o parágrafo novo) | `tests/test_repo_config.py::test_reviews_readme_documents_architect_commits` |
| CA-15 | todo o repositório | comandos rodados (ver "Checagens do autor") |
| CA-16 | `README.md` (comando do contêiner) | verificação manual com contêiner separado (ver abaixo) |
| CA-17 | `.github/workflows/ci.yml` | manual, no PR (orquestrador/humano) |
| CA-18 | — | manual (reviewer). Comandos `Bash` da exceção registrados abaixo |

Mutação: rodei os testes novos de `tests/test_guard_paths.py` contra a versão do hook da `main`, e 30 deles falharam (comando abaixo). Depois restaurei o hook novo e os 116 voltaram a passar.

## Exceção de caminhos (SPEC-022 §4.5): comandos `Bash` usados, na íntegra

Diretório de trabalho: raiz do repositório (`/home/carlos/Área de trabalho/Projeto_IoT_AI_Agent`). Não usei `Write`/`Edit` em nenhum arquivo de `.claude/**` nem em `reviews/README.md`.

### 1. `.claude/hooks/guard_paths.py` (commit `ebef2a0`)

```bash
cd "/home/carlos/Área de trabalho/Projeto_IoT_AI_Agent" && python3 - <<'EOF'
from pathlib import Path

path = Path(".claude/hooks/guard_paths.py")
text = path.read_text(encoding="utf-8")

old_doc = '''Reads the PreToolUse event JSON from stdin, takes the target path from
``tool_input.file_path`` (Write, Edit, MultiEdit) or ``tool_input.notebook_path``
(NotebookEdit) and decides whether ``<role>`` may write there.

* allowed -> exit 0, no output;
* denied  -> exit 2, reason on stderr (Claude Code shows it to the agent and blocks the call).

It fails closed (exit 2) on invalid JSON, missing path, missing/unknown role, a path outside the
project root or a path inside ``.git/``.
'''
new_doc = '''Reads the PreToolUse event JSON from stdin, picks the path field from ``tool_name``
(SPEC-022 §4.1, case-sensitive): ``tool_input.file_path`` for Write, Edit and MultiEdit,
``tool_input.notebook_path`` for NotebookEdit; then decides whether ``<role>`` may write there.

* allowed -> exit 0, no output;
* denied  -> exit 2, reason on stderr (Claude Code shows it to the agent and blocks the call).

It fails closed (exit 2) on invalid JSON, missing/unknown role, a path outside the project root,
a path inside ``.git/`` and on every ambiguous event: no ``tool_input`` object, no ``tool_name``
string, a ``tool_name`` outside the map above, both ``file_path`` and ``notebook_path`` keys
present in ``tool_input`` (whatever their values), or the expected field missing, not a string,
empty or only whitespace.
'''
assert text.count(old_doc) == 1
text = text.replace(old_doc, new_doc)

old_fn = '''def target_path(event: object) -> str:
    """Extract the raw target path from a PreToolUse event."""
    if not isinstance(event, dict):
        raise GuardError("event is not a JSON object")
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        raise GuardError("event has no tool_input object")
    for key in ("file_path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise GuardError("tool_input has no file_path or notebook_path")
'''
new_fn = '''# Path field read for each tool (SPEC-022 §4.1). Exact, case-sensitive names: any other
# tool_name is denied.
PATH_FIELD_BY_TOOL: dict[str, str] = {
    "Write": "file_path",
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "NotebookEdit": "notebook_path",
}
# The field of the other kind of tool: none of the four tools sends it, so its key being present
# (with any value, even null or "") makes the event malformed.
OTHER_PATH_FIELD: dict[str, str] = {
    "file_path": "notebook_path",
    "notebook_path": "file_path",
}


def target_path(event: object) -> str:
    """Extract the raw target path from a PreToolUse event (SPEC-022 §4.1).

    Checks run in this order and the first failure raises GuardError: event not an object,
    no ``tool_input`` object, no ``tool_name`` string, unknown ``tool_name``, both path keys
    present, expected field missing/not a string/empty/whitespace.
    """
    if not isinstance(event, dict):
        raise GuardError("event is not a JSON object")
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        raise GuardError("event has no tool_input object")
    tool_name = event.get("tool_name")
    if not isinstance(tool_name, str):
        raise GuardError("event has no tool_name string")
    field = PATH_FIELD_BY_TOOL.get(tool_name)
    if field is None:
        raise GuardError(f"unknown tool_name {tool_name!r}")
    if OTHER_PATH_FIELD[field] in tool_input:
        raise GuardError("tool_input has both file_path and notebook_path")
    value = tool_input.get(field)
    if not isinstance(value, str) or not value.strip():
        raise GuardError(f"tool_input.{field} missing or empty for {tool_name}")
    return value
'''
assert text.count(old_fn) == 1
text = text.replace(old_fn, new_fn)
path.write_text(text, encoding="utf-8")
EOF
python3 -m py_compile .claude/hooks/guard_paths.py && echo COMPILED && uv run pytest -q tests/test_guard_paths.py 2>&1 | tail -3 && git diff --stat
```

Teste de mutação: troquei o hook pela versão da `main`, rodei os testes, restaurei a versão nova e rodei de novo. O arquivo final é idêntico ao gerado pelo script acima; `$S` é o scratchpad da sessão, fora do repositório.

```bash
cd "/home/carlos/Área de trabalho/Projeto_IoT_AI_Agent" && S=/tmp/claude-1000/-home-carlos--rea-de-trabalho-Projeto-IoT-AI-Agent/4ca9163a-19f5-4333-abc6-a2d1881b3358/scratchpad && mkdir -p $S && cp .claude/hooks/guard_paths.py $S/new_hook.py && git show main:.claude/hooks/guard_paths.py > .claude/hooks/guard_paths.py && uv run pytest -q tests/test_guard_paths.py 2>&1 | tail -2; cp $S/new_hook.py .claude/hooks/guard_paths.py && git diff --stat && uv run pytest -q tests/test_guard_paths.py 2>&1 | tail -1
```

Resultado: `30 failed, 86 passed` com o hook da `main` e `116 passed` com o hook novo.

### 2. `.claude/agents/architect.md` e `reviews/README.md` (commit `38c5f07`)

```bash
cd "/home/carlos/Área de trabalho/Projeto_IoT_AI_Agent" && python3 - <<'EOF'
from pathlib import Path

# .claude/agents/architect.md: only the body of "## Commits" (SPEC-022 §4.3)
p = Path(".claude/agents/architect.md")
t = p.read_text(encoding="utf-8")
old = (
    "## Commits\n\n"
    "Todo commit seu termina com o trailer `Agent: architect` (linha própria no fim da mensagem, "
    "junto de `Refs: SPEC-XXX`). Sem esse trailer, o reviewer não consegue verificar a separação "
    "de papéis (R-07).\n\n## "
)
new = (
    "## Commits\n\n"
    "Você não tem shell (`Bash`), então não faz commits. Quem commita os seus arquivos é o "
    "**orquestrador** (sessão principal), com os trailers `Refs: SPEC-XXX` e `Agent: architect`, "
    "cada um em linha própria no fim da mensagem. Esse commit contém só os arquivos que você "
    "escreveu, sem misturar arquivos de outro papel. Sem esse trailer, o reviewer não consegue "
    "verificar a separação de papéis (R-07).\n\n## "
)
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8")

# reviews/README.md: new paragraph right after "**Rastreio de papéis:**" (SPEC-022 §4.3)
p = Path("reviews/README.md")
lines = p.read_text(encoding="utf-8").split("\n")
idx = [i for i, line in enumerate(lines) if line.startswith("**Rastreio de papéis:**")]
assert len(idx) == 1
i = idx[0]
assert lines[i + 1] == ""
paragraph = (
    "**Commits do architect:** o `architect` não tem shell, então quem commita os arquivos dele é "
    "o orquestrador, com `Agent: architect` e `Refs: SPEC-XXX`. Esse commit é esperado e não é "
    "desvio de papel, desde que contenha só arquivos de `docs/` (exceto `docs/rules.md` sem pedido "
    "explícito do humano) e nenhum arquivo de outro papel. As mudanças de status feitas pelo "
    "próprio orquestrador vão em commits separados, com `Agent: orchestrator`."
)
lines[i + 1 : i + 1] = ["", paragraph]
p.write_text("\n".join(lines), encoding="utf-8")
EOF
git diff --stat && git diff
```

Resultado: `git diff --stat main...HEAD -- .claude/ reviews/README.md` mostra só `.claude/agents/architect.md` (1 linha trocada, fora do frontmatter, na linha 39), `.claude/hooks/guard_paths.py` e `reviews/README.md` (+2 linhas). `ROLES` não aparece no diff do hook.

## Como rodar e verificar

```bash
uv sync --all-packages
uv run pytest -q tests/test_guard_paths.py tests/test_ci_workflow.py tests/test_repo_config.py
```

**CA-16 (verificação local).** O contêiner `partqc-pg` que já existia foi criado com senha e ocupa a porta 55432 em `0.0.0.0`. Não mexi nele. Para verificar, criei um contêiner **separado**, com outro nome e outra porta, usando o mesmo comando da §4.2 (`trust`, só em loopback), rodei o teste e o removi em seguida:

```bash
docker run -d --name partqc-pg-spec022 -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=partqc_test -p 127.0.0.1:55433:5432 postgres:16
TEST_DATABASE_URL=postgresql://postgres@localhost:55433/partqc_test uv run pytest -q -rs tests/test_db_smoke.py
# -> 1 passed in 0.08s, nenhum skip
docker rm -f partqc-pg-spec022
```

Com a URL na porta 55432, o CA-16 exige recriar o `partqc-pg` (`docker rm -f partqc-pg` + o `docker run` do README). Não fiz isso porque o orquestrador pediu para preservar o contêiner existente. A decisão fica com o tester e o humano.

Conferi a igualdade literal dos textos exigidos (CA-12, CA-13 e CA-14) com as citações da própria SPEC, por um script `python3` só de leitura: `CA-13 body True`, `CA-14 True`, `CA-12 True`. O frontmatter do architect continua `architect / Read, Grep, Glob, Write, Edit, WebSearch, WebFetch / inherit / purple / ['criar-spec', 'criar-adr']`.

## Decisões tomadas dentro do escopo da SPEC

- Duas constantes novas no hook: `PATH_FIELD_BY_TOOL` (o mapa da §4.1) e `OTHER_PATH_FIELD` (o campo "do outro tipo" usado na regra 5). Ambas são usadas só por `target_path()`.
- No `ci.yml`, mantive `POSTGRES_USER: postgres`, que a §4.2 permite. O health check (`pg_isready -U postgres -d partqc_test`) não mudou. O comentário do YAML diz que o `trust` vale só para o contêiner efêmero do CI e não cita o nome da variável de senha.
- No README, a explicação da porta em `127.0.0.1` e a nota do contêiner antigo (com `docker rm -f partqc-pg`) ficaram em parágrafos logo depois do bloco de comandos de "Testes de banco".
- Os testes unitários que conferem a ausência de `postgres:postgres@` e da variável de senha montam as sequências por concatenação. Eles cobrem `ci.yml`, `.env.example` e `README.md`. A varredura de todo o repositório (CA-10) fica no teste de aceite do tester.

## SPEC_ISSUE (se houver)

Nenhum.

Observação (não é SPEC_ISSUE, porque a §3.1 já prevê): até o tester atualizar `tests/acceptance/test_spec_001.py`, `test_ca20_env_example` falha, porque ainda espera a URL com senha no `.env.example`. Pelo mesmo motivo, a linha 536 desse arquivo ainda contém `postgres:postgres@`, o que faria o CA-10 falhar. Pela §3.1, a troca é do `tester` desta SPEC, e eu não toquei em `tests/acceptance/`.

## Checagens do autor

Rodadas com `CI` e `TEST_DATABASE_URL` fora do ambiente (`env -u CI -u TEST_DATABASE_URL`):

- [x] `uv run ruff check .`: `All checks passed!` (rc=0)
- [x] `uv run ruff format --check .`: `23 files already formatted` (rc=0)
- [x] `uv run pytest -q`: `1 failed, 229 passed, 2 skipped`. A única falha é a `tests/acceptance/test_spec_001.py::test_ca20_env_example`, esperada e prevista na §3.1 (ver acima). Sem ela (`--deselect`): `229 passed, 2 skipped`.
- [x] CA-07: `uv run pytest -q tests/acceptance/test_spec_001.py -k "ca11 or ca12 or ca13 or ca14 or ca15 or ca16 or ca17"`: `38 passed, 16 deselected` (rc=0)
- [x] Testes unitários do autor passando (`tests/test_guard_paths.py`: 116; `tests/test_ci_workflow.py` + `tests/test_repo_config.py`: todos)
- [x] `.env.example` atualizado (nenhuma variável nova; só o valor de `TEST_DATABASE_URL`)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhum arquivo de `.claude/**` além de `guard_paths.py` e `architect.md` alterado; `ROLES` e frontmatter intactos
