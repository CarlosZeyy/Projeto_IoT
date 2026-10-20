# SPEC-033 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-033](../../docs/specs/SPEC-033-hook-worktree.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `0e45413` (código do hook em `3ee9d66`) |
| **Veredicto** | **PASS** |

## Cobertura dos critérios de aceite

Arquivo: `tests/acceptance/test_spec_033.py` (63 testes coletados: 31 de CA e 32 extras). Todos os testes de hook seguem o preâmbulo da §5: repositório `R` com um commit em `tmp_path`, cópia do hook em `R/.claude/hooks/guard_paths.py`, `git -C R worktree add R/.claude/worktrees/wt -b wt` e `python3 <cópia> --role <papel>` com o evento no stdin. O `git` roda com identidade local ao comando e sem configuração global ou de sistema (`GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`). Toda escrita, link ou remoção passa antes por `_inside(tmp_path, ...)`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `tests/acceptance/test_spec_033.py::test_ca01_worktree_paths_judged_by_role_table` (as 12 linhas da tabela; nas negações por papel, confere também o formato completo `guard_paths: role ... (SPEC-001, R-07)`) | ✅ |
| CA-02 | `::test_ca02_relative_path_with_cwd_in_worktree` | ✅ |
| CA-03 | `::test_ca03_not_a_worktree_of_this_repo_fails_closed` (9 casos: 1 comum, 2 clone, 3 alheia, 4 falsa, 5 link, 6 caminho aninhado sem worktree, 6 worktree real de `R` criada dentro de `W`, 7 raiz `wt`, 7 `x.py`) | ✅ |
| CA-04 | `::test_ca04_worktree_git_metadata_denied` (`W/.git` e `R/.git/worktrees/wt/HEAD`) | ✅ |
| CA-05 | `::test_ca05_symlinks_inside_worktree_do_not_loosen` | ✅ |
| CA-06 | `::test_ca06_spec001_hook_tests_still_pass`, `::test_ca06_spec022_hook_tests_still_pass` (pytest em subprocesso só com o caminho do arquivo e a seleção `-k` do CA, sem `CI` e sem `TEST_DATABASE_URL`, §6 e `docs/architecture.md` §10), `::test_ca06_hook_imports_only_stdlib_and_no_subprocess` (`ast`: só `sys.stdlib_module_names`, sem `subprocess`, sem `__import__`/`import_module`) | ✅ |
| CA-07 | `::test_ca07_gitignore_and_readme` (`git check-ignore --no-index -q`: 0 e 1; `.claude/worktrees/` na seção do README até o próximo título) | ✅ |
| CA-08 (manual) | Executado pelo **orquestrador** (o tester não pode criar subagentes). Evidência abaixo, transcrita sem alteração. | ✅ |

### CA-08 (manual): evidência registrada pelo orquestrador

Executado pelo orquestrador, e não pelo tester. Texto recebido, sem alteração:

> CA-08 (manual), executado pelo orquestrador em 2026-10-19 ~22:55 (-03), na pasta principal com a branch spec/SPEC-033-hook-worktree no commit 1166ecc (hook novo carregado de $CLAUDE_PROJECT_DIR):
> 1. `git worktree add --detach .claude/worktrees/teste-hook HEAD`, equivalente a `claude --worktree teste-hook` para o hook (mesma estrutura: `.git` → `.git/worktrees/teste-hook`).
> 2. O subagente `developer`, com a ferramenta Write, tentou criar `.claude/worktrees/teste-hook/docs/specs/teste.md` e `.claude/worktrees/teste-hook/api/teste_hook.txt`.
> 3. Resultado: o primeiro foi BLOQUEADO com `guard_paths: role 'developer' may not write 'docs/specs/teste.md' (SPEC-001, R-07)`; o segundo foi CRIADO em `.claude/worktrees/teste-hook/api/teste_hook.txt` (conteúdo "probe").
> 4. O arquivo foi apagado e a worktree, removida com `git worktree remove`.
> Diferença em relação ao roteiro: a sessão paralela foi simulada com `git worktree add` dentro desta sessão, e não com `claude --worktree`. O hook depende só da estrutura da worktree e do caminho, que são os mesmos.

Nota do tester: o código do hook não mudou entre `1166ecc` (commit do CA-08) e `0e45413` (commit testado); o commit seguinte só muda o status da SPEC.

## Suíte completa

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
...
SKIPPED [1] ml/tests/test_parity.py:53: no local ml/models/*/model.onnx (the real model is not in Git)
4891 passed, 22 skipped, 1 warning in 300.88s (0:05:00)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
211 files already formatted
```

Os 22 pulos são de `torch` ausente e do modelo ONNX local (fora do Git), os mesmos do dev-report (4828 + os 63 testes novos = 4891).

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

### Automatizados no arquivo de aceite (`test_extra_*`)

Cobrem requisitos da §4.1 sem CA próprio e a regra "nada mais muda" da §2. Todos passam.

| Teste | O que verifica | Resultado |
|---|---|---|
| `test_extra_bad_gitfile_fails_closed` (11 casos) | `W/.git` vazio, `gitdir:` sem caminho, `gitdir: ` vazio, prefixo em maiúsculas, binário (não UTF-8), byte NUL, `gitdir` apontando para o `.git` principal, para `.git/worktrees` em si, para um filho inexistente, para `/` e para `/dev/null` | negado com a mensagem da worktree |
| `test_extra_gitfile_size_limit_4096` | worktree real com `.git` completado até 4096 bytes é aceita; com 4097, negada (limite da condição 3) | ok |
| `test_extra_huge_gitfile_fails_closed_fast` | `.git` esparso de 64 MiB: negado em menos de 10 s, sem ler o arquivo todo | ok |
| `test_extra_gitfile_as_directory_or_fifo_fails_closed` | `.git` como diretório e como FIFO: negado, e o FIFO não trava o hook (timeout de 10 s) | ok |
| `test_extra_unreadable_gitfile_fails_closed` | `.git` com permissão 000: `OSError` vira a mensagem da worktree (item 5) | ok |
| `test_extra_back_pointer_must_match` | cópia byte a byte e hard link do `.git` real de `wt` em outra pasta: negados pela condição 5 | ok |
| `test_extra_main_git_not_a_directory_fails_closed` | hook com `PROJECT_ROOT` numa worktree (`.git` em arquivo): nada sob `.claude/worktrees/` é aceito (condição 2); a sessão aberta na própria worktree mantém o comportamento antigo (`api/x.py` 0, `docs/rules.md` negado, `.git` negado), como diz a §3.2 | ok |
| `test_extra_stale_worktree_fails_closed` | pasta da worktree apagada com `.git/worktrees/<id>` ainda presente: negado | ok |
| `test_extra_suffixed_admin_dir_and_unicode_name_accepted` | `.git/worktrees/dup1` (sufixo numérico, §7) aceito; nome com espaço e acento (`inspeção ç`) aceito, com arquivo `ação.py`; worktree fora de `.claude/worktrees/` continua "outside the project root" (§3.2) | ok |
| `test_extra_dotdot_resolved_before_rules` (8 casos) | `..` voltando para `wt`, para o checkout principal (`docs/specs` negado, `api` aceito), por pasta inexistente, para fora de `R`, para `.claude/worktrees/x.py`, para `W/.git/config` e para uma worktree aninhada: cada um recebe a decisão do caminho resolvido | ok |
| `test_extra_worktree_rights_equal_main_checkout_rights` (6 papéis × 14 caminhos) | dentro da worktree válida, cada papel recebe exatamente o mesmo código **e o mesmo stderr** que recebe no checkout principal para o mesmo relativo (incluindo `.claude/hooks/tests/acceptance/t.py` e `reviews/SPEC-033/r1-test-report.md`) | ok |
| `test_extra_tester_acceptance_loophole_closed` | o tester é negado em `.claude/worktrees/nope/**/tests/acceptance/**`, em `.claude/worktrees/tests/acceptance/t.py` e na versão aninhada em `W`; continua aceito em `**/tests/acceptance/**` no checkout principal e na worktree válida; `.claude/worktreesx/...` e `x/.claude/worktrees/...` não caem na regra nova | ok |

### Teste de mutação dos testes de aceite (no scratchpad, sem tocar no hook do repositório)

Rodei uma cópia de `test_spec_033.py` (sem os CA-06, que usam o hook do repositório) contra o hook da `main` e contra 8 mutantes do hook novo:

| Hook | Resultado |
|---|---|
| hook da `main` | 52 falhas, 8 passam |
| sem a condição 5 (ponteiro de volta) | 3 falhas |
| sem o `lstat`/regular/tamanho | 2 falhas (o caso FIFO estoura o timeout, ou seja, o hook travaria) |
| sem o item 4 (aninhada) | 5 falhas |
| sem "filho direto de `.git/worktrees`" | 2 falhas |
| sem a condição 2 | 1 falha |
| sem a condição 1 | 2 falhas |
| limite `>=` em vez de `>` (4096) | 2 falhas |
| sem o `except` (item 5) | 7 falhas |

Todos os mutantes são detectados.

### Exploração de segurança (no scratchpad)

- **O tester não ganhou acesso fora das worktrees válidas.** Comparação diferencial em processo entre o hook da `main` e o hook novo, para os 6 papéis e todos os caminhos de 1 a 4 segmentos formados com `api`, `docs`, `specs`, `adr`, `rules.md`, `ml`, `tests`, `acceptance`, `reviews`, `SPEC-1`, `r1-test-report.md`, `r1-dev-report.md`, `.claude`, `hooks`, `infra`, `.github`, `x.py`, `.git`, `..`, `worktreesx`, `claude`: **1.225.224 decisões, 0 diferenças** (decisão e mensagem). Somado ao `test_extra_worktree_rights_equal_main_checkout_rights`, a única mudança de acesso é a esperada: numa worktree válida, cada papel tem os direitos que tem no checkout principal; qualquer outra coisa sob `.claude/worktrees/` passou a ser negada (antes o tester passava em `**/tests/acceptance/**` ali).
- **Worktree falsa:** pasta comum, `.git` diretório (clone), worktree de outro repositório, `gitdir` para fora, para o `gitdir` de `wt` sem ponteiro de volta, `gitdir` passando por um link simbólico em `.git/worktrees/alias` → `wt` (o `realpath` dá `wt`, e a condição 5 nega): todos negados.
- **Links simbólicos:** `.git` como link (negado); `G/gitdir` como link (negado; o hook é mais estrito que a SPEC, que pede só "arquivo regular" — decisão 3 do dev-report, que só nega o que o `git` não produz); `R/.claude/worktrees` como link para fora (negado como "outside the project root"); `R/.claude/worktrees/evil` → `W` (julgado como `wt`, com a mesma tabela: `docs/rules.md` negado, `api/x.py` aceito); `R/.claude/worktrees/toapi` → `R/api` (o `realpath` leva para `api/tests/acceptance/...` no checkout principal, que o tester já podia escrever diretamente; não é afrouxamento).
- **Conteúdo do `.git`:** CRLF e linhas extras depois da primeira são aceitos (primeira linha, §4.1 condição 3); BOM, dois espaços depois de `gitdir:` e espaço no fim do caminho são negados (fail closed; o `git` não grava assim).
- **`gitdir` relativo** (`worktree.useRelativePaths=true`, git 2.56): `../../../.git/worktrees/rel` e ponteiro de volta `../../../.claude/worktrees/rel/.git` são aceitos e julgados pela tabela (decisão 2 do dev-report). Não afrouxa: forjar o ponteiro de volta exige escrever em `.git/`, que o hook nega.
- **Caminho relativo + `cwd`:** `cwd` numa pasta comum de `.claude/worktrees/` é negado; `cwd=R` com `.claude/worktrees/wt/api/x.py` é aceito (mesma regra do absoluto, o `cwd` não decide a raiz, §7).
- **Python:** com `python3.10`, `python3.12` e o `python3` do sistema (3.14), `W/api/x.py` dá 0 e `.claude/worktrees/zz/tests/acceptance/t.py` (tester) dá 2 com a mensagem da worktree.

### Observações (não são bugs desta SPEC)

- **O-01 (informativa, fora do escopo):** a comparação dos segmentos `.claude`/`worktrees` é sensível a maiúsculas, e o `os.path.realpath` não normaliza a caixa. Num sistema de arquivos insensível a maiúsculas (macOS, Windows), `R/.Claude/Worktrees/x/tests/acceptance/t.py` escaparia da regra nova e o tester passaria pela regra antiga `**/tests/acceptance/**`. O projeto roda em Linux (ext4, sensível), onde isso é outra pasta e não foi possível reproduzir. A §4.1 define a regra por segmentos exatos, então o hook cumpre a SPEC; fica o registro para o architect, se quiser tratar (a SPEC-032 já trata variantes de maiúsculas no `.gitignore`).
- **O-02 (informativa):** entre o `lstat` e o `open` de `W/.git` há uma janela (TOCTOU) em que um FIFO poderia substituir o arquivo e travar o hook. Explorá-la exige escrever em `W/.git` em paralelo, o que só o `Bash` faria (limitação já documentada da SPEC-001). Não reproduzível pelas ferramentas que o hook guarda.

## Ajustes em testes de aceite de SPECs anteriores

Nenhum. Os testes de aceite da SPEC-001 e da SPEC-022 passam sem alteração.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
