# SPEC-025 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-025](../../docs/specs/SPEC-025-manutencao-borda-host-rede.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `e316424` (código da r1: `7074ead`, `301ee48`, `8f4aee3`, `874d5f0`; branch `spec/SPEC-025-manutencao-borda`) |
| **Veredicto** | **PASS** |

Escrevi os testes a partir da SPEC (caixa-preta), antes de ler a implementação. Arquivo: `edge/tests/acceptance/test_spec_025.py`, com **133 testes coletados** (67 funções):

- 48 ligados aos 18 CAs (28 funções `test_caNN_*`);
- 85 exploratórios (39 funções `test_extra_*`).

Regras seguidas (`reviews/checklist.md` e `docs/architecture.md` §10):

- o token de sessão e todos os marcadores (COM, `--token=`, argumento posicional) são gerados em tempo de execução (`secrets`), sem credencial literal em URL, conninfo ou header;
- as imagens são geradas em memória (Pillow + bytes inseridos), nunca fotos reais (R-14);
- `EDGE_DATA_DIR` e `DATASET_DIR` ficam sempre em `tmp_path`, e a fixture faz `chdir` para um diretório temporário;
- nenhum teste roda a suíte em subprocesso. Os subprocessos são três:
  - o servidor real do CA-04 (`qc-edge --stub-model` em `127.0.0.1`);
  - o `pytest --collect-only` do CA-12, com os dois caminhos explícitos e sem `TEST_DATABASE_URL`;
  - um `python -m qc_edge.privacy` sobre um diretório temporário;
- as fronteiras simuladas são só as que a SPEC cita: `detect_lan_ips` (socket), `uvicorn.run`, os dublês de inferenciador e sink e, nos CA-08, CA-16 e CA-17, os espiões em `qc_edge.limits.load_capture_image`, `qc_edge.jpeg.strip_private_segments` e `os.fsync`;
- o `umask` é restaurado num `finally` (fixture `umask_guard`);
- os caracteres invisíveis (U+2028, bidi, U+00AD, NBSP) aparecem no código-fonte só como escapes (`" "`), nunca como literais.

## Cobertura dos critérios de aceite

Prefixo dos testes: `edge/tests/acceptance/test_spec_025.py::`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_console_answers_loopback_hosts[127.0.0.1:8000, localhost:8000, LOCALHOST:8000, [::1]:8000]`: 200, `<svg` e a URL de pareamento; o espião de `detect_lan_ips` foi usado | ✅ |
| CA-02 | `test_ca02_console_refuses_other_hosts_before_detecting_ips`: os 6 `Host` pela `ASGITransport` e, por ASGI cru, `Host` vazio, sem `Host` e dois `Host`. Os 9 dão 403 sem o token, o espião tem 0 chamadas e nenhum registro de log (texto, `msg` e `args`) contém `attacker.example`. Controle no fim: com `Host` de loopback, o mesmo espião é chamado, o que prova que o 0 não é tautológico | ✅ |
| CA-03 | `test_ca03_port_80_accepts_hosts_without_port`: com `EDGE_PORT=80`, 200 para `127.0.0.1`, `localhost`, `[::1]` e `127.0.0.1:80`; 403 para `attacker.example`; `is_allowed_console_host(None, 8000)` e `("", 80)` são `False` | ✅ |
| CA-04 | `test_ca04_real_server_refuses_a_rebound_host` (`slow`): `qc-edge --stub-model` em subprocesso, `EDGE_HOST=127.0.0.1`, porta livre e `EDGE_DATA_DIR` temporário. `Host: attacker.example:<p>` → 403 sem o token; `Host` padrão → 200 com `<svg`; `localhost:<p>` → 200. Exploratório, no mesmo servidor: dois `Host` e HTTP/1.0 sem `Host` → 403. O log do servidor não contém `attacker.example` nem o token, e o processo é encerrado no `finally` | ✅ |
| CA-05 | `test_ca05_token_routes_do_not_check_the_host`: cliente `192.168.0.50`; `GET /capture?t=` com `Host: 192.168.0.42:8000` → 200; `POST /api/capture` com `Host: 10.0.0.7:8000` → 200 | ✅ |
| CA-06 | `test_ca06_edge_host_must_be_ipv4[::, ::1, fe80::1, localhost]`: `main([])` sai com 2, o log cita `EDGE_HOST`, nenhuma linha com `EDGE_HOST` traz o valor e o espião do `uvicorn.run` não é chamado. `test_ca06_ipv4_edge_host_is_passed_to_uvicorn[0.0.0.0, 127.0.0.1, 192.168.0.10]`: 1 chamada com `host` igual ao valor | ✅ |
| CA-07 | `test_ca07_waiting_requests_do_not_block_the_status`: `httpx.AsyncClient` + `ASGITransport` num único event loop, 1 slot e `decode_wait_s=3`. A 1ª captura ocupa o slot (o teste espera o `infer` começar) e depois vêm 45 em paralelo. Resultados: `/api/status` 0,5 s depois → 200 em < 1,0 s; as 45 → 503 `server busy` em ≤ 5,0 s cada; a 1ª → 200; máximo de 1 `infer` simultâneo; `infer` sem event loop na thread; 1 item no sink; 1 `.jpg` em `captures/` | ✅ |
| CA-08 | `test_ca08_blocking_work_never_runs_on_the_event_loop`: o espião em `qc_edge.limits.load_capture_image` (que chama o original) é chamado 3 vezes (captura 200, GIF 415, coleta 200), sempre sem event loop rodando na thread. `test_ca08_slot_is_released_after_an_inference_error`: 1 slot e `InferenceError` na 1ª chamada → 500, 200, 200 | ✅ |
| CA-09 | `test_ca09_capture_modes_are_exact_whatever_the_umask[0o22, 0o77, 0o0, 0o277]`: `EDGE_DATA_DIR` inexistente, config carregada, `with TestClient(app)`, uma captura JPEG e uma PNG. `0700` em `EDGE_DATA_DIR`, `captures/` e no dia; `0600` nos 2 `.jpg`. `test_ca09_existing_dirs_keep_data_dir_and_fix_captures`: `EDGE_DATA_DIR` e `captures/` já com `0755`; depois da subida, `captures/` fica `0700` e `EDGE_DATA_DIR` continua `0755` | ✅ |
| CA-10 | `test_ca10_unknown_arguments_exit_2_without_values`: `--stub-modle`, `--token=<marcador>` e `<marcador>` → 2 e o espião não é chamado; o log do 1º contém `--stub-modle`; nenhum marcador aparece em `caplog` nem em `capsys`. `main([])` e `main(["--stub-model"])` → 1 chamada cada | ✅ |
| CA-11 | `test_ca11_readme_and_env_example`, com as seis condições do CA: (1) toda linha de bloco de código com `ufw allow`, `firewall-cmd … --add-` ou `nft add/insert rule` tem `from `, `source address=` ou `saddr`; (2) nenhum `--permanent` em código, e o texto tem `ip -4 route show scope link`; (3) `## Segurança na operação` com `EDGE_SESSION_TOKEN`, `WPA2` e `172.17.`; (4) a linha da tabela de variáveis que começa com `EDGE_HOST` tem `IPv4` e não tem `ou IPv6`; (5) seção "Modo coleta" com `python -m qc_edge.privacy`, `--fix` e `dataset-protocol.md`; (6) `.env.example`: o comentário imediatamente acima de `EDGE_HOST=` contém `IPv4` | ✅ |
| CA-12 | `test_ca12_docstrings_of_spec_022_and_023`: `ast.get_docstring` dos dois módulos (sem `CA-01 to CA-16` e com `CA-15 is checked by CI`; sem `and CA-13` e com `CA-13 is checked by CI`) e `pytest --collect-only -q <arquivo>` em subprocesso, com caminho explícito e sem banco: 38 e 22 testes, as contagens da `main` (`8392a8e`), medidas antes do ajuste. Depende dos ajustes da tabela abaixo | ✅ |
| CA-13 | `test_ca13_collect_stores_the_jpeg_without_private_segments`, com o "JPEG com metadados" da SPEC: EXIF com o IFD GPS, APP1 XMP, APP13, COM com marcador e trailer `ftypmp42` + 200 000 bytes. O arquivo gravado: não tem `Exif\0\0`, o XMP, `Photoshop 3.0`, o marcador nem `ftypmp42`; termina com `FF D9`; `getexif()` vazio; mesmos pixels (`np.array_equal`). Um JPEG limpo do Pillow é gravado byte a byte, e o JPEG com metadados em `mode=inspect` também | ✅ |
| CA-14 | `test_ca14_findings_and_strip_of_the_metadata_jpeg` (`{"app1", "app13", "com", "trailer"}` e `frozenset()` depois do strip). `test_ca14_eoi_inside_app1_is_not_the_end`: APP1 com um JPEG inteiro dentro (com `FF D9`) num JPEG progressivo; a saída tem todos os DQT, SOFn, DHT, SOS e dados de entropia da entrada, na mesma ordem (conferidos por um parser próprio do teste), e os mesmos pixels. `test_ca14_structural_errors[not-a-jpeg, first-100-bytes, app0-length-1]`: as duas funções levantam `JpegStructureError` (subclasse de `ValueError`), e a mensagem não tem `\x`, `b'`, o texto da entrada nem o hex dos primeiros bytes | ✅ |
| CA-15 | `test_ca15_scan_reports_without_changing_anything`: código 1; o stdout tem exatamente as linhas `raw/screw/fair/b.jpg: app1`, `raw/screw/fair/c.jpg: trailer` e `checked 3 images, 2 with private data`. Nem stdout, stderr ou log têm o `<D>` absoluto ou a latitude, e nenhum byte muda (o link `d.jpg` é ignorado). `test_ca15_fix_rewrites_only_the_private_files[0o22, 0o277]`: dataset recriado em cada valor; código 0 com as linhas `fixed`; `b.jpg` e `c.jpg` sem achados, com os mesmos pixels e modo `0600`; `a.jpg`, `manifest.csv` e o alvo do link iguais; nenhum temporário; a nova varredura dá 0 e `checked 3 images, 0 with private data`. `test_ca15_usage_errors_exit_2_without_echo[missing-dir, token-argument]`: código 2, sem o marcador em stdout, stderr ou log | ✅ |
| CA-16 | `test_ca16_unwalkable_jpeg_is_415_and_releases_the_slot`: `qc_edge.jpeg.strip_private_segments` trocado por uma função que levanta (e foi chamada); com 1 slot, 415 com o `detail` exato, nenhuma imagem nem linha no manifest, e a captura seguinte (`inspect`) → 200 | ✅ |
| CA-17 | `test_ca17_directories_are_synced_in_order`, com espião em `os.fsync` e `os.readlink("/proc/self/fd/<fd>")`. Antes do 1º arquivo de `raw/screw/fair/`, aparecem o pai de `DATASET_DIR`, `DATASET_DIR`, `raw` e `raw/screw`; depois, nesta ordem relativa: arquivo em `raw/screw/fair/`, `raw/screw/fair`, `manifest.csv` e `DATASET_DIR`. `test_ca17_directory_sync_errors_are_warnings`: `EINVAL` em todo descritor de diretório → 200, linha no manifest, imagem existe e um `WARNING` de `qc_edge` por diretório recusado (6 = 6), cada um com o `strerror` | ✅ |
| CA-18 | `test_ca18_notes_with_separators_or_format_chars_are_422[U+2028, U+2029, U+202E, U+2066, U+200F, U+00AD]` → 422, e `DATASET_DIR` nem é criado. `test_ca18_valid_notes_are_stored_unchanged` (`dúvida fair/poor`). `test_ca18_user_agent_controls_become_spaces_before_the_cut`, por ASGI cru com `b"Phone\x85X\tY" + b"z" * 70`: `capture_device == "Phone X Y" + "z" * 51` (60 caracteres) e `splitlines()` do manifest com 2 linhas | ✅ |

**Sensibilidade (os testes falham sem a mudança).** Copiei o `test_spec_025.py` para um `git worktree` temporário da `main` (`8392a8e`, fora do repositório, removido no fim) e rodei contra o código antigo. Falham, entre outros:

- CA-02, CA-03 e CA-04 (sem checagem de `Host`);
- CA-06 com `::`, `::1` e `fe80::1`;
- os três testes do CA-07: o `/api/status` levou **2,64 s** com o semáforo antigo no threadpool, contra o limite de 1,0 s;
- CA-08 (o espião em `qc_edge.limits` nunca era chamado);
- CA-09 (modo `0755`/`0777` com umask `022`/`000`; com umask `0o277`, 500);
- CA-10, CA-13 e CA-18.

Os que não dependem de símbolos novos passam nos dois lados, como esperado (ex.: CA-05).

## Ajustes em testes de aceite de SPECs anteriores

Dois commits próprios (`Agent: tester`), só nos arquivos e itens da §4.7. Regra: `docs/architecture.md` §10, "Testes de aceite de SPECs anteriores". Nenhum `test_caNN_` foi removido nem renomeado. Nenhuma outra linha dos arquivos mudou:

- `git show 2d5ab42 --stat`: `test_spec_007.py`, 11 inserções e 2 remoções;
- `git show 1fce170 --stat`: 2 arquivos, 4 inserções e 3 remoções.

| Arquivo | Teste | Asserção antes → depois | Requisito da SPEC-025 que motivou |
|---|---|---|---|
| `edge/tests/acceptance/test_spec_007.py` | helper `asgi_get`. Afeta `test_ca02_generated_tokens_are_long_urlsafe_and_distinct` (via `_console_token`), `test_ca13_console_from_loopback`, `test_ca14_console_refuses_remote_or_proxied`, `test_ca18_no_candidate_falls_back_to_loopback_with_console_warning`, `test_extra_console_ip_parameter_only_accepts_detected_ips` e `test_extra_console_accepts_ipv6_loopback` | URL base `http://testserver` → `http://127.0.0.1:<EDGE_PORT>` (`EDGE_PORT` do ambiente, padrão 8000). Nenhuma asserção mudou. No CA-14 da SPEC-007, a recusa continua vindo do cliente remoto ou do header de proxy, agora com um `Host` que por si só seria aceito | §4.1 (`Host` de loopback); §4.7, item 1, 1º marcador (commit `2d5ab42`) |
| `edge/tests/acceptance/test_spec_007.py` | `test_extra_configuration_boundaries_are_accepted` (extra, sem CA) | `EDGE_HOST="::"`: `run_main(...) == 0` → `== 2`, e o espião do `uvicorn.run` não é chamado. Para manter a intenção do teste, que confere os limites aceitos, ele roda de novo com o IPv4 de fronteira `255.255.255.255` e continua exigindo código 0 e `port == 65535` (token de 32 e `DEVICE_ID` de 32 caracteres). Nome mantido | §4.3 (só IPv4); §4.7, item 1, 3º marcador (commit `2d5ab42`) |
| `tests/acceptance/test_spec_022.py` | docstring do módulo | `(CA-01 to CA-16).` → `(CA-01 to CA-14 and CA-16;` + quebra de linha + `CA-15 is checked by CI and by the test report, docs/architecture.md section 10).` A quebra existe só por causa do limite de 100 colunas do ruff e fica antes de `CA-15`, para que a frase `CA-15 is checked by CI` continue inteira. Coleta: 38 → 38 | §4.7, item 2; RV-02 de `reviews/SPEC-004/r2-review-report.md` (commit `1fce170`) |
| `packages/contracts/tests/acceptance/test_spec_023.py` | docstring do módulo | `CA-03 to CA-06\nand CA-13.` → `CA-03 to CA-06\n(CA-13 is checked by CI and by the test report, docs/architecture.md section 10).` O resto da frase (`Tests named ...`) foi só reflowed nas duas linhas seguintes, sem mudar o texto. Coleta: 22 → 22 | §4.7, item 3; RV-02 de `reviews/SPEC-004/r2-review-report.md` (commit `1fce170`) |

Conferências da §4.7:

- **Item 1, 2º marcador:** nenhum ajuste foi necessário. Todas as chamadas a `qc_edge.cli.main()` do `test_spec_007.py` passam pelo `run_main`, que já faz `monkeypatch.setattr(sys, "argv", ["qc-edge", ...])`.
- **Item 4 (`test_spec_010.py`):** passa sem ajuste (125 testes), como a SPEC previa. O mesmo vale para `test_spec_022.py` e `test_spec_023.py`, fora as docstrings.

## Suíte completa

```text
$ env -u TEST_DATABASE_URL uv run pytest -q
2961 passed, 643 skipped, 5 warnings in 260.03s (0:04:20)

$ TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
3604 passed, 5 warnings in 427.02s (0:07:07)

$ uv run pytest -q edge/tests/acceptance/        # depois dos últimos ajustes do arquivo novo
368 passed, 1 warning                            # 110 (SPEC-007) + 125 (SPEC-010) + 133 (SPEC-025)

$ uv run pytest -q edge/tests/acceptance/test_spec_025.py   # 4 execuções seguidas
133 passed, 1 warning in ~18 s

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
148 files already formatted
```

- **Avisos:** o `StarletteDeprecationWarning` do `TestClient` já existia. Na rodada registrada acima, os outros 4 avisos eram `UserWarning: Corrupt EXIF data` do Pillow, causados pelo APP1 de teste do CA-14 (cabeçalho TIFF incompleto). Troquei esse APP1 por um TIFF válido com IFD0 vazio, e o arquivo agora só emite o aviso do Starlette.
- **Rodada final** (o mesmo conteúdo deste commit, depois desses ajustes):

  ```text
  $ env -u TEST_DATABASE_URL uv run pytest -q
  2961 passed, 643 skipped, 1 warning in 258.01s (0:04:18)

  $ TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
  3604 passed, 1 warning in 427.99s (0:07:07)

  $ uv run ruff check . && uv run ruff format --check .
  All checks passed!
  148 files already formatted
  ```

- **Limpeza:** nenhum processo `qc_edge` ficou rodando (`pgrep`), e o `git status` só mostra os arquivos deste trabalho. As portas foram abertas só em `127.0.0.1`, e o worktree temporário da `main` foi removido.

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Todos estão automatizados em `test_extra_*` e passam.

- **Console e `Host`:**
  - 16 variações recusadas por `is_allowed_console_host`:
    - espaço antes ou depois;
    - `127.0.0.1:08000`, `127.0.0.1:8000/`, `127.0.0.1:8000.`, `localhost:8000:8000`, `user@127.0.0.1:8000`;
    - `[::1]` sem porta (porta ≠ 80), `::1:8000`, `[::ffff:127.0.0.1]:8000`;
    - `127.1:8000`, `2130706433:8000`, `0.0.0.0:8000`;
    - `LOCALHOST.:8000`;
    - `localhost` com "o" cirílico;
    - `localhost\0:8000`;
  - a recusa por `Host` gera exatamente um `WARNING` `console refused: host not allowed`, sem o valor;
  - com `Host` de loopback, o cliente da LAN e cada um dos 3 headers de proxy continuam recusados, sem chamar `detect_lan_ips`;
  - o 403 por `Host` tem o mesmo corpo do 403 por cliente remoto e os mesmos headers de página do 200.
- **Servidor real (sonda manual com o mesmo `qc-edge`):**
  - dois `Host`, HTTP/1.0 e HTTP/1.1 sem `Host` → 403;
  - `Host` `127.0.0.1:<p>` com dois espaços antes e depois do valor → 403;
  - `LOCALHOST:<p>` → 200;
  - `X-Forwarded-Host: attacker.example` com `Host` de loopback → 200 (a SPEC só lista os 3 headers de proxy);
  - alvo em forma absoluta (`GET http://attacker.example:<p>/`) com `Host` de loopback → 200. O navegador não manda essa forma ao servidor de origem, então isso não abre o DNS rebinding;
  - 4 recusas no log, nenhuma com `attacker.example`.
- **Limitador:**
  - a mesma cena do CA-07 com threads + `with TestClient(app)` passa;
  - a mesma cena também passa num **uvicorn real** em thread (`slow`): `/api/status` em < 1,0 s, o console responde 200 durante a rajada, as 45 recebem 503 em ≤ 5,0 s e a 1ª recebe 200 (a medição do SEC-03);
  - corrida entre timeout e liberação: 150 capturas com `decode_wait_s=0.02` e `infer` de 10 ms, com 1 e 2 slots. Só aparecem 200 e 503 (nenhum 500 de over-release). Depois, `slots` capturas lentas rodam juntas (nenhum slot vazou), e o máximo simultâneo nunca passa de `slots`;
  - 3 `with TestClient(app)` seguidos e 2 requisições com `TestClient` sem `with`, no mesmo app → todas 200 (o `anyio.Semaphore` se religa a cada loop, §7).
- **Permissões:** `EDGE_DATA_DIR` com 3 níveis inexistentes e umask `0o277` → `0700` e foto `0600`. Coleta com umask `0o277` → `DATASET_DIR`, diretório da imagem, imagem e `manifest.csv` com os modos exatos.
- **`EDGE_HOST`:**
  - `" 127.0.0.1"`, `127.0.0.01`, `::ffff:127.0.0.1`, `0`, `"127.0.0.1\n"` e `1.2.3.4/32` → 2;
  - vazio → `0.0.0.0` (ver O-03).
- **CLI:**
  - nenhum marcador aparece no log ou no stderr com `--stub-model=<m>`, `--Token=<m>`, `-<M>`, `--<M>` (maiúsculas, fora do formato), `-- <m>`, `--stub-model <m>`, `--tökén=<m>` e um nome de 40 letras;
  - lista no formato `--stub-modle, --token, 1 other`;
  - `--help` e `-h` → 0;
  - `main()` sem argumento lê `sys.argv`.
- **Varredura de JPEG:**
  - ficam iguais byte a byte, sem achados: baseline, progressivo, `optimize`, com RSTn (`restart_marker_blocks=1`), cinza, `subsampling=0`, com ICC (APP2) e CMYK com APP14 Adobe;
  - COM, APP1 vazio (comprimento 2) e APP13 entre o DHT e o SOS são removidos, e APP2 e APP14 ficam: a saída é exatamente a entrada sem esses três segmentos;
  - COM entre dois scans progressivos e bytes `FF` de preenchimento: o COM sai, o preenchimento fica, e os pixels e os segmentos de imagem não mudam;
  - um trailer que é outro JPEG inteiro (com EXIF) é removido;
  - 7 erros estruturais a mais: vazio, só SOI, comprimento além do fim, APP1 de comprimento 0, sem EOI, EOI cortado e `FF` no fim;
  - `strip` é idempotente;
  - 3 MiB de trailer são varridos em < 2 s.
- **Coleta:**
  - APP1 com um JPEG dentro → grava exatamente o JPEG sem o APP1, com os mesmos pixels;
  - PNG com EXIF → JPEG reencodado, sem achados;
  - **JPEG com 2 bytes soltos entre segmentos** (que o Pillow aceita) → 415 `unsupported JPEG structure`, sem gravar nada, e o slot é liberado. É o caso do CA-16 sem espião;
  - JPEG com metadados cortado antes do EOI → 415 e nada gravado;
  - `notes` com U+061C, U+200E, U+FEFF, U+2069, U+202A, `\r`, `\x85` e U+E0001 → 422;
  - `notes` com emoji, NBSP, CJK e acentos → 200 e texto igual;
  - `User-Agent` cru `A\0B\x1bC\x7fD\x85E\xadF\xa0G` + 80 `q` → `"A B C D E F G" + "q" * 47` (o NBSP é `Zs` e fica) e 2 linhas no manifest.
- **CLI `qc_edge.privacy`:**
  - `--fix` espera o `flock` de `manifest.csv.lock` segurado pelo teste (0,6 s sem mexer em `b.jpg`), depois corrige e sai com 0;
  - com umask `0o000`, o lock é criado com `0600`;
  - ordem: `fsync` do temporário → `os.replace` → `fsync` do diretório, para `b.jpg` e `c.jpg`;
  - arquivo `invalid`: aparece na varredura e o `--fix` sai com 1, sem tocá-lo;
  - `upper.JPG`, um diretório `dir.jpg` e `notes.txt` são ignorados;
  - `--dataset-dir` que é arquivo → 2; dataset sem `raw/` ou com `raw/` vazio → 0 e `checked 0 images, 0 with private data`;
  - `python -m qc_edge.privacy` em subprocesso → 1, sem o caminho absoluto.
- **R-02:**
  - com `socket.connect`, `create_connection` e `getaddrinfo` espionados, uma coleta, uma inspeção e um `--fix` não tentam nenhuma conexão;
  - nenhuma rota serve `captures/` nem o dataset;
  - `privacy.py` não importa `httpx`, `requests`, `urllib`, `http`, `socket` nem `aiohttp`.

### Observações (não são bugs; para o architect e o security-devops)

- **O-01 (§4.9, baixa):** a CLI imprime o caminho relativo cru. Um arquivo copiado à mão com `\n` no nome (ex.: `x\nchecked 0 images, 0 with private data\n.jpg`) ocupa três linhas da saída, e uma delas imita o resumo. O código de saída (1) e a última linha (o resumo verdadeiro) continuam certos, e o teste extra confere só isso. Sequências de escape de terminal no nome passariam do mesmo jeito. A SPEC diz "uma linha" por arquivo, mas não define o escape. Sugestão para uma emenda: imprimir `repr`/escape de caracteres `Cc`/`Cf`/`Zl`/`Zp` no caminho, ou listar esses nomes como `invalid`.
- **O-02 (§4.5, informativa):** pela regra da SPEC, uma palavra minúscula com cara de opção (`--?[a-z][a-z0-9-]{0,30}`) é registrada como nome. Um segredo em hex minúsculo de até 30 caracteres digitado como `--<segredo>` iria para o log. O teste extra documenta esse comportamento, que é o que a SPEC pede. Os tokens do projeto (`token_urlsafe`, 43 caracteres) não cabem no formato.
- **O-03 (§4.3, informativa):** `EDGE_HOST=` vazio vale como "não definido" (`env_ignore_empty` da SPEC-007) e sobe com `0.0.0.0`. É coerente com as demais variáveis.
- **O-04:** confirmei a O-01 do dev-report: `IMG_0001.JPG` e `.jpeg` não são varridos. A O-02 dele (o próprio `raw` como link) não foi testada além do que a SPEC pede.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório:
  - `edge/tests/acceptance/test_spec_025.py` (novo);
  - os ajustes da §4.7 em `edge/tests/acceptance/test_spec_007.py`, `tests/acceptance/test_spec_022.py` e `packages/contracts/tests/acceptance/test_spec_023.py`, listados na tabela acima.
