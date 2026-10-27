# qc-dashboard

Painel Streamlit do PartQC (SPEC-013, SPEC-018, ADR-007). Lê **todos** os dados pela `qc-api`, com a chave de leitura no header `X-API-Key`, e nunca acessa o banco. Os rótulos em PT-BR vêm de `qc_contracts.labels` (ADR-012).

## Páginas

| Página | Arquivo | O que mostra |
|---|---|---|
| Visão geral (padrão) | `views/visao_geral.py` | KPIs, distribuição por grau e por tipo, volume e taxa de defeito no tempo |
| Controle estatístico | `views/controle_estatistico.py` | Carta p por lote de **uma** origem (ADR-013, ADR-017) e tabela dos lotes |
| Histórico | `views/historico.py` | Inspeções paginadas, filtros da página e CSV da página atual |
| Sobre o modelo | `views/sobre_o_modelo.py` | `metrics.json` do modelo contra as metas do PRD (SPEC-012) |
| Dispositivos | `views/dispositivos.py` | Cada dispositivo `online`/`offline`, com a origem dos dados, o último sinal, o modelo, a versão da borda, as filas do outbox e o tempo ligado (SPEC-018) |

A barra lateral (origem, período, tipo e lote) vale para todas as páginas e é mantida ao trocar de página. A origem padrão é **Real**. Na Visão geral, no Histórico e em "Sobre o modelo", com `Simulado`, ou com `Todos` quando há dados simulados nos filtros, a página mostra o aviso `Contém dados simulados` (R-06). A Visão geral e o Histórico sempre dizem a origem em vigor logo abaixo do título.

A carta p usa toda a história da origem escolhida: o período da barra lateral não se aplica a ela. A origem da carta acompanha a da barra lateral (`Simulado` lá → `Simulado` aqui; `Real` ou `Todos` → `Real`); numa sessão nova, ela começa em `Real` e pode ser trocada na própria página. Nessa página, o aviso `Contém dados simulados` aparece se, e só se, a carta for `Simulado` (ele não depende da barra lateral), e a origem da carta aparece sempre logo abaixo do título (`Origem da carta: real` ou `Origem da carta: simulado`), fora da figura (SPEC-028).

"Sobre o modelo" lê as métricas de um arquivo local. A API só é consultada para o aviso com a origem `Todos`; se essa consulta falhar, a página mostra o erro e o aviso (por conservadorismo) e continua com as tabelas e as imagens.

"Dispositivos" lê `GET /api/v1/devices`, com o mesmo cache das outras leituras. Quem decide `online` é a API: o último heartbeat da borda chegou há menos de 180 s, pela hora do servidor (com o cache de 30 s, a mudança pode levar até ~3,5 min para aparecer). `Último sinal` é a hora local do último heartbeat (`nunca` sem heartbeat) e `Ligado há` é o tempo ligado que ele informou (ex.: `2 h 05 min`; `—` sem heartbeat). `Origem` é a origem da inspeção mais recente do dispositivo (`real`, `simulado` ou `—`); se algum dispositivo estiver com `simulado`, a página mostra o aviso `Contém dados simulados` (R-06). O simulador não envia heartbeat, então aparece `offline`, com a origem `simulado`. Os filtros da barra lateral não se aplicam a essa página.

As figuras não têm a barra de ferramentas do Plotly, que, em aparelhos de toque, fica sempre visível sobre o título. O botão de tela cheia do Streamlit continua.

## Configuração

| Variável | Obrigatória | Descrição |
|---|---|---|
| `API_BASE_URL` | sim | URL base da `qc-api`, com `https://` (ex.: `https://<serviço>.onrender.com`); `http://` só em `localhost` ou `127.0.0.1` (ex.: `http://localhost:8001`) |
| `READ_API_KEY` | sim | Chave de leitura (segredo; o mesmo valor configurado na API) |
| `MODEL_METRICS_PATH` | não | `metrics.json` da página "Sobre o modelo"; relativo à raiz do repositório ou absoluto. Padrão: `ml/models/partqc-mnv3-v1/metrics.json`. Se o arquivo não existir, a mensagem mostra o caminho relativo à raiz (ou o absoluto, se ele ficar fora do repositório) |

Cada valor é lido de `st.secrets` (em produção, Streamlit → Secrets; SPEC-015) e, se a chave não existir lá ou não houver arquivo de secrets, da variável de ambiente de mesmo nome. Sem `API_BASE_URL` ou `READ_API_KEY`, as páginas que leem a API mostram `Configuração ausente` e param. Com uma `API_BASE_URL` que não use `https://` (salvo `http://` em `localhost` ou `127.0.0.1`), elas mostram `Configuração inválida: API_BASE_URL precisa usar https:// (http:// só em localhost ou 127.0.0.1).` e param sem nenhuma requisição, para que a chave nunca trafegue em claro. Nunca coloque a chave no Git (R-03).

## Rodar localmente

Localmente, o dashboard lê a configuração de um arquivo `.streamlit/secrets.toml` **na raiz do repositório**, só com as duas variáveis dele. O Streamlit procura esse arquivo em `.streamlit/secrets.toml` a partir da pasta de onde se roda o `streamlit run` (e em `~/.streamlit/secrets.toml`), por isso o comando abaixo é rodado da raiz. O arquivo está no `.gitignore` (R-03).

```toml
# .streamlit/secrets.toml (na raiz do repositório; nunca vai para o Git)
API_BASE_URL = "http://localhost:8001"
# o mesmo valor de READ_API_KEY configurado na API (segredo)
READ_API_KEY = ""
```

```bash
uv sync --all-packages
# com a API rodando em http://localhost:8001 (ver api/), a partir da raiz do repositório:
uv run --package qc-dashboard streamlit run dashboard/app.py
```

Não carregue o `.env` único do projeto no dashboard: ele traz também a connection string do banco e a chave do dispositivo de borda, que o dashboard não usa e não deve ter no processo (ADR-007).

## Comportamento com a API

- Todas as leituras passam pelas funções de `qc_dashboard.data`, com cache de 30 s (`st.cache_data`). Erros não são cacheados.
- Todas as leituras guardam no máximo 256 entradas por função (`max_entries`); com o cache cheio, a entrada mais antiga sai.
- Timeout (10 s), erro de conexão ou HTTP 502/503/504: aviso `API acordando (free tier), tente em ~1 min` e o botão `Tentar novamente`, que só recarrega a página (`st.rerun()`): como os erros não são cacheados, a nova tentativa já vai à API, e as leituras que deram certo continuam no cache, inclusive as das outras sessões. Nada é repetido automaticamente.
- HTTP 401/403: `Chave de leitura inválida ou ausente (READ_API_KEY).` Outros erros: `Erro da API (HTTP <status>).` Nenhum stack trace na tela, e a chave nunca aparece em log ou mensagem.

## Estrutura

```text
app.py                     st.navigation com as 5 páginas
views/                     uma página por arquivo
src/qc_dashboard/
  config.py                secrets e variáveis de ambiente
  api.py                   cliente HTTP (ApiClient, Filters, erros, get_client)
  data.py                  leituras com cache, uma por endpoint
  filters.py               barra lateral, selo de simulado, mensagens de erro
  charts.py                figuras Plotly puras
  formatting.py            rótulos, números, fuso, CSV
  model_info.py            metrics.json e metas do PRD
tests/                     testes do autor (tests/acceptance/ é do tester)
```

## Dependências (R-12)

Só `streamlit`, `plotly`, `pandas`, `httpx`, `tzdata` e `qc-contracts`. Nada de torch, timm, runtime de inferência, `qc-ml`, driver de banco ou SDK do provedor do banco.

## Testes

```bash
uv run pytest dashboard/tests -q
```

As páginas são testadas com `streamlit.testing.v1.AppTest`, com `api.get_client` trocado por um `ApiClient` sobre `httpx.MockTransport`. Nenhum teste acessa a rede.
