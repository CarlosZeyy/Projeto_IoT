# SPEC-043 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-043](../../docs/specs/SPEC-043-manutencao-pos-deploy.md) |
| Rodada | r1 |
| Autor | developer (Parte A). A Parte B é do security-devops |
| Branch | `spec/SPEC-043-manutencao-pos-deploy` |
| Commits | só o deste relatório. Nenhum código da Parte A foi escrito |

## Resumo

**Parte A interrompida antes de começar, por causa do SPEC_ISSUE-01.** O CA-09 e a primeira frase do CA-08 contradizem a §4.2 e a §7 para uma das quatro URLs mal formadas. Como manda o processo, parei sem escolher uma saída. Nenhum arquivo de produção ou de teste mudou.

## Rastreabilidade (critério de aceite → implementação)

Vazia: nada foi implementado nesta passagem.

## SPEC_ISSUE

### SPEC_ISSUE-01 — A primeira URL **M** tem a porta 6543, e o CA-09 pede para ela um erro que a §4.2 e a §7 não produzem

**Trechos em conflito:**

- A primeira URL **M** é `postgresql://u:<A>@<B>@db.example.org:6543/postgres`.
- **§4.2:** a nova checagem entra "no início" de `_connect`. A §4.2 não muda `apply_migrations` nem `pending_migrations`, que hoje chamam `ensure_supported_connection` antes de `_connect`.
- **§7, "Ordem no `migrate.py`":** "`ensure_supported_connection` vem antes da nova recusa".
- **CA-09:** "*Dado* cada **M**, *quando* se chamam `apply_migrations` e `pending_migrations`, *então* levantam `DatabaseConnectionError`".
- **CA-08:** a primeira frase diz que, com cada **M**, a saída contém `invalid database URL (not shown)`. A segunda frase diz que, com essa mesma URL, a recusa é a da porta 6543. No CA-08, a própria segunda frase mostra a intenção; no CA-09, nada trata esse caso.

**Medição (código atual, `psycopg.connect` substituído por uma função que falha):** o parser devolve `host='<B>@db.example.org'` e `port='6543'`, e as duas funções levantam `UnsupportedConnectionError`, que não é subclasse de `DatabaseConnectionError` (as duas são filhas de `MigrationError`). Implementada a §4.2 ao pé da letra, nada muda nesse caminho, e o CA-09 falha com essa URL.

**Saídas possíveis (a decisão é do architect):**

| Opção | SPEC | Código da Parte A |
|---|---|---|
| (a) O CA-09 e a primeira frase do CA-08 valem para as outras três **M**. Para a URL com 6543, o CA-09 passa a esperar `UnsupportedConnectionError`, sem chamar `psycopg.connect` e sem sentinela | Só os dois CAs | Exatamente a §4.2 |
| (b) `apply_migrations` e `pending_migrations` recusam a URL mal formada antes da checagem da porta, e só o `main` mantém a ordem da §7 | §4.2, §7 e CA-08, se ele mudar | Uma checagem a mais nas duas funções, e a ordem passa a diferir entre elas e o `main` |

**Sugestão do autor:** a opção (a). Ela mantém uma única ordem no módulo, e a URL continua recusada sem conectar e sem mostrar a senha, que é o objetivo do DEP-02. O CA-09 verifica a R-03, então a classificação pelo ADR-019 (exclusão X-7) precisa ser avaliada pelo architect.

### Conferido sem encontrar outro conflito

Leitura do código e sondagens fora do repositório, **sem** a Parte A implementada, para que a retomada não pare de novo pelo mesmo tipo de problema:

- **CA-05:** a saída de `conninfo_to_dict` para as 15 URLs do CA, comparada à mão com a tabela da §4.2, dá o resultado pedido em todas. As quatro **M** caem pela regra esperada: `host` com `@` na primeira, `port` não numérica na segunda e na quarta, `dbname` com `@`, `/` e `:` na terceira.
- **CA-10:** o `register_device.py` não tem a checagem da porta 6543, então as quatro **M** chegam à nova recusa. O conflito é só do `migrate.py`.
- **CA-11:** numa página mínima no `AppTest` com o Streamlit 1.65.0, `TextColumn(width=240)` aparece como `json.loads(proto.columns)["Modelo"]["width"] == 240`. A chave citada na §7 existe.
- **CA-19:** em `dashboard/README.md` e `filters.py`, `acordando` e `free tier` só aparecem nos trechos que a §4.8 troca. `dashboard/src/qc_dashboard/api.py`, linha 6, cita "free tier" num comentário, fora do §3.1 e do CA.
- **CA-13 a CA-15:** `console.html` não traz `no-lan-warning`, `loopback-warning` nem `Outros IPs` fora do `$ip_warning` e do `_other_ips_html`, e `detect_lan_ips` só é chamada em `app.py`, linha 869.

## Como rodar e verificar

Nada a rodar: não há mudança de código.

## Decisões tomadas dentro do escopo da SPEC

Nenhuma.

## Checagens do autor

- [ ] `uv run ruff check .` e `uv run ruff format --check .` limpos: não rodados, sem mudança de código
- [ ] Testes unitários do autor passando: não rodados, sem mudança de código
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova, e o arquivo é da Parte B
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
