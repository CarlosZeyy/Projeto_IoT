# SPEC-042 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-042](../../docs/specs/SPEC-042-manutencao-telemetria-ca-lote.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `origin/main...ca80943` (`origin/main` = `9419a5e`, 13 commits) |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante ou alto. O código faz o que a SPEC pede, e não encontrei bug. Os achados são de processo e de documentação, e nenhum pede mudança em código ou teste.

**O merge ainda depende do `security-report`,** porque a SPEC tem a tag `security`, e o §8 pede que o security-devops confira o CA-01 por conta própria. Esta revisão não o substitui.

## Achados

**Contagem:** bloqueante 0, alta 0, média 1, baixa 5.

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | média | commit `472771a`; `reviews/README.md:59` | O texto inteiro da SPEC (198 linhas) entrou no `chore: start SPEC-042`, com `Agent: orchestrator`, junto das mudanças de status, e a mensagem não cita a SPEC nova. O `reviews/README.md` manda commitar os arquivos do architect com `Agent: architect` e deixar o status em commit separado. A SPEC-040 e a SPEC-041 seguiram isso. Pelo Git, então, não dá para confirmar que o texto veio do architect; só o §1 da SPEC o cita. **Não é ❌ de R-07:** o item do checklist trata de autor e tester, e todo commit tem o trailer. O conteúdo não mudou depois: de `472771a` a `ca80943`, só o status, o aviso de aprovação e o título do Histórico | Sem reescrever a branch. Registrar no PR que o texto é do architect, e separar os dois commits nas próximas SPECs |
| RV-02 | baixa | `docs/specs/SPEC-042-manutencao-telemetria-ca-lote.md:10`; `docs/plan.md:85` | A semana alvo diverge: S4 (02–08/11) na SPEC e S5 no quadro | Corrigir o quadro para S4 num commit de status, que é a célula derivada da SPEC |
| RV-03 | baixa | `edge/src/qc_edge/templates/live.html:13` | `#lot-in-use { overflow-wrap: anywhere; }` não está na SPEC. **Aceito, sem mudança:** o §3.1 inclui o arquivo, o `<p>` segue o §4.3, o dev-report declara a regra com a medição (616 px de largura numa tela de 320 px), o tester conferiu o efeito (OBS-03), e a regra não muda comportamento nem CA | Nenhuma |
| RV-04 | baixa | `edge/src/qc_edge/static/live.js:112` | Com um lote de 40 `W`, a 3ª linha da faixa cai para 8 px em 390 px e para 6 px em 320 px (OBS-02). Não há corte, como o §4.3 exige, e a 2ª linha, com o aviso de R-06, não é afetada, porque a fonte é ajustada por linha. É o pior caso: `Lote: L-001` fica com 18 px, e `#lot-in-use` mostra o lote inteiro | Nenhuma agora. A dupla pode olhar isso no CA-11 |
| RV-05 | baixa | `docs/specs/SPEC-042-manutencao-telemetria-ca-lote.md:20` e `:139` | O §1 diz que a telemetria dispara "ao carregar um modelo", e o preâmbulo do §5 liga a conferência à criação da sessão. A OBS-01 mediu que o `import` já a dispara. A implementação e os scripts não são afetados, e o `docs/architecture.md` §9 já traz o fato certo. Ver "SPEC_ISSUE" | Nenhuma nesta rodada |
| RV-06 | baixa | `reviews/SPEC-042/r1-test-report.md:139-151` | O tester disparou a telemetria fora do isolamento, uma vez com o `HOME` real. Ele mesmo registrou. Sem imagem envolvida, e nada disso entra no Git. Conferi a data da fila real: 18:23:47, a do relatório, e ela não mudou com os meus comandos. Uma consulta de DNS pode ter saído | Citar no PR, para o humano ver antes de decidir o item 1 do §3.3. O §9 da arquitetura já cobre a prevenção |

## Rastreabilidade

| Critério | Implementação | Teste que o exercita | Conferência |
|---|---|---|---|
| CA-01 | `qc_edge/__init__.py`, `qc_ml/__init__.py` | `test_ca01_real_network_measurement_with_control` | Li o teste: `unshare` e `strace` do §4.2, controle obrigatório, sonda do observador, janela de 35 s conferida. **Não rodei** (ver "Limites") |
| CA-02, CA-03 | os mesmos | `test_ca02_*`, `test_ca03_*` | Sessão e inferência reais, em ambiente limpo; passaram aqui |
| CA-04 | os mesmos | `test_ca04_*` (`qc_edge` e `qc_ml`) | Passou |
| CA-05 | `conftest.py:24-25` | `test_ca05_*` | Passou |
| CA-06 | nenhum import novo | `test_ca06_*` | Passou. `git grep` confirma: fora de `tests/`, só os 3 arquivos, e nenhum import dinâmico |
| CA-07 | `.env.example:83` | `test_ca07_*` | Passou; o texto é o do §4.1 |
| CA-08 | `edge/README.md` | `test_ca08_*` | Passou; os 6 passos seguem o §4.4 |
| CA-09 | `live.html`, `live.js` | `test_ca09_*` | Passou, pelas rotas reais |
| CA-10 | `live.js:64-69`, `:108-113`, `:208` | Ensaio do tester, com controle negativo | Li os resultados. Conferi à parte a tabela do §4.3 (ver abaixo) |
| CA-11 | os mesmos | Manual, depois do merge (§8) | Pendente, como a SPEC prevê |

## Verificação independente

- **Testes:** `ruff check` e `ruff format --check` limpos. Os arquivos da SPEC e os do `/live` (`test_spec_042.py` dos dois lugares, `test_telemetry.py` dos dois lugares, `test_live_route.py` e `test_spec_019.py`): **291 passed, 1 skipped** (o CA-01, sem a variável).
- **`showLot`:** rodei o `live.js` real em Node, com o DOM falso, sem navegador: 14 de 14 casos certos. Cobrem as 4 linhas da tabela do §4.3, espaços nas pontas, campo apagado, lote guardado válido, inválido e com 41 caracteres. Em todos, o `lot` só muda ao confirmar.
- **README, passo 5:** `qc-edge --stub-model` com `EDGE_TLS_CERT` e `EDGE_TLS_KEY` apontando para arquivos inexistentes sai com **código 2**, como o texto diz. Sem fila no `HOME` temporário.
- **`docs/dataset-protocol.md` §9:** existe e manda apagar `captures`, como o passo 6 cita. `edge/data/tls` é o caminho que o próprio README manda criar.
- **Contagens do test-report:** os pulos somam 167, e os testes novos somam 41 (10 de CA e 31 extras), como ele diz.

## Limites desta revisão

- **Não rodei o CA-01,** nem a suíte inteira. Os números deles vêm do test-report. O CA-01 tem uma segunda conferência prevista, a do security-devops.
- **Não abri um navegador.** A faixa de 3 linhas, o `measureText` e os quadros com `lot_id` vêm do ensaio do tester e da leitura do código. O script do ensaio não é versionado, como o §6 permite, então não pude repeti-lo.
- **CI:** ainda não há PR. A conferência fica para o portão de merge.
- **Aprovação humana e decisão sobre a R-02:** só as li no Histórico e no §1 da SPEC, registradas pelo orquestrador. Não tenho como confirmá-las fora desses registros.
- **Menus do iOS e do Android:** o texto do README é o do §4.4. Não há celular aqui, e não abri as fontes externas.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Todos os requisitos estão no diff, e nenhum CA mudou. `app.py`, `live.py`, `packages/contracts`, `api/` e `dashboard/` ficaram de fora, como o §3.2 pede. Fora da SPEC, só a regra de CSS (RV-03) e a SPEC-042 no título do README. Rastreabilidade no dev-report. **R-08:** a aprovação (`34d8d0c`) vem antes do primeiro código (`d6304c5`). **ADR-019:** nenhuma reaprovação nesta branch |
| 2. Regras inegociáveis | ✅ | **R-01, R-12:** `uv.lock` e `pyproject.toml` sem mudança. **R-02:** nenhuma rota nova nem imagem; a telemetria é o assunto da SPEC, com o CA-01 no test-report. **R-03:** busca no diff sem chave, JWT ou credencial em URL; `.env.example` só com o comentário. **R-04, R-05:** payload e API sem mudança. **R-06:** o aviso continua na 2ª linha, e o ensaio teve `source=simulated`. **R-07:** `tests/acceptance` e `edge/tests/acceptance` só no commit do tester (`3999d70`), que não toca produção; `ml/` só do ml-engineer; o resto da produção só do developer; `docs/architecture.md` só do architect; todo commit tem o trailer. Ver RV-01. **R-11:** N/A, sem treino nem split. **R-13:** uma identidade, Conventional Commits, nenhuma empresa ligada à dupla no diff |
| 3. Corretude | ✅ | A atribuição direta vence um `0` herdado, e os dois `__init__.py` rodam antes de qualquer módulo do pacote. `showLot` usa `textContent`, e `send` e `tick` não leem o campo. A faixa usa `inspection.lot_id`, e a rota só aceita um lote válido, então a linha não mostra `null`. Sem `async`, SQL ou data novos |
| 4. Testes | ✅ | PASS, cobrindo todos os CAs. Os testes não são tautológicos: o dev-report mediu falha contra a produção anterior, e o CA-10 teve controle negativo. **CA-02 e CA-03 sem rede externa nem telemetria:** a conferência vem antes de o `onnxruntime` carregar. **CA-01:** só sob demanda, dentro do namespace. Nenhum ajuste em teste de aceite anterior (conferido no `--stat`), nenhuma suíte em subprocesso, nenhuma credencial literal. RNF-09: nenhum dos módulos exigidos muda |
| 5. Qualidade | ✅ | `ruff` limpo; sem código morto nem `print`; README e `.env.example` atualizados. `docs/architecture.md` §9 e §10 como o §8 pede, e o §9 já com o fato da OBS-01 |
| 6. Segurança | N/A | O autor não é o security-devops. O portão é dele, e continua pendente |

## Pontos positivos

- A medição do CA-01 só vale com o controle e com a sonda que prova que o `strace` enxerga a consulta, então os "0 consultas" têm observador comprovado.
- O tester achou a OBS-01 e pôs a conferência antes do `import`, o que preserva o propósito do preâmbulo do §5, e não só a letra.
- Os autores deixaram claro, nos dois relatórios, o que as medições parciais deles **não** provavam.

## SPEC_ISSUE (se houver)

Nenhum.

O descompasso da RV-05 não vira `SPEC_ISSUE`: nenhum requisito ou CA fica ambíguo ou contraditório por causa dele, o §1 relata a medição de outra rodada, e a conferência dos scripts cumpre o preâmbulo do §5. Concordo com a justificativa do tester na OBS-01.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
