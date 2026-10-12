# SPEC-001 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-001](../../docs/specs/SPEC-001-setup-repositorio.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `c6eee79` |
| **Veredicto** | **PASS** |

Os testes de aceite foram escritos primeiro a partir da SPEC (caixa-preta). Só depois li a implementação, para os testes exploratórios. Arquivo: `tests/acceptance/test_spec_001.py`, com 18 funções `test_caNN_*` marcadas `acceptance`, que viram 54 casos depois da parametrização. Ambiente: Arch Linux, uv 0.13.0, Python 3.12.15 (`.venv`), Postgres 16 em Docker (`partqc-pg`, porta 55432).

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 (manual) | Clone limpo da branch em diretório temporário, sem `.venv`: `uv sync --all-packages --frozen` → rc 0; `sys.version_info[:2]` → `(3, 12)`; `import torch` → `ModuleNotFoundError` (rc 1); `uv pip list` sem torch, torchvision, timm, onnx nem coral-pytorch. Usei o cache local do uv: o download do PyPI com `--no-cache` não foi repetido por mim (o dev-report registra esse caso) | ✅ |
| CA-02 (manual) | No mesmo clone: `import qc_contracts, qc_preprocess, qc_api, qc_edge, qc_dashboard, qc_ml` → rc 0 | ✅ |
| CA-03 | `tests/acceptance/test_spec_001.py::test_ca03_ruff_check_and_format_are_clean` | ✅ |
| CA-04 | `tests/acceptance/test_spec_001.py::test_ca04_db_smoke_passes_with_database_url` (marcado `db`; roda o pytest via `subprocess` só sobre `tests/test_db_smoke.py`) | ✅ (com `TEST_DATABASE_URL`) |
| CA-05 | `tests/acceptance/test_spec_001.py::test_ca05_db_smoke_skipped_without_url_outside_ci` | ✅ |
| CA-06 | `tests/acceptance/test_spec_001.py::test_ca06_ci_without_url_fails_session` | ✅ |
| CA-07 | `tests/acceptance/test_spec_001.py::test_ca07_light_packages_have_no_ml_runtime_and_synthetic_path_is_reported` (função do autor no lock real e no sintético, mais um oráculo de fecho independente escrito pelo tester) | ✅ |
| CA-08 | `tests/acceptance/test_spec_001.py::test_ca08_ml_base_has_no_torch_and_train_extra_declares_stack` (fecho do autor e do oráculo; extra `train` conferido no `ml/pyproject.toml` e no `uv.lock`) | ✅ |
| CA-09 | `tests/acceptance/test_spec_001.py::test_ca09_python_312_everywhere` | ✅ |
| CA-10 | `tests/acceptance/test_spec_001.py::test_ca10_ci_workflow_shape` | ✅ |
| CA-11 | `tests/acceptance/test_spec_001.py::test_ca11_tester_denied_on_production_code_with_message` | ✅ |
| CA-12 | `tests/acceptance/test_spec_001.py::test_ca12_role_table` (as 25 linhas; nas negadas, confere também a mensagem completa) | ✅ (25/25) |
| CA-13 | `tests/acceptance/test_spec_001.py::test_ca13_traversal_outside_and_git_are_denied` (`..`, `/tmp/x.py`, `.git/config`) | ✅ (3/3) |
| CA-14 | `tests/acceptance/test_spec_001.py::test_ca14_bad_input_fails_closed` (JSON inválido, sem campo de caminho, sem `tool_input`, `--role admin`, sem `--role`) | ✅ (5/5) |
| CA-15 | `tests/acceptance/test_spec_001.py::test_ca15_notebook_edit_uses_notebook_path` | ✅ (2/2) |
| CA-16 | `tests/acceptance/test_spec_001.py::test_ca16_root_with_space_and_accent` (cópia do hook para `<tmp>/Área de trabalho/proj/.claude/hooks/`; também confere a negação dentro dessa raiz) | ✅ |
| CA-17 | `tests/acceptance/test_spec_001.py::test_ca17_hook_imports_only_stdlib` | ✅ |
| CA-18 | `tests/acceptance/test_spec_001.py::test_ca18_agent_frontmatter_keeps_fields_and_has_hook` (os valores de `name`, `description`, `tools` e `model` foram copiados da `main`) | ✅ (6/6) |
| CA-19 | `tests/acceptance/test_spec_001.py::test_ca19_settings_json` | ✅ |
| CA-20 | `tests/acceptance/test_spec_001.py::test_ca20_env_example` (linha exata, 20 variáveis da `main` presentes, chaves `*KEY*`/`*TOKEN*`/`*SECRET*`/`*PASSWORD*` vazias, `DATABASE_URL` com placeholder) | ✅ |
| CA-21 (manual) | `git diff --stat main...HEAD -- docs` → só `docs/plan.md` e `docs/specs/SPEC-001-setup-repositorio.md`. `git diff main...HEAD -- .claude/agents/` → 6 adições e 0 remoções por arquivo, um único hunk por arquivo, todo dentro do frontmatter (antes do `---` de fechamento), com o corpo intacto | ✅ |
| CA-22 (manual) | Pendente: depende do PR e do workflow no GitHub | ⏳ pendente |
| CA-23 (manual) | Pendente: exige reiniciar a sessão do Claude Code depois do merge | ⏳ pendente |

## Suíte completa

```text
# sem TEST_DATABASE_URL e sem CI
$ env -u TEST_DATABASE_URL -u CI uv run pytest -q
SKIPPED [1] tests/acceptance/test_spec_001.py:174: TEST_DATABASE_URL not set
SKIPPED [1] tests/test_db_smoke.py:11: TEST_DATABASE_URL not set
182 passed, 2 skipped in 8.15s          (rc 0)

# com TEST_DATABASE_URL (Postgres 16 local, porta 55432)
$ TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/partqc_test uv run pytest -q
184 passed in 8.81s                     (rc 0)

# CI=true + TEST_DATABASE_URL (simula o CI)
$ CI=true TEST_DATABASE_URL=... uv run pytest -q -rs
184 passed in 9.67s                     (rc 0, nenhum teste pulado)

# controle: CI=true sem TEST_DATABASE_URL
ERROR: TEST_DATABASE_URL is required when CI=true      (rc 4)

# só aceite
$ uv run pytest -q -m acceptance
54 passed, 130 deselected

$ uv run ruff check .
All checks passed!                      (rc 0)
$ uv run ruff format --check .
23 files already formatted              (rc 0)
```

Cobertura: não se aplica a esta SPEC, que não tem código de componente além dos `__init__.py`.

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | baixa | §4.6 (fora dos CAs) | 1. `echo '{"tool_name":"NotebookEdit","tool_input":{"notebook_path":"<raiz>/api/src/qc_api/evil.ipynb","file_path":"<raiz>/ml/x.ipynb"}}' \| python3 .claude/hooks/guard_paths.py --role ml-engineer` 2. Ver o código de saída. | rc 2. A §4.6 diz que o alvo do `NotebookEdit` é `tool_input.notebook_path`, e `api/**` é proibido ao ml-engineer | rc 0. `target_path()` sempre prefere `file_path` e não escolhe o campo pelo `tool_name`, então um `file_path` permitido "mascara" o `notebook_path` real. O mesmo acontece com `file_path` só com espaços e `notebook_path` permitido num `Write` (rc 0). Impacto prático baixo: exige um evento com campo extra (o schema do `NotebookEdit` provavelmente o rejeita antes do hook), só afeta `.ipynb`, e o papel já tem o `Bash` como limitação aceita. Ainda assim, é uma via de falha aberta. Sugestão: escolher o campo pelo `tool_name` ou negar quando os dois campos vierem e divergirem |

Não encontrei nenhum bug que afete os CAs.

## Testes exploratórios (além dos critérios)

O hook foi copiado para uma raiz temporária `<tmp>/Área de trabalho/proj/` e rodado com `/usr/bin/python3` (3.14.8), Python 3.10.22 e Python 3.12.15, com o mesmo resultado nas três versões. Foram 63 casos (script no scratchpad do tester, fora do repositório).

**Caminhos com espaço e acento**
- Arquivo `tests/acceptance/teste ção.py` com tester → 0.
- Negação de `api/src/qc_api/módulo é.py` → 2, com o caminho acentuado intacto na mensagem.
- Com `LC_ALL=C` e com `PYTHONIOENCODING=ascii:strict`, a negação com acento continua rc 2 e a mensagem sai legível em UTF-8.
- Raiz em NFD em vez de NFC → 2 (fora da raiz). Falha fechada, o que é aceitável.

**`..`**
- `tests/acceptance/../../api/src/x.py` com tester → 2 (`api/src/x.py`).
- `tests/acceptance/sub/../x.py` → 0.
- `docs/../README.md` com architect → 2.
- Relativo `../../outside/x.py` com `cwd` = raiz → 2.
- `//` e `/./` no caminho → normalizados, 0.

**Links simbólicos**
- Diretório em `tests/acceptance/` apontando para `api/src` → 2.
- Diretório apontando para fora da raiz → 2.
- Arquivo em `tests/acceptance/` apontando para `docs/rules.md` → 2.
- Link "proibido" que aponta para `tests/acceptance` → 0: vale o destino real, como pede a SPEC.
- Link pendente (dangling) para `tests/acceptance/...` com developer → 2.
- Link para `.git` → 2.
- Raiz acessada por um diretório-pai simbólico, tanto pelo alvo quanto pelo caminho do próprio hook → 0.

**`.git`**
- `.git/config` e `api/.git/hooks/pre-commit` → 2.
- `.gitignore` e `.github/...` com security-devops → 0, ou seja, sem falso positivo.
- `.GIT/config` → 0. No Linux é outro diretório; num sistema de arquivos sem distinção de maiúsculas (macOS/Windows) seria `.git`. Fica como informação, porque o projeto roda em Arch.
- A própria raiz como alvo → 2.

**JSON malformado**: todos os casos abaixo deram rc 2 com mensagem `blocked: ...`.
- stdin vazio, `null`, `[]` e `"x"`;
- `file_path` numérico ou vazio, e `tool_input` como string;
- BOM UTF-8 no início, bytes que não são UTF-8, JSON truncado e lixo depois do JSON;
- byte NUL no caminho.

Chave duplicada → vale a última, como no `json` padrão (informativo).

**Caminho relativo**
- Relativo com `cwd` absoluto → resolvido, 0.
- Relativo sem `cwd`, ou com `cwd` relativo → 2.

**Papel inválido**
- `--role ""`, `Developer` (maiúscula), `admin`, `--role` sem valor, argumento posicional extra e `--help` → todos 2.
- `--role=developer` → 0.
- Informativo: `--role tester --role developer` vale o último (developer), e o argparse aceita a abreviação `--ro developer`. Não é explorável, porque o comando vem fixo do frontmatter, que o agente não edita.

**Semântica dos padrões**
- `reviews/SPEC-001/r1-test-report.md.bak` e `reviews/SPEC-001/sub/r1-test-report.md` com tester → 2.
- `api/pyproject.toml` com security-devops → 2 (só o da raiz é permitido).
- `.github/tests/acceptance/x.py` com security-devops → 2 (a exclusão vence).
- `reviews/templates/dev-report.md` com developer → 2.
- `MultiEdit` → 0.
- Um caminho de cerca de 4 mil caracteres → sem erro.
- Informativo, coerente com a semântica de `**` da SPEC: o tester pode escrever em `api/src/qc_api/tests/acceptance/x.py`, e o caminho do próprio diretório `tests/acceptance` também casa.

**Robustez**
- Com stderr em `/dev/null`, a negação continua rc 2.
- Tempo médio por chamada: cerca de 49 ms.

**Política do `conftest.py`** (pytest em `tests/test_db_smoke.py`)
- `CI=TRUE` ou `CI=1` sem URL → rc 4 com a mensagem.
- `CI=false` sem URL → pulado, rc 0.
- `CI=true` com `TEST_DATABASE_URL` vazia ou só com espaços → rc 4.
- URL com senha errada ou porta fechada → o teste **falha** (rc 1, `OperationalError`) em vez de ser pulado, que é o comportamento correto. O `connect_timeout=10` evita travar.
- O `conftest.py` não lê `.env`.

**Notas para o reviewer** (não são bugs de teste)
- O dev-report registra duas divergências em relação ao texto da SPEC: `astral-sh/setup-uv@v10.3.0` em vez de uma tag major, e `extend-exclude = ["*.md"]` no ruff. Os CAs não as cobrem e não as avaliei como aceite.
- O README documenta o `docker run` (§4.3) e a limitação do `Bash` (§4.6), que também aparece no topo do script.
- Todos os commits da branch são de `CarlosZeyy` e têm trailer `Agent:` (developer/orchestrator).

## SPEC_ISSUE (se houver)

Nenhum. Todos os CAs automatizáveis (CA-03…CA-20) puderam ser testados como estão escritos.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
