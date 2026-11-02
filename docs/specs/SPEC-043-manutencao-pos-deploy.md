# SPEC-043: Manutenção pós-deploy (simulador em produção, senha nos erros de conexão, Histórico, aviso de API indisponível, console da borda e passo a passo do Coolify)

| Campo | Valor |
|---|---|
| Status | Blocked |
| Rodada atual | r1 |
| Autor da implementação | developer (Parte A: `scripts/`, `infra/migrate.py`, `api/`, `dashboard/`, `edge/`), depois security-devops (Parte B: `docs/deployment-plan.md` e `.env.example`), na mesma rodada |
| Tags | security, deploy |
| Depende de | Nada a esperar: SPECs 014, 015, 025, 028, 039 e 041 estão `Done` |
| Semana alvo | S4–S5, antes do CA-22 da SPEC-041 e do CA-13 da SPEC-017. Merge até o ensaio do M4 (29/11); nenhum merge na véspera nem no dia da apresentação |
| Requisitos cobertos | RF-01, RF-06, RF-11, RF-13, RF-14, RNF-06, RNF-10; R-03, R-05, R-06, R-13 |
| ADRs relevantes | ADR-023 (emenda 2 proposta, só de texto, §4.7), ADR-019, ADR-006, ADR-013 |

> **Aguardando reaprovação humana**: correção do SPEC_ISSUE-02 de `reviews/SPEC-043/r1-test-report.md`, lá numerado SPEC_ISSUE-01 (§2, §6, §7 e CA-12). Classificação ADR-019: exige humano (X-6). Ver o Histórico.
>
> **Reaprovada pelo humano em 2026-11-02**: correção do SPEC_ISSUE-01 de `reviews/SPEC-043/r1-dev-report.md` (CA-08 e CA-09). Classificação ADR-019: exige humano (X-7). Ver o Histórico.

## 1. Contexto

O primeiro deploy (2026-11-02, `docs/deployment-plan.md` §9) e o ensaio local (`reviews/SPEC-041/r1-e2e-test-report.md`, 2026-11-01) deixaram pendências sem SPEC (`docs/plan.md` §3). Esta manutenção junta só o que atrapalha o que falta fazer até a entrega. **Não muda o contrato, o banco nem uma regra negociável. Não cria migração nem ADR.** A única mudança em ADR é uma emenda de texto no ADR-023 (§4.7), declarada ao humano.

Componentes, em `docs/architecture.md`: §4 (API e erros de banco no log), §6.1 (console), §8 e §9 (operação na VPS).

| Item | Origem | Severidade | Decisão |
|---|---|---|---|
| DEP-01 | `scripts/simulate.py`, `BATCH_TIMEOUT_S = 10.0` | média | **Entra só no cliente** (§4.1): 60 s e aviso sobre repetir com a mesma seed. O servidor fica como está (§3.2) |
| DEP-02 | `infra/migrate.py:226`, `_host_port` | média, segredo | **Entra** (§4.2): a URL mal formada é recusada antes de conectar nas três entradas (`migrate.py`, `register_device.py`, API) |
| DEP-03 | CA-20 da SPEC-039 | baixa, texto | **Entra** (§4.7): corrigido pelo architect na SPEC-039 e no ADR-023, e pela Parte B no plano. **Exige humano** (ADR-019) |
| E2E-01 | `dashboard/views/historico.py` | baixa | **Entra** (§4.3): largura fixa na coluna `Modelo` |
| E2E-02 | `edge/src/qc_edge/app.py`, `console` | baixa | **Entra** (§4.4): o console só oferece o endereço em que a borda escuta |
| OBS-01 | `dashboard/src/qc_dashboard/filters.py`, `API_WAKING_TEXT` | baixa | **Entra por decisão do humano** (§4.8): na VPS a API não dorme, e "API acordando (free tier)" pode esconder uma queda real na apresentação |
| Passo a passo do deploy | Primeira publicação | baixa | **Entra** (§4.5) |
| `revoke` na migração | Passo 1, item 4, do plano | decisão | **Fica o passo manual, sem migração** (§4.6) |

**Fatos conferidos no código em 2026-11-02 (leitura, sem executar):**

- **DEP-01:** `insert_inspections` (`api/src/qc_api/db.py`) faz um `INSERT` por item, numa transação. Com os 120 ms medidos, 75 itens levam cerca de 9 s só de banco, e 100 itens, cerca de 12 s. Extrapolando os 10 a 13 s medidos com 75 itens, 100 itens levam até cerca de 17 s.
- **DEP-02, por que o trecho aparece:** a libpq termina as credenciais no primeiro `@` ou `/` da URL. Com um `@` na senha, o resto da senha vira parte do `host`. Com um `/`, o usuário vira o `host`, e o começo da senha vira a `port`, de modo que o `_host_port` também o mostraria.
- **DEP-02, API:** a suposição de `docs/deployment-plan.md` §7, item 2 ("sem a senha"), só vale para uma URL bem formada. No `psycopg` 3.3.6, a falha de resolução vira `OperationalError("failed to resolve host '<host>': ...")` (`psycopg/_conninfo_attempts.py`), e o `psycopg_pool` a registra em `WARNING` (`error connecting in %r: %s`, `psycopg_pool/pool.py`). Logo, com a mesma URL, o log da API repetiria o trecho a cada tentativa. A resolução também recebe esse nome, então o trecho pode sair numa consulta de DNS.
- **DEP-02, `register_device.py`:** não mostra a mensagem (`database error: <classe>`), mas tenta conectar e resolver esse mesmo nome. Por isso entra, com uma recusa de uma linha.
- **Borda:** `fetch_due(100)` manda até 100 itens, e o `read` de 5 s é menor que os cerca de 12 s de um lote cheio. O que os esvazia é o `2**n * U(0.8, 1.2)` por item (`publish_loop.py`), que quebra a fila em lotes menores: a tentativa que estoura o prazo já gravou tudo (R-05), e os reenvios voltam como `duplicate`. Isso explica o que foi medido em produção (filas de 45 e 100, sem perda, com retentativas) e por que a borda fica fora (§3.2, §7).

**Fontes externas, consultadas pelo architect em 2026-11-02:**

- Postgres: <https://www.postgresql.org/docs/current/sql-alterrole.html>: "Whenever the role subsequently starts a new session, the specified value becomes the session default". Isso explica o `statement_timeout` antigo nas conexões que o pooler já tinha abertas.
- Coolify: <https://coolify.io/docs/knowledge-base/environment-variables>: "New variables default to **Available during build** and **Available in the container**", e "Production and preview variables appear in separate labelled sections". A página não fala do estado inicial das variáveis detectadas no compose; a origem desse fato é a medição de 2026-11-02.
- Supabase: <https://supabase.com/docs/guides/api/securing-your-api> (privilégios padrão de tabelas novas em `public`) e <https://supabase.com/changelog/45329-breaking-change-tables-not-exposed-to-data-and-graphql-api-automatically> (a mudança chegaria aos projetos existentes em 30/10/2026). As 56 linhas de 2026-11-02 são 4 tabelas × 7 privilégios × 2 papéis, o conjunto completo, o que não combina com esse aviso. Por isso, o plano não promete um número (§4.5, item 2).

## 2. Objetivo

`scripts/simulate.py --lots 3` e `--lots 10 --lot-size 50` terminam com código 0 em produção; nenhuma ferramenta nem a API tentam conectar com uma URL de banco mal formada, nem mostram um trecho da senha; no Histórico a 1500 px, `partqc-mnv3-provisional-v1` aparece inteiro na coluna `Modelo` ao rolar a tabela na horizontal, sem alargar a coluna, mesmo com modelos misturados na página; o painel diz que a API está indisponível, sem sugerir que ela só está acordando; o console da borda só oferece o endereço em que ela escuta; e o plano de deploy descreve o que a primeira publicação mostrou.

## 3. Escopo

### 3.1 Dentro

**Parte A (developer):**

- `scripts/simulate.py` (§4.1) e `scripts/tests/test_simulate.py`, na asserção de `{10.0}` em `test_timeouts`;
- `api/src/qc_api/conninfo.py`, novo, e `api/src/qc_api/config.py` (§4.2);
- `infra/migrate.py` e `scripts/register_device.py` (§4.2);
- `dashboard/views/historico.py` e `dashboard/src/qc_dashboard/formatting.py` (§4.3);
- `dashboard/src/qc_dashboard/filters.py`, `dashboard/README.md` e, nos testes do autor, `dashboard/tests/test_pages.py` e `dashboard/tests/test_devices.py` (§4.8);
- `edge/src/qc_edge/netinfo.py`, `edge/src/qc_edge/app.py` e `edge/README.md` (§4.4);
- testes do autor em `scripts/tests/`, `api/tests/`, `infra/tests/`, `dashboard/tests/` e `edge/tests/`, fora de `acceptance/`.

**Parte B (security-devops):** `docs/deployment-plan.md` (§4.5 e §4.7) e o comentário do `.env.example` (§4.5, item 8).

**Architect, junto com esta SPEC:** `docs/specs/SPEC-039-manutencao-deploy-coolify.md` e `docs/adr/ADR-023-coolify-proxy-e-caddy-interno.md` (§4.7), as anotações de `docs/architecture.md` §4 e §6.1 e `docs/plan.md`.

**Tester:** `scripts/tests/acceptance/test_spec_043.py` (CA-01 a CA-04 e CA-10), `api/tests/acceptance/test_spec_043.py` (CA-05 a CA-07), `infra/tests/acceptance/test_spec_043.py` (CA-08, CA-09, CA-16 e CA-17), `dashboard/tests/acceptance/test_spec_043.py` (CA-11 e CA-19), `edge/tests/acceptance/test_spec_043.py` (CA-13 a CA-15), mais o ensaio do CA-12.

**Testes de aceite de SPECs anteriores** (`docs/architecture.md` §10, aplicação explícita). O tester ajusta só o que o requisito citado muda e registra na tabela do test-report:

| Arquivo | Teste | O que muda | Requisito |
|---|---|---|---|
| `scripts/tests/acceptance/test_spec_014.py` | `test_extra_timeouts` | `batch.extensions["timeout"]["read"]` passa de `10` a `60`; o `90` da saúde continua | §4.1 |
| `dashboard/tests/acceptance/test_spec_013.py` e `test_spec_028.py` | a constante `WAKING` | passa a ser o texto da §4.8; as asserções continuam | §4.8 |

Se outro teste antigo falhar por causa de um requisito desta SPEC, vale a mesma regra. Esta SPEC substitui, sem editar os arquivos, o "timeout 10 s" da SPEC-014 §4.3, item 2, e o texto do aviso na SPEC-013 (§4 e CA-13).

### 3.2 Fora

- **Menos idas ao banco em `insert_inspections` (multi-linha ou pipeline):** fora. É o caminho crítico da idempotência (R-05) a um mês da entrega, muda a forma de apurar `created` e `duplicate` e não foi testado pelo pooler em modo transaction. Só entra por SPEC nova, se o humano pedir (§9, pergunta 1).
- **Prazos da borda (`publisher.py`, 5 s e 15 s) e SEC-30-03:** sem mudança. A borda esvaziou as filas em produção (§7).
- **Migração com o `revoke`, `alter default privileges` e a opção "Automatically expose new tables":** fora (§4.6).
- **Nenhum diff em `packages/contracts`, `infra/migrations/`, `infra/compose*.yaml` e `infra/Caddyfile`.** O `dashboard` já não tem a chave `networks`; o DEP-03 é só de texto.
- **OBS-02 a OBS-05 do ensaio local:** fora. O OBS-01 entra (§4.8).
- **"Outros IPs" listando as redes do Docker com `EDGE_HOST=0.0.0.0` (E2E-02):** fora. O `edge/README.md` já avisa (SEC-07), e o endereço é real naquela máquina.
- **CAs manuais pendentes do deploy** (`KEEPALIVE_URL`, 2FA e webhook, celular, ciclo de rollback, confirmação da R-01): tarefas humanas, sem mudança de texto.
- **Outras páginas do painel:** "Dispositivos" já mostra `Modelo` inteiro.

### 3.3 Trabalho humano

1. **Antes do merge:** conferir que a senha atual do banco tem só letras e números. Se o trecho da senha apareceu em algum lugar além do terminal (chat, print, log compartilhado, relatório), trocá-la no Supabase e atualizar a `DATABASE_URL` do `partqc-api` e o `.env.migrate`.
2. **Depois do merge:** o webhook não está configurado (CA-18 da SPEC-039), então a publicação é pelo botão **Deploy**, no `partqc-api` e depois no `partqc-web`, e a borda é atualizada com `git pull` no notebook.
3. Executar o CA-18 (§5).

## 4. Requisitos detalhados

### 4.1 Simulador (DEP-01)

Em `scripts/simulate.py`:

- `BATCH_TIMEOUT_S = 60.0`, valendo para as 4 fases do `httpx`, como hoje. Cobre cerca de 3 vezes os 17 s estimados para 100 itens. O `HEALTH_TIMEOUT_S`, as 3 novas tentativas, os intervalos de 2, 4 e 8 s, o `MAX_BATCH_SIZE` e a ordem da geração não mudam.
- A mensagem do esgotamento em `_post_batch` passa a ser exatamente:

  ```python
  f"batch failed after {attempts} attempts (last: {last_error}); the API may have stored it: "
  "run again with the same seed, stored items come back as duplicate (R-05)"
  ```

  Ela só existe nesse caminho. A falha da saúde, o 401/403, o 422 e os demais códigos não mudam. O sufixo existente `(sent=… created=… duplicate=… seed=…)` continua: é ele que dá a seed.
- As opções da CLI não mudam, e a chave continua fora de toda mensagem (R-03). Repetir com a mesma seed e os mesmos tamanhos reenvia os mesmos ids, porque eles vêm só do gerador (`generate`).

### 4.2 URL de banco mal formada (DEP-02, R-03)

**`api/src/qc_api/conninfo.py`, novo, sem depender de outro módulo do `qc_api`:**

```python
MALFORMED_CONNINFO_HINT = "use only letters and digits in the password, or percent-encode it"

def is_safe_conninfo(conninfo: str) -> bool:
    """False when a piece of the password could have landed in host, port or dbname."""
```

Nunca levanta exceção. Devolve `False` se `psycopg.conninfo.conninfo_to_dict` falhar por qualquer `Exception`, ou se algum destes parâmetros, quando presente e não vazio, fugir da regra (`host`, `hostaddr` e `port` são separados por vírgula, e cada pedaço vazio é aceito):

| Parâmetro | Regra (`re.fullmatch`) | O que pega |
|---|---|---|
| `host`, `hostaddr` | `[A-Za-z0-9._:-]+` ou `/[A-Za-z0-9._/-]*` | `@` na senha (`<resto>@<host>`) |
| `port` | `[0-9]+` | `/` ou um segundo `:` na senha |
| `dbname` | sem `@`, `/` e `:` | `/` na senha, com o começo numérico |

Senha com `%40` ou `%2F` continua válida, porque a libpq a decodifica. A senha numa conninfo `chave=valor` não é examinada.

**`qc_api.config.Settings`:** um `field_validator("DATABASE_URL")` levanta `ValueError(f"malformed connection URL: {MALFORMED_CONNINFO_HINT}")` quando `is_safe_conninfo` é `False`. Com isso, a API não sobe (o `Settings()` do `lifespan` falha antes do `create_pool`), e o erro cita só o nome da variável, por causa do `hide_input_in_errors`. Uma URL válida com o banco fora do ar continua subindo, com `/health` em 503.

**`infra/migrate.py`** (agora importa de `qc_api.conninfo`; ele já roda com `--package qc-api`):

- `main`: depois do `ensure_supported_connection`, que continua antes, para a mensagem da porta 6543 não mudar, uma URL com `is_safe_conninfo` `False` dá `invalid database URL (not shown): <MALFORMED_CONNINFO_HINT>` e sai com 2, sem conectar;
- `_connect`: no início, com `False`, levanta `DatabaseConnectionError("could not connect to the database: malformed URL (not shown)")`, sem chamar `psycopg.connect`. Cobre quem importa `apply_migrations` e `pending_migrations`;
- `_host_port`: com `False`, devolve `unknown host`;
- a docstring do módulo passa a dizer que uma URL mal formada nem chega a conectar.

**`scripts/register_device.py`:** depois do `conninfo_to_dict`, a mesma mensagem e o código 2 do `main` do `migrate.py`, antes de gerar a chave.

Fora disso, as mensagens continuam: `host:port` numa falha de conexão com URL bem formada, e `database error: <classe>` no `register_device.py`.

### 4.3 Coluna `Modelo` no Histórico (E2E-01)

- `formatting.py`: `MODEL_COLUMN_WIDTH_PX = 240`, com folga para os 26 caracteres de `partqc-mnv3-provisional-v1`.
- `historico.py`: o `st.dataframe` passa a receber `column_config={"Modelo": st.column_config.TextColumn(width=formatting.MODEL_COLUMN_WIDTH_PX)}`. O Streamlit 1.65.0 do `uv.lock` aceita a largura em pixels.
- Nada mais muda: `HISTORY_COLUMNS` (ordem e nomes), o CSV, a coluna `Origem` e o selo (R-06).

### 4.4 Console com `EDGE_HOST` específico (E2E-02)

`netinfo.py`:

```python
def console_ips(edge_host: str) -> list[str]:
    """Addresses the console may offer: the LAN ones with 0.0.0.0; otherwise only edge_host."""
```

`detect_lan_ips()` só é chamada com `0.0.0.0`.

`app.py`, em `console`: `ips = netinfo.console_ips(settings.EDGE_HOST)`, ainda recalculado a cada renderização, e `ip_warning` conforme a tabela:

| `EDGE_HOST` | `ips` | Aviso | "Outros IPs" |
|---|---|---|---|
| `0.0.0.0` (padrão) | os de `detect_lan_ips()`, como hoje | `NO_LAN_WARNING_HTML` só no fallback, como hoje | como hoje |
| `127.0.0.0/8` | `[EDGE_HOST]` | `LOOPBACK_ONLY_WARNING_HTML`, nunca o `no-lan-warning` | não aparece |
| Outro IPv4 | `[EDGE_HOST]` | nenhum | não aparece |

```python
LOOPBACK_ONLY_WARNING_HTML = (
    '<p class="warning" id="loopback-warning">A borda escuta só neste notebook (EDGE_HOST em '
    "loopback): o celular não vai conseguir abrir. Para parear, use EDGE_HOST=0.0.0.0 e reinicie "
    "o qc-edge.</p>"
)
```

O QR, a URL e, com o TLS ligado, o QR de `/live` usam o `ip` escolhido, de modo que nenhum deles traz o IP da LAN. O `?ip=` continua só aceitando um valor de `ips`. A regra de quem acessa o console (SPEC-025) não muda.

`edge/README.md`, linha de `EDGE_HOST`: acrescentar que, com um valor diferente de `0.0.0.0`, o console só oferece esse endereço e que, em loopback, ele avisa que o celular não abre.

### 4.5 `docs/deployment-plan.md` e `.env.example` (Parte B)

O autor confere cada frase contra a §1 e mantém as frases que os testes das SPECs 015, 032, 038, 039 e 040 exigem. Sem subdomínio, IP nem UUID reais (R-13).

1. **Passo 1, item 3, subitem 2 (`.env.migrate`):** troca "Se a senha tiver `$`, pôr a URL entre aspas simples" por: a senha do banco tem **só letras e números**, gerada ou trocada no painel do Supabase antes de montar a URL, porque `@`, `/` e `:` quebram a URL e fazem as ferramentas recusá-la (SPEC-043). Quem trocar a senha atualiza também a `DATABASE_URL` do `partqc-api`. O §8, item 5, subitem 1, perde o "entre aspas simples se tiver `$`".
2. **Passo 1, item 4 (RLS e grants):** depois das consultas, explica que é normal a última consulta devolver linhas logo depois das migrações, porque os privilégios padrão do projeto valem para as tabelas criadas. Em 2026-11-02, foram 56 linhas, 4 tabelas × 7 privilégios × 2 papéis. A contagem pode mudar com a configuração do projeto, mas o resultado depois do `revoke` tem de ser nenhuma linha. Diz também que a migração não faz esse `revoke` (SPEC-043 §4.6) e que o passo é obrigatório em todo projeto novo. A frase usa exatamente `56 linhas` e `SPEC-043 §4.6`.
3. **Passo 5 (variáveis), parágrafo novo:**
   - o Coolify cria as variáveis do compose com **Build time** ligado e **Literal** desligado (Coolify 4.5.3, 2026-11-02): desligar o Build time em **todas**, inclusive as opcionais, e não só nos segredos. O log do deploy tem de dizer `No build-time variables`;
   - o Coolify também cria uma cópia em **Preview deployments**. O PartQC não usa preview: a cópia fica como está, e nenhum segredo é colado nela;
   - o campo mostra `Loading value...` por alguns segundos. Editar só depois de o valor aparecer;
   - dois formulários abertos se sobrescrevem: editar uma variável por vez, salvar e recarregar a lista para conferir.
4. **Passo 6 (domínio):** o Coolify 4.5.3 acrescenta sozinho `www.<subdominio>` ao domínio do `caddy` ao salvar. Conferir o campo depois de salvar. Na primeira publicação, o humano o manteve; o certificado desse nome depende de haver um registro DNS para ele. O CA-42 cobre esse nome, porque o subdomínio está contido nele.
5. **§7, item 2:** "sem a senha" passa a valer para uma URL bem formada, com a recusa da SPEC-043 descrita: a API não sobe com uma `DATABASE_URL` mal formada. **§8, item 5:** o aviso "ela pode trazer o host do pooler" ganha "e, com uma URL mal formada, um trecho da senha".
6. **§8, item 4 (simulador):** o lote agora espera até 60 s. Referência, sem ser limite: um lote cheio leva cerca de 17 s, e 500 itens, cerca de 90 s, estimados a partir dos 10 a 13 s medidos com 75 itens. Se sair com código 5, repetir com a mesma seed, que é impressa no erro (R-05). **Passo 11, item 3:** o esperado é código 0 e `sent=75`.
7. **§8, item 5 (`statement_timeout`):** a saída esperada continua `15s`, mas `2min` logo depois do `alter role` não é falha: o `alter role` só vale para conexões novas, e o pooler reaproveita as abertas (fonte do Postgres, §1). Repetir o comando, com o arquivo temporário apagado só no fim, a cada 5 min, por até 30 min. Só depois disso registrar `SPEC_ISSUE`. Registrar o tempo observado. Os 30 min são uma folga do procedimento, e não uma medição: em 2026-11-02, foram "alguns minutos". O mesmo vale para o passo 5 do CA-26 da SPEC-015, sem mudar o arquivo dela.
8. **`.env.example`:** uma linha de comentário logo acima de `DATABASE_URL=`, sem mudar a linha de exemplo: `# A senha tem só letras e números: @, / e : quebram a URL, e a API e as ferramentas a recusam (SPEC-043).`
9. **Histórico do arquivo:** uma linha `2026-…: SPEC-043, Parte B, pelo autor (security-devops): …`.

### 4.6 O `revoke` fica no passo manual (decisão)

Uma migração com o `revoke` foi avaliada e **não entra**:

- as migrações aplicadas têm checksum, então ela seria uma `007` nova, rodada à mão por um `.env.migrate`;
- `anon` e `authenticated` não existem no Postgres local nem no do CI, então ela precisaria de um bloco `do $$` que testa `pg_roles`, um caminho que os testes do projeto não exercitariam com os papéis reais;
- em produção, ela não faria nada: os grants já estão em 0 (CA-14 da SPEC-015);
- a barreira principal é o RLS sem políticas (ADR-006), e o `revoke` é uma segunda camada;
- a tabela nova de uma migração futura já tem a conferência em "Atualização", item 3, e na §8, item 5.

Revisitar se o banco de produção for recriado mais de uma vez ou se uma SPEC futura criar várias tabelas. Fica como pergunta opcional a opção do painel "Automatically expose new tables" (§9, pergunta 3), que não tira os grants existentes.

### 4.7 DEP-03: texto da rede `partqc-api-link`

Medido no Coolify 4.5.3: a rede é `internal`, com 2 contêineres (`api` e `caddy`), e o `dashboard` chega à API por `https://`, pelo proxy. É mais restrito que o previsto, e os segredos estão onde deveriam (CA-20, passos 1 a 3: PASS). O texto antigo vai além dos dois lugares que motivaram o item:

| Onde | Quem | Mudança |
|---|---|---|
| SPEC-039 §4.1, item 4; CA-20, passo 4; §7, "Quem alcança a `api`" e "Ordem dos deploys" | architect, junto com esta SPEC | `true 2`, com `api` e `caddy`. `true 3` com o `dashboard` do PartQC continua aceito, porque o código lido em 2026-10-25 previa isso, e uma atualização do Coolify pode trazê-lo. Qualquer outro contêiner é `SPEC_ISSUE` |
| ADR-023, decisão 1, e "Quando revisitar" | architect, junto com esta SPEC (emenda 2, proposta) | Sem isto, o gatilho mandaria parar o `partqc-web` e trocar a senha do banco na próxima repetição do CA-20 |
| `deployment-plan.md` §7, item 10, e §9, linha do CA-20 | Parte B | Item 10: no Coolify 4.5.3, o `dashboard` não está na rede; se entrar depois de uma atualização, é o risco aceito que o item já descreve. Linha do CA-20, coluna "O que": `true 2` (`api` e `caddy`); na coluna "Resultado", "Desvio" dá lugar a "Texto corrigido pela SPEC-043" |

### 4.8 Aviso de API indisponível no painel (OBS-01)

Em `filters.py`, `API_WAKING_TEXT` passa a se chamar `API_UNAVAILABLE_TEXT`, com o valor exato:

```python
API_UNAVAILABLE_TEXT = (
    "API indisponível: pode ser uma queda da API ou do banco. "
    "Tente de novo em ~1 min; se continuar, confira o servidor."
)
```

Só o texto muda. Continuam iguais os casos que mostram o aviso (timeout, erro de conexão e HTTP 502, 503 e 504), o botão `Tentar novamente`, a ausência de repetição automática e a mensagem de chave inválida. O "~1 min" continua cobrindo o despertar da reserva no Render. O `dashboard/README.md` passa a citar o texto novo.

**SPECs `Done`:** nenhuma precisa de ajuste. A SPEC-028 §3.2 e a SPEC-029 §3.2 só deixaram o texto fora do escopo delas, e a SPEC-015 §3.2 já prevê a troca "numa SPEC futura do dashboard". O texto da SPEC-013 fica substituído (§3.1). Nos riscos das SPECs 015 e 039, "API acordando" passa a se ler como este aviso.

## 5. Critérios de aceite

Nenhum CA usa rede externa. As senhas fictícias são montadas em tempo de execução (`reviews/checklist.md` §4), com um sentinela em cada metade (`<A>` antes do separador e `<B>` depois), geradas com `secrets.token_hex`. "Sem sentinela" quer dizer: nem `<A>` nem `<B>` na saída capturada, inclusive no traceback e no `caplog`.

### Simulador (Parte A)

- **CA-01 (DEP-01)** — *Dado* uma API falsa cujo transporte levanta `httpx.ReadTimeout` quando `request.extensions["timeout"]["read"] < 13` num lote (os 13 s medidos), *quando* rodo `--lots 3 --seed 42`, *então* o código é 0, o stdout tem `sent=75 created=75 duplicate=0`, há 1 lote com 75 itens, nenhuma pausa, as 4 chaves do timeout do lote valem `60.0`, e as do health, `90.0`.
- **CA-02 (DEP-01)** — *Dado* o mesmo transporte, com o limite em `18` (100 itens), *quando* rodo `--lots 10 --lot-size 50 --seed 42`, *então* o código é 0, `sent=500 created=500 duplicate=0`, com exatamente 5 lotes de 100 itens, todos com `source="simulated"` (R-06).
- **CA-03 (erro, R-03)** — *Dado* um transporte que sempre levanta `httpx.ReadTimeout` no lote, *quando* rodo `--lots 3 --seed 42` com `SIM_DEVICE_API_KEY` definida, *então* o código é 5, há 4 tentativas e as pausas `[2, 4, 8]`, o stderr contém `batch failed after 4 attempts (last: ReadTimeout)`, `same seed` e `seed=42`, e não contém a chave. *Dado* health com 503, ou lote com 401, *então* os códigos são 5 e 3, e o stderr **não** contém `same seed`.
- **CA-04 (R-05)** — *Dado* a API real em Postgres local (`clean_db`) e um transporte que entrega o primeiro `POST` do lote à API e então levanta `httpx.ReadTimeout` (gravou, e o cliente não soube), *quando* rodo `--lots 3 --seed 42`, *então* o código é 0, `sent=75 created=0 duplicate=75`, e o banco tem 75 linhas, 75 `inspection_id` distintos, todas `simulated`. *Quando* repito com a mesma seed, *então* `created=0 duplicate=75`, e o banco continua com 75.

### URL de banco (Parte A; R-03)

As URLs mal formadas (**M**) são: `postgresql://u:<A>@<B>@db.example.org:6543/postgres`, `postgresql://u:<A>/<B>@db.example.org:5432/postgres`, `postgresql://u:12/<B>@db.example.org:5432/postgres` e `postgresql://u:<A>@<B>:x@db.example.org:5432/postgres`.

- **CA-05 (§4.2)** — *Dado* `is_safe_conninfo`, *então*:
  - é `True` para `postgresql://u:<A>@db.example.org:6543/postgres`, `postgresql://u.ref:<A>@pooler.example.org:5432/postgres?sslmode=require`, `postgresql://u:a%40b%2Fc@db.example.org:5432/x`, `postgresql://postgres@127.0.0.1:55432/partqc_test`, `postgresql://localhost/x`, `postgresql:///x`, `postgresql://u@h1:5432,h2:5433/x_test`, `postgresql://u@[::1]:5432/x`, `host=db.example.org port=6543 user=u password=a@b dbname=x` e `host=/var/run/postgresql dbname=x`;
  - é `False` para toda **M** e para `not a conninfo password=<A>`, sem levantar exceção.
- **CA-06 (§4.2)** — *Dado* cada **M**, *quando* se cria `Settings(DATABASE_URL=<M>, READ_API_KEY="r"*32)`, *então* levanta `ValidationError`, a mensagem contém `DATABASE_URL` e não tem sentinela. *Dado* `DATABASE_URL=<M>` no ambiente, *quando* se abre `TestClient(create_app())` com um espião em `qc_api.main.create_pool`, *então* a subida falha, o espião não é chamado, e nem o log nem a exceção têm sentinela.
- **CA-07 (§4.2, regressão)** — *Dado* uma URL bem formada em porta local fechada, com a senha `<A>`, *quando* a API sobe, *então* `GET /api/v1/health` responde 503, e, depois de o `psycopg.pool` registrar ao menos um `WARNING` (espera de até 10 s), nenhum log capturado contém `<A>`.
- **CA-08 (§4.2)** — *Dado* cada uma das três **M** sem a porta 6543 em `DATABASE_URL`, *quando* o `main` de `migrate.py` roda com `--status` e sem opções, com `psycopg.connect` substituído por uma função que falha o teste, *então* o código é 2, a saída contém `invalid database URL (not shown)` e `percent-encode`, sem sentinela. *Dado* `postgresql://u:<A>@<B>@db.example.org:6543/postgres`, *quando* o `main` roda da mesma forma, *então* a recusa é a da porta 6543 (mensagem de hoje), com código 2, sem sentinela.
- **CA-09 (§4.2, DEP-02)** — *Dado* cada uma das três **M** sem a porta 6543, *quando* se chamam `apply_migrations` e `pending_migrations`, *então* levantam `DatabaseConnectionError` sem chamar `psycopg.connect`, com `__cause__` nulo e sem sentinela. *Dado* `postgresql://u:<A>@<B>@db.example.org:6543/postgres`, *quando* se chamam as mesmas funções, *então* levantam `UnsupportedConnectionError` (§7, "Ordem no `migrate.py`") sem chamar `psycopg.connect`, com `__cause__` nulo e sem sentinela. *Dado* cada uma das quatro **M**, *então* `_host_port(<M>) == "unknown host"`. *Dado* `postgresql://u:<A>@127.0.0.1:1/x`, *então* o `DatabaseConnectionError` traz `127.0.0.1:1` e `OperationalError`, sem `<A>`, como hoje.
- **CA-10 (§4.2)** — *Dado* cada **M** em `DATABASE_URL`, *quando* o `main` de `register_device.py` roda com `--device-id edge-01` e `psycopg.connect` substituído como no CA-08, *então* o código é 2, o stdout é vazio (nenhuma chave gerada ou mostrada), e o stderr contém `invalid database URL (not shown)`, sem sentinela. *Dado* uma URL bem formada em porta fechada, *então* o código é 1, com `database error: OperationalError`, sem a senha, como hoje.

### Histórico (Parte A; R-06)

- **CA-11 (E2E-01)** — *Dado* a página Histórico no `AppTest`, com uma inspeção `source=simulated` e `model_version="partqc-mnv3-provisional-v1"`, *quando* ela renderiza, *então* `json.loads(at.dataframe[0].proto.columns)["Modelo"]["width"] == 240`; as colunas de `at.dataframe[0].value` são exatamente `formatting.HISTORY_COLUMNS`; a célula `Modelo` é `partqc-mnv3-provisional-v1`, e `Origem` é `simulado`; e o selo `Contém dados simulados` aparece.
- **CA-12 (ensaio do tester, fora da suíte)** — Com o painel real em Chrome headless, a 1500 px de largura, barra lateral aberta, API local e 20 inspeções `simulated` (15 `sim-v0` nas primeiras linhas da tabela e 5 como a do CA-11), abrir `Histórico` com a origem `Simulado`, rolar na vertical até uma linha `partqc-mnv3-provisional-v1` e tirar uma captura de tela; depois, rolar até o fim à direita e tirar outra, sem alargar a coluna. Na segunda, a célula mostra `partqc-mnv3-provisional-v1` inteira, sem `…`. Na primeira, o corte pela borda da tabela é aceito, e o test-report registra o trecho visível. O test-report registra também o mesmo roteiro com o código anterior (`37b6f3b`), em que a coluna fica mais estreita que o valor e não há rolagem horizontal, de modo que o valor só aparece inteiro alargando a coluna. As capturas não entram no Git.
- **CA-19 (OBS-01)** — *Dado* as páginas Visão geral e Histórico no `AppTest`, com um transporte falso que levanta `httpx.ReadTimeout`, levanta `httpx.ConnectError` ou responde 503 (um caso de cada), *quando* renderizam, *então* `at.warning` contém exatamente o texto da §4.8, o botão `Tentar novamente` aparece, e `at.exception` é vazio. *Quando* o botão é clicado com a API já respondendo, *então* os dados aparecem, e o aviso some. *Dado* um transporte que responde 401, *então* aparece a mensagem de chave inválida, sem o aviso da §4.8. *Dado* `dashboard/src/qc_dashboard/filters.py` e `dashboard/README.md`, *então* nenhum contém `acordando` nem `free tier`.

### Console da borda (Parte A)

Com `httpx.ASGITransport` a partir de `127.0.0.1` (como nos aceites da SPEC-025) e `detect_lan_ips` espiada, devolvendo `["192.168.0.42", "10.0.0.7"]`:

- **CA-13 (E2E-02)** — *Dado* `EDGE_HOST=127.0.0.1`, *quando* `GET /` e `GET /?ip=192.168.0.42` respondem, *então* os dois dão 200; o corpo contém `id="loopback-warning"`, `EDGE_HOST=0.0.0.0` e `http://127.0.0.1:<porta>/capture?t=`; não contém `192.168.0.42`, `10.0.0.7`, `Outros IPs` nem `no-lan-warning`; e a espia não foi chamada. *Dado* o TLS ligado, como nos aceites da SPEC-019, *então* a URL de `/live` começa com `https://127.0.0.1:` e também não traz os IPs da LAN.
- **CA-14 (E2E-02)** — *Dado* `EDGE_HOST=192.168.0.99`, *quando* `GET /` responde, *então* o corpo contém `http://192.168.0.99:<porta>/capture?t=`, e não contém `loopback-warning`, `Outros IPs`, `192.168.0.42` nem `10.0.0.7`.
- **CA-15 (regressão)** — *Dado* `EDGE_HOST=0.0.0.0`, *quando* `GET /` responde, *então* a URL usa `192.168.0.42`, `Outros IPs` traz `10.0.0.7`, e não há `loopback-warning`. *Dado* a espia devolvendo `["127.0.0.1"]`, *então* há `no-lan-warning`, e não há `loopback-warning`. *Dado* o `edge/README.md`, *então* a linha de `EDGE_HOST` contém `0.0.0.0` e `loopback`.

### Documentação (Parte B)

- **CA-16 (§4.5, §4.7)** — *Dado* `docs/deployment-plan.md`, *então*:
  - o trecho de `### Passo 1` a `### Passo 2` contém `só letras e números`, `56 linhas`, `revoke` e `SPEC-043 §4.6`;
  - o trecho de `### Passo 5` a `### Passo 6` contém `Build time`, `Literal`, `Preview deployments`, `Loading value`, `No build-time variables` e `uma variável por vez`;
  - o trecho de `### Passo 6` a `### Passo 7` contém `www.<subdominio>`;
  - a §7, item 2, contém `SPEC-043`;
  - a §8, item 5, contém `conexões novas`, `2min` e `30 min`, e `30 min` vem antes do `SPEC_ISSUE` desse item;
  - a §8, item 4, contém `60 s` e `mesma seed`;
  - a §7, item 10, contém `4.5.3`;
  - a linha do `SPEC-039 CA-20` na §9 contém `true 2` e não contém `com 3 contêineres`;
  - não contém `aspas simples se tiver` nem `Se a senha tiver`;
  - as condições dos CAs das SPECs 015, 032, 038, 039 e 040 sobre o plano continuam valendo.
- **CA-17 (§4.5, item 8; R-03)** — *Dado* `.env.example`, *então* a linha imediatamente anterior a `DATABASE_URL=postgresql://<user>:<password>@<host>:6543/postgres` começa com `#` e contém `só letras e números`, e a linha de exemplo não muda.

### Manual (humano, depois do merge e do deploy pelo botão)

- **CA-18 (manual, DEP-01, R-05, R-06)** — Em produção, dentro dos limites da §8, item 4, com o `.env.prod`:
  1. `scripts/smoke_test.py`: 8 × `PASS`;
  2. `scripts/simulate.py --lots 3 --seed <n>`: código 0, `sent=75`;
  3. `scripts/simulate.py --lots 10 --lot-size 50 --seed <m>`: código 0, `sent=500`, com o tempo anotado;
  4. repetir o passo 3 com a mesma seed: código 0, `created=0 duplicate=500`;
  5. no SQL Editor, `select count(*), count(distinct inspection_id) from inspections where lot_id like 'SIM-%';`: os dois números iguais;
  6. no painel, a 1500 px, `Histórico` com a origem `Simulado`: selo visível e `sim-v0` na coluna `Modelo`;
  7. registrar no dev-report e no `deployment-plan.md` §9, sem o subdomínio, o IP nem os UUIDs.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Timeout e mensagem do simulador; tabela de `is_safe_conninfo`; validator do `Settings`; recusas do `migrate.py` e do `register_device.py`; `console_ips` e os três casos do console; texto novo do aviso em `test_pages.py` e `test_devices.py` | `scripts/tests/`, `api/tests/`, `infra/tests/`, `edge/tests/`, `dashboard/tests/` |
| Aceite (tester) | CA-01 a CA-11, CA-13 a CA-17 e CA-19. Mock só de fronteira externa: transporte do `httpx`, `psycopg.connect` nos casos recusados e `detect_lan_ips` | `<comp>/tests/acceptance/test_spec_043.py`, §3.1 |
| Aceite com banco | CA-04, com `TEST_DATABASE_URL` local. CA-07 e CA-10 usam uma porta local fechada, sem banco | idem |
| Ensaio (tester), fora da suíte | CA-12, com o controle no test-report | descrito no CA |
| Manual (humano) | CA-18 | VPS e painel |

**Nota da rodada (SPEC_ISSUE-02):** a correção não muda requisito de código nem CA automático. Na r1, o developer e o security-devops não refazem nada por causa dela, e o tester repete só o ensaio do CA-12, no texto novo.

Os CAs de texto do plano seguem o padrão dos testes das SPECs 015 e 039. O reviewer confere no diff o que não vira teste: nenhum arquivo em `packages/contracts`, `infra/migrations/`, `infra/compose*.yaml` e `infra/Caddyfile`.

## 7. Riscos e notas para o implementador

- **Margem da borda (só leitura de código, sem medição):** um lote de mais de cerca de 40 itens passa do `read` de 5 s na latência medida, e a borda depende do `U(0.8, 1.2)` para quebrar a fila. A partir de `n = 7`, a espera é sempre 60 s, sem sorteio, então um grupo de mais de 40 itens que chegue ali com o mesmo horário seria reenviado inteiro a cada minuto, sem nunca ser marcado `sent`. Pela conta do backoff, a fila já está quebrada nesse ponto, e os testes de 45 e 100 itens esvaziaram. No ensaio do M4, se `Pendentes` parar de cair por mais de 5 min com a nuvem no ar, é o gatilho da pergunta 1 da §9: registrar `SPEC_ISSUE`, sem mexer nos prazos por conta própria.
- **API sem subir:** o validator derruba a subida com uma URL mal formada. Em produção, a senha já é só de letras e números. Por isso, a ordem do §3.3 importa, e o CA-18, passo 1, confere logo depois do deploy. Se a API não subir com uma URL que deveria valer (por exemplo, um host fora da regra), é `SPEC_ISSUE`: não afrouxe o `fullmatch`.
- **Limite do `is_safe_conninfo`:** é uma heurística sobre o resultado do parser. Uma senha que forma por acaso um host e uma porta válidos, com um `dbname` limpo, não é distinguível de uma URL real. A regra de "só letras e números" do plano é a defesa principal.
- **Ordem no `migrate.py`:** `ensure_supported_connection` vem antes da nova recusa. `test_migrate_production.py` e `test_spec_015.py` usam `port=+6543` e `port=abc` e não podem mudar de resultado por causa desta SPEC, mas `port=abc` agora é recusada no `main`, com código 2, antes de conectar; `ensure_supported_connection` continua sem levantar erro para ela.
- **`qc_api.conninfo` sem dependências internas:** `infra/migrate.py` passa a importar do `qc_api`, então este módulo não importa `db`, `config` nem `errors`. O `infra/` não entra nas imagens (SPEC-039 §4.6), e a API não importa `migrate.py`.
- **Largura da coluna:** se a soma das colunas passar da tela, aparece rolagem horizontal, e o valor continua inteiro. A 1500 px, com a barra lateral aberta, é o que acontece, e a largura fixa não evita a rolagem. Medido na r1 (`reviews/SPEC-043/r1-test-report.md`): com 1 inspeção, a tabela tem 1040 px, e as outras colunas, 882 px, então sobram 158 px para os 180 px do valor. Sem rolar, a célula mostra `partqc-mnv3-provisional-` com 1 inspeção e `partqc-mnv3-provisio` com 40, como no código anterior. O ganho da largura fixa é o valor não ficar preso numa coluna estreita, sem rolagem horizontal, o que acontecia com modelos misturados. No passo 4 do CA-22 da SPEC-041, role a tabela para a direita para confirmar o nome. Não mude a ordem das colunas: o CSV e os testes dependem dela. O CA-11 lê o JSON de `proto.columns`, conferido só por leitura do Streamlit 1.65.0. Se a chave for outra, é `SPEC_ISSUE` de verificação, e a largura continua a mesma.
- **Texto do aviso do console:** continua em PT-BR, porque é interface (ADR-012). A mensagem do simulador e a da URL ficam em inglês, porque são log e CLI.
- **`EDGE_HOST` nos testes do console:** com o padrão `0.0.0.0`, o `detect_lan_ips` continua sendo chamado, como os aceites da SPEC-025 exigem (`lan_spy`).

## 8. Definição de pronto

- [ ] CA-01 a CA-11, CA-13 a CA-17 e CA-19 com teste de aceite passando, e CA-12 ensaiado, com o controle (test-report PASS)
- [ ] review-report APPROVED; security-report PASS: o portão da Parte A é do security-devops, e o da Parte B, do reviewer (autor `security-devops`)
- [ ] CI verde; `ruff` limpo
- [ ] `docs/deployment-plan.md`, `.env.example` e `edge/README.md` atualizados
- [ ] Correção da SPEC-039 e emenda 2 do ADR-023 reaprovadas pelo humano
- [ ] Reviewer confirma: sem diff em `packages/contracts`, `infra/migrations/`, `infra/compose*.yaml` e `infra/Caddyfile`
- [ ] PR aberto com os relatórios; merge conforme R-09. O CA-18 é feito depois do merge e do deploy pelo botão, fica pendente no quadro e é registrado depois

## 9. Decisões do humano

Respostas do humano de 2026-11-02, relatadas pelo orquestrador:

1. **DEP-01:** só no cliente, com 60 s, deixando o `insert_inspections` como está (§3.2 e §7).
2. **DEP-02:** a API recusa subir com uma URL mal formada.
3. **Revoke:** fica o passo manual (§4.6). Desligar "Automatically expose new tables" no Supabase continua opcional e fora do repositório.
4. **DEP-03:** correção da SPEC-039 e emenda 2 do ADR-023 aprovadas, com `true 2` como esperado e `true 3` (`dashboard` do PartQC) ainda aceito.
5. **`www.<subdominio>`:** mantido.
6. **OBS-01:** entra nesta SPEC (§4.8 e CA-19), contra a recomendação inicial do architect.

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-11-02 | SPEC criada (`Draft`). Decisões do architect: DEP-01 só no cliente; DEP-02 com recusa antes de conectar nas três entradas; `revoke` manual; DEP-03 corrigido também no ADR-023 (emenda 2), porque o gatilho dele dispararia. | Fatos do primeiro deploy e do ensaio local | Orquestrador, a pedido do humano |
| 2026-11-02 | OBS-01 incluído (§1, §2, §3.1, §3.2, §4.8, CA-19, §6 e §8), e §9 preenchida com as respostas do humano. O texto exato do aviso (§4.8) é proposta do architect. O status continua `Draft`: a aprovação e a mudança para `Ready` são registradas pelo orquestrador. | Respostas do humano de 2026-11-02, relatadas pelo orquestrador | Orquestrador, a pedido do humano |
| 2026-11-02 | Aprovada pelo humano (`Draft` → `Ready`), com as respostas da §9, e iniciada a r1. O humano aprovou incluir o OBS-01 como ajuste de uma linha e um critério de aceite; o texto exato da §4.8 foi informado a ele na sessão. | Decisão do humano na sessão | Humano |
| 2026-11-02 | Correção do SPEC_ISSUE-01 (CA-08 e CA-09), com a saída (a) do relatório; §4.2 e §7 sem mudança. **CA-08, antes:** "*Dado* cada **M** em `DATABASE_URL`, [...] a saída contém `invalid database URL (not shown)`". **Depois:** "*Dado* cada uma das três **M** sem a porta 6543 em `DATABASE_URL`, [...]", e a frase da URL com 6543 ganha "*quando* o `main` roda da mesma forma". **CA-09, antes:** "*Dado* cada **M**, [...] levantam `DatabaseConnectionError` [...], e `_host_port(<M>) == "unknown host"`". **Depois:** as três **M** sem a porta 6543 levantam `DatabaseConnectionError`; a URL com 6543 levanta `UnsupportedConnectionError`, sem chamar `psycopg.connect`, com `__cause__` nulo e sem sentinela; e `_host_port` vale `unknown host` para as quatro. **Evidência:** medição do relatório (`host='<B>@db.example.org'`, `port='6543'`, `UnsupportedConnectionError`) e leitura de `infra/migrate.py` (`ensure_supported_connection` vem antes de `_connect` nas duas funções, e a mensagem é uma constante, sem a URL). A recusa continua sem conectar e sem mostrar a senha; só a classe do erro muda nessa URL, a mesma ordem que o §4.2 e o §7 pedem. Classificação ADR-019: exige humano (X-7: o CA-08 e o CA-09 verificam a R-03). E-1 a E-5 cumpridos; X-6 não se aplica, porque nenhum caso de erro sai. | `reviews/SPEC-043/r1-dev-report.md`, SPEC_ISSUE-01: o CA-09 e a primeira frase do CA-08 contradiziam a §4.2 e a §7 para a URL com a porta 6543 | Orquestrador |
| 2026-11-02 | Correção do SPEC_ISSUE-01 (CA-08 e CA-09) reaprovada pelo humano (commit do architect 4944e15). | `reviews/SPEC-043/r1-dev-report.md` | Humano |
| 2026-11-02 | Correção do SPEC_ISSUE-02 (§2, §6, §7 e CA-12), com a saída (a) do relatório, onde ele está numerado SPEC_ISSUE-01. §4.3 e CA-11 sem mudança, com a largura de 240 px. **§2, antes:** "a coluna `Modelo` aparece inteira no Histórico a 1500 px". **Depois:** "no Histórico a 1500 px, `partqc-mnv3-provisional-v1` aparece inteiro na coluna `Modelo` ao rolar a tabela na horizontal, sem alargar a coluna, mesmo com modelos misturados na página". **CA-12, antes:** "[...] API local e uma inspeção como a do CA-11, abrir `Histórico` com a origem `Simulado` e tirar uma captura de tela: a célula mostra `partqc-mnv3-provisional-v1` inteira, sem `…`, sem alargar a coluna. O test-report registra o resultado e o mesmo roteiro com o código anterior, que mostra o corte." **Depois:** 15 `sim-v0` nas primeiras linhas e 5 como a do CA-11; a célula fica inteira depois de rolar até o fim à direita, sem alargar a coluna; o corte pela borda da tabela antes de rolar é aceito e registrado; e o código anterior (`37b6f3b`) tem a coluna mais estreita que o valor, sem rolagem horizontal. **§7:** nota de "Largura da coluna" com as medidas. **§6:** nota da rodada. **Evidência:** tabela do ensaio em `reviews/SPEC-043/r1-test-report.md`, medida em `f3e9846` e `37b6f3b`. A ordem das linhas não foi registrada lá: "nas primeiras linhas" é inferência da coluna estreita do código anterior, e o tester a confirma ao repetir o ensaio. **Consequência aceita, a confirmar pelo humano:** a 1500 px, sem rolar, a célula continua cortada, igual ao código anterior, inclusive só com modelos provisórios, o caso provável do passo 4 do CA-22 da SPEC-041. **Saídas não adotadas:** (b) estreitar outras colunas para o valor caber sem rolar, que é requisito novo (X-5), sem largura medida por coluna, com risco de cortar outro valor, como o `Lote`, e nova rodada de código e testes; (c) mudar a largura de referência, descartada porque a 1540 px o código anterior também mostra o valor inteiro com 1 inspeção. Classificação ADR-019: exige humano (X-6: o §2 e o CA-12 passam a aceitar a rolagem, o que reduz o resultado prometido, em vez de só ajustar a verificação). E-1, E-2, E-3 e E-5 cumpridos; E-4 não, porque a intenção de ver o valor sem esforço não fica inteira. X-7 não se aplica: selo e `Origem` (R-06) ficam no CA-11, que não muda. | `reviews/SPEC-043/r1-test-report.md`, SPEC_ISSUE-01 daquele relatório: a §2 e o CA-12 contradiziam o que a §4.3 produz a 1500 px, e o controle não mostrava o corte | Orquestrador |
