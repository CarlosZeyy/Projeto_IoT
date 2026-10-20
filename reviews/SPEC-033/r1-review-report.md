# SPEC-033 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-033](../../docs/specs/SPEC-033-hook-worktree.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `main...a7faaf6` (`main` = `origin/main` = `bdf377c`) |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

O veredicto vale para o código, os testes e a documentação do diff. O RV-01 não pede rodada nova, mas afeta o portão de merge: ver a seção "CA-08".

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | média | `reviews/SPEC-033/r1-test-report.md:24-37` (CA-08 em `docs/specs/SPEC-033-hook-worktree.md:109`) | O CA-08 não foi executado como está escrito. O CA pede uma "sessão paralela real" aberta com `claude --worktree teste-hook`, com saída da sessão no passo 4. O orquestrador fez uma variante: `git worktree add --detach` dentro da própria sessão e o subagente `developer` chamado dali. A variante prova a decisão do hook, com o harness real, o frontmatter real e uma worktree real. Ela não prova o ambiente de uma sessão `--worktree`: a confiança (workspace trust) da pasta da worktree, que decide se os hooks de subagente rodam (precedente do CA-23 da SPEC-001), os agentes carregados da worktree e o valor do `$CLAUDE_PROJECT_DIR`. Esse ambiente é a premissa da §1. Além disso, o ADR-016 (condição 4) diz que "o orquestrador não executa nem marca um CA manual que caiba ao humano", e o ADR-016 e a skill `features` dizem que o orquestrador não testa. Os passos 1 e 4 (abrir e sair de uma sessão nova do Claude Code) só cabem ao humano. A troca de procedimento também não passou por reaprovação da SPEC. Não é defeito do código, e o registro é transparente: a diferença está declarada. | Antes do merge, o humano executa o CA-08 literal. São uns 2 minutos: `claude --worktree teste-hook`, os dois `Write` pelo `developer`, a limpeza e a remoção da worktree. O resultado, com quem executou, vai para o PR (ou para uma nota do tester no test-report). A alternativa é o humano declarar no PR que aceita a variante como cumprimento do CA-08. Até uma das duas, o CA-08 conta como pendente para a condição 4 da R-09/ADR-016. Para SPECs futuras, o architect pode dizer no CA manual quem o executa. |
| RV-02 | baixa | `.claude/hooks/guard_paths.py:204-209` | O-02 do tester. Entre o `os.lstat` e o `open` há uma janela em que um FIFO pode substituir o `W/.git`. O `open` bloquearia, e um hook que estoura o timeout do Claude Code não bloqueia a chamada, ou seja, falha aberta. Para explorar, é preciso escrever em `W/.git` em paralelo, o que só o `Bash` faz, e o `Bash` já está fora do alcance do hook (limitação documentada). | Endurecimento barato, para uma SPEC futura do hook: abrir com `O_NOFOLLOW \| O_NONBLOCK` e conferir `stat.S_ISREG(os.fstat(fd).st_mode)` no descritor aberto, em vez de confiar só no `lstat` anterior. |
| RV-03 | baixa | `.claude/hooks/guard_paths.py:266` | O-01 do tester. A comparação `(".claude", "worktrees")` é sensível a maiúsculas. Num sistema de arquivos insensível (macOS, Windows), `.Claude/Worktrees/x/tests/acceptance/t.py` escapa da regra nova, e o tester passa por `**/tests/acceptance/**`. A classe do problema é anterior a esta SPEC: todos os globs de `ROLES` são sensíveis a maiúsculas. Num FS insensível, `.CLAUDE/hooks/...` já escapava de `.claude/**` para o developer. O hook cumpre a §4.1, que define segmentos exatos. A dupla usa Linux (ext4). | Fora desta SPEC. Se a dupla for usar macOS ou Windows, abrir uma SPEC que normalize a caixa (`os.path.normcase` ou `casefold` nos segmentos) para o hook inteiro, e não só para a regra de worktree. |
| RV-04 | baixa | `tests/test_guard_paths.py:443-444` | O `git()` dos testes unitários herda o ambiente inteiro do processo, inclusive `GIT_DIR`, `GIT_WORK_TREE` e `GIT_INDEX_FILE`. Se a suíte rodar dentro de um hook do git ou de outro processo que exporte essas variáveis, o `git init`/`commit` desses testes pode agir sobre o repositório do projeto, e não sobre o `tmp_path`. Isso contraria a §6 ("nunca no repositório do projeto"). O helper do tester (`tests/acceptance/test_spec_033.py`, `_git_env`) já remove `GIT_*` e isola `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_NOSYSTEM`. Não ocorre no CI nem no uso atual. | Numa próxima mudança desse arquivo: passar `env=` sem as chaves `GIT_*` e com `GIT_CONFIG_GLOBAL=os.devnull` e `GIT_CONFIG_NOSYSTEM=1`, como o helper do tester. |

Contagem: 0 bloqueantes, 0 altas, 1 média, 3 baixas.

## Pontos pedidos pelo orquestrador

### Exceção de caminhos da §4.3

- `git diff --stat main...HEAD -- .claude/` mostra só `.claude/hooks/guard_paths.py` (76 inserções, 1 remoção, que é a linha da docstring de `relative_to_root`).
- `git diff main...HEAD -- .claude/ | grep -E '^[+-].*(ROLES|def target_path)'` não retorna nada: o dicionário `ROLES`, `target_path()`, as mensagens por papel, `_parse_role`, `_deny` e `main` estão intocados.
- Reproduzi os dois scripts `python3 - <<'EOF'` do dev-report, na íntegra, sobre o hook da `main` copiado para o scratchpad. O resultado é **byte a byte igual** ao hook do `HEAD`, e o hook não mudou entre `3ee9d66` e `HEAD`. Os comandos do relatório são exatamente os que produziram o commit. O terceiro bloco (mutação) restaura o arquivo, e o `git diff --stat -- .claude/` vazio que o dev-report registra é coerente.
- Mudanças além do texto literal da §3.1: `import stat`, que é da biblioteca padrão e é necessário para o `S_ISREG`, e a docstring de `relative_to_root`, que é parte da própria função autorizada. Considero as duas dentro do escopo.
- O commit `3ee9d66` só toca o hook, com `Agent: developer` e `Refs: SPEC-033`.

### Falha fechada

- Condições 1 a 5 da §4.1: cada uma levanta `GuardError(WORKTREE_ERROR)`, e `OSError`/`ValueError` dentro do `try` viram a mesma mensagem (item 5). Uma `GuardError` levantada dentro do `try` não é `OSError` nem `ValueError` e sobe intacta. O `except Exception` de `main()` e o `except BaseException` do `__main__` seguem cobrindo o resto, com código 2.
- A checagem de "worktree dentro de worktree" (item 4) usa segmentos e vem antes do retorno. A checagem de `.git` roda sobre o relativo da worktree, então `W/.git` é negado (CA-04).
- Conferi à mão, num repositório temporário com git 2.56 (só leitura no projeto): uma worktree absoluta aceita; uma worktree com `worktree.useRelativePaths=true` aceita e julgada pela tabela (`docs/rules.md` negado); `W/.git` negado; aninhada negada; `..` saindo de uma worktree para outra válida julgado pela de destino; `git worktree move` continua aceito, porque o git reescreve os dois ponteiros; uma pasta renomeada sem o git (ponteiro de volta velho) é negada.
- Leitura de `W/.git`: `lstat` sem seguir link, arquivo regular, `st_size ≤ 4096`, `O_NOFOLLOW` no `open`, leitura limitada a 4097 bytes e UTF-8 estrito. Ela recusa link, diretório, FIFO (sem travar, com a ressalva do RV-02), arquivo enorme e binário. A comparação final usa `realpath` dos dois lados, e o `dirname(G) == realpath(.git/worktrees)` impede que um link em `.git/worktrees/<alias>` afrouxe a regra.

### As decisões do autor

1. **Ponteiro de volta relativo resolvido a partir de `G`.** Correto. Confirmei que o git 2.56 grava `G/gitdir` = `../../../.claude/worktrees/rel/.git`, relativo ao próprio `G`, e `W/.git` = `gitdir: ../../../.git/worktrees/rel`, relativo a `W`. Isso é o que o `write_worktree_linking_files` do git faz. Não afrouxa nada: forjar o ponteiro exige escrever em `.git/`, que o hook nega a todos os papéis. É o preenchimento de uma lacuna pequena da condição 5 ("com `realpath`", sem base), registrado no dev-report, com uma regra simétrica à da condição 4. O caso padrão (absoluto) não depende dele. Não vejo `SPEC_ISSUE`.
2. **Leitura estrita de `G/gitdir`.** É mais estrita que "arquivo regular" e só nega o que o `git worktree add` não produz: falha fechada. Ok.
3. **`ValueError` capturado.** É superclasse de `UnicodeDecodeError` e cobre o `realpath` com byte NUL no `gitdir`. O resultado continua sendo código 2. Só muda a mensagem, de `unexpected error ValueError` para a da worktree, que é a que o item 5 pede para erros de leitura. O bloco `try` só tem operações de caminho e leitura, então não há risco de esconder um bug com um código de saída diferente. Ok.
4. **Posição da docstring.** O parágrafo `GIT WORKTREES` vem depois de `KNOWN LIMITATION` e antes da nota da biblioteca padrão. Atende à §4.1 item 7 e preserva o `test_hook_documents_bash_limitation` (nota nos primeiros 2000 caracteres). Ok.

### Observações O-01 e O-02 do tester

As duas são procedentes e estão fora do escopo da §4.1. Viraram o RV-03 e o RV-02, de severidade baixa, com sugestão para uma SPEC futura. Nenhuma das duas pode ser explorada pelas ferramentas que o hook guarda (`Write`/`Edit`/`MultiEdit`/`NotebookEdit`) no ambiente da dupla (Linux). Além disso, o conteúdo de `.claude/worktrees/` está no `.gitignore`, então uma escrita indevida ali não chega a um commit pelo `git add` comum.

### CA-08 executado pelo orquestrador

Ver o RV-01. Resumo: a evidência é boa para a lógica do hook. A forma literal do CA (sessão `claude --worktree`) é do humano, segundo a condição 4 do ADR-016, e cobre a premissa de ambiente que a variante não cobre: trust e hooks numa sessão aberta na worktree. Não é motivo para rodada nova. É uma pendência de merge, a menos que o humano aceite a variante explicitamente no PR.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | §4.1 itens 1 a 7, §4.2 e §4.3 implementados. Nenhum CA alterado pelo autor. A rastreabilidade CA → arquivo/teste está no dev-report. As decisões fora do texto literal estão registradas no dev-report e não criam regra nova. Nenhuma reaprovação delegada (ADR-019) nesta branch: os commits do orquestrador em `docs/specs/` só mudam `Status`/`Rodada`. O procedimento do CA-08 foi trocado sem reaprovação (RV-01). |
| 2. Regras inegociáveis | ✅ | R-01, R-02, R-04, R-05, R-06, R-11 e R-12: N/A (nenhuma dependência nova, só biblioteca padrão no hook). R-03: nenhum segredo no diff; a única URL é `postgresql://postgres@localhost:55432/partqc_test`, sem senha, como no precedente da SPEC-022. R-07: os 8 commits têm `Agent:`. Produção (`3ee9d66`, `9b0954f`), testes unitários (`503018d`) e dev-report (`1166ecc`) são do `developer`. `tests/acceptance/test_spec_033.py` e o test-report (`d5a6c6b`) são do `tester`. Os commits do `orchestrator` mexem só em status (`docs/plan.md` e o cabeçalho da SPEC). Ninguém cruzou a fronteira. R-13: todos os commits são de `Carlos Moises <179777237+CarlosZeyy@users.noreply.github.com>`, em Conventional Commits, e o diff não cita empresa nem ferramenta corporativa. |
| 3. Corretude | ✅ | Bordas cobertas: raiz da worktree, `.claude/worktrees` sozinho, `x.py` solto, caminho relativo + `cwd`, `..`, links dentro e fora da worktree, `gitdir` relativo, CRLF, nome com espaço e acento, sufixo numérico em `.git/worktrees/`, worktree velha ou movida. Sem `except Exception: pass`. Itens de HTTP, async e datas: N/A. Ressalvas de baixa severidade: RV-02 e RV-03. |
| 4. Testes | ✅ | Test-report PASS, cobrindo CA-01 a CA-07 com testes que exercitam o hook real copiado para um repositório temporário. O tester mostra que todos os 8 mutantes são detectados, e o autor mostra 49 falhas com o hook da `main`. O CA-06 roda o pytest em subprocesso só com o caminho explícito do arquivo e `-k`, sem banco (`docs/architecture.md` §10). Nenhum ajuste em testes de aceite de SPECs anteriores, e o diff não toca nenhum. Sem rede externa. Suíte que rodei: `CI=true TEST_DATABASE_URL=... uv run pytest -q` → `4891 passed, 22 skipped`. O CA-08 está registrado, mas não na forma literal (RV-01). Isolamento do git nos testes unitários: RV-04. |
| 5. Qualidade | ✅ | `uv run ruff check .` → `All checks passed!`; `uv run ruff format --check .` → `211 files already formatted`. Função nova pequena e comentada por condição; type hints presentes. O README tem o parágrafo **Worktrees:** com os pontos (a), (b) e (c) da §4.2, e o `.gitignore` tem a linha na seção certa. |
| 6. Segurança | N/A (tag) / ✅ (aplicada por pedido) | Sem tag `security`/`deploy`. Mesmo assim, revisei como controle de R-07. Falha fechada em todas as condições, sem `subprocess`, sem `git` e só biblioteca padrão (o CA-06 confere por `ast`). Nenhum papel ganha direito fora de uma worktree válida: o tester comparou 1.225.224 decisões entre o hook antigo e o novo, sem diferença fora de `.claude/worktrees/`. Dentro de uma worktree válida, cada papel tem os mesmos direitos que tem no checkout principal. A brecha do tester em `.claude/worktrees/<x>/**/tests/acceptance/**` foi fechada. Ressalvas: RV-02 e RV-03 (baixas). |

## Pontos positivos

- A detecção estrutural replica exatamente o que o `git worktree add` grava, sem `subprocess`. A checagem do ponteiro de volta (condição 5) é a que impede uma pasta de "se passar" por worktree com um `.git` copiado ou com hard link (`test_extra_back_pointer_must_match`).
- A exceção de caminhos da §4.3 foi usada com disciplina: scripts com `assert text.count(old) == 1` para cada substituição, comandos na íntegra no dev-report e resultado reproduzível byte a byte.
- O tester foi além dos CAs: comparação diferencial antigo × novo em mais de 1,2 milhão de decisões, mutação do hook com 8 mutantes, casos de FIFO e de arquivo esparso de 64 MiB com timeout, e cuidado com `_inside(tmp_path, ...)` antes de qualquer escrita.
- Os testes isolam a identidade do git por comando (R-13), e os de aceite também isolam a configuração global e de sistema.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
