# SPEC-043 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-043](../../docs/specs/SPEC-043-manutencao-pos-deploy.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `origin/main...b566251` |
| Test report | r1-test-report.md (PASS, com o CA-18 manual pendente) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante nem alto: 1 médio e 6 baixos. O merge ainda depende do portão de segurança da Parte A, do CI do PR e das demais condições listadas em "Antes do merge".

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | média | `docs/plan.md:177`, `:181`, `:239`, `:240` | O quadro ainda descreve um estado já superado: a SPEC-043 "em desenvolvimento" e `In Dev`; a SPEC-039 e o ADR-023 "(emenda 2, proposta)" e "**aguardando reaprovação humana**"; e o E2E-01 com a correção "aguardando reaprovação humana, SPEC_ISSUE-02". O Histórico da SPEC-039, o status do ADR-023 e o Histórico da SPEC-043 já registram as reaprovações. Quem confere o portão da R-09 pelo quadro lê uma pendência que não existe. | Atualizar as quatro linhas antes do merge. As linhas do histórico do próprio `plan.md` podem ficar. |
| RV-02 | baixa | `docs/specs/SPEC-043-manutencao-pos-deploy.md:12`, `:224`; `docs/adr/ADR-023-coolify-proxy-e-caddy-interno.md:195` | A SPEC-043 ainda chama a emenda 2 de "proposta". No ADR-023, o aceite foi gravado reescrevendo a linha da proposta, cujo "Quem pediu" continua sendo o architect. A emenda 1 tem uma linha própria de aceite. O conteúdo está certo, e a decisão está na SPEC-043, §9, item 4. | Trocar "proposta" por "aceita" na SPEC e acrescentar ao ADR uma linha de aceite, no padrão da emenda 1. |
| RV-03 | baixa | `dashboard/src/qc_dashboard/api.py:6` | O comentário ainda explica `ApiUnavailable` pelo "free tier cold start". É o mesmo motivo que levou à troca do aviso (OBS-01). O arquivo está fora da §3.1 e do CA-19, e os relatórios do autor e do tester já o registram. | Ajustar na próxima manutenção do dashboard. |
| RV-04 | baixa | `edge/src/qc_edge/cli.py:321`; `edge/README.md:33`; SPEC-043 §4.4, linha "Outro IPv4", e CA-14 | Com `EDGE_HOST` diferente de `127.0.0.1`, o console real não abre, pela regra da SPEC-025, que a §4.4 manda não mudar. O efeito da linha "Outro IPv4" só é visível pelo transporte de teste. O log continua indicando `127.0.0.1`, onde a borda não escuta, e o README novo diz que o console "só oferece esse endereço", sem dizer ali que só `127.0.0.1` abre (o `:551` diz, em outra seção). O tester mediu isso com `127.0.0.2` (OBS-01 do test-report). Não é regressão, e o caso do E2E-02 (`127.0.0.1`) funciona no socket real. | Fora desta SPEC: alinhar o log e a linha do README numa manutenção da borda. Não mexer na regra da SPEC-025. |
| RV-05 | baixa | `reviews/SPEC-043/r1-test-report.md:59` | O ensaio do CA-12 confirma a coluna estreita e a falta de rolagem no código anterior, mas não demonstra a parte positiva de "só aparece inteiro alargando a coluna". O arrasto por CDP não mudou a largura, e o `Autosize` não ajudou. A evidência dessa parte vem do E2E-01 (`reviews/SPEC-041/r1-e2e-test-report.md:135`). Aceito como PASS: o roteiro do CA não tem esse passo, e o limite está declarado. | Se quiser fechar, arrastar a coluna à mão num navegador, sem bloquear o merge. |
| RV-06 | baixa | `docs/specs/SPEC-043-manutencao-pos-deploy.md:258` | O CA-05 traz em texto literal uma conninfo com `password=` e uma URL com senha codificada, ambas fictícias. O scanner local (CA-05 da SPEC-015) ignora `docs/`, mas o GitGuardian do PR pode marcá-las: já houve falso positivo (SEC-15-08), e o branch ainda não passou por ele. Não é segredo real: o risco é o check ficar vermelho, o que impede o merge (R-09). | Se o check marcar, tratar como no SEC-15-08 ou pedir ao architect que troque os valores por marcadores. |
| RV-07 | baixa | `infra/tests/acceptance/test_spec_043.py:409` | A docstring de `test_extra_plan_has_no_real_identifiers` promete conferir IPs, mas o teste só procura UUIDs. É um teste extra, e a conferência de IPs desta rodada foi manual (seção 2 abaixo). | Corrigir a docstring ou incluir a checagem de IPv4. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Ver "Escopo" e "Correções de SPEC" abaixo. RV-01 e RV-02 são de registro |
| 2. Regras inegociáveis | ✅ | Ver "Regras inegociáveis" abaixo |
| 3. Corretude | ✅ | Ver "Corretude" abaixo. RV-04 é limite herdado da SPEC-025 |
| 4. Testes | ✅ | Ver "Testes" abaixo. RV-05 a RV-07 não bloqueiam |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos em `b566251` (323 arquivos). READMEs da borda e do dashboard atualizados. RV-03 é um comentário antigo |
| 6. Segurança | ✅ na Parte B; Parte A pendente | Parte B: `r1-security-report.md`, PASS. A Parte A é do security-devops, depois desta revisão |

### Escopo

- Conferi todos os requisitos da §4 no diff, um a um, inclusive os 9 itens da §4.5 e a tabela da §4.7. O diff não vai além da §3.1.
- **Sem diff** em `packages/contracts`, `infra/migrations/`, `infra/compose*.yaml`, `infra/Caddyfile`, `uv.lock` nem nos `pyproject.toml` (SPEC §8).
- A rastreabilidade do dev-report cobre do CA-01 ao CA-19, e cada CA automático tem teste de aceite que o exercita (tabela do test-report, conferida nos arquivos).
- As decisões do autor registradas no dev-report (`is_loopback`, `ALL_INTERFACES`, `rm .env.dbcheck` só no fim, "as mesmas opções" no simulador) ficam dentro do escopo e não introduzem requisito novo.

### Correções de SPEC (ADR-019)

| Correção | Commit do architect | Classificação no Histórico | Reaprovação | Conferência |
|---|---|---|---|---|
| SPEC_ISSUE-01 (CA-08 e CA-09) | `4944e15`, só a SPEC | Exige humano (X-7) | Humano, Histórico da SPEC e aviso do topo; registrada em `37b6f3b` | ✅ O texto novo segue a §4.2 e a §7, e a recusa continua sem conectar e sem mostrar a senha. O código e os testes seguem o texto novo |
| SPEC_ISSUE-02 (§2, §6, §7 e CA-12) | `6a1c203`, a SPEC e o `plan.md` | Exige humano (X-6) | Humano, que aceitou a rolagem horizontal; registrada em `4cc311e` | ✅ A §4.3 e o CA-11 não mudaram. O ensaio foi repetido no texto novo, e a ordem das linhas que o Histórico deixou a confirmar foi confirmada |
| DEP-03 na SPEC-039 | `abe73ae`; aceite em `1ed98eb` | Exige humano (X-2, X-3 e X-7) | Humano, Histórico da SPEC-039 e aviso do topo | ✅ Bate com a §4.7. Os outros "3 contêineres" da SPEC-039 e do plano são a contagem total dos dois recursos, e não a da rede |
| Emenda 2 do ADR-023 | `abe73ae`; aceite em `1ed98eb` | Só texto, sem mudança de decisão | Humano, status do ADR e SPEC-043 §9, item 4 | ✅ Decisão 1 e gatilho corrigidos. Sem a emenda, a repetição do CA-20 mandaria parar o `partqc-web`. Registro do aceite: RV-02 |

Nenhuma das quatro foi reaprovada pelo orquestrador sob delegação. As classificações estão certas, e nenhum `SPEC_ISSUE` "exige humano" ficou sem reaprovação registrada. A confirmação das reaprovações se apoia nos registros do repositório: não tenho acesso às mensagens do humano.

### Regras inegociáveis

- **R-01, R-12:** nenhuma dependência nem serviço novo.
- **R-02, R-14:** nenhuma mudança no caminho das imagens.
- **R-03:** busca nas linhas adicionadas sem JWT, chave privada nem URL com senha real. As sentinelas dos testes são geradas com `secrets.token_hex`. `.env.example` só ganhou o comentário da §4.5, item 8. Ver RV-06.
- **R-04:** nenhum payload muda.
- **R-05:** o CA-04, com a API real no Postgres, passa nesta revisão.
- **R-06:** o CA-11 e o CA-02 cobrem `Origem`, o selo e `source="simulated"`.
- **R-07:** conferi cada commit com os arquivos e o trailer `Agent:` (21 commits, todos com trailer). `tests/acceptance/` só muda em `551f51c` (tester). Produção só muda em `ab4be60`, `d98a115`, `3a79ba6` e `fa4f38f` (developer). Plano e `.env.example` só mudam em `0bf23bf` (security-devops). O tester não tocou em produção, e os autores não tocaram nos aceites.
- **R-11:** não se aplica.
- **R-13:** todos os commits têm a identidade do projeto e seguem Conventional Commits. No diff, **nenhum UUID**, nenhum nome de empresa e nenhum subdomínio real: os domínios são `db.example.org`, `pooler.example.org`, `api.partqc.test` e `api.test`, de teste, e `coolify.io`, `supabase.com` e `www.postgresql.org`, das fontes públicas. Os IPv4 são loopback, faixas privadas de teste, o `203.0.113.7` do intervalo de documentação, o `0.0.0.0` e o `128.0.0.1`, um valor de borda de `test_is_loopback`. Não li os `.env*` locais, então a comparação foi por padrão, e o CA-42 continua sendo a conferência final do humano.

### Corretude

- **`is_safe_conninfo`:** além dos casos de `@` e `/` dos testes, experimentei à mão, com valores fictícios, `:`, `%`, `?`, `#`, `$` e espaço na senha, e `host`, `port` e `dbname` por query. Uma senha com `@` sempre leva `@` ao host, e uma com `/` leva `@` ao `dbname` ou falha a porta. O limite que resta é o que a §7 admite (OBS-04 do test-report).
- **Ordem no `migrate.py`:** `ensure_supported_connection` vem antes da recusa nova, como pede a §4.2. `_connect` levanta antes de `psycopg.connect`, sem `__cause__`.
- **Pontos de conexão em produção:** `create_pool`, `_connect` do `migrate.py` e `register_device.py`. Os três estão cobertos. `qc_api/__init__.py` não importa nada interno, e todos os comandos documentados de `migrate.py` usam `--package qc-api`.
- **Borda:** `EDGE_HOST` é validado como IPv4 na configuração, então `is_loopback` não levanta exceção em uso real. A tabela da §4.4 está implementada nas três linhas.
- **Simulador:** a seed sai no erro tanto na falha do lote quanto na da saúde, então a frase do plano é verdadeira nos dois casos de código 5. Os ids dependem só do gerador.
- **Não se aplicam nesta SPEC:** fuso, I/O bloqueante novo em handler async e SQL novo.

### Testes

- **Execução nesta revisão, em `b566251`:** os cinco `test_spec_043.py`, `test_spec_013.py`, `test_spec_028.py`, `test_extra_timeouts` da SPEC-014 e os testes do autor `test_simulate.py`, `test_conninfo.py`, `test_config.py` e `test_migrate_malformed_url.py`, com `CI=true` e o Postgres local: **651 passed**. Coletei os 197 testes novos, a mesma contagem do test-report. Não repeti a suíte inteira: o test-report traz 10509 passed em `f3e9846`, e depois disso só mudaram documentação, relatórios e um parâmetro de teste. O CI do PR faz a suíte completa.
- **Testes reais:** o controle do tester contra `37b6f3b` mostra que os CAs de código falham no código anterior (fora o CA-04, regressão, que ficou de fora por rodar sem banco), e os mocks ficam só na fronteira (transporte do `httpx`, `psycopg.connect`, `detect_lan_ips`).
- **Ajustes em SPECs anteriores:** os 3 da tabela do test-report são exatamente os da §3.1 e os únicos no diff. Cada um muda uma asserção ou constante, sem remover teste. `test_spec_029.py` voltou a passar sem ajuste.
- **Regras do §10 da arquitetura e do checklist §4:** nenhum teste novo roda o pytest em subprocesso, nenhum usa rede externa, e as URLs com credencial são montadas em tempo de execução.
- **RNF-09:** esta SPEC não muda `qc_api.services` nem `qc_edge.decision` ou `outbox`.

## Pontos positivos

- A recusa acontece na subida da API e cobre o caminho que o primeiro deploy não tinha mostrado: o log do pool e a consulta de DNS.
- Os dois `SPEC_ISSUE` foram registrados com medição, e o controle do CA-12 foi repetido no texto novo em vez de ser assumido.
- O tester exercitou o `uvicorn` real com `getaddrinfo` vigiado, além do `TestClient`.
- O `test-report` declara com clareza o que não conseguiu demonstrar.

## Antes do merge

1. Portão de segurança da Parte A (security-devops), com `r1-security-report.md` PASS no total.
2. CI verde no PR, inclusive o scanner de segredos (RV-06).
3. Corrigir o RV-01 (recomendado): é o quadro em que o portão é conferido.
4. **Trabalho humano da §3.3, item 1:** confirmar que a senha atual do banco tem só letras e números. Sem isso, a API não sobe depois do deploy.
5. O CA-18 fica pendente no quadro até depois do merge e do deploy, como a §8 permite.

## SPEC_ISSUE (se houver)

Nenhum novo, e nenhum aberto. SPEC_ISSUE-01 e SPEC_ISSUE-02 estão resolvidos e reaprovados pelo humano. Os pontos de texto da SPEC (RV-02 e RV-04) não impedem verificar nem implementar nenhum CA.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
