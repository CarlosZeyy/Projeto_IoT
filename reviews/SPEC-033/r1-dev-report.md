# SPEC-033 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-033](../../docs/specs/SPEC-033-hook-worktree.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-033-hook-worktree` |
| Commits | `3ee9d66`, `503018d`, `9b0954f` (+ o commit deste relatório) |

## Resumo

- **Hook (§4.1):** em `relative_to_root()`, depois do cálculo do relativo à `PROJECT_ROOT` e antes da checagem de `.git`, um caminho que começa com `.claude/worktrees/` passa pela função nova `_worktree_relative()`. Ela confere as condições 1 a 5 da §4.1 (arquivo `.git` da worktree, `gitdir` filho direto de `.git/worktrees/` e ponteiro de volta) e devolve o resto do caminho depois de `.claude/worktrees/<nome>/`. Qualquer condição que falhe, uma worktree dentro de worktree ou um erro de leitura resultam em `GuardError("path is inside .claude/worktrees/ but not inside a git worktree of this repository")`. A partir daí, a checagem de `.git` e a tabela de papéis são as de sempre. A docstring do módulo cita a regra e a nova falha fechada. `ROLES`, `target_path()`, as mensagens por papel e o resto do hook não mudaram.
- **`.gitignore`:** a linha `.claude/worktrees/` na seção `# --- Claude Code (local) ---`.
- **README:** um parágrafo **Worktrees:** na seção `### Hook de guarda de caminhos (R-07)`, com os pontos (a), (b) e (c) da §4.2.
- **Testes unitários:** 56 casos novos em `tests/test_guard_paths.py`, todos rodados em repositórios e worktrees criados em `tmp_path`, com `git -c user.name=... -c user.email=...` locais ao comando.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `.claude/hooks/guard_paths.py` (`_worktree_relative`, `relative_to_root`) | `tests/test_guard_paths.py::test_worktree_path_judged_relative_to_worktree_root` (os 12 casos do CA, mais 2) |
| CA-02 | idem | `::test_worktree_relative_path_with_cwd` |
| CA-03.1 | idem | `::test_plain_folder_under_worktrees_denied` (pasta existente e pasta ainda inexistente) |
| CA-03.2 | idem | `::test_nested_clone_denied` |
| CA-03.3 | idem | `::test_worktree_of_another_repository_denied` |
| CA-03.4 | idem | `::test_fake_gitfile_pointing_to_another_worktree_denied` |
| CA-03.5 | idem | `::test_symlinked_gitfile_denied` |
| CA-03.6 | idem | `::test_worktree_inside_worktree_denied` (uma worktree real de `R` dentro de `W` e uma pasta comum) |
| CA-03.7 | idem | `::test_worktree_root_and_loose_files_denied` (`wt`, `x.py` e `.claude/worktrees`, para tester e developer) |
| CA-04 | idem (a checagem de `.git` agora vê o relativo da worktree) | `::test_git_metadata_of_worktree_denied` |
| CA-05 | idem (o `realpath` vem antes de tudo) | `::test_symlinks_inside_worktree_do_not_loosen` |
| CA-06 | idem (só biblioteca padrão, sem `subprocess`) | `::test_hook_imports_only_stdlib` (já existente), `::test_hook_does_not_import_subprocess`; seleções da SPEC-001 e da SPEC-022 passando (ver abaixo) |
| CA-07 | `.gitignore`, `README.md` | `::test_gitignore_and_readme_cover_worktrees` |
| CA-08 | — | manual (tester) |
| §4.1 item 2 (condições 2, 3 e 5) e item 5 (erros de leitura) | `.claude/hooks/guard_paths.py` | `::test_bad_gitfile_fails_closed` (11 conteúdos: vazio, sem caminho, prefixo errado, não UTF-8, mais de 4096 bytes, `.git` principal, a própria `.git/worktrees`, filho inexistente, byte NUL), `::test_gitfile_directory_or_unreadable_fails_closed` (`.git` como diretório e sem permissão de leitura), `::test_bad_back_pointer_fails_closed`, `::test_symlinked_back_pointer_fails_closed`, `::test_main_git_not_a_directory_fails_closed` |
| §4.1 item 7 (docstring) | idem | `::test_hook_documents_worktree_rule`, `::test_hook_documents_bash_limitation` (já existente) |
| Outros | idem | `::test_main_checkout_unchanged_next_to_worktree`, `::test_relative_gitdir_paths_accepted`, `::test_gitfile_with_crlf_accepted`, `::test_worktree_with_space_and_accent`, `::test_worktree_relative_in_process` (inclui `.claude/worktreesx/` e `x/.claude/worktrees/`, que não são caminhos de worktree) |

**Mutação:** com o hook da `main` no lugar, 49 dos 172 testes de `tests/test_guard_paths.py` falham; com o hook novo, os 172 passam (comando abaixo).

**Python 3.10:** rodei o hook copiado para um repositório temporário com `python3.10`, `python3.12` e o `python3` do sistema (3.14). Nos três, `W/api/x.py` deu 0, `W/docs/rules.md` deu 2 com a negação por papel e `.claude/worktrees/zz/tests/acceptance/t.py` (tester) deu 2 com a mensagem nova.

## Exceção de caminhos (SPEC-033 §4.3): comandos `Bash` usados, na íntegra

Diretório de trabalho: raiz do repositório (`/home/carlos/Área de trabalho/Projeto_IoT_AI_Agent`). Não usei `Write`/`Edit` em nenhum arquivo de `.claude/**`. O resultado final está no commit `3ee9d66`.

### 1. Patch do hook

```bash
cd "/home/carlos/Área de trabalho/Projeto_IoT_AI_Agent" && python3 - <<'EOF'
from pathlib import Path

path = Path(".claude/hooks/guard_paths.py")
text = path.read_text(encoding="utf-8")

old_doc = '''It fails closed (exit 2) on invalid JSON, missing/unknown role, a path outside the project root,
a path inside ``.git/`` and on every ambiguous event: no ``tool_input`` object, no ``tool_name``
string, a ``tool_name`` outside the map above, both ``file_path`` and ``notebook_path`` keys
present in ``tool_input`` (whatever their values), or the expected field missing, not a string,
empty or only whitespace.
'''
new_doc = '''It fails closed (exit 2) on invalid JSON, missing/unknown role, a path outside the project root,
a path inside ``.git/`` and on every ambiguous event: no ``tool_input`` object, no ``tool_name``
string, a ``tool_name`` outside the map above, both ``file_path`` and ``notebook_path`` keys
present in ``tool_input`` (whatever their values), or the expected field missing, not a string,
empty or only whitespace.

GIT WORKTREES (SPEC-033 §4.1): Claude Code keeps ``$CLAUDE_PROJECT_DIR`` on the main checkout
when a session runs in a worktree under ``.claude/worktrees/<name>/``. A target there is judged
with its path relative to the root of that worktree, but only when ``<name>`` is a git worktree
of this repository: the main ``.git`` is a directory, ``<name>/.git`` is a small regular UTF-8
file (not a symlink) whose first line is ``gitdir: <dir>``, ``<dir>`` resolves to a direct child
of ``.git/worktrees/`` and that child's ``gitdir`` file points back to ``<name>/.git``. Any other
path under ``.claude/worktrees/`` (a plain folder, a nested clone, a worktree of another
repository, a fake or symlinked ``.git``, the worktree root itself, a worktree inside a worktree)
and any read error while checking it fail closed with "path is inside .claude/worktrees/ but not
inside a git worktree of this repository". No ``git`` executable and no subprocess are used.
'''
assert text.count(old_doc) == 1
text = text.replace(old_doc, new_doc)

old_imports = "import re\nimport sys\n"
new_imports = "import re\nimport stat\nimport sys\n"
assert text.count(old_imports) == 1
text = text.replace(old_imports, new_imports)

old_fn = '''def relative_to_root(raw_path: str, cwd: object, root: Path = PROJECT_ROOT) -> str:
    """Resolve the target (`..`, symlinks) and return it as a POSIX path relative to root."""
'''
new_fn = '''# Git worktrees of Claude Code sessions live in `.claude/worktrees/<name>/` (SPEC-033 §4.1).
WORKTREES_PREFIX = (".claude", "worktrees")
WORKTREE_ERROR = (
    "path is inside .claude/worktrees/ but not inside a git worktree of this repository"
)
GITFILE_MAX_BYTES = 4096


def _worktree_relative(rel_parts: list, real_root: str) -> str:
    """Map `.claude/worktrees/<name>/<rest>` to `<rest>` when `<name>` is a git worktree of root.

    Structural check of what `git worktree add` writes (SPEC-033 §4.1, conditions 1 to 5); any
    failed condition, nested worktree or read error raises GuardError (fail closed).
    """

    def read_first_line(file_path: str) -> str:
        # Regular file, not a symlink, at most GITFILE_MAX_BYTES, strict UTF-8.
        info = os.lstat(file_path)
        if not stat.S_ISREG(info.st_mode) or info.st_size > GITFILE_MAX_BYTES:
            raise GuardError(WORKTREE_ERROR)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        with open(file_path, "rb", opener=lambda p, f: os.open(p, f | nofollow)) as handle:
            data = handle.read(GITFILE_MAX_BYTES + 1)
        if len(data) > GITFILE_MAX_BYTES:
            raise GuardError(WORKTREE_ERROR)
        return data.decode("utf-8").split("\\n", 1)[0].rstrip("\\r")

    if len(rel_parts) < 4:  # 1. something after `<name>`
        raise GuardError(WORKTREE_ERROR)
    worktree = os.path.join(real_root, *WORKTREES_PREFIX, rel_parts[2])
    try:
        # 2. the main checkout has a `.git` directory
        if not os.path.isdir(os.path.join(real_root, ".git")):
            raise GuardError(WORKTREE_ERROR)
        # 3. `<name>/.git` is a gitfile: `gitdir: <dir>`
        dot_git = os.path.join(worktree, ".git")
        line = read_first_line(dot_git)
        if not line.startswith("gitdir: ") or not line[len("gitdir: ") :]:
            raise GuardError(WORKTREE_ERROR)
        # 4. `<dir>` (relative to the worktree) is a direct child of `.git/worktrees/`
        gitdir = os.path.realpath(os.path.join(worktree, line[len("gitdir: ") :]))
        admin_dir = os.path.realpath(os.path.join(real_root, ".git", "worktrees"))
        if os.path.dirname(gitdir) != admin_dir or not os.path.isdir(gitdir):
            raise GuardError(WORKTREE_ERROR)
        # 5. `<dir>/gitdir` points back to `<name>/.git` (relative to `<dir>` if not absolute)
        back = read_first_line(os.path.join(gitdir, "gitdir"))
        if not back or os.path.realpath(os.path.join(gitdir, back)) != os.path.realpath(dot_git):
            raise GuardError(WORKTREE_ERROR)
    except (OSError, ValueError) as exc:  # ValueError includes UnicodeDecodeError
        raise GuardError(WORKTREE_ERROR) from exc
    rest = rel_parts[3:]
    if tuple(rest[:2]) == WORKTREES_PREFIX:  # 4.1 item 4: no worktree inside a worktree
        raise GuardError(WORKTREE_ERROR)
    return "/".join(rest)


def relative_to_root(raw_path: str, cwd: object, root: Path = PROJECT_ROOT) -> str:
    """Resolve the target (`..`, symlinks) and return it as a POSIX path relative to root.

    A target inside a git worktree in `.claude/worktrees/<name>/` is returned relative to that
    worktree's root (SPEC-033 §4.1); any other path under `.claude/worktrees/` is denied.
    """
'''
assert text.count(old_fn) == 1
text = text.replace(old_fn, new_fn)

old_tail = '''    if rel_posix == "." or rel_posix == ".." or rel_posix.startswith("../"):
        raise GuardError("path is outside the project root")
    if ".git" in rel_posix.split("/"):
'''
new_tail = '''    if rel_posix == "." or rel_posix == ".." or rel_posix.startswith("../"):
        raise GuardError("path is outside the project root")
    rel_parts = rel_posix.split("/")
    if tuple(rel_parts[:2]) == WORKTREES_PREFIX:
        rel_posix = _worktree_relative(rel_parts, real_root)
    if ".git" in rel_posix.split("/"):
'''
assert text.count(old_tail) == 1
text = text.replace(old_tail, new_tail)
path.write_text(text, encoding="utf-8")
EOF
python3 -m py_compile .claude/hooks/guard_paths.py && echo COMPILED && uv run pytest -q tests/test_guard_paths.py 2>&1 | tail -3 && git diff --stat
```

Resultado: `COMPILED` e `1 failed, 115 passed`. A falha foi `test_hook_documents_bash_limitation`, que procura `NOT intercepted` nos primeiros 2000 caracteres do arquivo. O parágrafo novo da docstring tinha empurrado a nota da limitação para depois disso.

### 2. Reposicionar o parágrafo da docstring (depois de `KNOWN LIMITATION`)

```bash
cd "/home/carlos/Área de trabalho/Projeto_IoT_AI_Agent" && python3 - <<'EOF'
from pathlib import Path

path = Path(".claude/hooks/guard_paths.py")
text = path.read_text(encoding="utf-8")
start = text.index("\nGIT WORKTREES (SPEC-033 §4.1)")
end = text.index("\nKNOWN LIMITATION:")
block = text[start:end]  # "\nGIT WORKTREES ... repository\". No ``git`` ... used.\n"
text = text[:start] + text[end:]
anchor = "\nStandard library only and compatible with Python >= 3.10"
assert text.count(anchor) == 1
text = text.replace(anchor, block + anchor)
path.write_text(text, encoding="utf-8")
EOF
python3 -m py_compile .claude/hooks/guard_paths.py && sed -n 1,50p .claude/hooks/guard_paths.py && uv run pytest -q tests/test_guard_paths.py 2>&1 | tail -2
```

Resultado: `116 passed`. Depois, `uv run ruff check` e `uv run ruff format --check` no hook ficaram limpos, e o hook foi commitado (`3ee9d66`).

### 3. Teste de mutação (troca temporária pelo hook da `main` e restauração)

`$S` é o scratchpad da sessão, fora do repositório.

```bash
cd "/home/carlos/Área de trabalho/Projeto_IoT_AI_Agent" && uv run ruff check tests/test_guard_paths.py && uv run ruff format --check tests/test_guard_paths.py && uv run pytest -q tests/test_guard_paths.py 2>&1 | tail -2 && S=/tmp/claude-1000/-home-carlos--rea-de-trabalho-Projeto-IoT-AI-Agent/0bd4884d-5d8f-4e6c-8a2a-b32acbb6728a/scratchpad && cp .claude/hooks/guard_paths.py $S/new_hook.py && git show main:.claude/hooks/guard_paths.py > .claude/hooks/guard_paths.py && uv run pytest -q tests/test_guard_paths.py 2>&1 | tail -1; cp $S/new_hook.py .claude/hooks/guard_paths.py && git diff --stat -- .claude/ && uv run pytest -q tests/test_guard_paths.py 2>&1 | tail -1
```

Resultado: `172 passed`, depois `49 failed, 123 passed` com o hook da `main`, `git diff --stat -- .claude/` vazio (o hook restaurado é idêntico ao commitado) e `172 passed`.

Conferência para o reviewer: `git diff --stat main...HEAD -- .claude/` mostra só `.claude/hooks/guard_paths.py` (76 inserções, 1 remoção, que é a linha da docstring de `relative_to_root`). No diff, nenhuma linha `+`/`-` contém `ROLES` nem `def target_path`.

## Como rodar e verificar

```bash
uv run pytest -q tests/test_guard_paths.py
uv run pytest -q tests/acceptance/test_spec_001.py -k "ca11 or ca12 or ca13 or ca14 or ca15 or ca16 or ca17"   # 38 passed
uv run pytest -q tests/acceptance/test_spec_022.py -k "ca01 or ca02 or ca03 or ca04 or ca05 or ca06"           # 27 passed
git check-ignore --no-index -q .claude/worktrees/wt/api/x.py; echo $?   # 0
git check-ignore --no-index -q .claude/hooks/guard_paths.py; echo $?    # 1
git diff --stat main...HEAD -- .claude/
```

## Decisões tomadas dentro do escopo da SPEC

1. **Uma só função nova.** A §3.1 permite "uma função nova chamada por" `relative_to_root()`. Por isso, a leitura dos dois arquivos (`W/.git` e `G/gitdir`) é uma função aninhada (`read_first_line`) dentro de `_worktree_relative()`, e não outra função do módulo. Constantes novas: `WORKTREES_PREFIX`, `WORKTREE_ERROR` e `GITFILE_MAX_BYTES`. O único import novo é `stat`, da biblioteca padrão, usado para conferir "arquivo regular" sobre o resultado do `os.lstat`.
2. **Ponteiro de volta relativo (condição 5).** A SPEC diz "a primeira linha, com `realpath`", sem dizer a base de um caminho relativo. Com `worktree.useRelativePaths=true`, opção do git 2.48 em diante, o git grava `G/gitdir` relativo ao próprio `G`. Conferi isso no git 2.56 local: `../../../.claude/worktrees/rel/.git`. Por isso, um caminho relativo é resolvido a partir de `G`, do mesmo jeito que a condição 4 resolve a partir de `W`. O caminho absoluto, que é o padrão do git e o caso dos CAs, não muda. Teste: `test_relative_gitdir_paths_accepted`. Se o architect preferir negar o caminho relativo, a mudança é de uma linha.
3. **`G/gitdir` lido com as mesmas regras de `W/.git`.** Ou seja: `lstat` sem seguir link, arquivo regular, até 4096 bytes e UTF-8 estrito. A SPEC pede só "arquivo regular", então isso é mais estrito, e só nega casos que o `git worktree add` não produz. Teste: `test_symlinked_back_pointer_fails_closed`.
4. **`ValueError` também vira a mensagem da worktree.** O §4.1 item 5 cita `OSError` e `UnicodeDecodeError`. Capturei `ValueError`, que é a superclasse de `UnicodeDecodeError` e também é o erro do `realpath` quando o `gitdir` contém um byte NUL. Assim, esse caso sai com a mensagem da worktree, e não com `unexpected error ValueError`. O código continua 2 nos dois casos.
5. **Primeira linha:** o texto até o primeiro `\n`, sem um `\r` final (arquivo com CRLF). `gitdir:` sem caminho ou com o caminho vazio é negado.
6. **`.claude/worktrees` sozinho** (dois segmentos) cai na regra 2, porque os dois primeiros segmentos casam, e falha na condição 1. A checagem de "worktree dentro de worktree" (item 4) também usa segmentos, então pega `.claude/worktrees/<x>` e o próprio `.claude/worktrees` dentro de `W`.
7. **Condição 2** usa `os.path.isdir`, como no texto (segue link). A condição 4 compara com `realpath(.git/worktrees)`, então um link no `.git` principal não afrouxa nada.
8. **Docstring:** o parágrafo `GIT WORKTREES` ficou depois de `KNOWN LIMITATION`. Assim, a nota da limitação do `Bash` continua nos primeiros 2000 caracteres, que é o que o teste existente `test_hook_documents_bash_limitation` confere.
9. **README:** o parágrafo **Worktrees:** fica entre **Workspace trust:** e **Limitação:**, na mesma seção.

## SPEC_ISSUE (se houver)

Nenhum. Para o reviewer: a decisão 2 completa uma lacuna pequena do texto da condição 5, e eu a registrei aqui em vez de parar porque o caso padrão (caminho absoluto) não depende dela.

Nenhum teste de aceite de SPEC anterior falhou.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos (`All checks passed!`, `210 files already formatted`)
- [x] Testes unitários do autor passando (`tests/test_guard_paths.py`: 172 passed)
- [x] Suíte inteira: `CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q` → `4828 passed, 22 skipped, 1 warning in 291.14s`. Os pulos são de `torch` ausente e do modelo ONNX local, que não está no Git.
- [x] `.env.example` sem mudança (nenhuma variável nova)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhum teste novo roda a suíte inteira em subprocesso; repositórios e worktrees só em `tmp_path`, com identidade git local ao comando (R-13)
