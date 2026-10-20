# SPEC-030 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-030](../../docs/specs/SPEC-030-manutencao-borda-publisher-privacidade.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-030-manutencao-borda` |
| Commits | `f3571e3`, `9ee49b0`, `aa2cdc1`, `51b576a`, `bf66151` (mais o commit deste relatório) |

## Resumo

- **§4.1:** o `HttpPublisher` passa a usar `client.stream(...)` e lê o corpo com `iter_bytes()` só em 2xx, 413 e 422. Depois de cada bloco confere o prazo total (15 s, pelo `monotonic` injetável) e o teto (512 KiB). Ao estourar, fecha a resposta e levanta `PublishTransientError` com as mensagens fixas `request deadline exceeded` ou `response too large`. Os outros status e o `check_health` (também por `stream`) não leem o corpo. `deadline_s` e `max_response_bytes` não positivos dão `ValueError`.
- **§4.2:** `fetch_due(limit, *, max_delay_s=60.0)` devolve também os `pending` com `next_attempt_at > now + max_delay_s`, com o SQL parametrizado e a ordem mantida. O `PublishLoop` chama `fetch_due` com `max_delay_s=MAX_DELAY_S`. O health check ocioso roda também quando `now` é anterior ao último contato.
- **§4.4/§4.5:** a varredura confere `.jpg`/`.jpeg` em qualquer caixa e marca como `invalid`, sem ler, qualquer outro arquivo regular de `raw/`. Ignora os temporários `.*.tmp` da borda. Todo caminho no stdout e nos logs passa por `printable_path`, e um arquivo ilegível sai como `<caminho>: unreadable` (código 1).
- **§4.3:** a URL com credencial do `test_cli_cloud.py` é montada em tempo de execução, com a senha de `secrets`. O `test_publisher_real_api.py` usa um `httpx.BaseTransport` próprio (`TestClientTransport`) que encaminha as requisições pela API pública do `TestClient`.
- `edge/README.md` atualizado nas seções "Modo coleta" (item 3) e "Envio para a nuvem".

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `edge/src/qc_edge/publisher.py` (`HttpPublisher.publish_batch`, `_read_body`) | `edge/tests/test_publisher.py::test_a_slow_body_exceeds_the_deadline`, `::test_a_body_within_the_deadline_is_read`, `::test_the_deadline_is_configurable` |
| CA-02 | `edge/src/qc_edge/publisher.py` | `edge/tests/test_publisher.py::test_a_body_above_the_cap_is_too_large`, `::test_a_body_of_exactly_the_cap_is_read`, `::test_the_cap_is_configurable`, `::test_a_large_422_still_gives_the_summary`, `::test_a_refusal_above_the_cap_is_transient`, `::test_deadline_and_cap_must_be_positive`, `::test_other_statuses_never_read_the_body`, `::test_check_health_never_reads_the_body`, `::test_a_network_error_while_reading_is_transient`, `::test_defaults_of_the_deadline_and_the_cap` |
| CA-03 | `edge/src/qc_edge/publisher.py`, `edge/src/qc_edge/publish_loop.py` (sem mudança no tratamento do transitório) | `edge/tests/test_publish_loop.py::test_a_deadline_is_a_retry_and_nothing_is_lost` |
| CA-04 | `edge/src/qc_edge/outbox.py` (`fetch_due`), `edge/src/qc_edge/publish_loop.py` (`run_once`) | `edge/tests/test_publish_loop.py::test_a_retry_is_not_held_by_a_clock_jump_back`; `edge/tests/test_outbox.py::test_fetch_due_returns_a_row_scheduled_beyond_the_longest_delay`, `::test_fetch_due_after_the_clock_jumped_back`, `::test_fetch_due_never_returns_sent_or_dead_rows_after_a_jump`, `::test_default_max_delay_matches_the_backoff_cap` |
| CA-05 | `edge/src/qc_edge/publish_loop.py` (`_maybe_check_health`) | `edge/tests/test_publish_loop.py::test_a_health_check_after_a_clock_jump_back` |
| CA-06 | `edge/tests/test_cli_cloud.py` (do autor). Os literais restantes estão em `edge/tests/acceptance/test_spec_009.py` e são do tester (§4.6) | `edge/tests/test_cli_cloud.py::test_invalid_cloud_url_exits_2[credentials]` |
| CA-07 | `edge/tests/test_publisher_real_api.py` (`TestClientTransport`, sem `._transport`) | os 3 testes do arquivo: `3 passed` com `TEST_DATABASE_URL` |
| CA-08 (manual) | idem | Ver "Como rodar e verificar" (verificação prévia com `httpx2`, sem o extra `train`) |
| CA-09 | `edge/src/qc_edge/privacy.py` (`is_jpeg_name`, `is_edge_temporary`, `_files`, `scan`) | `edge/tests/test_privacy.py::test_any_case_jpeg_is_checked_and_other_files_are_invalid`, `::test_fix_keeps_names_and_leaves_other_files`, `::test_only_edge_temporaries_are_ignored`, `::test_symlinks_to_other_files_are_ignored`, `::test_invalid_images_are_reported_and_never_rewritten` (ajustado) |
| CA-10 | `edge/src/qc_edge/privacy.py` (`printable_path`, `ImageFinding.line`, `scan`, `_fix`) | `edge/tests/test_privacy.py::test_printable_path` (tabela), `::test_printable_path_output_has_no_escapable_character`, `::test_a_hostile_name_cannot_forge_lines`, `::test_a_name_that_is_not_utf8_is_escaped`, `::test_cannot_fix_logs_the_escaped_path` |
| CA-11 | `edge/src/qc_edge/privacy.py` (`scan`, ramo `OSError`) | `edge/tests/test_privacy.py::test_an_unreadable_file_is_listed` |
| CA-12 | só no teste de aceite (`_collected` de `test_spec_025.py`, do tester, §4.6) | — |

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1).

## Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest -q edge/tests --ignore=edge/tests/acceptance
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test \
  uv run pytest -q edge/tests/test_publisher_real_api.py           # 3 passed
```

Verificação prévia do problema do `httpx2`, sem instalar o extra `train`. O ambiente temporário do `uv run --with` não muda o `uv.lock` nem o `.venv`, e nele o `starlette.testclient` passa a importar o `httpx2` (conferido com `starlette.testclient.httpx.__name__ == "httpx2"`):

```bash
CI=true TEST_DATABASE_URL=<url do banco de teste> \
  uv run --no-sync --with httpx2 python -m pytest -q edge/tests/test_publisher_real_api.py -p no:cacheprovider
```

- versão nova do teste: `3 passed`;
- versão anterior (`git show 84045fc:edge/tests/test_publisher_real_api.py`, copiada para um arquivo temporário e apagada em seguida): `3 failed`, a falha relatada na SPEC-011.

O CA-08 manual, com o extra `train`, continua com o tester.

Suíte inteira (`CI=true TEST_DATABASE_URL=... uv run pytest -q`): `1 failed, 5626 passed, 52 skipped`. A única falha está listada abaixo e decorre de requisito desta SPEC.

## Testes de aceite de SPECs anteriores afetados (ajuste do tester, §4.6)

| Arquivo | Teste | Situação | Requisito |
|---|---|---|---|
| `edge/tests/acceptance/test_spec_025.py` | `test_extra_privacy_invalid_file_and_odd_entries` | **falha**: a última linha passa a ser `checked 6 images, 5 with private data` (antes, `checked 4 images, 3 with private data`) | §4.4 (`upper.JPG` varrido, `notes.txt` como `invalid`); ajuste previsto na §4.6, item 2 |
| `edge/tests/acceptance/test_spec_025.py` | `_collected` (CA-12) | passa hoje; a remoção de `PYTEST_ADDOPTS`, `PYTEST_PLUGINS` e `PYTEST_CURRENT_TEST` é do tester | §4.6, item 2 (RV-08) |
| `edge/tests/acceptance/test_spec_009.py` | linhas 1035 e 1058–1059 (URL com credencial literal) | passa hoje, mas é a única ocorrência que resta para o CA-06 | §4.3, item 1, e §4.6, item 1 |

## Decisões tomadas dentro do escopo da SPEC

- **Fechamento da resposta antes de levantar:** o `_read_body` chama `response.close()` antes de levantar o prazo ou o teto. Os status que não leem o corpo saem do bloco `with client.stream(...)`, que fecha a resposta, e só depois levantam a exceção.
- **Ordem das conferências:** depois de cada bloco, o prazo é conferido antes do teto. Um bloco que estoura os dois dá `request deadline exceeded`.
- **`check_health` com `stream`:** o `client.get` lia o corpo inteiro, o que contrariava o "não lê o corpo" da §4.1. Agora o método só olha o status.
- **`DEFAULT_MAX_DELAY_S = 60.0` em `qc_edge.outbox`:** é o padrão de `fetch_due`, porque o `outbox` não pode importar o `publish_loop` (o import seria circular). O `PublishLoop` passa `MAX_DELAY_S` de forma explícita, e `test_default_max_delay_matches_the_backoff_cap` garante que as duas constantes são iguais.
- **Temporários:** a exceção exige o prefixo `.` e o sufixo exato `.tmp`, em minúsculas, que é o que o `mkstemp` da borda gera. `.x.TMP` e `x.jpg.tmp` continuam como `invalid`.
- **Contagem do não JPEG:** entra em `n` e em `k`. Os arquivos ilegíveis ficam fora das duas contagens, como a §4.5 manda.
- **README, item 3:** não criei procedimento novo para o `invalid`. O texto remete ao item 2 (apagar e registrar em `exclusions.csv`), conforme a §7 da SPEC.
- **Teste do nome não UTF-8:** roda `python -m qc_edge.privacy` em subprocesso (só a CLI, nunca o pytest), para provar que não há `UnicodeEncodeError` no stdout real. O teste é pulado se o sistema de arquivos recusar o nome.

## Observação para o security-devops (fora do escopo, sem ação minha)

- **Teto e compressão:** o teto de 512 KiB vale para os bytes **decodificados** (`iter_bytes`, como a SPEC pede). O `httpx` envia `Accept-Encoding: gzip, deflate` por padrão e descomprime cada bloco recebido de uma vez. Um servidor hostil com `Content-Encoding: gzip` pode fazer um único bloco de 64 KiB virar dezenas de MiB na memória antes da primeira conferência. O risco é baixo, porque a URL é só HTTPS ou loopback e o servidor é a própria API. Se quiserem fechar, uma SPEC futura pode mandar `Accept-Encoding: identity` ou limitar pelo `iter_raw`. Não mudei nada, porque isso alteraria a requisição além do que a §4.1 define.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (inclusive os 3 de `test_publisher_real_api.py` com o banco)
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
