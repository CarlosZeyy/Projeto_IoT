# SPEC-019 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-019](../../docs/specs/SPEC-019-modo-ao-vivo.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `origin/main...6bd595c` (`origin/main` = `70cc351`) |
| Test report | r1-test-report.md (PASS, com o bug T-01) |
| **Veredicto** | **CHANGES_REQUESTED** |

Motivo único do veredicto: RV-01 (T-01). O restante da entrega está correto, e as reaprovações estão dentro dos limites.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 (= T-01) | **bloqueante** (R-06) | `edge/src/qc_edge/static/live.js:73-74` e `:86` | O overlay desenha a 1ª linha com `fillText`, sem quebra nem ajuste à largura, e a fonte cresce com a altura. O aviso ` (modelo provisório)` fica fora do canvas fora dos 2 s do `EMIT`, e em retrato o próprio veredito sai da tela. Decisão na seção seguinte | Em `resultLines`, dar ao veredito uma linha própria, como `emittedLines` já faz. Em `drawBand`, medir cada linha com `ctx.measureText` e reduzir a fonte até caber em `width - 20`, para valer em qualquer proporção e também na 1ª linha da faixa do `EMIT`. Não muda a SPEC, a rota nem os rótulos |
| RV-02 | baixa | `edge/tests/acceptance/test_spec_019.py:1684` | `test_extra_token_and_image_do_not_reach_the_logs` só exclui o logger `httpx`. Com o extra `train` (ambiente documentado no `CLAUDE.md`), o `TestClient` usa o `httpx2`, cujo log traz a URL de teste com o token, e o teste falha. Reproduzido no `.venv` com torch: 1 falha em 344. Em ambiente como o do CI, passa: 344 de 344. Não é vazamento da borda, porque o log é do cliente de teste | **Tester:** filtrar por `record.name.startswith("qc_edge")`, ou excluir os dois loggers |
| RV-03 | baixa | `edge/src/qc_edge/static/live.js:57` e `:155` | Cada quadro envia o valor atual do campo de lote, mesmo no meio da digitação. Uma pausa de 5 s com a peça na mesa e o lote incompleto, como `L-0`, grava a inspeção nesse lote, e o lote é o subgrupo do SPC (ADR-013) | Guardar o lote só no evento `change`, que a página já escuta para o `localStorage`, e enviar esse valor. Não bloqueia |
| RV-04 | baixa | `edge/src/qc_edge/static/live.js:176` | Confirma a nota do tester, por leitura: o `pagehide` para a câmera e nada a religa se a página voltar do cache de navegação. A tela fica parada, sem mensagem. O `no-store` reduz a chance, mas o comportamento varia com o navegador | Tratar `pageshow` com `event.persisted` recarregando a página. Conferir no CA-12 |
| RV-05 | baixa | `docs/specs/SPEC-019-modo-ao-vivo.md:207` e commit `9183d41` | Registro da reaprovação: (a) o ADR-019, passo 2, pede um "commit só de status", e o `9183d41` também marca a SPEC-041 como `Done` e registra a decisão sobre o SEC-41-01 no `docs/plan.md`; (b) a linha 207 cita a resposta 11 do ADR-024 só para a 07, enquanto a linha da 05 a invoca de forma condicional. O conteúdo está certo, e nada disso muda a conferência abaixo: a 05 não toca a R-05 | Sem correção no histórico. Separar os commits nas próximas reaprovações e citar `77e3e12` e `9183d41` na seção "Reaprovações sob o ADR-019" do PR |

**Contagem:** bloqueante 1, alta 0, média 0, baixa 4.

## Decisão sobre o T-01

**O bug é real e bloqueia o merge. A severidade sobe de média para bloqueante.** O tester acertou a descrição, e a leitura do código confirma a causa (`live.js:73-74`).

**Por que é R-06, e não só layout:**

1. A SPEC §4.4 dá a finalidade do sufixo: "para o overlay também avisar". O JSON cumpre o texto, e o CA-13 passa, mas a finalidade não se cumpre.
2. O ADR-024, decisão 2, é explícito: "O celular e o console avisam que o modelo é provisório". No vídeo, o celular só avisa nos 2 s da faixa do `EMIT`.
3. O checklist §2 pede `source` "respeitado e visível", com a marca [R-06], e ❌ nesses itens é bloqueante.
4. Hoje o modelo provisório é o único que existe (ADR-024), então este é o caso principal do ensaio e do CA-12, e não uma exceção. A tela mostra `parafuso mediano — aprovada (` como se fosse um resultado qualquer.

**O que atenua, sem resolver:** os dados continuam corretos (`source=simulated` na resposta, no outbox e na nuvem, então nada contamina a carta p), e o console avisa. Por isso não há risco de dado, e o problema está no que a pessoa diante do celular vê.

**O alcance é maior que o do relatório:**

- A largura não resolve: `main` tem `max-width: 32rem` (`capture.css:3`), então o canvas não passa de 512 px em nenhuma tela.
- A fonte é `band / 2,6`, com `band = max(56, altura / 6)`, então cresce com a altura. O ensaio do tester usou câmera falsa em paisagem. Um celular em retrato costuma entregar vídeo em retrato, e aí o corte é pior.

Estimativa para `parafuso mediano — aprovada (modelo provisório)`, por escala linear dos 555 px medidos pelo tester com fonte de 22 px. Esta máquina não tem navegador, então os números são de cálculo, e não de reprodução:

| Canvas | Fonte | Largura do texto | Parte visível | Fica na tela |
|---|---|---|---|---|
| 358×268 (celular, vídeo em paisagem) | 22 px | 555 px | 63% | sem o aviso (medido pelo tester) |
| 358×477 (celular, vídeo 3:4 em retrato) | 31 px | cerca de 782 px | 44% | cerca de 20 caracteres: o veredito fica cortado |
| 358×636 (celular, vídeo 9:16 em retrato) | 41 px | cerca de 1034 px | 34% | cerca de 15 caracteres: sem o veredito |
| 512×384 (canvas máximo, 4:3) | 25 px | cerca de 631 px | 80% | sem o fim do aviso |
| 512×288 (canvas máximo, 16:9) | 22 px | 555 px | 90% | sem o fim do aviso |

Com o modelo oficial, o mesmo corte tira `aprovada` ou `reprovada` da tela em retrato, então a correção também é necessária para o §4.5.

**Como fechar:**

- **Quem:** o developer, na r2, em `live.js`. A SPEC está clara, então não há `SPEC_ISSUE`.
- **Sem CA novo como condição:** a suíte não roda navegador, e o CA-13 continua certo para o JSON. Um CA novo é decisão do architect e não é exigido por este relatório.
- **Verificação exigida na r2:** o tester repete o procedimento do T-01 em 390 px e registra o resultado no test-report, com vídeo em paisagem e em retrato (por exemplo, câmera falsa com `--use-file-for-fake-video-capture` e um arquivo sintético em retrato), para um modelo provisório e para o rótulo mais longo do modelo oficial (`chave Phillips inutilizável — reprovada`). A rodada pode se limitar a isso e aos testes da borda.

## Reaprovações da branch (checklist §1 e §6; ADR-019; ADR-024, resposta 11)

Conferidas com `git show` de `77e3e12`, `ddd28a2`, `9183d41`, `f86ce51` e `d76cbc5`.

**Critérios comuns às 12:**

- **E-2:** `77e3e12` tem `Agent: architect` e toca só o arquivo da SPEC. Depois dele, só commits de status do orquestrador mexem na SPEC (`9183d41`, `f727326`, `6bd595c`), e os dois últimos alteram só a linha de status.
- **E-3:** SPEC aprovada pelo humano (PR #45, com as reaprovações de 2026-11-01) e `Blocked` desde `d76cbc5`. O bloqueio foi aberto pelas 01 a 05; as 06 a 09 entraram na mesma passada, com a SPEC ainda `Blocked`, e leio assim a condição "por este `SPEC_ISSUE`".
- **E-5:** percorri o diff, e cada trecho alterado pertence a um ID: §3.1 (06, 10, 12e); §4.1 (12f); §4.2 (01, 02, 03, 07, 12c); §4.3 (09, 12b); §4.4 (04, 05, 08, 10, 12a); §4.5 (06, 12d); contexto do §5 (01); CA-05 (08); CA-08 (09); CA-09 e CA-14 (12e); CA-10 (06); CA-12 (10); CA-15 a CA-20 (02, 03, 04, 05, 12a, 10); §7 (12g); §8 (11).
- **X-1, X-2 e X-4:** nada de SPEC nova, ADR ou contrato. O `uv.lock` e `packages/contracts` não mudam.
- **X-3:** o `312e35f` (`docs/architecture.md`) decorre do §8 original (§6.1) e da 11, reaprovada pelo humano, e não de uma correção delegada.
- **X-9:** ninguém marcou as 01 a 09 como "exige humano", nenhuma depende do professor, e é a primeira correção de cada trecho. As que dividem o §4.2 e o §4.4 entraram juntas no mesmo commit, e nenhuma é uma segunda correção.

| ID | Aprovou | E-1 (registro) | E-4 | Exclusões a conferir | Conclusão |
|---|---|---|---|---|---|
| 01 | orquestrador | `f86ce51` | tipo 1 | X-5: o tipo `InferenceResult` já existe, e o nome antigo não existia em lugar nenhum | Dentro dos limites |
| 02 | orquestrador | `f86ce51` | tipos 1 e 3 (CA-15) | X-5: retira uma emissão que contrariava o §2 e o §3.2; `stability` e `(drill, None)` não mudam | Dentro dos limites |
| 03 | orquestrador | `f86ce51` | tipos 1 e 3 (CA-16) | X-5: "estável" (§2) já excluía o empate, e o caso não tinha resultado definido | Dentro dos limites |
| 04 | orquestrador | `f86ce51` | tipos 1 e 3 (CA-17) | X-4: a resposta vai da borda ao celular, fora do contrato. X-7: o sufixo e o CA-13 não mudam, e a SPEC-041 §4.7 ("inclusive `desconhecido`") confirma a decisão 2 do dev-report | Dentro dos limites |
| 05 | orquestrador | `f86ce51` | tipos 1 e 3 (CA-18) | X-5: é o caso mais próximo do limite, porque troca `WAIT_REMOVAL` por `reset` na falha; aplica o §2, com o `reset` já público. X-7: a idempotência não é tocada, e a tentativa que falhou não grava nada (o `SinkError` vem de uma escrita SQLite que falhou, `outbox.py:297`) | Dentro dos limites, sem precisar da resposta 11 |
| 06 | orquestrador | `ddd28a2` (antes da aprovação) | tipos 1 e 3 (CA-10) | X-6 (autenticação): o valor prometido ("sem token → 401") não muda, e a correção fecha o caminho sem token. X-5: mesmo arquivo em outra pasta; os headers vêm de "como a `/capture`" | Dentro dos limites. O portão de segurança confere de novo a X-6 |
| 07 | orquestrador | `ddd28a2` | tipo 1 | X-7: toca R-02 e R-14, então só cabe pela **resposta 11 do ADR-024**, cujas condições conferi: só texto, regra mais rígida (menos imagens em memória), nenhum CA removido, nenhum escopo novo, SPEC-019 ainda fora da `main`. O código cumpre: `live.py:104` e `:117-118`, com teste por `sys.getrefcount` | Dentro dos limites. Falta confirmar o aviso ao humano (abaixo) |
| 08 | orquestrador | `ddd28a2` | tipos 1 e 3 (CA-05) | X-6 (tamanho de corpo): os valores não mudam (1 048 576, 1 310 720 e 1 000 000), e o limite efetivo da rota fica mais estrito que os 3,5 MiB globais. Nenhum caso sai. X-5: nenhuma variável ou rota nova; `path_limits` é detalhe de implementação | Dentro dos limites. O portão de segurança confere de novo a X-6 |
| 09 | orquestrador | `ddd28a2` | tipos 1 e 2 | X-6: os 60 s e o 429 não mudam, e o CA-08 mantém a intenção. O Histórico traz o texto antigo, o novo e a evidência | Dentro dos limites |
| 10 | humano | `ddd28a2` | — | Classificada como `exige humano` (X-5) | Fora da delegação, e foi ao humano: correto |
| 11 | humano | `ddd28a2` | — | Classificada como `exige humano` (X-3) | Fora da delegação, e foi ao humano: correto |
| 12 | humano | `ddd28a2` | — | Classificada como elegível, mas reaprovada pelo humano: caminho mais rígido que o necessário | Correto |

**Conclusão: nenhuma reaprovação fora dos limites, então não há `SPEC_ISSUE` "exige humano".**

**Três ressalvas para o orquestrador:**

1. **Resposta 11, aviso ao humano:** a condição "o orquestrador avisa o humano de cada caso" (07) não deixa rastro no Git, e não consigo confirmá-la. Registre o aviso na seção "Reaprovações sob o ADR-019" do PR.
2. **Reaprovações do humano (10, 11 e 12):** confiro o registro no Histórico (linha 208), e não a resposta em si, que só o humano pode confirmar.
3. **Segunda conferência:** com a tag `security`, o `security-devops` faz a mesma conferência no `security-report`, com atenção à X-6 (06 e 08) e à X-7 (07). Ela não está coberta por este relatório.

As decisões locais 2, 3 e 7 aceitas no Histórico não são correções de requisito. A 7 é necessária para cumprir o §4.1 em `EDGE_PORT=443`: `is_allowed_console_host` continua só com os três nomes de loopback, sem `strip` nem prefixo, e, com TLS, deixa de aceitar o `Host` sem porta na 80. O `security-devops` a confere contra a SPEC-025 §4.1, como o Histórico pede.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Todos os requisitos implementados, com exceção do efeito pedido no §4.4 e no §4.5 (RV-01). CA-12 e §3.3 pendentes, como o §8 permite. Rastreabilidade completa no dev-report. Nenhum CA reinterpretado. As decisões do dev-report ficam dentro do escopo; a 2 é confirmada pela SPEC-041 §4.7. Reaprovações: seção anterior |
| 2. Regras inegociáveis | ❌ | **R-06: RV-01.** R-01 ✅ sem dependência, `mkcert` é BSD-3-Clause. R-02 ✅ `fetch` só para a própria origem, só o JSON no outbox (CA-07). R-03 ✅ busca no diff sem chave nem credencial; `.env.example` atualizado; `edge/data/tls/*` ignorado (`git check-ignore`). R-04 ✅ `packages/contracts` intacto. R-05 ✅ `inspection_id` novo a cada emissão, API sem mudança. R-07 ✅ abaixo. R-11 N/A. R-12 ✅ `uv.lock` sem mudança. R-13 ✅ identidade única do projeto, Conventional Commits |
| 3. Corretude | ✅ | Sem bug de servidor. Conferi: ordem dos erros; serialização do `feed` e gravação fora do lock (`live.py:212-217`, `app.py:760-770`); `reset` na falha, inclusive em exceção genérica; bytes descartados no `EMIT`, no `reset` e na expiração; handlers async sem I/O bloqueante (trabalho em thread com slot); datas com `clock` em UTC; erros com `{"detail"}` e sem stack trace. RV-03 e RV-04 são da página |
| 4. Testes | ✅ | Relatório PASS, e um teste por CA automatizado. Li os testes dos CAs: exercitam a rota e a máquina reais, e o `SpyInferencer` confere que o modelo não é chamado. Nenhum teste de aceite antigo mudou (o diff só adiciona `test_spec_019.py`). Sem subprocesso de suíte, sem rede externa, sem credencial literal. Rodei em ambiente como o do CI: 344 de 344 nos arquivos da SPEC e `edge/tests` com 3522 passed, 11 skipped. Cobertura: `live.py` 99%, `limits.py` 100%, `security.py` 100%; RNF-09: `outbox.py` 92%. RV-02 só no ambiente com torch |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos (311 arquivos). Type hints presentes, sem `print`. `_labels_pt` e `record_inspection` reaproveitados pela captura e pelo vídeo, sem duplicar a regra de defeito no JS. README e `docs/architecture.md` §6.1 e §6.4 atualizados |
| 6. Segurança | ✅ parcial | A SPEC tem a tag `security`, e o autor é o `developer`, então o portão é do `security-devops`. Aqui, só o item da reaprovação delegada (seção anterior). Sem achado de leitura nos demais: token em tempo constante nas duas rotas novas, limites de corpo e de pixels antes de decodificar, sem CORS, logs sem token. Não substitui o `security-report` |

## Separação de papéis (R-07)

| Commits | `Agent` | Arquivos | Fronteira |
|---|---|---|---|
| `dad275d`, `387cae4`, `1003693`, `92e515c` | developer | `edge/src`, `edge/tests` fora de `acceptance/`, README, `.env.example` | ✅ |
| `f86ce51`, `e058184` | developer | só o dev-report | ✅ |
| `fc67b8c` | tester | só `edge/tests/acceptance/test_spec_019.py` e o test-report | ✅ |
| `77e3e12`, `312e35f` | architect | só a SPEC; só `docs/architecture.md` | ✅ |
| `61f0efb`, `d76cbc5`, `ddd28a2`, `9183d41`, `d380fe6`, `f727326`, `6bd595c` | orchestrator | status, Histórico, `docs/plan.md`, adendo ao dev-report e o merge da `main` | ✅ |

Todos os commits têm `Refs: SPEC-019` e `Agent:`, inclusive o merge.

## Pontos positivos

- A máquina de estados é pequena e segue o §4.2 linha a linha, e a memória de quadros é mais rígida que o pedido: os bytes saem já no `EMIT`.
- `record_inspection` foi extraída da captura, então o vídeo herda o `source` da SPEC-041, a foto apagada na falha e o console, sem cópia de lógica.
- A rota usa `load_live_image`, com os limites conferidos pelo cabeçalho antes de decodificar, e o middleware passa a aceitar limite por caminho sem afrouxar as outras rotas.
- O tester foi além dos CAs: concorrência real, 150 JPEGs mutados, servidor TLS real e a página em navegador. Foi esse ensaio que achou o T-01.

## SPEC_ISSUE (se houver)

Nenhum. A SPEC está clara no RV-01, e as reaprovações estão dentro dos limites.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
