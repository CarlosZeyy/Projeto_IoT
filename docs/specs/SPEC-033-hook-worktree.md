# SPEC-033: Manutenção do setup: hook de guarda de caminhos em git worktree

| Campo | Valor |
|---|---|
| Status | In Test |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | infra |
| Depende de | SPEC-022 (e SPEC-001) |
| Semana alvo | S2 (antes de rodar duas sessões do loop em paralelo) |
| Requisitos cobertos | R-07 (hook de guarda e rastreio de papéis), RNF-08 |
| ADRs relevantes | ADR-010 (Python 3.12 + uv; exceção do `python3` do sistema para o hook), ADR-011 (loop de agentes), ADR-015 (git e PRs) |

## 1. Contexto

O hook `.claude/hooks/guard_paths.py` (SPEC-001 §4.6, SPEC-022 §4.1) calcula o caminho do arquivo **relativo à raiz do projeto** e aplica a tabela de papéis (`ROLES`) a esse caminho. A raiz é `PROJECT_ROOT = Path(__file__).resolve().parents[2]`, e o hook é chamado como `python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guard_paths.py" --role <papel>`, ou seja, a raiz é a do checkout principal.

O Claude Code cria as worktrees de sessões paralelas em `.claude/worktrees/<nome>/`, na raiz do repositório, e, depois que a sessão entra numa worktree, o `${CLAUDE_PROJECT_DIR}` dos hooks **continua** apontando para o checkout principal; só o campo `cwd` do evento segue a worktree (<https://code.claude.com/docs/en/worktrees>, seções "Start Claude in a worktree" e "Hook paths don't follow the worktree", consultada pelo architect em 2026-10-19).

Resultado: um arquivo da worktree, por exemplo `.claude/worktrees/wt/api/src/qc_api/main.py`, chega ao hook como o caminho relativo `.claude/worktrees/wt/api/...`. A regra `.claude/**` nega a escrita ao developer, `docs/**` não casa para o architect, e o loop não consegue rodar em duas sessões paralelas. Pior: o tester **passa** em qualquer `.claude/worktrees/<x>/**/tests/acceptance/**`, mesmo numa pasta que não é worktree, porque o padrão começa com `**`.

Arquitetura: nada muda em `docs/architecture.md` (o hook e o processo do loop estão na SPEC-001, no ADR-011 e em `reviews/README.md`).

## 2. Objetivo

Um arquivo dentro de uma git worktree deste repositório em `.claude/worktrees/<nome>/` é julgado pela tabela de papéis com o caminho relativo à raiz **dessa worktree**; qualquer outro caminho sob `.claude/worktrees/` é negado; e nada mais muda no hook.

## 3. Escopo

### 3.1 Dentro

- `.claude/hooks/guard_paths.py`: só `relative_to_root()` (ou uma função nova chamada por ela), as constantes que ela usar e a docstring do módulo (§4.1). **Exceção de caminho, §4.3.**
- `tests/test_guard_paths.py`: testes unitários dos casos novos (autor).
- `.gitignore`: a linha `.claude/worktrees/` (§4.2).
- `README.md`, seção `### Hook de guarda de caminhos (R-07)`: um parágrafo sobre worktrees (§4.2).
- **Tester:** `tests/acceptance/test_spec_033.py`.

### 3.2 Fora

- A tabela de papéis (`ROLES`), as mensagens de negação por papel, `target_path()`, o frontmatter dos agentes e `.claude/settings.json`: não mudam.
- Worktrees fora de `.claude/worktrees/` (por exemplo, `git worktree add ../outro`): continuam negadas como "fora da raiz". Para trabalhar nelas, a sessão precisa ser aberta na própria worktree, e aí o `$CLAUDE_PROJECT_DIR` e a cópia do hook são os dela.
- Escritas pelo `Bash`: continuam fora do alcance do hook (limitação documentada na SPEC-001).
- Isolar subagentes com `isolation: worktree` no frontmatter: fora desta SPEC (mexe nos agentes).

## 4. Requisitos detalhados

### 4.1 Hook: raiz da worktree

Depois do `realpath` e do cálculo do caminho relativo à `PROJECT_ROOT` de hoje (`rel`), e **antes** da checagem de `.git` e da tabela de papéis:

1. Se o primeiro e o segundo segmentos de `rel` não forem `.claude` e `worktrees`, nada muda: o comportamento é o da SPEC-001/SPEC-022.
2. Se forem, seja `nome` o terceiro segmento e `W = realpath(PROJECT_ROOT) / ".claude" / "worktrees" / nome`. O caminho só é aceito como "dentro de uma worktree" se **todas** as condições abaixo valerem; senão, `GuardError` com a mensagem exata `path is inside .claude/worktrees/ but not inside a git worktree of this repository` (código 2, no formato `guard_paths: blocked: <mensagem> (SPEC-001, R-07)` de hoje):
   1. `rel` tem pelo menos 4 segmentos (há um caminho depois de `<nome>`);
   2. `PROJECT_ROOT/.git` é um **diretório** (o checkout principal);
   3. `W/.git` é um **arquivo regular** (`os.lstat`, sem seguir link), com no máximo 4096 bytes, decodificável em UTF-8, cuja primeira linha é `gitdir: <caminho>`;
   4. `G = realpath(<caminho>)` (relativo a `W`, se não for absoluto) é um diretório filho direto de `realpath(PROJECT_ROOT/.git/worktrees)`;
   5. `G/gitdir` é um arquivo regular cuja primeira linha, com `realpath`, é igual a `realpath(W/.git)` (o ponteiro de volta que o `git worktree add` grava).
3. Aceito, o caminho relativo passa a ser o resto de `rel` depois de `.claude/worktrees/<nome>/`, e daí em diante tudo é como hoje: a checagem de `.git` (que agora pega também `W/.git`, cujo relativo é `.git`) e a tabela de papéis aplicada a esse relativo.
4. Se o relativo da worktree começar de novo com `.claude/worktrees/`, `GuardError` com a mesma mensagem do item 2 (worktree dentro de worktree não é aceita).
5. Qualquer erro de leitura (`OSError`, `UnicodeDecodeError`) nas condições do item 2 vira a mesma `GuardError` (falha fechada). A regra geral "exceção inesperada → código 2" continua.
6. Só biblioteca padrão; compatível com Python ≥ 3.10; nada de `subprocess` nem de `git` (o hook roda com o `python3` do sistema, antes do `.venv` existir, e não pode depender de outro executável).
7. A docstring do módulo passa a citar a regra da worktree e a nova condição de falha fechada.

**Por que a verificação estrutural, e não `git rev-parse --show-toplevel`.** O `git` exigiria `subprocess`, um executável a mais no caminho (sem ele, o hook falharia) e um diretório existente (o `Write` cria arquivos e pastas novas). As condições 2 a 5 são exatamente o que o `git worktree add` grava (`.git` em arquivo na worktree e `gitdir` de volta em `.git/worktrees/<id>/`), e recusam uma pasta comum, um clone aninhado (`.git` em diretório) e uma worktree de outro repositório.

### 4.2 `.gitignore` e README

- `.gitignore`: a linha `.claude/worktrees/`, na seção `# --- Claude Code (local) ---`. A documentação do Claude Code recomenda isso para que o conteúdo das worktrees não apareça como não rastreado no checkout principal (fonte da §1).
- `README.md`, seção `### Hook de guarda de caminhos (R-07)`: um parágrafo dizendo que (a) numa sessão em `.claude/worktrees/<nome>/`, o hook aplica a tabela de papéis ao caminho relativo à raiz da worktree; (b) qualquer outra pasta sob `.claude/worktrees/` é negada; (c) worktrees fora de `.claude/worktrees/` precisam de uma sessão aberta nelas.

### 4.3 Exceção de caminhos desta SPEC

O hook nega ao developer `.claude/**`. Como na SPEC-022 §4.5, o humano autoriza, **somente nesta SPEC**, a alteração de `.claude/hooks/guard_paths.py` (só o que a §4.1 pede; `ROLES` e `target_path()` não mudam), feita pelo `Bash` (por exemplo, `patch -p1` com um diff guardado fora do repositório ou um script `python3 - <<'EOF'`). Os comandos vão, na íntegra, no `r1-dev-report.md`. O commit leva `Agent: developer` e `Refs: SPEC-033`. O reviewer confere com `git diff --stat main...HEAD -- .claude/` que só esse arquivo de `.claude/` mudou e que o dicionário `ROLES` e a função `target_path` não mudaram.

## 5. Critérios de aceite

Nos CAs do hook, o teste cria um repositório git temporário `R` (com pelo menos um commit) **fora** do repositório do projeto, copia `.claude/hooks/guard_paths.py` para `R/.claude/hooks/guard_paths.py` (assim `PROJECT_ROOT` é `R`), cria a worktree com `git -C R worktree add R/.claude/worktrees/wt -b wt` e roda `python3 R/.claude/hooks/guard_paths.py --role <papel>` com o evento no stdin, os caminhos absolutos e `W = R/.claude/worktrees/wt`. "stderr contém X" segue a convenção da SPEC-022 §5: `guard_paths: blocked: X` para os `GuardError` e X literal para a negação por papel.

- **CA-01** — *Dado* os eventos bem formados abaixo, *quando* o hook roda, *então* sai com o código indicado (e, com 2, o stderr contém a mensagem):

  | Papel | Ferramenta | Caminho | Código | Mensagem |
  |---|---|---|---|---|
  | developer | `Write` | `W/api/src/qc_api/main.py` | 0 | — |
  | developer | `Edit` | `W/reviews/SPEC-033/r1-dev-report.md` | 0 | — |
  | developer | `Write` | `W/docs/specs/SPEC-001-setup-repositorio.md` | 2 | `role 'developer' may not write 'docs/specs/SPEC-001-setup-repositorio.md'` |
  | developer | `Write` | `W/.claude/hooks/guard_paths.py` | 2 | `role 'developer' may not write '.claude/hooks/guard_paths.py'` |
  | developer | `Write` | `W/edge/tests/acceptance/test_spec_030.py` | 2 | `role 'developer' may not write 'edge/tests/acceptance/test_spec_030.py'` |
  | tester | `Write` | `W/edge/tests/acceptance/test_spec_030.py` | 0 | — |
  | tester | `Write` | `W/edge/src/qc_edge/app.py` | 2 | `role 'tester' may not write 'edge/src/qc_edge/app.py'` |
  | architect | `Edit` | `W/docs/plan.md` | 0 | — |
  | architect | `Edit` | `W/docs/rules.md` | 2 | `role 'architect' may not write 'docs/rules.md'` |
  | reviewer | `Write` | `W/reviews/SPEC-030/r1-review-report.md` | 0 | — |
  | ml-engineer | `NotebookEdit` | `W/ml/notebooks/train_colab.ipynb` | 0 | — |
  | security-devops | `Write` | `W/infra/compose.yaml` | 0 | — |

- **CA-02** — *Dado* `--role developer` e o evento `{"tool_name":"Write","tool_input":{"file_path":"api/x.py"},"cwd":"<W>"}` (caminho relativo, `cwd` na worktree), *então* o código é 0; e, com `file_path` = `docs/specs/x.md`, o código é 2 e o stderr contém `role 'developer' may not write 'docs/specs/x.md'`.
- **CA-03 (falha fechada)** — *Dado* `--role tester` (o papel que hoje passa por `**/tests/acceptance/**`), *quando* o caminho é cada um dos abaixo, *então* o código é 2 e o stderr contém `path is inside .claude/worktrees/ but not inside a git worktree of this repository`:
  1. `R/.claude/worktrees/comum/x/tests/acceptance/t.py`, com `comum/` uma pasta comum (sem `.git`);
  2. `R/.claude/worktrees/clone/x/tests/acceptance/t.py`, com `clone/` um `git init` (`.git` em diretório);
  3. `R/.claude/worktrees/alheia/x/tests/acceptance/t.py`, com `alheia/` uma worktree de **outro** repositório temporário `R2`;
  4. `R/.claude/worktrees/falsa/x/tests/acceptance/t.py`, com `falsa/.git` um arquivo `gitdir: <R>/.git/worktrees/wt` (aponta para o `gitdir` da worktree `wt`, cujo ponteiro de volta não é `falsa/.git`);
  5. `R/.claude/worktrees/link/x/tests/acceptance/t.py`, com `link/.git` um link simbólico para `W/.git`;
  6. `W/.claude/worktrees/outra/x/tests/acceptance/t.py` (worktree dentro de worktree);
  7. `R/.claude/worktrees/wt` (a própria raiz da worktree) e `R/.claude/worktrees/x.py`.
- **CA-04** — *Dado* `--role developer`, *quando* o caminho é `W/.git` ou `R/.git/worktrees/wt/HEAD`, *então* o código é 2 e o stderr contém `path is inside .git/`.
- **CA-05 (sem afrouxar por link)** — *Dado* `W/docs-link` como link simbólico para `R/docs` e `W/fora` como link para um diretório temporário fora de `R`, *quando* o developer escreve em `W/docs-link/specs/x.md` e em `W/fora/x.py`, *então* os dois saem com 2: o primeiro com `role 'developer' may not write 'docs/specs/x.md'` (o `realpath` leva ao checkout principal) e o segundo com `path is outside the project root`.
- **CA-06 (comportamento antigo)** — *Dado* o hook do repositório, *quando* se rodam `uv run pytest -q tests/acceptance/test_spec_001.py -k "ca11 or ca12 or ca13 or ca14 or ca15 or ca16 or ca17"` (os testes do hook da SPEC-001, a mesma seleção do CA-07 da SPEC-022) e `uv run pytest -q tests/acceptance/test_spec_022.py -k "ca01 or ca02 or ca03 or ca04 or ca05 or ca06"` (caminhos de arquivo explícitos; o CA-07 da SPEC-022 fica de fora porque ele mesmo roda pytest em subprocesso), *então* os dois terminam com código 0; e `.claude/hooks/guard_paths.py`, analisado com `ast`, só importa módulos de `sys.stdlib_module_names` e não importa `subprocess`.
- **CA-07** — *Dado* o `.gitignore`, *então* `git check-ignore --no-index -q .claude/worktrees/wt/api/x.py` dá 0 e `git check-ignore --no-index -q .claude/hooks/guard_paths.py` dá 1; e o trecho do `README.md` entre `### Hook de guarda de caminhos (R-07)` e o próximo título contém `.claude/worktrees/`.
- **CA-08 (manual)** — Sessão paralela real: 1. na raiz, `claude --worktree teste-hook`; 2. pedir que o subagente `developer` crie `docs/specs/teste.md` e `api/teste_hook.txt` na worktree; 3. conferir que o primeiro é negado com `role 'developer' may not write 'docs/specs/teste.md'` e o segundo é criado em `.claude/worktrees/teste-hook/api/teste_hook.txt`; 4. apagar o arquivo, sair da sessão e remover a worktree; 5. registrar o resultado no test-report.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Casos das §4.1 (worktree válida, pasta comum, clone, worktree alheia, `gitdir` falso, link, aninhada, raiz da worktree, erro de leitura) via `subprocess` com `sys.executable`, num repositório temporário | `tests/test_guard_paths.py` |
| Aceite (tester) | Um por CA automatizável (CA-01 a CA-07) | `tests/acceptance/test_spec_033.py` |
| Manual | CA-08 | descrito no CA |

- Os testes criam repositórios e worktrees **só** em `tmp_path`, nunca no repositório do projeto, e usam `git` com `-c user.name=... -c user.email=...` locais ao comando (sem tocar a identidade do repositório, R-13).
- O CA-06 roda o pytest em subprocesso só com caminhos de arquivo explícitos, sem banco e sem incluir teste que rode pytest em subprocesso (`docs/architecture.md` §10).

## 7. Riscos e notas para o implementador

- **Edite o hook primeiro e rode `uv run pytest -q tests/test_guard_paths.py` logo depois.** O hook vale para o próprio developer: um erro de sintaxe faz o `python3` sair com 1, que o Claude Code **não** trata como bloqueio (falha aberta), e um erro de lógica pode bloquear todos os seus `Write`/`Edit` (corrija pelo `Bash`, como na §4.3). É a mesma nota da SPEC-022 §7.
- O `.git/worktrees/<id>/` do checkout principal tem o nome da worktree (ou um sufixo numérico se o nome colidir); por isso a condição 4 aceita qualquer filho direto, e a condição 5 é que garante o par.
- O hook continua sem conhecer o `cwd` do evento para decidir a raiz: a decisão vem do caminho alvo. Assim, um `cd` da sessão não muda a regra.
- O `.gitignore` também é tocado pela SPEC-032 (variantes de maiúsculas). As duas mudanças são em seções diferentes; quem entrar depois resolve o conflito de merge mantendo as duas.

## 8. Definição de pronto

- [ ] Todos os CAs automatizáveis com teste de aceite passando (test-report PASS) e o CA-08 registrado
- [ ] review-report APPROVED
- [ ] CI verde; `ruff` limpo
- [ ] `README.md` e `.gitignore` atualizados
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-19 | SPEC criada (`Draft`). Decisões do architect: (a) detecção estrutural da worktree (arquivo `.git` com `gitdir` dentro de `.git/worktrees/` e o ponteiro de volta), sem `git` nem `subprocess`; (b) só worktrees em `.claude/worktrees/<nome>/` são reconhecidas; (c) toda outra pasta sob `.claude/worktrees/` é negada, o que fecha também a brecha do tester em `**/tests/acceptance/**`; (d) `.claude/worktrees/` no `.gitignore`, como a documentação do Claude Code recomenda; (e) exceção de caminho só para o hook, como na SPEC-022 §4.5. | Problema de processo relatado pelo orquestrador: com o `$CLAUDE_PROJECT_DIR` fixo no checkout principal, os subagentes não conseguem escrever numa worktree, o que impede duas sessões em paralelo | Orquestrador, a pedido do humano |
| 2026-10-19 | Aprovada pelo humano (`Draft` → `Ready`), com as respostas recomendadas às perguntas do architect (comentário do PR #36). Autorizadas a exceção de caminhos da §4.3 (edição do hook) e a linha `.claude/worktrees/` no `.gitignore`. | Aprovação humana | Humano (Carlos) |
