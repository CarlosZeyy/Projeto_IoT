# SPEC-029 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-029](../../docs/specs/SPEC-029-manutencao-dashboard-simulador.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `origin/main...c58533f` (17 commits, de `efde88c` a `c58533f`) |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante, alto ou médio. Há 1 achado baixo e 1 informativo, e nenhum `SPEC_ISSUE`. A reaprovação delegada do SPEC_ISSUE-01 está dentro dos limites do ADR-019. A do SPEC_ISSUE-02 foi humana.

## Superfície analisada

- **Segredos (R-03):** a `READ_API_KEY` lida pelo `st.secrets` durante a suíte de testes (SEC-28-01). Também conferi se ela aparece em exceções, logs e na árvore do `AppTest` quando a URL é malformada.
- **Entrada de configuração:** o `API_BASE_URL` (`is_secure_api_url`, `dashboard/src/qc_dashboard/config.py:87-110`), com a checagem de `Cc` antes do `urlsplit` e a leitura de `parts.port` dentro do `try`.
- **R-06:** o selo da carta pela origem devolvida (`dashboard/views/controle_estatistico.py:119-133`).
- **Testes:** `test_spec_013.py` (`NoSecretsFile` no `_isolated`), `test_spec_029.py` do dashboard e dos scripts (subprocessos com ambiente limpo) e `conftest.py` (`MockApi.spc_source`).
- **Fora do diff (conferido):** nada mudou em rotas, autenticação, SQL, RLS, CORS, `infra/`, `.github/`, `pyproject.toml`, `uv.lock` ou `.env.example`.

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-29-01 | baixa | input | `dashboard/src/qc_dashboard/config.py:87-110`; `dashboard/src/qc_dashboard/api.py:149` e `:164` | **RV-04 / O-01, severidade confirmada.** Fiz a reprodução de forma independente, com o `AppTest` da Visão geral, a `READ_API_KEY` gerada na hora, `httpx.HTTPTransport.handle_request` e `socket.getaddrinfo` interceptados e um handler no logger raiz. Cinco valores sem nenhum `Cc` passam por `is_secure_api_url` e derrubam a página com exceção não tratada: `https://api.exa<U+200B>mple.org` (`Cf`), `https://api.exa<U+00AD>mple.org` (`Cf`), `https://api.example.org<U+2028>x` (`Zl`), `https://api.exa<U+00A0>mple.org` (`Zs`, o mesmo caso do RV-01 do reviewer) e `https://xn--zz.com` (punycode inválido). Nos cinco: **0 requisições, 0 consultas DNS**, e a chave não aparece na mensagem nem no traceback da exceção, no log ou na árvore da página. O navegador recebe só a mensagem genérica, porque `showErrorDetails = "none"` vem do `.streamlit/config.toml`, que a imagem copia para `/app`. O traceback no log do servidor cita só o host. Por que é baixa: o valor vem do operador (`secrets.toml`/`infra/.env.dashboard`), não de um atacante; o impacto é só de disponibilidade, por erro de configuração; não há impacto de confidencialidade nem de integridade. É a mesma família do SEC-28-02, mas fora do recorte que a SPEC fixou (decisão (b) do Histórico, aprovada pelo humano: só `Cc`). **Detalhe para a correção futura:** os quatro primeiros falham no construtor do `httpx.Client` (`httpx.InvalidURL`). Já o `xn--zz.com` passa no construtor e só falha no `build_request` da primeira leitura (`idna.IDNAError`, que não é `httpx.TransportError`). Portanto, só envolver o construtor não cobre esse caso. | **Nenhuma nesta SPEC.** O orquestrador registra em `docs/plan.md` §3, na "Próxima SPEC do dashboard": validar o host dentro do `try` de `is_secure_api_url`, montando `httpx.URL(url)` e codificando o `raw_host` com o codec `idna`, como o `scripts/simulate.py` faz. Também vale o `ValueError`/`UnicodeError` virar recusa. Como alternativa, converter `httpx.InvalidURL` e `idna.IDNAError` em `ConfigError` tanto no `get_client()` quanto no `_get`. Um teste deve cobrir os cinco valores acima. |
| SEC-29-02 | info | input | `dashboard/src/qc_dashboard/config.py:87-110` | `https://api.example<U+FF0E>org` (ponto de largura total) passa pela checagem, e o `httpx` normaliza o host para `api.example.org`. A requisição sai por `https://` para o host que o operador quis dizer. Não há vazamento nem desvio de destino. Também testei se o `urlsplit` e o `httpx` discordam sobre o host nas URLs `http://` aceitas (`evil.com\@localhost`, `localhost#@evil.com`, `a@evil.com@localhost`, `localhost:8001\@evil.com`, `127.0.0.1:80@evil.com`, `localhost<U+FF0E>evil.com`, `[::ffff:127.0.0.1]`). Em todas, ou a checagem recusa, ou o `httpx` também vai para `localhost`. Nenhuma URL aceita manda a chave em claro para outro host. | Nenhuma. Fica como contexto para quem for corrigir o SEC-29-01. |

## Pontos pedidos pelo orquestrador

### 1. Reaprovação delegada do SPEC_ISSUE-01 (ADR-019, checklist §6)

Conferi o `git show --word-diff cd99179` (architect) e o `git show 4d8b5e1` (orquestrador). Depois, refiz o comportamento no código.

| Critério | Resultado | Evidência |
|---|---|---|
| E-1 Origem | ✅ | O SPEC_ISSUE-01 tem ID em `reviews/SPEC-029/r1-dev-report.md` (`0312b91`, `Agent: developer`). |
| E-2 Autoria | ✅ | `cd99179` tem `Agent: architect` e toca só `docs/specs/SPEC-029-…md` e a linha da SPEC-029 em `docs/plan.md`. |
| E-3 Estado | ✅ | Aprovada pelo humano em 2026-10-19 (PR #36) e `Blocked` pelo SPEC_ISSUE-01 (`67b8cbd`). |
| E-4 Natureza | ✅ | CA-04: um dos 7 valores recusados foi trocado (tipo 2, forma de verificação), com o texto antigo, o novo e a evidência no Histórico. §4.3: um parágrafo que descreve o `str.strip()` de `_read()`, já entregue pela SPEC-013 (tipo 1). Aviso do topo e Histórico: tipo 4. |
| E-5 Abrangência | ✅ | Só os trechos do SPEC_ISSUE-01. |
| X-1 a X-5 | ✅ nenhuma | Nenhuma SPEC ou ADR novo, nenhum `rules.md`, `architecture.md` ou contrato tocado. A §3.1, a assinatura de `is_secure_api_url` e `_read()` não mudam. |
| **X-6** (limites de segurança) | ✅ não | Nenhum limite de tamanho, taxa, timeout de produção, permissão ou autenticação foi tocado. A regra `https://` do `API_BASE_URL` (`docs/architecture.md` §9, SEC-13-01) também não mudou. Nenhum caso de erro saiu: o valor foi **trocado**, o CA-04 continua com 7 recusados, e o C1 (U+0085) continua testado. Conferi que o valor retirado não deixa brecha: `https://api.example.org/\x85`, `http://localhost\x85` e `\x85https://api.example.org` são aparados por `_read()`, e `get_settings()` devolve `https://api.example.org` e `http://localhost`, que são as URLs limpas que o cliente usa. Nenhum `Cc` de ponta chega ao `httpx`, então o erro de origem (SEC-28-02) não acontece. O caso novo `https://api.exa\x85mple.org` é recusado na branch, e só a checagem de `Cc` da §4.3 o recusa (a `main` devolve `True`, como o orquestrador e o reviewer conferiram). |
| **X-7** (regras inegociáveis) | ✅ não | O CA-04 verifica o SEC-28-02, um achado informativo de robustez sem impacto de segredo. O relatório da SPEC-028 diz que "nenhuma URL nesse caso manda a chave em claro". A asserção de não eco da mensagem, ligada à R-03 pela SPEC-028 §4.1, não foi tocada no SPEC_ISSUE-01. Os CAs ligados a R-03 e R-06 (CA-01 e CA-03) também não foram tocados. |
| X-9 | ✅ não | Primeira correção do CA-04 e da §4.3. Nenhum agente nem o humano marcou o caso como "exige humano". |

**Conclusão: dentro dos limites do ADR-019.** Não abro `SPEC_ISSUE` "exige humano". A imprecisão de horário do registro (RV-03 do reviewer) já foi corrigida em `c58533f`, um commit só de status.

**SPEC_ISSUE-02 (humano, `b2a0b76` / `6644810`):** a classificação "exige humano" pela X-9 está correta. Do lado da segurança, a asserção nova é mais forte contra o eco do valor que a antiga, porque exige a mesma mensagem nos 7 casos (`len(set(...)) == 1` no teste de aceite) e cobre também o eco parcial (`:abc`, `99999`, `local\thost`). O "nem `localhost`" que saiu não protegia nada, porque `localhost` faz parte do texto fixo. Como a reaprovação foi humana, ela não entra no escopo do ADR-019.

### 2. Severidade do RV-04 / O-01

**Baixa**, sem bloquear (SEC-29-01 acima). Os três valores da O-01 e mais dois (`U+00AD` e `NBSP`) foram reproduzidos. Nenhum deles faz sair requisição ou consulta DNS, e nenhum expõe a chave em exceção, log ou tela. É um defeito de disponibilidade, que só aparece com erro de configuração do operador, e a SPEC tirou esse caso do escopo de propósito. A correção fica para a próxima SPEC do dashboard, com o detalhe do `xn--zz.com`, que falha no `build_request` e não no construtor.

### 3. Isolamento do `st.secrets` nos testes da SPEC-013 (SEC-28-01)

- **Suíte completa com um `.streamlit/secrets.toml` fictício na raiz.** Usei um script no scratchpad da sessão que recusa rodar se o arquivo já existir, apaga o arquivo num `trap` e gera o valor na hora com `secrets.token_hex`. O arquivo aparece como `!!` (ignorado) no `git status --ignored`. Resultado: `pytest exit: 0`, `5571 passed, 52 skipped, 1 warning`, e o `grep -F` não acha o valor em nenhum ponto da saída. Depois da execução, `.streamlit/` contém só o `config.toml`. Também não existe `~/.streamlit/secrets.toml` nesta máquina.
- **Controle negativo (cenário do CA-01).** Rodei `python -m pytest -q -p no:cacheprovider <arquivo>` com `cwd=T` fora do repositório, `T/.streamlit/secrets.toml` com marcador novo e as 5 variáveis removidas:
  - `test_spec_013.py` da `origin/main` (via `git archive`): `exit=1`, `1 failed, 116 passed, 1 skipped`, e **o marcador aparece na saída**;
  - `test_spec_013.py` da branch: `exit=0`, `117 passed, 1 skipped`, com **0 ocorrências**.

  O ajuste da §4.1 fecha o vazamento, e o CA-01 distingue as duas versões.
- **O próprio CA-01 não vaza:** as asserções sobre o marcador são booleanas, a saída citada nas falhas passa por `redact`, a sonda compara dentro do subprocesso e imprime só `True`/`False`, e nem o `pyproject.toml` nem o CI usam `--showlocals`.
- **Fim da regra provisória:** do lado da segurança, a regra "tirar o `.streamlit/secrets.toml` da raiz antes de rodar a suíte" (`docs/plan.md` §3) pode ser encerrada no fechamento desta SPEC, como a Definição de pronto prevê.

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota; comparação em tempo constante | N/A. Nenhuma rota nem autenticação mudou. O cabeçalho da chave de leitura continua o mesmo (`api.py:151`). |
| Entradas validadas | ✅ `is_secure_api_url` recusa todo `Cc` antes do `urlsplit` e a porta inválida dentro do `try`. O valor nunca é ecoado: a mensagem é constante e o teste de aceite confere que é a mesma nos 7 casos. Resíduo fora do escopo: SEC-29-01 (baixa). Imagem, IDs e `extra="forbid"`: N/A. |
| SQL parametrizado | N/A. Nenhuma query no diff. |
| RLS; `DATABASE_URL`/`service_role` só na API | N/A. A única conninfo é a de teste local (`postgresql://postgres@localhost:55432/partqc_test`), sem senha. |
| CORS | N/A. |
| Logs sem segredos e sem imagem | ✅ Nenhum log novo. Com URL malformada, o log do servidor cita só o host, nunca a chave (conferido com um handler no logger raiz). |
| Dependências novas | ✅ Nenhuma (`pyproject.toml` e `uv.lock` sem mudança). `unicodedata` é da biblioteca padrão. |
| Deploy | N/A. Nada em `infra/`, `.github/` ou `.streamlit/config.toml`. O `showErrorDetails = "none"` da SPEC-015, que segura o SEC-29-01 em produção, continua igual. |
| Reaprovação delegada (ADR-019) | ✅ SPEC_ISSUE-01 dentro de E-1 a E-5, sem X-6 nem X-7 (ver acima). O SPEC_ISSUE-02 teve reaprovação humana. |
| R-03 (busca de padrões de chave no diff) | ✅ Nenhum literal com cara de chave, token ou senha. Chaves e marcadores são gerados com `secrets.token_hex`. O `.streamlit/secrets.toml` continua no `.gitignore:18` e no `.dockerignore` da imagem do dashboard. |
| R-06 | ✅ O selo também sai pela origem devolvida (`badge_shown`), uma vez só, sem requisição nova. `render_chart_badge` devolve `bool`. |
| R-02 / R-14 | N/A. Nenhum caminho de imagem foi tocado. |
| R-13 | ✅ Todos os commits têm a identidade do projeto e `Refs: SPEC-029`. Nenhuma ferramenta nem serviço corporativo. |

Suíte e qualidade, rodadas por mim:

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q   # com o secrets.toml fictício na raiz
5571 passed, 52 skipped, 1 warning in 350.87s (0:05:50)
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
223 files already formatted
```

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma dependência nova. `unicodedata` é da biblioteca padrão do Python 3.12. |

## Ações para depois do merge (não bloqueiam)

- Orquestrador: registrar o SEC-29-01 em `docs/plan.md` §3, na "Próxima SPEC do dashboard", junto do RV-01 do reviewer (o caso NBSP de `test_config.py:219`).
- Orquestrador: encerrar a regra provisória do `secrets.toml` em `docs/plan.md` §3 (Definição de pronto da SPEC).
- PR: incluir a seção "Reaprovações sob o ADR-019" com o SPEC_ISSUE-01 (`cd99179` / `4d8b5e1`).

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs. Escrevi só este relatório. Os scripts de verificação ficaram no scratchpad da sessão, fora do repositório.
- [x] Não sou autor de nenhum commit desta SPEC (nenhum commit com `Agent: security-devops` no diff).
- [x] O `.streamlit/secrets.toml` fictício existiu só durante a execução e foi apagado. Nenhum valor que pareça segredo aparece neste relatório.
