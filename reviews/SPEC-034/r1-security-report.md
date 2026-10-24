# SPEC-034 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-034](../../docs/specs/SPEC-034-reenvio-dead-outbox.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `origin/main...1a26fab` (base `31979b9`, 9 commits, de `c084929` a `1a26fab`) |
| **Veredicto** | **PASS** |

Não há achado bloqueante, alto ou médio, nem `SPEC_ISSUE`. Ficam 2 achados baixos e 2 informativos. O SEC-34-01 confirma o RV-01 do reviewer (o T-01 do tester) e mede a consequência no laço de envio. Concluo que ele **pode ficar como pendência** e não exige uma rodada nova (justificativa no item 1 de "Pontos pedidos pelo orquestrador"). O SEC-34-02 confirma o RV-02. A SPEC não foi reaprovada sob o ADR-019 (conferi o Histórico e o diff da SPEC, que traz só o status e a rodada).

## Superfície analisada

- **CLI local nova:** `edge/src/qc_edge/requeue.py` (parser sem eco da SPEC-025, validação do `--outbox-path`, `--id` como UUID, modo só leitura sem `--yes`, saída e códigos 0/1/2, saneamento do `last_error`).
- **Outbox:** `edge/src/qc_edge/outbox.py`: `open_existing` (URI `file:...?mode=ro|rw` com `quote`, timeout de 5 s, recusa do que não é outbox), `dead_items` (sem `payload`) e `requeue_dead` (`WHERE status = 'dead'`, partes de 100 numa transação).
- **Interação com o laço da SPEC-009/030:** `fetch_due`, `PublishLoop.run_once` e `_load` (revalidação do `payload` pelo contrato vigente), para medir o RV-01.
- **Documentação:** `edge/README.md`, seção "Reenviar itens `dead`".
- **Fora do diff (conferido):** nada mudou em `api/`, `dashboard/`, `packages/contracts`, `infra/`, `.github/`, `pyproject.toml`, `uv.lock` ou `.env.example`. Não há rota nova, autenticação nova, mudança de RLS ou de CORS, nem variável de ambiente nova. A CLI não lê `DEVICE_API_KEY` nem `CLOUD_API_URL` e não importa nada de rede.

Verificações próprias, com script no scratchpad da sessão, fora do repositório e sem banco Postgres:

1. Outbox real com 3 itens, 2 `dead`, e um `created_at` adulterado à mão numa das linhas `dead`. Sem `--yes`, a saída é código 1 com traceback no stderr, terminando em `ValueError: Invalid isoformat string: '<valor da coluna>'`. Com `--yes`, a saída é `requeued 2 item(s)` (código 0), e em seguida `SqliteOutbox.fetch_due()` levanta `ValueError`. Isso confirma o RV-01.
2. `env -u TEST_DATABASE_URL -u CI uv run pytest -q edge/tests/test_requeue.py edge/tests/test_outbox.py edge/tests/acceptance/test_spec_034.py edge/tests/acceptance/test_spec_009.py edge/tests/acceptance/test_spec_030.py`: 324 passed e 1 skipped (o caso `db`). `ruff check edge` limpo.
3. Busca de padrões de segredo no diff (URLs de Postgres, JWT, `password=`, chaves literais): nenhuma ocorrência em código ou teste. A única ocorrência é o texto do review-report que descreve essa mesma busca. Nenhuma empresa citada (R-13).

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-34-01 | baixa | input (disponibilidade) | `edge/src/qc_edge/requeue.py:134-146`, `edge/src/qc_edge/outbox.py:330-345` e `:249-280`, `edge/src/qc_edge/publish_loop.py:172-174` | **RV-01 / T-01, confirmado.** `dead_items()` e `fetch_due()` convertem `inspection_id`, `created_at`, `attempts` (e `next_attempt_at`) sem tratar linha inválida, e `main` só captura `sqlite3.Error`. Com uma linha `dead` adulterada: (a) a listagem sai com código 1 e traceback que ecoa o valor da coluna; (b) o `--yes` não lê essas colunas e devolve a linha a `pending`; (c) a partir daí, o `fetch_due` do laço levanta `ValueError` em todo ciclo (a cada 2 s), o `run_once` só loga `publish cycle failed unexpectedly` com o traceback, e **nenhum** item pendente sobe até a linha ser corrigida. A linha adulterada ordena depois dos timestamps válidos, mas entra na janela de 100 do `fetch_due` sempre que houver 100 pendentes ou menos, que é o caso da demo. **Por que é baixa e não bloqueia:** ver item 1 de "Pontos pedidos pelo orquestrador". Em resumo: só um processo com escrita no arquivo `0600` do próprio usuário cria a linha, e esse ator já obtém o mesmo efeito, ou pior, sem o comando. Nenhum caminho de código grava esses campos fora do formato. A fragilidade do laço já existe desde a SPEC-009 para uma linha `pending`. Não há perda nem duplicata (R-05), não há vazamento de `payload` ou chave (R-03), e nada sai da LAN (R-02). | **Nenhuma nesta SPEC.** Para a próxima SPEC de manutenção da borda (registrar em `docs/plan.md` §3): (1) em `requeue.main`, capturar também `ValueError`/`TypeError` em volta de `list_dead`/`requeue_dead`, com código 1 e log só com a classe, como já é feito com `sqlite3.Error`; (2) em `dead_items()` e `fetch_due()`, pular a linha inválida e logar só o `rowid` e a classe da exceção, sem o valor, para que uma linha ruim não pare o envio das outras; (3) um teste de aceite com a linha adulterada nos dois caminhos. Até lá, vale a nota de operação do item 1. |
| SEC-34-02 | baixa | input (mensagem) | `edge/src/qc_edge/requeue.py:134-137` | **RV-02, concordo.** Qualquer `sqlite3.Error` na abertura, inclusive `OperationalError` por permissão (`0000`), por diretório sem escrita para o `-shm` do WAL ou por I/O, sai como `--outbox-path is not an outbox file (<classe>)`, com código 2. Nada vaza, porque o log tem só a classe. O efeito é só levar o operador a desconfiar do arquivo errado. | **Nenhuma nesta SPEC.** Separar `NotAnOutboxError`/`DatabaseError` ("não é outbox") de `OperationalError` ("não foi possível abrir") na mesma SPEC de manutenção do SEC-34-01. |
| SEC-34-03 | informativo | input (SQL) | `edge/src/qc_edge/outbox.py:372` | O `UPDATE` com `IN (...)` é montado com f-string. O item do checklist §6 diz "sem f-string em query". O texto interpolado é só a constante `update` e uma sequência de `?` gerada a partir de `len(chunk)`, que é no máximo 100 e vem do código. Todos os valores, `now` e os ids já canonizados por `UUID(...)`, vão como parâmetros. Não há caminho para entrada externa no texto do SQL, e o próprio código documenta isso. Cumpre o objetivo do item (SQL parametrizado). É o idioma usual para listas `IN` no `sqlite3`. | Nenhuma. |
| SEC-34-04 | informativo | input (arquivo) | `edge/src/qc_edge/requeue.py:129`, `edge/src/qc_edge/outbox.py:200-201` | Há uma janela entre o `os.stat` (arquivo regular) e o `sqlite3.connect`, também registrada pelo tester. Quem troca o caminho nesse intervalo precisa ter escrita na pasta do outbox do próprio operador, que roda o comando na máquina dele. A URI usa `quote(...)` sobre o caminho absoluto, então `?`, `#` e `%` no nome não injetam parâmetros da URI (como `mode=rwc`), e o `mode=ro|rw` nunca cria o arquivo. | Nenhuma. |

## Pontos pedidos pelo orquestrador

### 1. O RV-01 (SEC-34-01) pode ficar como pendência?

**Sim, como baixa, sem rodada nova.** Analisei os três eixos pedidos.

**Disponibilidade do envio na demo.** O efeito existe: uma linha `pending` inválida para o laço inteiro, e o `qc-edge` passa a logar um traceback a cada 2 s. Para chegar a isso, porém, é preciso escrever no SQLite com valores fora do formato:

- Todos os escritores do outbox são código do projeto e gravam formatos fixos. `put` grava `str(UUID)` e `format_timestamp` (UTC, largura fixa), o `attempts` é inteiro, e `mark_*` e `requeue_dead` não tocam nessas colunas.
- Uma corrupção de página do SQLite dá `sqlite3.DatabaseError`, que a CLI já trata (o tester testou páginas corrompidas: código 2, nada reescrito).
- O `edge/README.md` só mostra um `sqlite3 ... "select ..."` de leitura. Nenhum procedimento documentado edita o arquivo à mão, e a nova seção substitui justamente a edição manual que a SPEC queria evitar.
- O passo 1 do README (listar antes de reenviar) falha com código 1 e traceback **antes** do `--yes`. Um operador que segue o README não chega ao passo 2 sem perceber o problema.
- O `--id` permite reenviar só os itens válidos, sem tocar na linha ruim.

Na demo, o outbox é criado e escrito só pelo `qc-edge`, então o caminho não ocorre sem uma ação deliberada sobre o arquivo.

**Modelo de ameaça.** O arquivo é `0600`, numa pasta `0700` do usuário que roda o `qc-edge`. Quem consegue adulterar uma linha `dead` também consegue pôr `status='pending'` direto, adulterar uma linha `pending` (o mesmo travamento, já presente desde a SPEC-009), apagar o arquivo ou trocar `payload`. O comando não cruza nenhuma fronteira de confiança e não dá a esse ator capacidade nova. É uma fragilidade de robustez preexistente, não uma vulnerabilidade introduzida.

**R-05 (idempotência).** Continua íntegra. O `fetch_due` falha antes de qualquer envio, então nada é marcado `sent` nem `dead` (com `items` vazio, o `_retry` do `run_once` não altera linha nenhuma), e nada se perde: todas as linhas continuam no arquivo. Depois que a linha é corrigida, os itens sobem uma vez cada, porque a nuvem deduplica por `inspection_id` e o CA-03 prova 0 duplicatas. Uma linha `sent` nunca volta (`WHERE status = 'dead'`, CA-02).

**R-06 (dado simulado).** Não é afetado. O `--stub-model` não grava no outbox (SPEC-009 §4.4), e o reenvio não altera o `payload`, então o `source` gravado chega igual à nuvem. Um `payload` editado para fugir do contrato (por exemplo, um `source` inexistente) é recusado pelo `_load` e volta a `dead` sem ser enviado: o teste exploratório do tester rodou 40 ciclos com 0 envios.

**Vazamento.** O traceback da listagem e o log do laço ecoam o valor da coluna adulterada (`created_at`, `attempts` ou `inspection_id`), nunca o `payload` nem o `last_error`, que não são convertidos em `dead_items`. O valor sai no terminal e no log locais de quem escreveu a coluna. O CA-05 (outbox válido) continua valendo.

**Nota de operação até a correção** (não exige mudança de código nem de SPEC; quem decide se vira texto no README é o humano ou a SPEC de manutenção). Se a listagem sair com código 1 e um traceback, **não** rode o `--yes` sem `--id`. Reenvie só os ids listados como válidos, ou corrija a linha. Se o envio parar e o log do `qc-edge` repetir `publish cycle failed unexpectedly` com `ValueError`, há uma linha `pending` inválida no outbox, e é preciso corrigi-la ou movê-la para fora antes de o laço voltar a enviar.

**Prazo.** A correção não precisa entrar antes da SPEC-016 ou da SPEC-018. O cenário que motivou a SPEC, a recusa geral por divergência de contrato, produz linhas `dead` válidas, que este comando trata corretamente (CA-03 e CA-04).

### 2. O resto do diff

- **Entrada (CLI):** `QuietArgumentParser` com `allow_abbrev=False`. Argumento desconhecido, `--id` que não é UUID e variantes de `--yes` saem com código 2 e logam só nomes de opção (tester: 16 casos do CA-06, `--id` de 200 mil caracteres, SQL, bidi). `--outbox-path` precisa ser arquivo regular existente com a tabela `outbox` e as colunas exatas da SPEC-009. O arquivo, o `-wal`, o `-shm` e o `-journal` nunca são criados num caminho inexistente. FIFO, `/dev/null`, diretório, links quebrados ou em laço e NUL são recusados.
- **Só leitura de verdade:** sem `--yes`, o arquivo é aberto com `mode=ro`, o que impede o checkpoint de um `-wal` pendente. O CA-05 compara os bytes do arquivo. Os `-wal` e `-shm` que o SQLite pode criar herdam o modo `0600` do banco (verificado pelo tester).
- **SQL:** parametrizado em `dead_items` e `requeue_dead`, em partes de 100 dentro de uma única transação, com rollback de todas as partes em caso de falha (teste do autor). Ver também o SEC-34-03.
- **R-05:** o `UPDATE` exige `status = 'dead'`. `inspection_id`, `payload`, `created_at` e `sent_at` não mudam. Com 4 processos `--yes` em paralelo, a soma dá exatamente o total (tester).
- **R-02:** a CLI não importa `httpx`, `requests`, `urllib3` nem `http.client`, e os espiões de socket registram 0 chamadas (CA-08).
- **R-03:** a CLI não lê a chave nem o `payload`. O `last_error` é impresso com `Cc`, `Cf`, `Cs`, `Zl` e `Zp` trocados por `?`, então um texto gravado não forja linha nem manda sequência ANSI ao terminal.
- **Concorrência:** o timeout de 5 s fica na conexão da CLI, e a transação dura só o `UPDATE`. O `put` da captura (timeout padrão de 5 s do `sqlite3`) não fica bloqueado além disso, e o `PRAGMA integrity_check` dá `ok` com o `PublishLoop` real rodando em thread (CA-07 e exploratório).
- **R-07/R-13:** todos os 9 commits têm o trailer `Agent:`. Os do developer tocam só `edge/src`, `edge/tests/test_requeue.py`, `edge/README.md` e o dev-report. O do tester toca só `edge/tests/acceptance/test_spec_034.py` e o test-report. Os do orchestrator tocam só `docs/plan.md` e o status das SPECs, inclusive o `Done` da SPEC-035, que é manutenção do processo. O autor é a identidade `noreply` do CarlosZeyy em todos.

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota; comparação em tempo constante | N/A: nenhuma rota nova nem alterada. A CLI é local e não fala com a nuvem. |
| Entradas validadas (tamanho, tipo real da imagem, regex de IDs, `extra="forbid"`) | ✅ `--id` validado como UUID sem eco, `--outbox-path` validado (regular, existente, outbox) e não criado. O `payload` continua revalidado pelo `InspectionCreate` (`extra="forbid"`) antes do envio. Não há imagem envolvida. Resíduo: SEC-34-01 (linha adulterada), baixo. |
| SQL sempre parametrizado, sem f-string em query | ✅ Todos os valores são parâmetros. A f-string monta só os `?` (SEC-34-03, informativo). |
| RLS ligado; `DATABASE_URL` e `service_role` só na API | N/A: banco da nuvem intocado. |
| CORS fechado ou mínimo | N/A: nada mudou. |
| Logs sem segredos e sem payloads de imagem | ✅ Logs com nomes de opção ou classe de exceção. Não há `payload`, chave nem caminho de foto. O traceback do SEC-34-01 ecoa só uma coluna local adulterada. |
| Dependências novas | ✅ Nenhuma (`pyproject.toml` e `uv.lock` intocados). `urllib.parse` e `unicodedata` são da biblioteca padrão. |
| Deploy (variáveis no provedor, health check, free sem cartão) | N/A: nada de deploy. Nenhuma variável nova (R-01). |
| Reaprovação delegada (ADR-019) | ✅ Não houve reaprovação nesta branch. O diff da SPEC traz só o status e a rodada. |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma dependência nova. |

## Ações pendentes (não bloqueiam o merge)

1. Registrar o SEC-34-01 e o SEC-34-02 como candidatos da próxima SPEC de manutenção da borda (`docs/plan.md` §3), com as correções da tabela.
2. Até essa correção, seguir a nota de operação do item 1: listar antes, não usar `--yes` sem `--id` se a listagem falhar, e saber reconhecer o `ValueError` repetido no log do `qc-edge`.

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
