# SPEC-001 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-001](../../docs/specs/SPEC-001-setup-repositorio.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `main...794ea15` (45 arquivos, +3986/−4). Entre o commit testado `c6eee79` e `794ea15` só mudaram `tests/acceptance/`, o test-report e o status em `docs/`: nenhum código de produção mudou depois do teste. |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante nem alto. Há um achado médio (RV-01) e três baixos, que não bloqueiam, mas devem ir para o PR como pendências conhecidas.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | média | `.claude/hooks/guard_paths.py:137-140` | **Bug T-01 do test-report, confirmado.** `target_path()` ignora `tool_name` e sempre tenta `file_path` antes de `notebook_path`. Um `NotebookEdit` com `notebook_path` proibido e um `file_path` permitido passa com rc 0 (reproduzido numa cópia do hook: `ml-engineer`, `notebook_path=api/src/evil.ipynb`, `file_path=ml/x.ipynb` → rc 0). O mesmo vale para `file_path` não-string ou só com espaços seguido de um `notebook_path` permitido (rc 0). A §4.6 associa cada campo a uma ferramenta, e a implementação só segue essa associação quando o evento é bem formado. **Por que é média e não alta nem bloqueante:** (a) nenhum CA cobre o caso, e todos os CAs passam; (b) explorar a falha exige um evento com um parâmetro a mais, que o schema da ferramenta provavelmente rejeita antes do hook (não confirmado); (c) qualquer subagente com `Bash` já contorna o hook inteiro, o que é uma limitação aceita e documentada na §4.6, então o risco marginal é praticamente nulo; (d) a R-07 em si não foi violada, e o controle autoritativo dela continua sendo o `git log` com os trailers, conferido abaixo. Ainda assim, é um caminho que falha aberto num controle que a §4.6 manda falhar fechado, e a correção é trivial. | Escolher o campo pelo `tool_name` (`NotebookEdit` → `notebook_path`; `Write`/`Edit`/`MultiEdit` → `file_path`) e negar quando: o `tool_name` é desconhecido, o campo esperado falta, ou os dois campos vêm preenchidos. Acrescentar um teste de aceite para esse caso. **Atenção ao fluxo:** depois que o hook estiver ativo, o developer não pode editar `.claude/**` (§7 da SPEC). Por isso a correção precisa de autorização humana: uma SPEC de follow-up com a mesma exceção, ou a correção feita pelo próprio humano. Registrar como pendência no PR. |
| RV-02 | baixa | `.github/workflows/ci.yml:39` | **Desvio declarado 1:** `astral-sh/setup-uv@v10.3.0` em vez de "versão major fixada" (§4.4, §7). Conferi com `git ls-remote --tags`: o repositório tem `v3`…`v7` e `v10.0.0`…`v10.3.0`, mas não tem `v8`, `v9` nem `v10`. Logo, `@v10` quebraria o CI. A tag exata cumpre a intenção da SPEC (não flutuar de major) com rigor maior. **Decisão: aceito, sem correção.** O `actions/checkout@v7` aponta para o mesmo commit da `v7.0.1` (a mais recente). O CA-10 não depende disso. | Nenhuma ação de código. O architect atualiza o texto da §4.4/§7 (ver SPEC_ISSUE-1). Como nota para a SPEC-015 (portão `security`/`deploy`): tags são mutáveis, e fixar por SHA é a prática mais forte contra ataques de cadeia de suprimentos. |
| RV-03 | baixa | `pyproject.toml:40` | **Desvio declarado 2:** `extend-exclude = ["*.md"]` no `[tool.ruff]`. Conferi que o ruff 0.17.0 do lock formata blocos de código em Markdown: `ruff format --isolated --check docs/specs/SPEC-008-edge-inferencia-decisao.md` → `1 file would be reformatted`. Sem a exclusão, o CA-03 falharia num arquivo que o developer não pode editar (`docs/specs/**`, §3.2). A exclusão não afeta código Python: são 23 arquivos `.py` verificados, e o `ruff check` não linta Markdown. Ela também alcança `README.md`, `CLAUDE.md` e `.claude/agents/*.md`, mas nenhum deles contém código do projeto. **Decisão: aceito, sem correção.** É uma escolha de configuração necessária, sem alterar critério, e foi registrada no dev-report e no comentário do `pyproject.toml`, como pede o checklist §1. | Nenhuma ação de código. O architect atualiza a §4.2 (ver SPEC_ISSUE-2). Se no futuro houver Markdown com Python que deva ser formatado, trocar por uma exclusão mais estreita (ex.: `docs/**`). |
| RV-04 | baixa | `tests/test_guard_paths.py` (todo o arquivo); `.claude/hooks/guard_paths.py:1-24` | A §4.6 exige compatibilidade com Python ≥ 3.10, e o hook roda com o `python3` do sistema (3.14.8 no notebook). A suíte só executa o hook com `sys.executable` (3.12), como o plano de testes da §6 prevê. A compatibilidade com 3.10 e 3.14 foi verificada só manualmente pelo developer e pelo tester. O `per-file-target-version = py310` do ruff dá uma proteção parcial. | Não exige mudança agora. Numa SPEC futura que mexa no CI, considerar um passo `uv run --python 3.10 --no-project python -m pytest tests/test_guard_paths.py`, ou equivalente. |

## Avaliação dos pontos pedidos pelo orquestrador

1. **Desvios do texto da SPEC.** Os dois são **aceitáveis dentro do espírito da SPEC** e não exigem correção: RV-02 e RV-03, ambos de severidade baixa. Não alteram nenhum CA. O dev-report os registrou como decisão e como ponto para o architect, que é o tratamento certo pelo checklist §1. Abro um SPEC_ISSUE informativo para cada um, para que o texto da SPEC volte a refletir o que foi implementado. Nenhum dos dois bloqueia.
2. **T-01:** **média** (RV-01). Não é bloqueante, porque não há violação da R-07: nenhum commit cruzou a fronteira de papéis (ver o item 3). Também não é alta, porque a exploração exige um evento malformado, provavelmente rejeitado pelo schema da ferramenta, e o `Bash` já é um desvio aceito e muito mais simples. Também não é baixa, como o tester classificou: é um desvio da semântica de campo por ferramenta da §4.6 e abre um caminho de falha aberta num controle de segurança cujo requisito central é falhar fechado.
3. **R-07:** ✅. Todos os 10 commits têm os trailers `Agent:` e `Refs: SPEC-001`. Os arquivos de cada commit batem com o papel:

   | Commit | Agent | Arquivos | Conforme |
   |---|---|---|---|
   | `b2ab241`, `c6eee79`, `794ea15` | orchestrator | só `docs/plan.md` e o status em `docs/specs/SPEC-001-…md` | ✅ (previsto no CA-21) |
   | `7f24d93` | developer | workspace, 6 esqueletos (incluindo `ml/pyproject.toml`, `ml/src/qc_ml/__init__.py`, `ml/tests/test_smoke.py`), `uv.lock`, `.python-version` | ✅ (`ml/` restrito aos 3 arquivos da exceção da §4.6) |
   | `702d915`, `97c4e4f` | developer | `conftest.py`, `tests/*.py` (fora de `acceptance/`), `.github/workflows/ci.yml` | ✅ |
   | `9142217` | developer | `.claude/hooks/guard_paths.py`, `.claude/settings.json`, frontmatter dos 6 agentes, testes unitários | ✅ (exceção da §4.6; o diff dos agentes tem só 6 linhas `+` dentro do frontmatter, sem nenhuma `-`) |
   | `c5a5b45`, `91efd31` | developer | `README.md`, `reviews/SPEC-001/r1-dev-report.md` | ✅ |
   | `07716de` | tester | só `tests/acceptance/test_spec_001.py` e `reviews/SPEC-001/r1-test-report.md` | ✅ |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Os itens da §3.1 e os requisitos da §4.1–§4.6 foram implementados, e nada de §3.2 entrou no diff (não há `infra/`, `render.yaml` nem índice CPU do torch). Nenhum CA foi alterado (R-08 ✅). O dev-report traz rastreabilidade completa de CA-01…CA-23. Decisões fora do texto da SPEC: os desvios 1 e 2 foram registrados como pontos para o architect (RV-02, RV-03); as decisões 3–8 do dev-report são detalhes de implementação e todas tornam o comportamento mais restritivo ou conservador. A exceção é RV-01, que é um desvio de implementação e não uma decisão de projeto. Pendentes manuais: CA-22 (CI verde no PR, obrigatório pela R-09 antes do merge) e CA-23 (depois do merge). |
| 2. Regras inegociáveis | ✅ | **R-01** ✅: só dependências OSS do PyPI, GitHub Actions e a imagem `postgres:16`. **R-02** N/A. **R-03** ✅: a busca por `key\|secret\|token\|password\|postgres://\|eyJ` encontrou só a credencial `postgres/postgres` do contêiner efêmero, comentada no YAML como pede a §4.4, e o `docker run` local documentado; `.gitignore` cobre `.env` e `.env.*`; o CI não usa `secrets.`. **R-04** e **R-05** N/A. **R-06** N/A. **R-07** ✅ (ver a tabela acima). **R-11** N/A. **R-12** ✅: `requires-python = ">=3.12,<3.13"` nos 7 `pyproject.toml`, `.python-version = 3.12` e `uv.lock` com `requires-python = "==3.12.*"`; o cruzamento independente com `uv export --package qc-api/qc-dashboard --no-dev` não mostra torch, torchvision, timm nem onnxruntime; o `qc-ml` sem extras tem só `onnxruntime`, e torch, torchvision, timm, onnx e coral-pytorch aparecem como `(extra: train)`. **R-13** ✅: os 10 commits são de `Carlos Moises <179777237+CarlosZeyy@users.noreply.github.com>`, em Conventional Commits (`build:` e `ci:` são tipos válidos do padrão). |
| 3. Corretude | ✅ (com RV-01) | Hook: falha fechada em todos os caminhos de erro, incluindo exceção inesperada, `BaseException` no `__main__` e stderr em bytes UTF-8 para não cair com rc 1 em locale não UTF-8. Também trata `realpath` para `..` e links simbólicos, `.git` em qualquer segmento, a raiz como alvo e caminho relativo sem `cwd` absoluto. A semântica de `*`/`**` está correta, e a exclusão vence a inclusão. `conftest.py`: `UsageError` em `pytest_configure` (rc 4) e URL vazia ou só com espaços tratada como ausente. `lockgraph`: BFS com caminho mínimo, segue só os extras pedidos na aresta, ignora grupos dev e termina em ciclos. As exceções tratadas não engolem erros (não há `except: pass`). Itens de async, HTTP e fuso horário: N/A nesta SPEC. |
| 4. Testes | ✅ | Test-report PASS, com CA-03…CA-20 automatizados (54 casos) e CA-01/02/21 conferidos manualmente. Reproduzi: `ruff check` e `ruff format --check` limpos (23 arquivos); `env -u TEST_DATABASE_URL -u CI uv run pytest -q` → `182 passed, 2 skipped`, rc 0. Os testes não são tautológicos: o CA-07 usa um oráculo de fecho independente e exige um fecho com mais de 10 pacotes; o CA-04…06 roda o pytest real em subprocesso, só sobre `tests/test_db_smoke.py`; os testes do hook alimentam o stdin e conferem rc e stderr, sem mocks. Não há rede externa na suíte. Cobertura RNF-09: N/A, porque ainda não há módulos de componente. Lacunas: RV-01 (sem teste para os dois campos) e RV-04 (3.10 não automatizado). |
| 5. Qualidade | ✅ | Ruff limpo. Funções pequenas, com nomes claros. Não há `print`. Type hints nas funções públicas do hook, do `conftest` e do `lockgraph`. O `README.md` ganhou "Como rodar" (ambiente, testes `db`, CI e hook com a limitação do `Bash`). O `CLAUDE.md` não mudou, e não precisava: os comandos continuam válidos. O `.env.example` também não mudou, porque o bloco exigido já existia, como confirma o CA-20. Não há duplicação com `qc_contracts` nem `qc_preprocess`, que ainda estão vazios. |
| 6. Segurança | N/A | A SPEC tem a tag `infra`, não `security` nem `deploy`, e o autor é o developer. Mesmo assim, conferi de forma pontual: o workflow usa `permissions: contents: read`, `timeout-minutes: 30` e nenhum segredo. A observação sobre fixar actions por SHA está em RV-02. |

## Pontos positivos

- O hook foi bem pensado para falhar fechado: tratou locale não UTF-8 (onde o rc 1 deixaria a escrita passar), bytes NUL, `.git` em qualquer nível, links simbólicos pendentes e `BaseException`. Os 63 casos exploratórios do tester não acharam nenhuma falha aberta além da T-01.
- O fecho de dependências no `uv.lock` segue os extras por aresta, como a §4.5 pede, e tem controles negativos sintéticos: transitivo, variante `onnxruntime-*`, extra pedido e não pedido, grupo dev e ciclo. O tester completou isso com um oráculo independente.
- Os dois desvios do texto da SPEC foram transparentes: o motivo foi verificado, ficou em comentário no próprio arquivo e foi registrado no dev-report para o architect, sem reinterpretar nenhum CA.
- Separação de papéis limpa, com trailers em 100% dos commits e o uso das exceções da §4.6 restrito aos arquivos autorizados.

## SPEC_ISSUE (se houver)

Os dois são informativos e não bloqueiam. São pedidos de atualização de texto para o architect; a implementação já está aceita.

- **SPEC_ISSUE-1 (§4.4 e §7):** "versão major fixada" do `astral-sh/setup-uv` deixou de ser possível, porque o projeto não publica mais tags major flutuantes (não existe `v10`). Sugestão de texto: "versão fixada (tag de release completa ou SHA do commit), verificando a mais recente no momento da implementação".
- **SPEC_ISSUE-2 (§4.2):** "formatação padrão do `ruff format`" passou a incluir Markdown no ruff ≥ 0.17, o que entra em conflito com os trechos ilustrativos de `docs/`. Sugestão: registrar na §4.2 que `*.md` fica fora do ruff (`extend-exclude = ["*.md"]`), ou definir a exclusão estreita que o architect preferir.

Sobre a RV-01, não há SPEC_ISSUE: a §4.6 já é clara sobre qual campo vale para cada ferramenta. O problema está na implementação. A correção depende de autorização humana para tocar em `.claude/**` depois que o hook estiver ativo (§7).

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
