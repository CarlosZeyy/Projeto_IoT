# SPEC-030 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-030](../../docs/specs/SPEC-030-manutencao-borda-publisher-privacidade.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `3eeff9e` (implementação até `bf66151`, mais o dev-report e o `chore` de status) |
| **Veredicto** | **PASS** |

Os testes foram escritos a partir da SPEC (caixa-preta) antes da leitura da implementação. Arquivo novo: `edge/tests/acceptance/test_spec_030.py` (42 funções, 80 testes coletados com a parametrização). Mock só das fronteiras da SPEC (§6): a nuvem (`httpx.MockTransport` com um `SyncByteStream` próprio, `Blocks`, que conta os blocos entregues e registra o `close`), o relógio de parede, o `monotonic` e o RNG (`random.Random(0)`). SQLite e sistema de arquivos reais, sempre em `tmp_path`. Chaves, marcadores e a senha fictícia são gerados com `secrets`. JPEGs sintéticos, montados no teste (R-14).

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `edge/tests/acceptance/test_spec_030.py::test_ca01_slow_body_exceeds_the_deadline` (10 blocos de 1 byte, +4 s por bloco: `request deadline exceeded`, ≤ 5 blocos entregues, resposta fechada, sem URL nem chave na cadeia da exceção) | ✅ |
| CA-02 | `::test_ca02_body_above_the_cap_is_too_large` (512 KiB + 1 em blocos de 64 KiB: `response too large`, ≤ 9 blocos); `::test_ca02_large_fastapi_422_keeps_the_summary` (422 FastAPI com 2 erros e 300 KiB: `HTTP 422: 2 validation errors`); `::test_ca02_non_positive_deadline_or_cap_is_value_error` (0 e negativos, 4 casos) | ✅ |
| CA-03 | `::test_ca03_deadline_is_a_retry_and_nothing_is_lost` (3 itens `pending`, `attempts=1`, `last_error == "request deadline exceeded"`, `offline`; depois do `next_attempt_at`, 3 `sent` e 3 ids únicos na nuvem) | ✅ |
| CA-04 | `::test_ca04_retry_is_not_held_by_a_clock_jump_back` (falha de conexão em T, `next_attempt_at` em [T+0,8; T+1,2], relógio em T − 3600 s: `sent` na mesma chamada); `::test_ca04_exactly_max_delay_ahead_is_not_due` (`now + 60 s` exatos não volta; +1 µs volta; vencido volta; +30 s não volta) | ✅ |
| CA-05 | `::test_ca05_health_check_after_a_clock_jump_back` (health em T, relógio em T − 3600 s: exatamente 1 `GET /api/v1/health`; novo `run_once` no mesmo instante: nenhuma requisição) | ✅ |
| CA-06 | `::test_ca06_no_credential_literal_in_edge_urls` (`git ls-files edge`, arquivos de texto, a regex da SPEC linha a linha) | ✅ (depois do ajuste da §4.6, item 1; antes, falhava em `test_spec_009.py:1035`) |
| CA-07 | `::test_ca07_real_api_test_has_no_private_transport_attribute` (`ast`: nenhum `Attribute` com `attr == "_transport"`); `::test_ca07_real_api_test_passes_on_the_database` (marcador `db`: `pytest -q` só no arquivo, num banco próprio `<base>_acc030`, criado e apagado pelo teste, termina com `3 passed`) | ✅ |
| CA-08 | Manual, executado por mim (ver "CA-08 (manual)") | ✅ |
| CA-09 | `::test_ca09_any_case_jpeg_is_checked_and_other_files_are_invalid` (as 5 linhas de achado em ordem e `checked 6 images, 5 with private data`; `.g.jpg.abc123.tmp` não citado; `--fix`: código 1, `fixed` de `B.JPG` e `c.Jpeg`, sem achados, mesmos pixels pelo `qc_preprocess.load_image`, nomes mantidos, `d.png`, `e.heic`, `f` e o `.tmp` iguais byte a byte) | ✅ |
| CA-10 | `::test_ca10_control_characters_are_escaped` (exatamente 2 linhas, a de achado igual à da SPEC com as barras literais, sem `\x1b` e sem `\n` fora dos fins de linha); `::test_ca10_a_name_that_is_not_utf8_is_escaped` (nome com o byte `0xff`: código 1, sem exceção, linha com `\udcff` literal) | ✅ |
| CA-11 | `::test_ca11_unreadable_file_is_listed` (`z.jpg` com modo `0o000`: código 1, `raw/screw/fair/z.jpg: unreadable`, `checked 1 images, 0 with private data`, log `ERROR`; pulado como root) | ✅ |
| CA-12 | `::test_ca12_pytest_addopts_does_not_break_the_spec_025_count` (subprocesso `pytest -q edge/tests/acceptance/test_spec_025.py -k ca12` com `PYTEST_ADDOPTS="-k nao_existe_nenhum_teste"`, sem banco: código 0, `1 passed`) | ✅ (depois do ajuste da §4.6, item 2; antes, falhava com `no tests collected (38 deselected)` no `_collected`) |

Os CA-06 e CA-12 foram vistos falhando (vermelho) antes dos ajustes da §4.6 e passando depois, o que confirma que os testes verificam o que a SPEC pede.

O comando do CA-12 também foi rodado literalmente, fora da suíte:

```text
$ PYTEST_ADDOPTS="-k nao_existe_nenhum_teste" uv run pytest -q -p no:cacheprovider edge/tests/acceptance/test_spec_025.py -k ca12
1 passed, 196 deselected, 1 warning in 0.79s
exit=0
```

Nota sobre a regra "sem suíte dentro da suíte" (`docs/architecture.md` §10): o CA-07 roda o pytest num único arquivo explícito, num banco próprio com `test` no nome (`<base>_acc030`), para que o `migrated_db` interno nunca recrie o schema da sessão externa. O CA-12 roda o pytest num único arquivo explícito, sem banco e com `-k ca12`; o único teste selecionado chama `pytest --collect-only` em 2 arquivos explícitos (o CA-12 da SPEC-025), que não executa teste nenhum. Nos dois subprocessos, `PYTEST_ADDOPTS`, `PYTEST_PLUGINS` e `PYTEST_CURRENT_TEST` da execução externa são removidos (o CA-12 define o seu próprio `PYTEST_ADDOPTS`, de propósito).

## Ajustes em testes de aceite de SPECs anteriores (§4.6 e `docs/architecture.md` §10)

| Arquivo | Teste | Asserção antes → depois | Requisito |
|---|---|---|---|
| `edge/tests/acceptance/test_spec_009.py` | `test_extra_cloud_url_refused_with_or_without_stub` (parâmetro da linha 1035) | a URL literal com usuário e senha fictícios (`https://` + `user` + `:` + senha de 2 letras + `@api.exemplo.org`) → `pytest.param(CREDENTIAL_URL, id="credential-in-url")`, com `CREDENTIAL_PASSWORD = secrets.token_hex(8)` e `CREDENTIAL_URL = "https://user:" + CREDENTIAL_PASSWORD + "@api.exemplo.org"` definidos logo acima do `parametrize` (o `id` fixo evita que a senha gerada entre no nome do teste) | §4.6, item 1; §4.3, item 1 (RV-01/SEC-09-01); CA-06 |
| `edge/tests/acceptance/test_spec_009.py` | mesmo teste (linhas 1058–1059) | `if "<usuário:senha literal>" in url: assert "<usuário:senha literal>" not in text` → `if url == CREDENTIAL_URL: assert CREDENTIAL_PASSWORD not in text` | §4.6, item 1 ("as asserções que procuram o valor no log passam a procurar a senha gerada") |
| `edge/tests/acceptance/test_spec_025.py` | `_collected` (usado pelo `test_ca12_docstrings_of_spec_022_and_023`) | ambiente sem `TEST_DATABASE_URL` e `CI` → sem `TEST_DATABASE_URL`, `CI`, `PYTEST_ADDOPTS`, `PYTEST_PLUGINS` e `PYTEST_CURRENT_TEST`; contagens (`MAIN_COLLECTED`) inalteradas | §4.6, item 2 (RV-08 da SPEC-025); CA-12 |
| `edge/tests/acceptance/test_spec_025.py` | `test_extra_privacy_invalid_file_and_odd_entries` | última linha `checked 4 images, 3 with private data` → `checked 6 images, 5 with private data`; mais as linhas `raw/screw/fair/notes.txt: invalid` e `raw/screw/fair/upper.JPG: app1` conferidas. Nome do teste mantido | §4.4 (`.JPG` varrido; outro arquivo de `raw/` é `invalid`); §4.6, item 2 |

Nenhuma outra linha desses dois arquivos mudou. A intenção dos testes continua a mesma: a URL com credencial é recusada sem eco do segredo; o CA-12 da SPEC-025 confere as mesmas contagens; o teste extra confere o mesmo `invalid` de `e.jpg`, o mesmo código 1 e o mesmo `--fix` que não toca o `invalid`. Nenhum outro teste de aceite antigo falhou por causa das §4.4 e §4.5. O `test_extra_privacy_paths_with_control_characters_keep_code_and_summary` (SPEC-025) continua passando sem ajuste (ele só confere o código e a última linha); o comentário dele que fala do nome "impresso cru" (O-01 da SPEC-025) ficou desatualizado, mas não é asserção e não foi tocado.

## CA-08 (manual, `httpx2`)

Executado em 2026-10-20 na máquina da dupla, na pasta principal, sem rodar a suíte completa com o extra instalado.

1. `uv sync --all-packages --extra train`: instalou `torch==2.14.1`, `torchvision==0.29.1`, `timm==1.0.30` e dependências (cache local do uv).
2. Conferência do ambiente e do teste:

   ```text
   $ uv run --no-sync python -c "import torch, importlib.metadata as m, starlette.testclient as t; ..."
   torch 2.14.1+cu130
   httpx2 2.13.1
   testclient uses httpx2

   $ CI=true TEST_DATABASE_URL=<url do banco de teste> uv run --no-sync pytest -q -p no:cacheprovider edge/tests/test_publisher_real_api.py
   ...                                                                      [100%]
   3 passed in 0.50s
   exit=0
   ```

   O `--no-sync` garante que o `uv run` não mexe no ambiente entre os passos. Contraprova, no mesmo ambiente: a versão anterior do arquivo (`git show 84045fc:edge/tests/test_publisher_real_api.py`, copiada para um arquivo temporário em `edge/tests/acceptance/` e apagada logo em seguida) dá `3 failed`, com `assert isinstance(response.stream, SyncByteStream)`, a falha relatada na SPEC-011.
3. `uv sync --all-packages --locked`: removeu `torch`, `torchvision`, `timm`, `triton` e afins.

   ```text
   $ uv run --no-sync python -c "import torch"
   ModuleNotFoundError: No module named 'torch'
   $ uv run --no-sync python -c "import httpx2"
   ModuleNotFoundError: No module named 'httpx2'
   ```

   O `uv.lock` não mudou (`git status` limpo nesse arquivo).
4. Registrado aqui.

## Suíte completa

Executada depois do passo 3 do CA-08 (ambiente igual ao do CI, sem o extra `train`):

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
5707 passed, 52 skipped, 1 warning in 349.08s (0:05:49)
(os 52 skipped são os testes `docker`, que exigem PARTQC_DOCKER_TESTS=1; nenhum teste `db` pulado)

$ CI=true TEST_DATABASE_URL=... uv run pytest -q edge/tests/acceptance/test_spec_030.py edge/tests/acceptance/test_spec_009.py edge/tests/acceptance/test_spec_025.py
371 passed, 1 warning in 35.45s
(reexecução final dos 3 arquivos tocados, com o test_spec_030.py já no índice do git, para o CA-06 varrê-lo também)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
224 files already formatted
```

## Bugs encontrados

Nenhum bug contra a SPEC.

## Testes exploratórios (além dos critérios)

Todos automatizados em `test_spec_030.py` (`test_extra_*`) e passando, salvo indicação.

### Publisher (§4.1)

| Caso | Resultado |
|---|---|
| O prazo conta desde antes do envio: o transporte gasta 16 s (fake `monotonic`) antes de devolver uma resposta de 1 bloco | `request deadline exceeded` ✅ |
| Exatamente 15 s (3 blocos de +5 s): a comparação é `>`, não `>=` | lido e aceito ✅ |
| `deadline_s=3` configurável; 401, 403, 302 e 503 com corpo lento e grande | o corpo nunca é lido (0 blocos); as exceções continuam as da SPEC-009 ✅ |
| `check_health` com 200 e 503 e corpo de 20 × 64 KiB lento | só o status; 0 blocos lidos; sem `X-API-Key` ✅ |
| Corpo de exatamente 512 KiB (JSON válido com espaços) | lido e aceito ✅ |
| 413 e 422 com corpo de 600 KiB | `response too large` (transitório, vira retry, nunca `dead`, §7); o marcador do corpo não aparece na exceção ✅ |
| `max_response_bytes=10` configurável | recusa no 2º bloco ✅ |
| Padrões do construtor (só o `monotonic` injetado) | 512 KiB + 1 recusado; 16 blocos de +1 s recusados no 16º ✅ |
| `too large` no laço (`run_once`) | `pending`, `attempts=1`, `last_error == "response too large"`, chave fora dos logs ✅ |
| **Descompressão gzip antes do teto** (nota do autor) | Confirmada. O teto vale para os bytes decodificados (como a SPEC pede, `iter_bytes`), mas o `httpx` descomprime cada bloco bruto inteiro antes da primeira conferência. Medido com `tracemalloc` (script em scratch, fora do repositório): um corpo gzip de 64 KiB que vira 64 MiB dá `response too large` depois de 1 bloco, com pico de ~141 MiB; 256 MiB descomprimidos em 4 blocos de 64 KiB também param no 1º bloco, com o mesmo pico de ~141 MiB. O pico fica limitado ao tamanho de um bloco bruto vezes a taxa de compressão (~1000:1), não cresce com o corpo. O teste automatizado (`test_extra_ca02_cap_is_configurable_and_counts_decoded_bytes`) só confere que o corpo gzip acima do teto é recusado. Ver O-01. |

### Salto do relógio (§4.2)

| Caso | Resultado |
|---|---|
| `fetch_due()` com linhas vencida, na janela `(now, now + 60]` e além de `now + 60` (duas): só a da janela espera, e a ordem por `created_at` se mantém; o `run_once` manda exatamente essas, no mesmo lote | ✅ |
| `sent` e `dead` nunca voltam depois de um salto de 30 dias para trás | ✅ |
| `max_delay_s` hostil (texto com SQL) | `TypeError` antes do SQL; tabela intacta ✅ |
| Depois do health por salto, o período normal volta: nada em +59 s, health em +61 s | ✅ |
| Salto para trás com a nuvem fora do ar | health roda e o estado vai a `offline` ✅ |

### Varredura (§4.4 e §4.5)

| Caso | Resultado |
|---|---|
| `x.JPEG`, `x.jPg`, `x.JpEg`, `.hidden.jpg`, `x.jpg.JPG` | varridos como JPEG (`app1`) ✅ |
| `x.jpg.tmp`, `.x.TMP`, `x.tmp`, `x.jpgx`, `x.jpe`, `x.jfif`, `x.JPG.png`, `x.gif`, `x.webp` (com bytes de JPEG com GPS dentro) | `invalid`, não lidos, `--fix` não toca, código 1 ✅ |
| Temporários `.a.jpg.abc.tmp`, `.tmp`, `.x.tmp` (com GPS dentro) | ignorados: não contam, não aparecem, código 0 ✅ (ver O-02) |
| Arquivo direto em `raw/`, `.PNG` em subpasta funda, `.png` vazio | `invalid` ✅ |
| Link simbólico para `.png`, FIFO `fifo.jpg`, arquivo fora de `raw/` | ignorados (o FIFO não trava a varredura) ✅ |
| `.png` com modo `0o000` | `invalid` (não é lido), não `unreadable` ✅ |
| `printable_path`, tabela de 17 casos: `\n`, `\t`, `\r`, `\x1b`, DEL, U+0085, U+202E, U+200B, U+FEFF, U+2028/U+2029, surrogate, U+E0001, `\`, acentos, NBSP (Zs), emoji, vazio | conforme a §4.5 (hexadecimal minúsculo, `\xHH`/`\uHHHH`/`\UHHHHHHHH`) ✅ |
| `printable_path` em todos os caracteres de U+0000 a U+2FFF mais surrogates e tags | nenhum caractere de `Cc`/`Cf`/`Cs`/`Zl`/`Zp` sobra; o escape do `\` mantém nomes diferentes com saídas diferentes ✅ |
| Ordem: `a\x01.jpg` antes de `a0.jpg` (pelo caminho original, não pelo escapado) | ✅ |
| `--fix` com nome hostil (`\x1b]0;t\x07`, sequência OSC) | linha de achado e `fixed` escapadas; sem ESC nem BEL no stdout ✅ |
| `unreadable` com `--fix` e nome com `\x1b[2J` | linha `unreadable` escapada, o outro arquivo é corrigido, código 1, sem ESC no stdout, no stderr nem no log, sem caminho absoluto ✅ |
| `python -m qc_edge.privacy` num pipe real com nome hostil, nome com `0xff` e nome acentuado (`peça-ção.jpg`), com e sem `--fix` | sem `Traceback`, sem ESC, o acento sai sem escape, contagem de linhas exata ✅ |
| Subpasta de `raw/` sem permissão de leitura (modo `0o000`) com um JPEG com GPS dentro (exploração manual em scratch) | a foto é pulada em silêncio: nem linha, nem log, nem efeito no código (com o resto limpo, o código seria 0). Comportamento anterior a esta SPEC (o `os.walk` sem `onerror` vem da SPEC-025). Ver O-03. |

## Observações (não bloqueantes, fora do escopo desta SPEC)

- **O-01 (para o security-devops; confirma a nota do autor):** com `Content-Encoding: gzip`, o pico de memória antes da conferência do teto é de dezenas de MiB por bloco (medido: ~141 MiB de pico para um bloco de 64 KiB que vira 64 MiB). O comportamento segue a SPEC (§4.1 manda `iter_bytes`), e o risco é baixo (URL só HTTPS ou loopback, servidor da própria API). Uma SPEC futura pode mandar `Accept-Encoding: identity` ou contar pelo `iter_raw`.
- **O-02:** a exceção dos temporários (§4.4) vale para qualquer nome `.*.tmp` em qualquer pasta de `raw/`, não só para o padrão exato do `mkstemp` (`.<nome>.<aleatório>.tmp`). Um arquivo copiado à mão com esse formato de nome (raro) não seria varrido nem acusado. É o que a SPEC escreve; fica como observação.
- **O-03:** uma subpasta de `raw/` que o `os.walk` não consegue listar é pulada sem aviso, então as fotos dela não são conferidas. É anterior à SPEC-030 e nenhum requisito desta SPEC cobre o caso (a §4.5 fala de arquivo ilegível). Sugestão para uma SPEC futura: tratar a subpasta ilegível como o `unreadable` da §4.5.
- **O-04:** um corpo vazio (sem blocos) nunca passa pela conferência do prazo, que roda "depois de cada bloco". Isso não deixa a requisição pendurada (ela já terminou), só não reclassifica uma resposta lenta e vazia. Segue a SPEC.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
