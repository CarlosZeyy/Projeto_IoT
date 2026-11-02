# SPEC-043 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-043](../../docs/specs/SPEC-043-manutencao-pos-deploy.md) |
| Rodada | r1 |
| Autor | developer (Parte A). A Parte B é do security-devops |
| Branch | `spec/SPEC-043-manutencao-pos-deploy` |
| Commits | ver "Commits da Parte A" |

## Resumo

Parte A implementada depois da correção do SPEC_ISSUE-01 (commit `4944e15`, reaprovada pelo humano).

- **DEP-01:** o lote do simulador espera até 60 s, e a mensagem do esgotamento manda repetir com a mesma seed.
- **DEP-02:** `qc_api.conninfo.is_safe_conninfo` recusa a URL mal formada antes de conectar, na API, no `migrate.py` e no `register_device.py`.
- **E2E-01:** a coluna `Modelo` do Histórico tem 240 px.
- **E2E-02:** com `EDGE_HOST` diferente de `0.0.0.0`, o console só oferece esse endereço e, em loopback, avisa que o celular não abre.
- **OBS-01:** o aviso passa a ser `API_UNAVAILABLE_TEXT`, com o texto da §4.8.

## Commits da Parte A

| Commit | Item |
|---|---|
| `b5cb88c` | Registro do SPEC_ISSUE-01 (primeira passagem, sem código) |
| `ab4be60` | DEP-01 |
| `d98a115` | DEP-02 |
| `3a79ba6` | E2E-01 e OBS-01 (juntos, porque os dois mudam `dashboard/tests/test_pages.py`) |
| `fa4f38f` | E2E-02 |

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `scripts/simulate.py` | `scripts/tests/test_simulate.py::test_timeouts` |
| CA-02 | `scripts/simulate.py` | `scripts/tests/test_simulate.py::test_batch_that_needs_more_than_the_old_timeout_succeeds` |
| CA-03 | `scripts/simulate.py` | `scripts/tests/test_simulate.py::test_exhausted_batch_tells_to_repeat_with_the_same_seed`, `::test_other_failures_do_not_suggest_repeating` |
| CA-04 | Sem código novo: a idempotência já existia, e a §4.1 não muda a geração dos ids | `scripts/tests/test_simulate.py::test_send_and_resend_are_idempotent` (o caso com o banco real é do tester) |
| CA-05 | `api/src/qc_api/conninfo.py` | `api/tests/test_conninfo.py` |
| CA-06 | `api/src/qc_api/conninfo.py`, `api/src/qc_api/config.py` | `api/tests/test_config.py::test_malformed_database_url_is_refused_without_its_pieces`, `api/tests/test_app_no_db.py::test_startup_fails_with_a_malformed_url_before_the_pool` |
| CA-07 | Regressão, sem código novo | `api/tests/test_app_no_db.py::test_logs_have_no_password` (já existia) |
| CA-08 | `infra/migrate.py` | `infra/tests/test_migrate_malformed_url.py::test_main_exits_2_with_the_hint`, `::test_main_keeps_the_port_6543_message` |
| CA-09 | `infra/migrate.py` | `infra/tests/test_migrate_malformed_url.py::test_functions_refuse_before_connecting`, `::test_port_6543_keeps_its_own_refusal`, `::test_host_port_is_unknown`; `infra/tests/test_cli.py::test_closed_port_exits_1_without_leaking_password` (já existia) |
| CA-10 | `scripts/register_device.py` | `api/tests/test_register_device.py::test_malformed_url_exits_2_before_generating_a_key`, `::test_unreachable_database_exits_1_without_leaking` (já existia) |
| CA-11 | `dashboard/views/historico.py`, `dashboard/src/qc_dashboard/formatting.py` | `dashboard/tests/test_pages.py::test_history_model_column_has_a_fixed_width` |
| CA-12 | Os mesmos do CA-11 | Ensaio do tester, fora da suíte |
| CA-13 | `edge/src/qc_edge/netinfo.py`, `edge/src/qc_edge/app.py` | `edge/tests/test_pages.py::test_console_in_loopback_warns_and_never_offers_the_lan`, `edge/tests/test_live_route.py::test_console_with_tls_in_loopback_keeps_both_urls_off_the_lan`, `edge/tests/test_netinfo.py` |
| CA-14 | `edge/src/qc_edge/netinfo.py`, `edge/src/qc_edge/app.py` | `edge/tests/test_pages.py::test_console_with_a_specific_lan_host_offers_only_it` |
| CA-15 | `edge/src/qc_edge/app.py`, `edge/README.md` | `edge/tests/test_pages.py::test_console_on_all_interfaces_is_as_before`, `::test_console_on_all_interfaces_without_lan_has_only_the_no_lan_warning` |
| CA-16, CA-17 | Parte B | Fora desta parte |
| CA-18 | Manual, depois do merge | Humano |
| CA-19 | `dashboard/src/qc_dashboard/filters.py`, `dashboard/README.md` | `dashboard/tests/test_pages.py::test_timeout_then_retry`, `::test_unavailable_text_does_not_suggest_a_cold_start`, `dashboard/tests/test_devices.py::test_page_api_unavailable` |

## Testes de aceite de SPECs anteriores (ajuste do tester)

Falham de propósito por causa desta SPEC e não foram tocados por mim (`docs/architecture.md` §10):

| Teste | Requisito | Situação |
|---|---|---|
| `scripts/tests/acceptance/test_spec_014.py::test_extra_timeouts` | §4.1 | Na tabela da §3.1 da SPEC |
| `dashboard/tests/acceptance/test_spec_013.py`: `test_ca13_timeout_shows_waking_and_retry_recovers` (3 casos), `test_ca13_model_page_badge_check_timeout`, `test_extra_gateway_statuses_wake_up_warning` (3 casos), `test_extra_retry_while_still_down_is_bounded` | §4.8 | Constante `WAKING`, na tabela da §3.1 |
| `dashboard/tests/acceptance/test_spec_028.py`: `test_ca05_model_page_without_the_api`, `test_ca07_retry_does_not_clear_the_cache`, `test_extra_spc_caption_right_under_title_and_after_failure` | §4.8 | Constante `WAKING`, na tabela da §3.1 |
| `dashboard/tests/acceptance/test_spec_029.py::test_ca01_spec013_suite_passes_and_hides_key_with_local_secrets` | §4.8 | **Fora da tabela, sem ajuste próprio:** ele roda a suíte da SPEC-013 num subprocesso e falha pelas 8 falhas acima. Deve voltar a passar quando o `WAKING` da SPEC-013 mudar |

## Como rodar e verificar

```bash
uv run ruff check . && uv run ruff format --check .
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

Resultado no código dos commits acima, com o contêiner `partqc-pg`: **13 failed, 10299 passed, 167 skipped** em 16 min 25 s. As 13 falhas são exatamente as da tabela "Testes de aceite de SPECs anteriores": 1 da SPEC-014, 8 da SPEC-013, 3 da SPEC-028 e 1 da SPEC-029. Nenhum teste do autor falha. Os skips incluem os testes que pedem torch, MQTT, modelo real ou medição de rede. O `ruff check` e o `ruff format --check` estão limpos.

## Decisões tomadas dentro do escopo da SPEC

- `netinfo.is_loopback` e `netinfo.ALL_INTERFACES` são auxiliares novos, e `_ip_warning_html` em `app.py` aplica a tabela da §4.4. O `is_fallback` só é verdadeiro com `0.0.0.0` ou em loopback, então a ordem "loopback primeiro" já cobre as três linhas da tabela.
- `_host_port` deixou o `try` e passa a usar só o `is_safe_conninfo`, que já cobre a falha do parser.
- **Limite observado:** `host=a\0b` não é recusada, porque o parser corta a string no caractere nulo e devolve `host=a`. O trecho depois dele nem chega ao `host`, então a regra da §4.2 é cumprida.
- Nos testes novos, o esquema da URL fica numa constante separada (`"postgresql" + "://"`), porque o scanner de segredos do repositório marca `u:{a}/{b}@` (`reviews/checklist.md` §4).
- `dashboard/src/qc_dashboard/api.py`, linha 6, ainda cita "free tier" num comentário. Ficou como está: o arquivo não está na §3.1, e o CA-19 não o cobre.

## SPEC_ISSUE

**SPEC_ISSUE-01: resolvido** pelo architect com a saída (a) (commit `4944e15`, reaprovado pelo humano). A implementação segue a §4.2 e a §7, e a URL com a porta 6543 levanta `UnsupportedConnectionError`.

Registro original: o CA-09 e a primeira frase do CA-08 pediam, para a URL com a porta 6543, um erro que a §4.2 e a §7 não produzem. A medição mostrou `host` com `@` e `port` igual a `6543`, e as duas funções levantando `UnsupportedConnectionError`. Os detalhes estão no commit `b5cb88c`.

Nenhum `SPEC_ISSUE` novo.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova, e o arquivo é da Parte B
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim

## Parte B (security-devops)

Autor: security-devops. Commit: `0bf23bf`. Só `docs/deployment-plan.md` e `.env.example`, mais esta seção. Nenhum arquivo da Parte A foi alterado. Como o autor é o security-devops, o portão de segurança da Parte B é do reviewer (SPEC §8).

### Rastreabilidade

| Requisito | Onde, em `docs/deployment-plan.md` |
|---|---|
| §4.5, item 1 | Passo 1, item 3, subitem 2; §8, "### 1", passo 5, subitem 1 |
| §4.5, item 2 | Passo 1, item 4 |
| §4.5, item 3 | Passo 5, parágrafo "O que o painel faz sozinho" |
| §4.5, item 4 | Passo 6, item 4 |
| §4.5, item 5 | §7, item 2; §8, "### 1", passo 5 |
| §4.5, item 6 | §8, "### 4"; passo 11, item 3 |
| §4.5, item 7 | §8, "### 1", passo 5 |
| §4.5, item 8 | `.env.example`, linha acima de `DATABASE_URL=` |
| §4.5, item 9 | Histórico do arquivo |
| §4.7 | §7, item 10; §9, linha `SPEC-039 CA-20` |

### Verificação

- Conferência local de todas as condições de texto do CA-16 e do CA-17, por um script fora do repositório: todas atendidas. O teste de aceite continua sendo do tester.
- Testes que leem o plano e o `.env.example` (`infra/tests/test_coolify_deploy.py`, `test_deploy_maintenance.py`, `test_maintenance_040.py`, `test_deploy_files.py`; aceites das SPECs 015, 032, 038, 039 e 040 em `infra/`; aceites das SPECs 017 e 040 em `api/`; `tests/acceptance/test_spec_001.py`; `tests/test_guard_paths.py`), com `CI=true` e o Postgres local: **859 passed, 84 skipped**. Os skips que apareceram no resumo pedem `PARTQC_DOCKER_TESTS=1`, e esta parte não mudou `infra/compose*.yaml` nem os Dockerfiles. A suíte completa não foi rodada de novo: a mudança é só de texto.
- `ruff check` e `ruff format --check` limpos.
- Fontes abertas de novo em 2026-11-02: a página do `ALTER ROLE` do Postgres e a de variáveis do Coolify, com as frases citadas na §1 da SPEC, e a de segurança da API do Supabase, que confirma os privilégios padrão de tabelas novas em `public` e a opção "Automatically expose new tables". Nenhum limite de free tier foi fixado ou alterado.
- O diff não traz subdomínio, IP nem UUID reais (R-13), e nenhum `.env` local foi lido.

### Decisões dentro do escopo

- **Comentário SQL do passo 1, item 4:** passou a `-- esperado: nenhuma linha, depois do revoke explicado abaixo`, para não contradizer a explicação nova.
- **`rm .env.dbcheck`:** o subitem 3 dizia "logo depois". Passou a "só no fim da conferência", para o arquivo sobreviver às repetições do §4.5, item 7.
- **`SPEC_ISSUE` do passo 5:** o "Se não for" antigo ficaria sem referente depois do texto novo. A frase virou "Se, depois disso, a saída ainda não for `15s`", com a mesma alternativa do `set local`.
- **Simulador:** o texto pede a mesma seed "e as mesmas opções", um pouco mais que os "mesmos tamanhos" da §4.1, porque é a forma simples e segura de reenviar os mesmos ids. O código 5 também sai numa falha da saúde (CA-03), em que repetir é inofensivo.
- **§9, regra de colagem, "a mensagem de erro de uma conexão que falhe no item 5 da §8 (host do pooler)":** fica como está, fora da lista do §4.5. O aviso novo está no próprio passo 5.

### Notas para o tester e o reviewer

- **Rótulo "§8, item 5":** na SPEC (§4.5, itens 1, 5 e 7, e CA-16), ele indica o passo 5 de `### 1. statement_timeout`, e não a seção `### 5. Alertas no Telegram`, que é o que o próprio plano chama de "§8, item 5" em outros lugares. O texto da §4.5, item 7, torna o alvo inequívoco, por isso não é `SPEC_ISSUE`. Porém, um teste do CA-16 que recorte `### 5.` falharia: o recorte certo vai de `5. **Conferir pelo caminho` a `6. Registrar na §9`, dentro de `### 1.`. Já o "§8, item 4" do CA-16 é a seção `### 4.`.
- **Linha do CA-20 na §9:** a medição não mudou. "Desvio" deu lugar a "Texto corrigido pela SPEC-043", como pede a §4.7, e o resultado continua "PASS nos segredos".

### SPEC_ISSUE

Nenhum.

### Pendências humanas

- §3.3, item 1, antes do merge: conferir que a senha atual do banco tem só letras e números.
- §3.3, item 2, depois do merge: **Deploy** no `partqc-api` e depois no `partqc-web`, e `git pull` na borda.
- CA-18, depois do deploy, com o registro no `deployment-plan.md` §9 e num dev-report.
