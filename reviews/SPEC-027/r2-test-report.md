# SPEC-027 — r2 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-027](../../docs/specs/SPEC-027-manutencao-api-banco-simulador.md) |
| Rodada | r2 |
| Tester | tester |
| Commit testado | `acd2e5c` (código do developer da r2 em `00f121e`); testes do tester no commit deste relatório |
| **Veredicto** | **PASS** |

A r2 só muda `_api_url` em `scripts/simulate.py` (SEC-01 do [r1-security-report](r1-security-report.md) = RV-01 do [r1-review-report](r1-review-report.md)). Nesta rodada, eu:

- acrescentei os hosts do SEC-01 como **extras do CA-11**, de recusa e de aceitação, sem mudar o texto do CA nem o `test_ca11_*`;
- corrigi a OBS-04 do r1-test-report (RV-02);
- conferi a correção contra o simulador real, sem rede;
- rodei de novo todos os CAs e a suíte inteira, com e sem banco.

Escrevi os extras a partir da lista do SEC-01 (caixa-preta) e só depois li o diff de `00f121e`. Fronteiras mockadas: a API falsa (`httpx.MockTransport`) e, nos testes de "caminho real", só `socket.create_connection` (detalhe abaixo). Os testes não usam rede, não rodam pytest nem o simulador em subprocesso e não têm credencial literal: chaves, `S` e marcadores vêm de `secrets` em tempo de execução.

## Cobertura dos critérios de aceite

Os testes dos CAs são os mesmos da r1. Rodei todos de novo no `acd2e5c`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `infra/tests/acceptance/test_spec_027.py::test_ca01_apply_on_empty_schema` | ✅ |
| CA-02 | `infra/tests/acceptance/test_spec_027.py::test_ca02_idempotent_runner_and_sql_editor` | ✅ |
| CA-03 | `infra/tests/acceptance/test_spec_027.py::test_ca03_refusals` (10 casos), `::test_ca03_limits_accepted` (2) | ✅ |
| CA-04 | `infra/tests/acceptance/test_spec_027.py::test_ca04_inspection_id_check_mirrors_pydantic_uuid4`, `::test_ca04_model_version_check_mirrors_contract` | ✅ |
| CA-05 | `infra/tests/acceptance/test_spec_027.py::test_ca05_refuses_invalid_rows_with_counts_only` | ✅ |
| CA-06 | `api/tests/acceptance/test_spec_027.py::test_ca06_write_log_uses_the_sqlstate_label` | ✅ |
| CA-07 | `scripts/tests/acceptance/test_spec_027.py::test_ca07_usage_errors_never_echo_the_value` (12), `::test_ca07_help_exits_0_with_usage` | ✅ |
| CA-08 | `scripts/tests/acceptance/test_spec_027.py::test_ca08_readme_and_help_document_the_equals_form`, `::test_ca08_help_keeps_the_equals_form_at_any_width` (4), `::test_ca08_key_starting_with_dash_in_the_equals_form`, `::test_ca08_key_starting_with_dash_in_the_environment` | ✅ |
| CA-09 | `scripts/tests/acceptance/test_spec_027.py::test_ca09_api_url_outside_visible_ascii_is_refused` (7), `::test_ca09_visible_ascii_url_still_sends` (2) | ✅ |
| CA-10 | `scripts/tests/acceptance/test_spec_027.py::test_ca10_lot_numbers_with_more_than_4_digits_exit_2` (2), `::test_ca10_leading_zeros_give_the_same_bytes` | ✅ |
| CA-11 | `scripts/tests/acceptance/test_spec_027.py::test_ca11_no_invalid_usage_exits_with_code_1` (os mesmos 37 `argv` da r1, todos com código 2), mais os extras `test_extra_ca11_sec01_*` da r2 (66 casos, ver abaixo) | ✅ |
| CA-12 (manual) | Não precisa ser refeito (ver "CA-12" abaixo). Amostra de 3 execuções e a suíte inteira com banco, ambas sem falhas | ✅ |

### Extras do CA-11 na r2 (SEC-01)

Todos estão em `scripts/tests/acceptance/test_spec_027.py`. "Recusa" significa: código 2, `invalid --api-url (not shown)` no stderr, sem `Traceback`, 0 requisições na API falsa e nenhum trecho do host, do caminho ou da chave no stdout, no stderr ou no `caplog`.

| Teste | Hosts | Esperado | Casos |
|---|---|---|---|
| `test_extra_ca11_sec01_hosts_are_refused_with_code_2` | `https://exa..mple.com`, `https://.example.com`, `https://example.com..`, `https://<64×a>.example.com`, `https://<64×a>` | recusa | 5 |
| `test_extra_ca11_sec01_marked_hosts_are_refused_without_echo` | os mesmos formatos, mais `x.<m>..` e `1.2.3..<m>`, com um marcador `m` e um caminho gerados (`/<marcador>`) | recusa, sem eco do marcador nem do caminho | 7 |
| `test_extra_ca11_sec01_hosts_in_cloud_api_url_are_refused` | os 5 do primeiro teste, em `CLOUD_API_URL` | recusa | 5 |
| `test_extra_ca11_sec01_valid_hosts_still_send` | `https://example.com.`, `https://<63×a>.example.com`, `https://<63×a>`, `https://[::1]`, `https://[::1]:8443`, `https://xn--nxasmq6b.com`, `https://xn--1-zhc.com`, `http://localhost:8001`, `http://localhost`, `https://localhost`, `http://127.0.0.1:8001`, `http://127.0.0.1` | código 0, exatamente 1 lote enviado, ao `raw_host` e à porta da URL | 12 |
| `test_extra_ca11_sec01_real_path_refuses_before_the_socket` | os 5 de recusa, com o **transporte real** do httpx | código 2, sem `Traceback`, nenhuma chamada ao socket | 5 |
| `test_extra_ca11_sec01_real_path_valid_hosts_reach_the_socket` | os 12 de aceitação e os 3 "estranhos, mas usáveis" da OBS-04 (`-bad-.example.org`, porta vazia e host de 403 caracteres), com o transporte real | código 5 (erro de rede), sem `Traceback`, e exatamente 1 chamada ao socket com o `raw_host` | 15 |
| `test_extra_ca11_sec01_premise_the_socket_codec_decides` | os 5 de recusa e os 12 de aceitação | o `socket.getaddrinfo` real levanta `UnicodeError` exatamente nos 5 de recusa | 17 |

**Como o "caminho real" funciona sem rede.** O `httpx.MockTransport` não passa pelo socket, e é por isso que a r1 não viu o defeito (RV-02). Nos testes de caminho real, `main` roda **sem** `transport=`, então o simulador monta o próprio `httpx.Client` com o transporte de verdade, e o httpcore chama `socket.create_connection`. Só essa função é trocada por uma falsa, que:

1. chama o `socket.getaddrinfo` **real** com `AI_NUMERICHOST`. Ele aplica ao host a mesma codificação `idna` (em C) de uma conexão real e levanta `UnicodeError` para os hosts do SEC-01, mas nunca consulta o DNS;
2. recusa a conexão (`ConnectionRefusedError`), então um host aceito termina em erro de rede, com código 5.

As variáveis de proxy são removidas, para que o host da conexão seja o da URL.

**O teste da premissa** usa o mesmo `getaddrinfo` real. Ele mostra que a conferência da r2 recusa exatamente o que o socket recusaria e nada além disso.

**Caso `xn--1-zhc.com` (escolha do `raw_host`).** É o domínio IDNA 2008 `א1.com`. A forma Unicode, que o httpx devolve em `.host`, viola a regra bidi do IDNA 2003 do codec (`Violation of BIDI requirement 3`). A forma ASCII, que é a que o socket recebe, passa. Com isso, o caso distingue a correção pedida (`raw_host`) da sugerida no RV-01 (`.host`). O `xn--nxasmq6b.com` citado no SEC-01 não faz essa distinção: o codec aceita as duas formas dele.

**Validação por mutação** (cópia da árvore no scratchpad, por `git archive`, sem tocar no repositório):

| Mutação de `scripts/simulate.py` | Resultado nos 164 testes do arquivo |
|---|---|
| Versão anterior à r2 (`00f121e^`, sem a conferência nova) | 22 falhas: todos os testes de recusa (5 + 7 + 5) e os 5 de caminho real. Esses 5 falham com `UnicodeError: encoding with 'idna' codec failed`, que é exatamente o SEC-01 |
| Conferência com `.host` no lugar do `raw_host` | 2 falhas: `…valid_hosts_still_send[xn-label-rtl-digit]` e `…real_path_valid_hosts_reach_the_socket[xn-label-rtl-digit]` (recusa falsa) |
| Código da r2, sem mutação | 164 passed |

### Ajustes nos meus extras da r1

Todos ficam no mesmo arquivo. Nenhum teste de CA mudou.

- **`test_extra_ascii_urls_that_httpx_rejects_exit_2`:** na r1, ele aceitava código 0 **ou** 2 para 11 URLs. Esse foi o ponto cego da OBS-04. Agora ele fixa o código de cada caso:
  - `xn--zz.com`, `[::1`, `[zz]/`, porta `99999` e porta `-1` dão recusa;
  - os 3 hosts do SEC-01 que estavam nele (`exa..mple.com`, `.example.com` e o rótulo de 64) passaram para os extras do CA-11;
  - os 3 aceitos (`-bad-.example.org`, porta vazia e host de 403 caracteres) foram para o novo `test_extra_odd_but_usable_ascii_urls_still_send`, que exige código 0 e 1 lote enviado.
- **`test_extra_more_bad_lot_lists_exit_2`:** os ids a partir de `+7` estavam deslocados (o rótulo `trailing-space` caía em `+7`). Corrigi os ids, e `7 7` passou a se chamar `inner-space`. Os valores e as asserções não mudaram.

## Suíte completa

```text
uv run ruff check .                 -> All checks passed!
uv run ruff format --check .        -> 116 files already formatted

uv run pytest -q (sem TEST_DATABASE_URL)
  -> 2173 passed, 642 skipped, 1 warning in 175.42s (0:02:55)

TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
  -> 2815 passed, 1 warning in 343.99s (0:05:43)

Só os 3 arquivos de aceite desta SPEC, com banco:
  -> 219 passed, 1 warning in 10.49s

Testes de aceite desta SPEC (tester): 219 (eram 156 na r1)
  infra/tests/acceptance/test_spec_027.py    48 (17 de CA + 31 extras), todos db, sem mudança
  api/tests/acceptance/test_spec_027.py       7 (1 de CA + 6 extras), todos db, sem mudança
  scripts/tests/acceptance/test_spec_027.py 164 (33 de CA + 131 extras), sem banco
    r2: +66 extras do CA-11 (SEC-01); o extra de URLs ASCII da r1 passou de 11 para 5 + 3 casos (-3)
```

As contagens batem com o dev-report: 2110 + 63 sem banco e 2752 + 63 com banco. O único aviso é o `StarletteDeprecationWarning` do `fastapi.testclient`, que já existia. Depois das execuções, o servidor de teste tem só `partqc_test`, `postgres`, `template0` e `template1`, então o banco temporário `partqc_test_acc027` foi removido.

## CA-12: não precisa ser refeito

O CA-12 deu 30 de 30 na r1, depois do commit `efe5d8f`. Desde esse commit até o `acd2e5c`, `git diff --stat efe5d8f..HEAD -- api/ packages/ infra/ uv.lock pyproject.toml` não mostra nenhum arquivo. Não mudaram o teste da SPEC-004, a API, o contrato, as migrações nem as dependências. A r2 só toca `scripts/simulate.py` e `scripts/tests/`, que não fazem parte do caminho desses testes. Por isso, as 30 execuções da r1 continuam valendo para o código atual.

Como conferência barata, rodei 3 vezes `uv run pytest -q api/tests/acceptance/test_spec_004.py -k "real_server"` com banco. As 3 deram `2 passed, 79 deselected`, entre 2,98 s e 3,32 s. A suíte inteira com banco (acima) também passou com esses dois testes incluídos. O diagnóstico e a correção da §4.4 estão no [r1-test-report](r1-test-report.md) e não mudaram.

## Conferência contra o simulador real, sem rede (manual, fora da suíte)

Rodei o `scripts/simulate.py` como processo próprio, com `unshare -rn`, que cria um namespace de rede sem nenhuma interface além do loopback desligado. Usei `SIM_DEVICE_API_KEY` gerada por `secrets`, `SIM_DEVICE_ID=sim-01` e `--lots 1 --lot-size 2 --seed 1`. O script de apoio ficou no scratchpad da sessão, fora do repositório.

| `--api-url` | `00f121e^` (antes da r2) | `acd2e5c` (r2) |
|---|---|---|
| `https://exa..mplemark.invalid/pathtok` | `exit=1`, traceback, `encoding with 'idna' codec failed` | `exit=2`, `invalid --api-url (not shown)` |
| `https://.examplemark.invalid/pathtok` | `exit=1`, traceback | `exit=2` |
| `https://examplemark.invalid../pathtok` | `exit=1`, traceback | `exit=2` |
| `https://<64×q>.examplemark.invalid/pathtok` | `exit=1`, traceback | `exit=2` |
| `https://<64×q>` | `exit=1`, traceback | `exit=2` |
| `https://examplemark.invalid./pathtok`, `https://<63×q>.examplemark.invalid`, `https://[::1]`, `https://xn--nxasmq6b.com`, `https://xn--1-zhc.com`, `http://localhost:8001`, `http://127.0.0.1:8001`, `https://-bad-.examplemark.invalid` | — | `exit=5`, `health check failed: ConnectError` |

Em nenhum caso da r2 o stderr teve `Traceback`, `examplemark`, `pathtok`, `qqqq` ou a chave.

## Correção da OBS-04 do r1-test-report (RV-02)

O texto da r1 dizia: "hosts ASCII sintaticamente estranhos (`-bad-`, `..`, rótulo com mais de 63 caracteres) passam por `_api_url`. Com a API real, terminariam em erro de rede (código 5), não em código 1 nem em traceback". **Esse texto estava errado.** A frase "nunca saem com código 1" só tinha sido verificada com o `httpx.MockTransport`, que não passa pelo socket.

Texto corrigido, conferido acima com a API falsa, com o transporte real e com o processo real sem rede:

- **No código da r1:** um host com rótulo vazio (`exa..mple.com`, `.example.com`, `example.com..`, `1.2.3..4`) ou com mais de 63 caracteres passava por `_api_url`. Na primeira requisição real, o codec `idna` do socket levantava `UnicodeError`, que saía com **código 1 e traceback**, sem mostrar o host, o caminho nem a chave. Com a API falsa, o resultado era código 0. Esse é o SEC-01 = RV-01.
- **No código da r2 (`00f121e`):** esses hosts são recusados em `_api_url`, com código 2 e `invalid --api-url (not shown)`, antes de qualquer requisição.
- **`-bad-.example.org`, `a-.com`, `_dmarc.example.com`, porta vazia, `0x7f.1` e hosts com mais de 253 caracteres no total**, mas com rótulos de até 63: o httpx e o codec aceitam, e a conferência não os recusa. Com a API real, terminam em erro de rede (código 5), sem traceback. Com a API falsa, terminam em código 0. Para esses casos, a frase da r1 sobre o código 5 vale. A SPEC não pede validação de sintaxe DNS além do que o cliente e o socket exigem.

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Além dos extras automatizados acima, rodei `main` em processo, com o transporte real e o mesmo `socket.create_connection` falso, sobre o código da r2. Nenhum caso deu código 1, exceção ou traceback.

| URL | Código | Observação |
|---|---|---|
| `https://Exa..Mple.com`, `https://1.2.3..4`, `https://[::1]..`, `https://..`, `https://.` | 2 | `invalid --api-url (not shown)`, sem chegar ao socket |
| `https://256.1.1.1`, `https://xn--.com`, `https://xn--a.com` | 2 | o httpx recusa (conferência da r1) |
| `http://localhost.` | 2 | `http://` só vale para `localhost`/`127.0.0.1` exatos (regra da SPEC-014) |
| `https://[fe80::1%25eth0]`, `https://[::ffff:127.0.0.1]`, `https://EXAMPLE.COM` (vira `example.com`), `https://localhost.`, `https://example.com:0`, `https://example.com.:8443/p` | 5 | chegam ao socket e terminam em erro de rede |
| 4 e 5 rótulos de 63 caracteres (255 e 319 caracteres no total) | 5 | o codec só limita cada rótulo; o resolvedor recusaria o nome, o que também dá erro de rede, código 5 |
| `https://0x7f.1`, `https://a-.com`, `https://_dmarc.example.com`, `https://%2e%2e.com`, `https://exa%2e%2emple.com` | 5 | ASCII aceito pelo codec, que o socket recebe como está |

**Observações (não são bugs):**

- **OBS-R2-01:** `https://%2e%2e.com` não é decodificado para `...com` pelo httpx: o host chega ao socket com o `%`. O DNS recusa e o resultado é código 5, então o §4.3.5 continua cumprido.
- **OBS-R2-02:** a conferência da r2 reproduz o codec do Python 3.12.15 (R-12). O teste da premissa falha se uma versão futura do codec mudar de comportamento para esses hosts. Esse é o mesmo risco do SEC-04 do security-report, agora coberto por teste.

As OBS-01, OBS-02, OBS-03 e OBS-05 do r1-test-report continuam válidas. A OBS-04 foi substituída pela correção acima.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção. Só alterei `scripts/tests/acceptance/test_spec_027.py` e este relatório. As cópias da árvore usadas na mutação e os scripts da conferência manual ficaram no scratchpad da sessão, fora do repositório.
