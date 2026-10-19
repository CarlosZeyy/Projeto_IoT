# SPEC-012 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-012](../../docs/specs/SPEC-012-ml-treino-export.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `origin/main...f08273d` (45 arquivos, +6941/−14) |
| Test report | [r1-test-report.md](r1-test-report.md) (PASS, sem bugs) |
| **Veredicto** | **APPROVED** |

Não há achado bloqueante nem alto. Há 1 achado médio e 3 baixos, e nenhum deles bloqueia.

A implementação segue a SPEC requisito por requisito. Conferi o R-11 no código, e não só pelos testes:
- só o `evaluate` pede o teste;
- os limiares só aceitam `Predictions` de `val`;
- o melhor checkpoint e o early stopping usam só o QWK de validação.

Os 27 CAs automatizáveis têm teste de aceite que os exercita de fato. O CA-28 é manual e fica com a dupla.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | média | `ml/src/qc_ml/export.py:77-89`; `ml/pyproject.toml:19` | **O export depende do exportador TorchScript, que está depreciado, e o aviso de depreciação foi silenciado.** O `dynamo=False` evita o `onnxscript`, que não está no `uv.lock`, e a escolha está registrada no dev-report (decisão 15). Hoje ela funciona: rodei os *slow* com torch 2.14.1, e a paridade do `mobilenetv3_small_050` e a do CORN passam. O risco é futuro, e há três agravantes. (1) O extra `train` não fixa versão (`"torch"`), e no Colab o `pip` ignora o `uv.lock`. (2) O `warnings.simplefilter("ignore", DeprecationWarning)` esconde o único sinal de que o caminho vai acabar. (3) Uma quebra só aparece **depois** do treino na GPU. O impacto é limitado: a paridade acusa uma saída errada, e `--resume` com o treino já concluído (ou `python -m qc_ml.export`) reexporta a partir do `best.pt` no Drive sem treinar de novo. | Não justifica rodada nova. Numa SPEC futura, ou na próxima mudança de dependências: (a) acrescentar `onnxscript` ao extra `train` (com o `uv.lock`, o que exige o humano ou o hook ampliado) e migrar para o exportador padrão, ou fixar um teto para o `torch` no extra; (b) trocar o `ignore` por um `logger.warning` com o texto do aviso; (c) no notebook, rodar `python ml/scripts/make_tiny_fixture.py --out /tmp/export_check` antes do pipeline, para que uma incompatibilidade do export apareça antes do treino. |
| RV-02 | baixa | `ml/src/qc_ml/thresholds.py:86-88` | **Nota fora da SPEC.** Com a validação sem nenhum `screw`/`nut`, o `type_threshold` sai 0,50 com a nota `no_screw_nut_in_val`. A §4.6 diz "se nenhum [t passa], 0,50 e nota `type_target_not_met`". O valor bate, e a nota nova está no dev-report (decisão 5). Mesmo assim, é um código que nenhum consumidor espera. O caso não acontece com um split válido, que sempre tem parafusos e porcas na validação. | Registrar a nota no Histórico da SPEC (mudança só de texto), ou emitir também `type_target_not_met` nesse caso. |
| RV-03 | baixa | `ml/src/qc_ml/predict.py:55-78`; `ml/src/qc_ml/thresholds.py:78` | **`Predictions` não valida as probabilidades.** É a O-01 do tester. Com `NaN`, `type_threshold` sai 0,85 sem aviso, porque `NaN < t` é falso. Valores negativos ou linhas com soma diferente de 1 também passam. O caminho real (`OnnxModel.predict`) só produz entradas válidas, mas a paridade cobre só as 8 entradas sintéticas. Um modelo que gere `NaN` em fotos reais daria limiares e métricas silenciosamente errados. | Em `Predictions.__post_init__`, recusar valores não finitos ou fora de [0, 1] (`ValueError`). Isso não muda nenhum CA. |
| RV-04 | baixa | `ml/notebooks/train_colab.ipynb` (célula markdown da seção 5); `ml/README.md:91` | **Falta o pré-requisito do split no fluxo do Colab.** O notebook diz que o `ml/splits/split_v1.csv` "vem do repositório", mas hoje `ml/splits/` não existe na `main`. Nem o notebook nem o passo 1 de "Do Colab ao Release" dizem que a dupla precisa gerar o `split_v1` (`python -m qc_ml.split`, SPEC-011) e fazer o merge dele **antes** de abrir o Colab. Sem ele, o pipeline falha logo no início do treino, sem dano, mas depois da instalação e da validação. | Acrescentar um passo 0 ao README e uma linha ao markdown do notebook: gerar o split localmente, commitar `split_v1.csv`/`.sha256`/`.json` por PR e só então treinar. |

## Pontos que o orquestrador pediu para conferir

- **R-11.**
  - O `"test"` só aparece em `evaluate.py:432` (`--latency-only`, só para cronometrar) e em `evaluate.py:465` (uma vez por avaliação, depois de `_check_model_dir` exigir o `decision.json`).
  - `train.py:441-442` pede só `train`/`val`, `thresholds.py:234` só `val`, e o export usa entradas sintéticas.
  - Todos chamam `split.rows_for` pelo atributo do módulo, e nenhum faz `from qc_ml.split import rows_for`. Por isso o espião do CA-20 enxerga todas as chamadas.
  - O `evaluate` pede `train` e `val` antes do teste, só para os `counts`, que a §4.7 exige "por split". Nada é escolhido com eles, e o CA-20 só restringe o `"test"`.
  - `choose_thresholds` recusa outro split antes de qualquer cálculo, com `SplitIntegrityError`. O melhor checkpoint e o `EarlyStopper` usam o QWK da validação.
  - Os valores do `metrics.json` são brutos e não são arredondados. Uma métrica indefinida vira `null` com aviso.
- **Artefatos versionados.**
  - A fixture tem 852.546 bytes (`model.onnx` 2.536 + `parity_fixture.npz` 849.566 + 4 arquivos de texto), abaixo de 1 MB.
  - `git check-ignore --no-index` não ignora nenhum dos 6 arquivos: a regra `ml/models/**/*.onnx` não alcança `ml/tests/fixtures/`, e a negação da §4.10 não foi necessária.
  - `ml/reports/**/*.png` já tem exceção no `.gitignore`, e `ml/checkpoints/` e os `.pt`/`.pth` de `ml/models/` continuam ignorados.
  - O `.onnx` da fixture é uma rede mínima, sem pesos de modelo real. A `architecture.md` §7 diz que "os JSONs e a fixture vão" para o Git.
  - As 8 entradas do `npz` vêm de `make_synthetic_dataset(seed=0)`, sem foto real (R-02, R-14).
  - Rodei `python -m qc_ml.parity` na fixture: `max_abs_diff = 1,19e-07`, com o `model_sha256` do `npz` igual ao `model.sha256`.
  - O tamanho é razoável: o `npz` comprime 4,8 MB de `float32` para 0,85 MB, e a §7 da SPEC já prevê esse custo por versão.
- **Notebook.**
  - 10 células de código, todas com `outputs = []` e `execution_count = null`.
  - Nenhum `def` ou `class`, e nenhum token literal.
  - O token vem de `userdata.get('GITHUB_RO_TOKEN')` e vai ao `git clone` só pelo ambiente do subprocesso (`GIT_CONFIG_*`, cabeçalho `Authorization`). Não aparece na URL, no `.git/config` nem no `os.environ` do kernel, e as variáveis são apagadas com `del` logo depois.
  - Segue os 7 passos da §4.8: Python 3.12 e GPU, Drive, clone, `pip install -e`, dataset, `validate` e pipeline, cópia para o Drive.
  - O envio dos dados ao Colab pelo Drive pessoal está coberto pelo ADR-004, e o markdown cita a checagem de privacidade da `dataset-protocol.md` §8 (R-14).
- **`dynamo=False`:** ver o RV-01.
- **Módulos extras** (`config`, `artifacts`, `plots`, `steps`).
  - Todos são internos e sem torch, e não acrescentam comportamento fora da SPEC.
  - `config.py` separa o `TrainConfig` porque `thresholds`, `evaluate` e `pipeline` leem o mesmo JSON no CI sem torch. `qc_ml.train` reexporta `TrainConfig`, `ConfigError` e `load_config`, e assim a interface da §4.2 continua valendo.
  - `artifacts.py` centraliza os nomes de arquivo e o formato do `model.sha256`. O `read_verified_model` lê os bytes uma vez e entrega ao onnxruntime os mesmos bytes cujo hash conferiu, sem janela entre a checagem e o uso.
  - `plots.py` desenha os PNGs com Pillow (sem matplotlib), com os rótulos PT-BR de `qc_contracts`.
  - `steps.py` reúne os códigos de saída das CLIs.
  - As CLIs avulsas `python -m qc_ml.train|export|parity` também ficam dentro do escopo: são os passos do pipeline da §4.8 e estão no README.
  - Está tudo no dev-report (decisão 1), e não precisa de `SPEC_ISSUE`.
- **Regra de exibição** (`architecture.md` §7), em `report.py:39-122`.
  - O valor é formatado de `Decimal(repr(v))` com 4 casas e vírgula.
  - `ROUND_CEILING` vale exatamente para as 5 métricas "menor é melhor" da §7, e `ROUND_FLOOR` para as demais.
  - Nos ICs, `low` é cortado para baixo e `high` arredondado para cima. `latency_runs` sai sem casas.
  - O status compara o valor bruto com a meta (`Target.status`).
  - O CA-25 cobre os três casos (`0,9312`, `0,7500`, `120,0001`), e o teste extra cobre o `0,1235` do `grade_mae` e o IC alargado.
- **R-12.**
  - `api/`, `dashboard/` e `edge/` não aparecem no diff, e `uv.lock` e `pyproject.toml` não mudaram.
  - O `.venv` do CI não tem torch, e a suíte inteira passa sem ele.
  - Os 6 módulos do CA-27 e os auxiliares importam com `sys.modules["torch"] = None`. Nenhum importa sklearn ou scipy: QWK, matrizes e bootstrap são feitos com numpy. O `test_qwk_matches_sklearn` compara o QWK com o `cohen_kappa_score` em 50 casos.
- **R-14.** Nenhum dado de `ml/data/` é lido nos testes, e a paridade usa imagens sintéticas. As PNGs e os JSONs de relatório não contêm imagem.
- **R-07.** Conferi os commits com `git log --format='%h %(trailers:key=Agent)'` e `git show --stat`:

  | Commit | `Agent` | Arquivos |
  |---|---|---|
  | `2957070`, `35d14aa`, `4d06cf0` | `ml-engineer` | `ml/src/`, `ml/scripts/`, `ml/tests/` fora de `acceptance/`, fixture, config, notebook, CHANGELOG, README e dev-report |
  | `22a35e5` | `tester` | só `ml/tests/acceptance/test_spec_012.py` e o test-report |
  | `7f56c90`, `4858b58`, `f08273d` | `orchestrator` | só status em `docs/plan.md` e nas SPECs |

  Todos os commits têm `Refs: SPEC-012` e `Agent:`, e a identidade é a CarlosZeyy (R-13). Nenhum arquivo de aceite de SPEC anterior foi alterado. O `ml/tests/test_no_torch.py` que mudou é teste do autor, não de aceite.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Todos os requisitos de §4.1 a §4.10 estão implementados. Nenhum CA foi alterado. A rastreabilidade CA → arquivo → teste está no dev-report. As decisões fora do texto da SPEC estão listadas no dev-report e são detalhes de implementação. A única que muda uma saída visível é a nota do RV-02. |
| 2. Regras inegociáveis | ✅ | R-01: nenhuma dependência nova. R-02 e R-14: a fixture é sintética, e o Colab e o Drive estão cobertos pelo ADR-004. R-03: varri o diff por `ghp_`, `github_pat_`, `eyJ`, `password=`, `secret=` e URLs com credencial, e só aparecem as regex dos próprios testes. R-04: o contrato não mudou. R-05 e R-06: N/A. R-07, R-11, R-12 e R-13: ver acima. |
| 3. Corretude | ✅ | Os casos de borda estão tratados: split vazio vira `EvaluationError` ou `TrainError`; métrica indefinida vira `null`; reamostragem indefinida fica fora do IC, com aviso; `model.sha256` divergente ou mal formado é recusado; `decision.json` sem as 3 chaves ou fora de [0, 1] também; grau sem imagem de treino dá `TrainError`; batch sem grau dá loss finita. As datas são UTC (`datetime.now(UTC)`). Não há `except: pass`: os `except Exception` das CLIs relatam o erro e saem com 2, e o erro inesperado vai ao log com traceback. Os checkpoints são gravados de forma atômica e lidos com `weights_only=True`. A regra de decisão bate com a `qc_edge.decision` em 1.000 vetores. Validação de entrada: RV-03. |
| 4. Testes | ✅ | O test-report é PASS e cobre os CA-01 a CA-27. Os testes não são tautológicos: o CA-22 reconta a matriz pelo CSV, o CA-17 e o CA-18 recalculam com `apply_decision`, e o CA-20 espiona o `rows_for` com o módulo chamador e a existência do `decision.json`. Não há rede (`pretrained=False`, `HF_HUB_OFFLINE=1`), nenhum teste roda pytest em subprocesso e não há credencial literal. Nenhum ajuste em arquivo de aceite antigo. RNF-09 não se aplica a `qc_ml`. |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` passam (210 arquivos). As funções públicas têm type hints. O `print` aparece só em `stderr`/`stdout` de CLI, como no `qc_ml.split` da SPEC-011. Não há lógica duplicada de `qc_contracts`/`qc_preprocess`: `is_defective`, os rótulos PT-BR, `MODEL_VERSION_PATTERN`, `PreprocessParams`, `load_image` e `preprocess` são importados. O README traz o fluxo Colab → artefatos → Release (Definição de pronto). |
| 6. Segurança | N/A | A SPEC não tem tag `security`/`deploy`. Mesmo assim, conferi o token do notebook e o `allow_pickle=False` na leitura do `npz`. |

## Verificação independente

- **Suíte completa sem torch:** `CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q` deu **4772 passed, 22 skipped** em 312,86 s, a mesma contagem do test-report. Os skips são os testes com torch, o CA-12 sem modelo local e o CA-16 manual da SPEC-008.
- **Slow com torch:**
  - `uv sync --all-packages --extra train`, depois `uv run pytest -q ml/tests/acceptance/test_spec_012.py ml/tests/test_pipeline_slow.py ml/tests/test_model.py -m slow`: **21 passed** em 68 s;
  - isso inclui CA-07 a CA-10, CA-20 do pipeline, `--resume`, pipeline CORN e falha de paridade;
  - depois, `uv sync --all-packages --locked`, e conferi que `import torch` dá `ModuleNotFoundError`.
- **Paridade da fixture:** `python -m qc_ml.parity --model-dir ml/tests/fixtures/tiny_model` deu `parity ok (max_abs_diff=1.19e-07)`.
- **Árvore de trabalho:** limpa depois das execuções.

## Observações (sem severidade)

- Com o extra `train`, 3 testes de `edge/tests/test_publisher_real_api.py` falham por causa do `httpx2` (via `huggingface-hub`). É um problema do ambiente, anterior a esta SPEC e fora do caminho do CI. O dev-report e o test-report já o registram.
- Em caso de falha no meio, `thresholds.run` grava o `thresholds_report.json` antes do `decision.json`, e `evaluate.run` grava os PNGs antes do `metrics.json`. Nada disso fere a SPEC, porque as pré-condições são checadas antes de qualquer escrita. Uma falha de disco na segunda escrita, porém, deixa um relatório novo ao lado de um `decision.json` ou `metrics.json` antigo.
- As observações O-02 a O-04 do tester seguem a SPEC ao pé da letra e não exigem ação.

## Pontos positivos

- O R-11 está garantido no código, e não só por convenção:
  - `choose_thresholds` e `compute_metrics` recusam o split errado;
  - o `evaluate` exige o `decision.json` antes de tocar o teste;
  - o CA-20 identifica o módulo chamador.
- As taxas dos limiares usam aritmética inteira (`20·count ≤ n`), sem arredondamento de float.
- O QWK é calculado com inteiros até a divisão final.
- `read_verified_model` evita a janela entre a checagem do hash e o uso do modelo.
- O notebook passa o token ao `git` sem expô-lo em URL, configuração ou saída.
- A fixture mínima passa pelo mesmo `ProbabilityWrapper` e `export_onnx` do modelo real. Assim, paridade, limiares e avaliação rodam no CI sem torch.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
