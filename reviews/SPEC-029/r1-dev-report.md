# SPEC-029 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-029](../../docs/specs/SPEC-029-manutencao-dashboard-simulador.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-029-manutencao-dashboard-simulador` |
| Commits | `0312b91` (relatório com o SPEC_ISSUE-01), `73fcecf`, `94de48e`, `c21ebde`, mais o commit deste relatório |

## Resumo

Depois que o SPEC_ISSUE-01 foi resolvido (`cd99179`, reaprovação pelo ADR-019), implementei as três partes que são do developer:

- **§4.3:** `is_secure_api_url` agora recusa qualquer caractere `Cc`, com a checagem feita antes do `urlsplit`. Também recusa a URL quando a leitura de `parts.port` levanta `ValueError`; essa leitura fica dentro do mesmo `try` do `urlsplit`.
- **§4.2:** na página de controle estatístico, o selo também é decidido pela origem devolvida (`spc.source`). Ele vai para o mesmo `badge_slot` e aparece uma vez só, sem requisição nova.
- **§4.4:** o caso `https://xn--1-zhc.com` entrou na parametrização do teste do autor do simulador.

A §4.1 é do tester, e não mexi em nada de `tests/acceptance/`.

Abri o **SPEC_ISSUE-02**, de baixa gravidade: uma asserção do CA-04 sobre a mensagem da exceção não pode ser cumprida sem mudar o texto constante, e mudar esse texto fica fora da §3.1. O código entregue mantém a mensagem de hoje. Detalhes abaixo.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | tester (§4.1, `_isolated` de `test_spec_013.py`) | — (o `conftest.py` do autor já isola o `st.secrets` desde a SPEC-028) |
| CA-02 | tester (§4.1) | — |
| CA-03 | `dashboard/views/controle_estatistico.py`; `dashboard/tests/conftest.py` (`MockApi.spc_source`, origem da resposta do SPC para o teste; `None` repete a da query) | `dashboard/tests/test_pages.py::test_spc_badge_by_returned_origin` (Real→simulated: 1 selo; Real→live: 0; Simulado→simulated: 1; Todos→simulated: 1; sempre 1 requisição ao SPC e 0 a `/metrics/summary`), `::test_spc_returned_badge_is_in_the_badge_slot` |
| CA-04 | `dashboard/src/qc_dashboard/config.py` (`is_secure_api_url`) | `dashboard/tests/test_config.py::test_any_control_character_is_refused` (65 caracteres `Cc` × 5 posições), `::test_invalid_port_or_control_character_is_refused`, `::test_valid_port_is_still_accepted`, `::test_get_settings_refuses_invalid_port_or_control_character`, `::test_get_settings_refuses_them_from_the_environment`, `::test_control_character_only_at_the_edges_is_trimmed_first` (frase nova da §4.3), `::test_trailing_del_is_not_trimmed`; `dashboard/tests/test_pages.py::test_malformed_url_stops_the_overview` (os 7 valores do CA-04: `st.error` de configuração, 0 envios, sem exceção) |
| CA-05 | `scripts/tests/test_simulate.py` (só o teste; `scripts/simulate.py` não muda) | `::test_visible_ascii_api_url_still_sends[https://xn--1-zhc.com]`; `::test_idna_case_needs_raw_host` (protege a premissa) |

Mutações que conferi à mão, todas revertidas antes de commitar:

- Com a view da `main`, 3 dos 5 testes novos de selo falham: Real→simulated, Todos→simulated e o do slot.
- Com `scripts/simulate.py` usando `.host` no lugar de `.raw_host`, `test_visible_ascii_api_url_still_sends[https://xn--1-zhc.com]` falha.

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1). O SPEC_ISSUE-01 desta rodada está resolvido (ver abaixo).

## Como rodar e verificar

```bash
uv run pytest -q dashboard/tests/test_config.py dashboard/tests/test_pages.py
uv run pytest -q scripts/tests/test_simulate.py -k "visible_ascii_api_url_still_sends and xn--1-zhc"   # 1 passed
uv run ruff check . && uv run ruff format --check .
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

Resultado da suíte completa (banco `partqc-pg-host`): `5531 passed, 52 skipped, 1 warning`. A warning é a `StarletteDeprecationWarning` do `fastapi.testclient`, que já existia. ruff check e ruff format --check estão limpos.

Nenhum teste de aceite antigo falhou. Os testes de selo da SPEC-028 (CA-04) não mudaram e passam, como a §7 exige.

## Decisões tomadas dentro do escopo da SPEC

- **Selo (§4.2):** guardei o retorno de `filters.render_chart_badge(source)` em `badge_shown`. Depois da leitura, se o selo ainda não apareceu, chamo `filters.render_chart_badge(spc.source)` dentro do mesmo `badge_slot`. Não precisei de função nova em `filters.py`. O componente continua o mesmo de hoje (`show_badge`: `st.warning` na página e legenda na barra lateral).
- **Mock (só testes do autor):** `MockApi.spc_source` (padrão `None`) força a origem da resposta do SPC. Com `None`, o mock repete a query, como antes.
- **Porta:** `https://host:` (porta vazia) continua aceita, porque `parts.port` devolve `None` e não levanta. `:0` e `:65535` são aceitas, pela faixa 0–65535 da §4.3.

## SPEC_ISSUE (se houver)

### SPEC_ISSUE-01 — resolvido

O caso `https://api.example.org/\x85` do CA-04 não podia ser atingido, porque `_read()` apara o valor com `strip()`. O architect resolveu pela opção 2 em `cd99179`: o caso virou `https://api.exa\x85mple.org`, e a §4.3 ganhou uma frase de esclarecimento. O orquestrador reaprovou pelo ADR-019 (Histórico da SPEC, 2026-10-20). O novo caso passa, e há teste do autor para o comportamento de aparar as pontas descrito na nova frase da §4.3.

### SPEC_ISSUE-02 — CA-04: "a mensagem não contém `localhost`" contradiz a mensagem constante que a §4.3 e a §3.1 mantêm

- O **CA-04** pede que, para os 7 valores recusados, a mensagem de `InsecureApiUrlError` "não contém `example.org` nem `localhost`".
- A §4.3 diz que "a mensagem da exceção e a da tela continuam constantes (SPEC-028 §4.1)", e a §3.1 limita `config.py` a `is_secure_api_url`. Hoje a mensagem constante, levantada em `get_settings()` (`config.py`, fora de `is_secure_api_url`), é `API_BASE_URL must use https:// (http:// only for localhost or 127.0.0.1)`, que **contém `localhost`**. Isso vale para qualquer valor recusado, e não só para `http://localhost:abc` e `http://local\thost:8001`.
- Resultado: a parte "nem `localhost`" do CA-04 falha com qualquer implementação que mantenha a mensagem. Para cumpri-la, eu teria que mudar o texto em `get_settings()`, o que está fora da §3.1. Nenhum teste existente fixa esse texto, exceto os testes do autor em `dashboard/tests/test_config.py`, que eu ajustaria.
- **O que entreguei:** a mensagem ficou como está. Os testes do autor conferem que ela é o texto constante, que não contém o valor recusado e que não contém `example.org`. A tela (`INSECURE_API_URL_MESSAGE`) não entra nessa questão, porque o CA-04 só exige que o `st.error` comece por `Configuração inválida: API_BASE_URL precisa usar https://`.

Resoluções possíveis (a escolha é do architect/humano):

1. **Ajustar o CA-04:** a mensagem "não contém o valor de `API_BASE_URL` nem `example.org`" (ou "é exatamente o texto constante da SPEC-028 §4.1"). Assim a intenção (R-03, valor nunca ecoado) fica preservada, e não muda código.
2. **Ampliar a §3.1** para permitir trocar o texto da exceção em `get_settings()` por um sem `localhost` (ex.: `API_BASE_URL must use https:// (http:// only for a loopback host)`). A mensagem da tela fica como está. Mudaria só um literal e o teste do autor que o fixa.

A implementação de `is_secure_api_url` não muda em nenhuma das duas. Se for a opção 2, a mudança é de uma linha.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (suíte completa: 5531 passed, 52 skipped)
- [x] `.env.example` atualizado (se houver variável nova): nenhuma variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
