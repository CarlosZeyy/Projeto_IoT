# SPEC-030 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-030](../../docs/specs/SPEC-030-manutencao-borda-publisher-privacidade.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `origin/main...f96c41a` (10 commits, de `84045fc` a `f96c41a`) |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante ou alto. Há 5 achados baixos, que não bloqueiam, e nenhum `SPEC_ISSUE`.

Conferências que rodei (só leitura):

- `CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q`: `5707 passed, 52 skipped, 1 warning` (os 52 são os `docker`), a mesma contagem do test-report;
- `uv run ruff check .` (`All checks passed!`) e `uv run ruff format --check .` (`224 files already formatted`);
- busca de segredos nas linhas adicionadas do diff (`secret`, `token`, `password`, `postgres://`, `eyJ` e a regex do CA-06): só aparecem `secrets.token_*` gerados em tempo de execução, as concatenações do `test_extra_ca06_*` e a URL do banco de teste local, sem senha, nos relatórios.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `edge/src/qc_edge/publisher.py:210` (O-01 do test-report) | Confirmo a O-01. O teto de 512 KiB vale para os bytes **decodificados** (`iter_bytes`, como a §4.1 manda), mas o `httpx` pede `Accept-Encoding: gzip, deflate` e descomprime cada bloco bruto inteiro antes da primeira conferência. Um servidor hostil com `Content-Encoding: gzip` faz um bloco de 64 KiB virar ~64 MiB na memória (pico medido pelo tester: ~141 MiB), e esse pico não cresce com o corpo. O risco é baixo: a URL é só HTTPS ou loopback, e o servidor é a própria API. Não é bug contra a SPEC. | Nada nesta SPEC. A severidade final fica com o portão de segurança. Registrar para uma SPEC futura da borda: mandar `Accept-Encoding: identity` no `publish_batch` (e no `check_health`), ou contar o teto pelo `iter_raw`. |
| RV-02 | baixa | `edge/src/qc_edge/privacy.py:130` (O-03 do test-report) | Uma subpasta de `raw/` que o `os.walk` não consegue listar (sem `onerror`) é pulada em silêncio: as fotos dela não são varridas, e o código pode ser `0`. O comportamento vem da SPEC-025, e a §4.5 desta SPEC fala só de **arquivo** ilegível, então está fora do escopo. A mitigação é natural: um backup feito com o mesmo usuário também não consegue ler essa pasta. | Registrar para uma SPEC futura da borda: `os.walk(..., onerror=...)` listando `<pasta>: unreadable` e deixando o código em `1`, como o arquivo ilegível da §4.5. |
| RV-03 | baixa | `edge/src/qc_edge/privacy.py:118-120` (O-02 do test-report) | A exceção dos temporários vale para qualquer nome que comece com `.` e termine com `.tmp`, inclusive `.tmp` sozinho e `.x.tmp`, e não só para o padrão do `mkstemp` (`.<nome>.<aleatório>.tmp`). Um arquivo copiado à mão com esse formato de nome não seria varrido nem acusado. É exatamente o texto da §4.4 (decisão (c) do Histórico), e o `find ml/data/raw -type f ! -name '*.jpg'` do `docs/dataset-protocol.md` §8 ainda listaria o arquivo. | Nada nesta SPEC. Se o humano quiser fechar, uma SPEC futura pode restringir a exceção ao padrão do `mkstemp`, por exemplo `^\..+\.[A-Za-z0-9_]{8}\.tmp$`, conferido contra `collect.write_private_file_atomically`. |
| RV-04 | baixa | `docs/dataset-protocol.md:138` e `:172` | O passo 1 da §8 traz a mitigação temporária **"Até o merge da SPEC-030"**: conferir o `echo $?` e o `find ... ! -name '*.jpg'`, e "só copie para `raw/` arquivos renomeados para `.jpg` em minúsculas". Depois do merge, o texto fica desatualizado: a varredura passa a conferir `.JPG`/`.jpeg` e a acusar os outros arquivos, e o resumo não pode mais ser forjado. O arquivo está fora da §3.1, então o autor não podia mexer nele, e o texto se autolimita ("até o merge"). | Num commit `docs` do architect, ou no commit de `Done` pelo orquestrador, se o ADR-019 permitir: trocar o trecho por uma frase que diga que, desde a SPEC-030, basta o código de saída da varredura. O `find` pode continuar como conferência opcional (ver RV-03). |
| RV-05 | baixa | `edge/tests/acceptance/test_spec_025.py:2685` | O comentário `the name itself is printed raw (observation O-01 of the r1 test report)` ficou falso com a §4.5: agora o nome sai escapado. O tester fez certo em não tocar, porque a §4.6 limita as edições nesse arquivo, e o comentário não é asserção. | O tester da próxima SPEC que tocar `test_spec_025.py` pela regra do §10 atualiza o comentário. Sem ação agora. |

## Pontos pedidos pelo orquestrador

### Ajustes do tester em `test_spec_009.py` e `test_spec_025.py` (§4.6 e `docs/architecture.md` §10)

Conferi o diff linha a linha (`git diff origin/main...HEAD -- edge/tests/acceptance/test_spec_009.py edge/tests/acceptance/test_spec_025.py`). Todas as mudanças estão na tabela do test-report, e não há nenhuma fora dela.

| Ajuste | Conferência |
|---|---|
| `test_spec_009.py:1024-1026` (constantes `CREDENTIAL_PASSWORD` e `CREDENTIAL_URL`) e `:1040` (`pytest.param(CREDENTIAL_URL, id="credential-in-url")`) | ✅ §4.6, item 1. A senha vem de `secrets.token_hex(8)`, e a URL é montada por concatenação, que a regex do CA-06 não pega. O `id` fixo evita que a senha entre no node id. O `import secrets` já existia. |
| `test_spec_009.py:1063-1064` (`if url == CREDENTIAL_URL: assert CREDENTIAL_PASSWORD not in text`) | ✅ §4.6, item 1, literal ("as asserções que procuram o valor no log passam a procurar a senha gerada"). A intenção se mantém: a URL com credencial é recusada sem eco do segredo. As outras 8 URLs do `parametrize` e as outras asserções não mudaram. |
| `test_spec_025.py:1317-1319` (`_collected` tira também `PYTEST_ADDOPTS`, `PYTEST_PLUGINS` e `PYTEST_CURRENT_TEST`) | ✅ §4.6, item 2 (RV-08). `MAIN_COLLECTED` não mudou. O CA-12 da SPEC-030 mostra o teste vermelho antes e verde depois. |
| `test_spec_025.py:2650-2652` (`checked 4 …, 3 …` → `checked 6 …, 5 …`, mais as linhas de `notes.txt: invalid` e `upper.JPG: app1`) | ✅ §4.6, item 2, literal. O nome do teste não mudou. O `invalid` de `e.jpg`, o código 1 e o `--fix` que não toca o `invalid` continuam conferidos. |

Nenhum `test_caNN_` foi removido nem renomeado, e nenhuma outra linha dos dois arquivos mudou.

### Decisão do autor sobre o `check_health` com `stream`

Concordo. A §4.1 diz que o `check_health` "continua sem chave e só olha o status; não lê o corpo", mas o `client.get` de antes lia o corpo inteiro, sem teto. Trocar por `client.stream("GET", ...)` e devolver só `status_code == 200` cumpre o texto da SPEC, sem ampliar o escopo, e fecha o mesmo vetor do teto (um health com corpo enorme). O dev-report registra a decisão, e o `test_check_health_never_reads_the_body` (autor) e o `test_extra_ca01_check_health_never_reads_the_body` (tester) a cobrem com 0 blocos lidos.

Um efeito colateral sem impacto: fechar uma resposta HTTP/1.1 sem ler o corpo descarta a conexão, em vez de devolvê-la ao pool. Isso vale também para 401, 403, 3xx e 5xx no `publish_batch`. O custo é um handshake TLS a mais por health check ocioso (um a cada 60 s) ou por erro, o que é desprezível. Não é achado.

### Observações O-01 a O-04 do test-report

- **O-01:** confirmada; é o RV-01 (baixa), para o portão de segurança.
- **O-02:** confirmada; é o RV-03 (baixa). Segue o texto da SPEC.
- **O-03:** confirmada pela leitura do `_files` (o `os.walk` sem `onerror`); é o RV-02 (baixa). Vem da SPEC-025 e está fora do escopo.
- **O-04:** sem achado. Com um corpo vazio, o `iter_bytes` não entrega bloco, e a conferência do prazo não roda. A requisição já terminou, então nada fica pendurado, e um 2xx vazio cai no `_parse_results` como antes. Pela §7, o prazo é conferido "entre blocos", e o mesmo vale para os status cujo corpo não é lido. É o comportamento especificado.

### R-02, R-03, R-05, R-07 e R-14

- **R-02:** ✅. O corpo do `publish_batch` continua sendo só o `BatchCreate` JSON, e o `check_health` é um `GET` sem corpo. A varredura de privacidade não abre conexão (docstring do módulo e nenhum import de rede). Nenhuma rota nova.
- **R-03:** ✅. Não há credencial literal em URL em `edge/` (CA-06 verde, e conferi a busca no diff). As mensagens `request deadline exceeded` e `response too large` são constantes (`publisher.py:55-56`) e não citam URL, chave nem corpo, o que os CA-01 e CA-02 conferem na cadeia inteira da exceção. Não há variável nova, então o `.env.example` não muda.
- **R-05:** ✅. O prazo e o teto levantam `PublishTransientError`, que o laço trata como retry (`offline`, `mark_retry`). O CA-03 confirma 3 `pending` com `attempts=1` e depois 3 `sent`, com 3 ids únicos. Um 413/422 acima do teto vira retry, nunca `dead` (§7, `test_extra_ca02_refusal_above_the_cap_is_a_retry_not_dead`).
- **R-07:** ✅. Todos os 10 commits têm o trailer `Agent:`. Os do `developer` (`f3571e3`, `9ee49b0`, `aa2cdc1`, `51b576a`, `bf66151`, `df4fa74`) tocam só `edge/src`, `edge/tests` (fora de `acceptance/`), `edge/README.md` e o dev-report. O do `tester` (`c8f7313`) toca só `edge/tests/acceptance/` e o test-report. Os do `orchestrator` (`84045fc`, `3eeff9e`, `f96c41a`) tocam só o status em `docs/plan.md` e nas SPECs 029 e 030. Não sou autor de nenhum deles.
- **R-14:** ✅. A varredura passa a conferir `.jpg`/`.jpeg` em qualquer caixa e a acusar o resto (`invalid`, sem ler). Os nomes saem escapados, de modo que um nome não forja o resumo nem o código. O arquivo ilegível deixa o código em `1`. Os JPEGs dos testes são sintéticos, montados no próprio teste. A lacuna da pasta ilegível (RV-02) é anterior a esta SPEC.

## Rastreabilidade (CA → implementação → teste de aceite)

| CA | Implementação | Teste de aceite (exercita de fato) |
|---|---|---|
| CA-01 | `publisher.py:166-219` (`stream`, `_read_body`, prazo antes do teto) | `test_ca01_slow_body_exceeds_the_deadline`: ≤ 5 blocos, resposta fechada, sem URL nem chave |
| CA-02 | `publisher.py:153-156` (`ValueError`) e `:200-219` (teto) | `test_ca02_body_above_the_cap_is_too_large` (≤ 9 blocos), `test_ca02_large_fastapi_422_keeps_the_summary`, `test_ca02_non_positive_deadline_or_cap_is_value_error` |
| CA-03 | `publish_loop.py` (transitório → `_Unreachable` → `mark_retry`) | `test_ca03_deadline_is_a_retry_and_nothing_is_lost` |
| CA-04 | `outbox.py:176-198` (`fetch_due` com `max_delay_s`, SQL parametrizado) e `publish_loop.py:158` | `test_ca04_retry_is_not_held_by_a_clock_jump_back`, `test_ca04_exactly_max_delay_ahead_is_not_due` |
| CA-05 | `publish_loop.py:195-203` (`0 <= diff < health_every_s`) | `test_ca05_health_check_after_a_clock_jump_back` |
| CA-06 | `edge/tests/test_cli_cloud.py:245-262` (autor) e `test_spec_009.py` (tester, §4.6) | `test_ca06_no_credential_literal_in_edge_urls` (regex da SPEC em `git ls-files edge`) |
| CA-07 | `edge/tests/test_publisher_real_api.py` (`TestClientTransport`) | `test_ca07_real_api_test_has_no_private_transport_attribute` (`ast`) e `test_ca07_real_api_test_passes_on_the_database` (banco próprio `<base>_acc030`) |
| CA-08 | idem | Manual, registrado no test-report com as saídas (`3 passed` com `httpx2`, contraprova `3 failed`, `ModuleNotFoundError` depois do `--locked`, `uv.lock` intacto) |
| CA-09 | `privacy.py:113-142` (`is_jpeg_name`, `is_edge_temporary`, `_files`) e `:176-208` (`scan`) | `test_ca09_any_case_jpeg_is_checked_and_other_files_are_invalid` |
| CA-10 | `privacy.py:74-97` (`printable_path`) e o seu uso em `ImageFinding.line`, `scan` e `_fix` | `test_ca10_control_characters_are_escaped`, `test_ca10_a_name_that_is_not_utf8_is_escaped` |
| CA-11 | `privacy.py:186-190` (ramo `OSError`) | `test_ca11_unreadable_file_is_listed` |
| CA-12 | `test_spec_025.py:_collected` (tester, §4.6) | `test_ca12_pytest_addopts_does_not_break_the_spec_025_count` |

Os testes não são tautológicos. Os mocks ficam só nas fronteiras da §6 (nuvem, relógio de parede, `monotonic`, RNG), e o SQLite e o sistema de arquivos são reais. O tester registrou os CA-06 e CA-12 falhando antes dos ajustes e passando depois.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Todos os requisitos das §4.1 a §4.6 foram implementados, e nada além deles. A troca do `check_health` para `stream` cumpre o texto da §4.1. O `DEFAULT_MAX_DELAY_S` de `outbox.py` existe só para evitar o import circular, e o `test_default_max_delay_matches_the_backoff_cap` o amarra ao `MAX_DELAY_S`. O dev-report tem a rastreabilidade. Nenhum CA foi alterado. Nenhuma reaprovação de SPEC nesta branch: os commits na SPEC-030 só mudam `Status` e `Rodada`. |
| 2. Regras inegociáveis | ✅ | R-01: nenhuma dependência nova (sem mudança em `pyproject.toml` nem `uv.lock`). R-02, R-03, R-05, R-07 e R-14: ver acima. R-04: nenhum payload mudou. R-06 e R-11: N/A. R-12: sem mudança de dependências. R-13: os 10 commits são de `Carlos Moises <179777237+CarlosZeyy@users.noreply.github.com>` e seguem Conventional Commits. |
| 3. Corretude | ✅ | O prazo usa `time.monotonic` (injetável), e o salto do relógio é tratado no relógio de parede (`fetch_due` com horizonte em `now + max_delay_s`; a comparação de texto é correta porque o `format_timestamp` tem largura fixa e microssegundos). `0 <= diff` no health check. `response.close()` antes de levantar. Um `httpx.HTTPError` durante a leitura continua transitório. O SQL é parametrizado. Escapes cobrem `Cc`/`Cf`/`Cs`/`Zl`/`Zp` com hexadecimal minúsculo, e o `\` também, para não haver ambiguidade. A ordem segue o caminho original. Achados baixos: RV-01, RV-02 e RV-03. |
| 4. Testes | ✅ | Test-report PASS, cobrindo os 12 CAs (o CA-08 manual está registrado). Os ajustes do §10 estão todos na tabela e são justificados pela §4.6 (ver acima). Nenhum teste roda a suíte inteira: o CA-07 roda um arquivo explícito num banco próprio com `test` no nome, e o CA-12 roda um arquivo explícito sem banco. O teste do autor com nome não UTF-8 roda só a CLI em subprocesso. Nenhuma rede externa. Nenhuma credencial literal em URL (CA-06). Achado baixo: RV-05. |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos. Type hints nas funções públicas novas (`printable_path`, `is_jpeg_name`, `is_edge_temporary`, `fetch_due`). Sem `print` e sem código morto (o `IMAGE_SUFFIX` e o `_images` antigos saíram). `edge/README.md` atualizado nas duas seções exigidas, e as docstrings dos módulos também. Achado baixo: RV-04 (texto temporário do `dataset-protocol.md`, fora da §3.1). |
| 6. Segurança | N/A | A SPEC tem a tag `security`, mas o portão de segurança é feito por outro agente (`r1-security-report.md`). Os RV-01 a RV-03 ficam como insumo para ele. |

## Pontos positivos

- O `_read_body` é curto e fácil de auditar. A ordem das conferências (prazo, depois teto) está documentada, e as duas mensagens são constantes do módulo.
- A decisão de manter o relógio de parede, com o horizonte `now + max_delay_s`, resolve o salto sem invalidar os CAs da SPEC-009. Ela também cobre o caso simétrico das linhas criadas enquanto o relógio estava adiantado.
- O `TestClientTransport` usa só a API pública do `TestClient` e foi validado com e sem o `httpx2`, com contraprova da versão antiga, pelo autor e pelo tester (CA-08).
- O test-report é exemplar: tabela do §10 completa, exploração extensa (tabela do `printable_path` de U+0000 a U+2FFF, FIFO, pipe real, OSC) e as observações O-01 a O-04 bem delimitadas como fora do escopo.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
