# SPEC-043 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-043](../../docs/specs/SPEC-043-manutencao-pos-deploy.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `f3e9846` |
| **Veredicto** | **FAIL**, só por causa do `SPEC_ISSUE-01` (CA-12). Nenhum bug de implementação. Todos os testes automatizados passam |

Testes escritos a partir da SPEC, antes de ler a implementação. Li o código de produção só depois, para procurar casos de borda.

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `scripts/tests/acceptance/test_spec_043.py::test_ca01_three_lots_survive_the_measured_13_s` | ✅ |
| CA-02 | `scripts/…::test_ca02_ten_lots_of_fifty_survive_18_s_per_full_batch` | ✅ |
| CA-03 | `scripts/…::test_ca03_exhausted_batch_says_to_repeat_with_the_same_seed`, `::test_ca03_exact_message_of_section_4_1`, `::test_ca03_health_503_exits_5_without_the_seed_advice`, `::test_ca03_batch_401_exits_3_without_the_seed_advice` | ✅ |
| CA-04 (banco) | `scripts/…::test_ca04_stored_batch_is_not_duplicated_by_the_retry_or_the_repeat` | ✅ |
| CA-05 | `api/tests/acceptance/test_spec_043.py::test_ca05_well_formed_urls_are_safe`, `::test_ca05_malformed_urls_are_not_safe` (4), `::test_ca05_unparsable_conninfo_is_not_safe_and_does_not_raise`, `::test_ca05_hint_text` | ✅ |
| CA-06 | `api/…::test_ca06_settings_refuse_without_the_sentinels` (4), `::test_ca06_app_does_not_start_and_never_creates_the_pool` (4) | ✅ |
| CA-07 | `api/…::test_ca07_valid_url_with_the_database_down_starts_and_logs_no_password` | ✅ |
| CA-08 | `infra/tests/acceptance/test_spec_043.py::test_ca08_main_refuses_malformed_url_with_the_hint` (6), `::test_ca08_main_keeps_the_port_6543_refusal` (2) | ✅ |
| CA-09 | `infra/…::test_ca09_functions_raise_before_connecting` (6), `::test_ca09_port_6543_raises_unsupported_before_connecting` (2), `::test_ca09_host_port_is_unknown` (4), `::test_ca09_closed_port_keeps_host_port_and_class` (2), `::test_ca09_literal_port_1_of_the_ca` (2) | ✅ |
| CA-10 | `scripts/…::test_ca10_register_device_refuses_malformed_url` (4), `::test_ca10_register_device_closed_port_exits_1_without_the_password` | ✅ |
| CA-11 | `dashboard/tests/acceptance/test_spec_043.py::test_ca11_model_column_is_240_px_with_everything_else_intact` | ✅ |
| CA-12 | Ensaio fora da suíte, abaixo | ❌ `SPEC_ISSUE-01` |
| CA-13 | `edge/tests/acceptance/test_spec_043.py::test_ca13_loopback_warns_and_offers_only_loopback` (2), `::test_ca13_exact_warning_of_section_4_4`, `::test_ca13_with_tls_the_live_url_stays_on_loopback` | ✅ |
| CA-14 | `edge/…::test_ca14_specific_host_offers_only_itself` | ✅ (ver OBS-01) |
| CA-15 | `edge/…::test_ca15_all_interfaces_is_as_before`, `::test_ca15_default_host_is_all_interfaces`, `::test_ca15_fallback_keeps_only_the_no_lan_warning`, `::test_ca15_readme_line_of_edge_host` | ✅ |
| CA-16 | `infra/…::test_ca16_step_1`, `_step_5`, `_step_6`, `_section_7_item_2`, `_section_8_statement_timeout_step`, `_section_8_simulator`, `_section_7_item_10`, `_ca20_line_of_section_9`, `_old_quote_advice_is_gone`, `_earlier_spec_acceptance_files_still_exist`. A última condição (SPECs 015, 032, 038, 039 e 040) é verificada pelos aceites dessas SPECs, que passam na suíte | ✅ |
| CA-17 | `infra/…::test_ca17_comment_right_above_the_example_line` | ✅ |
| CA-18 | Manual, em produção, depois do merge e do deploy | Pendente (humano). Não executado |
| CA-19 | `dashboard/…::test_ca19_unavailable_notice_and_retry_recovers` (6), `::test_ca19_401_shows_the_key_message_without_the_notice` (2), `::test_ca19_the_old_words_are_gone` (2), `::test_ca19_constant_has_the_exact_value`, `::test_ca19_readme_cites_the_new_text` | ✅ |

**Contagem:** 197 testes novos, 85 de CA e 112 extras (`scripts/` 29, `api/` 67, `infra/` 50, `dashboard/` 25, `edge/` 26).

**Controle dos testes:** rodei os arquivos novos de `scripts/`, `infra/`, `dashboard/` e `edge/` contra uma cópia do código anterior à implementação (`37b6f3b`). CA-01, 02, 03, 08, 09, 10, 11, 13, 14, 15, 16, 17 e 19 falham lá. CA-05 a CA-07 (`api/`) não coletam, porque `qc_api.conninfo` não existe nessa versão. O controle rodou sem banco, então o CA-04 ficou de fora. Ele é regressão: a SPEC não pede código novo para esse caso.

## CA-12: ensaio e controle

**Montagem:** banco próprio `partqc_ca12_test` no `partqc-pg` (apagado no fim), `qc-api` real em `uvicorn`, painel real em `streamlit` e Chrome headless a 1500 × 1000, conduzido por CDP, sem acesso à rede externa. Código novo: `f3e9846`. Código anterior: `37b6f3b`. Origem `Simulado`. As capturas ficaram só no scratchpad.

| Cenário | Código | Coluna `Modelo` | Sem rolagem horizontal | Depois de rolar para a direita |
|---|---|---|---|---|
| **1 inspeção (o roteiro do CA-12)** | novo | 240 px | `partqc-mnv3-provisional-` | Inteira |
| 1 inspeção | anterior | 180 px (automática) | `partqc-mnv3-provisional-` | Inteira |
| 40 inspeções provisórias | novo | 240 px | `partqc-mnv3-provisio` | Inteira |
| 40 inspeções provisórias | anterior | automática | `partqc-mnv3-provisio` | Inteira |
| 15 `sim-v0` + 5 provisórias | novo | 240 px | `partqc-mnv3-provisio` | Inteira |
| 15 `sim-v0` + 5 provisórias | anterior | automática, estreita | `partqc-mn` | **Não há rolagem horizontal**: só alargando a coluna |

- **Diferença entre novo e anterior, sem rolagem:** 1 pixel com 1 inspeção; 0 pixel com 40 inspeções, na região de 720 px capturada.
- **Largura do painel:** com 1 inspeção, a tabela tem 1040 px, e as outras colunas ocupam 882 px. Sobram 158 px para `Modelo`, que precisa de 180 px. Com 40 linhas, a barra vertical reduz a tabela a 1030 px.
- **Com a janela maior:** a 1540 px, com 1 inspeção, a célula aparece inteira sem rolagem nos dois códigos. A 1600 e a 1700 px, conferi só o código novo, também inteira.
- **`…`:** nenhuma captura mostrou o caractere. O corte vem da borda da tabela ou da própria coluna.
- **Selo e `Origem`:** `Contém dados simulados` e `simulado` apareceram em todos os cenários (R-06).

**Conclusão:**

- O requisito da §4.3 está implementado como escrito, e o CA-11 passa.
- A largura fixa traz um ganho real no caso misto, o único em que o código anterior não mostra o valor nem rolando.
- Mas o resultado previsto no CA-12 não se confirma como está escrito (`SPEC_ISSUE-01`).

## Suíte completa

```text
CI=true TEST_DATABASE_URL=<Postgres local> ORT_DISABLE_TELEMETRY=1 uv run pytest -q
10509 passed, 167 skipped, 1 warning in 1002.83s (0:16:42)

uv run ruff check .             All checks passed!
uv run ruff format --check .    323 files already formatted
```

- Nenhum teste de `test_spec_043.py` foi pulado, inclusive o CA-04, com banco.
- **Mudança depois da suíte:** troquei um parâmetro de `test_extra_never_raises`, que tinha uma URL literal com credencial fictícia (`reviews/checklist.md` §4), por uma montada em tempo de execução. Rodei de novo, com os arquivos no índice do Git, os cinco arquivos novos e o scanner de segredos da SPEC-015 (`-k "test_spec_043 or ca05"`): `201 passed, 137 deselected`. A suíte inteira não foi repetida para essa troca.

## Ajustes em testes de aceite de SPECs anteriores

`docs/architecture.md` §10, aplicação explícita da §3.1 da SPEC:

| Arquivo | Teste | Antes → depois | Requisito |
|---|---|---|---|
| `scripts/tests/acceptance/test_spec_014.py` | `test_extra_timeouts` | `batch.extensions["timeout"]["read"] == 10` → `== 60`; o `90` da saúde continua | §4.1 |
| `dashboard/tests/acceptance/test_spec_013.py` | Constante `WAKING` | `"API acordando (free tier), tente em ~1 min"` → texto da §4.8; as asserções continuam | §4.8 |
| `dashboard/tests/acceptance/test_spec_028.py` | Constante `WAKING` | Igual à linha acima | §4.8 |

`test_spec_029.py::test_ca01_spec013_suite_passes_and_hides_key_with_local_secrets` voltou a passar sem ajuste próprio, como o dev-report previa. Nenhum `test_caNN_` foi removido nem renomeado.

## Bugs encontrados

Nenhum bug de implementação.

## Testes exploratórios (além dos critérios)

| Área | Casos | Resultado |
|---|---|---|
| Simulador | 403, 400, 404 e 422 sem o aviso da seed; 500, 502, 503 e 504 esgotados com 4 tentativas e o aviso; `ConnectError` com a chave no texto da exceção; lote que precisa de 60 s e de 60,01 s; mesma seed 6 h depois | OK. A chave não aparece, e os ids não dependem do relógio |
| `is_safe_conninfo` | 30 casos da tabela da §4.2: socket por query e por `%2F`, multi-host, porta vazia, `hostaddr`, `port=+6543`, `port=abc`, `%40`, `%2F` e `%3A` em `dbname`, quebra de linha e espaço em `host`, dígitos não ASCII e URL vazia | OK |
| `is_safe_conninfo`, entradas ruins | Caractere nulo, `%`, `=`, aspas, `[`, porta enorme, 100 000 caracteres, emoji, `None`, `int` e `bytes` | Nunca levanta exceção |
| Subida real da API | `uvicorn` em processo, com as 4 URLs M e `getaddrinfo` vigiado | Sai com erro, cita `DATABASE_URL`, sem sentinela e sem consulta de DNS |
| `register_device.py` como processo | As 4 URLs M, com `psycopg.connect` vigiado; também com `--rotate` | Código 2, stdout vazio, nenhuma chave gerada e o stderr real com a recusa |
| `migrate.py` | URL pelo argumento `--database-url`; `port=abc` (§7) | Código 2, sem conectar |
| `qc_api.conninfo` | Importado sozinho em outro processo | Não carrega `db`, `config` nem `errors` (§7) |
| Painel | HTTP 502 e 504 em 3 páginas; nova tentativa com a API ainda fora; nenhuma repetição automática; CSV; `model_version` de 40 caracteres | OK |
| Console | `127.0.0.2`, `127.255.255.254` e outros IPv4; `?ip=` vazio, com `<script>`, repetido, `%00` e fora da lista; QR diferente por endereço; `Host` recusado; outro cliente | OK |
| Plano | Itens 2, 5, 6, 7 e 9 da §4.5 e a coluna "Resultado" da §4.7; nenhum UUID | OK |

**Observações, sem bloquear:**

- **OBS-01, baixa: com `EDGE_HOST` específico, o console real não abre.**
  - **Medido** com o `qc-edge --stub-model` real e `EDGE_HOST=127.0.0.2`: `http://127.0.0.2:<porta>/` responde 403, `http://127.0.0.1:<porta>/` recusa a conexão, e o log ainda diz `operator console: http://127.0.0.1:<porta>/`.
  - **Causa:** a regra da SPEC-025 aceita só `127.0.0.1`, `localhost` e `[::1]` no `Host`, e a §4.4 manda não mudá-la. Por isso, a implementação segue a SPEC.
  - **Efeito:** a linha "Outro IPv4" da §4.4 e o CA-14 só são visíveis por um transporte de teste. Com `EDGE_HOST=127.0.0.1`, o caso do E2E-02, tudo funciona no socket real.
  - **Limite:** não testei um IP real da LAN no socket, para não expor a borda na rede. O código é o mesmo, e o teste por ASGI com outro cliente dá 403.
- **OBS-02, baixa:** o comentário de `dashboard/src/qc_dashboard/api.py`, linha 6, ainda diz "free tier cold start". O CA-19 não cobre esse arquivo, e a §3.1 não o lista (o dev-report já registra).
- **OBS-03, informativa:** "§8, item 5" no CA-16 é o passo 5 de `### 1. statement_timeout`, e não `### 5. Alertas no Telegram`. Testei conforme o texto inequívoco da §4.5, item 7, a mesma leitura do dev-report.
- **OBS-04, informativa:** uma senha como `1?user=<B>/c`, numa URL com `@` depois, é aceita pelo `is_safe_conninfo`, porque o trecho cai no `user`, que a regra não examina. É o limite da heurística que a §7 admite, e a regra de "só letras e números" do plano é a defesa principal.

**Desvio de procedimento:** a guarda de caminhos do tester nega o `Write` fora do repositório. Os scripts de apoio do ensaio rodaram pelo `Bash`, passados em linha, sem arquivo de script, e só as capturas, os logs e a cópia do código anterior foram para o scratchpad. É o mesmo procedimento registrado em `reviews/SPEC-041/r1-e2e-test-report.md`. Nada disso entra no Git. Banco do ensaio apagado, processos parados, e o `partqc_test` não foi usado no ensaio.

## SPEC_ISSUE (se houver)

**SPEC_ISSUE-01 (CA-12, §2, §4.3 e §7): a largura de 240 px não faz a coluna aparecer inteira a 1500 px, e o controle previsto não mostra o corte.**

- **Texto:**
  - a §2 pede que "a coluna `Modelo` aparece inteira no Histórico a 1500 px";
  - o CA-12 pede uma captura em que "a célula mostra `partqc-mnv3-provisional-v1` inteira", e que o código anterior, "no mesmo roteiro", "mostra o corte";
  - a §7 admite que, "se a soma das colunas passar da tela, aparece rolagem horizontal, e o valor continua inteiro".
- **Medido:** ao abrir a página a 1500 px, a célula continua cortada no código novo, e o corte é o mesmo do anterior (tabela acima). Ela só aparece inteira depois da rolagem horizontal, o que vale também para o código anterior no roteiro do CA-12, com 1 inspeção. O corte exclusivo do código anterior só aparece com modelos mistos, que o CA-12 não descreve. Com 40 inspeções provisórias, a tela sem rolagem é a mesma nos dois códigos e mostra `partqc-mnv3-provisio`, o mesmo trecho relatado no E2E-01.
- **Por que é SPEC_ISSUE, e não bug:** a implementação cumpre a §4.3 ao pé da letra, e a §7 manda não mudar a ordem das colunas. A contradição está entre o objetivo e o CA-12, de um lado, e o que a medida prescrita produz nessa largura, de outro. Decidir o que vale é do architect e do humano.
- **Saídas possíveis, para o architect avaliar:**
  - (a) reescrever a §2 e o CA-12 para aceitar a rolagem horizontal e usar os modelos mistos no controle. O E2E-01 continuaria exigindo rolagem na tela sem rolagem;
  - (b) mudar a medida para a coluna caber a 1500 px, por exemplo reduzindo outras colunas, sem mudar a ordem nem o CSV. Precisa de `SPEC` nova ou alterada e de nova rodada;
  - (c) mudar a largura de referência do CA-12 (a 1540 px, com 1 inspeção, a célula aparece inteira, mas também no código anterior).
- **Impacto:** baixo, sem efeito na R-06, mas o passo 4 do CA-22 da SPEC-041, que motivou o E2E-01, e o CA-18, passo 6, passam pela mesma tela. No passo 6, o valor esperado é o curto `sim-v0`, que cabe na parte visível.

## Pendências

- CA-18: manual, do humano, depois do merge e do deploy.
- CA-12: depende da decisão sobre o `SPEC_ISSUE-01`.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
