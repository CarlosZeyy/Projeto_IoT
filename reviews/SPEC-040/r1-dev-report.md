# SPEC-040 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-040](../../docs/specs/SPEC-040-manutencao-consolidada.md) |
| Rodada | r1 |
| Autor | developer (Parte A); ml-engineer (Parte B) e security-devops (Parte C) acrescentam as seções deles |
| Branch | `spec/SPEC-040-manutencao-consolidada` |

## Parte A (developer)

Commits: `3f463ce`, `e5b06a9`, `01e4c08`, `4e10ab1`, `882d39d`, `c8333a9`.

### Resumo

- **Publisher (§4.1):** toda requisição pede `Accept-Encoding: identity`. Antes de ler o corpo, um `Content-Encoding` fora de vazio/`identity` fecha a resposta e levanta `PublishTransientError("unsupported response encoding")`, inclusive em 413/422.
- **Varredura (§4.2):** diretório que não lista e nome sem `lstat` viram `<caminho>: unreadable`, com `ERROR` e código 1, na ordem dos caminhos. Só o nome exato do `mkstemp` com alvo JPEG é temporário.
- **Heartbeat (§4.3):** a falha ao montar registra só a classe, sem `exc_info`; `_cap(value: float) -> int`.
- **Painel (§4.4):** `is_secure_api_url` monta um `httpx.Request` sem enviá-lo. `get_client()` e `ApiClient._get` (agora `build_request` + `send`) convertem a falha de montagem em `InsecureApiUrlError`.
- **Alertas (§4.5):** `identity` no cliente, recusa de codificação sem ler o corpo e `abandoned_for_s` no aviso. A seção do `api/README.md` foi reescrita para o Coolify.

### Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `edge/src/qc_edge/publisher.py` | `edge/tests/test_publisher.py::test_every_request_asks_for_identity` |
| CA-02 | `edge/src/qc_edge/publisher.py` | `edge/tests/test_publisher.py::test_publish_batch_refuses_an_encoding_without_reading`, `::test_send_heartbeat_refuses_an_encoding_without_reading`, `::test_a_real_gzip_body_is_never_decompressed`, `::test_statuses_without_a_body_read_do_not_change`, `::test_check_health_ignores_the_encoding_and_never_reads` |
| CA-03 | `edge/src/qc_edge/publisher.py` | `edge/tests/test_publisher.py::test_empty_or_identity_is_read_as_before` (o laço com o outbox real fica para o aceite) |
| CA-04 | `edge/src/qc_edge/privacy.py` | `edge/tests/test_privacy.py::test_unreadable_folders_and_files_are_listed_in_path_order`, `::test_fix_rewrites_nothing_in_an_unreadable_folder`, `::test_an_unreadable_folder_name_is_escaped`, `::test_raw_itself_unreadable_is_listed`, `::test_raw_that_is_a_file_is_listed`, `::test_raw_absent_is_not_unreadable`, `::test_a_subfolder_that_vanishes_during_the_walk_is_listed`, `::test_a_relative_dataset_dir_gives_relative_lines`, `::test_a_failed_lstat_is_listed_and_not_counted`, `::test_an_error_without_strerror_logs_the_class` |
| CA-05 | `edge/src/qc_edge/privacy.py` | `edge/tests/test_privacy.py::test_only_edge_temporaries_are_ignored`, `::test_the_temporary_of_the_real_writer_is_ignored` |
| CA-06 | `edge/src/qc_edge/heartbeat.py` | `edge/tests/test_heartbeat.py::test_a_failure_to_build_logs_only_the_class`, `::test_the_loop_goes_on_after_a_failure_to_build`, `::test_cap_hints_and_behaviour` |
| CA-07 | `dashboard/src/qc_dashboard/config.py` | `dashboard/tests/test_config.py::test_nbsp_in_the_host_is_refused`, `::test_url_httpx_cannot_build_is_refused`, `::test_urls_httpx_can_build_are_still_accepted`; `dashboard/tests/test_pages.py::test_url_httpx_cannot_build_stops_the_overview` |
| CA-08 | `dashboard/src/qc_dashboard/api.py`, `dashboard/src/qc_dashboard/config.py` | `dashboard/tests/test_api.py::test_get_client_converts_an_invalid_url`, `::test_read_converts_a_url_that_only_fails_on_the_request`, `::test_a_body_that_is_not_json_is_not_a_config_error`, `::test_a_value_error_while_decoding_is_not_converted`, `::test_build_and_send_keep_the_timeout_and_the_key`, `::test_send_errors_are_still_unavailable`; `dashboard/tests/test_pages.py::test_defense_in_depth_shows_the_same_message_on_the_page` |
| CA-09 | `api/src/qc_api/services/alerts.py` | `api/tests/test_alerts.py::test_send_asks_for_identity`, `::test_send_refuses_an_encoding_without_reading`, `::test_send_accepts_empty_or_identity` (a linha em `alerts_sent` fica para o aceite, com banco) |
| CA-10 | `api/src/qc_api/services/alerts.py` | `api/tests/test_alerts.py::test_abandoned_for_s_is_the_truncated_age_of_the_oldest_alive`, `::test_abandoned_for_s_without_a_send_is_zero`; `api/tests/test_alerts_deadline.py` (formato do aviso e nova estrutura de `_abandoned_sends`) |
| CA-11 | `api/README.md`, `edge/README.md` | sem teste do autor (texto; o aceite é do tester) |
| CA-18 | manual, depois do deploy | não executado nesta parte; exige a VPS e a borda de produção |

### Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

Resultado da suíte inteira, com banco: **5 failed, 9096 passed, 143 skipped**, em 13min47s. As 5 falhas estão na próxima seção. `ruff check` e `ruff format --check` limpos. A cobertura de `qc_api.services` (RNF-09) não foi medida nesta parte.

### Testes de aceite de SPECs anteriores (ajuste do tester)

Conforme `docs/architecture.md` §10, não editei nenhum deles. Todas as falhas decorrem de requisito desta SPEC:

| Teste (`edge/tests/acceptance/test_spec_030.py`) | Por que falha | Requisito |
|---|---|---|
| `test_extra_ca02_cap_is_configurable_and_counts_decoded_bytes` | a segunda metade envia um corpo `gzip` e espera `response too large`; agora a resposta é recusada antes da leitura, com `unsupported response encoding`. Este caso não está na tabela de prováveis da §3.1 da SPEC | §4.1 |
| `test_ca09_any_case_jpeg_is_checked_and_other_files_are_invalid` | o fixture usa `.g.jpg.abc123.tmp` (6 caracteres), que passa a ser `invalid` | §4.2 |
| `test_extra_ca09_edge_temporaries_are_ignored[.a.jpg.abc.tmp]` | nome fora do formato do `mkstemp` | §4.2 |
| `test_extra_ca09_edge_temporaries_are_ignored[.tmp]` | idem | §4.2 |
| `test_extra_ca09_edge_temporaries_are_ignored[.x.tmp]` | idem | §4.2 |

As linhas 933, 946 e 972 do mesmo arquivo usam o mesmo nome `.g.jpg.abc123.tmp`; só o `test_ca09` acima falhou, mas o tester pode querer trocar o nome em todas. Os demais arquivos da tabela da §3.1 (`test_spec_017.py`, `test_spec_025.py`, `test_spec_029.py`, `test_spec_028.py`, `test_spec_013.py`, `test_spec_009.py`, `test_spec_018.py`) passam sem ajuste na suíte atual. O teste de `test_spec_017.py` confere o aviso por substring, então não exige mudança.

### Decisões tomadas dentro do escopo da SPEC

- **Conferência dentro de `_read_body`:** os dois métodos só leem corpo por ali, então nenhum caminho de leitura fica sem a conferência. O efeito é o da §4.1 (antes de qualquer leitura).
- **Conferência repetida em `qc_edge.publisher` e `qc_api.services.alerts`:** são 4 linhas sobre um header HTTP, não um payload do contrato, e os dois pacotes não têm um módulo HTTP comum.
- **`httpx.Request("GET", url)` no `is_secure_api_url`:** conferi as 5 URLs do CA-07 no `httpx` 0.28.1. As 4 com caractere inválido falham em `httpx.URL` (`InvalidURL`), e `https://xn--zz.com` falha com `idna.IDNAError` só na montagem, como descreve o SEC-29-01. As URLs aceitas continuam aceitas.
- **Só o `FileNotFoundError` do próprio `raw/` é "ausente":** uma subpasta que some durante a travessia sai como `unreadable` (código 1), e `raw` que é um arquivo também. A SPEC só isenta o `raw/` ausente, e falhar fechado é o seguro numa conferência antes do backup. Basta rodar de novo.
- **Idade do envio abandonado:** usa `time.monotonic()` direto, no abandono e no aviso. O `monotonic` injetável de `send_message` é o relógio do prazo do worker, e `run_check` não recebe relógio. `_abandoned_sends` passou a guardar `_AbandonedSend(thread, abandoned_at)`.
- **`api/README.md`:** além dos itens da §4.5, o passo 1 manda deixar `ALERTS_ENABLED=false` e fazer Redeploy ou Restart antes de ler o `chat_id`, como o `docs/deployment-plan.md` §8, item 5, porque o `docker exec ... printenv` só encontra o token depois disso.
- **Testes do autor ajustados:** os nomes de temporários de `edge/tests/test_privacy.py` passaram ao formato da §4.2, e `.tmp` e `.x.jpg.k3j2.tmp` agora esperam `invalid`. `api/tests/test_alerts_deadline.py` segue o novo aviso e a nova estrutura. O caso NBSP de `dashboard/tests/test_config.py` saiu da lista de aceitas e virou `test_nbsp_in_the_host_is_refused`, com o NBSP na URL.

### Observação (fora do escopo, sem ação)

`https://api.example.org x`, com espaço comum, continua aceita: o `httpx` a monta, com o host `api.example.org%20x`. A leitura termina em erro de conexão (`ApiUnavailable`), sem exceção na tela. A terceira URL do CA-07 tem U+2028 no lugar do espaço, e é essa que a SPEC exige recusar (conferi os bytes da SPEC).

### SPEC_ISSUE

Nenhum.

### Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando
- [x] `.env.example` sem mudança (nenhuma variável nova)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
