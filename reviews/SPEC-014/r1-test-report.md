# SPEC-014 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-014](../../docs/specs/SPEC-014-simulador.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `2fb7cf3` (implementação em `1b2a9a6`, `620ee21`, `3beb390`; CA-01 corrigido em `ff3f4b1`) |
| **Veredicto** | **PASS** |

Escrevi os testes a partir da SPEC (caixa-preta), antes de ler a implementação. O arquivo é `scripts/tests/acceptance/test_spec_014.py`, com 104 testes:

- 34 cobrem os CAs. São 16 funções `test_caNN_*`, algumas parametrizadas: CA-03 (3 casos de `--source`), CA-06 (2 casos inválidos), CA-08 (8 casos), CA-13 (401 e 403).
- 70 são exploratórios (`test_extra_*`).

Dois testes exploratórios levam o marcador `db`: eles passam o `MockTransport` à app real (`create_app`) num `TestClient`, sobre o `clean_db`.

O script é carregado com `importlib.util.spec_from_file_location` (§6) e acionado por `main([...], transport=MockTransport(...), sleep=<registrador>, now=<fixo>)`. A API falsa guarda os ids num `dict` e responde `created`/`duplicate`, como na SPEC-004. Para respeitar a R-03 e o checklist §4, a chave do dispositivo é gerada em tempo de execução (`"k" + secrets.token_urlsafe(24)`) e a URL da API falsa (`https://api.partqc.test`) não tem credencial. Nenhum teste usa rede real nem subprocesso.

## Cobertura dos critérios de aceite

Prefixo: `scripts/tests/acceptance/test_spec_014.py::`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_dry_run_prints_valid_simulated_items`: 30 linhas, cada uma `InspectionCreate`, com `source`, `model_version`, `model_sha256` e `device_id` exatos, lotes `SIM-20261001-001…003` com 10 itens cada e `inspected_at` estritamente crescente em UTC. `test_ca01_dry_run_makes_no_request`: 0 requisições e nenhum `sleep` | ✅ |
| CA-02 | `test_ca02_same_seed_same_bytes_other_seed_other_ids`: stdout idêntico byte a byte; com a seed 43, nenhum id em comum; ids únicos e `version == 4` | ✅ |
| CA-03 (R-06) | `test_ca03_source_argument_is_unknown[space, equals, even-simulated]` (`--source live`, `--source=live` e até `--source simulated` → 2, stdout vazio, 0 requisições). `test_ca03_source_argument_is_refused_when_sending`. `test_ca03_thousand_items_with_valid_combinations_are_simulated`: 25 ou mais combinações aleatórias válidas, ≥ 1 000 itens, com `SOURCE=live` e `SIM_SOURCE=live` no ambiente. `test_ca03_generate_returns_only_simulated_items`: 1 000 itens via `parse_args` + `generate` | ✅ |
| CA-04 | `test_ca04_grade_distribution` (10 000 itens; defeituosos 0,20 ± 0,02; `poor` 0,70 ± 0,04; `perfect`/`good`/`fair` 0,40/0,35/0,25 ± 0,03) | ✅ |
| CA-05 | `test_ca05_unknown_fraction_and_nulls` (2 000 itens; `unknown` 0,10 ± 0,03; nulos no modelo e no JSON; `type_confidence < 0.70`) | ✅ |
| CA-06 | `test_ca06_random_lot_sizes_stay_in_range` (5 lotes com 3 a 8 itens), `test_ca06_invalid_lot_size_combinations_exit_2[min-above-max, exclusive-with-lot-size]` | ✅ |
| CA-07 (SPC) | `test_ca07_out_of_control_lots_on_the_p_chart`: agrega por `lot_id` com `is_defective` e passa `LotCounts` a `compute_p_chart(lots, baseline_lots=20, min_lot_size=5)`. Resultado com a seed 42: p̄ = 0,0917; UCL (n = 200) = 0,153; só `024` (p = 0,295) e `028` (p = 0,305) ficam fora; o maior p entre os outros 28 é 0,140 | ✅ |
| CA-08 | `test_ca08_invalid_arguments_exit_2[...]`, com os 8 casos do CA (`0,3`, `11`, `a,b`, `3,3`, `--defect-rate 1.5`, `--unknown-rate -0.1`, `"sim-01\n"`, `"sim-v0\n"`). Cada caso roda com `--dry-run` (código 2, stdout vazio, mensagem no stderr) e no modo de envio (código 2, 0 requisições) | ✅ |
| CA-09 | `test_ca09_start_in_the_future_exits_2_without_requests` (`now + 1 h`, no envio e no `--dry-run`) | ✅ |
| CA-10 (R-05) | `test_ca10_send_then_resend_is_idempotent`. 1ª execução: `GET /health`, depois 3 `POST /batch` com 100, 100 e 50 itens, todos com `X-API-Key`; `sent=250 created=250 duplicate=0`, `lots=10 seed=42 source=simulated`, código 0. 2ª execução: `sent=250 created=0 duplicate=250` e a API continua com 250 registros | ✅ |
| CA-11 | `test_ca11_retries_then_success` (503, depois `ConnectError`, depois 201: código 0, `sleep == [2, 4]`, 250 registros sem duplicata, o mesmo corpo nas 3 tentativas) | ✅ |
| CA-12 | `test_ca12_retries_exhausted_exit_5` (503 sempre: código 5, 4 POSTs, `sleep == [2, 4, 8]`, nada gravado) | ✅ |
| CA-13 | `test_ca13_auth_failure_exit_3_no_more_requests_no_key[401, 403]`: código 3; só `GET /health` e 1 `POST`; nenhum `sleep`; a chave não aparece no stdout, no stderr nem no `caplog` | ✅ |
| CA-14 | `test_ca14_422_exit_4_with_detail` (`{"detail": "x"}` → 4 e `x` no stderr). Repeti com um `detail` aleatório (`detail-<hex>`), que não pode aparecer por acaso numa mensagem | ✅ |
| CA-15 | `test_ca15_missing_key_exits_2_without_requests`, `test_ca15_plain_http_remote_url_exits_2` (`http://api.exemplo.org`), `test_ca15_local_http_url_is_accepted` (`http://127.0.0.1:8001` → 0, requisições para `127.0.0.1:8001`) | ✅ |
| CA-16 (R-04) | `test_ca16_batch_items_have_exactly_the_contract_keys` (corpo `{"items"}` com 1 a 100 itens; cada item tem exatamente as 14 chaves do §3.2, com itens `unknown` e reconhecidos no mesmo envio) | ✅ |

Validação de mutação: rodei os testes contra 14 cópias mutadas de `simulate.py`, todas no scratchpad (o código de produção não foi tocado). Os testes pegam 13 delas:

- `source=LIVE`;
- atrasos `(1, 2, 4)`;
- 401/403 com nova tentativa;
- bloco de 50 itens;
- fator 1,2 no lugar de 3;
- `re.match` no lugar de `re.fullmatch`;
- pesos trocados;
- `http://` remoto aceito;
- headers no erro, o que exporia a chave;
- limite de `--start` relaxado;
- resumo do `--dry-run` no stdout;
- `uuid4()` fora do RNG;
- uma variante do bloco de 50.

A única que sobrevive é `allow_abbrev=True`. Era esperado: não existe nenhuma opção com o prefixo `--sour`, e a SPEC não exige `allow_abbrev`.

## Suíte completa

```text
# sem banco (sem TEST_DATABASE_URL e sem CI)
$ uv run pytest -q
1562 passed, 487 skipped, 1 warning in 165.29s (0:02:45)          exit=0

# com banco (TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test, sem CI)
$ uv run pytest -q
2049 passed, 1 warning in 287.59s (0:04:47)                       exit=0

# só este arquivo: com banco 104 passed; sem banco 102 passed, 2 skipped

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
111 files already formatted
```

As contagens batem: 1945 (dev report) + 104 = 2049, e 1562 + 487 = 2049. O único aviso é o `StarletteDeprecationWarning` do `TestClient`, que já existia antes desta SPEC. Nenhum teste de aceite de SPEC anterior falhou.

## Bugs encontrados

Nenhum dos dois achados afeta um CA. Ambos são de severidade baixa e ficam registrados para o reviewer e o security-devops.

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | baixa | §4.1 (`--api-url`) e códigos de saída | `uv run --package qc-api python scripts/simulate.py --api-url "$(printf 'https://exa\x01mple.com')" --api-key kabc --device-id sim-01 --lots 1 --lot-size 1`. O mesmo acontece com `\t`, `\n`, `\r`, `\x1b` ou `\x7f` no meio do host ou do caminho, por `--api-url` ou por `CLOUD_API_URL`; o `.strip()` só remove esses caracteres nas pontas | Código 2 com mensagem de uso, porque o valor é inválido como URL. O código 1 é reservado para "item gerado inválido" | `httpx.InvalidURL` sem tratamento (levantado por `httpx.Client(base_url=...)` em `send`): traceback no stderr e **código 1**. A chave não aparece no traceback (conferido) |
| T-02 | baixa | §4.3 ("a chave nunca é impressa") e R-03 | `simulate.py --api-url https://h.test --api-keyy <CHAVE> --device-id sim-01`, com a opção digitada errado | Código 2, sem repetir o valor | Código 2 com `error: unrecognized arguments: --api-keyy <CHAVE>` no stderr: o argparse repete a chave. Só acontece com erro de digitação, e o help já recomenda a variável de ambiente. Fica registrado para o security-devops avaliar |

## Testes exploratórios (além dos critérios)

Casos automatizados em `test_extra_*`, todos passando:

| Caso | Resultado |
|---|---|
| Resumo do `--dry-run` no stderr com `sent`, `lots`, `seed` e `source=simulated`, sem `created`/`duplicate`; o stdout só tem JSON Lines | ok |
| Seed aleatória: impressa no resumo, entre 0 e 2³²; reexecutar com ela reproduz a saída | ok |
| Mesma seed com outro `--start`: os mesmos ids, `lot_id` com a nova data e a API responde `duplicate=10` (§4.2) | ok |
| Tempo dos lotes: `--start 2026-09-30T22:00:00-03:00` gera `SIM-20261001-…` (data UTC); 1º item de cada lote em `start + (i−1)·10 min`; passo igual (`10 min / n`) | ok |
| `lot_id` com a data UTC em `+14:00`, `-05:00` e `Z` sem segundos | ok |
| `--start` padrão = `now − lots × 10 min` | ok |
| Limite de `--start`: o último item exatamente em `now + 5 min` é aceito; com 1 µs a mais, código 2 | ok |
| `--start` fora do intervalo (`9999-12-31T23:00Z`, `0001-01-01T00:00+05:00`, `+2026-…`) → 2, sem traceback | ok |
| Regras de cada item (2 000 itens): `latency_ms` em 40..180; `type_confidence` 0,30–0,69 (`unknown`) e 0,75–0,99; `grade_confidence` 0,55–0,95; `grade_score` em [0, 4] e a no máximo 0,4 do índice do grau; `needs_review` exatamente pela regra do §4.2; `screw`/`nut` ≈ 50/50 | ok |
| Fora de controle com `--defect-rate 0.5`: o lote marcado fica 100% defeituoso (`min(1, 3 × 0,5)`), e os outros ficam em torno de 0,5 | ok |
| Taxas extremas: 0 com lote fora de controle (nenhum defeito), 1 (todos defeituosos), `--unknown-rate 1` (todos `unknown`) | ok |
| Mais 22 argumentos inválidos → 2: `--lots 0/501`, `--lot-size 0/1001`, só `--lot-size-min` ou só `--lot-size-max`, min 0, max 1001, `--seed -1/abc`, `--start` sem fuso ou não ISO, `device-id` com unicode, maiúsculas ou curto, `model-version` em maiúsculas ou curto, `--defect-rate nan`, `--unknown-rate 1.01`, `--out-of-control-lots 3,` e `-3`, `--sour live` | ok |
| 9 combinações nos limites aceitas: `--lots 1/500`, `--lot-size 1/1000`, `--out-of-control-lots 1,10`, taxas 0 e 1, faixa 1..1000, `model-version` com ponto, `--seed 0` | ok |
| Valores padrão vindos do ambiente (`CLOUD_API_URL`, `SIM_DEVICE_ID`, `SIM_DEVICE_API_KEY`) usados no envio, sem expor a chave | ok |
| Sem URL → 2; `ftp://`, sem esquema, `http://localhost.evil.test` e `https://` sem host → 2, com 0 requisições | ok |
| `http://localhost:8001/` aceito, e a barra final não duplica no caminho | ok |
| Timeouts: `read` = 90 s no health e 10 s no lote (`request.extensions["timeout"]`) | ok |
| Falha do health (503, 500, `ConnectError`, `ReadTimeout`) → 5, sem nenhum POST | ok |
| 500, 502, `ReadTimeout` e `ConnectError` no lote também geram novas tentativas (`[2, 4, 8]`, 4 POSTs, código 5) | ok |
| 401 no 2º lote: código 3, nenhuma requisição depois, 100 registros gravados (os do 1º lote) | ok |
| 422 com `detail` em lista (formato do FastAPI): código 4, com o conteúdo no stderr | ok |
| Envio com sucesso: a chave não aparece no stdout, no stderr nem no `caplog` | ok |
| `--help` → 0; cita `SIM_DEVICE_API_KEY` e não lista `--source` | ok |
| (`db`) API real: 120 itens criados e depois 120 `duplicate`; a tabela tem 120 linhas, todas com `source='simulated'` (R-05 e R-06 de ponta a ponta) | ok |
| (`db`) API real com chave errada → 3, sem expor a chave | ok |

Sondas manuais (não automatizadas, só informativas):

- **Volume máximo:** `--lots 500 --lot-size 1000 --dry-run` gera 500 000 itens em cerca de 24 s, com código 0.
- **Logs:** o logger `partqc.simulate` usa `propagate=False` e escreve no `sys.stderr`. Por isso, a ausência da chave nos logs do script é verificada pelo stderr capturado; o `caplog` cobre os logs do httpx.
- **Inteiros:** `--lots １０` (dígitos de largura total) e `--lots 5_0` são aceitos como 10 e 50, porque o `int()` do Python aceita esses formatos. É inofensivo, e a SPEC não proíbe.
- **Ano 1:** `--start 0001-01-01T00:00:00+00:00` gera `lot_id` `SIM-10101-001`, porque o `%Y` não completa o ano com zeros nesse caso. Segue a fórmula literal da SPEC; é irrelevante na prática.
- **`now` sem fuso** injetado em `main` levanta `ValueError`. É erro de programação do chamador, aceitável.
- **Chave começando com `-`:** passada como `--api-key -abc…`, dá código 2 ("expected one argument"), sem repetir a chave. Com `--api-key=-abc…` ou pela variável de ambiente, funciona.
- **URLs malformadas que não exigem tratamento:** `https://exa mple.com`, `https://[::1]` e `HTTPS://host` passam na validação e só falhariam na rede, com código 5.

Checklist §4 e `architecture.md` §10:

- nenhum conninfo ou URL com credencial literal no arquivo;
- nenhuma chamada a `subprocess`;
- nenhuma dependência de internet;
- o teste `db` usa o `clean_db` da raiz (sem banco próprio, porque não roda pytest em subprocesso).

Os commits da branch têm o trailer `Agent:` (orchestrator, developer e architect). O commit de `docs/specs/SPEC-014` (`ff3f4b1`) é do architect, e os marcadores de status são do orchestrator.

## SPEC_ISSUE (se houver)

Nenhum novo. O SPEC_ISSUE-1 do dev-report foi resolvido em `ff3f4b1` (CA-01 com `--start 2026-10-01T12:00:00Z` e `now` fixo em `2026-10-01T13:00:00Z`), e o CA-01 passa exatamente como está escrito agora.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
