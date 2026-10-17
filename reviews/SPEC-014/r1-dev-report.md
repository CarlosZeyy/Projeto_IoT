# SPEC-014 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-014](../../docs/specs/SPEC-014-simulador.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-014-simulador` (diff `main...HEAD`) |
| Commits | `1b2a9a6` (feat(scripts): add simulated lot generator), `620ee21` (test(scripts): cover the simulator and add scripts/tests to testpaths), `3beb390` (docs: document the simulator in README and .env.example), mais o commit deste relatório |

## Resumo

- **`scripts/simulate.py`** (argparse, sem `from __future__ import annotations`, para que o carregamento por `importlib.util.spec_from_file_location` funcione sem registrar o módulo em `sys.modules`). Ele expõe `SimConfig`, `parse_args`, `generate`, `send`, `SendSummary` e `main`, com as assinaturas do §3.1. A única diferença é o `now` keyword-only de `parse_args` (ver "Decisões").
- **Argumentos (§4.1):** validação com `parser.error` (código 2, mensagem no stderr). `--device-id` e `--model-version` passam por `re.fullmatch(DEVICE_ID_PATTERN | MODEL_VERSION_PATTERN, ...)` de `qc_contracts`. Não existe `--source`, e `allow_abbrev=False` impede que um prefixo seja aceito. `--start` precisa ter fuso e é normalizado para UTC. O limite "nenhum `inspected_at` depois de `now + 5 min`" é calculado sobre o último item possível (último lote, maior `n`), com a `MAX_FUTURE_SKEW` de `qc_contracts`. A URL e a chave só são exigidas fora do `--dry-run`.
- **Geração (§4.2):** um único `random.Random(seed)`, consumido na ordem documentada na docstring de `generate` (passos 0 a 4). Os ids não dependem de `--start`. Todo item é construído com `qc_contracts.InspectionCreate`, e um `ValidationError` vira código 1.
- **Envio (§4.3):** `httpx.Client(base_url, transport)`, `GET /api/v1/health` (timeout 90 s), blocos de até `MAX_BATCH_SIZE` (100) serializados com `BatchCreate.model_dump_json()`, header `X-API-Key`, timeout 10 s. Erro de rede, timeout ou 5xx: até 3 novas tentativas com `sleep(2)`, `sleep(4)` e `sleep(8)`, depois código 5. 401/403 → 3; 422 → 4, com o `detail` no stderr. A resposta 2xx é validada com `BatchResult`. O resumo vai para o stdout, ou para o stderr no `--dry-run`, que imprime JSON Lines no stdout.
- **Docs:** seção "Simulador (SPEC-014)" no `README.md`. As variáveis `SIM_DEVICE_ID`/`SIM_DEVICE_API_KEY` já estavam no `.env.example` e ganharam comentários, incluindo o uso de `CLOUD_API_URL`. `"scripts/tests"` entrou em `testpaths`.

## Rastreabilidade (critério de aceite → implementação)

Abreviações: `sim` = `scripts/simulate.py`; `t/` = `scripts/tests/test_simulate.py`.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `sim` (`generate`, `_item`, `_item_offset`, `main` no `--dry-run`) | `t/::test_dry_run_output` (com `--start` no passado; ver SPEC_ISSUE-1), `t/::test_dry_run_needs_no_url_nor_key` |
| CA-02 | `sim` (`generate`: RNG único em ordem fixa, `uuid.UUID(int=..., version=4)`) | `t/::test_same_seed_same_output_other_seed_other_ids`, `t/::test_rng_order_starts_with_the_first_id`, `t/::test_ids_do_not_depend_on_start` |
| CA-03 | `sim` (sem `--source`, `allow_abbrev=False`, `source=Source.SIMULATED` fixo) | `t/::test_invalid_arguments_exit_2[--source ...]`, `t/::test_source_is_always_simulated` |
| CA-04 | `sim` (`_item`: `choices` com pesos 0,7/0,3 e 0,40/0,35/0,25) | `t/::test_distribution_of_grades`, `t/::test_extreme_rates` |
| CA-05 | `sim` (`_item`, ramo `unknown`) | `t/::test_distribution_of_unknown`, `t/::test_item_rules` |
| CA-06 | `sim` (`_lot_sizes`, `randint(min, max)` por lote) | `t/::test_random_lot_sizes_stay_in_range`, `t/::test_random_lot_sizes_consume_the_rng_first`, `t/::test_invalid_arguments_exit_2[...lot-size...]` |
| CA-07 | `sim` (`SimConfig.lot_rate`: `min(1.0, 3 × defect_rate)`) | `t/::test_p_chart_flags_the_out_of_control_lots` (seed 42: p̄ = 0,0918; só `024` e `028` fora de controle), `t/::test_out_of_control_rate_is_three_times_capped_at_one` |
| CA-08 | `sim` (`_out_of_control_lots`, `_rate`, `re.fullmatch` em `parse_args`) | `t/::test_invalid_arguments_exit_2` (todos os casos do CA, mais `3,`, `-3`, dígito não ASCII, `nan`, `inf`), `t/::test_boundary_arguments_are_accepted` |
| CA-09 | `sim` (`_last_inspected_at` + `MAX_FUTURE_SKEW`) | `t/::test_start_in_the_future_is_refused`, `t/::test_start_limit_is_the_last_generated_item`, `t/::test_start_limit_uses_the_largest_random_lot_size` |
| CA-10 | `sim` (`send`, `_check_health`, `_post_batch`, `_summary`) | `t/::test_send_and_resend_are_idempotent`; com a API real e o banco: `t/::test_real_api_is_idempotent` (`db`) |
| CA-11 | `sim` (`_post_batch`) | `t/::test_retry_then_success` |
| CA-12 | `sim` (`_post_batch`, `RETRY_DELAYS_S`) | `t/::test_retries_exhausted_exit_5` (503, 500, 502, `ReadTimeout`, `ConnectError`) |
| CA-13 | `sim` (`_post_batch`; `SimConfig.api_key` com `repr=False`; mensagens sem a chave) | `t/::test_auth_failure_exits_3_without_more_requests`, `t/::test_key_from_the_command_line_is_not_echoed`, `t/::test_config_repr_hides_the_key`, `t/::test_real_api_refuses_another_device` (`db`) |
| CA-14 | `sim` (`_detail`) | `t/::test_422_exits_4_with_detail`, `t/::test_422_without_json_body` |
| CA-15 | `sim` (`_api_url`, `_api_key`) | `t/::test_missing_key_exits_2`, `t/::test_missing_url_exits_2`, `t/::test_invalid_api_url_exits_2`, `t/::test_local_http_url_is_accepted`, `t/::test_api_url_with_credentials_is_refused_without_echo` |
| CA-16 | `sim` (`BatchCreate(items=chunk).model_dump_json()`) | `t/::test_batch_items_have_exactly_the_contract_keys`, `t/::test_dry_run_output` |

Outros testes: `test_defaults`, `test_default_start_follows_lots_and_now_offset`, `test_naive_now_is_a_programming_error`, `test_random_seed_is_printed`, `test_env_defaults`, `test_options_override_env`, `test_device_id_is_required`, `test_help_exits_0`, `test_start_is_normalized_to_utc`, `test_lot_id_uses_the_utc_date_of_start`, `test_key_with_invalid_characters_exits_2_without_echo`, `test_item_rules`, `test_invalid_generated_item_exits_1`, `test_timeouts`, `test_health_failure_exits_5`, `test_other_status_exits_5_without_retry`, `test_unexpected_success_body_exits_5`, `test_failure_on_a_later_batch_reports_progress`, `test_send_returns_the_summary`, `test_send_refuses_a_dry_run_config`.

Os testes `db` encaminham o `MockTransport` para a app real (`create_app`) num `TestClient`, sobre o `clean_db` da raiz, com `sim-01` registrado por hash. Nenhum teste usa rede real, e a chave é gerada em tempo de execução.

## Resposta à rodada anterior (a partir de r2)

N/A (r1).

## Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest -q scripts/tests                                                     # sem banco
TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q scripts/tests
uv run --package qc-api python scripts/simulate.py --dry-run --device-id sim-01 --lots 3 --seed 42
```

Resultados desta rodada (máquina local, Postgres 16 do Docker da SPEC-001):

- `uv run ruff check .`: `All checks passed!`; `uv run ruff format --check .`: `110 files already formatted`.
- `uv run pytest -q` **sem** `TEST_DATABASE_URL`: `1460 passed, 485 skipped`.
- `uv run pytest -q` **com** `TEST_DATABASE_URL`: `1945 passed` (4 min 44 s).
- Cobertura de `scripts/simulate.py` nos testes do autor (com banco): 98%. Faltam só o ramo `now is None` de `_aware_now` e a linha do `if __name__ == "__main__"`.

## Decisões tomadas dentro do escopo da SPEC

1. **`parse_args(argv, *, now=None)`:** o `now` keyword-only é necessário para o padrão de `--start` e para o limite `now + 5 min` com o relógio injetado. `parse_args(argv)` continua funcionando, com o relógio real.
2. **`parse_args` sai por `SystemExit(2)`** (`parser.error`), como o argparse; `main` converte em código de retorno (2, ou 0 no `--help`).
3. **`allow_abbrev=False`:** sem isso, `--dry` ou `--sta` seriam aceitos como prefixos.
4. **`--api-url`:** além do §4.1 (`https://`, ou `http://` só para `localhost`/`127.0.0.1`), recusa URL sem host, com usuário/senha, query ou fragmento, e porta inválida. A mensagem nunca repete a URL (R-03). A barra final é removida.
5. **`--api-key`:** precisa ser não vazia e ter só ASCII visível (`!`…`~`), como um valor de header. Assim, uma chave com espaço ou `\n` vira código 2 em vez de um erro do httpx tratado como falha de rede. A mensagem nunca mostra a chave, e `SimConfig.api_key` tem `repr=False`.
6. **Respostas não previstas na SPEC:**
   - um status 4xx diferente de 401/403/422 (400, 404, 413, 429) ou um 3xx leva ao código 5, sem nova tentativa (os redirecionamentos não são seguidos);
   - um 2xx cujo corpo não é `BatchResult`, ou com outra quantidade de resultados, também leva ao código 5;
   - o health falha (código 5) com erro de rede ou com qualquer status diferente de 200, e não tem novas tentativas (o §4.3 só prevê tentativas para os lotes).
   - "Erro de rede ou timeout" foi implementado como `httpx.RequestError`.
7. **Falha no meio do envio:** o stderr registra o progresso parcial (`sent=… created=… duplicate=… seed=…`), para o usuário poder reexecutar com a mesma seed (a API responde `duplicate` para o que já entrou).
8. **Resumo do `--dry-run`:** `sent=<n> lots=<n> seed=<s> source=simulated` no stderr, em que `sent` conta os itens impressos (é o resumo do §4.3 sem `created`/`duplicate`).
9. **422 com `detail` em lista** (validação do FastAPI): o stderr mostra o JSON compacto do `detail`. Ele não contém a chave; pode conter valores do item, que são dados simulados.
10. **Código 1:** o log mostra só a contagem de erros do `ValidationError`, e não os valores gerados.

## SPEC_ISSUE (se houver)

**SPEC_ISSUE-1 — CA-01 e CA-02 (`--start 2026-11-01T12:00:00Z`) contra a validação do contrato no relógio real.** O §4.2, passo 5, manda construir todo item com `qc_contracts.InspectionCreate`, e o `InspectionCreate` recusa `inspected_at > datetime.now(UTC) + 5 min` usando o relógio **real** (o validador `_not_in_future` de `qc_contracts.schemas`), e não o `now` injetado em `main`. Hoje (2026-10-17), com `now` fixo depois do `--start` (por exemplo, `2026-11-01T13:00Z`), o CA-01 dá **código 1**, e não 0. Com `now` fixo antes, dá código 2 pelo CA-09. Até cerca de 2026-11-01T12:24Z (quando o último item, 12:29:00Z, deixa de estar mais de 5 min no futuro), o CA-01 e o CA-02, como escritos, só passam se o teste congelar o relógio de `qc_contracts.schemas`. Depois dessa data, passam sem nada disso. Reproduzido:

```text
main("--dry-run --seed 42 --lots 3 --lot-size 10 --start 2026-11-01T12:00:00Z --device-id sim-01".split(),
     now=datetime(2026, 11, 1, 13, tzinfo=UTC))  -> 1  ("a generated item failed the contract (1 errors)")
```

Implementei o texto literal da SPEC (validação pelo contrato, com o relógio que ele usa) e **não** contornei o problema no código. Meus testes usam `--start` no passado (2026-10-01) e verificam o mesmo comportamento do CA-01. Opções para o architect:

- (a) trocar a data do CA-01/CA-02 por uma data passada (por exemplo, `2026-10-01T12:00:00Z`; o `lot_id` vira `SIM-20261001-…`). É a mais simples e não muda código;
- (b) dizer na SPEC que os testes congelam o relógio de `qc_contracts.schemas`;
- (c) definir que o simulador valide o "futuro" contra o `now` injetado. Isso exige decidir como, porque o contrato não aceita um relógio, e mudar o contrato está fora do escopo (R-04).

Nenhum outro CA depende de data futura: o CA-07 usa o `--start` padrão (`now − 300 min`), e os CAs de envio não fixam `--start`.

**Testes de aceite de SPECs anteriores:** nenhum muda de comportamento por esta SPEC. O `testpaths` ganhou `scripts/tests`, e nenhum teste de aceite fixa essa lista. O `.env.example` só ganhou comentários: as variáveis e os valores verificados pelos CA-20 da SPEC-001 e da SPEC-022 continuam iguais.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (`scripts/tests`: 129 passed com banco; 127 passed e 2 skipped sem banco)
- [x] `.env.example` atualizado (as variáveis já existiam; ganharam comentários, sem valores secretos)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
