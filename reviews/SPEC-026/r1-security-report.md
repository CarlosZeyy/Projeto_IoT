# SPEC-026 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-026](../../docs/specs/SPEC-026-spc-teto-de-lotes.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `main...0db4d30` |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante, alto ou médio. Há um achado baixo (SEC-26-01, a decisão sobre o RV-02) e dois informativos (SEC-26-02 e SEC-26-03), todos com destino fora desta SPEC.

**O SEC-06-01 da SPEC-006 está fechado por esta SPEC.** O risco medido era a memória do processo da API (803 MB e 1 724 MB de RSS no pior caso, acima dos 512 MB do Render free) e o tamanho da resposta, sem teto. Agora o corte é feito no SQL. Chegam ao Python no máximo `baseline_lots + max_points + MAX_EXCLUDED_LOTS + 1` linhas, ou seja, 100 + 500 + 50 + 1 = 651 linhas com os maiores valores que a rota aceita. Pela medição do test-report (1 M de linhas por cenário), o pico de RSS ficou entre 62,8 e 64,8 MB, qualquer que seja o volume (cerca de 62,5 MB antes da chamada), e o corpo máximo foi de 102 KB (`max_points=500`). Usei esses números sem repetir a medição. Eles batem com a forma da consulta e com a contagem de linhas que o teste do autor confere, e não vi motivo para duvidar deles. Os itens (a) a (d) da correção pedida no SEC-06-01 foram atendidos pelo ADR-017 e por esta SPEC:

- (a) teto de pontos de 2 a 500, com padrão 100;
- (b) teto de 50 excluídos, com os totais na resposta;
- (c) base de `p̄` na história inteira (o ADR-013 não muda);
- (d) truncar com indicador, com o contrato 0.3.0 seguindo o R-04.

Os resíduos não são mais o SEC-06-01:

- o tempo do banco, que continua linear e fica para o `statement_timeout` da SPEC-015 (SEC-26-03);
- a disciplina dos chamadores futuros de `lot_selection` (SEC-26-01, SPEC-017);
- o cache com TTL no dashboard (SPEC-013, como já recomendado).

## Superfície analisada

- **Rota** `GET /api/v1/metrics/spc` (`api/src/qc_api/routers/metrics.py`): parâmetro novo `max_points` (`Query(ge=2, le=500)`, padrão 100). A autenticação continua no nível do router (`dependencies=[Depends(require_read_key)]`), que também é a ordem testada no CA-13 (401 antes de 422).
- **Repositório** `lot_selection` / `SELECT_LOT_SELECTION` (`api/src/qc_api/repositories/inspections.py:146-203`, `:343-411`): consulta nova com CTE `materialized` e quatro partes com `order by ... limit`.
- **Serviço** `qc_api.services.spc`: `LotCounts` mais estrito (RV-03 da SPEC-006), `validate_selection_parameters`, `select_lots` e `build_p_chart`. O serviço continua puro: sem I/O, sem relógio e sem logging.
- **Contrato** `qc_contracts.SpcResponse` 0.3.0: 3 campos opcionais, numéricos e com padrão `None`.
- **Segredos, dependências e deploy:** nenhuma variável nova, nenhuma dependência nova (o `uv.lock` muda só a versão do `qc-contracts`, em 1 linha) e nenhum arquivo de deploy tocado.

## Verificações feitas

1. **Injeção de SQL na consulta nova.**
   - Todos os valores entram como parâmetros nomeados do psycopg: `%(f_source)s`, `%(f_object_type)s`, `%(unknown)s`, `%(min_lot_size)s` (5 vezes) e `%(baseline_lots)s`, `%(max_points)s` e `%(max_excluded)s`, os três em `limit`.
   - O único ponto de composição é `sql.SQL(SELECT_LOT_SELECTION).format(where=...)`, e o `where` é um `sql.SQL(" and ").join(...)` de fragmentos `sql.SQL` constantes. Não há f-string, `%` nem concatenação com dado externo.
   - `source` e `object_type` passam por enums do FastAPI antes de chegar ao repositório.
   - Sonda num banco temporário: `source=live' or 1=1--` → 422.
2. **Validação dos tetos antes do banco.**
   - Na rota, `max_points` vai de 2 a 500, com 422 fora da faixa. O test-report cobre `0`, `-1`, `501`, `2.5`, `1e2`, `NaN`, `inf`, dígitos não ASCII e um inteiro de 20 dígitos.
   - `max_excluded` é a constante `MAX_EXCLUDED_LOTS = 50`, não um parâmetro.
   - `lot_selection` chama `validate_selection_parameters` antes de abrir a transação, então um teto negativo nunca chega ao Postgres como `DataError`.
   - A coerção leniente (`+5`, `05`, `10.0`) já foi analisada pelo reviewer. O valor final fica sempre entre 2 e 500, então não há impacto de segurança.
3. **Tamanho da resposta.** O corpo é limitado por construção:
   - no máximo 500 pontos e 50 excluídos;
   - `lot_id` com até 40 caracteres ASCII, pelo `check` do banco;
   - campos numéricos de tamanho fixo.

   O máximo medido foi de 101,7 KB, comparável ao das rotas paginadas (`limit <= 500`). Na sonda deste relatório, 300 000 lotes excluídos geraram um corpo de 1 587 B, com 50 excluídos e `excluded_lots_total = 300000`.
4. **Chave de leitura.** Não mudou. A rota só aceita a `READ_API_KEY`, comparada em tempo constante (`auth.py`). Uma chave de dispositivo com `max_points=501` dá 401, e não 422 (extra do tester). Os campos novos (`valid_lots_total`, `excluded_lots_total`) só expõem contagens de lotes, que quem tem a chave de leitura já obtém por `/api/v1/lots`.
5. **R-06.**
   - O filtro `source = %(f_source)s` fica dentro da CTE, antes de qualquer corte e antes dos totais. Uma resposta nunca mistura origens, e os totais contam só a origem pedida.
   - O padrão continua `live`, e `source` só é copiado para a resposta.
   - O CA-16 cobre os dois sentidos: nenhum `S-*` em `live` e só `S-*` em `simulated`, com totais próprios.
6. **Custo restante e o `statement_timeout`** (sonda num banco temporário, apagado no fim):
   - **Cenário:** banco `partqc_sec026_probe_test`, criado com `infra/migrations/001_init.sql`, com 300 000 lotes `live` de 1 inspeção. A chave de leitura foi gerada em tempo de execução, e a URL local não tem senha.
   - **Sem timeout:** 200 em 1,5 s.
   - **Com `statement_timeout` de 50 ms na conexão:** **503** `{"detail": "Database unavailable"}` em 0,11 s, sem stack trace e sem a mensagem do Postgres. O log registra só a linha de acesso (`GET /api/v1/metrics/spc 503 device_id=-`).
   - **Causa:** o `QueryCanceled` (SQLSTATE `57014`) é subclasse de `psycopg.OperationalError`, e o `db_connection` o converte em `DatabaseUnavailableError` (ver SEC-26-02).
   - **Limpeza:** no fim, só resta o `partqc_test`.
7. **Logs.** O diff não acrescenta nenhuma chamada de log. O serviço continua sem `logging` (CA-15 da SPEC-006 e extra do tester).
8. **Segredos nos testes.**
   - A busca no diff por conninfo com senha, chaves literais em header, `eyJ` e `sk_` não achou nada.
   - A única senha é a fictícia de `no_db_url()`, gerada em tempo de execução (`"pw" + secrets.token_hex(4)`, montada por `urlunsplit`) e usada contra uma porta fechada.
   - As chaves de leitura dos testes vêm das fixtures existentes.
9. **R-07 e R-13.**
   - Cada commit tem o trailer `Agent:` coerente com os arquivos que toca: `developer` no código e nos testes do autor, `tester` em `acceptance/` e no test-report, `reviewer` no review-report e `orchestrator` nos status.
   - A identidade é sempre `Carlos Moises <179777237+CarlosZeyy@users.noreply.github.com>`, e nenhuma empresa é citada.

## Achados

| ID | Severidade | Categoria (auth, input, secrets, deps, deploy, privacy) | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-26-01 | baixa | input (disponibilidade) | `api/src/qc_api/repositories/inspections.py:343-363` | **Decisão sobre o RV-02 do review.** `lot_selection` aceita `max_points=None` e `max_excluded=None`, que no SQL viram `limit null`, ou seja, sem teto. Hoje nenhum caminho de produção chega a isso: o único chamador é a rota, que sempre passa `max_points` entre 2 e 500 e `max_excluded = MAX_EXCLUDED_LOTS`. O `None` existe para manter o repositório igual à referência pura `select_lots`, e o teste de equivalência do tester (`None/None`) depende dele. O risco é de um chamador futuro: um `None` em `max_excluded` reabriria o SEC-06-01 nessa parte, porque 1 M de lotes pequenos viraria 1 M de `LotCounts` em Python. | **Não bloqueia, e não pede mudança de código nesta SPEC:** só uma nota na SPEC-017. Quando a SPEC-017 (`Draft`) for revisada, o **architect** registra que ela chama `lot_selection` com inteiros nos dois tetos (`max_points` pequeno e `max_excluded=0`, ou `MAX_EXCLUDED_LOTS`), **nunca** com `None`. Também acrescenta um CA estático que confira isso na chamada do serviço de alertas. Se outro chamador de `lot_selection` aparecer, a regra vale para ele. Opcional, numa manutenção futura da API: dizer na docstring de `lot_selection` que `None` só serve para testes e para a referência. |
| SEC-26-02 | info | deploy (documentação) | `docs/specs/SPEC-015-deploy.md:150` (§4.9, item 1, "Efeito aceito") | A SPEC-015 diz que uma consulta cancelada pelo `statement_timeout` (`57014`, `QueryCanceled`) "responde o 500 genérico". Na verdade, ela responde **503** `{"detail": "Database unavailable"}`, porque o `QueryCanceled` é subclasse de `psycopg.OperationalError` e o `db_connection` (`api/src/qc_api/db.py`) o converte em `DatabaseUnavailableError`. Medi isso pela rota SPC num banco temporário. O comportamento é seguro: não vaza a mensagem do Postgres nem o stack trace. Mas o texto do risco aceito e o futuro `deployment-plan.md` vão descrever um código diferente do real, e o dashboard vai mostrar "banco indisponível" para uma leitura que só passou do tempo. Não é causado por esta SPEC. | **Não bloqueia.** Vai para o **architect**: corrigir a frase da §4.9, item 1, da SPEC-015 (e o "Riscos aceitos" da §4.8, se ele repetir o 500) para "503 `Database unavailable`, igual a um banco fora do ar", mantendo o código `57014` no texto, porque o CA-27 da SPEC-015 confere esse trecho (`SPEC-015-deploy.md:194`). Isso deve ser feito antes de a SPEC-015 entrar em `In Dev`. Para a **SPEC-013**: tratar o 503 da carta como "dados indisponíveis no momento" e não repetir a chamada em laço (o cache com TTL já ajuda). |
| SEC-26-03 | info | deploy (disponibilidade) | `api/src/qc_api/repositories/inspections.py:146-203`; `api/src/qc_api/db.py` (`POOL_MAX_SIZE = 5`) | **O que o `statement_timeout` da SPEC-015 ainda precisa cobrir.** Depois do corte, o custo da rota fica só no banco e continua linear no número de linhas da origem. A agregação por `lot_id` roda uma vez, e as três ordenações com `limit` são top-N. O tester mediu, no Postgres local, 0,53 s com 2 000 lotes, 2,9 s com 200 000 e 4,2 a 5,3 s com 1 M de lotes de 1 linha, o mesmo patamar da agregação antiga (5,0 s). No Supabase free, a CPU compartilhada deve deixar esse tempo maior. O volume é limitado pela cota de 500 MB do banco, que comporta cerca de 1 M de linhas (estimativa do SEC-06-01). Durante esse tempo, a chamada segura 1 das 5 conexões do pool. Algumas chamadas simultâneas da carta podem ocupar o pool, e a ingestão da borda passa a receber 503 (o outbox da SPEC-009 reenvia, sem perda de dado). É o cenário do SEC-05-01, agora sem o risco de memória. | **Não bloqueia.** Já está no escopo da **SPEC-015** (§4.9, item 1, e CA-26), que **eu** implemento no modo autor. Na execução: (1) o `EXPLAIN ANALYZE` da carta no CA-26 deve usar a consulta nova (`SELECT_LOT_SELECTION`, com os parâmetros padrão da rota) e não a antiga; (2) como a medição em produção é feita com poucos lotes (`simulate.py --lots 3`), o valor deve ficar no padrão de `15s` da regra, e não em 3 vezes uma leitura de milissegundos, para não cortar a carta de uma história realista; (3) o `deployment-plan.md` registra que o `statement_timeout` é o teto do custo de banco da carta, e que a memória da API já é limitada pelo ADR-017. Para a **SPEC-013**: manter o cache com TTL da carta, para que a visita ao dashboard não dispare uma consulta por renderização. |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | ✅ A rota continua sob `require_read_key` no nível do router, sem mudança. A comparação usa `secrets.compare_digest` sobre bytes (`auth.py:60`, sem mudança). O CA-13 e um extra do tester confirmam o 401 antes do 422, inclusive com chave de dispositivo. |
| Entradas validadas (tamanho, tipo, regex, `extra="forbid"`) | ✅ `max_points` entre 2 e 500 (`Query(ge, le)`); `max_excluded` é uma constante; os outros parâmetros não mudaram; os tetos são validados no repositório antes da consulta. Não há corpo de requisição nem imagem. A cardinalidade da saída agora é limitada: **fecha o ⚠️ do SEC-06-01**. `LotCounts` recusa `bool`, `float`, `str` e datas sem fuso (RV-03 da SPEC-006). Do lado da resposta, o contrato usa `extra="ignore"` (leitor 0.2.0 compatível), como o R-04 e a skill `contrato-api` preveem. |
| SQL sempre parametrizado, sem f-string | ✅ Ver a verificação 1. Os tetos entram em `limit %(...)s`, e a composição é só com `psycopg.sql`. A sonda com `source` em forma de injeção dá 422. |
| RLS ligado; `DATABASE_URL` e `service_role` só na API | ✅ Sem mudança: nenhuma migração nova, e o RLS da `001` continua. Nenhum uso de `DATABASE_URL` fora da API. |
| CORS fechado ou mínimo | ✅ Sem mudança (a API não tem CORS). |
| Logs sem segredos nem payloads de imagem | ✅ Nenhum log novo, e o serviço continua sem `logging`. A resposta 503 de uma consulta cancelada não traz a mensagem do Postgres, e o log mostra só a linha de acesso (sonda). |
| Dependências novas: mantidas, licença, CVE | ✅ N/A: nenhuma dependência nova. O `uv.lock` muda só a versão do pacote local `qc-contracts` (`0.2.0 -> 0.3.0`). |
| Deploy: variáveis no provedor, health check, free sem cartão | ✅ N/A nesta SPEC: nenhum arquivo de deploy, nenhuma variável nova e o `.env.example` sem mudança. As pendências de operação ligadas à carta ficam na SPEC-015 (SEC-26-02 e SEC-26-03). |
| Privacidade das imagens (R-02, R-14) | ✅ N/A: a rota só devolve agregados por lote (`lot_id`, `n`, taxas e totais). Nenhuma imagem nem caminho de arquivo. |
| Segredos (R-03) | ✅ Nenhum segredo no diff. A senha fictícia de teste é gerada em tempo de execução, e nenhuma credencial aparece como literal em URL, conninfo ou header. |
| R-06 | ✅ O filtro de origem fica dentro da CTE, antes do corte e dos totais; o padrão é `live`; o CA-16 cobre os dois sentidos. |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma. Só a versão do pacote local `qc-contracts` muda (0.3.0). |

## Encaminhamentos

| Achado | Destino | Bloqueia esta SPEC? |
|---|---|---|
| SEC-06-01 (SPEC-006) | **Fechado** por esta SPEC (memória e corpo limitados, medidos pelo tester). Resíduos: SEC-26-01 a SEC-26-03. | — |
| SEC-26-01 (RV-02: `None` nos tetos de `lot_selection`) | Architect, ao revisar a SPEC-017 (`Draft`): tetos inteiros, nunca `None`, com um CA estático. Sem mudança de código agora. | Não |
| SEC-26-02 (timeout dá 503, e não 500) | Architect: corrigir o texto da SPEC-015 §4.9, item 1 (e a §4.8, se for o caso), antes de ela entrar em `In Dev`. SPEC-013: tratar o 503 da carta sem repetir em laço. | Não |
| SEC-26-03 (custo de banco linear; pool de 5) | SPEC-015 (security-devops, modo autor): CA-26 com a consulta nova, valor no padrão de `15s` e registro no `deployment-plan.md`. SPEC-013: cache com TTL. | Não |

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs. Só escrevi este relatório. A sonda rodou de um script no scratchpad, fora do repositório.
- [x] Não sou autor de nenhum commit desta SPEC (o autor é o `developer`).
- [x] O banco temporário da sonda (`partqc_sec026_probe_test`) foi apagado. Só resta o `partqc_test`.
- [x] Nenhuma credencial ou chave fictícia como literal em URL, conninfo ou header: a chave de leitura da sonda foi gerada em tempo de execução, e a URL local não tem senha.
