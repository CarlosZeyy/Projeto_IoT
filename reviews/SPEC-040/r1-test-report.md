# SPEC-040 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-040](../../docs/specs/SPEC-040-manutencao-consolidada.md) |
| Rodada | r1 (Parte A do developer, Parte B do ml-engineer, Parte C do security-devops) |
| Tester | tester |
| Commit testado | `2fa9248` |
| **Veredicto** | **PASS** |

Escrevi os testes a partir da SPEC antes de ler a implementação. Para saber as assinaturas públicas, consultei só os aceites antigos e o código da `main`. Depois li o diff de produção para escolher os exploratórios e as mutações.

O CA-18 é manual e continua pendente com o humano. Por isso, este PASS não confirma o caminho real pelo proxy do Coolify.

## Cobertura dos critérios de aceite

Arquivos e contagem de testes (`test_caNN_*` com parâmetros, mais `test_extra_*`):

| Arquivo | Testes | `test_ca*` | Extras |
|---|---|---|---|
| `edge/tests/acceptance/test_spec_040.py` | 94 | 27 | 67 |
| `dashboard/tests/acceptance/test_spec_040.py` | 98 | 18 | 80 |
| `api/tests/acceptance/test_spec_040.py` | 34 | 16 | 18 |
| `ml/tests/acceptance/test_spec_040.py` | 79 | 24 | 55 |
| `infra/tests/acceptance/test_spec_040.py` | 26 | 16 | 10 |
| **Total** | **331** | **101** | **230** |

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `edge/.../test_spec_040.py::test_ca01_every_request_asks_for_identity` | passou |
| CA-02 | `edge/...::test_ca02_batch_200_with_an_encoding_is_refused` (casos a a f), `::test_ca02_batch_422_bomb_is_transient_not_rejected` (g), `::test_ca02_heartbeat_204_with_gzip_is_refused` (h), `::test_ca02_heartbeat_422_bomb_is_transient_not_rejected` (i). Conferem também 0 blocos lidos e a resposta fechada | passou |
| CA-03 | `edge/...::test_ca03_batch_without_a_real_encoding_is_read` (3 casos), `::test_ca03_loop_keeps_the_items_and_delivers_them_once` | passou |
| CA-04 | `edge/...::test_ca04_unreadable_folder_and_files_are_listed_in_order` (com e sem `--fix`), `::test_ca04_real_command_gives_the_same_lines` (processo real, com e sem `--fix`), `::test_ca04_folder_name_is_escaped_on_one_line` (com e sem `--fix`), `::test_ca04_after_the_modes_are_restored_both_images_have_findings`, `::test_ca04_without_raw_is_not_unreadable` | passou (ver O-02) |
| CA-05 | `edge/...::test_ca05_only_the_exact_format_is_ignored`, `::test_ca05_clean_image_and_the_real_temporary_exit_0` | passou |
| CA-06 | `edge/...::test_ca06_failure_to_build_logs_only_the_class`, `::test_ca06_cap_hints_and_truncation` | passou |
| CA-07 | `dashboard/...::test_ca07_url_httpx_cannot_build_is_refused` (5), `::test_ca07_overview_shows_the_message_and_sends_nothing` (5), `::test_ca07_urls_accepted_today_stay_accepted` (5) | passou |
| CA-08 | `dashboard/...::test_ca08_build_or_read_raises_the_config_error` (2), `::test_ca08_body_that_is_not_json_keeps_its_exception` | passou |
| CA-09 | `api/...::test_ca09_request_asks_for_identity`, `::test_ca09_compressed_answer_is_a_failure_without_reading` (a a d), `::test_ca09_plain_answer_is_delivered` (2), `::test_ca09_candidate_with_gzip_stays_undelivered_and_is_not_retried` (banco) | passou (ver O-03) |
| CA-10 | `api/...::test_ca10_warning_has_the_age_and_the_candidate_not_reserved` (banco, servidor local que goteja os cabeçalhos) | passou |
| CA-11 | `api/...::test_ca11_api_readme_mentions_and_absences`, `::test_ca11_api_readme_bash_blocks_never_put_the_token_in_argv`, `::test_ca11_control_the_rule_detects_a_planted_line` (5 linhas plantadas); `edge/...::test_ca11_edge_readme` | passou (ver O-04) |
| CA-12 | `ml/...::test_ca12_invalid_counts_write_nothing` (a a f), `::test_ca12_valid_counts_keep_the_line` | passou |
| CA-13 | `ml/...::test_ca13_invalid_warnings_write_nothing` (a a g), `::test_ca13_valid_warnings_keep_their_lines` | passou |
| CA-14 | `ml/...::test_ca14_second_extension_is_refused_and_writes_nothing`, `::test_ca14_without_the_lists_new_pieces_are_never_in_test`, `::test_ca14_json_without_the_key_makes_the_type_new_again` | passou (ver O-05) |
| CA-15 | `ml/...::test_ca15_split_examples_have_line_continuations`, `::test_ca15_control_the_rules_detect_a_planted_example` (5 exemplos plantados) | passou |
| CA-16 | `infra/...::test_ca16_top_comment_follows_adr_023` (3), `::test_ca16_other_lines_are_identical` (3, com a cópia literal de `cf92f79`) | passou |
| CA-17 | `infra/...::test_ca17_update_block_has_the_order`, `::test_ca17_plan_mentions` (9) | passou (ver O-06) |
| CA-18 (manual, VPS e borda) | Não automatizável. Os passos estão em `docs/deployment-plan.md` §9, "CA manual da SPEC-040" | pendente (humano, depois do deploy) |

## Suíte completa

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
9516 passed, 143 skipped, 1 warning in 912.13s (0:15:12)
(warning preexistente do fastapi.testclient)
(pulados: 108 docker, 26 sem torch, 6 sem broker MQTT, 3 sem modelo real local)

$ env -u TEST_DATABASE_URL -u CI PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker
108 passed, 5 skipped, 9546 deselected, 1 warning in 276.24s (0:04:36)
(a lista de contêineres e a contagem de imagens ficaram iguais antes e depois)

$ CI=true TEST_DATABASE_URL=... uv run pytest -q api/tests --cov=qc_api.services
1331 passed; qc_api/services/alerts.py 99%, spc.py 100%, TOTAL 99%   (RNF-09: >= 80%)

$ uv run ruff check .          -> All checks passed!
$ uv run ruff format --check . -> 298 files already formatted
```

As três execuções com banco ou Docker foram sequenciais, sem outra suíte com banco ao mesmo tempo.

**Não rodou:** os 6 testes do broker MQTT real (`PARTQC_MQTT_TESTS=1`), que ficam fora do CI, e o treino com torch. A SPEC não muda nenhum dos dois: a ponte MQTT herda a §4.1 pelo `HttpPublisher` (§3.2).

## Testes de aceite de SPECs anteriores ajustados (`docs/architecture.md` §10)

Limpeza da §4.11: nenhuma asserção mudou, e nenhum teste foi removido nem renomeado.

| Arquivo | Teste ou trecho | Antes → depois | Requisito |
|---|---|---|---|
| `infra/tests/acceptance/test_spec_015.py` | módulo | `PUBLIC_HOST_RE` e `_env_file_paths`, sem uso → removidos | §4.11 (RV-04 da 039) |
| `edge/tests/acceptance/test_spec_025.py` | comentário em `test_extra_privacy_paths_with_control_characters_keep_code_and_summary` | "printed raw (observation O-01...)" → "printed escaped since SPEC-030 (section 4.5 there)" | §4.11 (RV-05 da 030) |
| `api/tests/acceptance/test_spec_004.py` | módulo | `SPEC016_CONTRACTS`, `SPEC018_CONTRACTS` e `SPEC026_CONTRACTS`, sem uso → removidas. `SPEC021_CONTRACTS` fica, porque o `ALLOWED_EXACT` a cita | §4.11 (observação 5 da 018) |
| `packages/contracts/tests/acceptance/test_spec_016.py` | docstring de módulo | "this file is the current SPEC of `qc-contracts`" → cita só a versão que a SPEC-016 introduziu (0.4.0) | §4.11 (observação 4 da 018) |

Ajustes pela regra da §10: os três primeiros estão na tabela da §3.1. O último não está lá, mas o dev-report o listou, e a falha decorre diretamente da §4.1.

| Arquivo | Teste | Antes → depois | Requisito |
|---|---|---|---|
| `edge/tests/acceptance/test_spec_030.py` | `test_ca09_any_case_jpeg_is_checked_and_other_files_are_invalid` | temporário `.g.jpg.abc123.tmp` (6 caracteres) → `.g.jpg.abc12345.tmp` (4 ocorrências). A intenção continua: o temporário da borda é ignorado | §4.2 |
| `edge/tests/acceptance/test_spec_030.py` | `test_extra_ca09_edge_temporaries_are_ignored` | parâmetros `.a.jpg.abc.tmp`, `.tmp` e `.x.tmp` → `.a.jpg.abcdefgh.tmp`, `.b.JPG.a1_b2_c3.tmp` e `.x.jpeg.00000000.tmp`. Os nomes antigos agora são `invalid`, o que o CA-05 confere | §4.2 |
| `edge/tests/acceptance/test_spec_030.py` | `test_extra_ca02_cap_is_configurable_and_counts_decoded_bytes`, **renomeado** para `test_extra_ca02_cap_is_configurable_and_gzip_is_refused` | segunda metade: corpo `gzip` esperava `response too large` → espera `unsupported response encoding`, e o comentário mudou junto. A primeira metade (teto configurável) não mudou | §4.1 |

Os outros arquivos citados na §3.1 passam sem ajuste: `test_spec_017.py`, `test_spec_013.py`, `test_spec_028.py`, `test_spec_029.py`, `test_spec_009.py` e `test_spec_018.py` (e `test_spec_025.py`, fora o comentário acima). O `test_extra_docs_never_put_the_token_in_argv` também passa como está. A regra mais estrita do CA-11 ficou no arquivo novo.

## Bugs encontrados

Nenhum.

## Observações (não bloqueiam)

- **O-01 (§4.5, aviso nas verificações seguintes).** O aviso cita o primeiro candidato da verificação. Na primeira, é mesmo o lote sem reserva. Numa seguinte, com o envio ainda abandonado, pode ser o próprio lote já reservado (`delivered = false`): reproduzi `lot_id=S-005, source=simulated` na primeira e `lot_id=L-005, source=live` na segunda, com `L-005` já em `alerts_sent`. Isso cumpre a letra da §4.5 ("não foi reservado nesta verificação"). Só que o `api/README.md` diz "o lote é o que ficou sem reserva", o que nesse caso induz a erro. Nada é reservado nem enviado. Fica para o reviewer decidir se o texto muda.
- **O-02 (CA-04, `--fix`).** O `--fix` cria um `manifest.csv.lock` vazio na raiz do dataset, então "nenhum arquivo muda" é verdade para os arquivos existentes, mas não para a lista de arquivos. O lock já existia antes desta SPEC (o mesmo da coleta), e por isso o teste compara os bytes de `raw/`.
- **O-03 (CA-09, redação do token).** No teste direto de `send_message`, chamo `install_token_redaction(token)` antes do envio, e esta é uma leitura minha do CA. Sem o filtro, o `httpx` registra a URL com o token em INFO: confirmei isso num script à parte com `send_message` sozinho, e o código é da SPEC-017, não desta. Em produção esse caminho não ocorre: o único chamador é `run_check`, que instala o filtro antes (`alerts.py:581`), e a subida do laço também (`alerts.py:673`). O teste de `run_check` do CA-09 não chama o `install` e também não mostra o token. Fica para o portão de segurança avaliar a função pública sem o filtro.
- **O-04 (CA-11, "seção da varredura").** O `edge/README.md` não tem um título para a varredura: ela está nos itens numerados da seção "Modo coleta". O teste considera como seção o bloco numerado que contém `python -m qc_edge.privacy`.
- **O-05 (CA-14, "continua no manifest").** As imagens excluídas continuam como linhas do `manifest.csv`, porque o `load_manifest` as exige. Li "continua no manifest" como "não está em `exclusions.csv`", a mesma leitura do dev-report. A outra leitura não pode ser cumprida, porque uma imagem excluída sai do split novo. O CA é testável, então não registrei `SPEC_ISSUE`.
- **O-06 (CA-17, "próximo título").** Considerei título uma linha que começa com `#` ou uma linha inteira em negrito. O bloco termina antes de `Depois de **atualizar o Coolify**`, que não é título, e por isso os 6 passos e os dois parágrafos seguintes ficam dentro dele. Os itens usam `1)` em vez de `1.`, como o dev-report explica, e a ordem é conferida pelo texto.
- **Bytes das URLs do CA-07.** Conferi na SPEC: a terceira URL tem U+2028 e a quarta, NBSP. Os testes as escrevem com escapes.

## Testes exploratórios (além dos critérios)

Todos automatizados (`test_extra_*`) e passando.

**Conferência dos próprios testes (mutação).** Rodei os testes novos contra 24 cópias alteradas do código de produção, no scratchpad, sem tocar no repositório. As alterações incluíram tirar o header `identity`, tirar a recusa, trocar `all` por `any`, tirar o `onerror`, afrouxar o padrão dos temporários, desfazer a ordenação, voltar ao `logger.exception`, trocar `httpx.Request` por `httpx.URL`, tirar as defesas do painel, fixar `abandoned_for_s`, tirar as conferências do CHANGELOG e ignorar `extended_before`. Os testes pegaram as 24.

**Publisher:**

- Socket real em `127.0.0.1` (caminho do `httpcore`): `Accept-Encoding: identity` chega no fio, e a bomba é recusada abaixo de 8 MiB.
- Também são recusados: `x-gzip`, `compress`, `zstd`, `chunked`, `gzip;q=1`, `identity,identity,br`, byte não ASCII, bytes que não são texto e dois headers separados (`identity` e `gzip`).
- São lidos: vazio, espaços, `,` e ` identity , IDENTITY `.
- Lote 413 e heartbeat 200, 201 e 413 com `gzip` viram `PublishTransientError`.
- 401, 403, 500 e 302 com a bomba não mudam, e nenhum bloco é lido. `check_health` com a bomba devolve `True`, sem ler.
- O teto de 512 KiB continua valendo sem codificação.
- Proxy que sempre comprime, 12 ciclos: a linha fica `pending`, com `last_error = unsupported response encoding`, 12 tentativas e conectividade `offline`, sem `dead`.

**Varredura:**

- `raw/` com modo `0o000` e `raw` que é um arquivo saem como `raw: unreadable`. `raw` como link quebrado conta como ausente (código 0).
- Modos `0o000`, `0o300` e `0o100` não mostram os arquivos da pasta. Com `0o400`, cada entrada sai com o próprio caminho, e a subpasta interna também aparece.
- Achados e `unreadable` saem intercalados, na ordem dos caminhos. O `--fix` limpa o resto, não toca na pasta ilegível e mantém o código 1.
- Nome de pasta com quebra de linha não forja linha de log. Nome que não é UTF-8 sai escapado. `--dataset-dir .` dá linhas relativas.
- `is_edge_temporary`: 8 nomes válidos e 18 inválidos (maiúsculas, 7 e 9 caracteres, `-`, `é`, sem ponto inicial, `\n` no fim e no alvo, alvo que não é JPEG, nome vazio).
- O nome gerado de verdade pelo `write_private_file_atomically` (`.jpg`, `.JPG`, `.jpeg`, `.Jpeg`) e 300 nomes reais do `mkstemp` são reconhecidos como temporários.
- O `--fix` não toca em `.x.tmp`.

**Heartbeat:** o laço volta a enviar depois da falha. `_cap` limita a 0 e a `MAX_HEARTBEAT_COUNT`.

**Painel:**

- 19 URLs a mais (ZWJ, BOM, RLO, U+2029, espaço ideográfico, punycode inválido, rótulo de 64 caracteres, `a..b`, IPv6 quebrado, porta dupla, sem host, `ftp://`, NUL, surrogate, tag Unicode). Regra conferida: o que `is_secure_api_url` aceita, o `httpx` monta. A Visão geral não tem exceção com nenhuma delas (a de NUL só na função, porque não cabe em variável de ambiente).
- As 5 páginas de `dashboard/views/` continuam de pé com `https://xn--zz.com`, pela validação e pela defesa em profundidade, sem requisição nem DNS.
- As 7 leituras do `ApiClient` convertem a falha de montagem. A exceção sai com `from None`.
- Erro de rede continua `ApiUnavailable`. `build_request` + `send` mantêm a chave, o timeout e a query.

**Alertas:**

- `GZIP`, `identity, gzip`, `x-gzip`, `zstd`, `compress` e `gzip, gzip` são recusados. `Identity`, ` identity `, vazio e ` , identity` são lidos.
- 400, 429 e 500 com a bomba empilhada não leem o corpo.
- Corpo sem codificação acima do teto continua falhando.
- `abandoned_for_s` cresce entre verificações. O candidato sai numa verificação seguinte, depois que a thread termina. Sem envio abandonado, não há aviso.
- `api/README.md`: os 6 itens da §4.5 e nenhum `.env.api`, `docker compose -f`, `git clone` ou `git pull` na seção.

**CHANGELOG:**

- Valores válidos: inteiro enorme, zero e os 5 graus. Vazios (`null`, `{}`, `[]`, `""`) não geram linha.
- Inválidos: chaves `unknown`, `GOOD`, `good ` e vazia; valores `null`, lista, objeto e `1e3`; campo texto, número ou booleano.
- Avisos recusados: U+2029, U+0085, U+200D, BOM, NUL, tab, surrogate solto, U+00AD e tag Unicode; campo objeto, número, booleano ou `null`; item que não é texto. Lista vazia e texto visível (`##`, CJK, emoji) passam.
- Vários campos inválidos saem na ordem da SPEC, também sem `--append`. `release-notes` não muda.

**Split:**

- JSON ausente, não JSON, não UTF-8, lista, ou chave em formato errado conta como lista vazia, sem traceback.
- `--defer-types` de um tipo já estendido é recusado.
- Tipo estendido na v2 continua "não novo" na v4, mesmo depois de excluir de novo as peças da v3.
- Outro tipo novo ainda exige decisão.
- `extended_before` é só por nome e tem padrão vazio.

**Documentação:** a ordem completa dos 6 passos do bloco, a janela e a regra aditiva, a repetição do CA-18 depois de atualizar o Coolify, os itens de risco (compressão e CDN, com as duas URLs e a data), o passo 3 do DNS, a §8, item 5, e a chave fora do `argv` no CA manual.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
