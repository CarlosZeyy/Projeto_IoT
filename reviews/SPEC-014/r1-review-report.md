# SPEC-014 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-014](../../docs/specs/SPEC-014-simulador.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `main...19aab3a` |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante ou alto. Há 4 achados baixos (RV-01 a RV-04), que não bloqueiam. Como a SPEC tem a tag `security`, o próximo passo é o security-devops.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `scripts/simulate.py:349-365` e `:480` | É o T-01 do test-report, que reproduzi. `_api_url` aceita uma URL com caractere de controle no meio (`\x01`, `\t`, `\n`, `\x1b`, `\x7f`), porque o `urlsplit` não a recusa. O `httpx.Client(base_url=...)` levanta então `httpx.InvalidURL` sem tratamento: o processo mostra um traceback e sai com o **código 1**, que o módulo reserva para "item gerado inválido". Uso inválido deveria dar o código 2. A mensagem do httpx mostra só a posição do caractere, e não a URL nem a chave. Além disso, credenciais na URL já são recusadas antes desse ponto. Não há vazamento. | Em `_api_url`, aplicar à URL a mesma regra de `_api_key` (só ASCII visível, `"!" <= ch <= "~"`), ou validar com `httpx.URL(url)` dentro do `try` e tratar `httpx.InvalidURL` com `parser.error("invalid --api-url (not shown)")`. Um teste unitário com `\x01` e `\t` no host basta. |
| RV-02 | baixa | `scripts/simulate.py:215` (`parser.parse_args(argv)`) | É o T-02 do test-report, que reproduzi. Com a opção digitada errado (`--api-keyy <CHAVE>`), ou com a chave passada como posicional, o argparse responde `error: unrecognized arguments: --api-keyy <CHAVE>` e repete o valor no stderr. Não viola o CA-13 nem a R-03: o valor não foi reconhecido como `--api-key`, nada vai para o Git ou para log, e o valor já está no histórico do shell de quem digitou. O risco residual é o eco num log de CI ou numa gravação de tela da demo. O help e o README já recomendam a variável de ambiente. | Usar `args, extra = parser.parse_known_args(argv)` e, se `extra` não estiver vazio, chamar `parser.error(f"unrecognized arguments: {len(extra)} value(s) (not shown)")`. Uma variante é mostrar só os tokens que começam com `-`, cortados no `=`. Um teste com `--api-keyy <segredo gerado>` verifica que o segredo não aparece no stderr. |
| RV-03 | baixa | `scripts/simulate.py:311-313` | É um achado novo, da mesma classe do RV-01. `_LOT_NUMBER` (`[0-9]+`) aceita qualquer quantidade de dígitos, e `int(token)` levanta `ValueError` acima de 4 300 dígitos (limite do Python 3.12). Por exemplo, `--out-of-control-lots "$(python3 -c 'print("1"*5000)')"` produz um traceback e o código 1, em vez do 2. A entrada é absurda e não tem impacto prático. | Limitar o token (`[0-9]{1,4}` já cobre `--lots ≤ 500`) ou tratar o `ValueError` com `parser.error`. |
| RV-04 | baixa | `scripts/simulate.py:507-521`, `:551-556` e `README.md` (códigos de saída) | Comportamentos que a SPEC não define foram decididos pelo autor e registrados na seção "Decisões" do dev-report (itens 4 a 6) e no README: código 5 para 4xx diferente de 401/403/422 e para 3xx (sem novas tentativas e sem seguir redirecionamentos); health sem novas tentativas e falhando com qualquer status diferente de 200; validação extra de `--api-url`. Aceito as três decisões (ver a seção "Decisões locais do dev-report"). Mesmo assim, o §4.1 e o §4.3 da SPEC descrevem menos do que o código faz. | Sem mudança de código. Sugiro ao architect registrar esses comportamentos no texto da SPEC, como mudança só de texto, quando a SPEC for tocada de novo. Isso deixa a SPEC-015 (smoke test) e o README alinhados à SPEC. |

## Decisão sobre o T-01 e o T-02 (pedem uma r2?)

**Não pedem uma r2. Podem ficar para depois.** Motivos:

- **T-01 (RV-01):** nenhum CA é afetado. O efeito é um código de saída errado (1 em vez de 2) e um traceback para uma entrada que só aparece por erro de digitação ou por um `.env` corrompido. A mensagem não expõe a URL nem a chave, e nenhum dado é enviado. Corretude de baixo impacto.
- **T-02 (RV-02):** é o comportamento padrão do argparse com um token que ele não reconhece. O simulador nunca trata esse valor como chave, e a frase do §4.3 ("a chave nunca é impressa nem registrada em log") vale para o valor de `--api-key`/`SIM_DEVICE_API_KEY`, que o CA-13 verifica e que de fato nunca aparece. Não há violação da R-03, porque nada entra no Git nem em log. O risco residual (eco no terminal do próprio usuário) é baixo, e a mitigação documentada (preferir a variável de ambiente) já existe. A avaliação final desse risco é do security-devops, no portão de segurança. Se ele o elevar, a r2 passa a ser necessária.
- **Encaminhamento:**
  - se a SPEC voltar para uma r2 por qualquer motivo (por exemplo, por um achado do security-devops), incluir RV-01, RV-02 e RV-03 nela: são três correções pequenas e locais em `parse_args`;
  - se não voltar, registrar os três como dívida técnica a ser corrigida por uma SPEC (R-08). A SPEC-015 é candidata natural, porque usa o simulador no smoke test.

## Decisões locais do dev-report

| Decisão | Avaliação |
|---|---|
| `parse_args(argv, *, now=None)`, com `now` keyword-only | **Aceita.** É uma extensão compatível da assinatura do §3.1: `parse_args(argv)` continua funcionando com o relógio real. O parâmetro é necessário para que o padrão de `--start` (`now − lots × 10 min`) e o limite `now + 5 min` do CA-09 usem o mesmo `now` injetado em `main`, como o §5 exige. Sem ele, `main(..., now=...)` não conseguiria passar o relógio ao parsing. Não muda nenhum CA. |
| Validação extra de `--api-url` (sem host, com usuário ou senha, com query ou fragmento, porta inválida; nunca repete a URL; barra final removida) | **Aceita.** Só estreita a validação para valores inválidos ou perigosos, e o resultado continua sendo o código 2 do §4.1. Recusar credenciais na URL e nunca ecoá-la reforça a R-03. O CA-15 continua valendo: `http://` remoto dá 2 e `http://127.0.0.1:8001` é aceito. A lacuna de caracteres de controle está no RV-01. |
| Código 5 para 4xx diferente de 401/403/422 e para 3xx, sem novas tentativas e sem seguir redirecionamentos | **Aceita.** O §4.3 só define 401/403 → 3, 422 → 4 e rede/timeout/5xx → 5, e a lista de códigos (0 a 5) é fechada. Entre os códigos existentes, 5 ("API fora do ar ou falhando") é o mais coerente: a mensagem mostra o status HTTP, o que permite distinguir um 404 de URL errada. Repetir um 4xx não faria sentido, e a API não tem limitação de taxa (nenhum 429 em `api/src`). Não seguir redirecionamentos (o padrão do `httpx.Client`) é **positivo para a segurança**: evita reenviar `X-API-Key` para outro host. Ver o RV-04 sobre registrar isso na SPEC. |
| `--api-key` só com ASCII visível; `SimConfig.api_key` com `repr=False` | **Aceita.** Transforma um erro do httpx (que seria tratado como falha de rede, código 5) em código 2, sem ecoar o valor. |
| Resumo parcial no stderr quando o envio falha no meio; `detail` em lista mostrado como JSON compacto; código 1 mostra só a contagem de erros | **Aceitas.** Nenhuma delas expõe a chave. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Implementa §3.1 (assinaturas de `SimConfig`, `parse_args`, `generate`, `send` e `main`), §4.1 a §4.3, `testpaths`, README e `.env.example`, e nada fora do escopo: não há `register_device`, limpeza nem selo no dashboard. Nenhum CA foi alterado pelo autor. O SPEC_ISSUE-1 foi resolvido pelo architect (`ff3f4b1`, só o texto do CA-01) e reaprovado pelo humano, conforme o histórico da SPEC. O dev-report tem a rastreabilidade de todos os CAs. As decisões fora do texto estão no dev-report e foram avaliadas acima (RV-04). |
| 2. Regras inegociáveis | ✅ | **R-01:** nenhuma dependência nova; `httpx` já é dependência de runtime do `qc-api`, e o `uv.lock` não mudou. **R-02:** só JSON do contrato, nenhuma imagem. **R-03:** a busca no diff por `key`, `secret`, `token`, `password`, `postgres://`, `eyJ` e `://user:pass@` não achou segredos. Os únicos conninfos são `postgresql://postgres@localhost:55432/partqc_test`, sem senha. Nos testes, chaves e senhas são geradas em tempo de execução (`secrets.token_*`, `f"https://user:{secret}@…"`). O `.env.example` ganhou só comentários. **R-04:** o payload usa `InspectionCreate`/`BatchCreate`/`BatchResult` de `qc_contracts`, e as regexes vêm de `DEVICE_ID_PATTERN`/`MODEL_VERSION_PATTERN` com `re.fullmatch`. `MAX_BATCH_SIZE` e `MAX_FUTURE_SKEW` também vêm do contrato. O contrato não mudou (0.2.0). **R-05:** os ids vêm do RNG semeado (`uuid.UUID(int=getrandbits(128), version=4)`) e não dependem de `--start`. O CA-10 e o teste `db` com a API real comprovam o `duplicate`. **R-06:** `source=Source.SIMULATED` fixo, sem `--source`, com `allow_abbrev=False`. **R-07:** os trailers batem com os arquivos: `developer` só em `scripts/simulate.py`, `scripts/tests/test_simulate.py`, `pyproject.toml`, README, `.env.example` e dev-report; `tester` só em `scripts/tests/acceptance/` e no test-report; `architect` só no texto da SPEC; `orchestrator` só em status e histórico. Todo commit tem `Agent:`. **R-11:** N/A. **R-12:** sem torch nem onnxruntime; Python 3.12. **R-13:** todos os commits como `Carlos Moises <…CarlosZeyy@users.noreply.github.com>`, em Conventional Commits, sem menção a empresa. |
| 3. Corretude | ✅ | Ordem do RNG fixa e documentada na docstring de `generate`. `lot_id` com a data UTC de `--start`. Limite de `--start` calculado sobre o último item possível, incluindo o maior lote sorteado. NaN e infinito recusados nas taxas. Erros de overflow em `--start` tratados. Datas sempre com fuso e normalizadas para UTC, e `now` sem fuso é recusado. Não há `except Exception`. Os 2xx são validados com `BatchResult`, inclusive a contagem de resultados. CLI síncrona, sem async. Desvios baixos: RV-01 e RV-03 (entradas inválidas que saem com código 1 e traceback). |
| 4. Testes | ✅ | Test-report PASS, com um teste de aceite por CA. A validação por mutação feita pelo tester pega 13 de 14 mutantes, e o sobrevivente (`allow_abbrev`) não é exigido pela SPEC. Os testes não são tautológicos: o CA-16 compara com as 14 chaves literais do §3.2, e o CA-07 usa o `compute_p_chart` real da SPEC-006. Sem rede real (`MockTransport`; os testes `db` usam `TestClient` sobre o `clean_db`) e sem subprocesso. Conferi a suíte completa com `TEST_DATABASE_URL`: `2049 passed, 1 warning` (o aviso do `TestClient` já existia). A RNF-09 não cobre `scripts/`, mas a cobertura informada é de 98%. Nenhuma versão exata de pacote nos testes novos (§10 de `architecture.md`). |
| 5. Qualidade | ✅ | `ruff check` limpo e `ruff format --check` com 111 arquivos formatados (conferido). Funções pequenas, type hints nas públicas, sem `print` (usa `sys.stdout.write`, que é a saída de dados da CLI, e `logging` para os erros). Nenhuma lógica duplicada de `qc_contracts`: `grade_index`, os padrões, `MAX_*` e os schemas são importados. README e `.env.example` atualizados. |
| 6. Segurança | ✅ | Avaliação prévia; o portão é do security-devops. A chave vai só no header `X-API-Key`, nunca em URL, repr (`repr=False`), mensagem ou log, e o CA-13 e os testes extras conferem stdout, stderr e `caplog`. `https://` é obrigatório fora de `localhost`/`127.0.0.1`. URL com credencial é recusada sem eco. Redirecionamentos não são seguidos. As mensagens de erro não repetem a URL nem a chave. Riscos residuais baixos: RV-02 (eco do argparse) e RV-01. |

## Pontos positivos

- A assinatura do §3.1 foi seguida à risca, com injeção de `transport`, `sleep` e `now`, o que torna toda a lógica de envio e de tempo testável sem rede e sem relógio real.
- O SPEC_ISSUE-1 foi tratado como manda o processo: o autor implementou o texto literal, não contornou o problema no código e levou ao architect opções claras.
- A defesa da chave tem várias camadas: `repr=False`, mensagens sem a chave, validação de ASCII visível, nenhum redirecionamento e nenhuma URL com credencial.
- O resumo parcial na falha (`sent/created/duplicate/seed`) combina bem com a idempotência: basta reexecutar com a mesma seed.
- Os testes `db` com a API real (`create_app`) comprovam R-05 e R-06 de ponta a ponta, sem rede.

## SPEC_ISSUE (se houver)

Nenhum. O SPEC_ISSUE-1 da r1 está resolvido (`ff3f4b1`) e foi reaprovado pelo humano. O RV-04 é só uma sugestão de registro textual, não uma ambiguidade que bloqueie.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
