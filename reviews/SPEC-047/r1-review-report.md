# SPEC-047 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-047](../../docs/specs/SPEC-047-console-visual.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `main...40bdac5` |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `docs/specs/SPEC-047-console-visual.md:297` | A linha da aprovação humana no Histórico (commit `3181e8e`, orchestrator) é uma linha de tabela (`\| 2026-11-17 \| ... \|`) logo depois de um item de lista, sem cabeçalho de tabela. No Markdown, ela aparece como texto literal com as barras. O conteúdo (aprovação, sem a tag `security`, exceção ao §5 do deployment-plan) está correto. | Ao marcar `Done`, reescrever as duas entradas no mesmo formato (as duas em lista ou as duas numa tabela com cabeçalho). Não exige rodada nova. |
| RV-02 | baixa | `edge/src/qc_edge/templates/console.html:40-41` | Entraram dois tons de apoio fora da tabela da §4.3: `#e9eef5` (fundo do `th`) e `#f6f8fa` (zebra). A §4.2, item 6, pede cabeçalho com fundo e zebra sem fixar a cor, e os dois ficam sob `#1b1b1b` com contraste acima de 14:1, então a regra de contraste da §4.3 é respeitada. O dev-report os registra em "Decisões". | Nenhuma ação. Fica registrado para o CA-11: se o projetor apagar a zebra, escurecer `#f6f8fa` dentro da mesma rodada (§5, CA-11, último parágrafo). |

Não há achados bloqueantes, altos nem médios.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | `git diff --stat main...HEAD -- edge/src` mostra só `templates/console.html` (54+, 16−), como exige a §7.2. O esqueleto da §4.1 foi seguido: as linhas `[igual]` estão idênticas, `$live_pairing` continua dentro de `.pairing`, `data-count` vem antes do `id` em `sink-pending` e `sink-dead`, e `sink-connectivity` ficou igual. Os únicos textos visíveis novos são `Pareamento` e a nota de 5 s. O `<head>` está igual. `docs/architecture.md` e `edge/README.md` não mudaram (§3.2). A rastreabilidade CA → teste está no dev-report. Não houve reaprovação delegada (ADR-019): a mudança para `Ready` (`3181e8e`) registra a aprovação humana no Histórico, incluindo a exceção de merge da §7.1. |
| 2. Regras inegociáveis | ✅ | R-01: nenhum recurso externo, fonte ou CDN (CA-01). R-02: N/A, nada sai da LAN. R-03: busca no diff sem segredos (o `postgresql://postgres@localhost` do test-report é o banco local de teste, sem senha). O token só aparece nas URLs de pareamento (CA-09). R-04, R-05, R-06, R-11 e R-12: N/A, sem contrato, API, dados ou dependências. R-07: os trailers conferem com os arquivos de cada commit. O developer (`7d43bb2`, `c1ae571`) tocou só `console.html`, `edge/tests/test_console_template.py` e o dev-report. O tester (`ae1d405`) tocou só `edge/tests/acceptance/test_spec_047.py` e o test-report. O architect (`01a39ed`) e o orchestrator (`3181e8e`, `785e633`, `8d07355`, `40bdac5`) tocaram só a SPEC e o `docs/plan.md`. Todos os 8 commits têm o trailer `Agent:`. R-13: identidade única `CarlosZeyy` (noreply), Conventional Commits, só famílias de fonte genéricas e nenhuma empresa citada. |
| 3. Corretude | ✅ | O template é válido para o `string.Template`, tem exatamente os 17 identificadores e nenhum `$` solto (o `rgba(...)` não usa `$`). Os seletores de selo usam o valor sem aspas e o prefixo `^=auth`, então o arquivo não contém `auth_error` nem um segundo `data-connectivity="`. Os testes antigos que procuram esses trechos continuam conferindo o valor renderizado. O seletor de zebra `tbody tr:nth-child(even):not(.complete) td` preserva o verde de `tr.complete td`, que tem especificidade menor. `#coverage tbody td:nth-child(n+3)` alinha à direita só as colunas `Imagens/meta` e `Peças/meta` geradas por `_coverage_row_html`, e o `tfoot td` com `colspan="2"`. Com TLS, `_live_pairing_html` gera `<div class="qr">` mais um `<div>` de texto, que caem como itens do flex `.pairing` e quebram linha no mesmo cartão. Não há `animation`, `transition`, `@keyframes`, `<details>`, `overflow`, `filter`, `opacity`, `transform` nem `prefers-color-scheme`. O selo de conectividade tem `white-space: normal`. A largura (`min(100%, 30rem)` por coluna, com `max-width: 1200px`) põe Pareamento e Estado lado a lado a 1280 px; a confirmação visual é o CA-11. |
| 4. Testes | ✅ | Test-report PASS, com um teste por CA do CA-01 ao CA-10 (CA-07 parametrizado pelos 4 estados, CA-08 com e sem TLS, CA-10 nos 3 casos de recusa mais o `?ip=` e os headers da 200). Os testes leem o template por `TEMPLATES_DIR` e renderizam a página real pelo `create_app` com o stub. Só a detecção de IPs e o `stats()` do sink são trocados, então os testes falhariam se o template quebrasse. Não há rede nem banco. O `git diff --stat main...HEAD -- '*/tests/acceptance/'` mostra só o `test_spec_047.py` novo: nenhum aceite antigo foi alterado, e a tabela de ajustes da `docs/architecture.md` §10 fica vazia, corretamente. Reexecutei `uv run pytest -q edge/tests/acceptance/test_spec_047.py edge/tests/test_console_template.py`: 41 passed. Não reexecutei a suíte completa (11212 passed no test-report). O CA-11 (manual) está pendente do humano e é condição da Definição de pronto antes do merge. |
| 5. Qualidade | ✅ | `uv run ruff check .`: All checks passed. `uv run ruff format --check .`: 336 files already formatted. O CSS é curto, cada regra tem um propósito claro, e o dev-report justifica as decisões de layout. O README não muda, porque o modo de rodar é o mesmo. Achados baixos RV-01 (SPEC) e RV-02 (cores de apoio). |
| 6. Segurança | N/A | SPEC sem as tags `security` e `deploy` (§9, pergunta 2, decidida pelo humano). Mesmo assim, conferi que rotas, headers, `FORBIDDEN_HTML` e a regra de acesso do console não mudaram (nenhum `.py` alterado) e que o CA-10 cobre o 403 e os headers. |

## Pontos positivos

- O diff de produção cabe num único arquivo, como a SPEC pede, e não toca nenhum fragmento do `app.py`.
- Os seletores foram escritos pensando nos testes antigos: o valor de conectividade sem aspas, o prefixo `^=auth` e nenhum `id` de aviso no CSS. Isso evita tanto o falso negativo quanto o teste que passaria sempre (SPEC §1).
- A zebra exclui `.complete` de forma explícita, e o tester cobriu isso com um teste exploratório.
- O tester escreveu os testes a partir da SPEC e acrescentou casos úteis: todo `$` é um placeholder, `id` como último atributo, `$live_pairing` dentro de `.pairing` e nenhuma rolagem interna. Ele também registrou o ensaio com `detect_lan_ips` vazio e explicou por que não é defeito.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
