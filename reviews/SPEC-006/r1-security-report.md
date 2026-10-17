# SPEC-006 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-006](../../docs/specs/SPEC-006-spc.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `main...aaf00ce` (`main` = `fbc8d03`, igual à base da branch) |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante ou alto. Há um achado médio (SEC-06-01): a resposta não tem teto de lotes, e com muitos lotes pequenos o processo da API passa de 512 MB. Ele não bloqueia esta SPEC, porque a correção depende de uma decisão de SPEC que o autor não podia tomar e porque o gatilho exige uma chave de dispositivo. Mas ele **precisa ser decidido pelo architect antes de a SPEC-013 consumir a rota em produção**. Os demais itens são informativos.

## Superfície analisada

- **Rota nova:** `GET /api/v1/metrics/spc` (`api/src/qc_api/routers/metrics.py:69-85`), no router que já tem `dependencies=[Depends(require_read_key)]` (`:24-29`).
- **Entradas externas:** o header `X-API-Key` e a query string (`source`, `object_type`, `baseline_lots`, `min_lot_size`).
- **Banco:** a consulta nova `SELECT_LOT_COUNTS` / `lot_counts` (`api/src/qc_api/repositories/inspections.py:144-155` e `:295-315`).
- **Lógica:** o serviço puro `api/src/qc_api/services/spc.py`.
- **CI:** o passo novo de cobertura em `.github/workflows/ci.yml:48-49`.
- **Inalterados:** `pyproject.toml`, `uv.lock`, `.env.example`, `infra/`, `main.py`, `auth.py`, `middleware.py`, `config.py` e `db.py`. Não há variável de ambiente nova, dependência nova nem mudança de CORS ou de RLS.

### Verificações feitas

1. **Chave de leitura.**
   - A dependência está no router e cobre a rota. A comparação é `secrets.compare_digest` (`auth.py`, já revisado na SPEC-005).
   - Conferi que a chave de dispositivo dá 401 (CA-14, com `edge-01` e `sim-01`) e que o 401 vem antes do 422 (teste exploratório do tester).
   - Uma requisição sem chave não toca o banco: não há negação de serviço anônima.

2. **Injeção de SQL.**
   - `SELECT_LOT_COUNTS` é uma constante. O `{where}` recebe só um `sql.SQL(" and ").join` de três fragmentos fixos, com placeholders nomeados (`%(unknown)s`, `%(f_source)s`, `%(f_object_type)s`).
   - Os valores entram só como parâmetros, e `source` e `object_type` passam por enum antes de chegar à consulta.
   - A transação é `repeatable read, read only`, o que dá defesa em profundidade.
   - Sonda: `object_type=screw';select 1--` dá 422 (`type: enum`), sem tocar o banco.

3. **Custo da agregação e tamanho da resposta.** Medi com a app real (`create_app` + `TestClient`), num banco temporário próprio (`partqc_sec006_probe`, criado com `infra/migrations/001_init.sql` e **apagado no fim**). Os dados tinham 1 000 000 de linhas, 5% dos lotes `simulated`, metade `screw` e metade `nut`, e 10% de defeitos. A chave de leitura foi gerada em tempo de execução. O "pico RSS" é o do processo inteiro, e a linha de base sem dados é de cerca de 63 MB.

   | Cenário (1 M linhas) | Requisição | Tempo | Corpo | Pico RSS | Pontos / excluídos |
   |---|---|---|---|---|---|
   | 2 000 lotes de 500 (volume "grande" realista) | padrão | 0,52 s | 393 KB | 67 MB | 1 900 / 0 |
   | idem | `object_type=screw` | 0,42 s | 390 KB | 67 MB | 1 900 / 0 |
   | idem | `source=simulated` | 0,07 s | 21 KB | 63 MB | 100 / 0 |
   | 200 000 lotes de 5 | padrão | 8,1 s | 34,6 MB | **405 MB** | 190 000 / 0 |
   | 1 000 000 de lotes de 1 | padrão (`min_lot_size=5`) | 19,5 s | 30,8 MB | **803 MB** | 0 / 950 000 |
   | idem | `min_lot_size=1` | 33,0 s | 159,5 MB | **1 724 MB** | 950 000 / 0 |

   - A parte do banco é pequena. No pior caso (950 000 grupos, sem paralelismo), o `EXPLAIN ANALYZE` deu **5,0 s**, com o `HashAggregate` e o `Sort` despejando em disco (48 MB e 54 MB de arquivos temporários). No cenário realista, foram 0,44 s.
   - O custo dominante é o do processo Python. Ele monta um `LotCounts`, um `SpcPoint` ou `SpcExcludedLot` e o JSON para **cada lote**. Isso dá cerca de 1,7 KB de memória e 180 B de corpo por ponto, e cerca de 0,8 KB de memória por lote excluído.
   - A rota é `def` e roda no threadpool, mas a montagem e a serialização seguram o GIL. Durante esses segundos, as outras requisições da mesma instância, inclusive a ingestão, ficam lentas.

4. **Exposição de dados e R-06.**
   - A resposta é só `SpcResponse`, com `response_model`: `lot_id`, datas, `n`, `defects`, `p`, `cl`, `ucl`, `lcl` e `out_of_control`. Não traz `device_id`, `model_sha256`, nada de `devices` nem imagens (R-02, R-14). São os mesmos dados que `/lots` já expõe ao portador da chave de leitura.
   - O `lot_id` é limitado a 40 caracteres pela `check` do banco.
   - R-06: `source` vale `live` por padrão. A consulta tem um único `source = %(f_source)s`, então nunca mistura origens, e a resposta repete a `source`. Os testes cobrem o mesmo `lot_id` nas duas origens.

5. **"Erros de banco no log" (`architecture.md` §4).**
   - A rota não registra nada.
   - Sonda: gravei direto no banco uma linha com `inspected_at = 'infinity'` num lote chamado `L-SECRETLOT`. A rota deu 500 `{"detail": "Internal server error"}`, e o log teve exatamente `unhandled database error: route=/api/v1/metrics/spc type=DataError sqlstate=-`, sem a mensagem, sem o `lot_id` e sem traceback.
   - O `ValueError` de `LotCounts.__post_init__` só traria contagens (números), e é inalcançável pela rota: `count(*) >= 1` e `count(*) filter (...) <= count(*)`.

6. **Passo novo do CI.**
   - É só um `run:` com o comando da §4.3. Não há action nova, `secrets.*` nem mudança de `permissions` (continua `contents: read`). O gatilho continua `pull_request`, e não `pull_request_target`.
   - Ele reaproveita o `TEST_DATABASE_URL` do job, que aponta para o Postgres efêmero em `trust`, sem senha. O `-m "not db"` não usa o banco.
   - O `--cov-report=term-missing` imprime só os números de linha.
   - O `pytest-cov` já estava no grupo de desenvolvimento e no `uv.lock`.

7. **Segredos (R-03).** Varri o diff atrás de URLs com credencial, JWT (`eyJ`), `password=` e chaves literais. Só aparecem o Postgres local sem senha (o mesmo do CI), a chave de teste `"r" * 32` das suítes existentes e a URL sem banco montada em tempo de execução (`secrets.token_hex`). Nada disso é segredo real.

8. **Testes da SPEC (uma execução, sem a suíte inteira).** `test_spc.py`, `test_spc_route.py`, `acceptance/test_spec_006.py` e `tests/test_ci_workflow.py`, com banco: **115 passed**.

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-06-01 | média | input / deploy (disponibilidade) | `api/src/qc_api/repositories/inspections.py:144-155` e `:295-315`; `api/src/qc_api/services/spc.py:68-96`; `api/src/qc_api/routers/metrics.py:69-85` | **Resposta e memória sem teto quando há muitos lotes (resposta ao RV-02).** A rota devolve um ponto por lote válido e um item de `excluded_lots` por lote pequeno, sem limite e sem janela de tempo. É a única rota de leitura sem teto: as outras têm `limit <= 500` (`filters.py:24`) ou `MAX_BUCKETS = 5000` (`inspections.py:44`). O volume realista está bem: 2 000 lotes dão 0,5 s, 393 KB e 67 MB. Mas o custo é linear no **número de lotes**, e o `lot_id` é livre para quem tem uma chave de dispositivo, só com a regex de 40 caracteres. Basta gravar cerca de 550 000 lotes de 1 linha (cerca de 5 500 lotes de `POST /batch` de 100, uns 175 MB no banco, dentro dos 500 MB do Supabase) para que a chamada **padrão** do dashboard passe de 800 MB de RSS. O Render free tem **512 MB e 0,1 CPU** (<https://render.com/docs/compute-plans>, consultado em 2026-10-17). O processo é morto por falta de memória, e com ele cai também a ingestão. A queda **se repete a cada visita ao dashboard** enquanto os dados existirem. Pela medição, o limite de 512 MB fica perto de 250 000 pontos ou 550 000 excluídos. Os agravantes são a 0,1 CPU do Render (os 8 a 33 s locais viram minutos) e o GIL preso durante a serialização. Os atenuantes: o gatilho exige uma chave de dispositivo (borda ou simulador da dupla), e quem tem essa chave já pode poluir os dados de outras formas; a chave de leitura só existe no servidor do dashboard; não há perda de dado, porque o outbox da SPEC-009 reenvia; e o volume do projeto é de dezenas de lotes. O `statement_timeout` do SEC-05-01 **não** resolve o problema: a parte do banco no pior caso é de só 5 s, e o custo está no processo Python. | **Não bloqueia esta SPEC.** A §4.2 não prevê teto, e criar um seria decisão fora da SPEC (o developer agiu certo). **Vai para o architect**, como manutenção da SPEC-006 ou dentro da SPEC-013, **antes de a SPEC-013 consumir a rota em produção** (e, portanto, antes do deploy da SPEC-015). Um teto de pontos, ou uma janela, sozinho não basta: o `excluded_lots` também precisa de limite. A decisão precisa definir: (a) um teto de pontos coerente com as outras rotas, por exemplo os últimos N ≤ 500 lotes válidos, ou uma janela `from`/`to` obrigatória ou com padrão; (b) um teto ou resumo de `excluded_lots`, por exemplo uma contagem mais os primeiros N; (c) como fica a base do `p̄` com o corte (os primeiros `baseline_lots` da janela ou da história toda), que toca o ADR-013 e pode pedir um ADR; (d) o comportamento ao passar do teto (422, como o `MAX_BUCKETS`, ou truncar com um indicador na resposta), o que é mudança de contrato e exige o R-04. Para limitar também o custo do banco, o corte deve ir para o SQL (`order by ... limit`), e não só para o Python. **Para a SPEC-017:** os alertas não devem recalcular a carta da história inteira a cada execução. **Para a SPEC-013:** usar cache com TTL (`st.cache_data`), como já recomendado no SEC-05-01. |
| INFO-01 | info | privacy (log) / integridade | `api/src/qc_api/repositories/inspections.py:295-315` | Uma linha gravada fora da API com `inspected_at = 'infinity'` derruba a carta inteira (500). O log sai sanitizado, conforme a §4 (conferido acima). É o mesmo caso do SEC-05-02, agora com mais uma rota afetada. | Nada nesta SPEC. A correção continua sendo a `check (isfinite(inspected_at))` da manutenção da SPEC-003, já encaminhada ao architect no SEC-05-02. |
| INFO-02 | info | privacy (R-06) | `api/src/qc_api/routers/metrics.py:69-85` | A carta nunca mistura origens, e a resposta traz a `source`. A garantia visual é da interface. | **Para a SPEC-013:** mostrar a `source` da carta em destaque e nunca sobrepor as cartas `live` e `simulated` no mesmo gráfico (R-06). |

## Resposta ao RV-02 e relação com o SEC-05-01

- **Custo da agregação no banco:** é linear nas linhas da origem (varredura sequencial com `group by lot_id`). Com 1 M linhas, levou 0,44 s em 2 000 lotes e 5,0 s em 950 000 lotes, com despejo em disco. Isso é aceitável e cabe no SEC-05-01, que continua na SPEC-015: um `statement_timeout` medido, de algo como 15 s, cobre a parte do banco desta rota.
- **Tamanho da resposta e memória da API:** é o risco real, e não é coberto pelo SEC-05-01. Vira o SEC-06-01, encaminhado ao architect.

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | ✅ `require_read_key` no router, com `compare_digest`; chave de dispositivo dá 401; 401 antes de 422; sem chave, o banco não é tocado. |
| Entradas validadas (tamanho, tipo, regex, `extra="forbid"`) | ✅ para os parâmetros: enums (`Source`, `SpcObjectType` sem `unknown`) e inteiros com `ge`/`le` (2…100 e 1…500). Não há corpo nem imagem. ⚠️ A cardinalidade da saída não tem teto (SEC-06-01, médio, não bloqueia). |
| SQL sempre parametrizado, sem f-string em query | ✅ Fragmentos `sql.SQL` fixos e placeholders nomeados; injeção em `object_type` dá 422; transação read only. |
| RLS ligado; `DATABASE_URL`/`service_role` só na API | ✅ Sem mudança de schema nem de configuração. |
| CORS fechado ou mínimo | ✅ Sem mudança (N/A). |
| Logs sem segredos e sem payloads de imagem | ✅ A rota não registra nada; erro de banco sai só com rota, classe e SQLSTATE (sonda com `infinity`); o log por requisição usa o template da rota, sem query string. |
| Dependências novas | ✅ Nenhuma (`pyproject.toml` e `uv.lock` inalterados). |
| Deploy: variáveis no provedor, health check, plano free sem cartão | N/A nesta SPEC (sem mudança de deploy). O passo novo do CI não usa segredos nem actions novas. O limite de memória do Render free (512 MB, 0,1 CPU) foi verificado em 2026-10-17 e é a base do SEC-06-01. **Pendência para a SPEC-015:** corrigir a linha do Render no `docs/deployment-plan.md`, que diz "≈ 512 MB, não confirmado", com essa fonte. |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma. O `pytest-cov` usado pelo passo novo já estava no `uv.lock`, no grupo de desenvolvimento. |

## Encaminhamentos

| Achado | Destino | Bloqueia? |
|---|---|---|
| SEC-06-01 (sem teto de lotes; memória da API) | Architect: manutenção da SPEC-006 ou SPEC-013, decidida antes de a SPEC-013 ir para produção; o ADR-013 pode precisar de revisão (base do `p̄` com janela). SPEC-017: não recalcular a história inteira. | Não |
| SEC-05-01 (`statement_timeout`) | Continua na SPEC-015; cobre a parte do banco desta rota (5 s no pior caso local). | Não |
| INFO-01 (`infinity` derruba a carta) | Architect: manutenção da SPEC-003 (`check (isfinite(inspected_at))`), como no SEC-05-02. | Não |
| INFO-02 (origem visível na carta) | SPEC-013 | Não |
| Linha do Render no `deployment-plan.md` (512 MB e 0,1 CPU confirmados) | SPEC-015 | Não |

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
- [x] O banco temporário `partqc_sec006_probe` foi apagado (só resta `partqc_test`). Nenhuma credencial literal foi usada: a chave de leitura das sondas foi gerada com `secrets.token_urlsafe(32)` em tempo de execução, e a URL do Postgres local não tem senha.
