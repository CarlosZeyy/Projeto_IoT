# SPEC-041 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-041](../../docs/specs/SPEC-041-modelo-provisorio-e-piso-do-split.md) |
| Rodada | r1 |
| Autor | ml-engineer (Parte A); o developer acrescenta a Parte B |
| Branch | `spec/SPEC-041-modelo-provisorio` |

## Parte A (ml-engineer)

**Estado: implementada, com um `SPEC_ISSUE` novo e bloqueante (SPEC_ISSUE-06).** Os CAs 07, 08 e 09 não passam como estão escritos, porque `--smoke` com a seed padrão sai com 2 na paridade. Todo o resto da Parte A está pronto e commitado. Registrei e parei, sem escolher a saída.

Commits: `3e35ec6`, `5b95ba6`, `f948e7d`, `f346b38`.

### SPEC_ISSUE resolvidos

Os `SPEC_ISSUE` anteriores foram corrigidos pelo architect e reaprovados, e a implementação segue o texto novo da SPEC (Histórico da SPEC, commits `111d2be` e `35f2c2d`):

| `SPEC_ISSUE` | Como a Parte A ficou |
|---|---|
| 01 | `provisional_report.json` tem as 17 chaves do §4.4; a interseção com `METRIC_KEYS` é `model_version`, `model_sha256` e `manifest_sha256` |
| 02 | `validate` imprime `agent_suggestion_label` na stdout, e `split` na stderr; a linha do manifest inválido do `qc_ml.provisional` usa `print_problems(exc.problems, sys.stderr)` |
| 03 | `other labelers` soma as linhas mantidas do manifest e as de `labels_overrides.csv` de imagem não excluída, lidas com `parse_csv` |
| 04 | É da Parte B (`qc_edge.importer`), sem efeito aqui |
| 05 | O `export` continua usando o padrão só no dataset sintético da paridade, sem mudança |

### SPEC_ISSUE novo

#### SPEC_ISSUE-06 (bloqueante): o CA-07 não passa com a seed padrão, porque o modelo de `--smoke` não atinge o gap da fixture de paridade

- **O que a SPEC diz:**
  - §4.2: `--smoke` usa `mobilenetv3_small_050`, `pretrained=False`, 1 época, só a fase A (`set_trainable(model, None)`), com `write_model_dir` (com a paridade) como reuso obrigatório, e `--seed 42` como padrão.
  - CA-07: "`python -m qc_ml.provisional --smoke` roda, *então* sai com 0". Os CAs 08 e 09 dependem dele.
- **O que o código diz:** `make_parity_fixture` descarta a entrada cujo gap entre as duas maiores probabilidades é menor que `1e-3` em qualquer cabeça (`MIN_TOP2_GAP`, `ml/src/qc_ml/export.py:65`) e exige 8 entradas (`:187`).
- **Causa, medida:** sem pesos pré-treinados, com o BatchNorm congelado nas estatísticas iniciais, as features ficam quase nulas (média absoluta 0,002 na medição com a seed 42) e a saída é quase constante e uniforme (exemplo: tipo 0,340/0,330/0,330; grau de 0,196 a 0,205). O gap fica em torno de `1e-3`, e o resultado vira sorteio. Com o CA-07 na seed 42: `only <n> synthetic inputs have a top-2 gap >= 0.001 in both heads; 8 are needed`, saída 2.
- **Medição** no dataset do CA-07 (44 imagens), torch 2.14.1 em CPU, entradas utilizáveis de 88 (precisa de 8). É medição de uma rede de teste em dados sintéticos, não métrica de modelo:

| Seed | Como a SPEC pede (gap ≥ `1e-3`) | Mesma rede, com gap ≥ `2e-4` | BatchNorm em modo de treino só no smoke (gap ≥ `1e-3`) |
|---|---|---|---|
| 42 (padrão) | **1** | 88 | **0** |
| 0 | 88 | 88 | 88 |
| 1 | 79 | 87 | 88 |
| 2 | **0** | 88 | 88 |
| 3 | 88 | 88 | 88 |
| 7 | 88 | 88 | 88 |

  Com 11 imagens (`external_items_per_stratum=1`), as seeds 42 e 0 também deram 0 entradas.
- **Opções para o architect:**
  - (a) **Recomendada:** parâmetro opcional `min_top2_gap` em `write_model_dir` e `make_parity_fixture`, com o padrão `1e-3`, e só o `--smoke` passa `2e-4` (o dobro da tolerância de paridade, `1e-4`). O caminho sem `--smoke` e o oficial não mudam. Exige acrescentar `ml/src/qc_ml/export.py` ao §3.1. A medição acima só contou entradas: ainda não rodei a paridade com esse gap.
  - (b) Os CAs 07 a 09 passam a usar uma seed fixa (`--smoke --seed 0`). Não muda código, mas o teste passa por sorte da seed e pode quebrar ao atualizar o torch.
  - Não serve pôr o BatchNorm em modo de treino no smoke: a seed 42 continua falhando (tabela).
  - Não usei nenhuma saída que acerte a seed 42 por acaso, como mudar a ordem dos sorteios.
- **Fora do smoke:** o treino real usa pesos do ImageNet, e a expectativa é de um gap bem maior, mas isso **não foi medido** (sem treino real nesta tarefa). Se falhar, o `qc_ml.provisional` sai com 2 e apaga o diretório do modelo, sem gravar um modelo ruim.

### Resumo

- `ml/src/qc_ml/provisional.py`: a CLI do §4.2, as recusas na ordem do §4.3 e o relatório do §4.4, sem chamar `load_split`, `rows_for`, `make_split`, `thresholds` ou `evaluate`.
- `ml/src/qc_ml/config.py`: `is_provisional_version` e a recusa no `TrainConfig`. `ml/src/qc_ml/report.py`: a recusa em `changelog` e `release-notes`.
- `ml/src/qc_ml/split.py`: `floor_problems` e `--allow-below-floor`. `make_split` não muda.
- `ml/src/qc_ml/data.py`: `AGENT_SUGGESTION_LABELER` e `allow_agent_suggestion`. `ml/src/qc_ml/synthetic.py`: `items_per_stratum=0` com externas e `labeler`.
- `ml/README.md`: o procedimento do §4.8, o piso e as recusas.

Sem treino real, sem operação sobre `~/partqc-entrada/`, sem `metrics.json` de modelo.

### Rastreabilidade

| CA | Arquivo(s) | Teste do autor | Situação |
|---|---|---|---|
| 01, 02, 03, 04 | `split.py` | `test_split_floor.py::test_ca01_*`, `test_ca02_*`, `test_ca03_*`, `test_ca04_*` | passam |
| 05 | sem código novo | `test_split_floor.py::test_ca05_*` | passa |
| 06 (slow) | sem código novo | `test_split_floor.py::test_ca06_*` | passa: o lote de 1 imagem não quebra, sem `drop_last` |
| 07, 08, 09 (slow) | `provisional.py` | `test_provisional.py::test_smoke_*` | **SPEC_ISSUE-06:** passam só com `--seed 0`; com a seed padrão, saída 2 |
| 10 | `provisional.py` | `test_own_images_refused` | passa |
| 11 | `provisional.py` | `test_paths_inside_git_refused`, `test_symlink_into_a_repository_refused` | passa |
| 12 | `provisional.py` | `test_version_refused`, `test_existing_model_dir_refused_untouched` | passa |
| 13 | `provisional.py` | `test_missing_type_refused`, `test_grade_without_images_refused`, `test_other_types_refused`, `test_epochs_out_of_range_refused` | passa |
| 14 | `provisional.py`, `train.py` | `test_without_torch_the_error_is_the_extra`, `test_no_torch.py` | passa |
| 15 | `config.py` | `test_train_config_refuses_a_provisional_version`, `test_official_steps_exit_2` | passa |
| 16 | `report.py` | `test_changelog_refuses_and_writes_nothing`, `test_release_notes_refuses_and_writes_nothing`, `test_report_refuses_before_reading_metrics` | passa |
| 20 (lado do ML) | `config.py` | `test_is_provisional_version` | passa; a comparação com `qc_edge` depende da Parte B |
| 23 | `data.py` | `test_agent_suggestion.py::test_manifest_row_*`, `test_override_line_*`, `test_validate_*` | passa |
| 24 | `data.py` | `test_thresholds_and_evaluate_refuse`, `test_pipeline_refuses` | passa |
| 25 | `provisional.py` | `test_other_labeler_*`, `test_other_labelers_sum_both_files`, `test_excluded_override_is_not_counted`, `test_without_torch_the_labelers_are_refused_first` | passa |
| 26 (lado do ML) | `data.py` | `test_constant_value` | passa; a comparação com `qc_edge` depende da Parte B |

### Testes existentes abaixo do piso (§7)

**Lista vazia.** Nenhum teste do autor nem de aceite precisou de `--allow-below-floor`, e nenhum teste antigo mudou, salvo `qc_ml.provisional` acrescentado à lista de `ml/tests/test_no_torch.py`.

### Decisões tomadas dentro do escopo

- `_require_torch` virou `require_torch` em `ml/src/qc_ml/train.py`, sem mudar o comportamento (§4.2 autoriza). É a única mudança nesse arquivo, fora do `__all__`.
- O laço de treino fica no `qc_ml.provisional`, com `compute_loss`, porque `_run_epoch` recebe um `TrainConfig`, que recusa versão provisória. Os hiperparâmetros vêm de `SKILL_DEFAULTS`, para não divergir do oficial.
- `<M>/<versão>` como arquivo ou link simbólico também dá `model directory already exists`.
- Em erro depois de começar a gravar, além do diretório do modelo, saem as pastas acima dele que o comando criou, para valer "sem gravar nada".
- `qc_ml.report` confere o nome em `--model-dir` e também depois do `realpath`, para cobrir `--model-dir .` e um link com nome oficial. `--previous` não é conferido: a SPEC cita só `--model-dir`, e um diretório provisório não tem `metrics.json`.
- `ml/tests/test_provisional.py` usa `--seed 0` no treino, com comentário que aponta para o SPEC_ISSUE-06. Isso confere o resto do CA-07 (os 7 arquivos, a paridade, o `OnnxInferencer`, o relatório, nenhum split), mas **não** cumpre o CA como está escrito.

### Como rodar

```bash
uv sync --all-packages --extra train
uv run pytest -q ml/tests
```

### Resultado dos testes

| Ambiente | Comando | Resultado |
|---|---|---|
| Como o CI: sem torch, `CI=true`, `TEST_DATABASE_URL` | `uv run pytest -q` (repositório inteiro) | 9581 passed, 153 skipped, 1 warning, em 924,92 s. Sem falha |
| Com o extra `train` (torch 2.14.1, CPU) | `uv run --package qc-ml pytest -q ml/tests` (com os *slow*) | 1245 passed, 2 skipped, em 487,76 s. Os 2 pulados pedem um `model.onnx` real |

O verde cobre os CAs 07 a 09 só com `--seed 0` (SPEC_ISSUE-06): com a seed padrão, eles falham.

### Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes do autor passando (com a ressalva do SPEC_ISSUE-06)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhuma imagem, `.onnx` ou operação sobre `~/partqc-entrada/`
- [x] `.env.example`: sem variável nova

## SPEC_ISSUE levantados na correção (orquestrador)

Encontrados pelo architect ao conferir a Parte B e os CAs, a pedido do orquestrador.

- **SPEC_ISSUE-04:** a recusa do `--provisional-set` em repositório Git diz só "antes de ler o dataset e o plano", mas o `load_plan` testa antes a inbox e o plano. Com eles no mesmo repositório, o CA-28 pode ver `inbox must be outside any git repository`.
- **SPEC_ISSUE-05:** o §4.9 diz que o `export` recusa `agent-suggestion`, mas ele só lê o dataset sintético da paridade (`ml/src/qc_ml/export.py:144`), e o ADR-024 não o lista.

## Parte B (developer)

**Estado: implementada, sem `SPEC_ISSUE` novo.** O SPEC_ISSUE-04 está cumprido no texto novo do §4.9 e do CA-28. O SPEC_ISSUE-06 é da Parte A, e eu não o toquei.

Commits: `a4217e8`, `f3f4c7a`, `f9da7d9`.

### Resumo

- `edge/src/qc_edge/inference.py`: `is_provisional_version`, com a mesma regra do lado do ML.
- `edge/src/qc_edge/app.py`: `source=simulated`, sufixo do veredito e aviso no console, com versão provisória.
- `edge/src/qc_edge/cli.py`: o `WARNING` da subida.
- `edge/src/qc_edge/importer.py`: `AGENT_SUGGESTION_LABELER` e `--provisional-set`. `load_plan` e `_row_problems` ganham um argumento com padrão falso. `ManifestEntry` e `read_manifest_entries` não mudam.
- `edge/README.md`: seções "Modelo provisório" e "Conjunto do modelo provisório".

Não mudam: `capture.js`, `/api/status`, heartbeat, outbox, publisher, contrato, API e `--stub-model`. Sem dependência nova e sem variável nova no `.env.example`.

### Rastreabilidade

| CA | Arquivo(s) | Teste do autor |
|---|---|---|
| 17 | `app.py`, `inference.py` | `test_provisional_model.py::test_provisional_model_is_simulated_in_the_answer_and_in_the_outbox`, `test_every_verdict_gets_the_suffix_and_keeps_approved`, `test_link_with_an_official_name_to_a_provisional_directory_is_simulated` |
| 18 | `app.py` | `test_official_model_stays_live_without_the_suffix`, `test_stub_model_does_not_change`, `test_status_does_not_change_with_a_provisional_model` |
| 19 | `app.py`, `cli.py` | `test_console_says_the_model_is_provisional`, `test_console_of_another_model_has_no_notice`, `test_console_without_a_model_has_no_notice`, `test_cli_warns_about_a_provisional_model`, `test_cli_does_not_warn_about_an_official_model`, `test_stub_model_flag_takes_precedence_without_the_warning` |
| 20 (lado da borda) | `inference.py` | `test_is_provisional_version` |
| 21 | `app.py` (sem campo novo) | `test_the_published_payload_is_only_the_contract` |
| 26 (lado da borda) | `importer.py` | `test_importer_provisional.py::test_constant_is_not_a_collect_labeler`, `test_collect_mode_refuses_the_labeler` |
| 27 | `importer.py` | `test_without_the_option_the_labeler_is_invalid`, `test_without_the_option_a_and_b_still_work`, `test_without_the_option_a_dataset_inside_git_stays_accepted`, `test_without_the_option_a_manifest_with_another_labeler_is_accepted` |
| 28 | `importer.py` | `test_dataset_inside_git_with_inbox_and_plan_outside`, `test_the_dataset_check_comes_before_the_inbox_and_plan_checks`, `test_the_dataset_check_comes_before_a_missing_inbox`, `test_symlink_into_a_repository_is_refused`, `test_the_privacy_option_is_still_checked_first` |
| 29 | `importer.py` | `test_a_valid_plan_is_imported_and_a_second_run_adds_to_it`, `test_a_repeated_plan_is_skipped`, `test_dry_run_writes_nothing`, `test_a_manifest_with_only_the_header_is_a_provisional_set` |
| 30 | `importer.py` | `test_rows_of_another_kind_are_refused`, `test_a_manifest_with_another_labeler_is_refused`, `test_one_row_of_another_labeler_among_others_is_enough`, `test_a_row_too_short_to_have_a_labeler_is_another_labeler` |

O CA-22 é manual e não foi executado: ele depende da operação do §4.8, depois do merge.

### Decisões tomadas dentro do escopo

- **Ordem da recusa do manifest:** `dataset is not a provisional set` vem logo depois de `_read_dataset`, antes de ler o plano. O §4.9 não fixa essa posição.
- **Leitura do `labeler`:** é feita à parte, em `_check_provisional_manifest`, porque `ManifestEntry` não pode mudar. Uma linha curta demais para ter `labeler` conta como outro `labeler`, para recusar na dúvida. Uma linha em branco do CSV não conta como linha.
- **Local do `WARNING`:** fica em `_load_inferencer`, depois de `model loaded`, então não aparece com `--stub-model`, que não carrega o `MODEL_DIR`.

### Limites que o reviewer e o security-devops devem conferir

Nenhum destes é `SPEC_ISSUE`: decorrem do texto da SPEC e do ADR-024.

- **O nome é o único sinal na borda.** Renomear o diretório de um modelo provisório, tirando `-provisional-`, faz as inspeções saírem como `source=live`, sem nenhum aviso, e a borda não olha o `provisional_report.json`. O ADR-024 decide por "o nome decide sozinho". O `edge/README.md` avisa para não trocar o nome.
- **A guarda do manifest vale só na fase 1.** Outra execução sem a opção, ou o modo coleta com o mesmo `DATASET_DIR`, pode acrescentar outro `labeler` depois da conferência, porque a fase 2 não relê o `labeler` sob o lock. O §4.9 põe essa leitura só no `load_plan`. O `qc_ml.provisional` recusa esse conjunto antes de treinar (`other labelers`).

### Como rodar

```bash
uv run pytest -q edge/tests/test_provisional_model.py edge/tests/test_importer_provisional.py
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

### Resultado dos testes

| Ambiente | Comando | Resultado |
|---|---|---|
| Testes novos da Parte B | `uv run pytest -q edge/tests/test_provisional_model.py edge/tests/test_importer_provisional.py` | 57 passed |
| Repositório inteiro, `CI=true`, `TEST_DATABASE_URL`, **com torch instalado** (2.14.1) | `uv run pytest -q` | 9696 passed, 117 skipped, em 1042,58 s. Sem falha |
| Lint | `uv run ruff check .` e `uv run ruff format --check .` | limpos |

A suíte inteira rodou com o extra `train` instalado, então não é o ambiente sem torch do CI, que eu não repeti. Ela rodou antes das duas últimas edições do `edge/README.md`, que só mudam texto. Os testes de aceite das SPECs anteriores passaram, inclusive os das SPECs 036 e 038: nenhum precisa de ajuste do tester, e não alterei nenhum teste existente.

### Conferências manuais, sem teste no repositório

Rodadas uma vez, com dados sintéticos em pasta temporária, sem treino e sem tocar em `~/partqc-entrada/`:

- **Importador → ML:** um conjunto de 11 imagens importado com `--provisional-set` foi recusado por `load_manifest` no padrão (`agent_suggestion_label`) e aceito com `allow_agent_suggestion=True` (11 linhas). O `qc_ml.provisional` não foi rodado sobre esse conjunto.
- **Os dois pacotes:** as 6 versões do CA-20 dão `True, True, False, False, False, False` nos dois lados, e as constantes do CA-26 são iguais e estão fora de `LABELERS`.

### Checagens do autor

- [x] Testes do autor passando
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhuma imagem real, `.onnx` ou operação sobre `~/partqc-entrada/`
- [x] `.env.example`: sem variável nova
