# SPEC-034 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-034](../../docs/specs/SPEC-034-reenvio-dead-outbox.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `origin/main...8126035` (base `31979b9`) |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `edge/src/qc_edge/requeue.py:138-146`, `edge/src/qc_edge/outbox.py:330-345` | É o T-01 do test-report, que reproduzi: com uma linha `dead` editada à mão (`created_at='SECRETVALUE'`), a listagem sai com código 1 e um traceback inteiro no stderr que termina em `ValueError: Invalid isoformat string: 'SECRETVALUE'`. `main` só captura `sqlite3.Error`, e o `ValueError` do `parse_timestamp`, do `int(...)` ou do `UUID(...)` em `dead_items()` passa direto. Tem uma consequência que o test-report não cita: o `--yes` funciona nesse arquivo (`requeued 2 item(s)`) e devolve a linha adulterada a `pending`. A partir daí, o `fetch_due` do laço (mesmo `parse_timestamp`) falha em todo ciclo, e o `run_once` só registra "publish cycle failed unexpectedly". Enquanto a linha não for corrigida, nenhum item pendente sobe. Essa fragilidade já vem da SPEC-009 (uma linha `pending` adulterada faz o mesmo), mas agora o comando abre um caminho de `dead` para `pending`. **Não bloqueia:** só acontece com o SQLite editado à mão ou corrompido, o valor ecoado está numa coluna local que não é o `payload` nem a chave, vai para o terminal do próprio operador, e a listagem (passo 1 do README) já mostra o problema antes do `--yes`. | Em `main`, capturar também `ValueError` (e `TypeError`) em volta de `list_dead`/`requeue_dead`. Sair com código 1 e logar só a classe (`outbox has an invalid row (ValueError)`), como já é feito com `sqlite3.Error`. Num ciclo de manutenção, deixar `dead_items()` e `fetch_due()` resistentes a linhas inválidas: pular a linha e logar só o `rowid`. |
| RV-02 | baixa | `edge/src/qc_edge/requeue.py:133-137` | Qualquer `sqlite3.Error` na abertura vira `--outbox-path is not an outbox file (...)` com código 2. Isso inclui um arquivo `0000`, um diretório sem escrita em que o SQLite precisa criar o `-shm` do WAL e um erro de I/O. Nada vaza, mas a mensagem leva o operador a desconfiar do arquivo errado (o test-report também registrou isso, como observação). | Separar a mensagem: `NotAnOutboxError` e `sqlite3.DatabaseError` "não é outbox", e `sqlite3.OperationalError` com algo como `cannot open --outbox-path (OperationalError)`, mantendo o código escolhido no dev-report. |

Sem achados bloqueantes, altos ou médios.

## Decisão sobre o T-01

O T-01 **não bloqueia** e fica como baixa (RV-01). Motivos:

- Fica fora dos CAs: o CA-05 trata da listagem de um outbox válido, e para chegar ao erro é preciso adulterar o arquivo.
- Não é vazamento no sentido do §4.2: o valor ecoado é o de `created_at`, `attempts` ou `inspection_id`, nunca o `payload` nem a `DEVICE_API_KEY`, e sai no terminal local de quem editou o arquivo.
- Nada é escrito na listagem.

A correção sugerida é pequena e pode entrar numa SPEC de manutenção da borda.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Os itens do §3.1 foram entregues (`dead_items`, `requeue_dead`, CLI, README, testes do autor e do tester), e nada do §3.2 entrou: nem botão, nem reenvio automático, nem migração de `payload`, nem remoção de linhas. Nenhum CA mudou. O diff da SPEC traz só o status e a rodada, e não houve reaprovação sob o ADR-019 (conferido no Histórico). O dev-report tem a rastreabilidade de CA-01 a CA-08 e do §4.1. Avaliei as escolhas do dev-report e nenhuma exige `SPEC_ISSUE` ou ADR. O `open_existing` como `classmethod` é necessário para o "abre em modo que não cria" do §4.2 e não muda o construtor da SPEC-009. O `mode=ro` sem `--yes` reforça o "não altera nada" do CA-05. "Não é outbox → 2" estende o espírito do §4.2. "Falha do SQLite → 1" segue o padrão de `qc_edge.privacy` num caso que a SPEC não cobre. O saneamento extra do `last_error` é defesa em profundidade. O filtro `--id` fica na CLI e mantém a assinatura de `dead_items()`. O commit `8126035` do orquestrador marca a SPEC-035 como `Done` no arquivo dela: é manutenção do processo, não escopo da SPEC-034. |
| 2. Regras inegociáveis | ✅ | R-01/R-12: nenhuma dependência nova, e `pyproject`, `uv.lock` e `.env.example` não mudaram. R-02: a CLI não importa rede (teste `test_extra_requeue_module_imports_no_network_library` e CA-08). R-03: a busca de padrões no diff (`postgres://`, `eyJ`, `password=`, chaves) não achou nada, e os marcadores dos testes vêm de `secrets`. R-04: contrato intocado. R-05: `sent` nunca volta (`WHERE status = 'dead'`), e o CA-03 mostra 4 ids únicos e 0 duplicatas. R-06: N/A (o stub não grava no outbox). R-07: `e000e0d`, `29a4c31` e `8be62b0` têm `Agent: developer` e tocam só `edge/src`, `edge/tests/test_requeue.py`, `edge/README.md` e o dev-report. `688f380` tem `Agent: tester` e toca só `edge/tests/acceptance/test_spec_034.py` e o test-report. `c084929`, `e7c023d` e `8126035` têm `Agent: orchestrator` e tocam só `docs/plan.md` e os status das SPECs. Todos os commits têm o trailer. R-13: autor `Carlos Moises <…+CarlosZeyy@users.noreply.github.com>`, com Conventional Commits. |
| 3. Corretude | ✅ (RV-01, RV-02) | O SQL é parametrizado: no `IN (...)` só os `?` entram no texto, em partes de 100 dentro de uma única transação (`with self._lock, self._conn`, sem commit entre os `UPDATE`). O `next_attempt_at` vem do `format_timestamp` (UTC, largura fixa), e a ordenação textual de `created_at` continua válida. A URI do SQLite usa `quote(...)`, então `?`, `#` e `%` no caminho não injetam parâmetros (testado). O timeout de 5 s fica na conexão. O `UPDATE` sem leitura prévia na transação pega o lock de escrita direto, com o busy handler. Não há I/O em handler async: a CLI é síncrona. Os ids repetidos ou em outra grafia viram a forma canônica. O único ponto fraco são as linhas adulteradas (RV-01) e a mensagem de abertura (RV-02). |
| 4. Testes | ✅ | Test-report PASS, com um teste por CA (`test_ca01` a `test_ca08`, 96 casos com os exploratórios). Os testes não são tautológicos: o CA-01 e o CA-02 comparam todas as colunas antes e depois, o CA-03 confere o `payload` que chegou à nuvem e o número de gravações, o CA-05 compara os bytes do arquivo, o CA-07 usa um subprocesso `python -m qc_edge.requeue`, não o pytest, e o CA-08 espiona `connect` e `getaddrinfo`. Os mocks ficam só nas fronteiras (`httpx.MockTransport`, relógio, RNG, socket). Nenhum teste chama o pytest em subprocesso, e não há credencial literal em URL. A cobertura de `qc_edge.outbox` é de 98% (RNF-09). Nenhum teste de aceite de SPEC anterior foi ajustado. Rodei, sem banco: `edge/tests/test_requeue.py`, `test_outbox.py` e os aceites das SPECs 034, 009 e 030 deram 324 passed e 1 skipped (db). |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos (rodei). Funções pequenas com type hints, sem `print` (a saída vai por `sys.stdout.write`, que é a saída do comando, e o log por `logging`) e sem código morto. O README ganhou a subseção do §4.3. |
| 6. Segurança | N/A | A SPEC tem a tag `security`, mas a autoria é do developer, então o portão é do `security-devops`, que precisa emitir o `r1-security-report.md` PASS antes do merge (R-09). Do meu lado, conferi: SQL parametrizado, nenhum segredo lido ou impresso, `--id` validado como UUID sem eco e o caminho validado antes de abrir. |

## Pontos positivos

- A listagem abre com `mode=ro`, o que garante o "não altera nada" mesmo com um `-wal` pendente, e os testes provam que os bytes do arquivo ficam iguais.
- O `open_existing` nunca cria o arquivo, nem os `-wal`/`-shm`/`-journal` de um caminho inexistente, e recusa bancos sem a tabela `outbox` da SPEC-009.
- O `last_error` impresso é neutralizado (`Cc`, `Cf`, `Cs`, `Zl` e `Zp` viram `?`), então um texto gravado não forja linha nem mexe no terminal.
- A bateria exploratória do tester é forte: FIFO, links, URI no nome, permissões, lock segurado, `PublishLoop` real em thread e 4 processos `--yes` em paralelo com soma exata.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
