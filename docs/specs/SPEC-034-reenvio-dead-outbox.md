# SPEC-034: Reenvio de itens `dead` do outbox

| Campo | Valor |
|---|---|
| Status | In Security |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-009, SPEC-030 (as duas mexem em `edge/src/qc_edge/outbox.py`; esta entra depois) |
| Semana alvo | S5 (**prazo:** `Done` antes da primeira mudança de contrato com a borda em operação, ou seja, antes de a SPEC-016 ou a SPEC-018 entrar em `In Dev`) |
| Requisitos cobertos | RF-06, RF-07, RNF-04, RNF-10; R-05, R-06 |
| ADRs relevantes | ADR-002, ADR-009 |

## 1. Contexto

Na SPEC-009 (`docs/architecture.md` §6.2, passo 8), um item que a API recusa com 413/422 é isolado por bissecção e vira `dead`. A linha fica no arquivo, mas nada a reenvia: a SPEC-009 §3.2 deixou o "reenvio manual de itens `dead`" para uma SPEC futura.

O caso que importa é o da observação do review e do SEC-09-04: se a API recusar **todos** os itens com 422 (por exemplo, numa divergência de versão do contrato, com `extra="forbid"`), a bissecção marca os 100 itens do lote como `dead` num ciclo. Depois que a API (ou a borda) é atualizada, esses itens precisam subir de novo, e hoje só subiriam editando o SQLite à mão.

| Pendência | Origem | Severidade | O que entra aqui |
|---|---|---|---|
| SEC-09-04 | `reviews/SPEC-009/r1-security-report.md` | informativo, **com prazo** | Reenvio de `dead` antes da primeira mudança de contrato com a borda em operação |
| Observação da recusa geral | `reviews/SPEC-009/r1-review-report.md` ("Observação, não é achado") | — | O mesmo caso |

**Contrato, API e ADR.** O reenvio usa a mesma rota (`POST /api/v1/inspections/batch`), o mesmo `InspectionCreate` e a mesma idempotência por `inspection_id` (R-05). O `payload` guardado é revalidado pelo contrato vigente antes do envio, como já acontece (SPEC-009 §4.3). Por isso esta SPEC **não** muda o contrato, a API nem uma regra negociável, e **não** precisa de ADR (`docs/rules.md` R-04; skill `criar-adr`). Um caso que exija **migrar** os `payload` guardados para uma versão incompatível (major) do contrato seria outra decisão, com ADR próprio, e fica fora (§3.2).

## 2. Objetivo

O operador lista os itens `dead` do outbox e os devolve a `pending` com um comando local; o laço de publicação os envia como qualquer pendente, sem duplicar nada na nuvem.

## 3. Escopo

### 3.1 Dentro

- `edge/src/qc_edge/outbox.py`: `SqliteOutbox.dead_items()` e `SqliteOutbox.requeue_dead()` (§4.1).
- `edge/src/qc_edge/requeue.py`: CLI `python -m qc_edge.requeue` (§4.2).
- `edge/README.md`, seção "Envio para a nuvem": quando e como usar o comando (§4.3).
- Testes do autor em `edge/tests/` (fora de `acceptance/`).
- **Tester:** `edge/tests/acceptance/test_spec_034.py`.

### 3.2 Fora

- Botão ou rota no console para o reenvio: não adotado. O console continua mostrando só a contagem de `dead` (SPEC-009); o reenvio é um passo consciente do operador, no terminal.
- Reenvio automático de `dead`: não adotado. Um item recusado de novo voltaria a `dead` em todo ciclo e repetiria a bissecção contra a nossa API.
- Migrar `payload` antigos para uma versão incompatível do contrato: exige ADR e SPEC próprios (§1).
- Apagar linhas `sent` ou `dead`: fora (SPEC-009 §7).
- Prazo e teto do publisher, e o salto do relógio → SPEC-030.

## 4. Requisitos detalhados

### 4.1 Outbox

```python
@dataclass(frozen=True)
class DeadItem:
    inspection_id: UUID
    created_at: datetime        # UTC
    attempts: int
    last_error: str | None

class SqliteOutbox:
    def dead_items(self) -> list[DeadItem]                         # por created_at (e o desempate de hoje)
    def requeue_dead(self, ids: Sequence[UUID] | None = None) -> int
```

- `requeue_dead(None)` devolve a `pending` **todos** os itens `dead`; `requeue_dead(ids)` só os itens `dead` cujo id está em `ids`. Ids que não existem ou que não estão `dead` (`pending` ou `sent`) são ignorados. O retorno é o número de linhas alteradas.
- Cada linha alterada recebe `status='pending'`, `attempts=0`, `next_attempt_at=now` (o relógio do outbox) e `last_error=NULL`. `inspection_id`, `payload`, `created_at` e `sent_at` não mudam. Uma linha `sent` nunca volta (R-05).
- Uma única transação, com o lock e o SQL parametrizado de hoje (SPEC-009 §4.1). `ids` com mais de 100 elementos é processado em partes, na mesma transação.
- `dead_items()` não devolve o `payload`.

### 4.2 CLI `python -m qc_edge.requeue`

```text
python -m qc_edge.requeue --outbox-path <arquivo> [--id <inspection_id> ...] [--yes]
```

- `main(argv: Sequence[str] | None = None) -> int`, com o mesmo parser sem eco das outras CLIs da borda (`qc_edge.argv`, SPEC-025 §4.5): argumento desconhecido → código 2, só nomes de opção no log, nunca valores.
- `--outbox-path` é obrigatório. Arquivo inexistente ou que não é arquivo regular → código 2, e o arquivo **não** é criado (a CLI abre o SQLite em modo que não cria, por exemplo a URI `file:<caminho>?mode=rw`).
- `--id` (repetível) precisa ser um UUID; senão, código 2 sem ecoar o valor.
- **Sem `--yes`** (padrão, só leitura): imprime uma linha por item `dead` selecionado, no formato `<inspection_id> <created_at ISO 8601 UTC> attempts=<n> <last_error ou ->`, e no fim `<k> dead item(s); run again with --yes to requeue`. Não altera nada. Código 0.
- **Com `--yes`:** chama `requeue_dead` e imprime `requeued <k> item(s)`. Código 0, inclusive com `k = 0`.
- A saída nunca traz o `payload` (nem `lot_id`, nem `device_id`, nem valores de confiança) nem a `DEVICE_API_KEY`. O `last_error` é o resumo da recusa da SPEC-009 §4.2 (status e `detail` em texto, cortado em 200 caracteres e sem controles), já sem o corpo da resposta.
- Pode rodar com o `qc-edge` ligado: o SQLite em WAL aceita outro processo, a CLI usa `timeout` de 5 s na conexão e não segura a transação além do `UPDATE`. O laço de publicação pega os itens no próximo ciclo.
- Não faz nenhuma requisição de rede (R-02): só altera o arquivo.

### 4.3 `edge/README.md`

Na seção "Envio para a nuvem": o que é um item `dead`; que, depois de uma atualização da API ou da borda que corrija a recusa, o operador roda `uv run --package qc-edge python -m qc_edge.requeue --outbox-path <arquivo>` para conferir e o mesmo com `--yes` para reenviar; que um item ainda inválido volta a `dead` com o motivo; e que a idempotência por `inspection_id` impede duplicatas na nuvem.

## 5. Critérios de aceite

Contexto comum: como na SPEC-009 §5 (nuvem falsa com `httpx.MockTransport` e idempotência por `inspection_id`, relógio falso, `random.Random(0)`, SQLite real em `tmp_path`). Marcadores gerados com `secrets`.

- **CA-01** — *Dado* um outbox com 3 itens `dead`, 2 `pending` e 1 `sent` (montados por `put` e pelos `mark_*` da SPEC-009), *quando* `requeue_dead()` roda com o relógio em T, *então* retorna 3, os 3 ficam `pending` com `attempts=0`, `next_attempt_at` igual a T e `last_error` nulo, e as outras 3 linhas ficam iguais em todas as colunas (comparação antes/depois).
- **CA-02** — *Dado* o mesmo outbox, *quando* `requeue_dead([id_dead_1, id_pending_1, id_sent, uuid4()])` roda, *então* retorna 1, só `id_dead_1` muda, e `id_sent` continua `sent` com o mesmo `sent_at`.
- **CA-03 (R-05)** — *Dado* 4 itens no outbox e a nuvem falsa respondendo 422 a qualquer lote, *quando* `run_once` roda até não haver pendentes, *então* os 4 ficam `dead`; *quando*, em seguida, a nuvem passa a aceitar, `main(["--outbox-path", <arquivo>, "--yes"])` roda e `run_once` roda até `pending=0`, *então* os 4 ficam `sent`, a nuvem tem exatamente 4 ids únicos (os 4 originais) e 0 gravações duplicadas, e `stats().dead == 0`.
- **CA-04** — *Dado* 1 item `dead` que a nuvem continua recusando (422), *quando* é reenviado com `--yes` e `run_once` roda até não haver pendentes, *então* ele volta a `dead` com `last_error` não vazio e não é mais enviado em 5 ciclos seguintes.
- **CA-05 (security, R-03)** — *Dado* 2 itens `dead` cujo `payload` tem `lot_id` igual a um marcador e `DEVICE_API_KEY` igual a outro marcador no ambiente, *quando* `main(["--outbox-path", <arquivo>])` roda, *então* o código é 0, o stdout tem exatamente 3 linhas (2 itens e o resumo `2 dead item(s); run again with --yes to requeue`), cada linha de item começa com o `inspection_id`, nenhum marcador aparece no stdout, no stderr nem no log, e o arquivo não muda (bytes iguais e as mesmas linhas).
- **CA-06** — *Dado* `--outbox-path` de um arquivo inexistente numa pasta existente, *quando* `main` roda (com e sem `--yes`), *então* o código é 2 e o arquivo não é criado; *dado* `--id nao-e-uuid-<marcador>` ou `--token=<marcador>`, *então* o código é 2 e o marcador não aparece no stdout, no stderr nem no log.
- **CA-07** — *Dado* um `SqliteOutbox` aberto no processo (como o `qc-edge` ligado) com 2 itens `dead`, *quando* `main([... , "--yes"])` roda num subprocesso sobre o mesmo arquivo, *então* o código é 0, `stats().pending` no outbox aberto passa a 2, e `PRAGMA integrity_check` dá `ok`.
- **CA-08 (R-02)** — *Dado* um espião em `socket.socket.connect` e em `socket.getaddrinfo`, *quando* `main` roda com e sem `--yes`, *então* o espião registra 0 chamadas.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | `dead_items`, `requeue_dead` (todos, por id, ids não `dead`, mais de 100 ids), CLI (formato, `--yes`, erros), concorrência com o outbox aberto | `edge/tests/` |
| Aceite (tester) | Um por CA | `edge/tests/acceptance/test_spec_034.py` |

- Mock só de fronteiras: a nuvem (`httpx.MockTransport`), o relógio e o RNG; os espiões de socket do CA-08.
- O subprocesso do CA-07 roda o `python -m qc_edge.requeue`, não o pytest.

## 7. Riscos e notas para o implementador

- **Ordem com a SPEC-030:** a SPEC-030 muda o `fetch_due` (salto do relógio). Esta SPEC entra depois dela, para não haver dois conflitos no mesmo arquivo. Um item reenviado tem `next_attempt_at = now` e é devolvido pelo `fetch_due` das duas versões.
- **`attempts=0`:** o backoff recomeça do início para o item reenviado (SPEC-009 §4.3), o que é o esperado depois de uma correção.
- **R-06:** o `--stub-model` nunca grava no outbox (SPEC-009 §4.4), então não existe item `stub-v0` para reenviar.
- **Mudança de contrato:** antes de atualizar a API para uma versão nova do contrato com a borda em operação, a ordem segura é atualizar a API primeiro (ela aceita os dois formatos numa ampliação compatível) e só depois a borda; se houver itens `dead` da transição, este comando os devolve. É uma nota de operação, sem requisito novo aqui.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde; `ruff` limpo; cobertura de `qc_edge.outbox` ≥ 80% (RNF-09)
- [ ] `edge/README.md` atualizado
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016), antes de a SPEC-016 ou a SPEC-018 entrar em `In Dev`

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-19 | SPEC criada (`Draft`). Decisões do architect: (a) reenvio só manual, por CLI local com `--yes`, sem botão no console nem reenvio automático; (b) sem mudança de contrato, de API nem ADR (mesma rota, mesmo `payload`, revalidação pelo contrato vigente); (c) depende da SPEC-030 por tocar o mesmo módulo. | SEC-09-04 de `reviews/SPEC-009/r1-security-report.md`; observação da recusa geral em `reviews/SPEC-009/r1-review-report.md`; SPEC-009 §3.2 | Orquestrador, a pedido do humano |
| 2026-10-19 | Aprovada pelo humano (`Draft` → `Ready`), com as respostas recomendadas às perguntas do architect (comentário do PR #36). | Aprovação humana | Humano (Carlos) |
