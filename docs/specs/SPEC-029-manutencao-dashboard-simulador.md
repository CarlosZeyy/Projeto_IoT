# SPEC-029: Manutenção do dashboard e do simulador (isolamento do `st.secrets` nos testes, selo pela origem devolvida, URL com porta e controles, caso IDNA do simulador)

| Campo | Valor |
|---|---|
| Status | Blocked |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-028 (e SPEC-013, SPEC-027) |
| Semana alvo | S2–S3 (**antes** do primeiro `.streamlit/secrets.toml` com a `READ_API_KEY` real na raiz do repositório, ou seja, antes dos CAs manuais da SPEC-015 rodados a partir do notebook) |
| Requisitos cobertos | RF-10, RF-13, RF-14, RNF-06; R-03, R-06 |
| ADRs relevantes | ADR-007, ADR-012 |

> **Reaprovada pelo orquestrador sob o ADR-019 em 2026-10-20 02:50 UTC**: correção do SPEC_ISSUE-01 de `reviews/SPEC-029/r1-dev-report.md` (um caso do CA-04 e uma frase de esclarecimento na §4.3). Classificação ADR-019: elegível. Ver o Histórico.

## 1. Contexto

Fecha as pendências não bloqueantes dos portões da SPEC-028 (dashboard) e da SPEC-027 (simulador), registradas em `docs/plan.md` §3 como "Próxima SPEC do dashboard" e "Próxima manutenção do simulador". Não muda o contrato, a API nem `docs/architecture.md` (o dashboard continua lendo tudo pela `qc-api`, §1 e §2; a regra de `https://` do `API_BASE_URL` continua a da §9).

| Pendência | Origem | Severidade | O que entra aqui |
|---|---|---|---|
| RV-01 = SEC-28-01 | `reviews/SPEC-028/r1-review-report.md` e `r1-security-report.md` | média | O `_isolated` de `dashboard/tests/acceptance/test_spec_013.py` passa a isolar o `st.secrets` (§4.1). Com um `.streamlit/secrets.toml` na raiz, `test_extra_settings_from_environment` falhava e imprimia a `READ_API_KEY` na saída do pytest |
| RV-03 | `reviews/SPEC-028/r1-review-report.md` | baixa | Comentário desatualizado em `test_spec_013.py:1306` (§4.1) |
| RV-02 = SEC-28-03 | mesmos relatórios | baixa / info | Selo "Contém dados simulados" também quando a carta **devolvida** é simulada (§4.2, R-06) |
| SEC-28-02 | `reviews/SPEC-028/r1-security-report.md` | info | `is_secure_api_url` recusa porta inválida e caracteres de controle (§4.3) |
| RV-01 | `reviews/SPEC-027/r2-review-report.md` | baixa | Caso `https://xn--1-zhc.com` nos testes do autor do simulador (§4.4) |

**Por que o prazo.** A SPEC-028 §4.6 manda a dupla pôr `API_BASE_URL` e `READ_API_KEY` em `.streamlit/secrets.toml` na raiz, a mesma pasta de onde se roda o `uv run pytest`. Enquanto o `_isolated` da SPEC-013 não isolar o `st.secrets`, rodar a suíte com a chave real no arquivo imprime a chave (4 vezes, reproduzido pelo security-devops), e os agentes colam saídas de teste em `reviews/` (R-03). Até esta SPEC estar `Done`, vale a regra operacional do `docs/plan.md` §3: tirar o arquivo da raiz antes de rodar a suíte.

## 2. Objetivo

A suíte do dashboard passa e não imprime a chave mesmo com um `.streamlit/secrets.toml` na raiz; a página da carta mostra o selo sempre que a carta exibida é simulada; `API_BASE_URL` com porta inválida ou caractere de controle é recusada com a mensagem de configuração; e o teste do autor do simulador protege o uso do `raw_host`.

## 3. Escopo

### 3.1 Dentro

- `dashboard/src/qc_dashboard/config.py`: só `is_secure_api_url` (§4.3).
- `dashboard/views/controle_estatistico.py`: selo também pela origem devolvida (§4.2).
- `dashboard/src/qc_dashboard/filters.py`, se o selo precisar de uma função nova ou de um parâmetro (§4.2).
- Testes do autor em `dashboard/tests/` (fora de `acceptance/`).
- `scripts/tests/test_simulate.py` (teste do autor do simulador): §4.4.
- **Tester desta SPEC:**
  - `dashboard/tests/acceptance/test_spec_029.py` (testes novos);
  - `scripts/tests/acceptance/test_spec_029.py`, se preferir separar o CA do simulador;
  - os ajustes de manutenção da §4.1, e nada além deles, em `dashboard/tests/acceptance/test_spec_013.py`. É aplicação explícita da regra "Testes de aceite de SPECs anteriores" de `docs/architecture.md` §10.

### 3.2 Fora

- A mensagem "API acordando (free tier)": continua como está (SPEC-028 §3.2 e SPEC-015 §3.2).
- `display_path` com caminho absoluto fora do repositório (SEC-28-04): sem ação, como o relatório decidiu.
- Qualquer mudança na API, no contrato, no `docs/architecture.md` ou no simulador além do teste do autor (§4.4).
- Validação de URL do simulador (`scripts/simulate.py`): não muda. O caso novo só testa o comportamento entregue pela SPEC-027.
- Deploy e `.streamlit/config.toml`: SPEC-015 e SPEC-032.

## 4. Requisitos detalhados

### 4.1 Isolamento do `st.secrets` nos testes da SPEC-013 (RV-01/SEC-28-01, RV-03; tester)

O tester desta SPEC faz só estas edições em `dashboard/tests/acceptance/test_spec_013.py`:

1. **`_isolated`** (fixture da linha 332 hoje): passa a substituir `streamlit.secrets` por um objeto que se comporta como o `st.secrets` sem nenhum `secrets.toml` (o mesmo padrão do `NoSecretsFile` de `dashboard/tests/acceptance/test_spec_028.py:239`), com `monkeypatch.setattr`, além do que já faz. Pode importar o `NoSecretsFile` do `test_spec_028.py` ou copiar a classe; a escolha vai no test-report.
2. **Comentário** de `test_extra_retry_while_still_down_is_bounded` (linha 1306 hoje): deixa de citar "after clearing the cache", porque desde a SPEC-028 §4.2 o botão só chama `st.rerun()`. A asserção (`<= 2` tentativas) não muda.

Nenhuma asserção, nenhum `test_caNN_` e nenhum outro teste do arquivo muda. As duas edições vão na tabela de ajustes do test-report, com o requisito desta seção.

O `dashboard/README.md` não muda: a regra provisória (tirar o `.streamlit/secrets.toml` da raiz antes de rodar a suíte) está só no `docs/plan.md` §3 (conferido pelo architect em 2026-10-19), e o orquestrador a encerra no fechamento desta SPEC.

### 4.2 Selo da carta também pela origem devolvida (RV-02/SEC-28-03, R-06)

Hoje o selo "Contém dados simulados" da página de controle estatístico é decidido pela origem **pedida** (`source`, antes da leitura), e a legenda final usa a origem **devolvida** (`spc.source`). A API ecoa o `source` da query, então os dois coincidem. A mudança é defesa em profundidade:

- Depois da leitura, se `spc.source is Source.SIMULATED` e o selo ainda não foi mostrado (origem pedida `Real`), o selo é mostrado no mesmo `badge_slot`, com o mesmo texto e o mesmo componente (`st.warning`) de hoje.
- Com a carta pedida e devolvida reais, nada muda (sem selo). Com a carta pedida simulada, o selo continua aparecendo antes da leitura, uma vez só (sem duplicar).
- Nenhuma requisição nova: a decisão usa só a resposta do SPC já lida (a SPEC-028 §4.3 proíbe a checagem do selo pela API).

### 4.3 `is_secure_api_url`: porta e caracteres de controle (SEC-28-02)

`is_secure_api_url(url: str) -> bool` passa a devolver `False` também quando:

1. algum caractere de `url` tem `unicodedata.category` igual a `Cc` (C0, DEL e C1, inclusive `\t`, `\n`, `\r` e U+0085). A checagem vem **antes** do `urlsplit`, que remove `\t`/`\n`/`\r` antes de analisar;
2. ler `parts.port` levanta `ValueError` (porta não numérica ou fora de 0–65535). A leitura fica dentro do mesmo `try` do `urlsplit`.

O resto não muda: `https` com host, ou `http` com host `localhost`/`127.0.0.1`. A mensagem da exceção e a da tela continuam constantes (SPEC-028 §4.1), sem o valor. Como hoje, a checagem roda em `get_settings()`, antes de qualquer `httpx.Client`.

A checagem vale para o valor que chega a `is_secure_api_url`. `get_settings()` continua lendo `API_BASE_URL` por `_read()`, que apara as pontas com `str.strip()` (SPEC-013 §4.1), e isso não muda. Um `Cc` que o `str.strip()` trata como espaço (`\t`, `\n`, `\x0b`, `\x0c`, `\r`, `\x1c`–`\x1f`, U+0085), quando está só na ponta do valor, é aparado antes da checagem, e a URL aparada é a que o cliente usa. Por isso, o CA-04 testa os controles no meio do valor ou, no caso de `\x7f` (que o `strip()` não remove), no fim.

### 4.4 Simulador: caso IDNA no teste do autor (RV-01 da SPEC-027 r2)

Em `scripts/tests/test_simulate.py`, a parametrização de `test_visible_ascii_api_url_still_sends` (linhas 1131–1152 hoje) ganha o caso `"https://xn--1-zhc.com"`. Esse domínio é aceito pelo codec `idna` a partir do `raw_host` e recusado a partir do `.host` (regra bidi do IDNA 2003), então o teste do autor passa a falhar se `scripts/simulate.py` voltar a usar `.host` (o motivo do comentário de `simulate.py:426-427`). O `scripts/simulate.py` não muda.

## 5. Critérios de aceite

Contexto comum: como na SPEC-028 §5 (`api.get_client` substituído por um `ApiClient` com `httpx.MockTransport` que registra as requisições; `st.cache_data` limpo antes de cada teste; chaves e marcadores gerados no teste com `secrets`, nunca literais).

- **CA-01 (security, R-03, RV-01/SEC-28-01)** — *Dado* um diretório temporário `T` fora do repositório com `T/.streamlit/secrets.toml` contendo `API_BASE_URL = "http://localhost:8001"` e `READ_API_KEY = "<marcador>"` (marcador gerado no teste), *quando* se roda, com `cwd=T` e o ambiente sem `CI`, `TEST_DATABASE_URL`, `PYTEST_ADDOPTS`, `PYTEST_PLUGINS` e `PYTEST_CURRENT_TEST`, `python -m pytest -q -p no:cacheprovider <raiz>/dashboard/tests/acceptance/test_spec_013.py` (caminho de arquivo explícito, `docs/architecture.md` §10), *então* o código de saída é 0 e o marcador não aparece no stdout nem no stderr.
- **CA-02 (RV-03)** — *Dado* `dashboard/tests/acceptance/test_spec_013.py`, *quando* se lê o corpo de `test_extra_retry_while_still_down_is_bounded` (via `ast`/`inspect.getsource`), *então* ele não contém `clearing the cache`; e `uv run pytest --collect-only -q dashboard/tests/acceptance/test_spec_013.py` coleta o mesmo número de testes da `main`.
- **CA-03 (security, R-06, RV-02/SEC-28-03)** — *Dado* a página de controle estatístico com a barra lateral em `Real` e o mock respondendo ao SPC (pedido com `source=live`) um `SpcResponse` válido com `source="simulated"`, *quando* a página é renderizada, *então* há exatamente 1 `st.warning` com `Contém dados simulados` e o `st.caption` `Origem da carta: simulado`. *Dado* o mock respondendo `source="live"`, *então* não há esse aviso. *Dado* a barra lateral em `Simulado` e o mock respondendo `source="simulated"`, *então* há exatamente 1 aviso (sem duplicar). Nos três casos, o transporte registra 0 requisições a `/api/v1/metrics/summary`.
- **CA-04 (security, SEC-28-02)** — *Dado* `READ_API_KEY` definida e `API_BASE_URL` igual a `https://api.example.org:abc`, `https://api.example.org:99999`, `http://localhost:abc`, `http://local\thost:8001`, `https://api.exa\nmple.org`, `https://api.example.org\x7f` ou `https://api.exa\x85mple.org`, *quando* `config.get_settings()` é chamado, *então* levanta `InsecureApiUrlError`, e a mensagem não contém `example.org` nem `localhost`; e, *quando* a Visão geral é renderizada com o mesmo valor, *então* há o `st.error` `Configuração inválida: API_BASE_URL precisa usar https://`, o transporte registra 0 requisições e `at.exception` está vazio. *Dado* `https://api.example.org:8443`, `https://api.example.org`, `http://localhost:8001` ou `http://127.0.0.1`, *então* `get_settings()` devolve as configurações sem erro.
- **CA-05 (RV-01 da SPEC-027)** — *Dado* `scripts/tests/test_simulate.py`, *quando* se roda `uv run pytest -q scripts/tests/test_simulate.py -k "visible_ascii_api_url_still_sends and xn--1-zhc"`, *então* exatamente 1 teste é coletado e passa.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | `is_secure_api_url` (tabela de casos da §4.3); selo pela origem devolvida; caso `xn--1-zhc.com` | `dashboard/tests/`, `scripts/tests/test_simulate.py` |
| Aceite (tester) | Um por CA; mais as edições da §4.1 em `test_spec_013.py` | `dashboard/tests/acceptance/test_spec_029.py` (e, se o tester preferir, `scripts/tests/acceptance/test_spec_029.py` para o CA-05) |

- O CA-01 roda o pytest em subprocesso só com um caminho de arquivo explícito, sem banco e sem incluir outro teste que rode pytest em subprocesso (`docs/architecture.md` §10). O ambiente do subprocesso tira as variáveis listadas no CA (lição do RV-08 de `reviews/SPEC-025/r3-review-report.md`).
- Mock só de fronteiras: o transporte HTTP da API (`httpx.MockTransport`). O `st.secrets` do CA-01 é o real, lido do `T/.streamlit/secrets.toml`.
- Nenhum teste usa a rede nem uma chave real.

## 7. Riscos e notas para o implementador

- O `urlsplit` do Python remove `\t`, `\n` e `\r` da URL antes de analisar (comportamento documentado do `urllib.parse` desde a correção do bpo-43882). Por isso a checagem de `Cc` vem antes dele.
- `parts.port` só levanta `ValueError` quando é lido. Hoje a função não o lê, e a URL inválida só falhava no `httpx.Client`, com `httpx.InvalidURL` fora do `api_guard` (SEC-28-02).
- O selo da §4.2 não depende da origem pedida pela barra lateral: a carta tem a sua própria origem (SPEC-028 §4.3). Não volte a consultar `summary(source=simulated)` para decidir o selo da carta.
- Os testes de aceite da SPEC-028 que conferem o selo (CA-04) não devem mudar: neles, a API falsa devolve a mesma origem pedida. Se algum falhar, é bug da implementação, não ajuste (`docs/architecture.md` §10).

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `docs/plan.md` §3: a regra operacional "tirar o `.streamlit/secrets.toml` da raiz antes de rodar a suíte" marcada como encerrada (orquestrador)
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-19 | SPEC criada (`Draft`). Decisões do architect: (a) o selo da §4.2 usa a resposta já lida, sem requisição nova; (b) a checagem de controles usa a categoria `Cc` inteira (C0, DEL e C1), e não só `\t`/`\n`; (c) o isolamento do `st.secrets` é feito pelo tester, no `_isolated` da SPEC-013, pela regra de `docs/architecture.md` §10. | RV-01, RV-02 e RV-03 de `reviews/SPEC-028/r1-review-report.md`; SEC-28-01, SEC-28-02 e SEC-28-03 de `reviews/SPEC-028/r1-security-report.md`; RV-01 de `reviews/SPEC-027/r2-review-report.md` | Orquestrador, a pedido do humano |
| 2026-10-19 | Aprovada pelo humano (`Draft` → `Ready`), com as respostas recomendadas às perguntas do architect (comentário do PR #36). | Aprovação humana | Humano (Carlos) |
| 2026-10-19 | **Correção do SPEC_ISSUE-01 (r1): um caso do CA-04 e uma frase na §4.3.** **CA-04, texto antigo:** "… `https://api.example.org\x7f` ou `https://api.example.org/\x85`, *quando* …". **Texto novo:** "… `https://api.example.org\x7f` ou `https://api.exa\x85mple.org`, *quando* …". O resto do CA-04 não muda: 7 valores recusados, os mesmos 4 aceitos, as mesmas asserções. **§4.3:** ganhou um parágrafo que esclarece que a checagem vale para o valor que chega a `is_secure_api_url`, depois do `str.strip()` de `_read()` (SPEC-013 §4.1, que não muda); um `Cc` que o `strip()` trata como espaço, só na ponta, é aparado antes. Os itens 1 e 2 da §4.3 e a §3.1 não mudam. **Evidência:** reprodução do developer em `reviews/SPEC-029/r1-dev-report.md` (`'https://api.example.org/\x85'.strip()` dá `'https://api.example.org/'`, e `'\x85'.isspace()` é `True`); `dashboard/src/qc_dashboard/config.py:68` (`str(value).strip()`) e `:118` (o valor aparado é o usado pelo cliente), conferidos pelo architect. **Escolha entre as duas saídas do relatório:** a opção 2 (trocar o caso). A opção 1 (checar `Cc` antes do `strip()`) mudaria o comportamento de `get_settings()`/`_read()` entregue pela SPEC-013 e recusaria valores hoje aceitos (um `\n` final copiado para o `secrets.toml`), o que é escopo novo (X-5) e pediria decidir a regra para a `READ_API_KEY`. **Intenção preservada:** o achado de origem (SEC-28-02) é a URL malformada que passa pela checagem e quebra no `httpx.Client`; um controle só na ponta é aparado e não chega ao cliente, então não produz esse erro. O caso novo continua cobrindo um C1 (U+0085), que o `urlsplit` não remove nem recusa: sem a checagem de `Cc` da §4.3, `is_secure_api_url` devolveria `True` para ele, e com ela devolve `False`. Classificação ADR-019: elegível (E-1: SPEC_ISSUE-01 de `reviews/SPEC-029/r1-dev-report.md`; E-2: só este arquivo e a linha da SPEC-029 em `docs/plan.md`; E-3: aprovada e `Blocked` por este SPEC_ISSUE; E-4: tipo 2 no CA-04, forma de verificação ajustada com a intenção preservada, e tipo 1 na §4.3, texto que esclarece sem mudar o comportamento pedido; E-5: só os trechos do SPEC_ISSUE-01; nenhuma exclusão: X-5 não, porque a §3.1, a assinatura e o comportamento não mudam; X-6 não, porque nenhum caso de erro sai (o C1 continua testado, e o número de casos recusados é o mesmo) e nenhum limite de segurança muda; X-7 não, porque o CA-04 verifica o SEC-28-02, e não uma regra inegociável; X-9 não, porque é a primeira correção deste CA e deste trecho). SPEC marcada como "Aguardando reaprovação (ADR-019)"; o status continua `Blocked` (r1) até a reaprovação. | SPEC_ISSUE-01 de `reviews/SPEC-029/r1-dev-report.md` | Orquestrador |
| 2026-10-20 | Correção do SPEC_ISSUE-01 (caso do CA-04 com U+0085 movido para o meio do host; frase de esclarecimento na §4.3) aprovada pelo orquestrador sob o ADR-019 (commit do architect `cd99179`). Conferidos E-1 a E-5 e nenhuma exclusão; verificado que `is_secure_api_url('https://api.exa\x85mple.org')` devolve `True` hoje, então o caso novo continua exigindo a checagem de `Cc`. `Blocked` → `In Dev`, retomada na r1. | SPEC_ISSUE-01 de `reviews/SPEC-029/r1-dev-report.md` | Orquestrador (ADR-019) |
