# SPEC-034 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-034](../../docs/specs/SPEC-034-reenvio-dead-outbox.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-034-reenvio-dead-outbox` |
| Commits | `e000e0d` (código e testes), `29a4c31` (README), mais o commit deste relatório |

## Resumo

- `qc_edge.outbox`: `DeadItem`, `SqliteOutbox.dead_items()`, `SqliteOutbox.requeue_dead(ids=None)` (§4.1) e `SqliteOutbox.open_existing(path, *, clock, read_only, timeout_s=5.0)`, que abre um arquivo já existente pela URI `file:<caminho>?mode=rw` (ou `mode=ro`) sem nunca criá-lo, sem `CREATE TABLE` e sem mudar o journal; recusa (`NotAnOutboxError`) um banco sem a tabela `outbox` com as colunas da SPEC-009.
- `qc_edge.requeue`: CLI `python -m qc_edge.requeue --outbox-path <arquivo> [--id <uuid> ...] [--yes]` (§4.2), com o `QuietArgumentParser` da SPEC-025 (`qc_edge.argv`): argumento desconhecido, `--id` inválido ou `--outbox-path` inválido → código 2, só nomes de opção no log. Sem `--yes`, só lê (abre com `mode=ro`); com `--yes`, chama `requeue_dead` e imprime `requeued <k> item(s)`.
- `edge/README.md`: subseção "Reenviar itens `dead` (SPEC-034)" dentro de "Envio para a nuvem" (§4.3); a frase "Reenviar uma `dead` à mão fica para uma SPEC futura" saiu.
- Nenhuma mudança de contrato, API, banco, `.env.example` ou dependência.

## Rastreabilidade (critério de aceite → implementação)

Todos os testes abaixo estão em `edge/tests/test_requeue.py`.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `edge/src/qc_edge/outbox.py` (`requeue_dead`) | `test_requeue_all_changes_only_dead_rows` |
| CA-02 | `edge/src/qc_edge/outbox.py` (`requeue_dead`) | `test_requeue_by_id_ignores_unknown_pending_and_sent`, `test_requeue_with_empty_ids_or_without_dead_rows_returns_zero` |
| CA-03 (R-05) | `outbox.py`, `requeue.py` | `test_requeue_then_publish_loop_sends_once_each`, `test_requeued_item_is_returned_by_fetch_due` |
| CA-04 | `outbox.py` (o item reenviado passa pelo laço da SPEC-009 sem mudança) | coberto pelo fluxo de `test_requeue_then_publish_loop_sends_once_each` (recusa → `dead`); o caso "recusado de novo e parado por 5 ciclos" é do teste de aceite |
| CA-05 (R-03) | `edge/src/qc_edge/requeue.py` (`list_dead`, `item_line`, `printable_error`) | `test_cli_lists_without_changing_anything`, `test_cli_shows_a_dash_without_error_and_hides_control_characters` |
| CA-06 | `requeue.py` (`_is_regular_file`, parser), `outbox.py` (`open_existing`) | `test_cli_missing_file_is_never_created[False/True]`, `test_cli_usage_errors_never_echo_values[...]`, `test_cli_rejects_a_directory_and_a_file_that_is_not_an_outbox`, `test_open_existing_never_creates_the_file`, `test_cli_without_outbox_path_is_a_usage_error` |
| CA-07 | `outbox.py` (`open_existing`, `timeout_s=5`), `requeue.py` (`__main__`) | `test_cli_in_a_subprocess_while_the_outbox_is_open`, `test_cli_waits_for_a_writer_lock_up_to_the_timeout` |
| CA-08 (R-02) | `requeue.py` (não importa `httpx` nem nada de rede) | `test_cli_opens_no_socket` |
| §4.1, ids > 100 | `outbox.py` (`REQUEUE_CHUNK = 100`) | `test_requeue_more_than_100_ids_in_chunks` (3 `UPDATE`, 1 `COMMIT`), `test_requeue_rolls_back_every_chunk_on_failure` |
| §4.1, `dead_items` | `outbox.py` | `test_dead_items_lists_only_dead_rows_in_created_order_without_payload`, `test_dead_items_ties_on_created_at_keep_insertion_order`, `test_dead_items_empty` |
| `open_existing` | `outbox.py` | `test_open_existing_rejects_a_database_without_the_outbox_table`, `test_open_existing_read_only_cannot_write`, `test_open_existing_with_spaces_and_uri_characters_in_the_path` |

Cobertura (`edge/tests/test_outbox.py` + `edge/tests/test_requeue.py`): `qc_edge.outbox` 98%, `qc_edge.requeue` 97% (RNF-09, ≥ 80%).

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1).

## Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run pytest -q edge/tests/test_requeue.py edge/tests/test_outbox.py --cov=qc_edge.outbox --cov=qc_edge.requeue
uv run pytest -q edge/tests tests
```

Resultado nesta rodada: `uv run pytest -q edge/tests tests` → 2020 passed, 8 skipped; `uv run pytest -q` (suíte inteira, sem banco) → 5369 passed, 724 skipped. `ruff check .` e `ruff format --check .` limpos.

Nenhum teste meu precisa do banco nem da API real: a nuvem é o `FakeCloud` (`httpx.MockTransport`) de `edge/tests/fake_cloud.py`. A suíte foi rodada sem `TEST_DATABASE_URL` e sem `CI=true`, como pedido (os testes de banco foram pulados).

## Decisões tomadas dentro do escopo da SPEC

- **`open_existing` como `classmethod`** em vez de novos parâmetros no `__init__` da SPEC-009: a assinatura documentada do construtor não muda. O construtor normal continua criando o arquivo (`0600`), ativando o WAL e o schema; `open_existing` não escreve nada ao abrir.
- **Modo só leitura sem `--yes`**: a listagem abre com `mode=ro`, o que garante "não altera nada" mesmo se houver um `-wal` antigo de uma queda (uma conexão `rw` faria o checkpoint ao fechar e reescreveria o arquivo principal). Com `mode=ro` o SQLite pode deixar `-wal`/`-shm` vazios ao lado do arquivo, como acontece com o `qc-edge` ligado; o arquivo do outbox fica com os mesmos bytes (`test_cli_lists_without_changing_anything`).
- **Arquivo que existe mas não é outbox** (texto, banco vazio, banco sem a tabela `outbox`): código 2, tratado como `--outbox-path` inválido, sem alterar o arquivo. A SPEC só fala de "inexistente ou não regular"; estendi o mesmo código a este caso.
- **Falha do SQLite durante a leitura ou o `UPDATE`** (por exemplo, o lock não liberado em 5 s): código 1 e log só com a classe da exceção. A SPEC não define este caso; 1 segue o padrão das outras CLIs da borda (`qc_edge.privacy`) para falha que não é de uso.
- **`last_error` na saída**: além de já vir saneado pelo publisher, cada caractere das categorias `Cc`, `Cf`, `Cs`, `Zl` e `Zp` vira `?` na impressão, para que um texto gravado à mão ou por versão antiga não forje uma linha nem mexa no terminal; vazio ou nulo vira `-`. Não reutilizei `qc_edge.privacy.printable_path` porque importar o módulo traria o Pillow (via `qc_edge.collect`) para uma CLI que só mexe no SQLite.
- **`--id` repetido ou em outra grafia de UUID** (`{...}`, sem hífens): o argparse converte com `UUID(...)` e o SQL usa a forma canônica, igual à gravada pelo `put`. Repetições não contam duas vezes.
- **Filtro `--id` na listagem**: `dead_items()` segue a assinatura da SPEC (sem parâmetro) e o filtro é feito na CLI.
- **SQL dos lotes de ids**: a única interpolação no texto do `UPDATE` são os marcadores `?` (até 100 por parte); todos os valores são parâmetros.

## SPEC_ISSUE (se houver)

Nenhum.

## Testes de aceite de SPECs anteriores

Nenhum teste de aceite anterior falhou. A frase do `edge/README.md` sobre reenvio "para uma SPEC futura" saiu, mas nenhum teste de aceite a verifica (procurei em `edge/tests/acceptance/`).

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (`edge/tests/test_requeue.py`, 31 testes)
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
