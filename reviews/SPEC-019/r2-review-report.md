# SPEC-019 — r2 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-019](../../docs/specs/SPEC-019-modo-ao-vivo.md) |
| Rodada | r2 |
| Reviewer | reviewer |
| Diff revisado | `origin/main...99d5ed6` (`origin/main` = `70cc351`, sem commit novo em relação à r1); foco em `e330113..99d5ed6` |
| Test report | r2-test-report.md (PASS, sem bugs) |
| **Veredicto** | **APPROVED** |

O bloqueante da r1 (RV-01, R-06) está resolvido, e confirmei o resultado por conta própria num navegador real. Restam só achados médios e baixos, todos da página. O merge ainda depende do `security-report` da r2, porque a SPEC tem a tag `security` e o portão não rodou na r1.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | média | `edge/src/qc_edge/static/live.js:62-65`, `:175` e `:188`; `:16` (mensagem) | O lote em uso não aparece na tela. Com um lote confirmado, trocar o texto do campo sem confirmar mantém os quadros no lote anterior, e o campo mostra outro valor (o test-report mediu isso: `L-0` no campo, 7 quadros com `L-001`). Se a peça estabilizar nesse intervalo, a inspeção entra no lote anterior, e nem a faixa nem a resposta visível avisam. O caso real que mais preocupa é fechar o teclado do Android pelo gesto de voltar: o campo costuma manter o foco, então nem `blur` nem `change` disparam, e a mesa e a peça já estão à vista. No primeiro uso, o mesmo estado mostra `Informe o lote: só letras...` com um lote válido no campo. **Esse comportamento do teclado vem do conhecimento da plataforma, e não foi reproduzido: não há celular nesta máquina.** O dano é o mesmo que a RV-03 da r1 queria evitar (subgrupo errado na carta p, ADR-013), agora num intervalo menor. Não bloqueia: o README explica a regra, e os dados de um modelo provisório ficam fora da carta p por padrão | Mostrar o lote em uso, e não só o campo: por exemplo, `Lote em uso: L-001` junto do campo, com um aviso `pressione Enter para aplicar` enquanto o campo divergir de `lot`, e o lote na faixa verde do `EMIT`. Conferir o gesto de voltar no CA-12 |
| RV-02 | baixa | `edge/src/qc_edge/static/live.js:113-116` | O canvas usa o tamanho em px CSS, sem `devicePixelRatio`, então o texto fica borrado em telas de escala 2 ou 3. Confirmei nas capturas de tela e na nota do test-report. Continua legível, mas agora a fonte chega a 14 px na faixa verde em 320 px, e é essa faixa que traz o aviso de R-06 durante o `EMIT` | Multiplicar `overlay.width` e `overlay.height` por `devicePixelRatio` e usar `ctx.scale`, mantendo `width` e `height` lógicos no restante de `draw` |
| RV-03 | baixa | `edge/src/qc_edge/templates/live.html:11-12` | Com vídeo em retrato numa tela baixa, o palco passa da altura da tela, e a barra de estabilidade (§4.5) só aparece rolando a página. Confirmei em 320×568. A faixa fica visível nas medições, mas elas emulam a tela inteira, sem as barras do navegador, então a folga no celular deitado (a faixa termina em 340 de 390 px) é menor | Conferir no CA-12. Se atrapalhar, limitar a altura do palco, com cuidado para o canvas continuar alinhado ao vídeo |
| RV-04 | baixa | `edge/src/qc_edge/static/live.js:104-109` | Num `desconhecido` do modelo oficial, a faixa repete a palavra em duas linhas. Os dois rótulos seguem o §4.4, e a forma de exibir não é definida pela SPEC, então é só aparência | Omitir a 2ª linha quando ela for igual à 1ª. A linha com o aviso do modelo provisório é diferente e continua |

**Contagem:** bloqueante 0, alta 0, média 1, baixa 3.

## Achados da r1

| Achado da r1 | Situação | Como conferi |
|---|---|---|
| RV-01 = T-01 (bloqueante, R-06) | **Fechado** | Leitura de `fitFont`, `drawBand` e `resultLines`, os dois ensaios dos relatórios (com o controle negativo do tester: a r1 reprovada em 6 de 6) e o meu ensaio, abaixo |
| RV-02 (baixa, tester) | **Fechado** | `ebef0c9` só muda o filtro do teste, e o teste passou a exigir um registro de `qc_edge`. Rodei os arquivos da SPEC neste worktree, com o extra `train`, onde a r1 falhava: 347 passed |
| RV-03 (baixa) | **Fechado**, com o resíduo da nova RV-01 | `93699cf`: `send` e `tick` usam só `lot`, e o campo só é lido em `confirmLot` e `loadLot`. O test-report mediu com teclas reais |
| RV-04 (baixa) | **Fechado** | `c7da4f4`: `pageshow` com `persisted` recarrega, registrado antes dos retornos antecipados que importam (a saída de contexto inseguro vem antes, mas nela a câmera nunca abre). `reload` não produz `persisted`, então não há laço. O teste real dependeu de uma opção do Chrome, e continua valendo conferir no CA-12 |
| RV-05 (baixa, orquestrador) | **Pendente no PR** | Sem o que mudar no código. Na seção "Reaprovações sob o ADR-019" do PR, citar `77e3e12` e `9183d41` e registrar o aviso ao humano da SPEC_ISSUE-07 (ressalva 1 da r1) |

## Verificação independente do RV-01

A r1 dizia que esta máquina não tinha navegador. Isso estava errado: há Chrome em `/usr/bin/google-chrome-stable`. Como os roteiros do developer e do tester não são versionados, escrevi um à parte, só no diretório temporário da sessão, e encerrei o servidor ao terminar. Nada foi para o repositório nem para a nuvem.

**Ambiente:** Chrome headless por CDP (`mobile: true`, escala 2), câmera falsa, `create_app` real com `InMemorySink`, HTTP em `127.0.0.1` (contexto seguro, e o TLS não influi no desenho), `LIVE_FPS=5`, inferenciador roteirizado com o `model_version` `partqc-mnv3-provisional-v1` e `chave Phillips inutilizável`. O ensaio cobre só o rótulo mais longo, porque a regra é a mesma para os outros.

| Tela e vídeo | Canvas | 1ª linha | Veredito com o aviso | Faixa verde (`Registrada: ...`) | Limite direito |
|---|---|---|---|---|---|
| 390×844, paisagem 4:3 | 358×269 | 18 px, termina em 236 | 18 px, termina em 266 | 18 px, termina em 342 | 348 |
| 390×844, retrato 9:16 | 358×636 | 26 px, termina em 336 | 23 px, termina em 337 | 18 px, termina em 342 | 348 |
| 320×568, retrato 9:16 | 288×512 | 21 px, termina em 273 | 18 px, termina em 266 | 14 px, termina em 268 | 278 |

Os tamanhos batem com os dois relatórios, inclusive a menor fonte, de 14 px. Conferi também três capturas de tela a olho: as linhas ficam inteiras e legíveis, com o texto `reprovada (modelo provisório)` visível nas duas faixas. **Limites:** sem celular, sem Wi-Fi, sem certificado e com a fonte desta máquina. O aparelho real continua dependendo do CA-12.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Desde a r1, a SPEC só mudou no campo "Rodada atual" (`e330113..HEAD`): nenhum CA, nenhuma linha nova no Histórico, então a conferência de reaprovações da r1 continua valendo, sem nada a acrescentar. A r2 só muda `live.js`, os testes do autor, dois itens do README e um teste exploratório. As decisões 1 a 5 do dev-report ficam dentro do §4.5. Rastreabilidade completa no dev-report. CA-12 e §3.3 pendentes, como o §8 permite |
| 2. Regras inegociáveis | ✅ | **R-06 ✅**, agora visível no overlay: veredito com o aviso em linha própria, nas duas faixas; `source` igual ao da r1 (CA-13). R-01 ✅ sem dependência nova. R-02 ✅ `fetch` só para a própria origem e nenhum recurso externo. R-03 ✅ busca no diff sem chave, JWT ou credencial em URL; `git ls-files` sem `.pem`, `.key`, vídeo ou roteiro de ensaio; `.env.example` sem variável nova nesta rodada. R-04 ✅ `packages/contracts` intacto, e a r2 não toca a resposta da rota. R-05 ✅ sem mudança. R-07 ✅ abaixo. R-11 N/A. R-12 ✅ `uv.lock` sem mudança. R-13 ✅ uma identidade só (CarlosZeyy, e-mail `noreply`), nenhuma empresa citada no diff, Conventional Commits |
| 3. Corretude | ✅ | `fitFont` termina sempre (`size > 1`) e mede com a fonte em uso. A faixa cabe no piso do palco (66 px em 192 px). `lot` é sempre uma string, e um lote inválido confirmado não envia quadro. Sem mudança no servidor: reli o diff de `app.py`, `live.py`, `limits.py`, `middleware.py`, `security.py`, `config.py` e `cli.py` e não achei nada novo em relação à r1. RV-01 a RV-04 são da página, e nenhuma compromete dados de modo bloqueante |
| 4. Testes | ✅ | Relatório PASS, com um teste por CA automatizado. A verificação exigida na r1 foi feita, e foi além do pedido (6 telas, 92 casos, controle negativo, conferência por pixels). Rodei neste worktree, com o extra `train`: 347 passed nos arquivos da SPEC e `edge/tests` com 3525 passed, 7 skipped, sem o marcador `db`. Não rodei a suíte inteira: a r2 só muda JS e testes, e o tester mediu 10165 passed, 166 skipped. O CI do PR confirma. Os 3 testes novos do autor só fixam a forma do JS, como a docstring diz, e falhariam se `fitFont` ou o lote confirmado saíssem; o comportamento em si não tem regressão automática, porque a suíte não roda navegador, e a r1 não exigiu um CA novo. Nenhum teste de aceite de SPEC anterior mudou (único arquivo em `acceptance/`: `test_spec_019.py`), então não há tabela a conferir. Sem subprocesso de suíte, rede externa ou credencial literal novos |
| 5. Qualidade | ✅ | `ruff check` limpo e `ruff format --check` limpo (311 arquivos). Código morto removido (`lotId`, `saveLot`). README atualizado nos dois itens que mudaram. O `live.js` continua pequeno e sem framework |
| 6. Segurança | ✅ parcial | O autor é o `developer`, então o portão é do `security-devops`, e o `r2-security-report.md` **continua obrigatório** para o merge (R-09), com as conferências que a r1 deixou para ele (X-6 das 06 e 08, X-7 da 07, decisão local 7 contra a SPEC-025 §4.1). Sem achado de leitura na r2: nenhuma rota, token, limite ou log mudou, e a recarga do RV-04 usa a mesma URL e os mesmos headers |

## Separação de papéis (R-07)

Commits novos desde a r1. Todos têm `Refs: SPEC-019` e `Agent:`. Os da r1 estão no `r1-review-report.md`.

| Commits | `Agent` | Arquivos | Fronteira |
|---|---|---|---|
| `5d94c44`, `93699cf`, `c7da4f4` | developer | `edge/src/qc_edge/static/live.js`, `edge/tests/test_live_route.py`, `edge/README.md` | ✅ |
| `4c0fec5` | developer | só o dev-report | ✅ |
| `ebef0c9` | tester | só `edge/tests/acceptance/test_spec_019.py` e o test-report | ✅ |
| `46a357d`, `018f64b`, `99d5ed6` | orchestrator | status em `docs/plan.md` e na SPEC | ✅ |
| `e330113` | reviewer | só o review-report da r1 | ✅ |

O tester escreveu os roteiros de ensaio em `edge/tests/acceptance/_t01_rehearsal/`, sem commit, e os apagou: o caminho não está no índice nem no histórico da branch.

## Pontos positivos

- A correção do RV-01 usa medição em tempo de execução, então vale para qualquer fonte e proporção, e não só para os casos ensaiados.
- O developer reproduziu o defeito do RV-04, que a r1 só tinha visto por leitura, e mediu r1 contra r2 no mesmo roteiro.
- O controle negativo do tester mostra que o roteiro detecta o defeito, e a conferência por pixels independe da medição do código.
- O teste do RV-02 ficou mais forte: agora exige um registro de `qc_edge`, e o filtro não pode esvaziar a conferência sem aviso.

## SPEC_ISSUE (se houver)

Nenhum. O lote em uso (RV-01) é uma melhoria da página dentro do §4.5, e a SPEC não precisa mudar.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit de implementação ou de teste desta SPEC (`e330113` é o relatório de revisão da r1).
