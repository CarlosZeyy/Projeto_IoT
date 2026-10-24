# SPEC-032 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-032](../../docs/specs/SPEC-032-manutencao-deploy.md) |
| Rodada | r1 |
| Revisor de segurança | reviewer (o autor é o security-devops, `reviews/README.md`) |
| Diff revisado | `origin/main...f842019` (base de merge `63b79af`) |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante, alto ou médio. Os três achados abaixo são baixos e não bloqueiam. Dois deles confirmam o RV-01 e o RV-02 do review-report do ponto de vista de segurança. O terceiro é uma lacuna de escopo do `.gitignore` em relação ao SEC-36-02. Não há `SPEC_ISSUE`.

## Superfície analisada

- **Rotas e autenticação:** nenhuma rota, dependência de autenticação, consulta SQL ou política RLS mudou. A API e o dashboard não têm código de produção alterado.
- **Entrada externa:** a linha de comando do `scripts/smoke_test.py`, que agora usa `allow_abbrev=False` (§4.1).
- **Segredos e privacidade:** o `.gitignore` (§4.2), o `.env.example` (3 variáveis de limite, sem valor sensível), o `docs/deployment-plan.md` e os relatórios da rodada.
- **Configuração de deploy:** os headers do `infra/Caddyfile` (§4.3) e as opções `read_only`, `tmpfs` e `pids_limit` do `infra/compose.yaml` (§4.4).
- **Dependências:** nenhuma. O `uv.lock` e os `pyproject.toml` não mudaram.

### O que conferi, além da leitura do diff

Todas as verificações foram locais, sem banco de teste (`TEST_DATABASE_URL` e `CI` fora do ambiente), sem VPS e sem rede externa.

1. **Smoke sem eco (§4.1, R-03).** Rodei o script com um marcador aleatório nas formas `-h<m>`, `-<m>`, `--<m>=1`, `-- --=<m>`, `@<m>` e `--api-url` sem valor ou repetido. Todas terminaram com código 2 (ou 0, no caso do `-h`, que só imprime a ajuda), e o marcador não apareceu na saída em nenhuma delas. As mensagens citam só a contagem (`N value(s) (not shown)`) ou o nome da opção (`invalid --api-url (not shown)`). Os 12 casos extras do tester e os 4 do autor cobrem o resto.
2. **`.gitignore` (§4.2, R-02, R-03, R-14, SEC-36-02).** Usei `git -c core.excludesFile=/dev/null -c core.ignorecase=false check-ignore --no-index`. `entrada/IMG_1.JPG`, `entrada/IMG_1.HEIC`, `.ENV.example`, `infra/.env.api` e `.env.migrate` ficam ignorados, e `.env.example` não. `ls-files -ci --exclude-standard` sai vazio: nenhum arquivo rastreado casa as regras. As lacunas fora da §4.2 estão no SEC-32-02.
3. **Headers do Caddy (§4.3).** Reproduzi o T-01/RV-01 por conta própria, com a imagem `caddy:2.11.7` fixada (por digest), `--network none`, `--read-only`, `PUBLIC_HOST=http://partqc.example.org`, as origens inexistentes e uma requisição HTTP crua por `nc`. Com o `Caddyfile` da `origin/main`, o 502 de `/api/v1/health` e de `/` sai com `Server: Caddy`, `Strict-Transport-Security` e `X-Content-Type-Options`. Com o desta branch, sai só com `Server: Caddy`, `Date` e `Content-Length: 0`. Os contêineres de sonda foram parados (`--rm`), e nenhum ficou.
4. **Contêineres (§4.4).** No compose, os três serviços mantêm `cap_drop: ALL`, `no-new-privileges:true` e os limites de memória e CPU da SPEC-015, e ganham `read_only: true`, `tmpfs` só em `/tmp:size=64m` e `pids_limit` interpolado. O dev-report e o tester conferiram o efeito real: raiz `ro`, `/tmp` com `nosuid,nodev,noexec`, `pids.max=256`, `/home/app` e `/app` não graváveis, e só `caddy_data` e `caddy_config` graváveis no Caddy.
5. **Segredos, R-01 e R-13.** Busquei no diff inteiro por `password`, `secret`, `token`, `api_key`, URLs `postgres://`, JWT (`eyJ`), chaves privadas, prefixos de token conhecidos, IPv4 e hosts que não fossem `example.org` ou páginas de documentação. Encontrei só chaves geradas com `secrets.token_*` em tempo de execução e o marcador `<user>:<password>`, que já existia na `main` (SPEC-015). Os 12 commits têm autor e committer `Carlos Moises <179777237+CarlosZeyy@users.noreply.github.com>`. Nenhuma empresa, ferramenta ou e-mail corporativo é citado. Nenhum serviço novo foi adicionado (R-01).
6. **Separação de papéis (R-07).** O security-devops tocou só em produção, em `infra/tests/` fora de `acceptance/`, no plano e no dev-report. O tester tocou só em `infra/tests/acceptance/test_spec_032.py` e no test-report. O orquestrador tocou só no status, no Histórico e no `docs/plan.md`.
7. **Testes e lint.** `uv run pytest -q infra/tests` sem banco: 395 passed, 338 skipped (só testes `db`). `uv run ruff check .` limpo. Os testes `docker` (47 passed) foram rodados pelo tester e pelo reviewer da rodada, e não os repeti além das sondas do item 3.

## Achados

| ID | Severidade | Categoria (auth, input, secrets, deps, deploy, privacy) | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-32-01 | baixa (risco aceito; = RV-01/T-01/O-01) | deploy | `infra/Caddyfile:11-18`; `docs/deployment-plan.md:317` (risco 9) | O `-Server` torna o bloco `header` inteiro adiado. O caminho de erro do próprio Caddy não passa pelo `ResponseWriter` adiado. Por isso, o 502 que o Caddy devolve quando a API ou o dashboard estão fora do ar perdeu o `Strict-Transport-Security` e o `nosniff`, que saíam antes (reproduzido no item 3). Também sai sem `Referrer-Policy` e sem `frame-ancestors`, e continua com `Server: Caddy`. O 308 da porta 80 já saía sem os headers antes, e HSTS em HTTP é ignorado pelo navegador. **Impacto real desprezível:** o 502 tem corpo vazio, então não há conteúdo para farejar (`nosniff`) nem para emoldurar (`frame-ancestors`), e não há URL de origem para vazar (`Referrer-Policy`). O HSTS de 1 ano é aprendido na primeira resposta HTTPS normal, que tem o header (CA-09, passo 2). Só um navegador que nunca recebeu uma resposta normal perde o HSTS, e esse caso já não tinha proteção antes da primeira visita. O nome do software já era descobrível por outros sinais (`Alt-Svc` do HTTP/3, comportamento do TLS). | Nenhuma nesta rodada. A §4.3 e o CA-05 foram cumpridos como escritos, e o humano aprovou a semântica do `defer`. Recomendado: (a) completar o risco 9 do plano dizendo que o 502 levava HSTS e `nosniff` antes da SPEC-032 e que a perda foi aceita (RV-01, sugestão a); (b) SPEC de acompanhamento, se o humano quiser, com um `handle_errors` no site que reaplique os 4 headers e apague o `Server` (é a opção que preserva o bloco único exigido pelo CA-05). |
| SEC-32-02 | baixa (lacuna fora do escopo da §4.2) | privacy | `.gitignore:32-43` | **SEC-36-02, fotos reais de terceiros com EXIF/GPS.** As variantes da §4.2 fecham as caixas misturadas de `jpg`, `jpeg`, `png`, `heic` e `webp`, inclusive `entrada/IMG_1234.JPG` e `entrada/a.HEIC`. Mas formatos que um celular ou um envio "como documento" também produzem continuam **sem** proteção, e todos podem levar EXIF com GPS: `.heif`, `.jfif`, `.jpe`, `.tif`/`.tiff`, `.dng`, `.avif`, e os vídeos de "Live Photo" (`.mov`, `.mp4`), que acompanham a foto e têm localização nos metadados. O `entrada/plano.csv`, que tem os `contributor` e as notas, também não é ignorado (O-02 do dev-report). Além disso, `!docs/**/*.[pP][nN][gG]` reabre qualquer PNG em `docs/`, por exemplo uma captura de tela com uma foto real. Isso é por projeto (SPEC-032 §4.2, CA-02) e já valia para `*.png` antes. Um `git add -A` com a pasta de entrada dentro do repositório publicaria esses arquivos, porque o repositório é público. **Por que não bloqueia:** a SPEC lista as extensões de forma fechada, e acrescentar outras seria improviso do autor. A importação da SPEC-036 recusa tudo que não seja JPEG ou PNG. E a mitigação principal do SEC-36-02 é humana e continua valendo: manter a pasta de entrada e o plano **fora** do repositório (`~/partqc-entrada/`), como a SPEC-036 já exige em relação ao dataset. | Nenhuma nesta rodada. Recomendado ao orquestrador: (a) na SPEC-036, ou no `docs/dataset-protocol.md` §10, deixar explícito que a pasta de entrada fica fora do checkout, e não só fora de `DATASET_DIR`; (b) se o humano quiser defesa em profundidade, uma SPEC pequena que acrescente ao grupo de fotos do `.gitignore` (e aos `.dockerignore`) `heif`, `jfif`, `jpe`, `tif`, `tiff`, `dng`, `avif`, `mov` e `mp4`, com as variantes de caixa, conferindo antes com `ls-files -ci` que nenhum arquivo rastreado casa. |
| SEC-32-03 | baixa (= RV-02/O-T-02) | deploy | `.env.example:76-81`; `docs/deployment-plan.md:65` | `*_PIDS_LIMIT=0` faz o `docker compose config` descartar o `pids_limit`, e `-1` significa "sem limite". Nos dois casos, não há aviso. O plano manda "subir o valor", mas quem "zerar para destravar" na pressa da demo desliga o endurecimento contra fork bomb ou vazamento de threads sem perceber. O `mem_limit` continua contendo o dano, por isso a severidade é baixa. | Nenhuma nesta rodada. Recomendado (o mesmo do RV-02): uma frase no `.env.example` e no bullet "Se um contêiner bater no `pids_limit`" dizendo que o valor é um inteiro positivo, e que `0` e `-1` removem o limite e nunca devem ser usados. |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação aplicada em toda rota que precisa dela; comparação em tempo constante | N/A: nenhuma rota nem código de autenticação mudou. O Caddy continua roteando só `/api/*` e o resto para o Streamlit, sem `/docs` nem `/openapi.json` (CA-30 da SPEC-015, conferido pelo CA-04). |
| Entradas validadas | ✅ A única entrada nova é a linha de comando do smoke. Com `allow_abbrev=False`, abreviações e `--=<valor>` caem na contagem sem eco (item 1). Nenhum schema, limite de corpo ou regex de ID mudou. |
| SQL sempre parametrizado | N/A: nenhum SQL no diff. |
| RLS ligado; `DATABASE_URL` e `service_role` fora da API | ✅ Nada mudou. O `DATABASE_URL` só aparece como o marcador fictício dos testes `docker` (`<user>:<password>@db.example.org`, preexistente) e na documentação do plano, sem valor. |
| CORS fechado ou mínimo | N/A para CORS, que não mudou. Os headers novos reduzem a superfície: sem `server`/`via` nas respostas proxiadas, `Referrer-Policy: no-referrer` e `frame-ancestors 'self'`, sem `includeSubDomains`/`preload` e sem CSP completa (§3.2). A única perda é o SEC-32-01. |
| Logs sem segredos e sem payloads de imagem | ✅ O Caddy continua sem log de acesso. O smoke não repete valores (item 1). Os relatórios da rodada não têm subdomínio, IP nem valor com cara de segredo. |
| Dependências novas | ✅ Nenhuma. As imagens base continuam fixadas por tag e digest. |
| Deploy: variáveis, health check, plano free sem cartão | ✅ As 3 variáveis novas estão no bloco `infra/.env` do `.env.example`, com o valor padrão `256` e sem nada sensível. Os health checks da SPEC-015 continuam (o dashboard fica `healthy` com `read_only`, CA-07). Nenhum serviço novo (R-01). O endurecimento (`read_only`, `tmpfs` `noexec` de 64m, `pids_limit`) se soma ao `cap_drop: ALL` e ao `no-new-privileges` existentes. Ressalva operacional: SEC-32-03. |
| Reaprovação delegada (ADR-019) | ✅ Não houve reaprovação delegada nesta branch. Os commits do orquestrador (`a544d0a`, `6b3b46b`, `8658888`, `f842019`) só mudam status, `Rodada atual`, o `docs/plan.md` e uma linha de Histórico que registra a decisão humana de entrar em `In Dev` antes de a SPEC-015 estar `Done`. Nenhum texto de requisito, CA, limite de segurança ou regra inegociável mudou. |

**Regras inegociáveis tocadas:** R-01 ✅ (nenhum serviço nem dependência); R-02/R-14 ✅ com a ressalva SEC-32-02 (o `.gitignore` melhora, e a lacuna é de escopo); R-03 ✅ (nenhum segredo, `.env.example` atualizado, `.env` ignorado em qualquer caixa); R-07 ✅ (item 6); R-13 ✅ (item 5).

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma dependência nova. |

## SPEC_ISSUE

Nenhum.

## Declaração

- [x] Não editei código; não sou autor desta SPEC. Só escrevi este relatório.
