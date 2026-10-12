# SPEC-023 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-023](../../docs/specs/SPEC-023-pacotes-compartilhados-0-2.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `spec/SPEC-003-schema-banco...bbc9a08` (branch empilhada sobre a SPEC-003, PR #6). Código da SPEC: `3caaaf0` (contracts) e `d3e1679` (preprocess); testes de aceite: `606ac7a`. Os commits `6962921`, `c9aa1de`, `16e76f6` e `bbc9a08` são do orquestrador (linha da skill `contrato-api` aprovada pelo humano e marcações de status). Deles, só a separação de papéis e o conteúdo foram conferidos. |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Motivo do veredicto: os 13 CAs estão implementados, e cada um tem um teste de aceite que o exercita de verdade. A mudança de produção é mínima e segue a SPEC à letra:

- `le=MAX_LATENCY_MS` em `_InspectionBase`;
- no `load_image`, a checagem da flag como primeira instrução e a checagem de proporção em aritmética inteira, entre a de `MAX_PIXELS` e o `.load()`.

`transform.py` e `params.py` não mudaram, e o `uv.lock` só tem as duas linhas de versão. Não há achado bloqueante nem alto. O achado médio (RV-01) é sobre o custo dos testes de "suíte inteira" aninhados, como o orquestrador pediu. Ele não bloqueia esta SPEC, mas vira recomendação ao architect.

Reprodução feita pelo reviewer (somente leitura):

- `uv run ruff check .`: "All checks passed!". `uv run ruff format --check .`: "53 files already formatted".
- `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q --durations=8`: **1050 passed in 130.75s**. Os dois testes mais lentos são `test_ca13_ruff_and_full_suite` (47,4 s) e `test_ca15_ruff_and_full_suite_without_ci_and_db_url` (41,7 s). Durante a execução, amostrei a cada 2 s quantos subprocessos `pytest -p no:cacheprovider -q` estavam vivos, com o resultado: 0 (19 amostras), 1 (33), 2 (11) e **3 (2)**. Ver RV-01.
- `git diff --stat main -- packages/preprocess/src/qc_preprocess/transform.py packages/preprocess/src/qc_preprocess/params.py`: vazio (§7 da SPEC).
- Nos dois `tests/acceptance/test_spec_002.py`, só mudaram as duas asserções de versão do CA-01 e a primeira linha da docstring (3 linhas por arquivo), como manda a §3.1.
- Busca por segredos no diff: as únicas ocorrências são `postgresql://postgres@localhost:55432/partqc_test`, sem senha, nos relatórios de dev e de teste. Não são segredos.
- Pillow instalado: 12.3.0.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | média (recomendação ao architect) | `packages/contracts/tests/acceptance/test_spec_023.py:203-236`; `tests/acceptance/test_spec_022.py:550-566` | **Aninhamento de suítes.** O CA-13 roda a suíte inteira num subprocesso, assim como o CA-15 da SPEC-022. Cada um se protege só da própria recursão: o CA-15 com `--deselect` de si mesmo, e o CA-13 com `PARTQC_SPEC023_CA13_INNER=1` mais o `--deselect` do CA-15. Mas o CA-15 não propaga `PARTQC_SPEC023_CA13_INNER`. Então, na execução interna do CA-15, o CA-13 roda e abre um **terceiro nível**: externa → CA-15 → CA-13 → suíte. A amostragem confirmou 3 subprocessos `pytest` simultâneos. Resultado: cada `uv run pytest -q` executa a suíte **4 vezes** (a externa, a do CA-15, a do CA-13 dentro do CA-15 e a do CA-13 externo). Os dois meta-testes somam cerca de 89 s dos 131 s, e as demais 1048 execuções levam ~42 s, então o custo é ~3×. Hoje cabe com folga no `timeout-minutes: 30` do CI. O problema é que o padrão não escala: com k meta-testes que se protegem cada um por conta própria, o número de execuções cresce de forma combinatória, e não linear. Uma SPEC futura que copie esse padrão (o CA "ruff + pytest = 0" aparece em várias) multiplica o tempo de novo. Para esta SPEC, o aninhamento é **aceitável**: está correto, é determinístico, passa e cumpre o CA-13 como foi escrito. Não justifica uma rodada r2. | **Ao architect, numa SPEC de manutenção do setup, antes da próxima SPEC que traga um CA "suíte inteira":** (a) preferência: deixar de exigir que "ruff + pytest = 0" vire teste de aceite automatizado. O portão já é o CI (R-09), e o tester registra a saída dos comandos no test-report. Nesse caso, CA-15/SPEC-022 e CA-13/SPEC-023 viram verificações do relatório, com remoção dos testes por quem tem o papel; ou (b) se o teste automatizado for mantido, adotar uma convenção única: um marker `full_suite` e uma variável de ambiente (ex.: `PARTQC_INNER_SUITE=1`) definida por **todo** meta-teste, com o `conftest.py` da raiz pulando os testes `full_suite` quando ela estiver ligada. Assim, o custo fica em 1 + k execuções, e não em k!·e. |
| RV-02 | baixa | `reviews/SPEC-023/r1-test-report.md:37` | A frase "Sem isso, haveria um terceiro nível de suíte aninhada" é imprecisa. O `--deselect` evita o caminho CA-13 → CA-15 → suíte, mas o caminho simétrico CA-15 → CA-13 → suíte continua existindo (RV-01). O comportamento está correto; o erro está só na descrição. | Em uma próxima rodada ou num relatório futuro do tester, descrever o aninhamento real: 4 execuções da suíte e 3 níveis. Nada a mudar no código de teste agora. |
| RV-03 | baixa | `packages/contracts/tests/acceptance/test_spec_023.py:195-200`; `conftest.py:81-91` | A execução interna do CA-13 herda `TEST_DATABASE_URL`. A fixture de sessão `migrated_db` faz `drop schema public cascade` e reaplica as migrações **no mesmo banco** que a sessão externa ainda vai usar. Hoje isso é seguro só por causa da ordem do `testpaths`: `infra/tests`, o único diretório que usa `migrated_db`/`clean_db`, roda depois de `packages/contracts/tests`, então a sessão externa ainda não criou o schema quando o CA-13 roda. Uma ordem diferente (`pytest infra/tests packages/contracts/tests`, um plugin de ordem aleatória) faria a execução interna recriar o schema no meio da sessão externa. Nos testes atuais, isso funcionaria, porque o `clean_db` trunca, mas é um acoplamento frágil. | Entra na mesma decisão do RV-01. Se o meta-teste for mantido, ou ele usa um banco próprio (outro `dbname` com `test`), ou a convenção documenta que uma execução interna nunca roda em paralelo com testes de banco da externa. |
| RV-04 | baixa | `docs/specs/SPEC-023-pacotes-compartilhados-0-2.md:58`, `:138` | Depois do `6962921`, a skill `contrato-api` tem a linha "Estreitar a validação de um campo… minor" com o precedente SPEC-023. A SPEC ainda diz que "a tabela da skill não tem linha" e que a classificação vale "até o humano decidir", e o Histórico não registra essa decisão. A divergência é só documental. | O architect acrescenta uma linha ao Histórico da SPEC-023 (por exemplo, "skill `contrato-api` ganhou a linha de estreitamento de validação, aprovada pelo humano") no commit que marcar a SPEC como `Done`. Não exige mudança de código. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Todos os itens da §4.1 e da §4.2 foram implementados, inclusive a docstring com as duas condições novas e as duas linhas novas nas "Regras principais" do README. Fora do §3.1, só há a linha da tabela "Conteúdo" do README listando `MAX_BATCH_SIZE`/`MAX_FUTURE_SKEW`, que já eram públicas (documentação, decisão registrada no dev-report), e a linha da skill do orquestrador, prevista pela §7 e aprovada pelo humano. Nenhum CA foi alterado. A rastreabilidade CA → arquivo/teste está no dev-report. Nenhuma decisão nova embutida no código. |
| 2. Regras inegociáveis | ✅ | **R-01/R-12:** nenhuma dependência nova; `uv.lock` só com `qc-contracts` e `qc-preprocess` 0.1.0 → 0.2.0; `pyproject.toml` sem mudança de dependências. **R-02:** sem I/O de rede. **R-03:** nenhum segredo. **R-04:** a mudança está em `packages/contracts`, com aumento de versão (0.2.0), tag `contrato` e justificativa na §4.1; a classificação "minor" bate com a linha nova da skill `contrato-api`; o `architecture.md` §3.2 já documenta o teto (linha 78) e a versão (linha 43), então código e fonte descritiva convergem. **R-05/R-06/R-11:** N/A. **R-07:** `3caaaf0`, `d3e1679` e `510fc17` são do developer e tocam só `src/`, `pyproject.toml`, `uv.lock`, `tests/` (fora de `acceptance/`) e o dev-report; `606ac7a` é do tester e toca só `tests/acceptance/` e o test-report; os quatro do orquestrador tocam só a skill, o `plan.md` e o cabeçalho da SPEC. Todos têm o trailer `Agent:`. **R-13:** todos os commits são `Carlos Moises <…CarlosZeyy@users.noreply.github.com>`, em Conventional Commits, com `Refs: SPEC-023`. |
| 3. Corretude | ✅ | Os limites estão certos nas duas direções: `le` inclusivo (2³¹ − 1 aceito, 2³¹ rejeitado) e `>` estrito com inteiros (10:1 exato aceito, 10:1 + 1 px rejeitado). `min == 0` é tratado (é um ramo defensivo, porque o Pillow já recusa IHDR com lado 0). A flag é lida a cada chamada e nunca é escrita, e seu teste vem antes de `Path`, do tipo e de bytes vazios. O `RuntimeError` não é subclasse de `ValueError`/`InvalidImageError`, então a borda não vai confundi-lo com 415. O EXIF só troca os eixos, por isso a checagem pelo cabeçalho basta (CA-10). Modo lax: o tester mostrou que `"2147483648"`, `2147483648.0` e um inteiro JSON de 400 dígitos não contornam o teto. Sem datas, sem SQL e sem handlers async nesta SPEC. |
| 4. Testes | ✅ | Test-report PASS, cobrindo os 13 CAs mais 32 testes exploratórios relevantes: RLIMIT_AS de 64 MB reproduzindo o R-A, 8 threads sem tocar a flag, reimplementação independente do pipeline numa faixa 10:1 e JSON Schema com `maximum`. Os testes não são tautológicos: o CA-09 usa um PNG sem IDAT, que só dá `aspect ratio` se a regra vier antes da decodificação, e o espião do autor em `ImageFile.load` prova que nada é decodificado. Sem mock do código testado: só `monkeypatch` da flag global e, no teste do ramo `min == 0` do autor, de `Image.open`, uma dependência, o que é aceitável. Sem rede. Nenhum binário de imagem foi commitado. Custo do CA-13: ver RV-01 a RV-03. |
| 5. Qualidade | ✅ | `ruff check`/`format --check` limpos. Constantes nomeadas e comentadas, mensagens de erro claras e em inglês, type hints mantidos, sem `print` e sem duplicação. README de contratos atualizado. |
| 6. Segurança | N/A aqui | O portão é do security-devops (tag `security`). Notas abaixo. |

### Notas para o security-devops

- **R-A fechado:** o tester mediu ~0 MB de alocação para 100×400 000 e 20×2 000 000, rejeitados pelo cabeçalho, e 227 MB de pico para a maior imagem aceita (2 000×20 000, 40 M pixels a 10:1). O CA-08 e o teste sob RLIMIT_AS de 64 MB fixam isso.
- **Janela TOCTOU da flag (por desenho):** a flag é lida em `image.py:35`, mas o Pillow a consulta de novo dentro de `img.load()` (`image.py:73`). Se outra thread a ligar entre os dois pontos, um arquivo truncado pode passar. A SPEC define a checagem como defesa em profundidade, e a garantia principal é o `architecture.md` §9 ("nenhum componente liga essa flag"). Não é achado desta SPEC, mas convém conferir isso na SPEC-007, onde a borda processa em várias threads.
- O modo lax segue como risco aceito (§4.4), com gatilho de revisão registrado.

## Pontos positivos

- Diff de produção pequeno e cirúrgico (+30 linhas). A paridade com a 0.1.0 é garantida estruturalmente, porque `preprocess` não foi tocado, e não só por teste.
- Os comentários no código explicam o porquê: a aritmética inteira no limite e a leitura da flag a cada chamada.
- O developer previu e explicou com precisão as 3 falhas esperadas antes do ajuste do tester (CA-01 da SPEC-002 e o CA-15 da SPEC-022 por tabela).
- Os testes do tester e do autor se complementam, sem redundância cega: o tester escreveu caixa-preta antes de ler o código, e o autor cobriu a ordem das verificações com espião.
- A medição manual de RSS no test-report documenta o fechamento do R-A com números, e não só com asserção.

## SPEC_ISSUE (se houver)

Nenhum. O RV-04 é só uma atualização do Histórico da SPEC, sem ambiguidade de requisito. O RV-01 é uma recomendação de processo de teste ao architect, não um defeito da SPEC-023.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
