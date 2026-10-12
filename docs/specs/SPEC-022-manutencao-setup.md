# SPEC-022: Manutenção do setup (hook, CI sem senha, commits do architect)

| Campo | Valor |
|---|---|
| Status | Done |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | infra |
| Depende de | SPEC-001 (mergeada no PR #3) |
| Semana alvo | S1 |
| Requisitos cobertos | R-07 (hook de guarda e rastreio de papéis), R-03 e RNF-06 (nenhuma credencial no Git), RNF-09 (ruff + pytest no CI) |
| ADRs relevantes | ADR-010 (Python 3.12 + uv; exceção do `python3` do sistema para o hook), ADR-011 (loop de agentes, trailers `Agent:`), ADR-015 (git/GitHub e PRs) |

## 1. Contexto

A SPEC-001 foi mergeada (PR #3) com quatro pendências pequenas, todas no setup e nenhuma em código de componente:

1. **RV-01** (`reviews/SPEC-001/r1-review-report.md`, severidade média): `target_path()` do hook ignora o `tool_name` e tenta `file_path` antes de `notebook_path`. Um `NotebookEdit` com `notebook_path` proibido e `file_path` permitido passa com código 0, o que contraria a §4.6 da SPEC-001 (campo por ferramenta, falha fechada).
2. **Credencial no repositório público:** o CI e a documentação usam `postgresql://postgres:postgres@...`. É a senha de um contêiner descartável, mas um scanner de segredos que monitora o repositório público acusou o padrão (falso positivo). Com o Postgres de teste em `trust`, a URL fica sem senha e o alerta deixa de existir.
3. **Commits do architect:** o `architect` não tem a ferramenta `Bash` (frontmatter de `.claude/agents/architect.md`), mas o arquivo diz "todo commit seu termina com o trailer `Agent: architect`". Na prática, quem commita é o orquestrador, e isso não está escrito em lugar nenhum que o reviewer consulte.
4. **Workspace trust:** no CA-23 da SPEC-001 (2026-10-12), a escrita proibida passou enquanto a pasta não tinha a confiança aceita no Claude Code e foi bloqueada depois de aceitá-la. A documentação oficial confirma: "Frontmatter hooks in a project subagent run only after you accept the workspace trust dialog for the folder the agent file came from. A `-p` session doesn't count as accepting it." (<https://code.claude.com/docs/en/hooks>, consultado em 2026-10-12).

Arquitetura: nada muda em `docs/architecture.md` (o CI, o hook e o processo do loop estão na SPEC-001, no ADR-011 e em `reviews/README.md`).

## 2. Objetivo

O hook escolhe o campo de caminho pelo `tool_name` e falha fechado em todo evento ambíguo; nenhum arquivo versionado fora de `docs/` e `reviews/` contém senha de Postgres; e o processo documenta quem commita os arquivos do architect e a exigência de workspace trust.

## 3. Escopo

### 3.1 Dentro

- `.claude/hooks/guard_paths.py`: só `target_path()`, as constantes que ela usar e a docstring do módulo (§4.1). **Exceção de caminho, §4.5.**
- `tests/test_guard_paths.py`: testes unitários dos casos novos (autor).
- `.github/workflows/ci.yml`: Postgres em `trust`, sem senha (§4.2).
- `.env.example` e `README.md` ("Como rodar" → "Testes de banco" e "Hook de guarda de caminhos"): §4.2 e §4.4.
- `tests/test_ci_workflow.py` e `tests/test_repo_config.py`: atualizar as asserções que hoje esperam a URL com senha (autor).
- `.claude/agents/architect.md`, **só** a seção `## Commits` (§4.3). **Exceção de caminho, §4.5.**
- `reviews/README.md`, **só** o parágrafo "Rastreio de papéis" (§4.3). **Exceção de caminho, §4.5.**
- `tests/acceptance/test_spec_001.py` (CA-20 da SPEC-001): trocar a URL esperada pela nova. **Quem faz é o `tester` desta SPEC**, junto com `tests/acceptance/test_spec_022.py`. O developer não toca em `tests/acceptance/`.

### 3.2 Fora

- RV-04 da SPEC-001 (rodar os testes do hook com Python 3.10 no CI) e RV-02 (fixar as actions por SHA): numa SPEC futura que mexa no CI ou na SPEC-015 (portão `deploy`/`security`).
- Qualquer mudança na tabela de papéis do hook (`ROLES`, §4.6 da SPEC-001), nas mensagens de negação por papel, no frontmatter de qualquer agente ou em `.claude/settings.json`.
- Qualquer outro arquivo de `.claude/**` e de `docs/**` (as mudanças em `docs/` desta SPEC já foram feitas pelo architect: SPEC-001 e esta SPEC).
- Relatórios antigos em `reviews/SPEC-001/` (são registro histórico e não mudam, mesmo citando a URL antiga).

## 4. Requisitos detalhados

### 4.1 Hook: campo por ferramenta (RV-01)

- Mapa fixo, sensível a maiúsculas: `Write`, `Edit`, `MultiEdit` → `tool_input.file_path`; `NotebookEdit` → `tool_input.notebook_path`.
- `target_path(event)` valida nesta ordem e levanta `GuardError` (código 2) na primeira falha. As mensagens abaixo saem no stderr no formato já existente, `guard_paths: blocked: <mensagem> (SPEC-001, R-07)`:

  | Ordem | Condição | Mensagem |
  |---|---|---|
  | 1 | evento não é objeto JSON | `event is not a JSON object` (já existe) |
  | 2 | `tool_input` ausente ou não é objeto | `event has no tool_input object` (já existe) |
  | 3 | `tool_name` ausente ou não é string | `event has no tool_name string` |
  | 4 | `tool_name` fora do mapa (inclusive `""`, `"write"`, `"Bash"`) | `unknown tool_name '<valor>'` (valor com `repr`) |
  | 5 | a chave do **outro** campo está presente em `tool_input`, com qualquer valor (inclusive `null`, `""` ou só espaços) | `tool_input has both file_path and notebook_path` |
  | 6 | o campo esperado está ausente, não é string, é vazio ou só tem espaços | `tool_input.<campo> missing or empty for <tool_name>` |

- A regra 5 usa **presença da chave**, não valor preenchido, porque nenhuma das quatro ferramentas manda o campo da outra; assim, um evento com os dois campos é sempre malformado e é negado.
- Todo o resto da §4.6 da SPEC-001 permanece: tabela de papéis, semântica de `*`/`**`, resolução relativa a `cwd`, `realpath`, `.git/`, fora da raiz, JSON inválido, `--role`, só biblioteca padrão, compatível com Python ≥ 3.10, falha fechada em exceção inesperada, mensagem `role '<papel>' may not write '<caminho>'` na negação por papel.
- A docstring do módulo passa a citar a escolha do campo pelo `tool_name` e as novas condições de falha fechada.

### 4.2 Postgres de teste sem senha

- `ci.yml`, serviço `postgres:16`: `env` com `POSTGRES_HOST_AUTH_METHOD: trust` e `POSTGRES_DB: partqc_test`, **sem** a chave de senha (`POSTGRES_USER: postgres` pode ficar ou sair; o padrão da imagem já é `postgres`). Health check com `pg_isready` mantido. `env` do job: `TEST_DATABASE_URL: postgresql://postgres@localhost:5432/partqc_test`. Comentário no YAML: o `trust` vale só para o contêiner efêmero do CI. Fonte do comportamento da imagem: com `POSTGRES_HOST_AUTH_METHOD=trust`, a variável de senha deixa de ser obrigatória (<https://github.com/docker-library/docs/blob/master/postgres/content.md>, consultado em 2026-10-12).
- `.env.example`, bloco `# ---------- testes locais ----------`: a linha passa a ser exatamente `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`, mantendo o comentário de banco descartável.
- `README.md`, "Testes de banco": o comando passa a ser

  ```bash
  docker run -d --name partqc-pg -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=partqc_test -p 127.0.0.1:55432:5432 postgres:16
  export TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test
  ```

  - A porta é publicada só em `127.0.0.1`: com `trust`, quem alcança a porta entra sem senha, e o padrão do Docker (`-p 55432:5432`) publica em todas as interfaces, ou seja, na LAN.
  - Nota obrigatória: um contêiner `partqc-pg` criado antes desta SPEC (com senha) não aceita a URL nova e deve ser recriado com `docker rm -f partqc-pg` seguido do `docker run` acima.
- **Nenhum arquivo versionado fora de `docs/` e `reviews/`** contém as sequências `postgres:postgres@` ou `POSTGRES_PASSWORD`, nem em comentário. Os testes que verificam essa ausência montam as duas sequências por concatenação em tempo de execução (ex.: `"POSTGRES_" + "PASSWORD"`), para o próprio arquivo de teste não casar.

### 4.3 Commits do architect

- `.claude/agents/architect.md`: a seção `## Commits` passa a ter **exatamente** este texto (o frontmatter e as outras seções não mudam):

  > Você não tem shell (`Bash`), então não faz commits. Quem commita os seus arquivos é o **orquestrador** (sessão principal), com os trailers `Refs: SPEC-XXX` e `Agent: architect`, cada um em linha própria no fim da mensagem. Esse commit contém só os arquivos que você escreveu, sem misturar arquivos de outro papel. Sem esse trailer, o reviewer não consegue verificar a separação de papéis (R-07).

- `reviews/README.md`: logo depois do parágrafo que começa com `**Rastreio de papéis:**`, um parágrafo novo com **exatamente** este texto:

  > **Commits do architect:** o `architect` não tem shell, então quem commita os arquivos dele é o orquestrador, com `Agent: architect` e `Refs: SPEC-XXX`. Esse commit é esperado e não é desvio de papel, desde que contenha só arquivos de `docs/` (exceto `docs/rules.md` sem pedido explícito do humano) e nenhum arquivo de outro papel. As mudanças de status feitas pelo próprio orquestrador vão em commits separados, com `Agent: orchestrator`.

### 4.4 Nota de workspace trust no README

- `README.md`, seção `### Hook de guarda de caminhos (R-07)`: acrescentar, antes do parágrafo **Limitação**, um parágrafo com **exatamente** este texto:

  > **Workspace trust:** os hooks do frontmatter dos agentes de projeto só rodam se a pasta tiver a confiança (workspace trust) aceita no Claude Code. Numa máquina ou num clone novo, rode `claude` uma vez na pasta e aceite o diálogo de confiança; uma sessão `claude -p` não conta como aceite. Sem isso, o hook não roda e a escrita fora do papel passa (constatado no CA-23 da SPEC-001, em 2026-10-12).

### 4.5 Exceção de caminhos desta SPEC

O hook da SPEC-001 já está ativo e nega ao `developer`, nas ferramentas `Write`/`Edit`/`MultiEdit`/`NotebookEdit`, os caminhos `.claude/**` e `reviews/**` (exceto o dev-report). O humano autorizou, **somente nesta SPEC**, as alterações abaixo:

| Arquivo | O que pode mudar |
|---|---|
| `.claude/hooks/guard_paths.py` | `target_path()`, constantes usadas por ela e a docstring do módulo (§4.1). `ROLES` não muda. |
| `.claude/agents/architect.md` | Só o corpo da seção `## Commits` (§4.3). O frontmatter não muda. |
| `reviews/README.md` | Só o parágrafo novo da §4.3. |

- Como o hook bloqueia `Write`/`Edit` nesses caminhos, o developer altera **apenas esses três arquivos** pelo `Bash` (por exemplo, um script Python em `python3 - <<'EOF' ... EOF` ou `patch -p1` com um diff guardado fora do repositório). Os comandos usados vão, na íntegra, no `r1-dev-report.md`.
- Os commits desses arquivos levam `Agent: developer` e `Refs: SPEC-022`.
- O reviewer confere com `git diff --stat main...HEAD -- .claude/ reviews/README.md` e `git show --stat` que nenhum outro arquivo de `.claude/**` mudou e que o diff de `.claude/agents/architect.md` não toca no frontmatter.
- A tabela de papéis do hook **não** muda. Fora desta SPEC, `.claude/**` e `reviews/**` continuam proibidos ao developer.

## 5. Critérios de aceite

Nos CAs do hook, `<raiz>` é a raiz do repositório, os caminhos são enviados como absolutos e o evento é passado no stdin a `python3 .claude/hooks/guard_paths.py --role <papel>`. Nos CA-01 a CA-04 (mensagens de `GuardError`, §4.1), "stderr contém X" significa que o stderr contém `guard_paths: blocked: X`; no CA-06 (negação por papel, formato inalterado da §4.6 da SPEC-001, sem `blocked:`), significa que o stderr contém X literalmente.

- **CA-01 (RV-01)** — Dado `--role ml-engineer` e o evento `{"tool_name":"NotebookEdit","tool_input":{"notebook_path":"<raiz>/api/src/evil.ipynb","file_path":"<raiz>/ml/x.ipynb"}}`, quando o hook roda, então o código de saída é 2 e o stderr contém `tool_input has both file_path and notebook_path`.
- **CA-02** — Dado o hook, quando recebe cada evento abaixo, então sai com código 2 e o stderr contém `tool_input has both file_path and notebook_path`:

  | Papel | `tool_name` | `tool_input` |
  |---|---|---|
  | ml-engineer | `NotebookEdit` | `notebook_path=<raiz>/ml/a.ipynb`, `file_path="   "` |
  | ml-engineer | `NotebookEdit` | `notebook_path=<raiz>/ml/a.ipynb`, `file_path=42` |
  | ml-engineer | `NotebookEdit` | `notebook_path=<raiz>/ml/a.ipynb`, `file_path=null` |
  | ml-engineer | `Write` | `file_path=<raiz>/ml/a.py`, `notebook_path=<raiz>/api/b.ipynb` |
  | developer | `Edit` | `file_path=<raiz>/api/src/qc_api/main.py`, `notebook_path=""` |

- **CA-03** — Dado `--role developer` e `tool_input = {"file_path":"<raiz>/api/src/qc_api/main.py"}`, quando o `tool_name` está ausente, é `42` ou é `null`, então o código é 2 e o stderr contém `event has no tool_name string`; e, quando o `tool_name` é `"Bash"`, `"write"` ou `""`, então o código é 2 e o stderr contém, respectivamente, `unknown tool_name 'Bash'`, `unknown tool_name 'write'` e `unknown tool_name ''`.
- **CA-04** — Dado o hook, quando recebe cada evento abaixo, então sai com código 2 e o stderr contém a mensagem indicada:

  | Papel | `tool_name` | `tool_input` | Mensagem |
  |---|---|---|---|
  | ml-engineer | `NotebookEdit` | `{}` | `tool_input.notebook_path missing or empty for NotebookEdit` |
  | developer | `Write` | `{}` | `tool_input.file_path missing or empty for Write` |
  | developer | `Edit` | `file_path=""` | `tool_input.file_path missing or empty for Edit` |
  | developer | `Edit` | `file_path="   "` | `tool_input.file_path missing or empty for Edit` |
  | developer | `MultiEdit` | `file_path=42` | `tool_input.file_path missing or empty for MultiEdit` |
  | developer | `Write` | `file_path=null` | `tool_input.file_path missing or empty for Write` |

- **CA-05** — Dado o hook, quando recebe cada evento abaixo (só o campo esperado), então sai com código 0 e o stderr fica vazio:

  | Papel | `tool_name` | Campo = caminho |
  |---|---|---|
  | developer | `Write` | `file_path` = `<raiz>/api/src/qc_api/main.py` |
  | developer | `Edit` | `file_path` = `<raiz>/api/src/qc_api/main.py` |
  | developer | `MultiEdit` | `file_path` = `<raiz>/api/src/qc_api/main.py` |
  | developer | `Write` | `file_path` = `api/src/qc_api/main.py` (relativo), com `"cwd": "<raiz>"` no evento |
  | ml-engineer | `NotebookEdit` | `notebook_path` = `<raiz>/ml/notebooks/train.ipynb` |
  | ml-engineer | `Write` | `file_path` = `<raiz>/ml/src/qc_ml/train.py` |
  | tester | `Edit` | `file_path` = `<raiz>/tests/acceptance/test_spec_022.py` |
  | architect | `Write` | `file_path` = `<raiz>/docs/specs/SPEC-022-manutencao-setup.md` |

- **CA-06** — Dado `--role developer` e o evento bem formado `{"tool_name":"NotebookEdit","tool_input":{"notebook_path":"<raiz>/ml/notebooks/train.ipynb"}}`, quando o hook roda, então o código é 2 e o stderr contém `role 'developer' may not write 'ml/notebooks/train.ipynb'` (a negação por papel não mudou).
- **CA-07** — Dado `.claude/hooks/guard_paths.py`, quando se analisam os `import` via `ast`, então todos estão em `sys.stdlib_module_names`; e, quando se roda `uv run pytest -q tests/acceptance/test_spec_001.py -k "ca11 or ca12 or ca13 or ca14 or ca15 or ca16 or ca17"`, então o código de saída é 0 (o comportamento da SPEC-001 continua).
- **CA-08** — Dado `.github/workflows/ci.yml` carregado com `yaml.safe_load`, quando se lê o único serviço `postgres:16` e o `env` do job, então `env["POSTGRES_HOST_AUTH_METHOD"] == "trust"`, `env["POSTGRES_DB"] == "partqc_test"`, o `env` do serviço não tem chave que contenha `PASSWORD`, `options` contém `pg_isready`, e `TEST_DATABASE_URL == "postgresql://postgres@localhost:5432/partqc_test"`.
- **CA-09** — Dado `.env.example`, quando é lido linha a linha, então existe a linha exata `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`, nenhuma linha contém `postgres:postgres@`, e as variáveis da lista do CA-20 da SPEC-001 continuam presentes, com as de segredo (`KEY`, `TOKEN`, `SECRET`, `PASSWORD` no nome) vazias.
- **CA-10 (R-03)** — Dado `git ls-files`, quando se leem como texto UTF-8 todos os arquivos cujo caminho **não** começa com `docs/` nem `reviews/` (arquivos que não decodificam são ignorados), então nenhum contém `postgres:postgres@` nem `POSTGRES_PASSWORD` (o teste monta as duas sequências por concatenação).
- **CA-11** — Dado `README.md`, quando é lido, então contém `-e POSTGRES_HOST_AUTH_METHOD=trust`, `-p 127.0.0.1:55432:5432`, `export TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test` e `docker rm -f partqc-pg`.
- **CA-12** — Dado `README.md`, quando se isola o trecho entre a linha `### Hook de guarda de caminhos (R-07)` e o próximo título (ou o fim do arquivo), então o trecho contém o parágrafo da §4.4 literalmente, e esse parágrafo aparece antes de `**Limitação:**`.
- **CA-13** — Dado `.claude/agents/architect.md`, quando se isola o trecho entre a linha `## Commits` e o próximo título de nível 2, então ele é igual ao texto da §4.3 (sem o marcador de citação `>` do início), descontados espaços nas pontas; e o frontmatter carregado com `yaml.safe_load` tem `name == "architect"`, `tools == "Read, Grep, Glob, Write, Edit, WebSearch, WebFetch"`, `model == "inherit"`, `color == "purple"`, `skills == ["criar-spec", "criar-adr"]` e um comando de hook que contém `guard_paths.py" --role architect`.
- **CA-14** — Dado `reviews/README.md`, quando é lido, então contém o parágrafo da §4.3 que começa com `**Commits do architect:**` (sem o marcador de citação `>` do início), e ele vem depois do parágrafo que começa com `**Rastreio de papéis:**`.
- **CA-15** — Dado o repositório desta SPEC, com `TEST_DATABASE_URL` e `CI` ausentes do ambiente, quando se rodam `uv run ruff check .`, `uv run ruff format --check .` e `uv run pytest -q`, então os três terminam com código 0.
- **CA-16** — Dado um contêiner criado com o comando da §4.2 e `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`, quando se roda `uv run pytest -q -rs tests/test_db_smoke.py`, então o código é 0 com `1 passed` e nenhum teste pulado.
- **CA-17 (manual)** — CI com Postgres sem senha: 1. Abrir o PR desta SPEC no GitHub. 2. Aguardar o workflow `ci`. 3. Conferir que o job terminou verde. 4. Conferir no log do passo `uv run pytest -q` que nenhum teste `db` foi pulado (não há `SKIPPED` com `TEST_DATABASE_URL not set`).
- **CA-18 (manual)** — Exceção de caminhos: 1. Rodar `git diff --stat main...HEAD -- .claude/` e conferir que só aparecem `.claude/hooks/guard_paths.py` e `.claude/agents/architect.md`. 2. Rodar `git diff main...HEAD -- .claude/hooks/guard_paths.py` e conferir que o dicionário `ROLES` não mudou. 3. Rodar `git diff main...HEAD -- .claude/agents/architect.md` e conferir que nenhuma linha entre os dois `---` do frontmatter mudou. 4. Conferir que os commits que tocam esses arquivos e `reviews/README.md` têm `Agent: developer` e que o `r1-dev-report.md` traz os comandos `Bash` usados.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Casos novos do hook (CA-01…CA-06), via `subprocess` com `sys.executable`; asserções do CI e do `.env.example` atualizadas para a URL sem senha e a ausência da variável de senha (por concatenação) | `tests/test_guard_paths.py`, `tests/test_ci_workflow.py`, `tests/test_repo_config.py` |
| Aceite (tester) | Um teste por CA automatizável (CA-01…CA-16). CA-16 usa o Postgres local criado com o comando da §4.2 (se o Docker não estiver disponível, o tester registra no test-report e o CA-17 cobre o banco). O tester também troca, em `tests/acceptance/test_spec_001.py`, a URL esperada no `test_ca20_env_example` pela nova (é esperado ver esse arquivo da SPEC-001 num commit `Agent: tester` desta SPEC) | `tests/acceptance/test_spec_022.py`, `tests/acceptance/test_spec_001.py` |
| Manual | CA-17 (CI no PR) e CA-18 (diff de `.claude/`) | Descritos nos CAs |

Mocks: nenhum. Os testes do hook alimentam o stdin com JSON e conferem o código de saída e o stderr.

## 7. Riscos e notas para o implementador

- **Edite o hook primeiro e rode `uv run pytest -q tests/test_guard_paths.py` logo em seguida.** O hook vale para o próprio developer durante a implementação: um erro de sintaxe faz o `python3` sair com código 1, que o Claude Code **não** trata como bloqueio (falha aberta); um erro de lógica pode bloquear todos os seus `Write`/`Edit` (nesse caso, corrija pelo `Bash`, como na §4.5).
- O hook roda com o `python3` do sistema (3.14 no notebook) e precisa continuar compatível com Python ≥ 3.10: nada de sintaxe ou módulo de 3.11+ (o `per-file-target-version = py310` do ruff ajuda).
- Os eventos reais do Claude Code trazem `tool_name`, e os testes existentes da SPEC-001 já enviam `tool_name` coerente com o campo; por isso a mudança não deve quebrar nenhum teste atual além das asserções de URL citadas na §3.1.
- Comentários no YAML, no `.env.example` e no README também contam para o CA-10: não escreva o nome da variável de senha nem a URL antiga, nem para explicar a mudança.
- A busca do CA-05 da SPEC-015 (R-03) usa o padrão `postgres(ql)?://[^\s:/@]+:[^\s@]+@`, que não casa com a URL nova (sem `:senha`). A entrada `postgres:postgres@localhost` da lista de permissão dela continua necessária, porque os relatórios históricos em `reviews/SPEC-001/` (fora de `docs/`) mantêm a URL antiga. Por isso a SPEC-015 não muda.
- O contêiner local antigo (`partqc-pg`, com senha) deixa de funcionar com a URL nova: recrie-o (§4.2) antes de rodar os testes `db`.

## 8. Definição de pronto

- [ ] Todos os CAs automatizáveis com teste de aceite passando (test-report PASS) e CA-17/CA-18 conferidos
- [ ] review-report APPROVED
- [ ] CI verde, com os testes `db` rodando (CA-17); `ruff` limpo
- [ ] `README.md` e `.env.example` atualizados
- [ ] PR aberto com os relatórios; merge humano

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-12 | Criação, com o escopo definido no pedido: RV-01 do hook, Postgres de teste sem senha, commits do architect e nota de workspace trust. Decisões do architect: (a) a regra "dois campos" usa presença da chave (§4.1); (b) a porta local publicada só em `127.0.0.1`, por causa do `trust` (§4.2); (c) `reviews/README.md` entrou na exceção de caminhos da §4.5, porque o hook também nega `reviews/**` ao developer; (d) a SPEC-015 não muda (§7). Criada em `Draft`: o architect não muda status para `Ready`. O orquestrador informou que o humano já aprovou o conteúdo ao pedir a SPEC; a passagem para `Ready` fica com o humano (ou com o orquestrador, sob a confirmação dele), conferindo os pontos (b) e (c). | Pendências do PR #3 da SPEC-001 (review r1, CA-23) e alerta de scanner de segredos no repositório público | Humano (Carlos), via orquestrador |
| 2026-10-12 | `Draft` → `Ready` → `In Dev` (r1). Aprovação humana explícita, com os pontos (b) e (c) e a tag `infra` confirmados. | Início do loop | Humano (Carlos) |
| 2026-10-12 | Preâmbulo da §5: a leitura "stderr contém X" = `guard_paths: blocked: X` passa a valer só para os CA-01 a CA-04; no CA-06, X aparece literalmente, no formato inalterado da SPEC-001 §4.6 (sem `blocked:`). Nenhum CA, requisito ou comportamento mudou; nenhuma mudança de código. Na r2, basta reexecutar o teste do CA-06. SPEC marcada como "Aguardando reaprovação humana"; o Status fica com o orquestrador. | SPEC_ISSUE-01 de `reviews/SPEC-022/r1-test-report.md`: o preâmbulo contradizia o CA-06 e as §3.2/§4.1 | Orquestrador |
| 2026-10-12 | Correção do SPEC_ISSUE-01 reaprovada; `Blocked` → `In Test`, retomando a r1 (o tester reemite o r1-test-report). | Fluxo do loop (§4 da skill `features`) | Humano (Carlos) |
