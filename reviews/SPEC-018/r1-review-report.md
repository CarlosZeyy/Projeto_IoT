# SPEC-018 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-018](../../docs/specs/SPEC-018-heartbeat-dispositivos.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `spec/SPEC-016-ferramentas-manuais...89e00be` (branch encadeada; base é a branch da SPEC-016, ainda não mergeada) |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante nem alto. Quatro achados baixos, que não bloqueiam.

## Verificação feita

- Leitura de `docs/rules.md`, `reviews/checklist.md`, a SPEC-018, os relatórios r1 (dev e test), a skill `contrato-api` e o `docs/architecture.md` §3, §4, §5, §6.4 e §10, no estado da branch.
- `git log spec/SPEC-016-ferramentas-manuais..HEAD` (11 commits) e `git show --stat` de cada um, com o trailer `Agent:`.
- `uv run ruff check .` e `uv run ruff format --check .`: limpos (263 arquivos).
- Suíte completa no ambiente do CI, com `CI=true` e `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`: **7684 passed, 75 skipped, 1 warning** (712 s), o mesmo resultado do test report; os pulados são os de Docker, MQTT, modelo real e torch.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `api/src/qc_api/repositories/devices.py:58-63` | O `last_source` usa um `left join lateral` que, para cada dispositivo, ordena todas as inspeções dele por `received_at desc, inspected_at desc, inspection_id desc`. Só existe o índice `(device_id)` (`001_init.sql:71`), então o custo cresce com o histórico de cada dispositivo, a cada recarga do cache (30 s) da página. Com o volume da demo, é desprezível (o próprio dev report registra isso na observação 3). | Se o histórico crescer, uma migração futura com o índice `(device_id, received_at desc)`. Fica para o architect decidir, sem mudança nesta SPEC. |
| RV-02 | baixa | `infra/migrations/004_device_heartbeat.sql:24-32` | `last_heartbeat_at` e `hb_sent_at` não têm `check` de faixa. Uma linha escrita fora da API (SQL Editor) com `infinity` derruba o `GET /api/v1/devices` com 500, e um `last_heartbeat_at` no futuro deixa o dispositivo `online` até essa hora passar mais 180 s. A SPEC não pede essas restrições (a §4.2 lista as `check`), e o `last_seen_at` já tinha a mesma exposição. Confirmado pelo tester (observação 1) e pelo dev (observação 2). | Proposta ao architect: a mesma faixa da `002` em `inspections` (`>= 0001-01-01` e `< 10000-01-01`) para as colunas de data de `devices`, numa SPEC futura. |
| RV-03 | baixa | `edge/src/qc_edge/heartbeat.py:130-131` | Uma exceção inesperada ao **montar** o heartbeat vira `logger.exception(...)`, com a mensagem e o traceback completos, enquanto uma exceção inesperada do **envio** (linhas 140-142) registra só o nome da classe, "porque a mensagem pode levar qualquer coisa". Hoje o `build()` só lê `SinkStats` e `model_info` (nada sensível), então não há vazamento, mas a regra fica inconsistente dentro do mesmo método. | Registrar só `type(exc).__name__` também no `build()`, como no envio, numa próxima mudança desse módulo. |
| RV-04 | baixa | `edge/src/qc_edge/heartbeat.py:51` | `_cap(value: int)` recebe um `float` em `_cap(self._monotonic() - self._started_at)` (linha 113). O comportamento está certo (`int()` trunca, como pede a SPEC), mas o type hint não corresponde ao uso. | `def _cap(value: float) -> int`. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Todos os itens da §3.1 estão no diff: contrato 0.5.0, migração `004` (próximo número livre depois da `003` da SPEC-016), as duas rotas, `send_heartbeat` e `HeartbeatLoop`, página "Dispositivos", `.env.example`, `edge/README.md`, `packages/contracts/README.md` e `dashboard/README.md`. Nada fora do escopo: sem histórico de heartbeats, sem alerta, sem MQTT, sem heartbeat no simulador. Nenhum CA alterado. Há rastreabilidade CA → arquivo → teste no dev report. Nenhuma reaprovação delegada (ADR-019) nesta branch: os commits do orquestrador (`92014ca`, `ea13d41`, `89e00be`) mudam só o status, a rodada e a linha do Histórico sobre o encadeamento (decisão do humano), e o `plan.md`. As decisões do dev report estão dentro do que a SPEC deixa em aberto (ver abaixo). |
| 2. Regras inegociáveis | ✅ | R-01: nenhuma dependência nova (`uv.lock` muda só a versão do `qc-contracts`). R-02: o `HeartbeatCreate` não tem campo de imagem nem dado pessoal (teste de aceite confere o corpo exato). R-03: nenhum segredo no diff (busca por URLs de banco com credencial embutida, por atribuições de senha, por tokens JWT e por chaves literais); `HEARTBEAT_INTERVAL_S` no `.env.example`; chaves geradas em tempo de execução nos testes. R-04: payload novo só em `packages/contracts`, minor 0.4.0 → 0.5.0 (`__version__`, `pyproject.toml`, `uv.lock` e histórico do README), sem mudar schema existente; SPEC com a tag `contrato`. R-05: N/A (o heartbeat é um `UPDATE` da própria linha, idempotente por natureza; nenhuma escrita de inspeção mudou). R-06: o laço nunca é registrado com `--stub-model` (CA-10 com controle positivo); `last_source` mostra o simulador como `simulado` e liga o selo. R-07: ver abaixo. R-11: N/A. R-12: `api/` e `dashboard/` sem torch/onnxruntime; nenhuma dependência nova. R-13: todos os commits com a identidade CarlosZeyy (noreply), Conventional Commits, `Refs: SPEC-018`. |
| 3. Corretude | ✅ | Ver "Corretude e escolhas do dev report". Achados RV-02 a RV-04 (baixos). |
| 4. Testes | ✅ | test-report PASS, CA-01 a CA-12 cobertos, CA-13 manual pendente (Definição de pronto). Os testes de aceite exercitam o comportamento real (banco real, `httpx.MockTransport`, `uvicorn.run` espião com controle positivo, AST no CA-11 com teste de não tautologia). Sem rede externa. Nenhum teste roda a suíte inteira em subprocesso (o `test_ca16` da SPEC-009, que já existia, roda dois arquivos explícitos). Tabela da §10 conferida linha a linha (abaixo). |
| 5. Qualidade | ✅ | `ruff` limpo; type hints nas funções públicas; sem `print` nem código morto (a constante `SPEC016_CONTRACTS` sem uso em `test_spec_004.py` segue o precedente da SPEC-016 e é do tester). Sem duplicação de `qc_contracts`: a borda e a API usam `HeartbeatCreate`, `DeviceStatus`, `DEVICE_ID_PATTERN` (com `re.fullmatch`) e `MAX_HEARTBEAT_COUNT`; o dashboard usa `SOURCE_LABELS_PT` pelo `source_label`. READMEs atualizados. RV-04 (type hint). |
| 6. Segurança | ✅ | Revisão do reviewer (o portão formal é do `security-devops`, porque a SPEC tem a tag `security` e o autor é o developer). Autenticação nas duas rotas (`require_device` com `secrets.compare_digest` e `require_read_key`); chave de dispositivo na rota de leitura → 401 (CA-06). `device_id` do caminho com `Path(pattern=DEVICE_ID_PATTERN)` (o `\n` final é recusado; teste `edge-01%0A`); `extra="forbid"`; mesmo limite de corpo da SPEC-004 (413 testado). SQL só com parâmetros psycopg; leitura em transação `read only`. Corpo nunca registrado no log (CA-03 com marcadores); 403 e erro de banco logam só rota, dispositivo e SQLSTATE. Na borda, a chave é removida das mensagens de rede, redirecionamentos não são seguidos e o teto de 512 KiB e o prazo de 15 s valem também no heartbeat. Nenhuma dependência nova. Sem reaprovação delegada nesta branch. |

### R-07 (separação de papéis)

| Commit | Agent | Arquivos | Conferência |
|---|---|---|---|
| `92014ca`, `ea13d41`, `89e00be` | orchestrator | `docs/plan.md`, cabeçalho e Histórico da SPEC-018 | só status, rodada e a linha do encadeamento |
| `77768b6`, `b59de11`, `9cc84a5`, `efd470f`, `baf4f18`, `6052be4` | developer | produção, `*/tests/` fora de `acceptance/`, READMEs, `.env.example`, `uv.lock`, dev report | nenhum arquivo em `tests/acceptance/` |
| `dd3b3ef` | tester | só `*/tests/acceptance/` e o test report | nenhum arquivo de produção |
| `a8eb876` | architect | só `docs/architecture.md` | §3 (versão e schemas), §4 (rotas), §5 (colunas da `004`), §6.4 (`HEARTBEAT_INTERVAL_S`) e a linha "Arquivos vigentes" do §10 |

Todos os commits têm o trailer `Agent:` no bloco final. Não sou autor de nenhum deles.

### Ajustes em aceites de SPECs anteriores (`docs/architecture.md` §10)

Conferi o `git diff` de cada arquivo contra a tabela do test report. São exatamente os 6 arquivos da tabela, só as asserções afetadas, nenhum `test_caNN_` removido ou renomeado:

| Arquivo | Conferência |
|---|---|
| `packages/contracts/tests/acceptance/test_spec_016.py` | asserções exatas `0.4.0` → coerência com `importlib.metadata`, formato e piso `(0, 4, 0) <= v < (1, 0, 0)`; nome do `test_ca01_` mantido. Autorizado pela §3.1. |
| `api/tests/acceptance/test_spec_004.py` | par do `qc_contracts` no `ALLOWED_EXACT` → `(test_spec_018.py, "0.5.0")`, no **mesmo commit** (`dd3b3ef`) que cria `packages/contracts/tests/acceptance/test_spec_018.py`, cujo CA-01 fixa `0.5.0` exato num `test_ca01_*`. Autorizado pela §3.1. A linha "Arquivos vigentes" do §10 foi atualizada pelo architect (`a8eb876`). |
| `api/tests/acceptance/test_spec_016.py` | teste **extra** `contract_version == "0.4.0"` → piso, renomeado (permitido para `test_extra_*`); decorre da §4.1. |
| `infra/tests/acceptance/test_spec_003.py` | teste extra de colunas de `devices`: de igualdade do dicionário para as 4 colunas da SPEC-003 com tipo e nulidade iguais; decorre da §4.2. As 8 colunas novas são conferidas no aceite da SPEC-018. |
| `dashboard/tests/acceptance/test_spec_028.py` | teste extra: 6 → 7 leituras cacheadas, mantendo a checagem de `ttl` e `max_entries`; decorre da §4.5. |
| `edge/tests/acceptance/test_spec_009.py` | teste extra de HTTP real: aceita também o `POST` do heartbeat e restringe a conferência dos itens ao `POST` do lote, mantendo a chave e o `Content-Type` em todo `POST`; decorre da §4.4. O `test_ca16_` voltou a passar sem edição. |

### Corretude e escolhas do dev report

- **`HttpPublisher(device_id=...)` (decisão 1):** a SPEC fixa `send_heartbeat(heartbeat)` sem `device_id`, mas a rota precisa dele no caminho; um argumento opcional, só por nome, validado com `re.fullmatch(DEVICE_ID_PATTERN, ...)` é a forma menos invasiva e não muda as chamadas existentes. O `DEVICE_ID` já é validado pelo `EdgeSettings`, então o `ValueError` do construtor não é alcançável pela CLI. Aceito.
- **Laço próprio e segundo `HttpPublisher` (decisões 2 a 4):** o `HeartbeatLoop` implementa o `BackgroundService`, lê o outbox (`SqliteOutbox` com uma conexão `check_same_thread=False` protegida por `threading.Lock`, então a leitura de outra thread é segura), nunca grava nele e não importa `httpx` (só o protocolo `HeartbeatPublisher`). A instância separada evita compartilhar o `httpx.Client` entre threads. Depois de 401/403, `run_once` não faz mais nada e a thread termina (CA-09). `stop()` acorda a espera pelo `Event`. Aceito.
- **Desempate do `last_source` (decisão 7):** a regra da SPEC (maior `received_at`) é a primeira chave de ordenação; `inspected_at desc, inspection_id desc` só tornam determinístico o empate de um mesmo lote (`now()` da transação). Não muda nenhum resultado que a SPEC define. Aceito.
- **"Último sinal" (decisão 10):** usar `last_heartbeat_at` (e `nunca` sem heartbeat) é a única leitura coerente com o CA-12 ("sem heartbeat" → `nunca`) e com o `online`, que também depende só do heartbeat; o `last_seen_at` também muda com inspeções. Aceito.
- **Selo de simulado:** a página liga o selo `Contém dados simulados` (o mesmo `filters.show_badge()` das outras páginas, que é por página) quando algum dispositivo tem `last_source = simulated`, e a linha do dispositivo mostra `Origem = simulado`. Atende à §4.5 e ao R-06.
- **`online` no SQL** com o `now()` do banco, o mesmo relógio que grava `last_heartbeat_at`; o `sent_at` da borda não decide nada (teste com `sent_at` de janeiro de 2026). Limites 179/181 s pelo banco, como o contexto do §5 permite.
- **Precedência** 401 → 422 → 403 da SPEC-004 mantida; handlers síncronos (`def`), sem I/O bloqueante em `async`.
- **Migração `004`:** um único bloco `DO`, `add column if not exists` e cada `check` nomeado criado só se não existir (testado rodando mais duas vezes); as regexes são as do contrato (`MODEL_VERSION_PATTERN`, `SHA256_PATTERN`, `APP_VERSION_PATTERN`) e o par do modelo é nulo junto; sem `BEGIN/COMMIT`, como as anteriores.

## Pontos positivos

- Contrato mínimo e fiel à §4.1, com a skill `contrato-api` cumprida (minor, `extra="forbid"`, datas normalizadas para UTC, histórico no README, `uv.lock`).
- Testes de aceite fortes: controle positivo no CA-10, prova de não tautologia no CA-11, ponta a ponta por HTTP real em que a nuvem segura a resposta do heartbeat e as inspeções continuam sendo entregues sem duplicata.
- Relatórios claros, com os aceites antigos afetados previstos pelo dev e todos registrados pelo tester na tabela da §10.
- O architect fechou as pendências de documentação da Definição de pronto (§3, §4, §5, §6.4 e §10) antes da revisão.

## SPEC_ISSUE (se houver)

Nenhum.

## Pendências para o merge (não são achados)

- Portão `security-devops` (tag `security`): `r1-security-report.md`.
- CA-13 manual da dupla, registrado na Definição de pronto.
- Ordem de merge: esta branch só entra depois dos merges da SPEC-036 e da SPEC-016 (decisão do humano registrada no Histórico).

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
