# SPEC-025 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-025](../../docs/specs/SPEC-025-manutencao-borda-host-rede.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-025-manutencao-borda` |
| Commits | `7074ead`, `301ee48`, `8f4aee3`, `874d5f0` (+ o commit deste relatório) |

## Resumo

- O console só responde com **um** header `Host` de loopback (`is_allowed_console_host`), checado antes de `detect_lan_ips()` e de qualquer render. O log da recusa só diz o motivo.
- O `POST /api/capture` passou a ser `async`. A espera pelo slot é um `anyio.Semaphore` aguardado no event loop, com `move_on_after(decode_wait_s)`. O trabalho bloqueante roda numa única chamada `anyio.to_thread.run_sync`, e o slot é liberado no `finally`.
- `EDGE_HOST` só aceita IPv4 literal. A CLI sai com código 2 diante de argumento desconhecido e registra só os nomes de opção.
- Modos exatos `0700`/`0600` para `EDGE_DATA_DIR` (quando criado), `captures/`, as pastas de dia e as fotos.
- Modo coleta:
  - JPEG gravado sem APP1, APP13, COM e trailer, por varredura estrutural e sem reencode;
  - 415 quando a estrutura não pode ser percorrida;
  - `fsync` dos diretórios;
  - `notes` recusa `Cf`/`Zl`/`Zp`, e `capture_device` troca esses caracteres por espaço antes do corte.
- CLI nova `python -m qc_edge.privacy` (varredura e `--fix`).
- `edge/README.md` e `.env.example` atualizados.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `edge/src/qc_edge/security.py` (`is_allowed_console_host`), `edge/src/qc_edge/app.py` (`_is_local_console_request`) | `edge/tests/test_pages.py::test_console_accepts_loopback_hosts`, `edge/tests/test_security.py::test_is_allowed_console_host` |
| CA-02 | idem | `test_pages.py::test_console_refuses_other_hosts_before_detecting_ips`, `test_pages.py::test_console_needs_exactly_one_host_header` (ASGI cru: sem `Host`, vazio, dois `Host`), `test_pages.py::test_proxy_header_is_still_refused_with_a_loopback_host` |
| CA-03 | `security.py` | `test_pages.py::test_console_on_port_80`, `test_security.py::test_is_allowed_console_host` (casos `None` e `""`) |
| CA-04 | `app.py`, `cli.py` | Sem teste unitário (é o CA de servidor real do tester). Conferido à mão: `qc-edge --stub-model` em `127.0.0.1`, porta livre e `EDGE_DATA_DIR` temporário. Resultados: `Host: attacker.example:<p>` → 403; `Host` padrão → 200 com `<svg`; `localhost:<p>` → 200. O valor do `Host` não aparece no log. Processo encerrado no fim. |
| CA-05 | `app.py` (as rotas com token não mudaram) | `test_pages.py::test_token_routes_do_not_check_the_host` |
| CA-06 | `edge/src/qc_edge/config.py` (`_ipv4_literal`) | `test_lifespan_cli.py::test_ipv6_or_name_edge_host_exits_2`, `test_config.py::test_edge_host_must_be_an_ipv4_literal`, `test_config.py::test_edge_host_ipv4_literals_are_accepted`, `test_lifespan_cli.py::test_main_runs_uvicorn_without_proxy_headers` |
| CA-07 | `app.py` (`capture` async, `anyio.Semaphore`, `move_on_after`, `to_thread.run_sync`) | `test_limiter.py::test_waiting_requests_do_not_block_status` (1 slot + 45 em espera, `/api/status` < 1 s, 503 em ≤ `decode_wait_s` + 2 s, `infer` sem event loop na thread, máximo de 1 simultâneo, 1 item no sink, 1 `.jpg`) |
| CA-08 | `app.py` (`limits.load_capture_image` resolvido no módulo na hora da chamada) | `test_limiter.py::test_blocking_work_never_runs_on_the_event_loop` (captura, GIF 415 e coleta), `test_limiter.py::test_slot_is_released_after_errors`, `test_limiter.py::test_the_limiter_is_an_anyio_semaphore_shared_by_both_modes`, `test_collect_route.py::test_collect_uses_the_decode_limiter` |
| CA-09 | `edge/src/qc_edge/fsutil.py`, `config.py`, `app.py` (`_CaptureStore.prepare`/`save`) | `test_capture_route.py::test_capture_modes_are_exact_whatever_the_umask` (umask `0o022`, `0o077`, `0o000`, `0o277`), `test_capture_route.py::test_existing_data_dir_is_kept_and_captures_becomes_0700`, `test_capture_route.py::test_without_lifespan_the_first_capture_creates_captures_0700`, `test_capture_route.py::test_chmod_failure_on_a_capture_is_a_warning`, `test_capture_route.py::test_an_existing_photo_is_never_overwritten` |
| CA-10 | `edge/src/qc_edge/cli.py`, `edge/src/qc_edge/argv.py` | `test_lifespan_cli.py::test_unknown_arguments_exit_2_without_values`, `test_lifespan_cli.py::test_argparse_errors_never_echo_the_value`, `test_lifespan_cli.py::test_help_still_exits_0`, `test_lifespan_cli.py::test_stub_model_flag`, `test_lifespan_cli.py::test_main_without_argv_reads_sys_argv` |
| CA-11 | `edge/README.md`, `.env.example` | Sem teste unitário (o CA é do tester). Conferi as 6 condições do CA com um script descartável: todas atendidas. |
| CA-12 | N/A para o autor (docstrings de `tests/acceptance/`, §4.7 itens 2 e 3: tester) | — |
| CA-13 | `edge/src/qc_edge/collect.py` (`dataset_image_bytes`, `DatasetWriter.write`), `edge/src/qc_edge/jpeg.py` | `test_collect_route.py::test_metadata_is_removed_from_the_stored_jpeg`, `test_collect.py::test_metadata_jpeg_is_stored_clean`, `test_collect.py::test_clean_jpeg_is_stored_byte_for_byte`, `test_collect_route.py::test_collect_success_without_model` (Pillow, byte a byte), `test_capture_route.py::test_inspect_mode_keeps_the_jpeg_as_received` |
| CA-14 | `jpeg.py` (`strip_private_segments`, `jpeg_private_findings`, `JpegStructureError`) | `edge/tests/test_jpeg.py` (26 testes): metadados, `FF D9` dentro de APP1/COM/APP13, ICC e Adobe mantidos, preenchimento, RSTn e `FF 00`, progressivo com vários SOS, TEM, COM depois do scan e 14 erros estruturais sem bytes na mensagem |
| CA-15 | `edge/src/qc_edge/privacy.py` | `edge/tests/test_privacy.py` (21 testes): leitura sem `--fix`, `--fix` com umask `0o022` e `0o277`, link simbólico ignorado, `invalid`, falha do `os.replace`, espera pelo `flock` da coleta, erros de uso com código 2 sem eco, sem rede, `python -m` |
| CA-16 | `collect.py` (`UnsupportedJpegStructureError`; `jpeg.strip_private_segments` resolvido no módulo) | `test_collect_route.py::test_unsupported_structure_is_415_and_releases_the_slot`, `test_collect.py::test_unwalkable_jpeg_is_415_before_touching_the_disk`, `test_collect.py::test_png_is_never_walked` |
| CA-17 | `fsutil.py` (`fsync_dir`, `make_private_dirs(sync=True)`), `collect.py` (`write_private_file_atomically`, `_append`) | `test_collect.py::test_directories_are_synced_in_order`, `test_collect.py::test_existing_manifest_is_not_followed_by_a_directory_sync`, `test_collect.py::test_directory_sync_failures_are_warnings`, `test_collect.py::test_fsync_dir_open_failure_is_a_warning` |
| CA-18 | `collect.py` (`FORBIDDEN_TEXT_CATEGORIES`, `capture_device_from_user_agent`), `app.py` | `test_collect_route.py::test_notes_with_separators_or_bidi_are_422`, `test_collect_route.py::test_raw_user_agent_controls_become_spaces` (ASGI cru, `b"Phone\x85X\tY" + b"z" * 70`), `test_collect.py::test_notes_refuse_separators_and_format_characters`, `test_collect.py::test_capture_device_replaces_controls_before_the_cut`, `test_collect.py::test_manifest_has_one_line_per_record` |

## Testes de aceite de SPECs anteriores que falham (para o tester, `docs/architecture.md` §10)

Não toquei em `**/tests/acceptance/**`. Com esta implementação, 6 testes falham, todos em `edge/tests/acceptance/test_spec_007.py`. Todos são casos previstos na §4.7, item 1, da SPEC:

| Teste | Por que falha | Requisito que o invalida |
|---|---|---|
| `test_ca02_generated_tokens_are_long_urlsafe_and_distinct` | `_console_token` lê o token do console via `asgi_get`, com a URL base `http://testserver` (`Host: testserver`) → 403 | §4.1 (`Host` de loopback); §4.7, item 1, 1º marcador |
| `test_ca13_console_from_loopback` | idem (`asgi_get`) → 403 | idem |
| `test_ca18_no_candidate_falls_back_to_loopback_with_console_warning` | idem | idem |
| `test_extra_console_ip_parameter_only_accepts_detected_ips` | idem | idem |
| `test_extra_console_accepts_ipv6_loopback` | idem (cliente `::1`, `Host: testserver`) | idem |
| `test_extra_configuration_boundaries_are_accepted` | `EDGE_HOST="::"` agora sai com código 2 | §4.3 (só IPv4); §4.7, item 1, 3º marcador |

- `test_spec_010.py`, `tests/acceptance/test_spec_022.py` e `packages/contracts/tests/acceptance/test_spec_023.py` passam sem ajuste (§4.7, item 4, confirmado).
- Nenhuma chamada a `qc_edge.cli.main()` dos testes de aceite herda os argumentos do pytest: o `run_main` do `test_spec_007.py` já faz `monkeypatch.setattr(sys, "argv", ...)`.

Testes do autor ajustados (permitidos pela §3.1):

- `test_pages.py`, `test_collect_route.py` e `test_lifespan_cli.py`: as chamadas ao console passaram a usar a URL base `http://127.0.0.1:8000`.
- `test_config.py::test_ipv6_host_literal_is_accepted` virou `test_edge_host_must_be_an_ipv4_literal` (+ `test_edge_host_ipv4_literals_are_accepted`).
- `test_lifespan_cli.py::test_unknown_arguments_are_ignored` virou `test_unknown_arguments_exit_2_without_values`.
- `test_limiter.py` e `test_collect_route.py`:
  - o espião de `load_capture_image` passou a ficar em `qc_edge.limits`;
  - os testes com threads concorrentes passaram a usar `with TestClient(app)` (um único event loop; ver as decisões abaixo).

## Como rodar e verificar

```bash
uv sync --all-packages
uv run pytest -q edge/tests --ignore=edge/tests/acceptance      # 417 passed
uv run pytest -q edge/tests/acceptance                          # 229 passed, 6 failed (tabela acima)
uv run ruff check . && uv run ruff format --check .             # limpos (147 arquivos formatados)
env -u TEST_DATABASE_URL uv run pytest -q                       # 2822 passed, 643 skipped, 6 failed (os mesmos 6)
TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q   # 3465 passed, 6 failed (os mesmos 6)
uv run --package qc-edge python -m qc_edge.privacy --dataset-dir <D> [--fix]
```

## Decisões tomadas dentro do escopo da SPEC

1. **Dois módulos internos novos**, fora da lista da §3.1, sem mudança de contrato nem de comportamento externo:
   - `qc_edge/fsutil.py`: modos exatos, criação exclusiva com `0600` e `fsync_dir`. O `_set_mode`/`_make_dirs`/`_open_file` do `collect.py` foram movidos para cá, porque `config.py`, `app.py`, `collect.py` e `privacy.py` usam a mesma regra.
   - `qc_edge/argv.py`: parser que nunca imprime erro, mais `describe_arguments` (a regra de não eco da §4.5), usado pelo `cli.py` e pelo `privacy.py`.
2. **Pontos de substituição dos CAs:**
   - `app.py` chama `limits.load_capture_image` e `collect.py` chama `jpeg.strip_private_segments`, os dois resolvidos no módulo na hora da chamada, para que os espiões do CA-08 (`qc_edge.limits.load_capture_image`) e do CA-16 (`qc_edge.jpeg.strip_private_segments`) tenham efeito;
   - o `os.fsync` é chamado sempre como `os.fsync` (CA-17).
3. **Onde a remoção acontece:** em `DatasetWriter.write`, antes de qualquer acesso ao disco. Assim, o 415 do CA-16 não cria nem o `DATASET_DIR`. Continua dentro do slot e da mesma chamada `to_thread.run_sync`.
4. **`EDGE_DATA_DIR` com pais inexistentes:**
   - todos os diretórios criados pelo `qc-edge` recebem `0700`, como o `DATASET_DIR` da SPEC-010, e não só o `EDGE_DATA_DIR`;
   - sem isso, com `umask 0o277`, o `mkdir(parents=True)` cria os pais com `0500` e a criação do filho falha;
   - um diretório que já existia não é alterado.
5. **`captures/` na subida:** se a criação falhar (por exemplo, disco só leitura), o `qc-edge` registra um `WARNING` e sobe mesmo assim. O modo coleta não precisa de `captures/`, e a primeira gravação de inspeção responde 500. A SPEC só define o caso do `chmod`.
6. **Erros do próprio `argparse`** (ex.: `--stub-model=x`, que o argparse ecoaria como "ignored explicit argument 'x'"):
   - saem com código 2 e `invalid command-line argument(s): <nomes>`, pela mesma regra de não eco;
   - `-h`/`--help` continua com código 0.
7. **Formato das listas:**
   - `unknown command-line argument(s): --stub-modle, --token, 1 other` (nomes, depois `N other`, separados por `, `);
   - na varredura, os achados são separados por `, ` e em ordem alfabética (`raw/x.jpg: app1, app13, com, trailer`).
8. **Saída do `--fix`:**
   - para cada arquivo com achado, sai a linha do achado e, se a correção deu certo, `fixed <caminho>`;
   - o resumo `checked n images, k with private data` conta os achados de antes da correção;
   - uma falha de E/S na reescrita gera um log de erro, deixa o original intacto, não deixa temporário e faz o código ser 1;
   - o `flock` é mantido durante a varredura inteira.
9. **Log da recusa do console:** só a recusa por `Host` gera o `WARNING` (`console refused: host not allowed`). As recusas por cliente e por header de proxy continuam como antes, sem log próprio.
10. **`anyio` declarado no `edge/pyproject.toml`** (`anyio>=4.15`), porque agora é importado diretamente. O `uv.lock` só ganhou a linha de dependência do `qc-edge`. Nenhum pacote novo foi resolvido (o anyio 4.15.1 já estava no lock via starlette/httpx).
11. **Semáforo e event loops:**
    - o `anyio.Semaphore` (backend asyncio) não é seguro entre event loops rodando **ao mesmo tempo** em threads diferentes;
    - em produção há um só loop (uvicorn), e `TestClient`s sucessivos com o mesmo app funcionam, como pede a §7;
    - já um `TestClient` usado **sem** `with` a partir de várias threads cria um loop por requisição, e por isso os testes concorrentes do autor usam `with TestClient(app)`;
    - os CA-22/CA-23 da SPEC-007 já usam `with`, e o CA-07 desta SPEC admite as duas formas que funcionam (threads com `TestClient` em contexto ou `AsyncClient` num único loop).
12. **Firewall:** a sintaxe do `nft` (`add`/`insert` com `ip saddr`, `-a list` e `delete ... handle`) foi conferida num namespace de rede sem privilégio (`unshare -rn`). O ufw e o firewalld não estão instalados neste notebook. Os comandos deles seguem a sintaxe das man pages citadas na §4.6 e **não foram executados aqui**.

## Observações para o architect (não bloqueiam; não são SPEC_ISSUE)

- **O-01 (§4.9, `*.jpg`):**
  - a varredura confere só arquivos terminados em `.jpg` (minúsculo), como diz a SPEC;
  - uma foto copiada à mão como `IMG_0001.JPG` ou `.jpeg` não é conferida e iria para o backup com os metadados;
  - o `edge/README.md` diz que a varredura confere os arquivos `*.jpg`;
  - se quiser fechar o caso, uma emenda pode aceitar `.jpg`/`.jpeg` sem diferenciar maiúsculas (a SPEC-011 só lê o que está no manifest, e a coleta sempre grava `.jpg`).
- **O-02 (§4.9, `raw/` como link):**
  - o `os.walk(..., followlinks=False)` não segue links **dentro** de `raw/`;
  - se o próprio `raw` for um link para um diretório, o `os.walk` o percorre, porque o topo é sempre listado;
  - mantive esse comportamento: ignorar o topo daria "0 with private data" para um dataset inteiro, o que seria pior para a privacidade.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (417 em `edge/tests`, fora de `acceptance/`)
- [x] `.env.example` atualizado (nenhuma variável nova; comentários de `EDGE_HOST`, `EDGE_SESSION_TOKEN` e `EDGE_DATA_DIR`)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhum token, chave ou credencial como literal nos testes: tokens e marcadores gerados em tempo de execução (`secrets`), imagens geradas em memória, `DATASET_DIR`/`EDGE_DATA_DIR` sempre em `tmp_path`
- [x] Nenhum teste roda a suíte em subprocesso (o único subprocesso é `python -m qc_edge.privacy` sobre um diretório temporário)
- [x] R-02: nada novo faz conexão de rede (`test_privacy.py::test_no_network_connection`); nenhuma rota nova
