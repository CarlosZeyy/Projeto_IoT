# SPEC-018 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-018](../../docs/specs/SPEC-018-heartbeat-dispositivos.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `ea13d41` (implementação em `77768b6`…`baf4f18`, dev report em `6052be4`) |
| **Veredicto** | **PASS**: todos os CAs automatizados (CA-01 a CA-12) têm teste e passam, a suíte inteira passa e o ruff está limpo; nenhum bug e nenhum `SPEC_ISSUE`. O CA-13 é manual e fica pendente para a dupla. |

Os testes de contrato e de API foram escritos a partir do texto da SPEC, em caixa-preta, antes da leitura da implementação. Na borda e no dashboard, a SPEC não fixa a assinatura do construtor do `HeartbeatLoop`, como o `HttpPublisher` recebe o `device_id` nem o formato de `Último sinal`; por isso li `qc_edge/heartbeat.py`, `qc_edge/publisher.py`, o `_build_sink` do `qc_edge/cli.py` e as funções novas do dashboard antes de escrever esses testes, só para chamar a interface pública (`HttpPublisher(..., device_id=...)`, `HeartbeatLoop(publisher, sink, inferencer, *, interval_s, ...)`, `formatting.device_rows`, `data.fetch_devices`, `ApiClient.devices`); as asserções seguem o texto da SPEC, não a implementação.

- Banco real `partqc_test` (marcador `db`, `clean_db` da SPEC-003). O relógio do servidor é "movido" gravando `last_heartbeat_at = now() - make_interval(secs => N)` direto no banco, como o contexto comum do §5 permite.
- Borda: só a rede da nuvem é simulada (`httpx.MockTransport`, ou um servidor HTTP local em `127.0.0.1` no teste ponta a ponta), mais o relógio monotônico e o `uvicorn.run` (espião). SQLite real em `tmp_path`, modelo dummy ONNX da SPEC-008 §6 construído no teste, imagens sintéticas em memória (R-14).
- Dashboard: só o HTTP do `ApiClient` é simulado (`httpx.MockTransport` com corpos do contrato); páginas pelo `streamlit.testing.v1.AppTest`.
- Chaves de dispositivo, chaves de leitura, tokens e marcadores gerados em tempo de execução (R-03); nenhuma credencial literal em URL ou header. Nenhum teste roda o pytest em subprocesso (`docs/architecture.md` §10).

## Arquivos e contagem

| Arquivo | Testes | Itens de CA (`test_caNN_*`, com parametrização) | Exploratórios (`test_extra_*`) |
|---|---|---|---|
| `packages/contracts/tests/acceptance/test_spec_018.py` | 55 | 11 | 44 |
| `api/tests/acceptance/test_spec_018.py` | 57 | 13 | 44 |
| `edge/tests/acceptance/test_spec_018.py` | 44 | 15 | 29 |
| `dashboard/tests/acceptance/test_spec_018.py` | 24 | 2 | 22 |
| **Total** | **180** | **41** | **139** |

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `packages/contracts/tests/acceptance/test_spec_018.py::test_ca01_contracts_version_is_0_5_0` (`__version__ == importlib.metadata.version("qc-contracts") == "0.5.0"`), `::test_ca01_valid_heartbeat_round_trip`, `::test_ca01_valid_heartbeat_without_model_round_trip`, `::test_ca01_extra_field_is_refused`, `::test_ca01_negative_uptime_is_refused`, `::test_ca01_outbox_pending_above_max_is_refused`, `::test_ca01_app_version_with_trailing_newline_is_refused`, `::test_ca01_sent_at_without_timezone_is_refused`, `::test_ca01_sent_at_six_minutes_in_the_future_is_refused`, `::test_ca01_model_version_without_sha_is_refused`, `::test_ca01_pyproject_and_readme_history` | ✅ |
| CA-02 | `api/tests/acceptance/test_spec_018.py::test_ca02_heartbeat_204_and_listed_online` (204 com corpo vazio; `GET /devices` com `online == true`, `outbox_pending == 3`, `last_heartbeat_at` não nulo; cada item valida como `DeviceStatus`) | ✅ |
| CA-03 | `api/.../test_spec_018.py::test_ca03_key_of_another_device_is_403`, `::test_ca03_without_key_is_401`, `::test_ca03_invalid_key_is_401`, `::test_ca03_extra_field_is_422_and_body_not_logged` (`caplog` em DEBUG sem o marcador do campo extra, sem o `app_version` marcador, sem `987654` e sem o JSON do corpo), `::test_ca03_device_id_outside_pattern_is_422` (`EDGE_01`) | ✅ |
| CA-04 | `api/.../test_spec_018.py::test_ca04_online_window_179_and_181_seconds`, `::test_ca04_device_without_heartbeat_is_offline` | ✅ |
| CA-05 | `api/.../test_spec_018.py::test_ca05_last_source_is_the_most_recent_inspection` (`edge-01`: `simulated` recebida 1 min antes de uma `live` → `live`; `sim-01` só `simulated` → `simulated`; `edge-02` sem inspeção → `null`) | ✅ |
| CA-06 | `api/.../test_spec_018.py::test_ca06_list_without_read_key_is_401`, `::test_ca06_list_with_a_device_key_is_401` | ✅ |
| CA-07 | `api/.../test_spec_018.py::test_ca07_negative_uptime_is_refused_by_the_database`, `::test_ca07_model_version_without_sha_is_refused_by_the_database` (ambos `23514`) | ✅ |
| CA-08 | `edge/tests/acceptance/test_spec_018.py::test_ca08_one_cycle_sends_the_heartbeat_with_model_and_outbox` (um `POST /api/v1/devices/edge-07/heartbeat` com `X-API-Key`; corpo `HeartbeatCreate` com `outbox_pending == 2`, `outbox_dead == 1` e `model_version`/`model_sha256` do `OnnxInferencer`), `::test_ca08_without_model_the_model_fields_are_null` | ✅ |
| CA-09 | `edge/.../test_spec_018.py::test_ca09_cloud_down_three_cycles_no_exception_and_outbox_unchanged[connect-error]` e `[http-503]` (3 ciclos, nenhuma exceção, linhas do outbox idênticas, `WARNING` e nenhum `ERROR`), `::test_ca09_capture_keeps_working_with_the_cloud_down` (captura `inspect` 200 com o laço registrado no app; só a captura acrescenta linha ao outbox), `::test_ca09_auth_error_only_the_first_cycle_sends_and_one_error[401]` e `[403]` | ✅ |
| CA-10 | `edge/.../test_spec_018.py::test_ca10_no_heartbeat_with_stub_model`, `::test_ca10_no_heartbeat_with_interval_zero`, `::test_ca10_no_heartbeat_without_device_api_key`, `::test_ca10_invalid_interval_exits_with_code_2[5]` e `[abc]` (código 2, `uvicorn.run` não chamado), com o controle positivo `::test_ca10_control_heartbeat_is_registered_with_key_url_and_model` (sem ele, "nenhum laço" passaria trivialmente) | ✅ |
| CA-11 | `edge/.../test_spec_018.py::test_ca11_only_the_publisher_imports_httpx` (varredura AST de `edge/src/qc_edge/`: o conjunto de módulos com cliente HTTP é exatamente `{publisher.py}`, com `heartbeat.py` presente), `::test_ca11_checker_is_not_tautological`; e o CA-17 da SPEC-007 (`edge/tests/acceptance/test_spec_007.py::test_ca17_no_http_client_import_outside_the_publisher`) passa na suíte completa | ✅ |
| CA-12 | `dashboard/tests/acceptance/test_spec_018.py::test_ca12_online_simulated_device_row` (`online`, `simulado`, `2 h 05 min`), `::test_ca12_device_without_heartbeat_row` (`offline`, `nunca`, `—`) | ✅ |
| CA-13 | manual (borda contra a nuvem publicada, dupla) | ⏳ pendente: registrar na Definição de pronto; roteiro no dev report |

## Suíte completa

Ambiente do CI (`uv sync --all-packages`, sem torch), banco `partqc_test`, nenhuma outra suíte com banco rodando, no estado do commit de testes deste relatório:

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
7684 passed, 75 skipped, 1 warning in 641.67s (0:10:41)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
263 files already formatted
```

Antes dos testes e dos ajustes deste relatório, o dev report registra `7498 passed, 75 skipped, 6 failed`; as 6 falhas eram exatamente os aceites antigos da tabela de ajustes abaixo. Depois dos ajustes, nenhuma falha: 7498 + 6 + os 180 testes novos = 7684. Os 75 pulados são os de Docker, MQTT, modelo real e torch, como antes.

## Ajustes em testes de aceite de SPECs anteriores (`docs/architecture.md` §10)

Só as asserções afetadas mudaram; nenhum `test_caNN_` foi removido nem renomeado, e a contagem de testes coletados em cada arquivo é a mesma de antes. Os ajustes de versão do `qc-contracts` (as duas primeiras linhas) estão no mesmo commit que cria `packages/contracts/tests/acceptance/test_spec_018.py`, como pede o §10.

| Arquivo | Teste | Antes → depois | Requisito da SPEC-018 | Na §3.1? |
|---|---|---|---|---|
| `packages/contracts/tests/acceptance/test_spec_016.py` | `test_ca01_contracts_version_is_0_4_0` | `__version__ == "0.4.0"` e `version("qc-contracts") == "0.4.0"` → coerência `__version__ == importlib.metadata.version("qc-contracts")`, formato `\d+\.\d+\.\d+` e piso `(0, 4, 0) <= v < (1, 0, 0)` (o nome fica: um `test_caNN_` não se renomeia; precedente da SPEC-016 no `test_spec_026.py`) | §3.1 e §4.1 (`__version__ = "0.5.0"`), "Expectativas de versão" | sim |
| `api/tests/acceptance/test_spec_004.py` | `ALLOWED_EXACT` do `test_ca28_version_expectations_migrated` | par `(SPEC016_CONTRACTS, "qc_contracts", "0.4.0")` → `(SPEC018_CONTRACTS, "qc_contracts", "0.5.0")`, com a constante nova `SPEC018_CONTRACTS = "packages/contracts/tests/acceptance/test_spec_018.py"` (a `SPEC016_CONTRACTS` fica, como a `SPEC026_CONTRACTS` ficou na SPEC-016) | §3.1 | sim |
| `api/tests/acceptance/test_spec_016.py` | `test_extra_health_reports_contract_0_4_0` → **renomeado** `test_extra_health_reports_contract_at_least_0_4_0` (teste extra) | `body["contract_version"] == "0.4.0"` → formato `\d+\.\d+\.\d+` e piso `(0, 4, 0) <= v < (1, 0, 0)`; `import re` acrescentado no topo do arquivo para isso. A intenção (o `/health` informa o contrato que traz as ferramentas) continua | §4.1 (`__version__ = "0.5.0"`; o `/health` devolve `qc_contracts.__version__`, SPEC-004) | não (§10, regra geral e "Expectativas de versão") |
| `infra/tests/acceptance/test_spec_003.py` | `test_extra_devices_columns` | `cols == {4 colunas}` → `{name: cols.get(name) for name in expected} == expected` (as 4 colunas da SPEC-003, com os mesmos tipos e a mesma nulidade; as 8 colunas novas são verificadas no `api/tests/acceptance/test_spec_018.py::test_extra_heartbeat_columns_are_nullable_with_the_spec_types`) | §4.2 (migração que acrescenta 8 colunas a `devices`) | não (§10) |
| `dashboard/tests/acceptance/test_spec_028.py` | `test_extra_every_cached_read_has_max_entries` | `len(decorators) == len(functions) == 6` → `== 7` (`fetch_devices`); a checagem de `ttl` e `max_entries` em cada decorador continua | §4.5 ("lido com o mesmo cache das outras leituras") | não (§10) |
| `edge/tests/acceptance/test_spec_009.py` | `test_extra_cli_with_key_and_url_publishes_over_real_http` | conjunto de requisições permitidas `{POST batch, GET health}` → mais `("POST", HB_PATH)`, com a constante nova `HB_PATH = "/api/v1/devices/edge-01/heartbeat"` (o `DEVICE_ID` padrão); a conferência dos itens do contrato, que lia `json.loads(body)["items"]` em todo `POST`, passa a valer só para o `POST` do lote. A chave e o `Content-Type` continuam conferidos em todo `POST` | §4.4 (o `HeartbeatLoop` é registrado nas mesmas condições do `PublishLoop`) | não (§10) |
| `edge/tests/acceptance/test_spec_009.py` | `test_ca16_outbox_coverage_is_at_least_80_percent` | sem edição: falhava só porque roda o `test_spec_009.py` em subprocesso e o teste acima falhava; voltou a passar | §4.4 (efeito transitivo) | não |

Escolhi, no `test_spec_009.py`, aceitar o heartbeat em vez de pôr `HEARTBEAT_INTERVAL_S=0` no teste: assim o teste continua exercitando a configuração padrão da borda (a que o operador vai usar) e passa a provar que o heartbeat sai pelo mesmo HTTP real sem atrapalhar a entrega das inspeções. Nenhum ajuste contraria a SPEC-018.

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Todos passam (os nomes estão nos arquivos; resumo por área). Os achados que não são bug estão em "Observações".

**Contrato** (`packages/contracts`, 44): `MAX_HEARTBEAT_COUNT == 2_147_483_647` e `APP_VERSION_PATTERN == r"^[0-9A-Za-z.+-]{1,40}$"`, exportados em `__all__` com os dois schemas; `model_sha256` sem `model_version` (e `model_version` nulo com `sha` preenchido) recusado; cada contador aceita `0` e `MAX_HEARTBEAT_COUNT` e recusa `-1`, `MAX + 1`, `1.5` e `None`; todos os 7 campos são obrigatórios (nenhum tem padrão na SPEC); `app_version` aceito em `0.0.0`, `1`, `1.0.0+build-7`, `v2.3-rc.1`, 40 caracteres e `0.5.0+g1a2b3c`, e recusado (no schema e com `re.fullmatch`) em vazio, 41 caracteres, espaço, `_`, `/`, `versão`, tab, `\n` no início, `\x00` e dígito de largura total; `re.match` deixaria passar `"1.0\n"` e `re.fullmatch` não (architecture.md §3.2); `model_version` e `model_sha256` seguem as regexes do contrato (maiúsculas, 2 caracteres, `sha` maiúsculo, com 63 caracteres, não hexadecimal, `\n` no fim → recusados); `sent_at` com `-03:00` é normalizado para UTC sem mudar o instante; 4 min no futuro e uma data de 2020 são aceitos; `outbox_dead=True` vira `1` (modo lax, §7, sem CA); `HeartbeatCreate` sem campo de imagem nem de dispositivo (R-02); `DeviceStatus` com os 11 campos, ida e volta JSON, `last_heartbeat_at` em UTC, chave desconhecida ignorada (`extra="ignore"`), dispositivo sem nada (todos os opcionais nulos) válido, `last_source="fake"` recusado; `InspectionCreate` com os mesmos 14 campos e `extra="forbid"` (nenhum schema existente mudou).

**Banco e API** (44, banco real): as 8 colunas novas com os tipos da §4.2, todas anuláveis, e nenhuma outra coluna em `devices`; o banco recusa com `23514` `hb_outbox_pending`/`hb_outbox_dead` negativos, `hb_app_version` com `\n` no fim, vazio, 41 caracteres, espaço, `versão` e dígito de largura total, `hb_model_version` fora da regex (maiúsculas, `\n` no fim), `hb_model_sha256` maiúsculo ou com 63 caracteres e `sha` sem versão; o banco aceita os limites do contrato (`MAX_HEARTBEAT_COUNT`, 40 caracteres, par nulo); a migração `004` roda **mais duas vezes** direto no banco migrado sem erro, sem criar `check` novo e sem perder o heartbeat gravado; a `004` é o próximo número livre. Heartbeat com `sent_at` de janeiro de 2026: `last_heartbeat_at` e `last_seen_at` ficam na hora do servidor (entre o antes e o depois da requisição), `hb_sent_at` guarda o valor da borda e o dispositivo aparece `online` (o relógio da borda não decide nada); todos os campos do corpo vão para as colunas `hb_*` e voltam no `GET`; um segundo heartbeat sem modelo sobrescreve e limpa o par do modelo; 422, 403 e 401 não mexem em `last_seen_at` nem em `last_heartbeat_at`; `sent_at` sem fuso, `uptime_s` acima do teto, `outbox_dead=-1`, `app_version` com `\n`, `model_sha256` nulo com versão, campo `image` e `sent_at` 6 min no futuro → 422 sem `Traceback`; `not json` → 422; precedência da SPEC-004 (sem chave + corpo inválido → 401; chave de outro dispositivo + corpo inválido → 422); corpo de 300 KB → 413 sem gravar; `device_id` do caminho `ab`, 33 caracteres, `edge_01`, `edge-01%0A` e `Edge-01` → 422; dispositivo não registrado no caminho → 403; a chave de leitura não envia heartbeat (401); chave de leitura errada ou vazia → 401; nenhuma chave de dispositivo, hash de chave ou chave de leitura no log; com 513 dispositivos, a lista tem 500, na ordem de `device_id`, os 500 primeiros; lista vazia → `[]`; `last_source` segue o `received_at` (uma `live` atrasada, com `inspected_at` de 3 dias antes, recebida por último, vence); inspeção por `/inspections/batch` também define `last_source` e preenche `last_seen_at`, mas não torna o dispositivo `online` (inspeção não é heartbeat); as duas rotas aparecem no OpenAPI, o `POST` com resposta 204.

**Borda** (29): corpo só com os 7 campos do contrato (sem imagem nem dado pessoal, R-02), `app_version == qc_edge.__version__`, `Content-Type: application/json`; `uptime_s` pelo relógio monotônico injetado (7.500,9 s → 7500) e limitado a `MAX_HEARTBEAT_COUNT`; `sent_at` em UTC e atual; cada ciclo lê o outbox de novo (2 → 3 pendentes); `stop()` não espera o intervalo de 3.600 s e nada é enviado depois dele; com 401 na thread, uma única requisição e um único `ERROR`; intervalo `0` ou negativo recusado no construtor; `send_heartbeat`: 200, 201, 404, 500, 502, `ConnectError` e `ReadTimeout` → `PublishTransientError`, 401 e 403 → `PublishAuthError`, 204 → `None`; o corpo de um 422 (com `input` marcador), de um 500 e de um 413 nunca aparece na exceção nem no log, e a chave citada numa mensagem de rede é removida da exceção e do log; redirecionamento 307 para outro host não é seguido; resposta de 600 KiB → `PublishTransientError` (teto da SPEC-030); o heartbeat nunca grava no outbox (204, rede fora e 401); `HEARTBEAT_INTERVAL_S` aceito em `10`, `3600` e `60` (o laço fica com esse intervalo), padrão `60`; recusado com código 2 em `9`, `3601`, `-1`, `60.5`, `1e3`, `0x10` e `sessenta`; a mensagem cita `HEARTBEAT_INTERVAL_S` e nunca o valor (marcador), com e sem `--stub-model`; sem `CLOUD_API_URL`, nenhum laço; sem `MODEL_DIR`, o laço é registrado mesmo assim (o heartbeat leva os nulos). **Ponta a ponta por HTTP real** (`qc_edge.cli.main` com uma nuvem local em `127.0.0.1`): o primeiro heartbeat chega na subida e a nuvem **segura a resposta**; enquanto isso, 3 capturas são entregues pelo `PublishLoop` (pendentes = 0 antes de a nuvem soltar o heartbeat), cada inspeção chega uma única vez (nenhuma duplicata), os lotes têm exatamente os 3 ids, o heartbeat leva a chave e o `model_version` do modelo carregado, e a chave não aparece no log. Repeti os testes da borda, do dashboard e do contrato 5 vezes seguidas, sem falha intermitente.

**Dashboard** (22): as 9 colunas da §4.5 na ordem, todas como texto; `Modelo`, `Versão`, `Pendentes` e `Com falha` do heartbeat; `Origem` pelo `SOURCE_LABELS_PT` (`real`, `simulado`) e `—` sem inspeção; `Último sinal` em hora local (13:00 UTC → 10:00); dispositivo `offline` com heartbeat antigo mostra a hora do último sinal, não `nunca`; `Ligado há` em 0, 59, 60, 3.599, 3.600, 7.500 e 90.000 s (`25 h 00 min`, sem dias); lista vazia → nenhuma linha; `ApiClient.devices()` faz um `GET /api/v1/devices` com a chave de leitura e devolve `DeviceStatus`; `data.fetch_devices()` usa o cache (duas chamadas, uma requisição); página "Dispositivos" com a tabela, `online`/`offline`, `simulado`, `nunca` e o selo `Contém dados simulados` (R-06); sem dispositivo simulado, sem selo; sem dispositivo, sem tabela e com aviso; API com 401 ou 503 → mensagem (erro ou o aviso de "API acordando" da SPEC-013), sem tabela e sem a chave na tela; o `app.py` lista a página; nenhum código cru (`live`, `simulated`) na tabela.

## SPEC_ISSUE

Nenhum.

## Observações (não bloqueiam)

- **`infinity` em `devices.last_heartbeat_at` (ou `last_seen_at`) derruba o `GET /api/v1/devices` com 500** (confirma a observação 2 do dev report). Reproduzido no `partqc_test`: `update devices set last_heartbeat_at = 'infinity'` (ou `'-infinity'`) e `GET /api/v1/devices` com a chave de leitura → 500 `{"detail": "Internal server error"}`; o log segue a regra do §4 (`type=DatetimeFieldOverflow sqlstate=22008`, sem valores). Só acontece com uma linha escrita fora da API (SQL Editor), porque a API grava `now()`. Do mesmo jeito, um `last_heartbeat_at` no futuro escrito à mão deixa o dispositivo `online` até essa hora passar mais 180 s. A SPEC não pede `check` de faixa nessas colunas (a §4.2 lista as `check` e não inclui datas), então não registro como bug; fica como sugestão ao architect: a mesma faixa da `002` em `inspections` (`>= 0001-01-01` e `< 10000-01-01`), talvez também `last_heartbeat_at <= now() + MAX_FUTURE_SKEW`, se a SPEC quiser.
- **`HEARTBEAT_INTERVAL_S` no modo lax do Pydantic:** `60.0`, `+60`, `060`, ` 60 `, `1_000` e `3600.0` são aceitos como os inteiros correspondentes, e `0.0` e `-0` desligam o heartbeat como `0`; `60.5`, `1e3`, `0x10`, `٦٠` e `true` saem com 2. Todos os aceitos são inteiros na faixa ("inteiro de 10 a 3.600; 0 desliga"), então não é bug; o README diz só "inteiro".
- **`Ligado há` de um dispositivo offline:** mostra o `uptime_s` do último heartbeat (ex.: `2 h 05 min`), mesmo com o dispositivo desligado há horas. A SPEC só define `—` "sem heartbeat", e a coluna `Situação` deixa claro que está `offline`; é uma nota de interface para a dupla (CA-13).
- **`docs/architecture.md`** (architect, Definição de pronto): a linha "Arquivos vigentes" das "Expectativas de versão" (§10) ainda cita `packages/contracts/tests/acceptance/test_spec_016.py` (0.4.0); com o `ALLOWED_EXACT` deste commit, o arquivo vigente do `qc-contracts` passa a ser `test_spec_018.py` (0.5.0). Também ficam desatualizados o título e a linha de versões do §3, o esquema de `devices` do §5 e a lista do §6.4 (`HEARTBEAT_INTERVAL_S`), como o dev report já aponta.
- **Docstring de `packages/contracts/tests/acceptance/test_spec_016.py`:** ainda diz que aquele arquivo é a SPEC vigente do `qc-contracts`. Não mudei, porque o §10 só autoriza converter as asserções exatas ("e nada mais"); o precedente da SPEC-016 também não mexeu na docstring do `test_spec_026.py`. A docstring do `test_spec_018.py` assume o papel.
- **Constante sem uso:** `SPEC016_CONTRACTS` em `api/tests/acceptance/test_spec_004.py` ficou sem uso depois da troca no `ALLOWED_EXACT`, como a `SPEC026_CONTRACTS` ficou na SPEC-016; o ruff não acusa (constante de módulo).

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
