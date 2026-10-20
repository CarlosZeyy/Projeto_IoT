# SPEC-029 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-029](../../docs/specs/SPEC-029-manutencao-dashboard-simulador.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `6644810` (implementação em `73fcecf`, `94de48e` e `c21ebde`; SPEC no texto reaprovado após o SPEC_ISSUE-02); ajustes da §4.1 em `6207f4b` e testes novos no commit deste relatório |
| **Veredicto** | **PASS** |

Testei contra o texto atual da SPEC, com as correções do SPEC_ISSUE-01 (reaprovada pelo orquestrador, ADR-019) e do SPEC_ISSUE-02 (reaprovada pelo humano) no CA-04. Escrevi os testes a partir da SPEC antes de ler a implementação. CA-01 e CA-02 foram rodados **antes** dos ajustes da §4.1 e falharam como esperado (no CA-01, o marcador aparecia na saída do `test_extra_settings_from_environment`, `test_spec_013.py:1607`). Depois dos ajustes, passam.

## Cobertura dos critérios de aceite

Arquivos:

- `dashboard/tests/acceptance/test_spec_029.py`: 38 testes coletados (15 dos CAs, contando os parâmetros, e 23 exploratórios);
- `scripts/tests/acceptance/test_spec_029.py`: 2 testes (1 do CA-05 e 1 exploratório).

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `dashboard/tests/acceptance/test_spec_029.py::test_ca01_spec013_suite_passes_and_hides_key_with_local_secrets`. Cria `T/.streamlit/secrets.toml` em `tmp_path`, fora do repositório, com `API_BASE_URL = "http://localhost:8001"` e `READ_API_KEY = "<marcador>"`; o marcador é gerado com `secrets.token_hex`. Uma sonda em subprocesso confirma que o `st.secrets` real lê o marcador em `T`. Depois roda `python -m pytest -q -p no:cacheprovider <raiz>/dashboard/tests/acceptance/test_spec_013.py` com `cwd=T` e sem `CI`, `TEST_DATABASE_URL`, `PYTEST_ADDOPTS`, `PYTEST_PLUGINS` e `PYTEST_CURRENT_TEST`. Verifica o código 0, o resumo `N passed` e a ausência do marcador no stdout e no stderr. As asserções usam booleanos e a saída citada numa falha é redigida (`<marker>`), então o marcador não aparece nem quando o teste falha | ✅ |
| CA-02 | `test_ca02_retry_comment_updated_and_same_collection_as_main`. Lê o corpo de `test_extra_retry_while_still_down_is_bounded` com `ast.get_source_segment`: não contém `clearing the cache`, e a asserção `assert len(fake.requests) <= 2` continua lá. Depois roda `--collect-only -q` no arquivo: dá 118 testes, o número medido na `main` (`3ed113c`) e fixado em `SPEC013_COUNT_ON_MAIN`. Quando a ref `main` (ou `origin/main`) existe, também coleta a versão da `main` (`git show`) numa cópia em `tmp_path` e compara os node ids, que devem ser iguais. O CI faz checkout de um commit só, então lá vale a contagem fixada | ✅ |
| CA-03 | `test_ca03_badge_when_the_returned_chart_is_simulated`, com três cenários. (a) Barra lateral `Real` e mock devolvendo `source="simulated"` para o pedido `source=live`: exatamente 1 `st.warning` com `Contém dados simulados` e o caption `Origem da carta: simulado`. (b) Mock devolvendo `live`: nenhum aviso (e `Origem da carta: real`). (c) Barra lateral `Simulado` e mock devolvendo `simulated`: exatamente 1 aviso. Nos três, 0 requisições a `/api/v1/metrics/summary`. O mock só responde `SpcResponse` válidos | ✅ |
| CA-04 | `test_ca04_malformed_url_is_refused_with_one_constant_message`: os 7 valores levantam `InsecureApiUrlError`; a mensagem contém `API_BASE_URL`, não contém o valor nem `example.org` e é a mesma nos 7 (`len(set(...)) == 1`). `test_ca04_malformed_url_stops_the_overview[7 valores]`: Visão geral com o `get_client` real e `httpx.HTTPTransport.handle_request` interceptado; há `st.error` começando por `Configuração inválida: API_BASE_URL precisa usar https://`, 0 requisições e `at.exception` vazio. `test_ca04_valid_url_is_still_accepted[4 valores]`: `get_settings()` devolve as configurações, com `api_base_url` igual ao valor e a chave lida | ✅ |
| CA-05 | `scripts/tests/acceptance/test_spec_029.py::test_ca05_idna_case_in_the_author_test_is_collected_once_and_passes`. Roda `python -m pytest -p no:cacheprovider --collect-only -q scripts/tests/test_simulate.py -k "visible_ascii_api_url_still_sends and xn--1-zhc"` e confere 1 node id, `test_visible_ascii_api_url_still_sends[https://xn--1-zhc.com]`. Depois roda a mesma seleção: código 0, resumo `1 passed` sem `failed`/`error`/`skipped`. O subprocesso usa o mesmo ambiente sem as 5 variáveis, com `cwd` na raiz | ✅ |

## Testes de aceite de SPECs anteriores ajustados

Regra "Testes de aceite de SPECs anteriores" de `docs/architecture.md` §10, aplicada de forma explícita pela SPEC-029 §3.1 e §4.1. Os ajustes estão no commit próprio do tester `6207f4b` (`test: isolate st.secrets in SPEC-013 acceptance tests`, `Agent: tester`).

| Arquivo | Teste | Antes → depois | Requisito |
|---|---|---|---|
| `dashboard/tests/acceptance/test_spec_013.py` | fixture `_isolated` (autouse; vale para todos os testes do arquivo) | Antes: só apagava `CONFIG_VARS`, trocava `HOME` e limpava os caches. Depois: também faz `monkeypatch.setattr(st, "secrets", NoSecretsFile())`. A classe `NoSecretsFile` foi **copiada** do `test_spec_028.py:239`, com o mesmo `__contains__`/`__getitem__` levantando `FileNotFoundError("No secrets found")`, e definida logo antes da fixture. Copiei em vez de importar para um arquivo de teste não importar outro módulo de teste, o que é frágil com `--import-mode=importlib`. Nenhuma asserção mudou | SPEC-029 §4.1, item 1 (RV-01/SEC-28-01 da SPEC-028); CA-01 |
| idem | `test_extra_retry_while_still_down_is_bounded` (só o comentário) | `# The click rerun and the st.rerun() after clearing the cache: 2 attempts, then it stops.` → `# The click rerun and the st.rerun() of the button: 2 attempts, then it stops.` A asserção `assert len(fake.requests) <= 2` não mudou | SPEC-029 §4.1, item 2 (RV-03 da SPEC-028); CA-02 |

Nenhum `test_caNN_` da SPEC-013 mudou e nenhuma outra linha do arquivo mudou (`git diff` mostra só a classe nova, a linha do `setattr` e o comentário). O arquivo continua com 118 testes coletados, como na `main`.

## Suíte completa

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
5571 passed, 52 skipped, 1 warning in 352.31s (0:05:52)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
223 files already formatted
```

A suíte passou de 5531 testes (dev-report) para 5571, com os 40 testes novos. Os 52 skips são os de Docker (`PARTQC_DOCKER_TESTS`), que já existiam. A warning é a `StarletteDeprecationWarning` do `fastapi.testclient`, que também já existia.

### Suíte completa com um `.streamlit/secrets.toml` fictício na raiz

Pedido do orquestrador para a §4.1. O script de apoio fica fora do repositório, no scratchpad da sessão, e faz o seguinte:

1. recusa rodar se o arquivo já existir;
2. registra um `trap` que apaga o arquivo na saída;
3. gera o valor na hora (`r` + `secrets.token_hex(20)`) e grava `API_BASE_URL = "http://localhost:8001"` e `READ_API_KEY = "<valor>"` em `<raiz>/.streamlit/secrets.toml`;
4. roda a suíte completa (mesmo comando acima) com a saída redirecionada para um arquivo;
5. procura o valor nessa saída com `grep -F`.

O valor nunca foi impresso.

```text
git sees file as: !! .streamlit/secrets.toml      (ignorado pelo .gitignore)
pytest exit code: 0
value not found in output
5571 passed, 52 skipped, 1 warning in 349.90s (0:05:49)
```

Depois da execução, `.streamlit/` contém só o `config.toml` versionado, e `git status --ignored .streamlit` não lista o `secrets.toml`. O arquivo não entrou em nenhum commit.

## Bugs encontrados

Nenhum bug contra a SPEC.

## Testes exploratórios (além dos critérios)

Os automatizados estão em `test_spec_029.py`, com o prefixo `test_extra_`. Todos passam.

| Caso | Resultado |
|---|---|
| Barra lateral `Todos` (a carta fica `Real`) e mock devolvendo `simulated` | 1 selo e 0 requisições a `/metrics/summary` ✅ |
| Barra lateral `Simulado`, rádio da carta de volta a `Real` e mock devolvendo `simulated` | 1 selo (pela origem devolvida) ✅ |
| Requisições por renderização com o selo pela origem devolvida | exatamente 1 a `/metrics/spc` e nenhuma outra rota (§4.2, "nenhuma requisição nova") ✅ |
| Posição do selo pela origem devolvida | na árvore da página, o `warning` vem antes do `plotly_chart` (mesmo `badge_slot`) ✅ |
| Mais valores recusados: portas `:-1`, `:65536` e `:1e3`; `Cc` `\x00`, `\x1b` e `\x9f` (C1) no meio do host; `\t` no caminho; `http://127.0.0.1:abc` | `is_secure_api_url` → `False`. Via `get_settings()`: `InsecureApiUrlError` sem o valor (o `\x00` não pode ir para uma variável de ambiente e só foi testado na função) ✅ |
| Portas `:+80`, `: 80` e `:٣٣` (dígitos árabes) | recusadas com a mensagem de configuração e 0 requisições ✅ (exploração manual) |
| Valores aceitos nas bordas: portas `:0` e `:65535`, `:443/`, caminho com query, `http://localhost` sem porta, host IDN `bücher.example` | `True` ✅ |
| `Cc` só na ponta (`\n`, `\t`, `\r\n`, ` \x85`) | aparado por `_read()`; `api_base_url == "https://api.example.org"` (§4.3, parágrafo novo) ✅ |
| URL malformada vinda do `st.secrets`, e não do ambiente (`:99999`) | mesma recusa, `st.error` de configuração, 0 requisições e sem exceção ✅ |
| Premissa do CA-05 (`scripts/tests/acceptance/test_spec_029.py::test_extra_idna_case_tells_raw_host_from_host`) | o codec `idna` aceita o `raw_host` de `https://xn--1-zhc.com` e recusa o `.host` (`UnicodeError`) ✅ |
| `https://[::1]:abc` e `https://[::1` | recusados com a mensagem de configuração e 0 requisições ✅ (exploração manual) |
| `https://api.example.org:` (porta vazia), `https://a..b.com`, URL com userinfo (`<usuário>:<senha>@`), `#frag`, label com 64 caracteres | aceitos pela checagem; a página mostra `Erro da API` dentro do `api_guard`, sem exceção (exploração manual; fora do escopo da SPEC) |

### Observação O-01 (baixa; fora do escopo da SPEC-029, para o security-devops/architect)

Três valores de `API_BASE_URL` sem caractere `Cc` passam por `is_secure_api_url` e ainda derrubam a Visão geral com exceção não tratada (`at.exception` não vazio, mensagem redigida pelo `showErrorDetails = "none"`). Os três:

- `https://api.exa​mple.org`: U+200B, categoria `Cf`;
- `https://api.example.org x`: U+2028, categoria `Zl`;
- `https://xn--zz.com`: punycode inválido.

Nos dois primeiros, o `httpx.Client(base_url=…)` levanta `httpx.InvalidURL: Invalid IDNA hostname: …`. A mensagem cita o host, não a chave. Esse é o mesmo tipo de falha do SEC-28-02 (URL malformada que passa pela checagem e quebra no `httpx`, fora do `api_guard`). Mesmo assim, não é bug contra a SPEC-029: a decisão (b) do Histórico limita a checagem à categoria `Cc`, e a §4.3 diz que "o resto não muda". Nenhuma requisição sai, e nenhuma chave aparece. Passos: `API_BASE_URL` com um desses valores e `READ_API_KEY` definida; renderizar `dashboard/views/visao_geral.py` com o `AppTest`. Esperado (se o escopo fosse ampliado): a mensagem de configuração. Obtido: exceção. Sugestão: uma manutenção futura pode validar a URL com o próprio `httpx.URL(...)`/`raw_host` dentro do `try`, como o `scripts/simulate.py` já faz.

## SPEC_ISSUE (se houver)

Nenhum. Os SPEC_ISSUE-01 e -02 da r1 foram abertos pelo developer e já estavam resolvidos e reaprovados antes deste teste.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório. Em `dashboard/tests/acceptance/test_spec_013.py`, só os dois ajustes da §4.1 listados acima.
- [x] Nenhum valor que pareça segredo ficou como literal nos testes ou neste relatório: chaves e marcadores são gerados em tempo de execução.
- [x] O `.streamlit/secrets.toml` fictício existiu só durante a execução e foi apagado.
