# SPEC-028 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-028](../../docs/specs/SPEC-028-manutencao-dashboard.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `882e80f` (implementação e dev-report); testes em `39669ca` (ajuste da SPEC-013) e no commit deste relatório |
| **Veredicto** | **PASS** (CAs automatizáveis; o CA-12 é manual e fica pendente para a dupla) |

## Cobertura dos critérios de aceite

Arquivo: `dashboard/tests/acceptance/test_spec_028.py` (52 testes coletados: 23 dos CAs, contando os parâmetros, e 29 exploratórios).

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_insecure_api_base_url_is_refused` (6 URLs; `get_settings` + Visão geral com o `get_client` real e `httpx.HTTPTransport.handle_request` interceptado: 0 requisições) e `test_ca01_secure_api_base_url_is_accepted` (4 URLs) | ✅ |
| CA-02 | `test_ca02_every_chart_hides_the_mode_bar` (3 + 1 `plotly_chart`, `proto.config` com `displayModeBar: false`) | ✅ |
| CA-03 | `test_ca03_series_right_margin` | ✅ |
| CA-04 | `test_ca04_spc_badge_follows_only_the_chart_origin` (a, b, c; 0 requisições a `/metrics/summary`) | ✅ |
| CA-05 | `test_ca05_model_page_without_the_api` (timeout e 401) | ✅ |
| CA-06 | `test_ca06_display_rule` (valores exatos e ausência dos valores com o arredondamento errado) | ✅ |
| CA-07 | `test_ca07_retry_does_not_clear_the_cache` (espião em `st.cache_data.clear`) | ✅ |
| CA-08 | `test_ca08_full_cache_drops_the_oldest_entry` (257 lotes) | ✅ |
| CA-09 | `test_ca09_missing_metrics_relative_and_absolute_path` | ✅ |
| CA-10 | `test_ca10_report_image_refuses_links_out_of_reports` (link simbólico em `tmp_path`) | ✅ |
| CA-11 | `test_ca11_readme_env_example_and_gitignore` (`git check-ignore`, blocos de código do README, comentários acima de `API_BASE_URL=`) | ✅ |
| CA-12 | manual | ⏳ pendente (dupla) |

### CA-12 (manual): pendente

Não executado pelo tester (exige celular e desktop reais). A dupla segue os passos 1 a 6 do CA-12 da SPEC (detalhados no `r1-dev-report.md`) e registra aqui: aparelho, navegador, data e quem executou. Se o último rótulo da série ainda for cortado com 60 px, registrar `SPEC_ISSUE` com a largura medida (SPEC §7).

| Passo | Aparelho / navegador | Data | Quem | Resultado |
|---|---|---|---|---|
| 3 (celular ~400 px) | | | | |
| 4 (desktop 1280 px) | | | | |
| 5 (selo com `Todos`) | | | | |

## Testes de aceite de SPECs anteriores ajustados

Regra "Testes de aceite de SPECs anteriores" de `docs/architecture.md` §10, aplicação explícita da SPEC-028 §3.1, item 1. Commit próprio: `39669ca` (`Agent: tester`).

| Arquivo | Teste | Asserção antes → depois | Requisito |
|---|---|---|---|
| `dashboard/tests/acceptance/test_spec_013.py` | `test_extra_real_api_end_to_end` (laço "Step 3") | Antes: para `SPC_PAGE`, `HISTORY` e `MODEL_PAGE`, `assert contains(values(at.main.warning), BADGE)`. Depois: para `SPC_PAGE`, `assert not contains(values(at.main.warning), BADGE)` e `assert "Origem da carta: real" in values(at.main.caption)`; para `HISTORY` e `MODEL_PAGE`, a asserção original, sem mudança | SPEC-028 §4.3 e CA-04 (a); §3.1, item 1 |
| idem | idem (comentário do laço) | `# Step 3: with 'Todos', the badge is on every page.` → comentário de 2 linhas que diz que a página da carta é a exceção (SPEC-028 §4.3). Só texto, para o comentário não contradizer a asserção | SPEC-028 §4.3 |

Nenhum `test_caNN_` da SPEC-013 mudou; nenhuma outra linha do arquivo mudou. O teste passa com `CI=true` e `TEST_DATABASE_URL`.

## Suíte completa

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
3855 passed, 1 warning in 239.87s (0:03:59)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
297 files already formatted

$ uv run pytest -q dashboard/tests/acceptance/test_spec_028.py
52 passed
```

O warning é o `StarletteDeprecationWarning` do `fastapi.testclient`, de fora desta SPEC.

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Todos passam (`test_extra_*` no mesmo arquivo):

- **URLs enganosas recusadas** (`InsecureApiUrlError`, mensagem começa com `API_BASE_URL` e não traz o host): `http://localhost.example.org`, `http://127.0.0.1.example.org:8001`, `http://localhost:8001@example.org` (userinfo; o host real é `example.org`), `http://0.0.0.0:8001`, `https:`, `//example.org`, `http://[::1` (malformada, `urlsplit` levanta `ValueError`), `javascript:alert(1)`.
- **Aceitas:** `HTTP://LOCALHOST:8001` (o `.hostname` vem em minúsculas) e `  https://api.example.org  ` (espaços removidos na leitura).
- **URL insegura nas páginas Controle estatístico e Histórico:** texto completo `Configuração inválida: ... (http:// só em localhost ou 127.0.0.1).`, 0 requisições na rede e o host não aparece na página.
- **Chave ausente + URL insegura:** vale `Configuração ausente` (SPEC §4.1), 0 requisições.
- **"Sobre o modelo" com `Todos`:** URL insegura (`ConfigError`) → mensagem, selo e tabelas, 0 requisições; HTTP 500 → `Erro da API (HTTP 500).`, selo e tabelas; timeout e depois "Tentar novamente" → 1 requisição de resumo, aviso some, selo some (total simulado 0), tabelas continuam; com `Real` ou `Simulado`, nenhuma requisição mesmo com a API caída.
- **Regra de exibição:** `grade_mae=0.30000000000000004` → `0,3001` (SPEC §7); `needs_review_rate=0.1` → `0,1000`; `latency_ms_p50=40.0` → `40,0000`; `unusable_recall=0.89999` → `0,8999` e `Abaixo da meta`; IC `[0.80009, 0.96001]` → `[0,8000; 0,9601]`; `latency_runs` inteiro.
- **Carta:** a legenda `Origem da carta:` continua visível quando a API dá timeout; com `Todos`, a barra lateral não mostra a legenda do selo; a Visão geral mantém o selo pelos filtros globais com `Todos` (SPEC §7).
- **`report_image`:** `None` para `..`, `.`, `....`, `partqc-ok-v1/../x`, `""`, `None` e `3`, e para um link simbólico de **arquivo** que aponta para fora de `ml/reports/`.
- **Cache:** as 6 funções `fetch_*` de `data.py` têm `ttl` e `max_entries` no decorador.
- **Git:** nenhum `.streamlit/secrets.toml` versionado (raiz ou `dashboard/`).

### Observações (não são bugs desta SPEC)

- **Isolamento do `.streamlit/secrets.toml` local:** os testes da SPEC-028 trocam `st.secrets` por um objeto sem arquivo, então não dependem da máquina. Os testes de aceite da SPEC-013 (`_isolated` troca só `HOME`; o CA-05 faz `chdir`) podem ler um `.streamlit/secrets.toml` na raiz, se a dupla o criar como o README recomenda, e falhar localmente (o dev-report descreve o mecanismo). No CI não há o arquivo, e nesta máquina ele não existe hoje. Blindar o `test_spec_013.py` ficaria fora do ajuste autorizado pela §3.1, por isso não foi feito. Sugestão ao orquestrador: registrar como pendência de teste (`test_spec_013.py::_isolated`) para uma SPEC futura, ou rodar a suíte sem esse arquivo.
- **Teste do CA-04 (c):** o rádio "Origem da carta" de volta a `Real` reaproveita a leitura `live` em cache da primeira renderização; para conferir o `source=live` da requisição, o teste limpa o cache antes da troca. É comportamento esperado (SPEC-013 CA-30), não bug.

## SPEC_ISSUE (se houver)

Nenhum.

## O que ficou de fora

- CA-12 (manual), pendente para a dupla.
- Nenhum teste de aceite foi rodado contra a `main` para confirmar que falharia antes da mudança (prova de sensibilidade); os CAs verificam valores exatos e contagens de requisições, e os exploratórios cobrem as variações.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
