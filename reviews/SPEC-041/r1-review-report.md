# SPEC-041 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-041](../../docs/specs/SPEC-041-modelo-provisorio-e-piso-do-split.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `origin/main...ca431e2` |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante ou alto. O código não precisa de rodada nova. **O merge continua impedido pela R-09** até o SPEC_ISSUE-07 (abaixo) ser fechado e até o portão de segurança da tag `security` sair.

**Atualização:** o SPEC_ISSUE-07 foi corrigido e está fechado, e o veredicto vale até `3f233a0`. Ver a seção "Adendo".

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | média | `docs/adr/ADR-024-modelo-provisorio-e-piso-do-split.md:165` | A resposta 11, que amplia a delegação do próprio orquestrador (exceção à X-7), entrou no commit `db2fbff`, escrito pelo orquestrador. O título é `chore: record SPEC-041 re-approvals and resume r1`, sem corpo que cite o ADR. O ADR-019 ("Como funciona", passo 2) e a skill `features` §4 pedem um "commit só de status" para a reaprovação. Há precedente de o orquestrador registrar resposta do humano em ADR (`4c62e22`, `ddc2dfe`), mas em commit próprio e com o assunto no título. O repositório só traz o relato do orquestrador: não consigo confirmar por aqui a resposta do humano, nem que ele foi avisado de cada caso, como a própria resposta 11 exige. **Impacto limitado:** nenhuma reaprovação desta branch depende dessa exceção para valer (ver a conferência abaixo). | No corpo do PR, citar a resposta 11 e o commit `db2fbff` na seção "Reaprovações sob o ADR-019", para o humano ver e poder vetar. Daqui em diante, nas SPECs 041 e 019, registrar esse tipo de resposta em commit próprio. |
| RV-02 | baixa | `docs/specs/SPEC-041-modelo-provisorio-e-piso-do-split.md:119`, `ml/README.md:237` | É a O-01 do test-report. O §4.5 diz que `export` sai com 2 "sem mudança", e isso é falso sem torch. Reproduzi: saída 1, com `ModuleNotFoundError` em `ml/src/qc_ml/export.py:36`, antes de ler a config. Com torch, saída 2 e a mensagem certa. O `ml/README.md` repete a frase. Decisão na seção "Decisão sobre a O-01". | SPEC_ISSUE-07 para o §4.5. A linha do README pode ser ajustada numa manutenção do ML, ou nesta branch se houver outra rodada. |
| RV-03 | baixa | `reviews/SPEC-041/r1-dev-report.md:12`, `:73`, `:98`, `:114` | A Parte A do dev-report continua dizendo que o SPEC_ISSUE-06 está aberto e que os CAs 07 a 09 não passam como escritos, embora o CA-07 já tenha sido corrigido. Além disso, `550d1c6` reescreveu o relatório e tirou o texto original dos SPEC_ISSUE-01 a 03, que o Histórico da SPEC cita. Eles só existem em `git show 5838d2b`. | Nas próximas SPECs, acrescentar a resolução ao relatório sem apagar o texto do `SPEC_ISSUE`. Não pede correção agora. |
| RV-04 | baixa | `ml/src/qc_ml/provisional.py:129` | É a O-04 do test-report. Um `--models-root` que aponta para um arquivo passa por todas as recusas e só falha depois do treino, que na CPU pode levar bastante tempo. Sai com 2, sem gravar nada, e o §4.3 não cobre o caso. | Numa manutenção: conferir, antes de treinar, que o `--models-root` é um diretório ou ainda não existe. |
| RV-05 | baixa | `ml/src/qc_ml/provisional.py:414` | É a O-03 do test-report. `--seed -1` e `--seed 99999999999` saem com 2, como o §4.2 pede, mas com traceback na stderr. | Numa manutenção: validar a faixa da seed no `_parser`. |

Contagem: 0 bloqueantes, 0 altos, 1 médio, 4 baixos.

## Conferência das reaprovações (checklist §1 e §6; ADR-019; ADR-024, resposta 11)

Conferi o `git show` de cada commit do architect (`111d2be`, `35f2c2d`, `1e217fb`) e dos commits de aprovação (`db2fbff`, `d093dcb`). Todos os itens abaixo valem para as seis correções:

- **E-2:** os três commits têm `Agent: architect` e tocam só o arquivo da SPEC.
- **E-3:** a SPEC estava `Blocked` em cada correção (`8f2caa9`, `ae0abaf`, `f4d08f7`).
- **X-1 a X-4:** nada de SPEC nova, ADR, outro documento ou contrato.
- **X-9:** cada CA e cada trecho foi corrigido uma única vez. O §4.3 tem duas correções em linhas diferentes da tabela (SPEC_ISSUE-02 e 03), e o §4.9, em frases diferentes (SPEC_ISSUE-04 e 05).
- **Registro:** avisos do topo, classificação e linhas de aprovação no Histórico, no formato do ADR-019.

| `SPEC_ISSUE` | Trechos | Quem reaprovou | Pontos conferidos | Resultado |
|---|---|---|---|---|
| 01 | §4.4, CA-09 | Orquestrador (`db2fbff`) | `manifest_sha256` está em `METRIC_KEYS`, e a chave era exigida e proibida ao mesmo tempo. O CA continua exigindo as 17 chaves exatas e recusando as outras. É um hash de entrada, não uma métrica de qualidade (E-4 tipos 1 e 2; X-6 ok). | Dentro dos limites |
| 02 | CA-23, §4.3 | Orquestrador (`db2fbff`) | Só muda o fluxo em que o `validate` já escrevia. Saída 2, o código do problema e "nenhum `split_v*`" continuam exigidos, e a guarda é a mesma (E-4 tipos 1 e 2). | Dentro dos limites |
| 03 | §4.3, CA-25 | Orquestrador (`db2fbff`) | **O caso mais próximo do limite.** A leitura de `labels_overrides.csv` é uma recusa que o texto antigo não detalhava, o que levanta a X-5 ("comportamento novo"). Considero esclarecimento, porque o §4.3 já remetia ao §4.9, que trata dos dois arquivos, e a decisão 4 do ADR-024 diz "recusa um conjunto com qualquer outro". Não surgiu assinatura nem arquivo: `parse_csv`, `OVERRIDE_COLUMNS` e `OVERRIDES_FILE` já eram públicos. A guarda fica mais estrita (E-4 tipos 1 e 3). | Dentro dos limites |
| 04 | §4.9, CA-28 | Humano (registrado em `db2fbff`) | Classificação correta: `exige humano` (X-7), fora da delegação. O texto novo só deixa a guarda mais estrita. O código cumpre: `load_plan` faz essa recusa primeiro (`edge/src/qc_edge/importer.py`), com 6 casos no aceite. A resposta do humano é relatada no Histórico; o repositório não permite confirmá-la de forma independente. | Conteúdo correto; aprovação como registrada |
| 05 | §4.9 | Orquestrador (`db2fbff`) | Confirmado: a única chamada a `load_manifest` no `export` é `ml/src/qc_ml/export.py:144`, sobre o dataset sintético. A decisão 4 do ADR-024 lista os mesmos seis comandos, sem o `export`, e nenhum CA cita o `export` nessa recusa (E-4 tipo 1; X-6 ok). | Dentro dos limites |
| 06 | CA-07 | Orquestrador (`d093dcb`) | Ver abaixo. | Dentro dos limites |

**SPEC_ISSUE-06:**

- **E-4 tipo 2:** a forma de verificação muda, e a intenção fica (os 7 arquivos, a paridade e a carga na borda). O Histórico tem o texto antigo, o novo e a evidência, e os números batem com o dev-report (seed 42 = 1 entrada; seed 0 = 88). Rodei o aceite: passa com `--seed 0`.
- **X-5:** a opção (a) criaria parâmetro público e tocaria em `export.py`. A escolhida não muda nenhum código. Está certa.
- **X-6:** não há CA removido nem virado manual, e nenhum caso de erro sai. A seed de `--smoke` não é um valor que o produto promete. `test_extra_default_seed_either_works_or_leaves_no_directory` mantém coberto o comportamento com a seed padrão: saída 0, ou saída 2 sem diretório.
- **X-7 e resposta 11:** o CA-07 não verifica regra inegociável. O CA-08 (R-11) herda o dado, mas o que ele confere (nenhuma função de split chamada e nenhum `split_v*` criado) não depende da seed. **A reaprovação vale mesmo sem a resposta 11**, que o Histórico cita só como reserva.

**Exceção à X-7:** nenhuma das cinco reaprovações delegadas precisa dela. Se o CA-09 ou o CA-23 fossem lidos como verificação da R-11, a regra ficaria igual ou mais rígida, que é a condição da resposta 11. Nenhuma correção afrouxa regra, remove CA ou cria escopo novo.

**Falta no PR e no portão de segurança:** a seção "Reaprovações sob o ADR-019" do PR ainda não existe, e o `security-devops` deve fazer a própria conferência destas reaprovações (ADR-019, passo 3).

## Decisão sobre a O-01

**Não é bug de código nem bloqueia esta revisão. É um problema de texto da SPEC, e registro como SPEC_ISSUE-07.**

- **Não é bug:** `export.py` importa torch no topo desde a SPEC-012 e não muda nesta branch. O próprio §4.5 diz "sem mudança neles", e `export.py` não está no §3.1, então o código não poderia cumprir a frase sem sair do escopo.
- **A guarda vale nos dois ambientes:** sem torch, nada é exportado, com qualquer versão. Com torch, sai com 2 e a mensagem certa (`test_extra_export_with_the_train_extra_exits_2`). O CA-15 não cita o `export`.
- **Por que não deixar como observação:** a frase é falsa no ambiente do CI, e o tester restringiu o próprio teste a partir de uma leitura dela ("válido onde o módulo pode rodar"). Quando o problema está na SPEC, a regra do loop é registrar, sem reinterpretar. O SPEC_ISSUE-05 é um precedente direto, com o mesmo módulo.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Todos os CAs têm linha de rastreabilidade (Partes A e B). Nenhum CA foi alterado por autor. Fora do §3.1, só o que a SPEC autoriza (`require_torch` em `train.py`, §4.2) e `qc_ml.provisional` em `test_no_torch.py`. Reaprovações na seção acima. SPEC_ISSUE-07 aberto. |
| 2. Regras inegociáveis | ✅ | **R-01, R-12:** nenhuma mudança em `pyproject.toml` nem em `uv.lock`. **R-02:** o payload é só o contrato (CA-21). **R-03:** a busca no diff só achou `secrets.token_*` em testes e a URL local de banco de teste, sem senha, nos relatórios; sem variável nova. **R-04, R-05:** contrato e API intactos. **R-06:** `source=simulated` conferido em resposta, outbox e nuvem falsa; a API e os alertas já tratam esse valor (`api/src/qc_api/services/alerts.py:361`, `services/spc.py:210`), e o MQTT publica o mesmo `InspectionCreate`. **R-07:** os 22 commits têm trailer, os de `tests/acceptance/` são só do tester (`5325db9`), e os de produção, só dos autores. **R-11:** o provisório não chama função de split nem lê `split_v*` (conferido no código e no CA-08); a única chamada com `allow_agent_suggestion=True` é `provisional.py:351`. **R-13:** identidade única do projeto, sem menção a empresa no diff. |
| 3. Corretude | ✅ | Ordem das recusas do §4.3 conferida no código e no aceite. Limpeza em erro correta, inclusive as pastas criadas acima do modelo. `created_at` em UTC. Sem `except` que engula erro. Sem handler async novo com I/O bloqueante. Probes meus: piso, `--allow-below-floor`, repetição idempotente e `agent_suggestion_label` em toda linha. RV-04 e RV-05 são baixos. |
| 4. Testes | ✅ | PASS, com CA-22 manual pendente, como o §9 permite. Os testes são reais: subprocesso, `git init`, outbox SQLite, `OnnxInferencer`, espiões do CA-08 também nos nomes já importados. Nenhum teste de aceite anterior foi ajustado (só dois arquivos novos em `tests/acceptance/`). Sem pytest em subprocesso, sem rede (`HF_HUB_OFFLINE`, `--smoke`) e sem credencial literal. RNF-09: `qc_api.services`, `qc_edge.decision` e `outbox` não mudaram. |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos. Type hints presentes. Os `print` são só a stderr de CLI, como `qc_ml.split` já fazia e o §4.3 pede. READMEs atualizados, com a ressalva do RV-02. |
| 6. Segurança | ✅ (só reaprovações) | Conferi o item de reaprovação delegada, como pedido. O resto da seção fica com o `security-devops`, porque os autores são `ml-engineer` e `developer`, e não escrevo `security-report`. |

**O que rodei nesta revisão** (extra `train`, torch 2.14.1, CPU, em `ca431e2`): os dois arquivos de aceite (193 coletados), os testes do autor desta SPEC e `ml/tests/test_no_torch.py`, incluindo os *slow*: **328 passed**. Mais a reprodução da O-01.

**O que não rodei:** a suíte inteira, com e sem torch. Para ela, vale o test-report (`9818 passed` sem torch, na versão final), e o CI do PR ainda vai confirmar. A suíte com torch do test-report é anterior ao ajuste de `test_ca15_official_steps_exit_2`, que só toca arquivos de teste desta SPEC, repetidos por mim.

## Riscos que ficam (sem achado)

Decorrem da SPEC e do ADR-024, e os relatórios já os declaram.

- **Treino real sem medição:** nenhum teste rodou `qc_ml.provisional` sem `--smoke`. O passo 6 do §4.8 é o primeiro uso real, e a paridade pode falhar só no fim do treino, com saída 2 e sem modelo. Convém rodar isso bem antes do ensaio de 29/11.
- **CA-07 depende da seed e só roda localmente:** os testes *slow* não rodam no CI, e uma troca do torch pode quebrá-lo (Histórico da SPEC).

**Para o `security-devops`:**

- o nome é o único sinal na borda: renomear o diretório faz as inspeções saírem `live`;
- o `labeler` só é relido na fase 1 da importação;
- `labeler` quase igual passa pelo `load_manifest` padrão (O-02), embora o `qc_ml.provisional` e o importador o recusem.

## Pontos positivos

- `floor_problems` reusa `item_strata`, a mesma função da alocação, sem uma segunda regra de estrato.
- A borda decide pelo nome do diretório resolvido, e o aceite cobre o link com nome oficial apontando para um diretório provisório.
- `qc_ml.report` também confere o `realpath`, o que cobre `--model-dir .`, sem ampliar o escopo além da recusa.
- Os autores pararam e registraram os `SPEC_ISSUE` em vez de escolher uma saída.
- O tester declarou com clareza o que não pôde testar.

## SPEC_ISSUE (se houver)

**SPEC_ISSUE-07: o §4.5 afirma uma saída do `export` que não vale sem torch.**

- **O que a SPEC diz (§4.5):** "Com isso, `qc_ml.train`, `export`, `thresholds`, `evaluate` e `pipeline` saem com 2, sem mudança neles."
- **O que acontece:** sem torch, `python -m qc_ml.export --config <provisória>` sai com 1 e `ModuleNotFoundError` (`ml/src/qc_ml/export.py:36`), antes de ler a config, com qualquer versão, desde a SPEC-012. Com torch, sai com 2 e `provisional model versions are not allowed in the official pipeline`.
- **Sugestão de texto para o architect:** tirar o `export` da lista e acrescentar: "O `export` também sai com 2 quando o extra `train` está instalado. Sem torch, ele falha ao importar (saída 1) antes de ler a config, como desde a SPEC-012, e não grava nada."
- **Efeito:** só texto. Nenhum código, CA ou teste muda, então não há o que reimplementar nem retestar, e o loop segue na mesma rodada (skill `features` §4). A classificação pelo ADR-019 cabe ao architect, e a reaprovação, conforme ela. **Impede o merge até ser fechado** (R-09).
- **Depois da correção:** se a reaprovação for delegada, ela ainda precisa da conferência do reviewer e do portão de segurança (ADR-019, passo 3), que este relatório não cobre, porque o commit ainda não existe. O APPROVED acima vale para o diff até `ca431e2`.

Nenhum `SPEC_ISSUE` "exige humano" por reaprovação fora dos limites.

## Adendo: conferência do SPEC_ISSUE-07 (até `3f233a0`)

**Resultado: a reaprovação está dentro dos limites do ADR-019, e o SPEC_ISSUE-07 está fechado. O veredicto continua APPROVED, agora para o diff até `3f233a0`.** Nenhum achado novo: a contagem segue 0 bloqueantes, 0 altos, 1 médio, 4 baixos. Nenhum `SPEC_ISSUE` novo, nem "exige humano".

Fiz esta conferência pelo `git show` de `59bd963`, `adf8c4a` e `806e804` e pelo código. O security-report só serviu para saber o que já estava apontado.

### Reaprovação (checklist §1 e §6; ADR-019)

| Item | Resultado | Evidência |
|---|---|---|
| E-1 Origem | ✅ | SPEC_ISSUE-07, com ID, na seção "SPEC_ISSUE" deste relatório |
| E-2 Autoria | ✅ | `adf8c4a`, `Agent: architect`, toca só o arquivo da SPEC (+4 −1) |
| E-3 Estado | ✅ | SPEC aprovada pelo humano (Histórico, `Draft` → `Ready`) e `Blocked` por este `SPEC_ISSUE` desde `59bd963`, que o `docs/plan.md` cita |
| E-4 Natureza | ✅ | Tipo 1 na frase do §4.5, sem mudar o comportamento pedido; tipo 4 no aviso do topo e no Histórico |
| E-5 Abrangência | ✅ | As 4 linhas acrescentadas são a frase do §4.5, a linha do Histórico e o aviso do topo, com a linha em branco que o separa |
| X-1, X-2, X-4 | ✅ | Nada de SPEC nova, ADR ou contrato. O ADR-024 só pede a recusa no `TrainConfig`, sem citar a saída do `export` |
| X-3 | ✅ | `ml/README.md:237` repete a frase antiga, mas a correção vale sem mudar o README: o erro é anterior a ela. `docs/architecture.md`, `docs/PRD.md`, `docs/dataset-protocol.md`, `docs/plan.md` e o ADR-024 não prometem essa saída. O README segue como o RV-02, baixo |
| X-5 | ✅ | Nada novo: `export.py` importa torch no topo desde a sua criação (`2957070`, SPEC-012), e nenhum código mudou |
| X-6 | ✅ | Nenhum CA muda, e o CA-15 não cita o `export`. O caso de erro continua: com o extra, saída 2; sem ele, nada roda nem é gravado. A saída do `export` não é valor do PRD, da arquitetura, do contrato nem limite de segurança |
| X-7 | ✅ | A frase descreve a guarda do ADR-024 e não verifica regra inegociável: a SPEC marca com regra o CA-08 (R-11), a Parte B (R-06) e o CA-21 (R-02), e não o bloco "Guardas do caminho oficial", onde fica o CA-15. **A validade não depende da resposta 11**, que o Histórico cita só como reserva. Por isso, o RV-01 e o SEC-41-02 não afetam esta correção |
| X-9 | ✅ | Primeira correção da frase: `git log -G` só traz `ffb50c0` (texto original) e `adf8c4a`. Ninguém marcou "exige humano". A pergunta 10 do `docs/professor-questions.md` trata do modelo provisório, mas a correção não depende da resposta |
| Registro | ✅ | Classificação `elegível` no Histórico, com o texto antigo, o novo e a evidência. `806e804` é um commit só de status, com `Agent: orchestrator`: muda status, aviso do topo, linha de aprovação e a linha do plano |

**O texto novo está certo.** "Sem esse extra", em vez do "Sem torch" que sugeri, é mais preciso, porque `export.py:35-36` também importa `onnx`, e os dois são do extra `train` (`ml/pyproject.toml:18`). Rodei os cinco comandos com uma config provisória:

| Ambiente | `train`, `thresholds`, `evaluate`, `pipeline` | `export` |
|---|---|---|
| Com o extra `train` | saída 2, mensagem certa | saída 2, mensagem certa |
| Sem torch, sem onnx ou sem os dois | saída 2, mensagem certa | saída 1, `ModuleNotFoundError` |

Nenhum deles gravou artefato. O ambiente "sem" foi simulado, bloqueando os módulos no `sys.modules`, sem um ambiente real sem o extra.

**Não verificável pelo repositório:** se o orquestrador informou o humano na sessão, com o texto antigo, o novo e o motivo (ADR-019, passo 2).

### Commits depois de `673ccaa`

Nenhum muda código de produção nem testes. `git diff --name-only 673ccaa..HEAD` traz só `docs/plan.md`, o arquivo da SPEC e `reviews/SPEC-041/r1-security-report.md`.

| Commit | `Agent:` | Arquivos |
|---|---|---|
| `59bd963` | orchestrator | `docs/plan.md`, SPEC |
| `adf8c4a` | architect | SPEC |
| `806e804` | orchestrator | `docs/plan.md`, SPEC |
| `3f233a0` | security-devops | `reviews/SPEC-041/r1-security-report.md` |

De `ca431e2`, o último commit de código que revisei, até `3f233a0`, soma-se só este relatório. Por isso, o que foi revisado e testado em `ca431e2` continua valendo. Os quatro commits têm a identidade do projeto, e a busca por segredos nesse diff só achou a menção a `service_role` no texto do security-report.

### O que rodei

- `ml/tests/acceptance/test_spec_041.py`, com o filtro `ca15 or export_with_the_train_extra or official_guard`, com o extra `train` e sem banco: **7 passed**.
- As reproduções da tabela acima, em diretórios temporários.

**Não rodei** a suíte inteira nem nada com banco, como pedido. Para ela, vale o que este relatório já diz sobre o test-report e o CI do PR.

### O que falta para o merge

- A seção "Reaprovações sob o ADR-019" no PR, com as seis delegadas (01, 02, 03, 05, 06 e 07), a 04 como humana e a resposta 11 (RV-01).
- Os checks do PR verdes e as decisões do humano listadas no security-report (SEC-41-01 e SEC-41-02). Elas não são desta conferência.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
