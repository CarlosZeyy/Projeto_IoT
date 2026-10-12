# SPEC-001: Setup do repositório e ferramentas

| Campo | Valor |
|---|---|
| Status | Ready |
| Rodada atual | — |
| Autor da implementação | developer |
| Tags | infra |
| Depende de | — |
| Semana alvo | S1 |
| Requisitos cobertos | RNF-08, RNF-09 (base: ruff + pytest no CI), R-07 (hook de guarda), R-12 |
| ADRs relevantes | ADR-010 (Python 3.12 + workspace uv), ADR-004 (dependências de ML), ADR-011 (loop de agentes), ADR-015 (git/GitHub e PRs) |

## 1. Contexto

> **Pré-condição (ADR-011):** a pergunta 4 de `docs/professor-questions.md` (uso de agentes de IA) precisa estar respondida **ou** com a decisão da dupla registrada. Sem isso, o orquestrador não inicia o loop desta SPEC.

`docs/architecture.md` §2 define um workspace uv em Python 3.12 com seis pacotes. Até esta SPEC, o repositório só tem documentação. Esta entrega cria o esqueleto mínimo que todas as outras SPECs usam: ambiente reproduzível (`uv.lock`), qualidade (ruff, pytest), CI no GitHub Actions com Postgres de teste, a verificação automática da R-12 e o hook de guarda de caminhos que materializa a R-07 para os subagentes.

## 2. Objetivo

Em um clone limpo no notebook (Arch Linux) e no CI, `uv sync --all-packages --frozen` instala o workspace em Python 3.12 **sem torch**, e `uv run ruff check .` e `uv run pytest -q` terminam com código 0; o hook `guard_paths.py` bloqueia escritas fora do papel de cada subagente.

## 3. Escopo

### 3.1 Dentro

- **Pré-requisito humano (manual):** instalar o uv no notebook — `sudo pacman -S uv` ou o instalador oficial (`curl -LsSf https://astral.sh/uv/install.sh | sh`). O Python do sistema é 3.14; o 3.12 é instalado pelo uv (`uv python install 3.12`).
- `pyproject.toml` na raiz (projeto virtual `partqc`, `[tool.uv] package = false`), `.python-version` (`3.12`) e `uv.lock` versionado.
- Esqueleto de cada membro: `pyproject.toml`, `src/<módulo>/__init__.py` (com `__version__ = "0.0.0"`, exceto onde outra SPEC definir) e `tests/test_smoke.py`:

  | Pasta | Pacote | Módulo |
  |---|---|---|
  | `packages/contracts/` | `qc-contracts` | `qc_contracts` |
  | `packages/preprocess/` | `qc-preprocess` | `qc_preprocess` |
  | `api/` | `qc-api` | `qc_api` |
  | `edge/` | `qc-edge` | `qc_edge` |
  | `dashboard/` | `qc-dashboard` | `qc_dashboard` |
  | `ml/` | `qc-ml` | `qc_ml` |

- `conftest.py` na raiz (política do marcador `db`) e `tests/` na raiz para testes do repositório (R-12, hook, CI).
- `.github/workflows/ci.yml`.
- `.claude/hooks/guard_paths.py`, `.claude/settings.json` e o campo `hooks:` no frontmatter dos seis arquivos `.claude/agents/*.md`.
- Atualizações de documentação permitidas: `.env.example` (bloco de testes), seção "Como rodar" do `README.md` e seção "Comandos úteis" do `CLAUDE.md` (só se os comandos mudarem). Se ainda existirem, remover os diretórios vazios `src/` e `tests/relatorios/` da raiz (já removidos na fundação documental).

### 3.2 Fora

- Código de qualquer componente: contrato e pré-processamento (SPEC-002), banco e migrações (SPEC-003), API (SPEC-004/005/006), borda (SPEC-007…010), ML (SPEC-011/012), dashboard (SPEC-013).
- Workflow de keep-alive, `infra/render.yaml` e `dashboard/requirements.txt` (SPEC-015).
- Índice de wheels CPU do torch e qualquer configuração de treino (SPEC-012).
- Qualquer outro arquivo de `docs/` além dos citados em 3.1.

## 4. Requisitos detalhados

### 4.1 Workspace e dependências

- Raiz: `[tool.uv.workspace] members = ["packages/contracts", "packages/preprocess", "api", "edge", "dashboard", "ml"]`; `requires-python = ">=3.12,<3.13"` (texto do ADR-010) na raiz **e** em cada membro; `[tool.uv] required-version = ">=0.8"`.
- Dependências entre membros via `[tool.uv.sources] <pkg> = { workspace = true }`. Build backend dos membros: `hatchling` (layout `src/`).
- Dependências diretas declaradas já nesta SPEC (limites inferiores; as SPECs seguintes podem acrescentar), conforme `architecture.md` §2:

  | Pacote | Dependências |
  |---|---|
  | `qc-contracts` | `pydantic>=2.7` |
  | `qc-preprocess` | `numpy>=1.26`, `pillow>=10.3` |
  | `qc-api` | `qc-contracts`, `fastapi`, `uvicorn`, `psycopg[binary,pool]>=3.2`, `pydantic-settings>=2`, `httpx` |
  | `qc-edge` | `qc-contracts`, `qc-preprocess`, `fastapi`, `uvicorn`, `onnxruntime`, `qrcode`, `httpx`, `python-multipart` |
  | `qc-dashboard` | `qc-contracts`, `streamlit`, `plotly`, `pandas`, `httpx` |
  | `qc-ml` (base, leve) | `qc-contracts`, `qc-preprocess`, `numpy`, `pandas`, `scikit-learn`, `onnxruntime`, `pillow` |
  | `qc-ml[train]` (extra opcional) | `torch`, `torchvision`, `timm`, `onnx`, `coral-pytorch` |

- Grupo de desenvolvimento na raiz (`[dependency-groups] dev`): `ruff`, `pytest`, `pytest-cov`, `httpx`, `pyyaml` (validação do workflow), `psycopg[binary]>=3.2` (testes `db`).
- `uv sync --all-packages` (sem extras) **não** instala torch; o ambiente de treino local é `uv sync --all-packages --extra train`.

### 4.2 Ruff e pytest (na raiz)

- `[tool.ruff]`: `line-length = 100`, `target-version = "py312"`; `[tool.ruff.lint] select = ["E", "F", "I", "B", "UP", "SIM"]`; `known-first-party` com os seis módulos; formatação padrão do `ruff format`.
- `[tool.pytest.ini_options]`:
  - `testpaths = ["tests", "packages/contracts/tests", "packages/preprocess/tests", "api/tests", "edge/tests", "dashboard/tests", "ml/tests"]` (SPECs futuras acrescentam, ex.: `infra/tests`);
  - `addopts = "-ra --strict-markers --import-mode=importlib"` (o `importlib` é obrigatório: vários componentes terão `tests/acceptance/test_spec_NNN.py` com o mesmo nome);
  - `markers`: `acceptance` (teste de aceite do tester), `db` (exige `TEST_DATABASE_URL`), `slow` (lento).

### 4.3 Política dos testes de banco (`conftest.py` da raiz)

- Sem `TEST_DATABASE_URL`: todo teste marcado `db` é **pulado** com o motivo exato `TEST_DATABASE_URL not set`.
- Com `CI=true` (o GitHub Actions define isso) e sem `TEST_DATABASE_URL`: a sessão do pytest **falha** antes de rodar testes, com a mensagem `TEST_DATABASE_URL is required when CI=true` (código de saída ≠ 0). Assim, o CI nunca fica verde com testes de banco pulados.
- O `conftest.py` **não** lê `.env`; a variável vem do ambiente (`export TEST_DATABASE_URL=...`).
- `tests/test_db_smoke.py` (marcado `db`): conecta com psycopg e executa `SELECT 1`.
- Postgres local documentado no `README.md` ("Como rodar"): `docker run -d --name partqc-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=partqc_test -p 55432:5432 postgres:16`, ou o Postgres do sistema. `.env.example` ganha o bloco `# ---------- testes locais ----------` com `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/partqc_test` e o comentário de que é um banco descartável, só local.

### 4.4 CI (`.github/workflows/ci.yml`)

- Gatilhos: `pull_request` e `push` na `main`. Um job em `ubuntu-latest`.
- Serviço `postgres:16` (usuário/senha/banco `postgres`/`postgres`/`partqc_test`, porta 5432, health check `pg_isready`). `env` do job: `TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/partqc_test` (credencial de um contêiner efêmero, não é segredo — registrar isso em comentário no YAML para a busca do reviewer, R-03) e `UV_FROZEN: "1"`.
- Passos: `actions/checkout` → `astral-sh/setup-uv` (versão major fixada, com cache) → `uv python install 3.12` → `uv sync --all-packages --frozen` → `uv run ruff check .` → `uv run ruff format --check .` → `uv run pytest -q`.
- Nenhum segredo do repositório é usado.

### 4.5 Verificação da R-12 (`tests/test_dependency_isolation.py`)

- Lê `uv.lock` com `tomllib` e calcula o **fecho transitivo** das dependências de execução de `qc-api` e de `qc-dashboard`: segue `dependencies` de cada pacote, incluindo os extras pedidos em cada aresta (ex.: `psycopg[binary]`), e ignora `dev-dependencies`/grupos e os `optional-dependencies` não pedidos.
- Falha se o fecho contiver `torch`, `torchvision`, `timm` ou `onnxruntime` (ou `onnxruntime-*`), listando o caminho da dependência proibida.
- A função de fecho é testada também contra um lock sintético (controle negativo).
- Outro teste confere `.python-version == "3.12"` e `requires-python == ">=3.12,<3.13"` na raiz e nos seis membros.

### 4.6 Hook de guarda de caminhos (`.claude/hooks/guard_paths.py`)

- Python **só com biblioteca padrão**, compatível com Python ≥ 3.10. Uso: `python3 guard_paths.py --role <papel>`. Roda com o `python3` do sistema, sem `uv`: é ferramenta do Claude Code, não código do projeto, e precisa funcionar antes de existir `.venv` (um interpretador ausente faria o hook falhar **aberto**). É a única exceção à regra do ADR-010 de nunca usar o Python do sistema.
- Lê o JSON do evento `PreToolUse` no stdin. Caminho alvo: `tool_input.file_path` (Write, Edit, MultiEdit) ou `tool_input.notebook_path` (NotebookEdit). Caminho relativo é resolvido a partir de `cwd` do JSON.
- Raiz do projeto: `Path(__file__).resolve().parents[2]`. O alvo é normalizado com `os.path.realpath` (resolve `..` e links simbólicos) e convertido para caminho POSIX relativo à raiz.
- Saída: permitido → código 0 sem saída; negado → código **2** com mensagem no stderr no formato `guard_paths: role '<papel>' may not write '<caminho relativo>' (SPEC-001, R-07)`.
- **Falha fechada** (código 2): JSON inválido, campo de caminho ausente, `--role` ausente ou desconhecido, caminho fora da raiz do projeto, caminho dentro de `.git/`.
- Semântica dos padrões (relativos à raiz): `*` casa qualquer sequência **dentro de um segmento** (sem `/`); `**` casa zero ou mais segmentos inteiros. Logo `**/tests/acceptance/**` casa `tests/acceptance/x.py` e `api/tests/acceptance/x.py`. A regra de exclusão vence a de inclusão.

  | Papel | Pode escrever | Exceto |
  |---|---|---|
  | `developer` | tudo | `**/tests/acceptance/**`, `docs/specs/**`, `docs/adr/**`, `docs/rules.md`, `ml/**`, `.claude/**`, `reviews/**` (mas pode `reviews/SPEC-*/r*-dev-report.md`) |
  | `ml-engineer` | `ml/**`, `reviews/SPEC-*/r*-dev-report.md` | `**/tests/acceptance/**` |
  | `tester` | `**/tests/acceptance/**`, `reviews/SPEC-*/r*-test-report.md` | — |
  | `reviewer` | `reviews/SPEC-*/r*-review-report.md`, `reviews/SPEC-*/r*-security-report.md` | — |
  | `security-devops` | `infra/**`, `.github/**`, `dashboard/requirements.txt`, `.streamlit/**`, `scripts/smoke_test.py`, `.env.example`, `.gitignore`, `pyproject.toml` (raiz), `uv.lock`, `docs/deployment-plan.md`, `reviews/SPEC-*/r*-dev-report.md`, `reviews/SPEC-*/r*-security-report.md` | `**/tests/acceptance/**` |
  | `architect` | `docs/**` | `docs/rules.md` |

- **Exceção única desta SPEC:** o `developer` está autorizado, **somente na SPEC-001**, a criar `.claude/hooks/` e `.claude/settings.json` e a editar o **frontmatter** dos seis `.claude/agents/*.md`, acrescentando apenas o campo `hooks:` (o corpo dos arquivos não muda), e a criar os arquivos de esqueleto de `ml/` (`ml/pyproject.toml`, `ml/src/qc_ml/__init__.py`, `ml/tests/test_smoke.py`). Fora desta SPEC, `.claude/**` e `ml/**` continuam proibidos ao developer. Formato do campo em cada agente (com o papel correspondente):

  ```yaml
  hooks:
    PreToolUse:
      - matcher: "Write|Edit|MultiEdit|NotebookEdit"
        hooks:
          - type: command
            command: 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guard_paths.py" --role developer'
  ```

- `.claude/settings.json` (configuração compartilhada, mínima): `permissions.allow` com `Bash(uv run *)`, `Bash(uv sync *)`, `Bash(uv tree *)`, `Bash(git status)`, `Bash(git diff *)`, `Bash(git log *)`; `permissions.deny` com `Read(./.env)`. Sem hooks globais (a sessão principal não tem papel).
- **Limitação documentada** (comentário no topo do script e no `README.md`): o hook **não** intercepta escritas feitas pelo `Bash` (ex.: `echo > arquivo`, `uv lock`); a R-07 continua sendo verificada pelo reviewer com `git log` (checklist §2).

## 5. Critérios de aceite

- **CA-01 (manual — requer internet/PyPI)** — Dado um clone limpo com uv ≥ 0,8 e sem `.venv`, quando se roda `uv sync --all-packages --frozen`, então o comando termina com código 0, `uv run python -c "import sys; print(sys.version_info[:2])"` imprime `(3, 12)` e `uv run python -c "import torch"` falha com `ModuleNotFoundError`.
- **CA-02 (manual — requer internet/PyPI)** — Dado o ambiente do CA-01, quando se roda `uv run python -c "import qc_contracts, qc_preprocess, qc_api, qc_edge, qc_dashboard, qc_ml"`, então o código de saída é 0.
- **CA-03** — Dado o repositório desta SPEC, quando se roda `uv run ruff check .` e `uv run ruff format --check .`, então ambos terminam com código 0.
- **CA-04** — Dado `TEST_DATABASE_URL` apontando para um Postgres 16 acessível, quando se roda `uv run pytest -q -rs tests/test_db_smoke.py`, então o código de saída é 0 com `1 passed` e nenhum teste pulado.
- **CA-05** — Dado `TEST_DATABASE_URL` ausente e `CI` ausente, quando se roda `uv run pytest -q -rs tests/test_db_smoke.py`, então o código de saída é 0 e o teste aparece como pulado com o motivo `TEST_DATABASE_URL not set`.
- **CA-06** — Dado `CI=true` e `TEST_DATABASE_URL` ausente, quando se roda `uv run pytest -q tests/test_db_smoke.py`, então o código de saída é diferente de 0 e a saída contém `TEST_DATABASE_URL is required when CI=true`.
- **CA-07** — Dado `uv.lock`, quando o teste de isolamento calcula o fecho de `qc-api` e de `qc-dashboard`, então nenhum dos dois contém `torch`, `torchvision`, `timm` ou `onnxruntime` (R-12); e, dado um lock sintético em que `qc-api → pkg-x → torch`, a mesma função reporta `torch` com o caminho `qc-api → pkg-x → torch`.
- **CA-08** — Dado `uv.lock`, quando se inspeciona o fecho de `qc-ml` sem extras, então ele não contém `torch` nem `timm`; e o extra `train` de `qc-ml` declara `torch`, `torchvision`, `timm`, `onnx` e `coral-pytorch`.
- **CA-09** — Dado o repositório, quando o teste lê `.python-version` e os sete `pyproject.toml` (raiz + 6 membros), então `.python-version` contém `3.12` e todos declaram `requires-python = ">=3.12,<3.13"`.
- **CA-10** — Dado `.github/workflows/ci.yml`, quando é carregado com `yaml.safe_load`, então: os gatilhos incluem `pull_request` e `push` com `branches: [main]`; há um serviço com `image: postgres:16`; o `env` define `TEST_DATABASE_URL`; e os passos contêm, nesta ordem, `uv sync --all-packages --frozen`, `uv run ruff check .`, `uv run ruff format --check .` e `uv run pytest -q`.
- **CA-11** — Dado o hook, quando recebe `{"tool_name":"Edit","tool_input":{"file_path":"<raiz>/api/src/qc_api/main.py"}}` com `--role tester`, então sai com código 2 e o stderr contém `role 'tester' may not write 'api/src/qc_api/main.py'`.
- **CA-12** — Dado o hook, quando avalia a tabela abaixo (caminhos relativos à raiz, enviados como absolutos), então o código de saída é o indicado em todas as linhas:

  | Papel | Caminho | Código |
  |---|---|---|
  | developer | `api/src/qc_api/main.py` | 0 |
  | developer | `api/tests/acceptance/test_spec_004.py` | 2 |
  | developer | `tests/acceptance/test_spec_001.py` | 2 |
  | developer | `docs/specs/SPEC-004-api-ingestao.md` | 2 |
  | developer | `docs/rules.md` | 2 |
  | developer | `ml/src/qc_ml/train.py` | 2 |
  | developer | `reviews/SPEC-004/r1-dev-report.md` | 0 |
  | developer | `reviews/SPEC-004/r1-test-report.md` | 2 |
  | developer | `.claude/agents/developer.md` | 2 |
  | ml-engineer | `ml/src/qc_ml/train.py` | 0 |
  | ml-engineer | `ml/tests/acceptance/test_spec_011.py` | 2 |
  | ml-engineer | `api/src/qc_api/main.py` | 2 |
  | tester | `packages/contracts/tests/acceptance/test_spec_002.py` | 0 |
  | tester | `reviews/SPEC-002/r2-test-report.md` | 0 |
  | tester | `packages/contracts/tests/test_schemas.py` | 2 |
  | reviewer | `reviews/SPEC-004/r1-review-report.md` | 0 |
  | reviewer | `reviews/SPEC-004/r1-security-report.md` | 0 |
  | reviewer | `api/src/qc_api/main.py` | 2 |
  | security-devops | `infra/render.yaml` | 0 |
  | security-devops | `.github/workflows/keepalive.yml` | 0 |
  | security-devops | `docs/deployment-plan.md` | 0 |
  | security-devops | `api/src/qc_api/main.py` | 2 |
  | architect | `docs/architecture.md` | 0 |
  | architect | `docs/rules.md` | 2 |
  | architect | `README.md` | 2 |

- **CA-13** — Dado o hook com `--role developer`, quando o caminho é `<raiz>/api/../docs/rules.md`, ou `/tmp/x.py` (fora da raiz), ou `<raiz>/.git/config`, então sai com código 2 nos três casos.
- **CA-14** — Dado o hook, quando o stdin não é JSON válido, ou o JSON não tem `tool_input.file_path` nem `tool_input.notebook_path`, ou `--role` é `admin` ou está ausente, então sai com código 2 em cada caso.
- **CA-15** — Dado o hook com `--role ml-engineer` e um evento `NotebookEdit` com `tool_input.notebook_path = "<raiz>/ml/notebooks/train.ipynb"`, então sai com código 0; com `--role developer`, sai com código 2.
- **CA-16** — Dado que a raiz do projeto contém espaço e acento (`Área de trabalho`), quando o hook recebe um caminho permitido dentro dela, então sai com código 0 (o teste cria um diretório temporário com esse nome e copia o script para `<tmp>/Área de trabalho/proj/.claude/hooks/`).
- **CA-17** — Dado o hook, quando se inspeciona o código-fonte, então ele só importa módulos da biblioteca padrão (o teste analisa os `import` via `ast` e compara com `sys.stdlib_module_names`).
- **CA-18** — Dado os seis `.claude/agents/*.md`, quando o frontmatter YAML é carregado, então cada um mantém `name`, `description`, `tools` e `model` com os valores atuais e tem `hooks.PreToolUse[0].matcher == "Write|Edit|MultiEdit|NotebookEdit"`, com um comando que contém `guard_paths.py --role <valor de name>`.
- **CA-19** — Dado `.claude/settings.json`, quando é carregado com `json.load`, então é JSON válido, `permissions.allow` contém `Bash(uv run *)` e não existe chave `hooks` no nível raiz.
- **CA-20** — Dado `.env.example`, quando é lido, então contém a linha `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/partqc_test` e as variáveis pré-existentes continuam presentes e sem valor de segredo (R-03).
- **CA-21 (manual)** — 1. Na branch da SPEC, rodar `git diff --stat main...HEAD`. 2. Conferir que, em `docs/**`, só mudaram `docs/specs/SPEC-001-setup-repositorio.md` e `docs/plan.md` (atualizações de status feitas pelo orquestrador). 3. Rodar `git diff main...HEAD -- .claude/agents/` e conferir que só há linhas **adicionadas** dentro do frontmatter (campo `hooks:`), sem mudança no corpo.
- **CA-22 (manual)** — 1. Abrir o PR desta SPEC no GitHub. 2. Aguardar o workflow `ci`. 3. Conferir que o job terminou verde e que o log do passo de pytest não mostra testes `db` pulados.
- **CA-23 (manual)** — 1. Reiniciar a sessão do Claude Code depois do merge. 2. Pedir ao subagente `tester` que crie `api/src/qc_api/probe.py`. 3. Conferir que a escrita é bloqueada com a mensagem do hook e que o arquivo não existe.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Smoke de import por membro; isolamento R-12 (lock real + sintético); versões de Python; política do marcador `db`; hook (tabela de papéis via `subprocess` com `sys.executable`); YAML do CI | `tests/`, `<membro>/tests/test_smoke.py` |
| Aceite (tester) | Um teste por CA automatizável (CA-03…CA-20). CA-01/02 são manuais (exigem rede) e ficam fora da suíte automatizada; CA-04…06 rodam o pytest via `subprocess` só sobre `tests/test_db_smoke.py` (nunca a suíte inteira, para não haver recursão) | `tests/acceptance/test_spec_001.py` |
| Manual (dupla/tester) | CA-01/02 (`uv sync` em clone limpo, com internet), CA-21 (diff), CA-22 (CI no GitHub) e CA-23 (hook numa sessão real) | Descritos nos CAs |

Mocks: nenhum. Os testes do hook alimentam o stdin com JSON e conferem código de saída e stderr. CA-04 e o smoke `db` usam o Postgres local (Docker) ou o serviço do CI.

## 7. Riscos e notas para o implementador

- O hook só vale para definições de agentes carregadas **depois** desta mudança (reinício da sessão). Se uma rodada r2/r3 desta SPEC precisar alterar `.claude/**` ou os arquivos de esqueleto de `ml/` (`ml/pyproject.toml`, `ml/src/qc_ml/__init__.py`, `ml/tests/test_smoke.py`) com o hook já ativo, o developer será bloqueado: registre no dev-report e o orquestrador escala ao humano.
- O hook não cobre o `Bash` (limitação aceita). Mudanças em `uv.lock` acontecem pelo comando `uv`, não pelo `Write`, então não conflitam com as listas acima.
- `uv sync` sem `--all-packages` remove os membros do ambiente (sincronização exata); use sempre `--all-packages` ou `--package`.
- O `torch` do PyPI é pesado; o índice de wheels CPU, se desejado, é decidido na SPEC-012.
- Fixe a versão major das actions (`actions/checkout`, `astral-sh/setup-uv`) verificando a atual no momento da implementação.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS) e CA-01, CA-02, CA-21…CA-23 conferidos
- [ ] review-report APPROVED
- [ ] CI verde; `ruff` limpo
- [ ] `README.md` ("Como rodar"), `CLAUDE.md` ("Comandos úteis", se mudou) e `.env.example` atualizados
- [ ] PR aberto com os relatórios; merge humano
