# SPEC-041 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-041](../../docs/specs/SPEC-041-modelo-provisorio-e-piso-do-split.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `origin/main...806e804` |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante ou alto. Há 2 médios, 5 baixos e 1 informativo. As guardas pedidas pela SPEC existem, estão no caminho certo e têm testes que falham sem elas. **O merge ainda depende de duas conferências fora deste relatório:** a do reviewer sobre o SPEC_ISSUE-07 (R-09, ADR-019, passo 3) e a do humano sobre a resposta 11 do ADR-024 (SEC-41-02).

O que mais pede atenção é o SEC-41-01: **renomear ou copiar o diretório do modelo provisório com um nome oficial desfaz toda a isolação**, na borda e no caminho oficial. Isso não contraria a SPEC, que decide "o nome decide sozinho", mas o ADR-024 não lista esse custo, e o humano precisa decidir se o aceita.

## Superfície analisada

- **Rotas:** nenhuma nova. `POST /api/capture` só muda o valor de `source` e o texto de `labels_pt.verdict`, com a autenticação e os limites de antes. `/api/status`, heartbeat, outbox, publisher, middleware e `capture.js` estão fora do diff.
- **Entradas externas novas:** argumentos de `python -m qc_ml.provisional`, `--allow-below-floor`, `--provisional-set`, e o `labeler` do manifest, de `labels_overrides.csv` e do plano. Tudo por CLI local, sem rede.
- **Segredos:** nenhum novo. `.env.example` sem mudança.
- **Dependências:** nenhuma. `uv.lock` e os `pyproject.toml` sem mudança.
- **Deploy:** nada. `infra/`, `.github/`, `api/`, `dashboard/` e `packages/` sem mudança.
- **Imagens:** o `qc_ml.provisional` lê imagens públicas locais e não envia nada. A única rede é o download dos pesos do ImageNet (`pretrained=True`, fora do `--smoke`), só de entrada, como o `qc_ml.train` já faz.

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-41-01 | **média** | input (R-06, integridade do modelo oficial) | `edge/src/qc_edge/onnx_inferencer.py:301`, `edge/src/qc_edge/app.py:540`, `ml/src/qc_ml/config.py:148` | **O nome é o único sinal, e o `provisional_report.json` não é lido por ninguém.** Reproduzi com um modelo real do `qc_ml.provisional`, copiado para um diretório `partqc-mnv3-v1`: a borda carrega como não provisório (o CA-18 mostra que esse nome sai `live`, sem sufixo e sem aviso), e `qc_ml.thresholds`, `evaluate`, `report changelog` e `report release-notes` saem todos com 0, gravando o `metrics.json` e gerando o texto do CHANGELOG e do Release. O arquivo `provisional_report.json`, com `provisional: true`, continua na pasta. O dev-report só declara o lado da borda. O lado do ML é novo, e por isso a frase do ADR-024 "nenhum caminho do código leva um resultado provisório ao `metrics.json`, ao CHANGELOG, ao Release ou à carta `live`" só vale enquanto ninguém renomear. **Não é bug:** cumpre o §4.1 ("se, e somente se") e a decisão 2 do ADR-024, e exige um ato deliberado no notebook. Mas o aviso existe só em `edge/README.md`: `ml/README.md`, a SPEC, o ADR-024 e o `docs/dataset-protocol.md` §11 não citam renomear, e o ADR não lista esse custo nas consequências, ao contrário do limite do `labeler`. | Nenhuma nesta rodada: o código segue a SPEC, e mudar exigiria escopo novo (X-5). **Decisão do humano:** aceitar e registrar o limite, ou pedir uma SPEC de manutenção em que a borda e o caminho oficial também tratem como provisório, ou recusem, um diretório com `provisional_report.json`. |
| SEC-41-02 | **média** | auth (autorização do processo, R-09) | `docs/adr/ADR-024-modelo-provisorio-e-piso-do-split.md:165` | É o RV-01, e concordo com ele. A resposta 11 amplia a delegação do próprio orquestrador e entrou no ADR pelo commit `db2fbff`, escrito por ele, misturada a um commit de status que não a cita no assunto nem no corpo. O repositório só traz o relato do orquestrador. Não consigo confirmar a resposta do humano, nem o aviso de cada caso, que a própria resposta 11 exige. Na minha leitura, nenhuma das seis reaprovações depende dela (seção "Reaprovações"), mas as SPEC_ISSUE-06 e 07 a citam como reserva. Se alguém ler a §4.5 ou o CA-07 como verificação de regra inegociável (X-7), a validade delas passa a depender dessa resposta. | No corpo do PR, citar a resposta 11 e o commit `db2fbff` na seção "Reaprovações sob o ADR-019", para o humano confirmar ou vetar. ADR alterado segue a R-09: aprovação humana do conteúdo. |
| SEC-41-03 | baixa | input | `ml/src/qc_ml/data.py:469`, `ml/src/qc_ml/data.py:1071` | É a O-02. O caminho oficial recusa um valor só, e o `labeler` do manifest é texto livre. Reproduzi: `Agent-Suggestion`, ` agent-suggestion`, `agent_suggestion` e `agent-suggestion ` passam no `qc_ml.data validate` com saída 0. Só uma edição à mão produz isso: o importador e o modo coleta recusam, e o `qc_ml.provisional` conta como `other labelers`. É da mesma classe do limite conhecido do §4.9. | Nenhuma nesta rodada. Numa manutenção, trocar a recusa de um valor por uma lista permitida (`a`, `b`) no modo padrão do `load_manifest`, conferindo antes se algum dado existente usa outro valor. |
| SEC-41-04 | baixa | input | `ml/src/qc_ml/report.py:656`, `ml/src/qc_ml/report.py:663` | A guarda do `qc_ml.report` olha só o nome do `--model-dir`. Reproduzi com `metrics.json` plantado à mão: `--previous` num diretório provisório sai com 0, e a entrada cita a versão provisória como "Anterior"; um `metrics.json` com `model_version` provisória num diretório de nome oficial também sai com 0. Nenhum código grava esse arquivo num modelo provisório, e o dev-report declara a escolha do `--previous`, que cumpre o §4.5. | Nenhuma nesta rodada. Numa manutenção, aplicar `is_provisional_version` também ao `model_version` dos dois `metrics.json` e ao nome do `--previous`. |
| SEC-41-05 | baixa | input (ADR-014) | `ml/src/qc_ml/agreement.py:43` | O `qc_ml.agreement` não usa o `load_manifest` e não recusa o `agent-suggestion`. Reproduzi: um `labels_second.csv` com esse `labeler` gera o relatório com QWK e saída 0. Assim, uma segunda rotulagem por agente poderia preencher, à mão, o portão de QWK do ADR-014, que a decisão 4 do ADR-024 mantém com a dupla. O §4.9 não pede essa recusa, e o `labeler_second` aparece no relatório, o que deixa o caso visível. | Nenhuma nesta rodada. Numa manutenção, recusar o valor nas duas entradas do `agreement`. Até lá, conferir o `labeler_second` antes de usar o QWK no `split_v1`. |
| SEC-41-06 | baixa | privacy (R-02, ADR-024, decisão 6) | `ml/README.md`, §4.8, passos 2 e 3; `docs/dataset-protocol.md:248` | A proibição de um agente abrir foto própria ou de conhecido é só regra de operação, como o ADR-024 declara. O risco concreto é o lugar: o §4.8 manda o agente trabalhar em `~/partqc-entrada/candidatos/`, e o protocolo sugere `~/partqc-entrada/` como pasta de entrada das fotos recebidas. Com a chegada de fotos de colegas, as duas coisas podem ficar sob a mesma raiz. Não abri essa pasta. | Antes de chamar o agente do §4.8 (orquestrador): passar só o caminho de `candidatos/`, conferir pela listagem que ela só tem recortes das fontes registradas e manter fotos de colegas em outra raiz. |
| SEC-41-07 | baixa | input (documentação) | `ml/README.md:237` | É a segunda parte do RV-02. O README ainda diz que `export` sai com 2, sem a ressalva que o SPEC_ISSUE-07 pôs na SPEC. A guarda não muda: sem o extra `train`, nada é exportado. | Corrigir numa manutenção do ML, ou nesta branch se houver outra rodada. |
| SEC-41-08 | informativa | privacy (fora do diff) | `edge/src/qc_edge/privacy.py:171` | Um link simbólico colocado à mão no dataset passa pelo `load_manifest`, que segue o link, e é ignorado pelo `qc_edge.privacy`. Reproduzi: 44 linhas aceitas, `checked 43 images, 0 with private data`, saída 0. O comportamento já existia, o importador nunca cria links, e o caso exige ato deliberado. Assim, o `0 with private data` do passo 5 do §4.8 não cobre um link. | Nenhuma. Se aparecer um link em `~/partqc-provisorio/data`, não confiar nesse resultado (`find <dataset> -type l` deve sair vazio). |

## Isolação entre o conjunto provisório e o oficial

Para cada guarda, além dos testes da SPEC, apliquei uma mutação numa **cópia temporária** do código e rodei o aceite correspondente. A cópia sem mutação passa (43 passed); as 17 mutações foram **todas pegas**, e conferi a causa em três delas (o `assert` falha pelo motivo esperado).

| CA | Guarda | Onde | Mutação | Resultado |
|---|---|---|---|---|
| 10 | Foto própria recusada | `ml/src/qc_ml/provisional.py:158` | desligar a recusa | pego |
| 11 | Caminhos fora de Git, depois de `realpath` | `ml/src/qc_ml/provisional.py:345` | desligar; conferir só o dataset | pego nos dois |
| 15 | `TrainConfig` recusa versão provisória | `ml/src/qc_ml/config.py:148` | desligar | pego |
| 16 | `changelog` e `release-notes` recusam | `ml/src/qc_ml/report.py:656` | desligar | pego |
| 17 | `source=simulated` com versão provisória | `edge/src/qc_edge/app.py:540` | sempre `live` | pego (`'live' == 'simulated'`) |
| 18 | Versão oficial continua `live` | `edge/src/qc_edge/app.py:540` | sempre `simulated` | pego |
| 23, 24 | `load_manifest` recusa no manifest e no override | `ml/src/qc_ml/data.py:1071`, `:469` | desligar cada uma; padrão `True` | pego nos três |
| 25 | `qc_ml.provisional` recusa outro `labeler` | `ml/src/qc_ml/provisional.py:160`, `:161` | desligar cada uma | pego nos dois |
| 26 | Modo coleta não aceita o valor | `edge/src/qc_edge/collect.py:78` | incluir o valor | pego |
| 27 | Sem a opção, `invalid_labeler` | `edge/src/qc_edge/importer.py:519` | aceitar sem a opção | pego |
| 28 | Dataset em Git, primeira verificação | `edge/src/qc_edge/importer.py:748` | desligar | pego |
| 29 | Importação válida | coberto pelo aceite | sem mutação | passa |
| 30 | Outro `origin`; manifest com outro `labeler` | `edge/src/qc_edge/importer.py:520`, `:764` | desligar cada uma | pego nos dois |

Conferi também, além dos testes:

- **Chamada única:** `allow_agent_suggestion=True` só aparece em `ml/src/qc_ml/provisional.py:351`, fora dos testes.
- **Todas as leituras oficiais do dataset usam o padrão:** `split.py:1056`, `thresholds.py:256`, `evaluate.py:507`, `:535`, `data.py:1440`, `train.py:485`. Nenhum chamador passa `apply_overrides=False`, que pularia a leitura de `labels_overrides.csv`. O `export.py:144` só lê o dataset sintético, e `export.py` não cita `dataset_dir`.
- **`source` só é decidido num lugar:** `edge/src/qc_edge/app.py:540` é o único ponto da borda que atribui `Source.LIVE` ou `Source.SIMULATED`. A API não filtra por `model_version` e já separa as origens (`routers/metrics.py:86`, `services/alerts.py:362`). `ALERTS_INCLUDE_SIMULATED` é `false` no compose e no `.env.example`.
- **Path traversal:** `--model-version` passa por `fullmatch` nos dois padrões antes de virar caminho (`_check_version`). O aceite cobre `../`, `/` e `\n`.
- **Limpeza em erro:** `_write_model_dir` apaga só o diretório do modelo e as pastas que ele criou. Um link simbólico no lugar do diretório é recusado antes.
- **Sem foto em artefato:** `parity_fixture.npz` usa entradas do dataset sintético (`export.py:143-144`), e o `provisional_report.json` só tem contagens, hashes e a perda.
- **Dentro de um repositório:** com o dataset ou o `--models-root` em `git init`, sai com 2, e `ml/models` não é criada.

### Os limites que o reviewer listou

| Limite | Conclusão |
|---|---|
| O nome é o único sinal na borda | É maior que o declarado: vale também no ML. Ver SEC-41-01. O link simbólico tem cobertura parcial: a borda e o `qc_ml.report` resolvem o caminho e tratam como provisório, mas `thresholds` e `evaluate`, por um link de nome oficial, saem com 0 e **gravam dentro do diretório provisório** (`decision.json` trocado e `metrics.json` novo, reproduzido). Depois disso, o `qc_ml.report` continua recusando esse diretório, com o link ou direto. |
| O `labeler` só é relido na fase 1 da importação | **Falha para o lado seguro.** Se outra execução acrescentar outro `labeler` depois da conferência, o conjunto fica recusado em `qc_ml.provisional` (`other labelers`, CA-25) e em toda nova importação com a opção (CA-30). Nenhum modelo sai dele. Sem achado. |
| `labeler` quase igual passa no `load_manifest` | Procede. Ver SEC-41-03. |

## Reaprovações (checklist §6; ADR-019; ADR-024, resposta 11)

Conferi o `git show` de cada commit, sem me apoiar no review-report. Valem para as seis correções:

- **E-2:** `111d2be`, `35f2c2d`, `1e217fb` e `adf8c4a` têm `Agent: architect` e tocam só o arquivo da SPEC.
- **E-3:** a SPEC estava `Blocked` em cada um deles.
- **Aprovação:** `db2fbff`, `d093dcb` e `806e804` têm `Agent: orchestrator`. No arquivo da SPEC, só mudam status, avisos do topo e linhas do Histórico.
- **X-1, X-2 e X-4:** nada de SPEC nova, ADR alterado por correção ou contrato. A mudança no ADR-024 é a resposta 11, em `db2fbff` (SEC-41-02).
- **Texto:** o diff da SPEC contra a `origin/main` só traz os trechos listados no Histórico, sem mudança silenciosa.
- **Sem código depois dos testes:** de `5325db9` até `806e804`, só mudam `docs/plan.md`, a SPEC e o review-report.

| `SPEC_ISSUE` | Trechos | Commits | X-6: limite de segurança ou CA enfraquecido | X-7: regra inegociável | X-9 | Resultado |
|---|---|---|---|---|---|---|
| 01 | §4.4, CA-09 | `111d2be`, `db2fbff` | Não. `manifest_sha256` é hash de entrada, e o CA continua com as 17 chaves exatas | Não. A R-11 é do CA-08 | 1ª correção | Dentro dos limites |
| 02 | §4.3 (manifest inválido), CA-23 | `111d2be`, `db2fbff` | Não. Saída 2, o código e "nenhum `split_v*`" continuam exigidos, e só muda o fluxo | Não. Guarda igual | 1ª correção, em linha diferente da SPEC_ISSUE-03 | Dentro dos limites |
| 03 | §4.3 (`labeler`), CA-25 | `111d2be`, `db2fbff` | Não. Fica mais estrito, e a mutação do override é pega | Não | 1ª correção | Dentro dos limites. É o caso mais perto da X-5, como diz o reviewer. Concordo: o ADR-024 já pedia recusar "um conjunto com qualquer outro", sem assinatura nem arquivo novos |
| 05 | §4.9 | `35f2c2d`, `db2fbff` | Não. O texto citava uma recusa que nunca existiu: `export.py` só lê o dataset sintético (conferido), então nenhum caso de erro real sai | Não | 1ª correção, em frase diferente da SPEC_ISSUE-04 | Dentro dos limites |
| 06 | CA-07 | `1e217fb`, `d093dcb` | Não. O CA continua automático, e a seed de `--smoke` não é limite de segurança. O `--smoke` não pula nenhuma recusa, salvo a faixa de `epochs`, que é do treino | Não. O que o CA-08 confere não depende da seed | 1ª correção | Dentro dos limites |
| 07 | §4.5 | `adf8c4a`, `806e804` | Ver abaixo | Ver abaixo | 1ª correção | Dentro dos limites |

A SPEC_ISSUE-04 não é delegada: o architect a classificou `exige humano` (X-7), e o registro é de reaprovação humana. Concordo com a classificação. O texto só deixa a guarda mais estrita, e o aceite pega a mutação correspondente. A resposta do humano é relatada no Histórico, e o repositório não permite confirmá-la por conta própria.

### Conferência da SPEC_ISSUE-07

O review-report não cobre esta correção, porque ela é posterior.

- **E-1:** registrada em `reviews/SPEC-041/r1-review-report.md`, com ID.
- **E-2:** `adf8c4a`, `Agent: architect`, 1 arquivo, a SPEC.
- **E-3:** `Blocked` por `59bd963`, antes da correção.
- **E-4, tipo 1, e tipo 4 para o aviso e o Histórico:** o texto antigo se contradizia, porque dizia "saem com 2, sem mudança neles", e o `export` não sai com 2 sem o extra, nem pode mudar: `export.py` não está no §3.1.
- **E-5:** só a frase citada, mais o aviso e o Histórico.
- **Reprodução do comportamento descrito**, com uma config provisória:

| Ambiente | Saída | Efeito |
|---|---|---|
| Sem `torch` | 1, `ModuleNotFoundError` | nada gravado |
| Sem `onnx` | 1, `ModuleNotFoundError` | nada gravado |
| Com o extra `train` | 2, `provisional model versions are not allowed in the official pipeline` | nada gravado |

  O texto novo ("Sem esse extra", e não "Sem torch") está certo: `export.py:35-36` importa os dois no topo, e os dois são do extra `train`.
- **X-3:** o `ml/README.md:237` continua com a frase antiga (SEC-41-07). Não considero mudança **necessária** para a correção valer: o erro no README é anterior a ela, e a SPEC, que prevalece, ficou certa. Fica como dívida pequena.
- **X-5:** nada novo. A saída 1 já existe desde a SPEC-012.
- **X-6:** nenhum CA muda (o CA-15 não cita o `export`), e nenhum limite de segurança muda. O que a guarda protege, nada exportado com versão provisória, vale nos dois ambientes.
- **X-7:** a frase descreve uma guarda do ADR-024, e não uma verificação de regra inegociável. Se for lida como X-7, a regra fica igual, que é a condição da resposta 11, mas aí a validade depende dela (SEC-41-02).
- **X-9:** primeira correção da §4.5.
- **Registro:** aviso do topo e linhas do Histórico no formato do ADR-019.

**Conclusão:** dentro dos limites. **Esta conferência não substitui a do reviewer:** a R-09 e o ADR-019, passo 3, pedem as duas, e o próprio review-report diz que a dele ainda falta para este commit.

### Resposta 11

Nenhuma correção afrouxa regra, remove CA ou cria escopo novo, que são os casos que a própria resposta 11 mantém com o humano. O aviso ao humano de cada caso não é verificável daqui.

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota, comparação em tempo constante | N/A: nenhuma rota nova. `POST /api/capture` continua com o token de sessão, sem mudança |
| Entradas validadas (tamanho, imagem, regex, `extra="forbid"`) | ✅ `--model-version` com `fullmatch` nos dois padrões; `--epochs` com faixa; plano e manifest validados antes de gravar. O `InspectionCreate` continua com `extra="forbid"` (CA-21). `--seed` fora da faixa sai com 2, com traceback (RV-05), sem efeito de segurança |
| SQL parametrizado | N/A: nenhuma query nova |
| RLS ligado; `DATABASE_URL` e `service_role` fora da API | N/A: nenhuma mudança |
| CORS | N/A: nenhuma mudança |
| Logs sem segredos e sem imagem | ✅ O `WARNING` da subida é um texto fixo. O `qc_ml.provisional` registra caminho local, hash e perda. O traceback do RV-05 só mostra caminhos locais |
| Dependências novas | N/A: nenhuma |
| Deploy | N/A: nenhuma mudança |
| Reaprovação delegada (ADR-019) | ✅ As seis estão dentro dos limites (seção acima), com a ressalva do SEC-41-02 |

**Regras inegociáveis tocadas:**

- **R-02:** o payload é só o contrato (CA-21), e o código novo não abre conexão própria (busca no diff por bibliotecas de rede, `subprocess`, `pickle`, `torch.load` e afins: nada em produção). A única rede é o download dos pesos, citado na superfície.
- **R-03:** a busca no diff por JWT, chave privada, URL com senha, token de bot e `service_role` não achou nada. Os `token` do diff são tokens de teste gerados em tempo de execução ou o nome do header de sessão, e a única URL de banco é local, sem senha, nos relatórios.
- **R-06:** ver CA-17 e CA-18, com a ressalva do SEC-41-01.
- **R-07:** os 26 commits têm trailer. `tests/acceptance/` só em `5325db9` (tester); `ml/src` só em `ml-engineer`; `edge/src` só em `developer`.
- **R-11:** `provisional.py` não chama nem cita função de split, salvo no texto do docstring que declara a proibição.
- **R-13:** identidade única do projeto em autor e committer, e nenhuma menção a empresa no diff nem nas mensagens.
- **R-14:** o importador continua com `--privacy-checked` obrigatório e sem copiar EXIF. Os `.onnx` e as fotos ficam fora do repositório (CA-11, CA-28).

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma. `uv.lock` e os `pyproject.toml` sem mudança, e por isso não rodei auditoria de CVE |

## O que rodei e o que não rodei

**Rodei, em `806e804`, com o extra `train` (torch 2.14.1, CPU):**

- os dois arquivos de aceite, os testes do autor desta SPEC e `ml/tests/test_no_torch.py`, incluindo os *slow*: **328 passed**;
- `ruff check .` e `ruff format --check .`: limpos;
- as reproduções citadas acima e as 17 mutações, sempre com dados sintéticos, em diretórios temporários já apagados e sobre uma cópia do código, sem editar nada no repositório. Os scripts rodaram pela entrada padrão, sem arquivo, porque o `guard_paths` deste papel bloqueia o `Write` fora do projeto.

**Não rodei nem verifiquei:**

- a suíte inteira, com ou sem torch: vale o test-report, e o CI do PR ainda confirma;
- o treino real, sem `--smoke`, que continua sem medição até o passo 6 do §4.8;
- o CA-22 manual, e portanto o fluxo real até a nuvem e o painel com `simulated`;
- a captura pela página no diretório renomeado: no SEC-41-01, medi o `model_version` no `OnnxInferencer` real e me apoio no CA-18 para o `source=live`;
- `~/partqc-entrada/` e `~/partqc-provisorio/`, que não abri.

## Pendências

**Para o humano:**

1. Decidir o SEC-41-01: aceitar e registrar o limite ou pedir uma SPEC de manutenção. Convém decidir antes do CA-22.
2. Confirmar ou vetar a resposta 11 do ADR-024 no PR (SEC-41-02).
3. CA-22 manual, depois do merge: o passo 3 (`(modelo provisório)` em cada resposta) também detecta um diretório renomeado.

**Para o orquestrador:**

4. Pedir ao reviewer a conferência da SPEC_ISSUE-07 (R-09). Sem ela, a coluna "Como verificar" da R-09 não fecha.
5. Seção "Reaprovações sob o ADR-019" no PR, com as seis delegadas, a SPEC_ISSUE-04 como humana e a resposta 11.
6. Na operação do §4.8, seguir o SEC-41-06 antes de chamar o agente, e o `find -type l` do SEC-41-08.

**Para uma manutenção (sem bloquear):** SEC-41-03, 04, 05 e 07.

## SPEC_ISSUE

Nenhum novo. Nenhuma reaprovação está fora dos limites, então não há `SPEC_ISSUE` "exige humano" por este portão.

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
