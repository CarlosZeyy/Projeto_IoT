# SPEC-013 — r2 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-013](../../docs/specs/SPEC-013-dashboard.md) |
| Rodada | r2 |
| Revisor de segurança | security-devops |
| Diff revisado | `main...31a23ef` (o código de produção é o de `b373052`; os commits seguintes só mexem em relatórios e status) |
| **Veredicto** | **PASS** |

Não há achado bloqueante nem alto. Há **1 achado médio** (SEC-13-01: `API_BASE_URL` sem checagem de esquema), **3 baixos** (SEC-13-02 a SEC-13-04, que são as outras três notas do review r1) e **5 informativos**. Nenhum deles exige uma r3. Pela R-10, a r3 seria a última rodada, e o risco de cada achado depende de erro de configuração do operador ou é só de higiene. O destino de cada um está na tabela: SPEC-015 ou architect.

Pontos centrais confirmados:

- **A chave de leitura não sai do processo Python.** Ela fica só no header `X-API-Key` do `httpx.Client`, que é criado uma vez em `api.get_client()` (`st.cache_resource`, memória do servidor). Ela não vai para o `st.session_state`: as únicas escritas no estado são os valores dos filtros (`filters.remember`), o offset e a consulta do Histórico e a origem da carta. Também não vai para os argumentos das funções `st.cache_data`, que recebem só `Filters`, enums e inteiros. `Settings.read_api_key` tem `repr=False`, `ApiClient.__repr__` omite a chave, as exceções usam `from None`, e os logs registram só o caminho, o status e o nome da classe do erro de transporte. O Streamlit renderiza no servidor, então nada disso chega ao navegador.
- **Não há caminho para XSS ou injeção de HTML.** Nenhum `unsafe_allow_html`, `st.html`, `components` ou `st.write` de dado externo. Os dados da API vão para `st.dataframe` (grade em canvas, sem interpretação de HTML), para figuras Plotly e para dois textos em markdown (`st.info` dos excluídos e `st.markdown` dos `warnings` do `metrics.json`). Ver SEC-13-06.
- **O 503 não gera repetição em laço.** O `httpx` não repete requisições por padrão e `follow_redirects=False`. `render_api_error` só chama `st.rerun()` dentro do `if st.button(...)`, e o único `st.rerun()` automático (Histórico, página que encolheu) só dispara com `offset > 0` e zera o offset antes, então roda no máximo uma vez. As exceções não são cacheadas.

## Superfície analisada

- **Cliente HTTP** `dashboard/src/qc_dashboard/api.py`: header `X-API-Key`, timeout de 10 s, mapeamento de erros, validação das respostas pelos modelos de `qc_contracts`.
- **Configuração** `dashboard/src/qc_dashboard/config.py`: `st.secrets`, depois o ambiente; `API_BASE_URL`, `READ_API_KEY` e `MODEL_METRICS_PATH`.
- **Cache** `dashboard/src/qc_dashboard/data.py` (`st.cache_data(ttl=30)`) e o botão "Tentar novamente" (`filters._retry`).
- **Entradas do usuário** (barra lateral e páginas): lote (`LOT_ID_PATTERN`), dispositivo (`DEVICE_ID_PATTERN`), números com limites (`number_input` mais o clamp em `_number`), enums por `selectbox`/`radio`.
- **Saídas com dados externos:** `st.info`, `st.markdown`, anotações e hover do Plotly, `st.dataframe` e o CSV (`formatting.history_csv`).
- **Arquivos locais:** `model_info.load_metrics` e `report_image`.
- **Dependência nova:** `tzdata`. **Documentação:** `.env.example` e `dashboard/README.md`.
- **Deploy:** nenhum arquivo de deploy foi tocado (`render.yaml`, `.streamlit/config.toml` e `requirements.txt` são da SPEC-015).

## Verificações feitas

1. **Vazamento da chave por cabeçalho malformado.** Sonda local, com uma chave gerada por `secrets.token_hex` e `httpx.MockTransport`:
   - sufixo não ASCII → `UnicodeEncodeError` sem a chave na mensagem;
   - TAB e NUL → aceitos pelo cliente, sem vazamento.
   - Com transporte real, o erro de protocolo do h11 é um `httpx.TransportError`, que `_get` captura, registra só pelo nome da classe e relança com `from None`.
2. **Padrões do `httpx` 0.28.1:** `follow_redirects=False`, então a chave não segue um redirecionamento para outro host, e não há repetição automática. `trust_env=True` (proxies do ambiente) não tem efeito no Streamlit CC.
3. **R-12 (CA-25):** `uv export --package qc-dashboard --frozen --no-hashes --no-dev` não contém torch, timm, onnx, qc-ml, psycopg nem supabase. O `grep` do CA-25 em `dashboard/` (sem os testes) não encontra nada.
4. **CVE:** `pip-audit` (via `uvx`, `--no-deps`) sobre as 44 dependências fixadas do export do `qc-dashboard`, que inclui streamlit 1.65.0, httpx 0.28.1, pandas 3.0.6, plotly 7.1.0, pillow 12.3.0, protobuf 7.36.2, pyarrow 25.0.1, requests 2.34.2, urllib3 2.8.0, jinja2 3.1.6 e tzdata 2026.5: *No known vulnerabilities found*.
5. **Segredos no diff:** nenhum JWT, conninfo com usuário ou senha, chave privada ou token. As chaves dos testes são geradas (`secrets.token_hex`/`token_urlsafe`, `new_key(...)`), e não há credencial em URL nem literal em header. `.env` continua no `.gitignore` (`.gitignore:15`), e `.env.example` só documenta nomes (`READ_API_KEY` sem valor).
6. **R-06:** origem padrão `Real` (`source=live`), selo `Contém dados simulados` com `Simulado` ou com `Todos` havendo simulados, legenda de origem sempre visível na Visão geral e no Histórico, e uma carta com uma origem por renderização. A checagem do selo passa pelo cache. O selo conservador da página da carta (RV-04 do review) não esconde simulado, então não é problema de segurança.
7. **R-07 e R-13:** os 20 commits de `main..HEAD` têm o trailer `Agent:` coerente com o papel (developer no código, tester nos testes de aceite, reviewer e orchestrator nos relatórios e status). A identidade é `CarlosZeyy@users.noreply.github.com`, e não há menção corporativa no diff.
8. **Testes e lint (uma execução):** `uv run pytest dashboard/tests -q` → 256 passed e 1 skipped (o teste de pilha real exige `TEST_DATABASE_URL`); `ruff check` e `ruff format --check` limpos.

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-13-01 | média | secrets | `dashboard/src/qc_dashboard/config.py:70-80`, `api.py:147-154` | **Nota 2 do review r1.** `API_BASE_URL` é aceita com qualquer esquema. Com um `http://` em produção (erro de digitação no painel de Secrets do Streamlit CC), a `READ_API_KEY` atravessa a internet em claro no header da primeira requisição. O redirecionamento HTTP→HTTPS do Render chega depois de o header já ter sido enviado, e o cliente não segue o 301 (o corpo inválido vira `ApiError`), então o painel falha, mas a chave já saiu. O `scripts/simulate.py` (`:363`) e o smoke test da SPEC-015 §4.5 já recusam `http://` fora de `localhost`/`127.0.0.1`, e o dashboard é o único cliente com chave que não recusa. Só acontece com erro do operador, por isso não é alto. | **Não bloqueia.** Destino: **architect**, para um CA numa SPEC de manutenção, ou na SPEC-015 se ele preferir reabri-la. A correção é `get_settings()` levantar `ConfigError` (mensagem só com o nome da variável) quando o esquema não for `https`, exceto `http` em `localhost`/`127.0.0.1`, com a mesma regra do simulador. Enquanto isso, o passo a passo do Streamlit CC na SPEC-015 deve dizer explicitamente `API_BASE_URL=https://<serviço>.onrender.com`. |
| SEC-13-02 | baixa | deploy | `dashboard/src/qc_dashboard/filters.py:221-223` | **Nota 1 (O-03 do tester).** `st.cache_data.clear()` limpa o cache de todas as sessões do processo. Um visitante do painel público que clique em "Tentar novamente" faz todas as sessões buscarem de novo na próxima renderização. Não abre ataque novo, porque qualquer visitante já pode gerar leituras sem cache trocando filtros, e o botão só existe enquanto a API falha, ou seja, quando o cache já não ajuda. A carga extra fica limitada pela velocidade de clique humano. Como as exceções não são cacheadas, a limpeza nem é necessária para tentar de novo. O código segue a letra da §4.1. | **Não bloqueia.** Destino: **architect** (sugestão). Na próxima mudança do dashboard, a §4.1 pode passar a dizer que o botão só chama `st.rerun()`, ou que limpa só as funções da página (`data.fetch_x.clear()`). |
| SEC-13-03 | baixa | privacy | `dashboard/views/sobre_o_modelo.py:23-24` | **Nota 3.** O estado vazio mostra o caminho absoluto do servidor (`config.REPO_ROOT / MODEL_METRICS_PATH`) no painel público. No Streamlit CC, é um caminho genérico do contêiner, sob o checkout do repositório, que é público. Localmente, aparece o caminho do usuário, mas só na máquina da dupla. A informação vazada é mínima, e o texto `<path>` é o que a §4.6 pede. | **Não bloqueia.** Destino: **architect** (sugestão). Mostrar o caminho relativo à raiz do repositório quando o arquivo estiver dentro dela, e o caminho completo só fora dela. |
| SEC-13-04 | baixa | secrets | `dashboard/README.md:33`, `.env.example:43` | **Nota 4.** `uv run --env-file .env` com o `.env` único da dupla carrega no processo do dashboard também `DATABASE_URL` e `DEVICE_API_KEY`. O dashboard não as lê, e o Streamlit não expõe o ambiente ao navegador, mas isso contraria a linha 2 do próprio `.env.example` ("Cada componente lê só as variáveis do seu bloco") e o princípio da R-12/ADR-007 de que o dashboard nunca tem acesso ao banco. Um traceback ou um log de dependência futuro poderia mostrá-las. Só afeta o uso local, porque no Streamlit CC valem apenas os Secrets do painel. | **Não bloqueia.** Destino: **SPEC-015**, que já cria `.streamlit/config.toml` e põe `.streamlit/secrets.toml` no `.gitignore` (CA-06). Documentar no README do dashboard e no `.env.example` a execução local com `.streamlit/secrets.toml`, só com `API_BASE_URL` e `READ_API_KEY`, ou com um arquivo de ambiente só do dashboard, no lugar do `.env` completo. |
| SEC-13-05 | info | deploy | `dashboard/src/qc_dashboard/data.py:27-60` | `st.cache_data` sem `max_entries`. O texto livre do lote multiplica as chaves possíveis, mas o TTL de 30 s expira as entradas a cada inserção, então a memória fica limitada ao que entra numa janela de 30 s (páginas de no máximo 100 itens). Compartilhar o cache entre sessões é correto aqui: todos os visitantes usam a mesma chave de leitura e veem os mesmos dados, então não há fronteira de autorização entre usuários. | Nenhuma nesta SPEC. Na **SPEC-015**, se a memória do Streamlit CC apertar, usar `max_entries` (por exemplo, 256). |
| SEC-13-06 | info | input | `dashboard/views/controle_estatistico.py:120-127`, `charts.py:285-288` | `SpcPoint.lot_id` e `SpcExcludedLot.lot_id` são `str` sem padrão no contrato e entram em markdown (`st.info`) e em anotações e hover do Plotly. A origem está protegida: a ingestão valida `LOT_ID_PATTERN` (`schemas.py:55`) e o banco tem `inspections_formats_check` (`infra/migrations/001_init.sql:63`), então só chegam `[A-Za-z0-9_-]`. O markdown do Streamlit não renderiza HTML cru. O pior caso é um `_` que vire itálico. | Nenhuma. Se o **architect** mexer no contrato, pode aplicar `LotId` também nos modelos de resposta (exige ADR e versão, R-04). |
| SEC-13-07 | info | input | `dashboard/src/qc_dashboard/formatting.py:188-210` | No CSV, `lot_id` e `device_id` podem começar com `-`, que alguns aplicativos de planilha tratam como início de fórmula. Os padrões não permitem `=`, `+`, `@`, `|`, `!` nem parênteses, então não há DDE nem `HYPERLINK`: no máximo um valor exibido como cálculo. | Nenhuma. |
| SEC-13-08 | info | input | `dashboard/src/qc_dashboard/model_info.py:236-244` | `MODEL_VERSION_PATTERN` (`^[a-z0-9.-]{3,40}$`) aceita `..`, então `report_image("..", ...)` resolveria `ml/<nome>.png`, um nível acima de `ml/reports/`. A docstring ("cannot point outside the reports") é imprecisa. O valor vem do `metrics.json` versionado no repositório (entrada confiável), e os nomes de arquivo são fixos. | Nenhuma nesta SPEC. Sugestão ao **architect** para uma manutenção futura: recusar `.`/`..` ou conferir `path.resolve().is_relative_to(reports_dir)`. |
| SEC-13-09 | info | deploy | `dashboard/src/qc_dashboard/api.py:239-247` | Uma exceção não prevista, como o `UnicodeEncodeError` de uma chave não ASCII ao criar o cliente, sai do `api_guard`, e o Streamlit mostra o traceback na página. A mensagem não contém a chave (verificação 1), mas mostra código-fonte. | Nenhuma nesta SPEC. Já está coberto pela **SPEC-015** §4.4 (`client.showErrorDetails` com o valor que oculta detalhes). |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota; comparação em tempo constante | N/A: o dashboard não expõe rotas. Toda chamada à API leva `X-API-Key`, e a comparação é da API (SPEC-005/006, já aprovadas). 401/403 viram mensagem sem a chave. |
| Entradas validadas (tamanho, tipo real de imagem, regex, `extra="forbid"`) | OK. Lote e dispositivo validados por regex do contrato antes de entrar na query (CA-21); números limitados às faixas da API; enums por seleção. As respostas são validadas pelos modelos de `qc_contracts`, e corpo inválido vira `ApiError`. Não há upload de imagem. `extra="ignore"` nas respostas é o contrato vigente (tolerância a campos novos). |
| SQL parametrizado | N/A: sem acesso a banco (CA-25 e verificação 3). |
| RLS; `DATABASE_URL` e `service_role` fora da API | OK: nenhuma referência no código do dashboard. Ressalva de uso local no SEC-13-04. |
| CORS | N/A: o dashboard não serve API. |
| Logs sem segredos e sem payloads de imagem | OK: caminho, status e nome da classe do erro, sem query nem header. CA-04 cobre `caplog` em DEBUG. |
| Dependências novas mantidas, com licença compatível e sem CVE crítica | OK: `tzdata` (verificação 4 e tabela abaixo). |
| Deploy: variáveis no provedor, health check, free sem cartão | N/A nesta SPEC (SPEC-015). Pendências levadas para lá: SEC-13-01 (instrução de `https://`), SEC-13-04, SEC-13-05 e SEC-13-09. |
| R-02 / R-14 (imagens) | OK: o dashboard não recebe imagens da borda. Os PNGs de matriz de confusão são artefatos agregados do repositório. |
| R-06 | OK (verificação 6). |
| R-12 | OK (verificação 3). |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| `tzdata` | 2026.5 (já estava no `uv.lock` como transitiva; o diff só acrescenta a aresta do `qc-dashboard`) | Apache-2.0 | Pacote oficial dos dados IANA, mantido pelo time do CPython. A §4.8 o autoriza. Necessário porque `zoneinfo` depende do banco de fusos do sistema, e uma imagem mínima pode não tê-lo. Sem CVE conhecida (`pip-audit`). |

## Declaração

- [x] Não editei código; não sou autor desta SPEC.
