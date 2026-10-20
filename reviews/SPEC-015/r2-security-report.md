# SPEC-015 — r2 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-015](../../docs/specs/SPEC-015-deploy.md) |
| Rodada | r2 |
| Revisor de segurança | reviewer (o autor é o security-devops; `reviews/README.md`) |
| Diff revisado | `7166cd9...561ba81` (esta rodada), sobre a base já aprovada no `r1-security-report.md` (`origin/main...7166cd9`) |
| **Veredicto** | **PASS** |

Não há achado bloqueante nem alto. Os três achados baixos da r1 (SEC-15-01 a SEC-15-03) foram corrigidos no `deployment-plan.md`, e as correções de imagem, smoke e executor (RV-01 a RV-04) não abrem superfície nova. Há **1 achado baixo** novo, o SEC-15-07, que é a face de segurança do RV-05/T-04, e **1 informativo** sobre o alerta do GitGuardian no PR #35. **Nada desta rodada precisa ser corrigido antes da primeira subida na VPS.** O check do GitGuardian no PR precisa ser resolvido pelo humano antes do merge (R-09, "o scanner de segredos"), como explicado no SEC-15-08.

## Superfície analisada

- **Imagens:** `infra/docker/{api,dashboard}.Dockerfile` (`UV_CACHE_DIR`) e os dois `.dockerignore` (variantes em maiúsculas).
- **Smoke:** `scripts/smoke_test.py` (`NoEchoArgumentParser`, `redact_usage_error`).
- **Executor:** `infra/migrate.py` (`_is_transaction_pooler_port`, `except` estreito).
- **Plano:** `docs/deployment-plan.md` §2, §4 ("Logs"), §8 item 5 e §9 (saídas a editar e comando do CA-42).
- **Agente:** `.claude/agents/security-devops.md` (commit `0d40518`, só texto).
- **Fora desta rodada:** o compose, o Caddyfile, os workflows e o código da API e do dashboard não mudaram. A análise da r1 (superfície do Caddy, endpoint de administração em `127.0.0.1:2019`, capacidades, segredos, workflows) continua valendo.
- **Alerta externo:** o "Generic CLI Secret" do GitGuardian no PR #35.

## Resposta à rodada anterior (conferida)

| Achado r1 | Situação | Conferência |
|---|---|---|
| SEC-15-01 (baixa): saídas com subdomínio ou IP | ✅ | A §9 lista as saídas que trazem o host ou o IP: `redirect_url`, `openssl s_client` sem filtro, `printenv API_BASE_URL`, `wss://`, `dig`, o erro do `curl` do CA-40, logs do Caddy e da API e o erro de conexão da §8. Manda trocá-los antes de colar e diz o que pode ser colado como sai. A regra de logs da §4 passou a cobrir o Caddy (`identifiers` e o IP numa falha de ACME). |
| SEC-15-02 (baixa): falso "nenhuma linha" no CA-42 | ✅ | O comando novo tira aspas, espaços e `\r`, recusa valor vazio (um padrão vazio casaria tudo) e lê o IPv4 com `read -r -p`, fora do histórico do shell. Também manda rodar `git pull --ff-only` antes, para os relatórios da SPEC estarem no checkout. Autor e tester o executaram num repositório descartável com valor entre aspas, espaço e CRLF. Veja a nota no SEC-15-08 sobre o histórico. |
| SEC-15-03 (baixa): `DATABASE_URL` no `.env.prod` | ✅ | A §8, item 5, usa um `.env.dbcheck` próprio, com `chmod 600` e `rm` logo depois, e proíbe colar o erro de conexão sem edição. Conferi que o nome é coberto pelo `.gitignore` (`.env.*`) e pelos dois `.dockerignore` (`**/.env*`). |
| SEC-15-04 a SEC-15-06 (informativos) | Sem mudança, aceito | O dev-report justifica não aplicar os SEC-15-04 e SEC-15-05 nesta SPEC (headers novos precisariam de teste contra o WebSocket do Streamlit; `pids_limit` e `read_only` precisariam de medição). Continuam como candidatos para uma SPEC futura de endurecimento. |

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-15-07 | baixa | secrets (R-03) | `scripts/smoke_test.py:162` | **Resíduo do eco do argparse (RV-05 / T-04).** Com `--=<valor>`, a mensagem `ambiguous option` repete o valor no stderr, porque não o põe entre aspas e o parser usa `allow_abbrev=True`. Reproduzi com um valor gerado em tempo de execução. Só vaza se o humano digitar `--=` colado a uma chave, o que não é um erro de digitação plausível de `--api-key` (que já é redigido). O plano manda passar as chaves só pelo arquivo de ambiente (§4, passo 11). | Não bloqueia nem precisa ser corrigido antes da subida. Numa manutenção: `allow_abbrev=False` no parser do smoke, como em `scripts/simulate.py:206`, mais o caso no teste do autor. |
| SEC-15-08 | informativo | secrets (R-03), processo | `reviews/SPEC-015/r1-test-report.md:102` (commit `2429492`) | **"Generic CLI Secret" do GitGuardian no PR #35: falso positivo.** A linha é o passo de reprodução do T-01: uma opção de chave seguida de um valor literal em maiúsculas, **inventado** pelo tester para mostrar o eco do argparse (aqui escrito como `--api-key=<valor>`). Ele é falso positivo por quatro motivos: (1) o smoke **não tem** opção de chave (só `--api-url` e `--dashboard-url`); (2) o valor não é uma chave de dispositivo nem a `READ_API_KEY`, que são geradas por `register_device.py` e por `secrets.token_urlsafe(32)` e nunca passaram por relatório; (3) o valor não aparece em mais nenhum arquivo nem commit da branch (`git log -S` só acha o `2429492`); (4) os outros dois valores da mesma linha são de uma letra. A forma do texto é que dispara o detector (opção `--…-key=` seguida de um token longo), não um segredo. **Rotação:** nenhuma, porque nenhuma credencial real foi exposta. | **Remediação recomendada: marcar o incidente como falso positivo (ou "test credential") no painel do GitGuardian**, ação do humano, e depois executar de novo o check no PR, para que ele fique verde (R-09 exige o scanner de segredos verde). **Não reescrever a branch.** Reescrever o `2429492` exigiria push forçado (a R-09 diz "Nunca `--force`") e mudaria os hashes citados nos relatórios das rodadas r1 e r2 (`2429492`, `3e20108`, `7166cd9`, `cd81b83`, `0d40518` e outros), o que quebraria a rastreabilidade. Também editaria um relatório de rodada fechada, para remover algo que não é segredo. Também **não** recomendo acrescentar um `.gitguardian.yaml` com exceções, que afrouxaria o scanner para casos futuros e não está no escopo de nenhuma SPEC. Para evitar a repetição, os relatórios passam a usar `<valor>` depois de opções de chave, como os da r2 já fazem. **Nota sobre o CA-42:** o `git grep` busca só a árvore atual. Um subdomínio ou IP colado num commit e depois apagado continuaria no histórico, onde um scanner como o GitGuardian o veria. Por isso a edição **antes** de colar (SEC-15-01) é a barreira principal, e o CA-42 é a conferência final. |

### Classificação de segurança das correções desta rodada

| Mudança | Efeito de segurança | Antes da subida na VPS? |
|---|---|---|
| `UV_CACHE_DIR` (RV-01) | Nenhum risco novo. O cache fica no cache de build do BuildKit da VPS (só root/docker o acessa) e sai das imagens. Conferi que a imagem do dashboard não tem `/home/app/.cache` e que o `HOME` do usuário `app` continua `/home/app`. | Já corrigido. |
| Variantes em maiúsculas no `.dockerignore` (RV-04) | Reforça a R-02, a R-03 e a R-14. As exceções só reabrem `/.env.example` (raiz) e os PNG de `ml/reports/`. Conferi `x/.ENV.API` e `x/FOTO.JPG` fora da imagem. | Já corrigido. |
| `NoEchoArgumentParser` no smoke (RV-02) | Fecha o eco das formas comuns. Resta o SEC-15-07. | Não precisa de mais nada. |
| Porta numérica no executor (RV-03) | Fecha as grafias de 6543 e mantém a recusa antes de conectar. A mensagem continua constante, sem URL. | Já corrigido. |
| `.claude/agents/security-devops.md` (`0d40518`) | Só texto. As ferramentas e o modelo do agente não mudaram, e o hook de guarda de caminhos continua o mesmo (o CA-18 da SPEC-001 confere o frontmatter). | — |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | ✅ Sem mudança nesta rodada (ver `r1-security-report.md`). |
| Entradas validadas (corpo, tipo de imagem, regex de IDs, `extra="forbid"`) | ✅ Sem endpoint novo. A porta da conninfo agora é validada numericamente. Os erros de uso do smoke são redigidos, com a ressalva do SEC-15-07. |
| SQL sempre parametrizado | ✅ O `migrate.py` não ganhou consulta nova. |
| RLS ligado; `DATABASE_URL` e `service_role` nunca fora da API | ✅ A conferência do `statement_timeout` passou a usar um arquivo temporário próprio (SEC-15-03). A `DATABASE_URL` continua só no `infra/.env.api`, no `.env.migrate` e, temporariamente, no `.env.dbcheck`. O CA-14 (RLS e grants em produção) continua manual e pendente. |
| CORS fechado ou mínimo | ✅ Sem mudança. |
| Logs sem segredos e sem payloads de imagem | ✅ A regra de logs do plano cobre a API e o Caddy, e a §9 lista as saídas a editar. A saída do smoke não traz chave, URL nem host (CA-12). Ressalva no SEC-15-07. |
| Dependências novas: mantidas, licença compatível, sem CVE crítica | ✅ Nenhuma dependência nem imagem nova nesta rodada (as mesmas tags e digests da r1). O `uv.lock` não mudou. |
| Deploy: variáveis no provedor, health check configurado, plano free sem cartão | ✅ Sem mudança no compose, nos healthchecks nem no `render.yaml`. O check `docker images + pytest -m docker` está verde no PR #35, com a rede bridge do runner. Os CAs manuais (CA-13 a CA-19, CA-26, CA-40, CA-42, CA-43) continuam pendentes do humano. |
| Reaprovação delegada (ADR-019) em SPEC `security`/`deploy` | ✅ Nenhuma correção de SPEC nesta rodada. Os commits do orquestrador na SPEC só mudam status e rodada. |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma nesta rodada. As imagens base (`python:3.12.15-slim-trixie`, `uv:0.13.2`, `caddy:2.11.7`) continuam fixadas pelos mesmos digests da r1. |

## Pendências para o merge (R-09), do ponto de vista deste portão

- O check "GitGuardian Security Checks" do PR #35 está **vermelho** pelo falso positivo do SEC-15-08. O humano o marca no painel do GitGuardian e executa o check de novo. Sem isso, o portão R-09 não fecha.
- Os CAs manuais da Definição de pronto, em especial o CA-14, o CA-18 e o CA-42, que fecham itens deste portão. Ao colar as saídas, seguir a §9 do plano (SEC-15-01).

## Declaração

- [x] Não editei código; não sou autor desta SPEC.
- [x] Neste relatório, nenhum valor que pareça segredo aparece depois de uma opção de chave: uso `<valor>`.
- [x] A única imagem que construí nesta rodada (`partqc-reviewer-dashboard:r2`, compartilhada com a revisão de código) foi removida. Nenhum contêiner ou imagem de outro projeto foi tocado.
