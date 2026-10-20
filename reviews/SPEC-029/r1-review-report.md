# SPEC-029 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-029](../../docs/specs/SPEC-029-manutencao-dashboard-simulador.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `origin/main...19d996b` (14 commits, de `efde88c` a `19d996b`) |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante ou alto. Há 4 achados baixos, que não bloqueiam, e nenhum `SPEC_ISSUE`.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `dashboard/tests/test_config.py:219` | O caso `"https://api.exa mple.org".replace(" ", "")` (o literal tem um NBSP de verdade, conferido com `od -c`) remove o NBSP antes do teste. Por isso, o valor testado é `https://api.example.org`, igual ao segundo caso da lista, e o comentário `# NBSP is Zs, not Cc` descreve um caso que não é exercitado. O teste não é falso, mas está duplicado e engana quem lê. Se o NBSP ficasse na URL, `is_secure_api_url` devolveria `True`, e o `httpx.Client` quebraria do mesmo jeito que na O-01. | Numa próxima passagem do autor, remover o caso. Ou então testar o NBSP sem o `.replace` e registrar que ele é aceito pela checagem, de propósito (fora do `Cc`, decisão (b) do Histórico). |
| RV-02 | baixa | `dashboard/tests/acceptance/test_spec_029.py:66` e `:361` | O CA-02 fixa `SPEC013_COUNT_ON_MAIN = 118` e compara os node ids com a ref local `main` antes da `origin/main`. Duas consequências: (a) uma SPEC futura que ajuste `test_spec_013.py` pela regra do §10 (por exemplo, um parâmetro novo num teste extra) também vai ter que ajustar este teste, e essa linha precisa entrar na tabela do test-report dela; (b) com uma `main` local desatualizada, a comparação usa uma base velha. É uma consequência direta do texto do CA ("o mesmo número da `main`"), e não um erro do tester. | Nada nesta SPEC. Fica registrado para o tester da próxima SPEC que tocar `test_spec_013.py`. Opcional: preferir `origin/main` à `main` local. |
| RV-03 | baixa | `docs/specs/SPEC-029-manutencao-dashboard-simulador.md:16` e `:139` (Histórico) | Imprecisões de registro no status da SPEC, sem efeito no conteúdo aprovado: (a) o aviso diz que a reaprovação delegada foi feita "em 2026-10-20 02:50 UTC", mas o commit `4d8b5e1` é de 2026-10-20 02:40:20 UTC (23:40:20 -0300); (b) a linha da correção do SPEC_ISSUE-01 está datada de 2026-10-19, mas o commit `cd99179` é de 2026-10-20 02:40:02 UTC (data local em vez de UTC, contrariando a convenção de datas); (c) a linha da reaprovação humana do SPEC_ISSUE-02 diz "`Blocked` → `In Dev`, retomada na r1", mas o commit `6644810` levou a SPEC a `In Test`, como explica a própria mensagem do commit. | O orquestrador corrige os três pontos num commit de status (por exemplo, no `Done`), e a seção "Reaprovações sob o ADR-019" do PR usa o horário do commit `4d8b5e1`. |
| RV-04 | baixa | `dashboard/src/qc_dashboard/config.py:87-110` (O-01 do test-report) | Confirmo a O-01: `https://api.exa​mple.org` (`Cf`) e `https://api.example.org x` (`Zl`) passam por `is_secure_api_url` e fazem o `httpx.Client` levantar `httpx.InvalidURL` (reproduzido). `https://xn--zz.com` passa na criação do cliente e falha depois. É a mesma família do SEC-28-02, mas a SPEC limitou de propósito a checagem ao `Cc` (decisão (b) do Histórico, aprovada pelo humano), e o objetivo da §2 ("porta inválida ou caractere de controle") está cumprido. O impacto é baixo: é um erro de configuração do operador, a página mostra uma exceção (sem detalhes em produção, `showErrorDetails = "none"`), nenhuma requisição sai e a chave não aparece. | Não é bug contra a SPEC-029. Registrar em `docs/plan.md` §3, na "Próxima SPEC do dashboard": validar a URL com o próprio `httpx.URL(...)` dentro do `try` de `is_secure_api_url`, ou converter `httpx.InvalidURL` em `ConfigError` no `api.get_client()`. A decisão de severidade final fica com o portão de segurança. |

## Reaprovações de SPEC nesta branch (checklist §1, ADR-019)

### SPEC_ISSUE-01: reaprovação delegada ao orquestrador (architect `cd99179`, aprovação `4d8b5e1`)

Conferi o `git show --word-diff` dos dois commits.

| Critério | Resultado | Evidência |
|---|---|---|
| E-1 Origem | ✅ | O SPEC_ISSUE-01 está registrado com ID em `reviews/SPEC-029/r1-dev-report.md` no commit `0312b91` (`Agent: developer`), com a reprodução (`'https://api.example.org/\x85'.strip()` → `'https://api.example.org/'`). |
| E-2 Autoria | ✅ | `cd99179` tem `Agent: architect` e toca só `docs/specs/SPEC-029-…md` e `docs/plan.md` (só a linha da SPEC-029). |
| E-3 Estado | ✅ | Aprovada pelo humano em 2026-10-19 (Histórico, PR #36) e `Blocked` por este SPEC_ISSUE (`67b8cbd`). |
| E-4 Natureza | ✅ | CA-04: troca de um dos 7 valores recusados (`https://api.example.org/\x85` → `https://api.exa\x85mple.org`), tipo 2 (forma de verificação), com o texto antigo, o novo e a evidência no Histórico. §4.3: um parágrafo novo, tipo 1. Ele descreve o `str.strip()` de `_read()`, comportamento já entregue pela SPEC-013 §4.1, e não pede comportamento novo. Aviso do topo e Histórico: tipo 4. |
| E-5 Abrangência | ✅ | Só o caso do CA-04, a frase da §4.3, o aviso, o Histórico e a linha do `plan.md`. |
| X-1 a X-4 | ✅ nenhuma | A SPEC já existia e já estava aprovada; nenhum ADR, `rules.md`, `architecture.md` ou contrato foi tocado. |
| X-5 Escopo novo | ✅ não | A §3.1, a assinatura de `is_secure_api_url` e `_read()` não mudam. A opção que o architect descartou (checar o `Cc` antes do `strip()`) é que seria X-5. |
| X-6 CA enfraquecido | ✅ não | Este era o ponto delicado: o valor com `\x85` no fim deixou de ser um caso de erro. Mas ele não podia ser recusado sem mudar `_read()`, e o valor aparado é o que o cliente usa, então não produz o erro de origem (SEC-28-02). O número de casos recusados continua 7, e o C1 continua coberto. Conferi na `main` que `is_secure_api_url('https://api.exa\x85mple.org')` devolve `True` e, na branch, `False`: o caso novo exige a checagem de `Cc`, como o orquestrador registrou. Nenhum limite de segurança mudou. |
| X-7 Regra inegociável | ✅ não | O CA-04 verifica o SEC-28-02. Pelo próprio relatório de segurança da SPEC-028, "nenhuma URL nesse caso manda a chave em claro". A asserção de não eco da mensagem, ligada à R-03 pela SPEC-028 §4.1, não foi tocada nesta correção. |
| X-9 | ✅ não | Foi a primeira correção do CA-04 e da §4.3 nesta SPEC. Nenhum agente nem o humano marcou o caso como "exige humano". |
| Registro do orquestrador | ✅ (ver RV-03) | Commit só de status, com `Agent: orchestrator`, aviso do topo e linha do Histórico no formato do ADR-019, citando `cd99179`. O horário do aviso diverge do commit (RV-03 a). |

Observação: entre `cd99179` (02:40:02 UTC) e `4d8b5e1` (02:40:20 UTC) passaram 18 segundos. O histórico não mostra se a conferência do orquestrador foi completa. Refiz a conferência de forma independente, e a classificação se sustenta.

**Conclusão: dentro dos limites do ADR-019.** Não há `SPEC_ISSUE` "exige humano". O PR precisa ter a seção "Reaprovações sob o ADR-019" com o SPEC_ISSUE-01 (`cd99179` / `4d8b5e1`).

### SPEC_ISSUE-02: reaprovação humana (architect `b2a0b76`, registro `6644810`)

- O architect classificou o caso como "exige humano" pela X-9: segunda correção do mesmo CA nesta SPEC, mesmo sendo outro trecho. A classificação está correta, porque a X-9 fala em "o mesmo CA ou trecho".
- `b2a0b76` tem `Agent: architect` e toca só a SPEC e a linha do `plan.md`. O Histórico tem o texto antigo, o novo e a evidência.
- A reaprovação foi registrada pelo orquestrador como humana, "Humano (Carlos)", em `6644810`.
- Sobre o conteúdo: a asserção nova ("a mesma mensagem para os 7 valores, contém `API_BASE_URL`, não contém o valor nem `example.org`") é mais forte que a antiga contra o eco parcial e preserva a regra "nunca o valor" da SPEC-028 §4.1. Como foi o humano quem reaprovou, isso não entra no escopo do ADR-019.
- O orquestrador levou a SPEC direto a `In Test`, sem passagem nova do developer. Está correto: o código de `73fcecf` já mantinha a mensagem constante, e nenhuma linha de produção precisava mudar.

## Ajustes em testes de aceite de SPECs anteriores (`docs/architecture.md` §10)

Conferi o `git diff origin/main...HEAD -- dashboard/tests/acceptance/test_spec_013.py`. Mudaram só três coisas:

1. a classe `NoSecretsFile`, nova e copiada de `test_spec_028.py:239`, com o mesmo comportamento;
2. a linha `monkeypatch.setattr(st, "secrets", NoSecretsFile())` no `_isolated`;
3. o comentário de `test_extra_retry_while_still_down_is_bounded`.

Nenhuma asserção mudou, e nenhum `test_caNN_` foi tocado ou renomeado. O arquivo continua com 118 testes coletados. As duas edições estão na tabela do test-report, ligadas à §4.1 itens 1 e 2. A §3.1 as autoriza de forma explícita e mantém a intenção dos CAs da SPEC-013. A escolha entre copiar e importar foi registrada, como a §4.1 pede. O ajuste está num commit próprio do tester (`6207f4b`). ✅

## Rastreabilidade

| CA | Implementação | Teste de aceite (exercita de fato?) |
|---|---|---|
| CA-01 | §4.1 (tester, `6207f4b`) | ✅ `test_ca01_…`: pytest em subprocesso só com `test_spec_013.py`, `cwd=T` fora do repositório, as 5 variáveis removidas e uma sonda que prova que o `st.secrets` real lê o marcador. O tester registra que o teste falhou antes do ajuste. |
| CA-02 | §4.1 (tester) | ✅ `ast.get_source_segment` mais coleta comparada à `main` (RV-02). |
| CA-03 | `dashboard/views/controle_estatistico.py:119-133` | ✅ três cenários com `SpcResponse` válido e 0 requisições a `/metrics/summary`. Os exploratórios conferem que há uma única requisição ao SPC e que o selo fica antes do gráfico. |
| CA-04 | `dashboard/src/qc_dashboard/config.py:97` (`Cc` antes do `urlsplit`) e `:102` (`parts.port` dentro do `try`) | ✅ os 7 valores pelo `get_settings()` e pela Visão geral (com `httpx.HTTPTransport.handle_request` interceptado), mais os 4 aceitos. |
| CA-05 | `scripts/tests/test_simulate.py` (caso novo e `test_idna_case_needs_raw_host`) | ✅ subprocesso com caminho explícito: 1 coletado, `1 passed`. O dev-report registra a mutação `.raw_host` → `.host`, com a qual o caso falha. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Todos os requisitos da §4 foram implementados, e nada fora da §3.1: `config.py` mudou só em `is_secure_api_url`, a view só no selo, `filters.py` não mudou, e `simulate.py` não mudou. Nenhum CA foi reinterpretado: os dois conflitos viraram SPEC_ISSUE-01 e SPEC_ISSUE-02. A rastreabilidade está no dev-report. A reaprovação delegada foi conferida acima e está dentro dos limites; a humana também foi conferida. |
| 2. Regras inegociáveis | ✅ | R-01/R-12: nenhuma dependência nova (`uv.lock`, `pyproject.toml` e `.env.example` não mudaram). R-03: a busca no diff só achou chaves e marcadores gerados com `secrets.token_hex`; a única conninfo é `postgresql://postgres@localhost:55432/partqc_test`, sem senha, e já aparecia em relatórios anteriores; o tester ainda rodou a suíte com um `secrets.toml` fictício na raiz, sem vazamento. R-06: o selo agora também aparece pela origem devolvida (CA-03). R-07: ver abaixo. R-13: todos os commits são de `Carlos Moises <…CarlosZeyy@users.noreply.github.com>`, no padrão Conventional Commits, com `Refs: SPEC-029`. R-02, R-04, R-05, R-11: N/A. |
| 3. Corretude | ✅ | O `Cc` é checado antes do `urlsplit` (que descarta `\t\n\r`). `parts.port` fica dentro do `try`. Porta vazia, `:0` e `:65535` são aceitas, e `:+80`, `:0x50`, `:%38%30` e dígitos de largura total são recusados (conferido). O selo pela origem devolvida usa `badge_shown`, sem duplicar e sem requisição nova; se o `api_guard` interrompe, o trecho não roda. Resíduo fora do escopo: RV-04. |
| 4. Testes | ✅ (RV-01, RV-02 baixos) | test-report PASS cobrindo os 5 CAs. Os testes não são tautológicos, e o mock é só da fronteira HTTP. Os ajustes do §10 estão conferidos. Os subprocessos passam caminhos explícitos, sem banco e sem a suíte inteira. Nenhuma credencial literal. Suíte rodada por mim: `CI=true TEST_DATABASE_URL=… uv run pytest -q` deu `5571 passed, 52 skipped, 1 warning` (os skips são do Docker, e a warning já existia), o mesmo número do test-report. |
| 5. Qualidade | ✅ | `ruff check` está limpo e `ruff format --check` dá "223 files already formatted". As funções têm type hints e não há `print`. A docstring da view foi atualizada. O README não muda (§4.1). |
| 6. Segurança | N/A neste relatório | O portão `security` fica com o security-devops, em `r1-security-report.md`. A conferência da reaprovação delegada pelo checklist §6 também é dele. Do lado do reviewer, ela já está feita acima. |

### R-07 (trailers × arquivos)

| Papel | Commits | Arquivos |
|---|---|---|
| developer | `0312b91`, `73fcecf`, `94de48e`, `c21ebde`, `f42e616` | `dashboard/src`, `dashboard/views`, `dashboard/tests/{conftest,test_config,test_pages}.py`, `scripts/tests/test_simulate.py`, dev-report. Nada em `tests/acceptance/`. |
| tester | `6207f4b`, `9ce0a4c` | Só `*/tests/acceptance/` e o test-report. Nenhum código de produção. |
| architect | `cd99179`, `b2a0b76` | Só a SPEC-029 e o `docs/plan.md`. |
| orchestrator | `efde88c`, `67b8cbd`, `4d8b5e1`, `acee920`, `6644810`, `19d996b` | Só o status da SPEC-029, a SPEC-033 (`Done`) e o `docs/plan.md`. |

Todos os commits têm o trailer `Agent:`, e nenhum papel cruzou a fronteira. ✅

## Pontos positivos

- O developer parou duas vezes diante de contradições reais da SPEC, em vez de improvisar, e trouxe uma reprodução mínima e opções de resolução nas duas.
- O CA-01 prova a premissa com uma sonda: o `st.secrets` real do subprocesso lê o marcador. O teste falha de forma redigida (`<marker>`), então nem uma falha vazaria o valor.
- A suíte completa foi rodada com um `secrets.toml` fictício na raiz, com `trap` de limpeza. Isso cobre o motivo do prazo da SPEC.
- A tabela de `Cc` do autor (65 caracteres × 5 posições) e os testes de aparar as pontas documentam o parágrafo novo da §4.3.
- A O-01 traz passos de reprodução e uma sugestão de correção, e não foi transformada em bug contra a SPEC.

## SPEC_ISSUE (se houver)

Nenhum. A reaprovação delegada do SPEC_ISSUE-01 está dentro dos limites do ADR-019. A do SPEC_ISSUE-02 foi humana.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
