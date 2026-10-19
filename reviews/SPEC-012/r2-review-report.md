# SPEC-012 — r2 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-012](../../docs/specs/SPEC-012-ml-treino-export.md) |
| Rodada | r2 (SPEC_ISSUE-01, conserto do CI) |
| Reviewer | reviewer |
| Diff revisado | `origin/main...175d7e4` (`ba380db...175d7e4`) |
| Test report | r2-test-report.md (PASS) |
| **Veredicto** | **APPROVED** (o merge depende do SPEC_ISSUE-02, de processo, que só o humano resolve) |

O diff da r2 está correto e no escopo. O critério novo do CA-13 é sólido, cada papel tocou só os próprios arquivos, e nada mudou em `ml/src/` nem na fixture. Não há achado bloqueante, alto ou médio.

O veredicto não resolve um ponto de processo. A correção do CA-13 foi reaprovada pelo orquestrador, e não pelo humano. A R-09 e o ADR-016 reservam ao humano as reaprovações de SPEC. Registro isso como SPEC_ISSUE-02. Ele não pede rodada nova nem mudança de código, mas impede o merge (R-09; ADR-016, condição 5) até o humano confirmar a correção.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `ml/src/qc_ml/parity.py:87` | **`NaN` some do `max_abs_diff`** (T-01 do tester, confirmado). `max(max_abs_diff, nan)` do Python devolve o primeiro argumento, porque `nan > x` é falso. Reproduzi o caso do tester numa cópia da fixture: com `NaN` na referência, na posição do argmax, o resultado é `ok=True`, `max_abs_diff=8.94e-08` e `parity ok`. Com a linha inteira em `NaN`, o `ok=False` vem só do argmax, por acaso. A análise do código mostra um caso mais relevante que o do tester. Se o torch e o ONNX derem `NaN` nas mesmas linhas (um modelo cujo treino divergiu), `got - want` vira `NaN` e é descartado. O `np.argmax` devolve o índice do primeiro `NaN` dos dois lados, então a paridade diria `parity ok` para um modelo quebrado. Nenhum CA é violado. Na prática, a avaliação mostraria métricas absurdas antes do Release. | **Pendência, não r3.** A §6 da r2 proíbe mexer em `ml/src/`, o defeito não viola nenhum CA, e uma r3 seria a última rodada (R-10), gasta num item fora do escopo. Destino: o item "Próxima manutenção do ML" de `docs/plan.md:119`, junto com o RV-03 da r1 (validar `NaN` e faixa em `Predictions`), que tem a mesma raiz. Conserto sugerido: recusar saídas não finitas antes da comparação (`if not (np.isfinite(got).all() and np.isfinite(want).all())` → `ok=False`, mensagem `non-finite values`) e trocar o `max` do Python por `np.fmax` ou por uma comparação explícita. Na SPEC dessa manutenção, criar um CA com `NaN` na referência e outro com `NaN` nos dois lados. |
| RV-02 | baixa | `docs/specs/SPEC-012-ml-treino-export.md:130` (CA-13) | **Dois detalhes imprecisos na justificativa do CA-13**, sem efeito no critério. (a) O texto diz "o ruído real é ~1e-8". Nesta máquina, a fixture sem perturbação dá `max_abs_diff = 1.19e-07` (o máximo sobre as 64 saídas). (b) O limite superior soma só `1e-3 + 1e-4`. Ele ignora o arredondamento float32 da soma (≤ 6e-8), que só importaria se o CA-12 estivesse no limite de `1e-4`. As duas diferenças ficam 3 ordens de grandeza abaixo da folga de `1e-4`. | Nenhuma ação agora. Se a SPEC for editada de novo, trocar "~1e-8" por "~1e-7" e "≤ `1e-3 + 1e-4`" por "a menos de `1e-4` de `1e-3`, com folga". |

## Pontos verificados a pedido do orquestrador

### 1. Solidez do critério novo (`9e-4 < max_abs_diff < 1.1e-3`)

- **Análise:** a fixture é float32. `arrays[k][i, j] += 1e-3` soma em float64 e arredonda para float32, com erro de até meio ulp (≤ 3e-8 para valores em [0,5; 1) e ≤ 6e-8 perto de 1). A comparação em `parity.py:77-78` é feita em float64. A diferença medida é `|onnx − (ref + 1e-3 + ε)|`, que fica em `1e-3 ± (|onnx − ref| + ε)`. Os outros elementos contribuem com ~1e-7. O máximo é, portanto, o elemento perturbado.
- **Medição:** usei cópias da fixture fora do repositório e perturbei **cada** um dos 64 elementos de `type_probs` (8×3) e de `grade_probs` (8×5), com `+1e-3` e com `−1e-3` (128 casos). Resultados:
  - `max_abs_diff` sempre em `[0.00099987, 0.00100011]`, ou seja, a até `1.3e-7` de `1e-3`;
  - a folga até os limites `9e-4` e `1.1e-3` é ~770 vezes maior que o desvio observado;
  - `ok=False` em todos os 128 casos;
  - 70 dos 128 casos ficaram **abaixo** de `1e-3` exato, o que confirma que o critério antigo (`≥ 1e-3`) era frágil e dependia da CPU.
- **Intenção preservada:** a perturbação continua 10 vezes acima da tolerância de `1e-4`, e o `ok=False` continua sendo afirmado. O limite superior é um ganho: ele garante que `max_abs_diff` é a diferença absoluta do elemento perturbado, e não um valor inflado (por exemplo, `inf` de um caminho de erro de shape ou uma soma de diferenças).
- **Robustez em outra CPU:** para o teste falhar, o ruído `|onnx − torch|` do runner teria de chegar a ~1e-4. Nesse caso, o CA-12 (`< 1e-4`) também falharia, e esse seria o sinal certo. O critério não tem mais dependência de arredondamento.

Conclusão: o critério é sólido. Ver o RV-02 para duas imprecisões só de texto.

### 2. Separação de papéis (R-07)

| Commit | `Agent:` | Arquivos | Conforme |
|---|---|---|---|
| `e1777db` | orchestrator | `docs/plan.md`, SPEC (status `Blocked`) | ✅ só status |
| `1d2a9aa` | architect | SPEC (CA-13, §6, Histórico, aviso de reaprovação), `docs/plan.md` | ✅ só `docs/`, como nos commits de architect das SPECs 008, 009 e 011 |
| `fae33e7` | orchestrator | SPEC (status, aviso, linha de Histórico), `docs/plan.md` | ✅ só status e registro (ver o SPEC_ISSUE-02 sobre o conteúdo) |
| `406fd66` | ml-engineer | `ml/tests/test_parity.py` | ✅ teste do autor, fora de `tests/acceptance/` |
| `4a91922` | ml-engineer | `reviews/SPEC-012/r2-dev-report.md` | ✅ |
| `51f08d8` | orchestrator | SPEC e plano (status `In Test`) | ✅ |
| `d9ddce4` | tester | `ml/tests/acceptance/test_spec_012.py`, `reviews/SPEC-012/r2-test-report.md` | ✅ só `tests/acceptance/` e o relatório |
| `175d7e4` | orchestrator | SPEC e plano (status `In Review`) | ✅ |

Todos os commits têm o trailer `Agent:`, a identidade `Carlos Moises <179777237+CarlosZeyy@users.noreply.github.com>` (R-13) e o formato Conventional Commits. Ninguém cruzou a fronteira de papel. Não sou autor de nenhum dos commits.

### 3. Nada mais mudou em `ml/src/` nem na fixture

`git diff --name-only origin/main...HEAD -- ml/src ml/tests/fixtures` não lista nenhum arquivo. O diff inteiro toca 6 arquivos: `docs/plan.md`, a SPEC, `ml/tests/test_parity.py` (+4/−1, só a asserção do CA-13; `ok is False` e o código de saída 2 da CLI continuam), `ml/tests/acceptance/test_spec_012.py` (+2/−1, só a asserção do CA-13) e os dois relatórios. Isso bate com a §6, "Rodada r2".

### 4. Aprovação da correção no Histórico da SPEC

A linha de 2026-10-19 do Histórico registra a aprovação pelo orquestrador "sob a delegação explícita do humano em 2026-10-19 ('total autonomia para prosseguir com o projeto')". O aviso no topo da SPEC diz "Reaprovada em 2026-10-19 pelo orquestrador, sob delegação do humano". O registro existe, mas não cumpre as regras escritas. Ver o SPEC_ISSUE-02.

### 5. Destino do T-01

Vai para pendência, não para a r3. Ver o RV-01: destino em `docs/plan.md:119`, "Próxima manutenção do ML", junto com o RV-03 da r1.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | O diff faz só o que a §6 da r2 autoriza: ajusta os dois testes do CA-13. Nenhum CA foi alterado pelo autor ou pelo tester; a mudança do texto veio do architect. A rastreabilidade CA-13 → `parity.py` (sem mudança) → teste está no dev-report. Não há decisão nova embutida no código. |
| 2. Regras inegociáveis | ✅ | R-01, R-02, R-04, R-05, R-06 e R-12: N/A (nenhuma dependência, payload, rota ou serviço novo; `uv.lock` intacto). R-03: a busca por padrões de segredo no diff acha só um texto do dev report sobre exceções do Postgres. R-07: ver a tabela acima. R-11: N/A (nem split nem métricas mudaram). R-13: ✅. A aprovação da SPEC (R-08/R-09) está no SPEC_ISSUE-02, porque não é defeito do diff. |
| 3. Corretude | ✅ | O critério novo foi verificado por análise e pelas 128 perturbações. Bug de borda pré-existente fora do escopo: RV-01 (`NaN`). |
| 4. Testes | ✅ | O test-report é PASS e cobre o CA-13 com o texto novo. Os dois testes falhariam se `check_parity` deixasse de detectar a perturbação ou relatasse um `max_abs_diff` errado. O ajuste do teste de aceite é desta mesma SPEC (não de uma anterior), está na tabela do test-report e decorre do texto novo do CA-13; nenhum `test_caNN_` foi removido ou renomeado. Rodei a suíte sem torch, com `CI=true` e `TEST_DATABASE_URL` no contêiner `partqc-pg-host` (postgres:16): **4772 passed, 22 skipped, 1 warning** (293 s). Os testes de paridade não usam rede nem credencial literal. |
| 5. Qualidade | ✅ | `uv run ruff check .`: passou. `uv run ruff format --check .`: 210 arquivos já formatados. Os comentários novos nos dois testes explicam o limite e citam o SPEC_ISSUE-01. |
| 6. Segurança | N/A | A SPEC não tem a tag `security` nem `deploy`, e o autor não é o `security-devops`. |

## Pontos positivos

- O SPEC_ISSUE-01 seguiu o caminho certo: status `Blocked`, correção do texto pelo architect com a justificativa numérica e a r2 limitada aos dois testes. Ninguém "consertou" o teste por conta própria.
- O limite superior novo deixa o CA-13 mais forte que o original, e não só mais tolerante.
- O tester revisou todas as outras comparações de float do arquivo de aceite à procura da mesma fragilidade, e mediu a perturbação negativa e a de `grade_probs`. Isso mostrou que o valor abaixo de `1e-3` não era raro.
- O dev-report explica as 3 falhas do ambiente local (Postgres 18.6), e o tester confirmou que elas somem com o postgres:16 do CI.

## SPEC_ISSUE (se houver)

**SPEC_ISSUE-02 (processo; impede o merge, não pede rodada nova).** A correção do CA-13 foi reaprovada pelo orquestrador, e não pelo humano.

- **Onde:**
  - `docs/specs/SPEC-012-ml-treino-export.md:14`: aviso "Reaprovada em 2026-10-19 pelo orquestrador, sob delegação do humano";
  - `docs/specs/SPEC-012-ml-treino-export.md:184`: linha do Histórico "aprovada pelo orquestrador, sob a delegação explícita do humano em 2026-10-19 ('total autonomia para prosseguir com o projeto')"; quem pediu: "Orquestrador (delegação do humano)".
- **Conflito com as regras:**
  - `docs/rules.md`, R-09 (inegociável): "o humano [...] mantém a aprovação de SPECs e ADRs";
  - ADR-016, "O que continua com o humano": "a aprovação de SPECs [...], **as reaprovações** e os escalonamentos". Em "Riscos": "ela continua exigindo a aprovação humana explícita, e um agente nunca a substitui";
  - skill `features`, §4, passo 3: "Apresente ao humano a correção proposta e peça a reaprovação";
  - R-08: o código implementa uma SPEC aprovada por humano;
  - precedente da SPEC-011 r2: "Reaprovada pelo humano em 2026-10-18", com quem pediu "Humano (Carlos)".

  Uma instrução genérica de autonomia não é a reaprovação explícita de um CA alterado. Estender a delegação do ADR-016 às reaprovações exigiria um ADR novo e a mudança do texto da R-09, ambos aprovados pelo humano. Eu também não tenho como verificar a mensagem do humano, só o registro feito por um agente.
- **O que não é:** não é defeito do diff. O conteúdo da correção é tecnicamente correto (ver o ponto 1), e a r2 não precisa ser refeita.
- **Como resolver, sem r3:**
  1. O orquestrador apresenta ao humano a correção do CA-13 (o texto antigo e o novo, e o motivo: run 39191665982) e pede a reaprovação explícita.
  2. Aprovada, o orquestrador registra a aprovação num commit só de status, que o ADR-016 (condição 7) permite depois do review: o aviso vira "Reaprovada pelo humano em <data>", e uma linha nova no Histórico tem quem pediu "Humano (Carlos)". O PR registra a data da mensagem.
  3. Se o humano quiser que correções pequenas de SPEC_ISSUE passem a ser reaprovadas pelo orquestrador, isso vira um ADR que altera a R-09 e o ADR-016.
  4. Até lá, a `main` continua com o CI vermelho (run 39191665982). Esse custo é conhecido e não justifica dispensar a regra.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
