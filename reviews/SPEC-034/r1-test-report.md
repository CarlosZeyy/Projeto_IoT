# SPEC-034 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-034](../../docs/specs/SPEC-034-reenvio-dead-outbox.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `e7c023d` |
| **Veredicto** | **PASS** |

Os testes foram escritos a partir da SPEC (caixa-preta), antes de ler `edge/src/qc_edge/requeue.py` e o diff de `edge/src/qc_edge/outbox.py`. Depois da leitura, entraram só testes exploratórios (`test_extra_*`). Nenhum teste do arquivo usa banco Postgres, rede real ou serviço externo. As únicas fronteiras trocadas são a nuvem (`httpx.MockTransport` com idempotência por `inspection_id`), o relógio, o RNG e os espiões de socket do CA-08. O SQLite é real, sempre em `tmp_path`, e os marcadores e chaves são gerados com `secrets`.

## Cobertura dos critérios de aceite

Arquivo: `edge/tests/acceptance/test_spec_034.py` (49 funções, 96 casos coletados).

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_requeue_all_changes_only_dead_rows` | ✅ |
| CA-02 | `test_ca02_requeue_by_id_only_touches_dead_ids` | ✅ |
| CA-03 (R-05) | `test_ca03_requeued_items_are_sent_once_each` | ✅ |
| CA-04 | `test_ca04_item_still_refused_goes_back_to_dead_and_stops` | ✅ |
| CA-05 (security, R-03) | `test_ca05_listing_hides_secrets_and_changes_nothing`, `test_ca05_line_format` | ✅ |
| CA-06 | `test_ca06_missing_file_is_not_created[False/True]`, `test_ca06_bad_arguments_are_not_echoed[...]` (16 casos: `--id` separado e com `=`, `--token=` e `--token <valor>`, com e sem `--yes`) | ✅ |
| CA-07 | `test_ca07_subprocess_requeue_while_outbox_is_open` (subprocesso `python -m qc_edge.requeue`, não o pytest) | ✅ |
| CA-08 (R-02) | `test_ca08_no_network[False/True]` (espiões em `socket.socket.connect` e `socket.getaddrinfo`, com `DEVICE_API_KEY` e `CLOUD_API_URL` no ambiente) | ✅ |

Notas sobre a montagem:

- **CA-01/CA-02:** o outbox é montado só com `put`, `mark_retry`, `mark_dead` e `mark_sent`. Um dos `dead` passou antes por `mark_retry` (`attempts > 0`), para que a volta a `attempts=0` seja visível. Um dos `pending` tem `last_error` e `attempts` de um retry, para provar que as linhas que não são `dead` ficam iguais em todas as colunas. `next_attempt_at` é comparado como texto (`isoformat(timespec="microseconds")`, `+00:00`) e como `datetime`.
- **CA-03/CA-04:** a CLI abre o outbox com o relógio real (`utc_now`), então o `next_attempt_at` que ela grava é a hora real. O relógio falso do laço começa 10 min antes da hora real e, depois da CLI, é posto 1 s depois dela. Sem isso, o laço com o relógio falso em 2026-10-01 nunca veria os itens como vencidos. É uma consequência de misturar relógios no teste, não um defeito. O CA-03 também confere que o `payload` que chegou à nuvem é o gravado (`InspectionCreate.model_validate(...) == item`).

## Suíte completa

Rodada **sem** `TEST_DATABASE_URL` e **sem** `CI=true`, como pedido pelo orquestrador (outro tester pode estar usando o `partqc_test`). Os testes marcados `db` foram pulados. Esta SPEC não muda a API nem o banco. **O orquestrador roda a suíte com banco antes do PR.**

```text
$ env -u TEST_DATABASE_URL -u CI uv run pytest -q
5465 passed, 724 skipped, 1 warning in 461.93s (0:07:41)
(os 724 pulados são os testes `db`, sem TEST_DATABASE_URL, e os `docker`/`mqtt`; os 96 de test_spec_034.py passaram)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
234 files already formatted

$ uv run pytest -q edge/tests/test_outbox.py edge/tests/test_requeue.py \
    edge/tests/acceptance/test_spec_034.py --cov=qc_edge.outbox --cov=qc_edge.requeue
edge/src/qc_edge/outbox.py      185      4    98%
edge/src/qc_edge/requeue.py      77      2    97%
151 passed
```

Cobertura de `qc_edge.outbox`: 98% (RNF-09 exige ≥ 80%). Os testes de concorrência (CA-03, CA-04, CA-07, publisher em thread, processos paralelos, lock curto) rodaram 3 vezes seguidas sem falha intermitente.

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | baixa | fora dos CAs (arquivo corrompido; relacionado ao §4.2) | 1. Outbox com 2 itens `dead` montado pela API pública. 2. Editar uma linha à mão: `UPDATE outbox SET created_at='<texto>' WHERE inspection_id=?` (ou `attempts='<texto>'`, ou um `inspection_id` que não é UUID). 3. `python -m qc_edge.requeue --outbox-path <arquivo>` (sem `--yes`). | Erro tratado (código 1 ou 2, uma linha de log só com a classe da exceção, como nas outras falhas da CLI), ou a linha listada com o campo marcado como inválido. | Exceção não tratada: código 1 com o traceback inteiro no stderr. `DeadItem` é montado em `SqliteOutbox.dead_items()` (`parse_timestamp`, `int(...)`, `UUID(...)`) e só `sqlite3.Error` é capturado em `main`. A mensagem do `ValueError` **ecoa o valor da coluna**: `ValueError: Invalid isoformat string: '<texto>'` e `invalid literal for int() with base 10: '<texto>'`. O `--yes` funciona nesse arquivo (`requeued 2 item(s)`), porque o `UPDATE` não lê essas colunas. Severidade baixa: só acontece com o SQLite editado à mão ou corrompido, a coluna não é o `payload` nem a chave, e nada é escrito. |

## Testes exploratórios (além dos critérios)

Todos estão no arquivo de aceite como `test_extra_*` e passam, exceto o T-01, que foi verificado à mão e não virou teste.

**API do outbox**

- `requeue_dead([])` e `requeue_dead(())` retornam 0 e não mudam nada: só `None` significa todos.
- Reenviar duas vezes: a segunda retorna 0. `requeue_dead([id_sent])` retorna 0 e a linha continua `sent`.
- 230 `dead`, com 265 ids (205 válidos, 60 desconhecidos e 5 repetidos): retorna 205 e só esses mudam (partes de 100 na mesma transação).
- Tupla e ids repetidos: cada linha conta uma vez.
- `dead_items()`: ordem de `created_at`, `DeadItem` congelado, com exatamente os 4 campos da SPEC (sem `payload`), `created_at` com fuso UTC. Depois do reenvio, a lista fica vazia.
- Um item reenviado é devolvido pelo `fetch_due` (com a versão da SPEC-030).

**CLI: argumentos (security)**

- Saídas exatas: `requeued 3 item(s)` e depois `requeued 0 item(s)` (código 0), e `0 dead item(s); run again with --yes to requeue`.
- O filtro `--id` vale na listagem e no `--yes`: um id desconhecido é ignorado, e um UUID em maiúsculas é aceito na forma canônica.
- 150 `--id` com `--yes`: `requeued 150 item(s)`.
- `--outbox-path` ausente ou vazio dá código 2 e nada é criado no diretório atual.
- `--id` com 10 mil e 200 mil caracteres, com SQL (`' OR 1=1 --`), com um caractere bidi, não hexadecimal ou vazio: código 2. O valor não aparece no stdout, no stderr nem no log, e a saída tem menos de 4000 caracteres. Um UUID com `\n` no fim é aceito pelo `uuid.UUID`, que tira os espaços, e não causa dano (nil UUID).
- Variantes de `--yes` nunca escrevem: `--ye`, `--y`, `-y`, `--YES`, `--yes=1` e `yes` posicional dão código 2 e o arquivo fica com os mesmos bytes (`allow_abbrev=False`). No log aparecem só nomes de opção ou `1 other`.
- `--help` dá código 0.

**CLI: arquivos (security)**

- Arquivo inexistente: código 2. Não são criados nem o arquivo nem `-wal`, `-shm` ou `-journal`.
- Nomes com sintaxe de URI inexistentes (`outbox.sqlite3?mode=rwc`, `#x`, `out%20box`): código 2 e o diretório continua vazio. A URI do SQLite não pode ser injetada pelo caminho.
- Caminhos existentes com espaço, `?`, `#`, `%`, acentos e CJK (inclusive no diretório, `a?b#c%25d`): lista e reenvia o arquivo certo, sem criar outro banco.
- Recusados com código 2, sem criar nada: diretório, `/dev/null`, link simbólico quebrado (o alvo não é criado), link para diretório, link em laço, caminho com caractere de controle, caminho com mais de `PATH_MAX` e caminho com NUL.
- FIFO: código 2 sem travar (subprocesso com timeout de 20 s).
- Arquivo que existe mas não é outbox (texto, vazio, SQLite vazio, SQLite com outra tabela, tabela `outbox` sem as colunas da SPEC-009), com e sem `--yes`: código diferente de 0 (é 2, escolha do dev-report), com o mesmo conteúdo e o diretório sem arquivo novo.
- SQLite com cabeçalho válido e páginas corrompidas: código 2, sem reescrever o arquivo.
- Link simbólico para um outbox real: aceito, e o reenvio vai para o alvo (o `os.stat` segue o link). O link continua link. É o caminho que o operador digitou; não considero achado.
- Caminho relativo: funciona a partir do diretório atual.
- Permissões: com o arquivo `0400`, a listagem funciona e o `--yes` dá código 1 (`outbox access failed (OperationalError)`) sem alterar nada. Com o arquivo `0000`, o código é diferente de 0 nos dois modos (2, com a mensagem "not an outbox file", que é imprecisa mas não vaza nada). O modo `0600` do arquivo é mantido, e os `-wal`/`-shm` criados pela CLI ficam sem permissão para grupo e outros, igual ao arquivo.
- Sem `--yes`, nada é escrito, inclusive com dados confirmados ainda no `-wal` e o `SqliteOutbox` aberto: o arquivo principal fica com os mesmos bytes e as mesmas linhas.

**`last_error` na saída (security)**

- Gravado à mão, com `\n` e uma linha forjada, ANSI (`\x1b[31m`), BEL, `\r`, bidi (U+202E, U+2066/2069), U+200B, U+2028/U+2029, U+0085 ou um surrogate substituído: a listagem tem sempre uma linha por item, e nenhum caractere das categorias `Cc`, `Cf`, `Cs`, `Zl` ou `Zp` chega ao stdout (viram `?`).
- O mesmo vale para um texto hostil passado ao `mark_dead`.
- `NULL` e vazio aparecem como `-`.
- Um `last_error` de 20 mil caracteres gravado à mão fica numa linha só e não é cortado na saída. A SPEC fala do corte em 200 no texto gravado pelo publisher, não na impressão, então não considero achado.

**Payload revalidado pelo contrato vigente**

- Um `payload` `dead` editado à mão para ser inválido no contrato (campo extra, `grade_score=9.5` ou `source` inexistente) e depois reenviado: em 40 ciclos, nunca chega à nuvem (0 envios do id; nenhum corpo de requisição contém o campo ou o valor inválido). O item válido do mesmo outbox é enviado.

**Concorrência**

- Com outra conexão segurando `BEGIN IMMEDIATE`:
  - a listagem (`mode=ro`, WAL) termina em menos de 3 s;
  - com o lock solto depois de 1 s, o `--yes` espera e reenvia (`requeued 2 item(s)`);
  - com o lock segurado, o `--yes` desiste depois de cerca de 5 s com código 1, sem traceback e sem mudar nada (teste `slow`).
- `PublishLoop` real rodando em thread (relógio real, `interval_s=0.05`), 30 itens viram `dead` com a nuvem recusando, a nuvem passa a aceitar e a CLI roda em subprocesso com `--yes`: `requeued 30 item(s)`, os 30 sobem uma vez cada (30 gravações, 30 ids únicos), e `PRAGMA integrity_check` dá `ok`.
- 4 processos `--yes` em paralelo sobre 50 `dead`: a soma dos `requeued` dá exatamente 50.

**Estático e README**

- Importar `qc_edge.requeue` num interpretador limpo não carrega `httpx`, `requests`, `urllib3`, `http.client` nem `PIL`.
- `edge/README.md` cita `python -m qc_edge.requeue`, `--outbox-path`, `--yes`, `dead` e `inspection_id` (§4.3). Conferi também à mão: a seção explica quando usar, conferir antes, voltar a `dead` com o motivo e a idempotência.

**Observações (não são achados)**

- A listagem sem `--yes` (`mode=ro`) deixa `-wal` e `-shm` vazios ao lado de um outbox que estava fechado (documentado no dev-report). O arquivo principal não muda, como pede o CA-05.
- Num diretório sem permissão de escrita, a listagem de um outbox em WAL falha com código 2 e a mensagem "not an outbox file (OperationalError)". O SQLite precisa criar o `-shm`. É um caso raro e a mensagem é imprecisa, mas nada vaza.
- Há uma janela entre o `os.stat` (arquivo regular) e o `sqlite3.connect`: o caminho poderia ser trocado por um FIFO nesse intervalo. O comando é rodado pelo próprio operador na máquina dele, então o risco é desprezível.

## Testes de aceite de SPECs anteriores

Nenhum ajuste. Nenhum teste de aceite anterior falhou.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
