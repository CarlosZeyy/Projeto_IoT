# SPEC-031: Manutenção do ML (`NaN` na paridade e nas predições, export TorchScript, `ITEM_ID_PATTERN` único e fluxo do Colab)

| Campo | Valor |
|---|---|
| Status | Done |
| Rodada atual | r1 |
| Autor da implementação | ml-engineer (+ developer, só na §4.8) |
| Tags | — |
| Depende de | SPEC-012 (e SPEC-011) |
| Semana alvo | S3 (**antes** do treino real no Colab, CA-28 da SPEC-012) |
| Requisitos cobertos | RNF-07, RNF-08; R-11, R-12 |
| ADRs relevantes | ADR-004, ADR-005, ADR-010, ADR-014 |

> **Reaprovada pelo humano em 2026-10-20**: correção dos SPEC_ISSUE-01 e 02 de `reviews/SPEC-031/r1-dev-report.md` (§3.1, §4.2, §4.8 nova e §6). Classificação ADR-019: SPEC_ISSUE-01 elegível; SPEC_ISSUE-02 exige humano (X-5 e X-7). Ver o Histórico.

## 1. Contexto

Fecha as pendências da "Próxima manutenção do ML" de `docs/plan.md` §3, deixadas pelos portões das SPECs 011 e 012. Nada muda no contrato, na borda, nos artefatos de `docs/architecture.md` §7 nem na regra de decisão. A skill `ml-pipeline` continua valendo inteira.

| Pendência | Origem | Severidade | O que entra aqui |
|---|---|---|---|
| RV-01 | `reviews/SPEC-012/r2-review-report.md` (T-01 do tester) | baixa | `check_parity` recusa valores não finitos; o `max` do Python deixava o `NaN` sumir do `max_abs_diff` (§4.1) |
| RV-03 | `reviews/SPEC-012/r1-review-report.md` (O-01 do tester) | baixa | `Predictions` recusa probabilidades não finitas ou fora de [0, 1] (§4.2) |
| RV-01 | `reviews/SPEC-012/r1-review-report.md` | média | Export pelo exportador TorchScript (`dynamo=False`) com o aviso de depreciação silenciado e o `torch` sem teto (§4.3) |
| RV-02 | `reviews/SPEC-012/r1-review-report.md` | baixa | Nota `no_screw_nut_in_val` registrada como comportamento da SPEC (§4.4) |
| RV-04 | `reviews/SPEC-012/r1-review-report.md` | baixa | O `split_v1` precisa estar na `main` antes do Colab: README e notebook (§4.5) |
| RV-07 | `reviews/SPEC-011/r3-review-report.md` | baixa | `ITEM_ID_PATTERN` duplicado entre `qc_ml.split` e `qc_ml.data` (§4.6) |

O RV-02 da SPEC-011 (`.jpeg`, `.png` e `.heic` sob `raw/`) vai para a SPEC-030, na varredura de privacidade da borda.

**Por que antes do treino real.** Os itens §4.1 a §4.3 e §4.5 protegem o próprio treino real: um modelo que gere `NaN` passaria pela paridade e daria limiares silenciosamente errados; uma quebra do exportador só apareceria depois do treino na GPU; e, sem o `split_v1` na `main`, o pipeline falha no Colab depois da instalação.

## 2. Objetivo

A paridade e os limiares falham alto com `NaN`, o export avisa (e o notebook testa antes do treino) quando o caminho TorchScript mudar, o `torch` do extra `train` fica com teto, e o fluxo do Colab diz que o `split_v1` vem antes.

## 3. Escopo

### 3.1 Dentro

- `ml/src/qc_ml/parity.py`: `check_parity` (§4.1).
- `ml/src/qc_ml/predict.py`: `Predictions.__post_init__` (§4.2).
- `ml/src/qc_ml/export.py`: o tratamento do aviso de depreciação (§4.3, item 2).
- `ml/pyproject.toml`: teto do `torch` no extra `train` (§4.3, item 1), e o `uv.lock` regenerado **só** por `uv lock` (exceção de caminho, §4.7).
- `ml/src/qc_ml/split.py`: importa `ITEM_ID_PATTERN` de `qc_ml.data` (§4.6).
- `ml/README.md` ("Do Colab ao Release") e `ml/notebooks/train_colab.ipynb` (§4.3, item 3, e §4.5).
- Testes do autor em `ml/tests/` (fora de `acceptance/`).
- **Developer (só a §4.8):** `tests/test_dependency_isolation.py`, uma asserção de `test_ml_train_extra_declares_training_stack`, e um adendo no fim de `reviews/SPEC-031/r1-dev-report.md`.
- **Tester:** `ml/tests/acceptance/test_spec_031.py`.
- **Tester, ajuste de aceite antigo** (aplicação explícita da regra "Testes de aceite de SPECs anteriores" de `docs/architecture.md` §10, motivada pela §4.2). Em `ml/tests/acceptance/test_spec_012.py`, só a **montagem das entradas** destes dois testes, sem mudar nenhuma asserção:
  - `test_ca18_review_threshold_targets_10pct`, segundo caso: a confiança de grau passa a ser `min(0.5525 + 0.005·i, 1)` (§4.2, "Efeito nos CAs da SPEC-012");
  - `test_ca17_unusable_threshold_for_recall_90pct`: a probabilidade de `fair` passa a ser montada sem resto negativo de ponto flutuante (por exemplo, `1.0 - (0.55 + p)` ou `max(0.0, 1.0 - 0.55 - p)`), com o mesmo valor matemático `1 − 0,55 − p`.

  Os dois ajustes vão na tabela do test-report, como manda o §10. Nenhuma outra linha desse arquivo muda.

### 3.2 Fora

- Migrar o export para o exportador padrão (`dynamo=True`, com `onnxscript`): não adotado aqui (§7). Entra numa SPEC própria se o teto do `torch` deixar de ser viável.
- Validar a soma das linhas de `Predictions` (= 1): não pedido pelo RV-03.
- A ordem de gravação dos relatórios em `thresholds.run`/`evaluate.run` (observação sem severidade do review r1): sem ação.
- Imprecisões de texto do CA-13 da SPEC-012 (RV-02 de `reviews/SPEC-012/r2-review-report.md`): sem ação, como o reviewer decidiu.
- Fotos com outras extensões em `raw/` → SPEC-030.

## 4. Requisitos detalhados

### 4.1 Paridade com valores não finitos (RV-01 da r2)

- Em `check_parity`, depois de conferir as formas e antes de calcular as diferenças, se alguma saída do ONNX ou alguma referência da fixture tiver valor não finito (`not np.isfinite(...).all()`), o resultado é `ParityResult(ok=False, max_abs_diff=math.inf, argmax_equal=False, sha256_match=<calculado como hoje>, message=...)`, com `message` contendo `non-finite values`.
- O `max` do Python sobre as diferenças é trocado por uma forma que não descarta `NaN` (por exemplo, `np.fmax` ou comparação explícita). Com valores finitos, o resultado é o mesmo de hoje (os CA-12 e CA-13 da SPEC-012 continuam valendo sem ajuste).
- A CLI `python -m qc_ml.parity` sai com 2 e imprime a mensagem no stderr, como em qualquer falha de paridade.

### 4.2 `Predictions` valida as probabilidades (RV-03 da r1)

- `Predictions.__post_init__`, depois das conferências de forma de hoje, levanta `ValueError` se `type_probs` ou `grade_probs` tiver algum valor não finito ou fora de `[0, 1]`. A mensagem cita o nome do campo (`type_probs` ou `grade_probs`) e não cita valores nem caminhos de imagem.
- Arrays vazios (`n = 0`) continuam aceitos.
- O caminho real (`OnnxModel.predict`) não muda: softmax e CORN dão valores em `[0, 1]` também em float32 (a divisão e o produto arredondam de forma monótona).
- **Efeito nos CAs da SPEC-012** (SPEC_ISSUE-01 de `reviews/SPEC-031/r1-dev-report.md`). A validação vale também para as entradas sintéticas dos testes de limiar. Por isso, valem estas leituras, que complementam a SPEC-012 sem alterar o arquivo dela (`Done`):
  - **CA-18, segundo caso:** a confiança de grau é `min(0.5525 + 0.005·i, 1)`. Sem o `min`, as imagens com i ≥ 90 teriam confiança de 1,0025 a 1,0475 e probabilidades negativas, que esta seção recusa. O resultado esperado não muda: continuam 10 imagens abaixo de 0,60 (i = 0 a 9, de 0,5525 a 0,5975), `grade_review_threshold = 0.60` e sem `review_adjusted`.
  - **CA-17:** o texto não muda (com `p_unusable = 0.45`, `fair` vale exatamente 0). Só a montagem do teste precisa evitar o resto `-5.55e-17` do ponto flutuante, como diz a §3.1.

### 4.3 Export TorchScript (RV-01 da r1)

1. **Teto do `torch`:** no extra `train` de `ml/pyproject.toml`, `"torch"` vira `"torch<2.15"`. A versão travada no `uv.lock` continua a de hoje (2.14.1), e nenhuma outra versão resolvida muda. No Colab, o `pip install -e "ml[train]"` respeita o teto.
2. **Aviso visível:** em `export_onnx`, o `warnings.simplefilter("ignore", DeprecationWarning)` sai. Os avisos emitidos dentro do `torch.onnx.export` são capturados (`warnings.catch_warnings(record=True)`) e cada `DeprecationWarning` (ou subclasse) vira um registro `WARNING` no logger `qc_ml.export`, com o texto `torch.onnx.export: <mensagem do aviso>`. Os avisos capturados não são reemitidos, e o export continua com `dynamo=False`.
3. **Checagem antes do treino:** no notebook, uma célula de código **antes** da célula que roda `python -m qc_ml.pipeline` executa `!python ml/scripts/make_tiny_fixture.py --out /tmp/export_check`. Um erro do exportador aparece aí, antes do treino na GPU. A célula de markdown anterior a ela explica isso em uma frase. As regras do CA-26 da SPEC-012 continuam (sem saídas salvas, sem `def`/`class`, sem token).

### 4.4 Nota `no_screw_nut_in_val` (RV-02 da r1)

Texto vigente, que complementa a SPEC-012 §4.6 (`type_threshold`): **sem nenhuma imagem `screw`/`nut` na validação**, `type_threshold = 0,50` e a nota é `no_screw_nut_in_val`, e não `type_target_not_met`. É o comportamento atual do código (`thresholds.py:86-88`); esta SPEC só o fixa num CA. O caso não acontece com um split válido.

### 4.5 `split_v1` antes do Colab (RV-04 da r1)

- `ml/README.md`, seção "Do Colab ao Release": um passo 0, antes do passo 1, dizendo que o `split_v1` é gerado localmente com `python -m qc_ml.split` (com os dados reais da S3), que `split_v1.csv`, `split_v1.sha256` e `split_v1.json` entram na `main` por PR, e que só depois se abre o Colab.
- Notebook: a célula de markdown da seção que diz que o split "vem do repositório" ganha a mesma condição, com `split_v1` e `python -m qc_ml.split` citados.

### 4.6 `ITEM_ID_PATTERN` único (RV-07 da SPEC-011)

`qc_ml.split` deixa de definir a própria regex e usa a de `qc_ml.data` (`from qc_ml.data import ITEM_ID_PATTERN`, ou pelo módulo). O nome `qc_ml.split.ITEM_ID_PATTERN` pode continuar existindo como o mesmo objeto. O comportamento do split não muda.

### 4.7 Exceção de caminho: `uv.lock`

O hook da SPEC-001 limita o ml-engineer a `ml/**` nas ferramentas de edição, e o `uv.lock` fica na raiz. **Somente nesta SPEC**, e só para o item 1 da §4.3:

- o ml-engineer regenera o `uv.lock` rodando `uv lock` pelo `Bash`, sem editar o arquivo à mão;
- o diff do `uv.lock` muda só a metadata do `qc-ml` (o `requires-dist` do `torch` no extra `train`), sem nenhuma versão resolvida nova; o dev-report traz o comando e o `git diff --stat uv.lock`;
- o commit leva `Agent: ml-engineer` e `Refs: SPEC-031`. O reviewer confere o diff.

### 4.8 Teste de autor da SPEC-001 com o teto do `torch` (developer)

`tests/test_dependency_isolation.py::test_ml_train_extra_declares_training_stack` é teste de autor do developer (SPEC-001 §4.5, CA-08) e compara as strings do extra `train` com igualdade exata (linha 73). Com o `"torch<2.15"` da §4.3, item 1, ele falha (SPEC_ISSUE-02 de `reviews/SPEC-031/r1-dev-report.md`). O arquivo é de outro papel e fica fora de `ml/**`, então o ml-engineer não o altera (R-07). Quem ajusta é o **developer**, numa passada só para isto:

- Na linha 73, a comparação passa a ser feita pelos **nomes** dos requisitos, sem o especificador de versão, o marcador e os extras. O nome é o prefixo de cada string que casa `[A-Za-z0-9._-]+`, em minúsculas (pode entrar o `import re`). A igualdade continua **exata**: o conjunto de nomes é `{"torch", "torchvision", "timm", "onnx", "coral-pytorch"}`, nem mais nem menos. Não se usa `packaging`, que é só dependência transitiva.
- Nenhuma outra linha do arquivo muda, nem as asserções sobre o `uv.lock`, nem outro arquivo de código ou de teste.
- O commit leva `Agent: developer` e `Refs: SPEC-031` e contém só esse arquivo. Num commit separado, também com `Agent: developer`, o developer acrescenta no fim de `reviews/SPEC-031/r1-dev-report.md` a seção `## Adendo do developer (§4.8)`, com o sha do commit e o resultado de `uv run pytest -q tests/test_dependency_isolation.py`. O resto do relatório do ml-engineer não muda.
- A passada vem **antes** do tester, na mesma rodada (r1). O reviewer confere no diff que a intenção do CA-08 da SPEC-001 continua verificada: os mesmos cinco nomes, com igualdade.

## 5. Critérios de aceite

- **CA-01 (RV-01 da r2)** — *Dado* uma cópia da fixture `ml/tests/fixtures/tiny_model/` com `type_probs[0, j] = nan`, em que `j` é o argmax da linha 0, *quando* `check_parity` roda, *então* `ok is False`, `max_abs_diff == math.inf` e `"non-finite values" in message`; e `python -m qc_ml.parity --model-dir <cópia>` sai com 2.
- **CA-02 (RV-01 da r2)** — *Dado* uma cópia da fixture com `inputs[0] = nan` (a entrada inteira da amostra 0) e `type_probs[0, :] = grade_probs[0, :] = nan`, *quando* `check_parity` roda, *então* `ok is False` e `"non-finite values" in message`. *Dado* a fixture original, *então* `ok is True` e `max_abs_diff < 1e-4` (como no CA-12 da SPEC-012).
- **CA-03 (RV-03 da r1)** — *Dado* `Predictions` com 2 imagens válidas e, em casos separados, `type_probs[0, 0] = nan`, `grade_probs[1, 2] = inf`, `type_probs[0, 1] = -0.01` e `grade_probs[0, 4] = 1.01`, *quando* é construído, *então* levanta `ValueError`, e a mensagem contém `type_probs` (nos casos de `type_probs`) ou `grade_probs` (nos outros). *Dado* valores em `[0, 1]`, inclusive `0.0` e `1.0` exatos, ou `n = 0`, *então* constrói sem erro.
- **CA-04 (RV-01 da r1, R-12)** — *Dado* `ml/pyproject.toml` e `uv.lock` lidos com `tomllib`, *então* o extra `train` contém exatamente `"torch<2.15"`; no `uv.lock`, o pacote `torch` tem a versão `2.14.1`, e o `requires-dist` do `qc-ml` tem o `torch` com o especificador `<2.15` e o marcador do extra `train`. E o `qc-api` e o `qc-dashboard` continuam sem `torch` nas dependências resolvidas (o teste de CI da R-12 passa).
- **CA-05 (RV-01 da r1)** — *Dado* `ml/src/qc_ml/export.py` analisado com `ast`, *então* não há chamada `simplefilter` com `"ignore"`. *Dado* torch instalado (`importorskip("torch")`, marcador `slow`) e `torch.onnx.export` envolvido por uma função que chama o original e depois `warnings.warn("<marcador>", DeprecationWarning)`, *quando* `export_onnx` exporta a rede mínima da fixture com `warnings.simplefilter("error")` ativo no teste, *então* não levanta, e o `caplog` tem um registro `WARNING` do logger `qc_ml.export` com `torch.onnx.export: <marcador>`.
- **CA-06 (RV-01 da r1, RV-04 da r1, R-03)** — *Dado* `ml/notebooks/train_colab.ipynb` lido como JSON, *então*: existe uma célula de código com `make_tiny_fixture.py --out` cujo índice é menor que o da célula com `python -m qc_ml.pipeline`; alguma célula de markdown anterior à do pipeline contém `split_v1` e `python -m qc_ml.split`; e continuam valendo as condições do CA-26 da SPEC-012 (toda célula de código com `outputs = []` e `execution_count = null`, nenhuma com `def ` ou `class `, nenhuma casando `ghp_|github_pat_|token\s*=\s*["']`).
- **CA-07 (RV-04 da r1)** — *Dado* `ml/README.md`, *quando* se isola o trecho da seção cujo título contém `Do Colab ao Release` até o próximo título de nível igual ou superior, *então* o trecho contém `python -m qc_ml.split` e `split_v1`, e a primeira ocorrência de `python -m qc_ml.split` vem antes da primeira linha de lista numerada com `1.`.
- **CA-08 (RV-02 da r1)** — *Dado* `Predictions` de validação só com imagens `other` (nenhum `screw`/`nut`), *quando* `choose_thresholds` roda, *então* `decision["type_threshold"] == 0.5`, e as notas do relatório contêm `no_screw_nut_in_val` e não contêm `type_target_not_met`.
- **CA-09 (RV-07 da SPEC-011)** — *Dado* os módulos importados, *então* `qc_ml.split.ITEM_ID_PATTERN is qc_ml.data.ITEM_ID_PATTERN`; e `ml/src/qc_ml/split.py`, analisado com `ast`, não tem chamada `re.compile` cujo argumento contenha `[SNOT]`.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Paridade com `NaN` (referência, saída, os dois lados); `Predictions` (tabela de valores); aviso do export (com torch, `slow`); notas dos limiares | `ml/tests/` |
| Aceite (tester) | Um por CA; o CA-05 tem a parte estática no CI e a parte com torch marcada `slow` | `ml/tests/acceptance/test_spec_031.py` |

- Sem internet e sem dados reais: cópias da fixture em `tmp_path` e `make_synthetic_dataset`.
- A parte `slow` do CA-05 roda localmente com `uv sync --all-packages --extra train`, registrada no test-report, e o `.venv` volta ao estado do CI depois (como na SPEC-012). Com o extra instalado, os 3 testes de `edge/tests/test_publisher_real_api.py` podem falhar até o merge da SPEC-030 (§4.3 dela); rode só `ml/tests` nesse ambiente.
- **Rodada r1, depois dos SPEC_ISSUE-01 e 02:** ordem developer (§4.8) → tester → reviewer. O tester escreve o `test_spec_031.py`, faz os dois ajustes de `test_spec_012.py` listados na §3.1 (tabela do §10 no test-report) e roda a suíte inteira sem torch. As 3 falhas citadas no dev-report r1 (`test_dependency_isolation.py`, CA-17 e CA-18 da SPEC-012) devem passar.

## 7. Riscos e notas para o implementador

- **Por que o teto, e não o `onnxscript`:** o teto não acrescenta dependência nem muda o `model.onnx` gerado, então a fixture `tiny_model` (CA-12 a CA-14 da SPEC-012) continua igual. Migrar para `dynamo=True` muda o grafo exportado, exige regerar a fixture e acrescenta o `onnxscript` ao lock. Pela documentação de `torch.onnx` da versão travada (<https://docs.pytorch.org/docs/2.14/onnx.html>, consultada pelo architect em 2026-10-19), o exportador `dynamo=True` é "the recommended and default way to export models to ONNX" desde a 2.9, e o `dynamic_axes` que o export usa está marcado como "Deprecated: Prefer specifying dynamic_shapes when dynamo=True"; a página não dá versão de remoção do caminho `dynamo=False`. Por isso o teto, e não a espera.
- **Colab e o teto:** se o Colab vier com um `torch` mais novo que 2.14, o `pip install -e "ml[train]"` baixa o 2.14.x do PyPI (alguns minutos a mais). É o comportamento desejado: o treino roda com a versão em que a paridade foi validada. Registre no README, junto do passo 0, que esse download é esperado.
- **`np.fmax`** ignora o `NaN` (devolve o outro valor). Ele só é seguro **depois** da checagem de finitude da §4.1; a checagem é o que torna o resultado `ok=False`.
- A §4.2 pode fazer o `evaluate`/`thresholds` falharem com `ValueError` num modelo quebrado. É o objetivo: falhar alto, antes de gravar o `decision.json` ou o `metrics.json`.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS); a parte `slow` do CA-05 rodada localmente com torch e registrada
- [ ] review-report APPROVED
- [ ] CI verde (sem torch); `ruff` limpo
- [ ] `ml/README.md` e o notebook atualizados
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-19 | SPEC criada (`Draft`). Decisões do architect: (a) teto `torch<2.15` no extra `train`, em vez de acrescentar o `onnxscript` e migrar para o exportador padrão (§7); (b) aviso de depreciação registrado no log em vez de silenciado, e checagem do export no notebook antes do treino (sugestões (b) e (c) do RV-01); (c) a nota `no_screw_nut_in_val` fica como comportamento da SPEC (opção "registrar" do RV-02), sem mudar o código; (d) exceção de caminho para o `uv.lock`, só por `uv lock` (§4.7). | RV-01 e RV-02 de `reviews/SPEC-012/r2-review-report.md`; RV-01 a RV-04 de `reviews/SPEC-012/r1-review-report.md`; RV-07 de `reviews/SPEC-011/r3-review-report.md` | Orquestrador, a pedido do humano |
| 2026-10-19 | Aprovada pelo humano (`Draft` → `Ready`), com as respostas recomendadas às perguntas do architect (comentário do PR #36). Aceitos o teto `torch<2.15` (no lugar do `onnxscript`) e a exceção de caminho do `uv.lock` regenerado só por `uv lock` (§4.7). | Aprovação humana | Humano (Carlos) |
| 2026-10-20 | **Correção do SPEC_ISSUE-01 (r1): efeito da §4.2 nos CAs 17 e 18 da SPEC-012.** **Texto antigo:** a SPEC não tratava do efeito; o CA-18 da SPEC-012 prescreve, no segundo caso, "confiança de grau `0.5525 + 0.005·i`". **Texto novo:** (a) §4.2, item "Efeito nos CAs da SPEC-012": o segundo caso do CA-18 é lido como `min(0.5525 + 0.005·i, 1)`, com o mesmo resultado esperado (10 imagens abaixo de 0,60, `grade_review_threshold = 0.60`, sem `review_adjusted`); o texto do CA-17 não muda; (b) §3.1: o tester ajusta, em `ml/tests/acceptance/test_spec_012.py`, só a montagem das entradas desses dois testes, como aplicação explícita da regra "Testes de aceite de SPECs anteriores" de `docs/architecture.md` §10. **Decisão:** a correção fica na SPEC-031, e não no CA-18 da SPEC-012 (`Done`), porque é a §4.2 desta SPEC que invalida as entradas, a intenção do CA-18 não muda, e o §10 já prevê o ajuste pelo tester da SPEC nova (precedente de "texto vigente que complementa a SPEC-012": §4.4). **Evidência:** dev-report r1, SPEC_ISSUE-01 e nota do CA-17 (`ValueError: grade_probs has values outside [0, 1]` para i ≥ 90; `1.0 - 0.55 - 0.45 = -5.55e-17`). Classificação ADR-019 do SPEC_ISSUE-01: elegível (E-1: SPEC_ISSUE-01 do dev-report r1; E-2: só este arquivo e `docs/plan.md`; E-3: aprovada, `Blocked` por este SPEC_ISSUE; E-4 tipo 1, texto que esclarece o requisito sem mudar o comportamento pedido; E-5; nenhuma exclusão: nenhum CA da SPEC-031 muda, e nenhum valor prometido muda). | SPEC_ISSUE-01 de `reviews/SPEC-031/r1-dev-report.md` | Orquestrador |
| 2026-10-20 | **Correção do SPEC_ISSUE-02 (r1): teste de autor da SPEC-001 quebrado pelo teto do `torch`.** **Texto antigo:** autor só o ml-engineer; o §3.1 e a §4.7 não cobriam `tests/test_dependency_isolation.py`. **Texto novo:** (a) cabeçalho: "ml-engineer (+ developer, só na §4.8)"; (b) §3.1: item do developer; (c) §4.8 nova: o developer troca a igualdade exata das strings do extra `train` (linha 73) por igualdade exata dos **nomes**, sem o especificador, com um commit só desse arquivo e um adendo no dev-report r1, antes do tester; (d) §6: ordem da rodada. **Decisão:** delegar ao developer, e não estender a §4.7 ao ml-engineer, porque o arquivo é teste de autor do developer (commit `702d915`, `Agent: developer`), fica fora de `ml/**` e do hook do ml-engineer, e editar teste de outro papel fere a separação da R-07. A igualdade continua exata nos nomes, então a intenção do CA-08 da SPEC-001 não muda e a SPEC-001 (`Done`) não é alterada. Classificação ADR-019 do SPEC_ISSUE-02: exige humano (X-5: acrescenta um papel autor e um arquivo fora do escopo da §3.1; X-7: o teste alterado faz parte da verificação da R-12, SPEC-001 §4.5). Como uma das duas correções exige humano, a SPEC fica marcada "Aguardando reaprovação humana" e o status continua `Blocked` (r1) até a reaprovação. | SPEC_ISSUE-02 de `reviews/SPEC-031/r1-dev-report.md` | Orquestrador |
| 2026-10-20 | Correções dos SPEC_ISSUE-01 e 02 reaprovadas pelo humano (o 01 era elegível pelo ADR-019, mas foi aprovado junto com o 02, que exige humano); `Blocked` → `In Dev`, retomada na r1 com a passada do developer da §4.8. | Fluxo do loop (§4 da skill `features`) | Humano (Carlos) |
