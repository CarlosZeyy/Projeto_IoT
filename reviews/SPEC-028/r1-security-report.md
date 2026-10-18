# SPEC-028 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-028](../../docs/specs/SPEC-028-manutencao-dashboard.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `main...00df387` (o código de produção é o de `2ad0de7`; os commits seguintes só mexem em testes de aceite, relatórios e status) |
| **Veredicto** | **PASS** |

Não há achado bloqueante nem alto. Há **1 achado médio** (SEC-28-01: seguir o novo README e rodar a suíte local imprime a `READ_API_KEY` em claro na saída do pytest), que tem a mesma causa do RV-01 do review, e **3 informativos**. Nenhum deles exige uma r2: o médio só acontece na máquina da dupla, não no CI nem em produção, e a correção fica fora da §3.1 desta SPEC (o `_isolated` de `test_spec_013.py`).

Pontos centrais confirmados:

- **SEC-13-01 fechado.** `is_secure_api_url` usa `urlsplit` e aceita só `https` com host ou `http` com `hostname` exatamente `localhost`/`127.0.0.1`. A checagem roda em `get_settings()`, antes de `api.get_client()` criar o `httpx.Client`. Por isso, com uma URL recusada, nenhum cliente é criado e nenhuma requisição sai (o CA-01 confere isso interceptando o `HTTPTransport` real). A mensagem da exceção e a da tela são constantes e não citam o valor. Testei 28 URLs montadas para enganar o parser (userinfo, `\`, `;`, `#`, `?`, `%40`, IPv4 em hexa, `[::ffff:127.0.0.1]`, `localhost.`, `127.0.0.1.nip.io`, espaço inicial e esquema em maiúsculas) e comparei o veredicto da função com o destino que o `httpx` monta para a mesma URL. **Nenhuma URL aceita com `http://` leva o `httpx` a outro host que não `localhost`/`127.0.0.1`.** Os dois parsers concordam até em `http://evil.com\@localhost` e `http://evil.com;@localhost` (os dois vão para `localhost`). O `httpx` não segue redirecionamentos (`follow_redirects=False` é o padrão e o código não muda isso), então um `https://` não pode virar `http://` por um 3xx.
- **SEC-13-02 e SEC-13-05 fechados.** O botão "Tentar novamente" chama só `st.rerun()`. Um visitante deixa de poder esvaziar o cache de todas as sessões e forçar uma rajada de agregações na API. `max_entries=256` limita cada uma das 6 funções de `data.py`. Os argumentos cacheados continuam sendo só `Filters`, enums e inteiros, nunca a chave.
- **SEC-13-03 e SEC-13-08 fechados.** `display_path` mostra o caminho relativo quando o arquivo resolvido fica dentro de `REPO_ROOT`. `report_image` recusa o que não casa `MODEL_VERSION_PATTERN` (`fullmatch`) ou é feito só de pontos, e recusa também o que, depois do `resolve()`, sai de `ml/reports` (link simbólico de diretório ou de arquivo). O `name` é sempre uma constante de `CONFUSION_IMAGES`.
- **SEC-13-04 fechado.** README e `.env.example` deixam de recomendar `--env-file .env`. Com isso, `DATABASE_URL` e `DEVICE_API_KEY` não entram mais no processo do dashboard. `.streamlit/secrets.toml` já estava no `.gitignore` (linha 18): `git check-ignore -v` confirma que ele é ignorado e que `.streamlit/config.toml` não é.
- **R-06 na página da carta.** O selo segue a origem pedida, e a legenda segue `spc.source`. A API copia o `source` da query para a resposta (`api/src/qc_api/services/spc.py:173`), então os dois coincidem hoje (ver SEC-28-03, que repete o RV-02).

## Superfície analisada

- **Configuração** `dashboard/src/qc_dashboard/config.py`: `is_secure_api_url`, `InsecureApiUrlError`, `get_settings()`.
- **Erros e selo** `dashboard/src/qc_dashboard/filters.py`: `_retry`, `show_api_error`/`render_api_error`, `show_config_error`, `render_badge_or_error` (página sem `st.stop()`), `render_chart_badge`, `spc_origin_caption`.
- **Cache** `dashboard/src/qc_dashboard/data.py`: `max_entries`.
- **Arquivos locais** `dashboard/src/qc_dashboard/model_info.py`: `display_path`, `report_image`, regra de exibição (`LOWER_IS_BETTER`, ROUND_FLOOR/ROUND_CEILING em `formatting.fmt_quantized`).
- **Páginas** `dashboard/views/controle_estatistico.py`, `sobre_o_modelo.py`, `visao_geral.py` (`config={"displayModeBar": False}`, sem efeito de segurança).
- **Documentação de segredos:** `.env.example` (bloco do dashboard) e `dashboard/README.md` (exemplo de `.streamlit/secrets.toml` com `READ_API_KEY = ""`).
- **Fora do diff:** rotas da API, SQL, RLS, CORS, contrato, `uv.lock`, `pyproject.toml`, `.github/` e `infra/` (confirmado com `git diff main...HEAD --stat`). Não há dependência nova nem configuração de deploy.

## Achados

| ID | Severidade | Categoria (auth, input, secrets, deps, deploy, privacy) | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-28-01 | média | secrets | `dashboard/README.md:34-49` e `:81` com `dashboard/tests/acceptance/test_spec_013.py:332-341` (`_isolated`) e `test_extra_settings_from_environment` | O README agora manda pôr `API_BASE_URL` e `READ_API_KEY` em `.streamlit/secrets.toml` na raiz do repositório. Essa é a mesma pasta de onde o próprio README (linha 81) manda rodar `uv run pytest dashboard/tests -q`, e o `_isolated` da SPEC-013 não isola o `st.secrets`. **Reproduzi** fora do repositório, com um `.streamlit/secrets.toml` de teste no diretório de trabalho (`API_BASE_URL = "http://localhost:8001"`, o exemplo do próprio README, e `READ_API_KEY = "CANARYKEY0123456789"`), rodando `pytest dashboard/tests`. Resultado: `test_extra_settings_from_environment` falha e a saída do pytest traz o valor da chave **4 vezes**, inclusive na linha do `short test summary` (`AssertionError: assert 'CANARYKEY0123456789' == 'k-…'`). Com outra `API_BASE_URL`, a primeira asserção (a da URL) falha antes e só a URL aparece. O risco é a chave real de leitura passar do terminal para um relatório em `reviews/` (os agentes colam saída de teste nos relatórios) e daí para o Git (R-03). O CI não é afetado, porque lá não existe o arquivo. Os testes do autor e os da SPEC-028 já isolam o `st.secrets`. | **Não bloqueia esta SPEC.** A correção fica fora da §3.1 e vai na mesma pendência do RV-01: uma SPEC futura do dashboard, ou um ajuste do architect, autoriza trocar o `st.secrets` no `_isolated` de `test_spec_013.py` (como o `NoSecretsFile` do `test_spec_028.py`). Isso deve entrar **antes do primeiro uso de um `.streamlit/secrets.toml` com chave real**. Até lá, o orquestrador registra a regra operacional: não rodar a suíte com `.streamlit/secrets.toml` na raiz (renomeie o arquivo ou tire-o da pasta) e nunca colar em relatório uma saída de pytest com falha de `test_extra_settings_from_environment` sem conferir o texto. |
| SEC-28-02 | info | input | `dashboard/src/qc_dashboard/config.py:86-99` | `is_secure_api_url` não lê `parts.port`, e o `urlsplit` tira `\t`/`\n` antes de analisar a URL. Por isso, uma URL malformada com `https://` ou com host local passa pela checagem (`https://host:abc`, `http://local\thost:8001`), e o `httpx.Client` levanta `httpx.InvalidURL` dentro de `api.get_client()`. Esse erro não está em `API_ERRORS` nem é tratado pelo `api_guard`, então a página mostra a exceção do Streamlit, com um trecho da URL (por exemplo, `Invalid port: 'abc'`), mas nunca a chave. O comportamento já existia antes desta SPEC e depende de um erro de configuração do operador. Nenhuma URL nesse caso manda a chave em claro. | Nenhuma nesta SPEC. Opcional, numa manutenção futura: ler `parts.port` dentro do `try` de `is_secure_api_url` (o `ValueError` já vira recusa) e recusar caracteres de controle. O `showErrorDetails` da SPEC-015 §4.4 cobre o traceback em produção. |
| SEC-28-03 | info | input (R-06) | `dashboard/views/controle_estatistico.py:119-128` | Mesmo ponto do RV-02 do review: o selo é decidido pela origem pedida (`source`), e a legenda final usa `spc.source`. Hoje a API copia o `source` da query (`api/src/qc_api/services/spc.py:173`), e a resposta é validada pelo `SpcResponse` do contrato, então os dois coincidem. | Nenhuma nesta SPEC. Defesa em profundidade numa próxima manutenção: mostrar o selo também quando `spc.source is Source.SIMULATED`. |
| SEC-28-04 | info | privacy | `dashboard/src/qc_dashboard/model_info.py:256-264` | Com um `MODEL_METRICS_PATH` relativo que sai do repositório (`../fora/metrics.json`), `display_path` mostra o caminho absoluto **não resolvido**, que inclui `REPO_ROOT` (`/…/Projeto_IoT_AI_Agent/../fora/metrics.json`). Isso segue a letra da §4.4 ("o caminho absoluto só quando fica fora"), e o valor vem da configuração do operador, não de quem acessa a página. Num deploy padrão (sem `MODEL_METRICS_PATH` ou com ele relativo e dentro do repositório), a mensagem só mostra o caminho relativo. | Nenhuma. |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | N/A: o diff não toca a API. No dashboard, a `READ_API_KEY` continua só no header `X-API-Key` do `httpx.Client` (`st.cache_resource`) e agora só sai com `https://` ou para o host local (SEC-13-01 fechado). |
| Entradas validadas (tamanho, tipo real de imagem, regex de IDs, `extra="forbid"`) | OK. `API_BASE_URL` validada pelo esquema e pelo host; `model_version` por `fullmatch` + recusa de nomes só com pontos + confinamento por `resolve().is_relative_to`; a resposta da carta continua validada pelo `SpcResponse`. Nenhuma entrada nova vem do usuário da página. |
| SQL sempre parametrizado | N/A: o diff não tem SQL. |
| RLS ligado; `DATABASE_URL`/`service_role` só na API | OK. O README e o `.env.example` deixam de carregar o `.env` único no dashboard. Assim, `DATABASE_URL` e `DEVICE_API_KEY` saem do processo do dashboard (SEC-13-04 fechado). |
| CORS fechado ou mínimo | N/A: o diff não toca a API. |
| Logs sem segredos e sem payloads de imagem | OK. Nenhum log novo. As mensagens novas (`INSECURE_API_URL_MESSAGE` e a da exceção) são constantes e não citam valores. Busca por padrões de chave no diff: nada. As chaves dos testes são geradas com `secrets.token_hex`. Ver SEC-28-01 para a saída do pytest local. |
| Dependências novas mantidas, licença compatível, sem CVE crítica | N/A: nenhuma dependência nova; `uv.lock` e `pyproject.toml` fora do diff. |
| Deploy: variáveis no provedor, health check, plano free sem cartão | N/A: nenhum arquivo de deploy foi tocado. O `https://` nos Secrets do Streamlit CC é da SPEC-015. |
| R-02/R-14 (imagens) | OK. Nenhuma imagem de inspeção é tocada. `report_image` só lê as matrizes de confusão de `ml/reports/`, agora confinadas ao diretório. |
| R-07 (papéis) | OK. Os trailers `Agent:` batem com os arquivos de cada commit: `developer` em `dashboard/src`, `dashboard/views`, `dashboard/tests/` (fora de `acceptance/`), README, `.env.example` e dev-report; `tester` só em `dashboard/tests/acceptance/` e no test-report; `reviewer` só no review-report; `orchestrator` só em status (`docs/plan.md` e cabeçalho das SPECs). Todos os commits são de `CarlosZeyy` (R-13). O diff não cita nenhuma empresa. |
| Suíte e lint | `CI=true TEST_DATABASE_URL=… uv run pytest -q`: **3855 passed**. `ruff check .`: limpo. `ruff format --check .`: 149 arquivos formatados. |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma. |

## Comandos executados (read-only)

```bash
git diff main...HEAD --stat; git diff main...HEAD -- dashboard/src dashboard/views dashboard/README.md .env.example
git check-ignore -v .streamlit/secrets.toml .streamlit/config.toml
# 28 URLs: is_secure_api_url(u) contra httpx.Client(base_url=u).build_request("GET", "/api/v1/health").url
# ApiClient com URLs malformadas aceitas pela checagem (SEC-28-02)
# display_path("../fora/metrics.json") (SEC-28-04)
# pytest dashboard/tests a partir de um diretório temporário fora do repositório, com um
# .streamlit/secrets.toml de teste (chave canário), e grep da chave na saída (SEC-28-01);
# o diretório foi apagado depois
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

## Declaração

- [x] Não editei código; não sou autor desta SPEC.
