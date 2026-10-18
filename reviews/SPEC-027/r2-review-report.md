# SPEC-027 — r2 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-027](../../docs/specs/SPEC-027-manutencao-api-banco-simulador.md) |
| Rodada | r2 |
| Reviewer | reviewer |
| Diff revisado | `main...83cc7db`, com foco em `cd94f41..83cc7db` (o que mudou desde o r1-review-report) |
| Test report | r2-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Não há achado bloqueante nem alto, e há 1 achado baixo (RV-01). Esta rodada confere quatro pontos:

- o SEC-01 do [r1-security-report](r1-security-report.md) (= RV-01 do [r1-review-report](r1-review-report.md)) foi corrigido exatamente como o security-report exigiu, com `raw_host` e não com `.host`;
- nada além do autorizado mudou;
- a correção da OBS-04 (RV-02 da r1) está certa;
- o CA-12 continua valendo pela r1.

A SPEC tem a tag `security`, então o próximo passo é o security-devops.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `scripts/tests/test_simulate.py:1131-1145` (`test_visible_ascii_api_url_still_sends`) | O motivo de usar o `raw_host` é não recusar por engano um domínio IDNA 2008 válido. Nenhum teste do autor protege esse motivo. O único caso `xn--` do autor é o `xn--nxasmq6b.com`, que o security-report citou, e o codec aceita esse domínio **nas duas formas**. Conferi: `raw:ok` e `host:ok`. Se a linha voltasse a usar `.host`, os testes do autor continuariam passando. Quem pega essa regressão é o extra do tester `xn--1-zhc.com` (`א1.com`): ele dá `raw:ok` e `host:ERR` (regra bidi do IDNA 2003), e a mutação do tester com `.host` falha exatamente nos 2 casos dele. Então o comportamento está coberto. O que falta é o teste do autor cobrir o próprio comentário de `simulate.py:426-427`. | Não exige ação nesta SPEC. Na próxima manutenção do simulador, incluir `https://xn--1-zhc.com` nos casos de aceitação do autor. |

## SEC-01 / RV-01 da r1: a correção

| Ponto exigido pelo security-report | Conferência no diff | Resultado |
|---|---|---|
| Mesmo `try` de `_api_url` | `scripts/simulate.py:423-428`: a linha nova fica logo depois do `_ = httpx.URL(url).host` (decisão 6 da r1), dentro do mesmo `try`/`except (ValueError, httpx.InvalidURL)`, que leva a `parser.error(f"invalid --api-url {NOT_SHOWN}")` e ao código 2. | ✅ |
| Forma exata: `httpx.URL(url).raw_host.decode("ascii").encode("idna")` | A linha é exatamente essa, caractere por caractere. Não usa `.host`. O comentário explica por que o `raw_host` é usado e por que a conferência da r1 continua. | ✅ |
| `UnicodeError` cai no `except` | `UnicodeError` é subclasse de `ValueError`. O `UnicodeDecodeError` do `.decode("ascii")` também é, mas não acontece: o `raw_host` do httpx é sempre ASCII, e o filtro de ASCII visível roda antes. | ✅ |
| É o mesmo codec do socket | `create_connection` chama `getaddrinfo`, que codifica o host `str` com o codec `idna` (o caminho httpx → httpcore → socket está descrito no security-report). O teste de premissa do tester usa o `getaddrinfo` **real** com `AI_NUMERICHOST`, sem DNS, e recusa exatamente os 5 hosts do SEC-01, nenhum dos 12 aceitos. | ✅ |
| Sem efeito colateral nas outras validações | Host vazio (`https:///p`, `https://`, `https://:443`): o `raw_host` é `b""` e o `encode` devolve `b""`, então a recusa continua sendo a de `not host`, com código 2. A ordem das validações e as mensagens não mudam. | ✅ |
| Duas conferências, e não uma só | **Aceita** (decisão 1 do r2-dev-report). O `.host` recusa o `xn--zz.com`, que o codec do socket deixaria passar (o httpx falharia ao montar a requisição). O `raw_host` com o codec recusa o que o socket recusaria. Nenhuma das duas cobre a outra. | ✅ |
| Testes do autor exigidos pelo SEC-01 | Recusa: `exa..mple.com`, `.example.com`, `example.com..`, rótulo de 64 caracteres com e sem domínio. Os testes conferem código 2, 0 requisições, a mensagem `(not shown)`, ausência de `Traceback` e ausência de trechos do host. Aceitação: `example.com.`, rótulo de 63 (×2), `https://[::1]` (e `:8443`), `xn--nxasmq6b.com`, `localhost:8001` e `127.0.0.1` (×2), todos com código 0 e 1 lote. Há também o teste de premissa sobre o codec. Todos os casos da lista do security-report estão presentes. | ✅ (RV-01 baixo acima) |

**Reprodução própria, com o `simulate.py` do `HEAD` em processo próprio e chave gerada por `secrets`:**

- `https://exa..mplemark.invalid/pathtok`, `https://.examplemark.invalid`, `https://examplemark.invalid..` e `https://<64×q>`: `exit=2`, última linha `simulate.py: error: invalid --api-url (not shown)`, 0 `Traceback`, 0 ocorrências de `examplemark`, `pathtok`, `qqqq` ou da chave no stdout e no stderr.
- `https://127.0.0.1:1` e `http://127.0.0.1:1`: `exit=5`, `health check failed: ConnectError`. Os hosts válidos continuam chegando ao socket.

## Nada além do autorizado

| Commit | Agent | Arquivos | Resultado |
|---|---|---|---|
| `02a8449` | security-devops | `reviews/SPEC-027/r1-security-report.md` | ✅ |
| `798fb63`, `beaa54c`, `acd2e5c`, `83cc7db` | orchestrator | só `docs/plan.md` e o cabeçalho da SPEC (status e rodada). Nenhum texto de requisito ou CA mudou. | ✅ |
| `00f121e` | developer | `scripts/simulate.py` (+6 linhas, só a conferência e o comentário) e `scripts/tests/test_simulate.py` | ✅ |
| `8c1629b` | developer | `reviews/SPEC-027/r2-dev-report.md` | ✅ |
| `65ab53e` | tester | `scripts/tests/acceptance/test_spec_027.py` e `reviews/SPEC-027/r2-test-report.md` | ✅ |

`git diff --stat cd94f41..HEAD -- . ':!scripts' ':!reviews'` só mostra `docs/plan.md` e a SPEC, uma linha cada, nos commits do orchestrator. Não mudaram `api/`, `packages/`, `infra/`, `dashboard/`, `edge/`, `ml/`, `README.md`, `pyproject.toml`, `uv.lock` nem `.env.example`. SEC-02 a SEC-04, RV-02 (produção) e RV-03 ficaram intocados, como determinado. Os testes de aceite de CA (`test_ca07_*` a `test_ca11_*`) não mudaram: o tester só acrescentou extras e ajustou os dois extras citados abaixo.

**Ajustes do tester nos próprios extras da r1:**

- `test_extra_ascii_urls_that_httpx_rejects_exit_2` deixou de aceitar `0 ou 2` e agora fixa o código de cada caso. Os 5 casos de recusa usam `assert_clean_usage_error`, a mensagem e 0 requisições. Os 3 hosts do SEC-01 foram para os extras do CA-11, e o `a*64 + ".com"` virou o `LABEL_64` equivalente. Os 3 hosts aceitos foram para `test_extra_odd_but_usable_ascii_urls_still_send` (código 0, 1 lote). A asserção ficou mais forte, não mais fraca.
- `test_extra_more_bad_lot_lists_exit_2`: comparei com o `cd94f41`. A lista de valores é idêntica. O id `trailing-space` saiu da 7ª posição, onde rotulava `+7`, e `inner-space` entrou no fim, para `7 7`. Agora os 10 ids correspondem aos 10 valores.

## OBS-04 corrigida (RV-02 da r1)

**Correta.** O texto novo do r2-test-report:

1. Reconhece que a frase da r1 ("nunca saem com código 1") só tinha sido verificada com o `MockTransport`.
2. Descreve com exatidão o comportamento da r1: rótulo vazio ou com mais de 63 caracteres levava a `UnicodeError`, código 1 e traceback com a API real, e a código 0 com a API falsa. É o que eu e o security-devops reproduzimos na r1.
3. Descreve o comportamento da r2: código 2, conferido acima.
4. Separa os casos em que a frase da r1 sobre o código 5 vale (`-bad-`, `a-.com`, `_dmarc`, porta vazia, `0x7f.1`, nomes longos com rótulos de até 63 caracteres). O teste de caminho real `…real_path_valid_hosts_reach_the_socket` cobre 3 deles, com código 5 e 1 chamada ao socket.

A frase final ("a SPEC não pede validação de sintaxe DNS além do que o cliente e o socket exigem") está de acordo com o §4.3.5, que trata de código 1 e traceback, e não de sintaxe DNS. O test-report também corrige, com razão, o exemplo do security-report: o `xn--nxasmq6b.com` não diferencia `raw_host` de `.host`, e o `xn--1-zhc.com` diferencia. Conferi as duas afirmações (ver RV-01).

## CA-12 vale pela r1

**Sim.** O CA-12 pede 30 execuções seguidas de `test_spec_004.py -k real_server` sem falha, uma execução da suíte inteira e o registro no test-report.

- As 30 execuções foram feitas na r1, depois do `efe5d8f` (a correção da §4.4). Conferi que o `efe5d8f` é ancestral do `HEAD`.
- `git diff --name-only efe5d8f..HEAD` lista só `docs/`, `reviews/` e os três arquivos de `scripts/`. Não mudaram `api/` (o servidor que o uvicorn sobe e o próprio `test_spec_004.py`), `packages/`, `infra/`, o `conftest.py` da raiz, o `pyproject.toml` nem o `uv.lock`. Os testes `real_server` não importam `scripts/`.
- O item 3 (suíte inteira) foi refeito na r2 pelo tester (2815 passed com banco), e eu o refiz também (abaixo).
- O registro (comando, 30 contagens, diagnóstico e correção) está no r1-test-report, e o r2-test-report remete a ele.

Refazer as 30 execuções não daria nenhuma informação nova sobre código que não mudou. A amostra do tester (3×) e a minha (3×, abaixo) confirmam que nada piorou no ambiente.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | A r2 fecha o resíduo do §2 e do §4.3.5, e nada além disso. Nenhum CA foi alterado. A rastreabilidade do dev-report foi atualizada para CA-09 e CA-11, com a tabela caso → teste da lista do SEC-01. As 3 decisões do dev-report cabem no §4.3.5 (a decisão 1 está avaliada acima; as decisões 2 e 3 são testes extras). |
| 2. Regras inegociáveis | ✅ | R-01, R-02 e R-12: nenhuma dependência nova, nenhuma imagem. R-03: busca no diff da r2 por `password=`, conninfo `:x@`, `eyJ`, `sk_`, `service_role`, chave privada e `X-API-Key` literal. As únicas ocorrências estão em textos dos relatórios que descrevem a própria busca. As chaves e os marcadores vêm de `secrets`, e não há variável nova. R-04, R-05 e R-06: sem mudança. R-07: os 8 commits de `cd94f41..HEAD` têm o trailer `Agent:`, e os arquivos de cada um conferem com o papel (tabela acima). O developer não tocou em `tests/acceptance/`, e o tester não tocou em produção. R-10: r2 de 3. R-13: autor `CarlosZeyy` (noreply) em todos, Conventional Commits, sem citação corporativa. |
| 3. Corretude | ✅ | A conferência reproduz o codec do socket, sem recusa falsa nos casos de aceitação (IPv6, ponto final, rótulo de 63, `xn--` IDNA 2008, `localhost`, `127.0.0.1`) e sem efeito nos casos de host vazio. Não há `except` amplo novo. O risco de uma versão futura do codec mudar (OBS-R2-02 do tester, SEC-04 da r1) agora tem teste de premissa, e o R-12 fixa o 3.12. |
| 4. Testes | ✅ | Test-report PASS, com todos os CAs reexecutados. O tester validou os extras por mutação: a versão anterior à r2 dá 22 falhas, a variante com `.host` dá 2 falhas e a r2 passa inteira. A novidade é o "caminho real", que troca só `socket.create_connection`. É a fronteira de rede, então vale o "só fronteiras são mockadas" do §6. O `AI_NUMERICHOST` impede o DNS, e a asserção `socket_guard.hosts == [raw_host]` garante que a troca funcionou, sem conexão real. As variáveis de proxy são removidas. Nenhum teste roda pytest ou o simulador em subprocesso, e não há credencial literal. RV-01 (baixa): o teste do autor não diferencia `raw_host` de `.host`, mas o extra do tester sim. |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos (116 arquivos). O comentário de `simulate.py:423-427` explica a escolha do `raw_host`. O `httpx.URL(url)` é analisado duas vezes, um custo desprezível num caminho de CLI que roda uma vez, sem efeito na leitura. |
| 6. Segurança | N/A | Fica com o security-devops (portão `security`). Pendências que vêm da r1 e não bloqueiam: a consulta do SEC-02 na SPEC-015 (CA-14/CA-19) e o RV-03 da r1 (texto do CA-07, para o architect). |

## Verificação própria (read-only)

- `uv run ruff check .`: limpo. `uv run ruff format --check .`: 116 arquivos já formatados.
- `uv run pytest -q -p no:cacheprovider scripts/tests`: 465 passed, 4 skipped (sem banco).
- `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q -p no:cacheprovider`: **2815 passed**, 1 warning (o `StarletteDeprecationWarning` que já existia), em 5 min 44 s. É o mesmo número do test-report.
- Amostra do CA-12: 3 execuções de `uv run pytest -q api/tests/acceptance/test_spec_004.py -k real_server`, todas com `2 passed, 79 deselected` (de 2,95 s a 3,08 s).
- Depois das execuções, o Postgres de teste tem só `partqc_test`, `postgres`, `template0` e `template1`, e `git status` está limpo.
- Codec: `xn--1-zhc.com` dá `raw:ok` e `host:ERR`, enquanto `xn--nxasmq6b.com`, `[::1]`, `example.com.` e `localhost` dão `ok` nas duas formas. `exa..mple.com` dá `ERR` nas duas.
- Reprodução com o script real, em processo próprio (ver a seção SEC-01). Os arquivos de apoio ficaram no scratchpad da sessão.

## Pontos positivos

- A correção é mínima e faz exatamente o que o security-report especificou: uma linha, no lugar certo, com um comentário que explica o motivo.
- O tester percebeu que o exemplo do security-report (`xn--nxasmq6b.com`) não diferencia `raw_host` de `.host` e encontrou um caso que diferencia (`xn--1-zhc.com`), validado por mutação.
- O teste de "caminho real", com o `getaddrinfo` verdadeiro e sem DNS, fecha o ponto cego que causou o RV-02 da r1, já que o `MockTransport` não passa pelo socket. Ele faz isso sem rede e sem subprocesso.
- O tester fixou o código de saída dos extras da r1, que aceitavam `0 ou 2`. Essa tolerância era o que escondia o defeito.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC (meu único commit é o do r1-review-report, `cd94f41`, e o deste relatório).
