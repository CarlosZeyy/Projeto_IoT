# SPEC-015 — r2 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-015](../../docs/specs/SPEC-015-deploy.md) |
| Rodada | r2 |
| Reviewer | reviewer |
| Diff revisado | `7166cd9...561ba81` (esta rodada; o diff completo da branch é `origin/main...561ba81`, com `origin/main` = `e948a06`) |
| Test report | r2-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Não há achado bloqueante nem alto. As correções de RV-01 a RV-04 (r1) estão certas e testadas, e as de SEC-15-01 a SEC-15-03 entraram no `deployment-plan.md`. Há **1 achado baixo** novo, o T-04 do tester, confirmado aqui como RV-05. O ajuste do teste de aceite da SPEC-001 segue a regra da §10. O portão de segurança desta rodada fica no `r2-security-report.md`.

## Resposta à rodada anterior (conferida)

| Achado r1 | Situação | Como conferi |
|---|---|---|
| RV-01 (média): cache do `uv` nas camadas | ✅ corrigido | `UV_CACHE_DIR=/root/.cache/uv` foi para o bloco `ENV` dos dois Dockerfiles (`api.Dockerfile:13`, `dashboard.Dockerfile:14`), apontando para o alvo do cache mount, e os comentários falsos foram reescritos. **Reproduzi** com um build do dashboard a partir de `git archive HEAD` (imagem já removida): **671 MB** (eram 1,09 GB), `/home/app` só com `.bash_logout`, `.bashrc` e `.profile`, e sem `/home/app/.cache`. Há teste do autor (`test_uv_cache_is_not_in_the_image`) e teste extra do tester nas duas imagens. O `deployment-plan.md` §2 traz os tamanhos novos. |
| RV-02 (baixa) / T-01: eco do argparse no smoke | ✅ corrigido, com o resíduo RV-05 | `NoEchoArgumentParser` no padrão do simulador: `parse_known_args` com contagem dos extras e `error()` com `redact_usage_error`. A duplicação de cerca de 20 linhas do simulador está justificada no dev-report (o smoke é carregado como script independente, §6). Os testes do autor e os 9 casos do tester geram o valor com `secrets`. Ver RV-05. |
| RV-03 (baixa) / T-02: porta comparada como texto, `except Exception` | ✅ corrigido | `_is_transaction_pooler_port` compara `int(port) == 6543`, e um `ValueError` vale como "não é 6543". O `except` ficou só com `psycopg.ProgrammingError`. Os testes cobrem `:06543`, `+6543`, `' 06543'`, `PGPORT=06543` e multi-host `006543`, todos com 0 conexões no listener. |
| RV-04 (baixa) / T-03: `.dockerignore` diferencia maiúsculas | ✅ corrigido | Os padrões obrigatórios literais da §4.11 foram mantidos e ganharam variantes com classes de caracteres. As exceções `!.env.example` e `!ml/reports/**/*.[pP][nN][gG]` vêm depois de todas as exclusões. **Reproduzi** no mesmo build: `x/.ENV.API` e `x/FOTO.JPG` ficam de fora, e `ml/reports/v0/R.PNG` e `.env.example` ficam dentro. Nenhuma exclusão proibida pela §4.11 foi usada. |

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-05 | baixa | `scripts/smoke_test.py:162` (criação do `NoEchoArgumentParser`) | **T-04 confirmado.** O parser do smoke usa o `allow_abbrev` padrão (`True`). Com `--=<valor>`, o argparse levanta `ambiguous option: --=<valor> could match --help, --api-url, --dashboard-url`. Essa mensagem não põe o valor entre aspas, então o `redact_usage_error` não o pega, e o erro acontece antes da contagem dos extras. **Reproduzi** com um valor gerado em tempo de execução: código 2 e o valor no stderr. As outras formas que testei (`--api-url-x <valor>` e as 9 do tester) saem redigidas. O `scripts/simulate.py:206` usa `allow_abbrev=False` e não tem o problema. O caso exige digitar `--=` colado ao valor, por isso a severidade é baixa. | Passar `allow_abbrev=False` na criação do parser (linha 162), como no simulador, ou redigir também a mensagem `ambiguous option`. Acrescentar o caso `--=<valor gerado>` ao `test_unknown_argument_is_never_echoed`. Pode ficar para uma manutenção. Não bloqueia o merge nem a subida (ver o `r2-security-report.md`). |

### Observações sem achado

- **Commit `0d40518` (orquestrador, `.claude/agents/security-devops.md`):** a SPEC-015 §7 deixa essa atualização com o orquestrador. O commit muda só a `description` (Render e Streamlit CC trocados por "VPS pessoal com Docker Compose e Caddy, banco no Supabase, Render como reserva e keep-alive") e a linha do Modo 2 (os arquivos do ADR-018 no lugar de `dashboard/requirements.txt`), num único arquivo com o trailer `Agent: orchestrator`. Não toca código de produção, testes nem as ferramentas e o modelo do agente, e o texto bate com o ADR-018. O README da raiz já descreve a VPS, então não há pendência de documentação nesta SPEC.
- **Ajuste do tester em `tests/acceptance/test_spec_001.py`** (commit `d73cfda`, `Agent: tester`), conferido contra `docs/architecture.md` §10:
  - o diff tem 2 linhas, só a string esperada de `AGENTS["security-devops"]`, igual à `description` do `0d40518`;
  - está na tabela "Ajustes em testes de aceite de SPECs anteriores" do `r2-test-report.md`, com o requisito que o motiva: a SPEC-015 §7 avisa que a `description` "é conferida literalmente pelo CA de agentes da SPEC-001 [...] e não deve ser mudada sem ajustar esse teste";
  - a intenção do CA-18 da SPEC-001 continua verificada (campos, `description` exata, ferramentas e hook de cada agente);
  - nenhum `test_caNN_` foi removido nem renomeado, e nenhuma outra linha do arquivo mudou.

  **Aceito.**
- **Verificação a mais no `test_ca36_*`:** o tester acrescentou, depois das asserções do CA, uma conferência marcada como exploratória (o PNG em maiúsculas dentro de `ml/reports/` continua na imagem). Fica no próprio arquivo desta SPEC, e as asserções do CA não mudaram.
- **Valores que parecem segredo nos relatórios:** os relatórios da r2 usam `<valor>` ou valores gerados em tempo de execução. O caso do `r1-test-report.md` (alerta do GitGuardian no PR #35) está analisado no `r2-security-report.md`.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | O texto da SPEC não mudou nesta rodada: os commits do orquestrador na SPEC só mudam status e rodada. As correções ficam dentro de requisitos existentes: §4.5 ("nenhuma chave é impressa"), §4.7 item 1 ("porta efetiva"), §4.10 e as exclusões extras que a §4.11 permite. Os informativos SEC-15-04 e SEC-15-05 não foram aplicados, com justificativa, como o portão recomendou ("Nenhuma nesta SPEC"). Não houve reaprovação de SPEC (nem humana nem delegada pelo ADR-019) nesta rodada. |
| 2. Regras inegociáveis | ✅ | **R-01:** nenhum serviço novo. **R-02/R-14:** o contexto de build agora também exclui fotos, outbox e pesos em maiúsculas. **R-03:** no diff da rodada, a busca de padrões de chave só acha nomes de variáveis, `<...>` e valores gerados com `secrets`. O `.env.dbcheck` temporário é coberto por `.env.*` no `.gitignore` e por `**/.env*` no `.dockerignore`. **R-04/R-05/R-06:** sem mudança. **R-07:** os 11 commits da rodada têm `Agent:`. O `security-devops` tocou só produção da SPEC, testes do autor, o plano e o próprio relatório. O `tester` tocou só `*/tests/acceptance/` e o test-report. O orquestrador tocou só status e o `.claude/agents/security-devops.md` (§7 da SPEC). **R-12:** os Dockerfiles só ganharam uma variável de cache, e o CA-35 continua passando. **R-13:** todos os commits são de `…CarlosZeyy@users.noreply.github.com`, em Conventional Commits. O diff não tem subdomínio, IP real, e-mail nem empresa. O comando do CA-42 usa `example.org`/IP de documentação só na verificação descrita, e nada disso foi versionado. |
| 3. Corretude | ✅ | A comparação numérica da porta trata as grafias de 6543 sem afetar uma porta não numérica. A redação do smoke cobre "unrecognized arguments" e os valores entre aspas, exceto o caso do RV-05. O `UV_CACHE_DIR` não muda o `HOME` do processo do usuário `app`. A ordem das exceções no `.dockerignore` está certa. |
| 4. Testes | ✅ | Test-report PASS, com os testes `docker` executados (16 do tester e 30 no total). Repeti localmente: `ruff check` e `ruff format --check` limpos (220 arquivos); `CI=true TEST_DATABASE_URL=… uv run pytest -q` → **5029 passed, 52 skipped**; `PARTQC_DOCKER_TESTS=1 PARTQC_DOCKER_BUILD_NETWORK=host … pytest -m docker -q` → **30 passed**. No PR #35, os checks `ruff + pytest` e `docker images + pytest -m docker` estão verdes (este último com a rede bridge do runner, o que a máquina local não prova). Os testes novos não são tautológicos: usam imagens reais com sentinelas em maiúsculas, um listener TCP real e o script real em subprocesso. O ajuste de teste de aceite anterior (SPEC-001) foi conferido acima. As credenciais e as chaves dos testes são montadas em tempo de execução. |
| 5. Qualidade | ✅ | Comentários corrigidos nos Dockerfiles, type hints nas funções novas (`_is_transaction_pooler_port`, `redact_usage_error`) e `except` estreito. A duplicação do `NoEchoArgumentParser` está justificada. O `deployment-plan.md` foi atualizado (tamanhos das imagens, logs do Caddy, `.env.dbcheck` e §9 com as saídas a editar e o comando do CA-42). |
| 6. Segurança | N/A aqui | Avaliado no `r2-security-report.md`. |

## Pontos positivos

- A correção do RV-01 tem um teste que falharia se a regressão voltasse (`/home/app/.cache` ausente nas duas imagens), e o tamanho do dashboard caiu cerca de 40%.
- O `.dockerignore` manteve os padrões literais exigidos pela SPEC e acrescentou as variantes sem quebrar nenhum CA.
- O comando novo do CA-42 resolve os casos de aspas, espaço, CRLF e valor vazio, e lê o IPv4 sem deixá-lo no histórico do shell. Autor e tester o executaram num repositório descartável.
- O tester procurou ativamente formas de contornar a redação do smoke e achou o T-04. Em vez de reprovar a suíte, deixou o caso documentado.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
- [x] A imagem que construí para conferir o RV-01 e o RV-04 (`partqc-reviewer-dashboard:r2`) e o contexto temporário foram removidos. Nenhum contêiner ou imagem de outro projeto foi tocado.
