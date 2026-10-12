# SPEC-022 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-022](../../docs/specs/SPEC-022-manutencao-setup.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `main...c1708ef` (`main` = `61da0f4`, 16 commits) |
| Test report | r1-test-report.md (PASS, reemitido após o SPEC_ISSUE-01) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante, alto ou médio. Há 5 achados de severidade baixa, que não bloqueiam. Pendências manuais para o humano: o CA-17 (CI verde no PR, sem `db` pulado) e o CA-16 na porta 55432, depois de recriar o `partqc-pg`.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `.github/workflows/ci.yml:22` | O comentário diz "Nunca use `trust` fora do CI (R-03)", mas a própria SPEC (§4.2) e o `README.md` mandam usar `trust` no contêiner local, com a porta em `127.0.0.1`. O comentário contradiz a documentação de "Testes de banco". A §4.2 pedia só "o `trust` vale só para o contêiner efêmero do CI". | Na próxima SPEC que mexer no CI: "Fora do CI, use `trust` só no contêiner local descartável, com a porta em `127.0.0.1` (README, Testes de banco)". |
| RV-02 | baixa | `.github/workflows/ci.yml:27` | (Observação do tester, confirmada.) `ports: - 5432:5432` publica a porta em todas as interfaces do runner. Não há exposição real: o runner hospedado pelo GitHub é efêmero, não aceita conexões de entrada, o banco não tem dados, e a senha anterior (`postgres`) já era pública. A SPEC não pede mudança. | Junto com a RV-02/RV-04 da SPEC-001 (SPEC futura de CI ou SPEC-015): avaliar `127.0.0.1:5432:5432`, coerente com o README. |
| RV-03 | baixa | `.claude/hooks/guard_paths.py:225` | (Observação do tester sobre `tool_name` duplicado.) `json.loads` aceita chaves duplicadas e fica com o último valor. Conferi que `{"tool_name":"Bash",…,"tool_name":"Write"}` é avaliado como `Write`, ou seja, segue a regra de papel normal (o `.claude/x.py` do developer foi negado, rc=2). Não dá para explorar: o evento é serializado pelo Claude Code, e o agente controla só os valores dos argumentos da ferramenta, que chegam reserializados, sem chaves duplicadas. A mudança também não caberia nesta SPEC, porque a exceção da §4.5 cobre só `target_path()`, e o `json.loads` fica em `main()`. | Endurecimento opcional numa SPEC futura: `json.loads(..., object_pairs_hook=...)` que levanta `GuardError("duplicate key in event")`, em qualquer nível. |
| RV-04 | baixa | commit `61ffa97` | O commit leva `Agent: developer`, mas o relato do orquestrador e o horário (logo depois do `filter-branch` e 12 s antes do `417107d`, `Agent: orchestrator`) indicam que foi feito pelo orquestrador. Se foi, o trailer deveria ser `Agent: orchestrator`. O conteúdo é mecânico: 3 linhas, só a troca de hashes antigos (`ebef2a0`, `07a912c`, `38c5f07`) pelos novos, que conferi. Além disso, a reescrita do histórico (`filter-branch`) não está registrada em nenhum relatório versionado. | Não reescrever de novo. Registrar na descrição do PR que (a) as mensagens dos 6 primeiros commits foram reescritas antes do push, só no bloco de trailers, e (b) o `61ffa97` é do orquestrador. Daqui em diante, correções do orquestrador em relatório de outro papel levam `Agent: orchestrator`. |
| RV-05 | baixa | `docs/specs/SPEC-022-manutencao-setup.md:19`; `reviews/SPEC-001/r1-dev-report.md:65`; `reviews/SPEC-001/r1-test-report.md:51` | O objetivo do §1 ("o alerta deixa de existir") não se cumpre por inteiro no `HEAD`: a própria SPEC-022 cita `postgresql://postgres:postgres@...`, e os relatórios históricos da SPEC-001 mantêm a URL antiga, como a §7 já reconhece. O histórico do Git também. Fica fora do escopo do developer: o CA-10 exclui `docs/` e `reviews/` de propósito. Não é `SPEC_ISSUE`, porque os CAs são coerentes entre si. | Para o architect, num próximo toque em docs: escrever `postgresql://postgres:<senha>@...` no §1. Para o humano: marcar o alerta do scanner como falso positivo e, se o scanner permitir, colocar `reviews/SPEC-001/` numa lista de exceções. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | O diff cobre §4.1 a §4.4, e nada além. A rastreabilidade CA → arquivo/teste está no dev-report. Nenhum CA foi alterado pelo autor. A única mudança na SPEC durante a rodada (`afa4173`, preâmbulo da §5) foi do architect, motivada pelo SPEC_ISSUE-01 e reaprovada pelo humano (`820f8bb`). As decisões do developer (`PATH_FIELD_BY_TOOL`, `OTHER_PATH_FIELD`, manter `POSTGRES_USER`) estão dentro do que a §4.1, §4.2 e §4.5 permitem. |
| 2. Regras inegociáveis | ✅ | **R-01:** nenhuma dependência nova (sem mudança em `uv.lock`/`pyproject.toml`). **R-02, R-04, R-05, R-06, R-11:** N/A. **R-03:** a busca no diff por `key`/`secret`/`token`/`password`/`postgres://…:…@`/`eyJ` só encontra nomes de variável vazios, texto de SPEC/relatório e sequências montadas por concatenação nos testes. Nenhum valor de segredo. Ver RV-05. **R-07:** ver "Separação de papéis" abaixo. **R-12:** N/A (sem dependência nova). **R-13:** os 16 commits usam `Carlos Moises <179777237+CarlosZeyy@users.noreply.github.com>`, seguem Conventional Commits, e não há menção a empresa no diff. |
| 3. Corretude | ✅ | `target_path()` segue a ordem exata da §4.1 (6 regras, mensagens literais, `repr` no `tool_name`). A regra 5 usa presença da chave. `main()` continua falhando fechado: `GuardError` → 2; qualquer `Exception` → 2; `BaseException` no `__main__` → 2. O hook é compatível com Python ≥ 3.10 (o tester rodou com 3.10.22 e 3.14). Ver RV-03. |
| 4. Testes | ✅ | Test-report PASS, com 39 testes de aceite para CA-01…CA-16. Rodei de novo, sem `CI`/`TEST_DATABASE_URL`: `268 passed, 3 skipped` (os 3 são `db`). Os testes não são tautológicos: a mutação com o hook da `main` deu `18 failed` (tester) e `30 failed` (autor). CA-07 e CA-15 rodam o pytest em subprocesso. CA-10 varre todo o `git ls-files`. O teste `test_texts_match_spec_quotes` amarra os textos literais às citações da SPEC. Sem mocks e sem rede. CA-17 e CA-16 na porta 55432 ficam pendentes (manuais). |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos (24 arquivos). As constantes têm nomes claros e comentário. As docstrings do módulo e de `target_path` foram atualizadas. README e `.env.example` foram atualizados. Ver RV-01. |
| 6. Segurança | N/A | Tag `infra`, sem portão formal. A análise pedida pelo orquestrador está logo abaixo. |

### Exceção de caminhos (§4.5 / CA-18)

- `git diff --stat main...HEAD -- .claude/ reviews/README.md`: só `.claude/agents/architect.md` (+1/−1), `.claude/hooks/guard_paths.py` (+42/−11) e `reviews/README.md` (+2). Nenhum outro arquivo de `.claude/**` mudou, e `.claude/settings.json` e os outros agentes estão intactos.
- `ROLES`: comparei a AST da `main` e do `HEAD`, e é idêntica. As únicas definições de topo que mudaram são `target_path`, `PATH_FIELD_BY_TOOL` e `OTHER_PATH_FIELD` (mais a docstring do módulo), exatamente o que a §4.5 permite.
- `architect.md`: o frontmatter (entre os dois `---`) é idêntico ao da `main`. A única linha alterada é o corpo de `## Commits` (linha 39).
- `reviews/README.md`: só o parágrafo novo, logo depois de `**Rastreio de papéis:**`.
- Os três arquivos foram alterados nos commits `9701352` e `9e652d3`, ambos com `Agent: developer`. Os scripts `python3 - <<'EOF'` estão no dev-report na íntegra e batem com o diff.

### Separação de papéis (R-07)

| Commit | Agent | Arquivos | Conferência |
|---|---|---|---|
| `a487f3c`, `afa4173` | architect | só `docs/` (SPEC-022, SPEC-001 com entrada no Histórico, `docs/plan.md`, `docs/README.md`) | ✅ Feitos pelo orquestrador, porque o architect não tem shell. É exatamente a regra que esta SPEC registra em `reviews/README.md`: só arquivos de `docs/`, sem `docs/rules.md` e sem arquivo de outro papel. |
| `01424ca`, `417107d`, `f33b20e`, `820f8bb`, `c1708ef` | orchestrator | só status em `docs/plan.md` e no cabeçalho/Histórico da SPEC-022 | ✅ |
| `9701352`, `4507ae4`, `9e652d3`, `b5285ae`, `61ffa97` | developer | produção (hook, CI, `.env.example`, README, architect.md, `reviews/README.md`), testes do autor em `tests/` e dev-report | ✅ Nada em `tests/acceptance/` nem em `docs/`. Ver RV-04 sobre o `61ffa97`. |
| `2a6bdc5`, `f90438c`, `4f9f9ab`, `e059008` | tester | só `tests/acceptance/` e test-report | ✅ A troca do CA-20 em `tests/acceptance/test_spec_001.py` foi atribuída ao tester pela §3.1. |

Reescrita de mensagens (`filter-branch`): pelo reflog, comparei os 6 commits originais (`8d0b254`, `283b9b2`, `ebef2a0`, `07a912c`, `38c5f07`, `f053e4b`) com os reescritos (`a487f3c`, `01424ca`, `9701352`, `4507ae4`, `9e652d3`, `b5285ae`). As árvores são idênticas, e autor e datas também. Os trailers `Agent:` e `Refs:` são os mesmos, e só a linha em branco entre `Agent:` e `Co-Authored-By:` saiu. A branch nunca foi enviada ao remoto (`git ls-remote` não a lista). A reescrita não alterou conteúdo nem a atribuição de papéis.

### Segurança (pedido do orquestrador)

- **O hook falha fechado?** Sim. Todas as entradas ambíguas novas dão 2, e o tratamento de exceções de `main()`/`__main__` não mudou. O hook ficou **mais** restrito: antes, um `NotebookEdit` com `file_path` permitido passava (RV-01 da SPEC-001); agora é negado. O único risco remanescente de falha aberta é conhecido (Bash, workspace trust), e esta SPEC o documenta no README.
- **O `trust` fica restrito?** Sim, no que esta SPEC controla. Localmente, o comando do README publica só em `127.0.0.1:55432`. O tester confirmou que a conexão pelo IP da LAN é recusada e que o contêiner temporário foi removido. No CI, o contêiner é efêmero e o runner não aceita conexões de entrada (RV-02 é só alinhamento). Em nenhum dos dois casos o banco tem dados reais, e o `DATABASE_URL` de produção (Supabase) não é afetado: continua com placeholder vazio no `.env.example`.
- **Precisa de um portão adicional do security-devops?** **Não.** Nenhum achado passa de baixa. Não há serviço, dependência, deploy, rota de API nem segredo real envolvido. A mudança no hook só restringe, e está coberta por testes de mutação. RV-01 a RV-03 podem ir para a próxima SPEC de CI (SPEC-015, que já tem portão `deploy`/`security`).

## Pontos positivos

- A exceção de caminhos foi seguida à risca: os scripts usam `assert text.count(old) == 1` antes de substituir, estão no relatório na íntegra, e não há nenhum `Write`/`Edit` em área bloqueada.
- Os dois papéis fizeram teste de mutação contra o hook da `main`, o que prova que os testes detectam a regressão do RV-01.
- As sequências proibidas são montadas por concatenação nos testes, então o CA-10 não acusa o próprio arquivo de teste.
- O tester fez exploração útil: Python 3.10/3.14, Unicode, `File_Path`, ordem das regras, chave duplicada e loopback real.
- O SPEC_ISSUE-01 foi tratado pelo fluxo correto: o tester não ajustou o teste a um comportamento que contradizia a SPEC; o architect corrigiu; o humano reaprovou; o teste foi reexecutado.

## SPEC_ISSUE (se houver)

Nenhum. A RV-05 é uma observação para o architect e o humano, e não bloqueia: os CAs são coerentes e testáveis como estão.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
