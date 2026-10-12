# SPEC-001 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-001](../../docs/specs/SPEC-001-setup-repositorio.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-001-setup-repositorio` |
| Commits | `7f24d93`, `702d915`, `97c4e4f`, `9142217`, `c5a5b45` (+ o commit deste relatório) |

## Resumo

Workspace uv na raiz (projeto virtual `partqc`, Python 3.12, `uv.lock` com 115 pacotes) com os seis membros em layout `src/` e hatchling, cada um com `__version__ = "0.0.0"` e `tests/test_smoke.py`. torch, torchvision, timm, onnx e coral-pytorch ficam só no extra `qc-ml[train]`. O `conftest.py` da raiz implementa a política do marcador `db`. O teste de R-12 calcula o fecho transitivo de execução no `uv.lock`, seguindo os extras pedidos em cada aresta. O CI no GitHub Actions roda com o serviço `postgres:16`. O hook `.claude/hooks/guard_paths.py` usa só a biblioteca padrão e falha fechado; ele está ligado no frontmatter dos seis agentes, e há um `.claude/settings.json` mínimo. O `README.md` ganhou a seção "Como rodar".

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 (manual) | `pyproject.toml`, `.python-version`, `uv.lock`, `*/pyproject.toml` | Conferido manualmente (ver "Como rodar e verificar") |
| CA-02 (manual) | `packages/*/src/*/__init__.py`, `api/src/qc_api/__init__.py`, `edge/src/qc_edge/__init__.py`, `dashboard/src/qc_dashboard/__init__.py`, `ml/src/qc_ml/__init__.py` | `<membro>/tests/test_smoke.py::test_import_and_version` (6) + conferência manual |
| CA-03 | `pyproject.toml` (`[tool.ruff]`) | `uv run ruff check .` / `uv run ruff format --check .` (ver resultado abaixo) |
| CA-04 | `conftest.py`, `tests/test_db_smoke.py` | `tests/test_db_smoke.py::test_select_one` (com `TEST_DATABASE_URL`) |
| CA-05 | `conftest.py` | `tests/test_db_policy.py::test_db_tests_are_skipped_without_url_outside_ci`, `::test_empty_url_counts_as_not_set` |
| CA-06 | `conftest.py` | `tests/test_db_policy.py::test_ci_without_url_fails_before_running_tests` |
| CA-07 | `tests/lockgraph.py`, `uv.lock`, `api/pyproject.toml`, `dashboard/pyproject.toml` | `tests/test_dependency_isolation.py::test_light_packages_have_no_ml_runtime`, `::test_closure_actually_walks_the_graph`, `::test_api_closure_follows_requested_extras`, `::test_synthetic_transitive_torch_is_reported_with_path` (+ outros controles sintéticos) |
| CA-08 | `ml/pyproject.toml`, `uv.lock` | `tests/test_dependency_isolation.py::test_ml_base_closure_has_no_torch_or_timm`, `::test_ml_train_extra_declares_training_stack`, `::test_ml_train_extra_reaches_torch_in_closure` |
| CA-09 | `.python-version`, 7 × `pyproject.toml` | `tests/test_python_version.py::test_python_version_file_is_312`, `::test_requires_python` (7 casos) |
| CA-10 | `.github/workflows/ci.yml` | `tests/test_ci_workflow.py` (gatilhos, serviço, env, ordem dos passos, actions fixadas, sem `secrets.`) |
| CA-11 | `.claude/hooks/guard_paths.py` | `tests/test_guard_paths.py::test_denied_message_format` |
| CA-12 | `.claude/hooks/guard_paths.py` (`ROLES`) | `tests/test_guard_paths.py::test_role_table` (as 25 linhas do CA-12 + 25 casos extras) |
| CA-13 | `.claude/hooks/guard_paths.py` (`relative_to_root`) | `tests/test_guard_paths.py::test_traversal_outside_root_and_git_are_blocked`, `::test_symlink_escaping_root_is_blocked` |
| CA-14 | `.claude/hooks/guard_paths.py` (`main`, `_parse_role`, `target_path`) | `tests/test_guard_paths.py::test_bad_events_fail_closed`, `::test_unknown_or_missing_role_fails_closed`, `::test_invalid_utf8_fails_closed` |
| CA-15 | `.claude/hooks/guard_paths.py` (`target_path`) | `tests/test_guard_paths.py::test_notebook_edit_uses_notebook_path` |
| CA-16 | `.claude/hooks/guard_paths.py` | `tests/test_guard_paths.py::test_root_with_space_and_accent` |
| CA-17 | `.claude/hooks/guard_paths.py` | `tests/test_guard_paths.py::test_hook_imports_only_stdlib` |
| CA-18 | `.claude/agents/*.md` (só frontmatter) | `tests/test_repo_config.py::test_agent_frontmatter_has_guard_hook` (6) |
| CA-19 | `.claude/settings.json` | `tests/test_repo_config.py::test_settings_json` |
| CA-20 | `.env.example` (o bloco `# ---------- testes locais ----------` já existia na fundação; nada a mudar) | `tests/test_repo_config.py::test_env_example_has_test_database_block`, `::test_env_example_has_no_secret_values` |
| CA-21 (manual) | — | `git diff --stat main...HEAD -- docs` mostra só `docs/plan.md` e `docs/specs/SPEC-001-setup-repositorio.md` (commit do orquestrador); `git diff main...HEAD -- .claude/agents/` tem 36 linhas adicionadas, 0 removidas, todas dentro do frontmatter |
| CA-22 (manual) | `.github/workflows/ci.yml` | Pendente: depende do PR (orquestrador/humano) |
| CA-23 (manual) | `.claude/agents/*.md`, `.claude/hooks/guard_paths.py` | Pendente: exige reiniciar a sessão depois do merge |

### Nota para o tester (como importar as funções)

- **Fecho de dependências:** `tests/lockgraph.py` (não é arquivo de teste). Com `--import-mode=importlib`, `tests/` não entra no `sys.path`, então carregue o módulo por caminho (`importlib.util.spec_from_file_location`), como faz `tests/test_dependency_isolation.py`. API:
  - `load_lock(path)`;
  - `dependency_closure(lock, root, extras=())` → `{nome: caminho}`;
  - `find_forbidden(lock, root, forbidden=FORBIDDEN_FOR_LIGHT_PACKAGES, extras=())` → `{nome proibido: caminho}`;
  - `format_path(path)` → `"qc-api → pkg-x → torch"`.
- **Glob do hook:** `glob_match(pattern, rel_path)` e `is_allowed(role, rel_path)` estão em `.claude/hooks/guard_paths.py`. O CA-16 pede a cópia do script, já que a raiz é `Path(__file__).resolve().parents[2]`.
- **YAML do CI:** o arquivo usa `on:` sem aspas, e o `yaml.safe_load` (YAML 1.1) lê essa chave como `True`.

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1).

## Como rodar e verificar

```bash
uv python install 3.12
uv sync --all-packages --frozen
uv run ruff check . && uv run ruff format --check .
uv run pytest -q                                   # sem banco: 129 passed, 1 skipped
docker run -d --name partqc-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=partqc_test -p 55432:5432 postgres:16
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/partqc_test uv run pytest -q   # 130 passed
```

Saídas registradas nesta rodada (2026-10-12, notebook Arch, uv 0.13.0):

- **CA-01/CA-02**, em clone limpo da branch (`git clone` em diretório temporário, sem `.venv`):
  - primeiro `uv sync --all-packages --frozen` → rc 0;
  - repetido com `--no-cache`, baixando do PyPI → `Using CPython 3.12.15`, `Prepared 73 packages in 33.57s`, `Installed 73 packages`;
  - `uv run python -c "import sys; print(sys.version_info[:2])"` → `(3, 12)`;
  - `uv run python -c "import torch"` → `ModuleNotFoundError: No module named 'torch'` (rc 1);
  - `uv run python -c "import qc_contracts, qc_preprocess, qc_api, qc_edge, qc_dashboard, qc_ml"` → rc 0;
  - suíte no clone: `129 passed, 1 skipped`.
- **Conferência cruzada de R-12:** `uv export --package qc-api|qc-dashboard --frozen --no-dev` não lista torch, torchvision, timm nem onnxruntime. O mesmo comando para `qc-ml` sem extras lista onnxruntime, mas não torch nem timm.
- **CA-04:** `TEST_DATABASE_URL=… uv run pytest -q -rs tests/test_db_smoke.py` → `1 passed`, rc 0.
- **CA-05:** `env -u TEST_DATABASE_URL -u CI uv run pytest -q -rs tests/test_db_smoke.py` → `SKIPPED [1] tests/test_db_smoke.py:11: TEST_DATABASE_URL not set`, `1 skipped`, rc 0.
- **CA-06:** `env -u TEST_DATABASE_URL CI=true uv run pytest -q tests/test_db_smoke.py` → `ERROR: TEST_DATABASE_URL is required when CI=true`, rc 4.
- **Hook fora do pytest:**
  - rodado com `/usr/bin/python3` (3.14.8) e com Python 3.10.22;
  - nas duas versões: `tester` em `api/src/qc_api/main.py` → rc 2 com a mensagem do CA-11; `developer` → rc 0; stdin inválido → rc 2; sem `--role` → rc 2;
  - também com `LC_ALL=C` → rc 2, mensagem intacta.

## Decisões tomadas dentro do escopo da SPEC

1. **`astral-sh/setup-uv@v10.3.0` em vez de `@v10`.** A release mais recente é a `v10.3.0` (via `gh api`), mas o repositório não publica mais tags major flutuantes: as tags `v3` a `v7` existem, e `v8`, `v9` e `v10` não. Um `@v10` quebraria o CI. A versão completa fixa o major com rigor ainda maior. Já `actions/checkout` usa `@v7`, tag flutuante que existe e corresponde à release mais recente, `v7.0.1`.
2. **`extend-exclude = ["*.md"]` no `[tool.ruff]`.** O ruff 0.17.0 (versão fixada no lock) passou a formatar blocos de código Python dentro de Markdown, e `uv run ruff format --check .` falhava no trecho ilustrativo de `docs/specs/SPEC-008-edge-inferencia-decisao.md`, que não posso editar. O estilo continua o padrão do `ruff format`; só o Markdown sai do conjunto de arquivos verificados.
3. **`per-file-target-version = { ".claude/hooks/*.py" = "py310" }`.** O ruff não sugere sintaxe 3.11+ no hook, que precisa rodar em Python ≥ 3.10.
4. **Fecho de dependências conservador.** Os marcadores de ambiente (`marker = "sys_platform == ..."`) são ignorados: a dependência conta como presente em qualquer plataforma. Quando um nome aparece em várias versões no lock, a aresta usa a `version` indicada nela; se não houver, todas as entradas entram.
5. **Hook mais restritivo que o mínimo, sempre falhando fechado:**
   - bloqueia qualquer segmento `.git`, não só `.git/` na raiz;
   - bloqueia a própria raiz como alvo;
   - bloqueia caminho relativo sem `cwd` absoluto no evento;
   - bloqueia bytes NUL e stdin que não seja UTF-8;
   - trata exceção inesperada como bloqueio, com rc 2;
   - escreve o stderr em bytes UTF-8, porque um locale não UTF-8 com caminho acentuado derrubaria o script com rc 1, e rc 1 deixa a escrita passar (falha aberta).
6. **Exceção do `reviews/**` do developer** modelada como regra de exclusão com exceção própria (`("reviews/**", ("reviews/SPEC-*/r*-dev-report.md",))`). Assim, "a exclusão vence a inclusão" continua valendo para as outras regras.
7. **`CI` verdadeiro** = `true` ou `1`, sem diferenciar maiúsculas. `TEST_DATABASE_URL` vazia equivale a ausente.
8. **Raiz sem dependências dos membros:** basta `uv sync --all-packages`, e `uv run` faz sincronização inexata, sem remover os membros.
9. `CLAUDE.md` não foi alterado: os comandos de "Comandos úteis" continuam válidos. `.env.example` também não, porque o bloco de testes exigido pelo CA-20 já existia.
10. Os diretórios `src/` e `tests/relatorios/` não existiam na raiz, então não havia nada a remover.

## SPEC_ISSUE (se houver)

Nenhum bloqueante. Dois pontos para o architect avaliar numa próxima revisão da SPEC (não impediram a implementação; ver decisões 1 e 2):

- §4.4/§7 pedem "versão major fixada" do `astral-sh/setup-uv`, mas o projeto não publica mais tags major (`v10` não existe). Sugestão: aceitar a fixação por versão completa ou por SHA.
- §4.2 fala em "formatação padrão do `ruff format`". A partir do ruff 0.17, o padrão inclui Markdown, o que obrigaria os snippets de `docs/` a serem Python formatado. Adotei a exclusão de `*.md`.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos (`All checks passed!`, `22 files already formatted`)
- [x] Testes unitários do autor passando: `129 passed, 1 skipped` sem `TEST_DATABASE_URL`; `130 passed` com `TEST_DATABASE_URL` e `CI=true`
- [x] `.env.example` atualizado (se houver variável nova): nenhuma variável nova; o bloco `TEST_DATABASE_URL` já estava presente
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
