# SPEC-045: Modelo oficial com as fotos dos colegas: piso sem porcas, estrato das ferramentas no `split_v1`, correção do dataset e treino

| Campo | Valor |
|---|---|
| Status | In Review |
| Rodada atual | r1 |
| Autor da implementação | ml-engineer (código do §3.1 e a operação do §4.7, depois do merge) |
| Tags | security |
| Depende de | ADR-025 `Aceito`; SPEC-044 mergeada (contrato 0.7.0 e constantes do `qc-ml`); SPEC-041, SPEC-036 e SPEC-037 `Done` (já estão). Para o modelo chegar à borda de produção: CA-15 da SPEC-044 |
| Semana alvo | S5 (logo depois da SPEC-044) |
| Requisitos cobertos | PRD §7 (só o que o teste pequeno permite, ADR-025 decisão 7); RNF-07; R-02, R-06, R-11, R-14 |
| ADRs relevantes | ADR-025 (`Aceito`; decisões 2 a 8), ADR-024 (piso e data de corte, alterados em parte), ADR-014, ADR-020, ADR-021, ADR-022 |

## 1. Contexto

Em 2026-11-04, o humano decidiu treinar já o modelo oficial com as 223 fotos de colegas que estão em `ml/data/`, sem porcas (ADR-025). Hoje, o `split_v1` é recusado só pelos 5 estratos `nut/*` do piso (SPEC-041 §4.6). Além disso, a inspeção das fotos achou tipos errados e `item_id` repetidos para a mesma peça física (vazamento, R-11). A borda e o `qc-ml` passam a conhecer martelo, chave de aperto e nível pela SPEC-044.

`docs/architecture.md` §7 (artefatos, piso), `docs/dataset-protocol.md` §4, §6, §7 e §10, skill `ml-pipeline` §2 e §5.

**O que já funciona sem código novo** (leitura de `ml/src/qc_ml/`): `derive_model_labels` só põe no modelo os tipos com imagem no treino, então `nut`, `adjustable_wrench` e `angle_grinder` ficam fora do `labels.json`; as métricas de grau são calculadas nos tipos de `GRADED_OBJECT_TYPES` presentes, só `screw` aqui; e a borda carrega um `labels.json` sem `nut` (CA-05 da SPEC-044). Esta SPEC fixa esse comportamento por CA.

## 2. Objetivo

O `python -m qc_ml.split` gera o `split_v1` sem porcas, com as ferramentas sem grau estratificadas pelo tipo inteiro e com a opção de adiar tipos; o pipeline roda até o `metrics.json` com um modelo sem `nut`; e o dataset é refeito com as correções do ADR-025, com o `split_v1` e o modelo oficial gerados a partir dele.

## 3. Escopo

### 3.1 Dentro

**Código (ml-engineer):**

- `ml/src/qc_ml/split.py`:
  - `FLOOR_STRATA` passa a ser a lista fixa `screw` × os 5 graus mais `("other", "none")` (6 estratos);
  - função pública nova `split_stratum` (§4.2), usada no `split_v1` e na extensão do ADR-022, no lugar da `extension_strata` interna;
  - `--defer-types` passa a valer também no `split_v1` (§4.3).
- `ml/src/qc_ml/synthetic.py`: `make_synthetic_dataset(…, include_nut: bool = True)`. Com `False`, nenhuma peça `N-`/`XN-` é criada, e a numeração das outras peças não muda. Saída padrão igual byte a byte à de hoje.
- `ml/scripts/make_tiny_fixture.py --identified-tools-no-nut` e a fixture `ml/tests/fixtures/tiny_model_no_nut/` (`object_types = ["screw", "other", "hammer", "wrench", "spirit_level"]`, `ungraded_object_types = ["hammer", "wrench", "spirit_level"]`), gerada pelo script e versionada como as outras (sem `.onnx` real de pesos treinados, só o modelo minúsculo da fixture, como `tiny_model_power_tools`).
- `ml/README.md`, seção nova "Modelo oficial com as fotos dos colegas (ADR-025)": o piso novo, o `--defer-types` no `split_v1` e o passo a passo do §4.7.

**Operação depois do merge** (ml-engineer, com a conferência do tester e os passos humanos marcados; §4.7): reimportação com o plano corrigido (Anexo A), rotulagem dupla, `split_v1` por PR, treino e modelo na borda.

**Tester:** `ml/tests/acceptance/test_spec_045.py`.

**Tester, ajustes de aceite antigos** (aplicação explícita de `docs/architecture.md` §10):

- `ml/tests/acceptance/test_spec_041.py`, CA-02 e CA-03: o estrato retirado do dataset (`nut/fair`) passa a ser `screw/fair`, e as linhas esperadas (`split_v1 below the floor: …` e o aviso `below_floor`) acompanham. A intenção (recusar abaixo do piso e citar o estrato) não muda. Uma asserção sobre o tamanho ou o conteúdo de `FLOOR_STRATA` passa a conferir os 6 estratos do CA-01 desta SPEC.
- Nos aceites das SPECs 011, 016 e 021: uma asserção de que `--defer-types` é ignorado no `split_v1`, ou de que uma ferramenta manual sem grau fica estratificada por grau no `split_v1`, passa a conferir o comportamento do §4.2 e do §4.3. As asserções sobre a extensão e sobre os splits seguintes não mudam.

### 3.2 Fora

- Os tipos novos no contrato, na borda, no dashboard e nas constantes do `qc-ml`: **SPEC-044**.
- Uma CLI de reetiquetagem de `item_id` ou de tipo: não é feita (ADR-025, decisão 4). O plano corrigido é gerado fora do repositório, a partir do Anexo A.
- Concordância das ferramentas (o `qc_ml.agreement` forma pares só de `screw`/`nut`): fora, porque nenhuma ferramenta é graduada pelo modelo.
- Remover `nut` do contrato, da rubrica ou do pipeline: não é feito.
- Imagens externas no `ml/data/`: nenhuma entra nesta SPEC.

## 4. Requisitos detalhados

### 4.1 Piso (ADR-025, decisão 2)

- `FLOOR_STRATA == (("screw","perfect"), ("screw","good"), ("screw","fair"), ("screw","poor"), ("screw","unusable"), ("other","none"))`, nessa ordem.
- `floor_problems` e a CLI não mudam de forma: a recusa continua com uma linha `split_v1 below the floor: <estrato>` por estrato e a saída 2, e `--allow-below-floor` continua gravando com o aviso `below_floor`.
- Uma porca presente no dataset é estratificada e dividida normalmente, mas não entra no piso.
- As "3 fotos por peça" do piso do ADR-024 continuam fora do código e ficam dispensadas neste dataset (ADR-025, decisão 7).

### 4.2 Estrato (ADR-025, decisão 8)

```python
def split_stratum(
    object_type: str,
    item_stratum: tuple[str, str],
    coverage: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str]:
    """Stratum used to allocate a non-external item, in split_v1 and in the test extension."""
```

- Devolve `(object_type, "none")` quando `object_type` está em `POWER_TOOL_OBJECT_TYPES` ou em `IDENTIFIED_TOOL_OBJECT_TYPES`, ou quando está em `TOOL_OBJECT_TYPES` e `coverage[object_type]["graded"]` é falso. Nos outros casos, devolve `item_stratum` sem mudança.
- `coverage` é `tool_grade_coverage(df)` sobre o mesmo `df` lido pela CLI, como na extensão de hoje (SPEC-016 §4.7).
- No `split_v1`, a alocação agrupa as peças não externas por `split_stratum`. Os avisos `small_stratum` citam o estrato devolvido (por exemplo, `pliers/none`).
- `floor_problems` continua usando o estrato do grau dominante (`item_strata`): só `screw` e `other` entram no piso, e para eles as duas funções dão o mesmo resultado.
- Com dados só de `screw`, `nut` e `other`, o `split_v1` sai igual byte a byte ao de antes desta SPEC (CA-07).

### 4.3 `--defer-types` no `split_v1`

- Sem versão anterior, as imagens dos tipos de `--defer-types` saem do `split_v1` antes da alocação, e `split_v1.json` registra `deferred_types` (na ordem de `KNOWN_OBJECT_TYPES`). Os leitores do split já ignoram essas imagens (`assign_splits`, aviso `deferred type images`).
- Um tipo adiado no `split_v1` continua "novo" na versão seguinte (ADR-022, decisão 4): precisa de `--extend-test-types` ou de `--defer-types` de novo.
- No `split_v1`, um tipo de `--defer-types` sem nenhuma imagem no dataset sai com 2, sem gravar nada, com a linha `deferred type without images: <tipo>` na stderr. Um valor fora de `KNOWN_OBJECT_TYPES` continua com `unknown object type: <valor>`.
- `--extend-test-types` continua sem efeito no `split_v1` (todo tipo presente e não adiado é dividido normalmente), com o aviso de hoje no log.
- O piso é conferido depois do adiamento: adiar `screw` ou `other` faz a CLI recusar pelo piso.

### 4.4 Treino e avaliação sem porca

Nenhuma mudança de comportamento esperada em `train`, `thresholds`, `evaluate`, `export` e `report`. O CA-10 confere o caminho sem torch com a fixture `tiny_model_no_nut`. Se algum desses módulos exigir `nut`, o ml-engineer registra `SPEC_ISSUE` em vez de contornar.

### 4.5 Privacidade e R-02

- Nenhum agente abre, converte em miniatura ou descreve uma foto de `ml/data/`, da pasta de entrada ou do backup (ADR-025, decisão 3). Os scripts da operação leem só CSV e saídas de texto das CLIs.
- O plano corrigido, o backup do `ml/data` antigo e qualquer script da operação ficam fora do repositório. A importação recusa plano e pasta de entrada dentro de um repositório Git (SPEC-038).
- `ml/data/` continua fora do Git. O `split_v1` (só caminhos e conjuntos) vai para o Git por PR, como manda a skill `ml-pipeline`.

### 4.6 Concordância (ADR-025, decisão 6)

Feita **depois** da reimportação, porque os caminhos das imagens mudam. O segundo membro da dupla grada às cegas, na tela local de rotulagem (fora do repositório), 20% das fotos de parafuso, estratificadas pelo grau do Carlos, e gera `ml/data/labels_second.csv`. Depois, `uv run --package qc-ml python -m qc_ml.agreement --first ml/data/manifest.csv --second ml/data/labels_second.csv --out ml/reports/agreement.json`. Com QWK < 0,6, o `split_v1` espera a decisão do humano. Se o humano dispensar a etapa (ADR-025, opção 6B), o PR do split diz isso.

### 4.7 Operação depois do merge (vai para o `ml/README.md`)

Ordem: CA-13 → CA-14 → CA-15 → CA-16. Cada passo para no primeiro erro; nada aqui é corrigido à mão no manifest.

1. **Backup e dataset vazio (ml-engineer):** mover `ml/data/` inteiro para uma pasta fora do repositório (ex.: `~/partqc-backup/ml-data-antes-adr-025/`, modo `0700`). O `ml/data/` fica vazio.
2. **Plano corrigido (ml-engineer):** gerar `~/partqc-entrada/colegas/plano-v2.csv` a partir de `plano.csv`, linha a linha, pelas regras do Anexo A, com um script fora do repositório que lê só CSV. Mesmas 223 linhas, mesmas colunas e mesma ordem; mudam só `item_id`, `object_type`, `grade` e `notes` das linhas afetadas.
3. **Importação (ml-engineer):** `uv run --package qc-edge python -m qc_edge.importer --dataset-dir ml/data --inbox ~/partqc-entrada/colegas --plan ~/partqc-entrada/colegas/plano-v2.csv --privacy-checked --dry-run`, conferir 0 `failed`, e repetir sem `--dry-run`. O `--privacy-checked` vale pela conferência humana da primeira importação, que viu os mesmos arquivos, e pela resposta 3 do ADR-025 sobre `O-534` e `O-535`.
4. **Conferências (tester):** as do CA-13.
5. **Concordância (dupla):** §4.6, CA-14.
6. **`split_v1` (ml-engineer):** `uv run --package qc-ml python -m qc_ml.split --dataset-dir ml/data --splits-dir ml/splits --seed 42`, com `--defer-types` só se o humano escolher a opção C da decisão 2 do ADR-025. PR só com `ml/splits/split_v1.*` (CA-15).
7. **Treino (ml-engineer ou dupla):** pelo procedimento da SPEC-012 e do `ml/README.md`, no Colab ou no notebook com o extra `train`, versão `partqc-mnv3-v1` (ou o próximo número livre), depois do merge do `split_v1`. `metrics.json`, entrada no CHANGELOG com as limitações da decisão 7 do ADR-025 e Release com `python -m qc_ml.report release-notes` (CA-16).
8. **Fim (humano):** depois do merge do `split_v1`, apagar os arquivos da pasta de entrada `~/partqc-entrada/colegas/` (ADR-020, decisão 6) e o backup do passo 1.

## 5. Critérios de aceite

Contexto comum: `make_synthetic_dataset` em pasta temporária, CLI `python -m qc_ml.split` chamada como em `test_spec_041.py`, sem torch.

- **CA-01 (piso)** — *Dado* `qc_ml.split`, *então* `FLOOR_STRATA` é exatamente a tupla de 6 estratos do §4.1, nessa ordem, e não contém nenhum estrato `nut/*`.
- **CA-02 (`split_v1` sem porcas)** — *Dado* `make_synthetic_dataset(items_per_stratum=3, images_per_item=3, include_nut=False)` (18 peças, 54 imagens) e nenhum split anterior, *quando* a CLI roda sem flag, *então* sai com 0, grava `split_v1.csv`, `.sha256` e `.json`, cada split tem 6 peças e 18 imagens, e `warnings` não tem nenhum `below_floor`.
- **CA-03 (recusa abaixo do piso)** — *Dado* o dataset do CA-02 sem as imagens e as linhas de uma peça `screw`/`fair` (17 peças), *quando* a CLI roda sem flag, *então* sai com 2, a stderr tem a linha `split_v1 below the floor: screw/fair` e nenhum arquivo `split_v1.*` existe; *quando* roda com `--allow-below-floor`, *então* sai com 0 e o `split_v1.json` tem `{"code": "below_floor", "stratum": "screw/fair"}`.
- **CA-04 (porca fora do piso)** — *Dado* o dataset do CA-02 mais uma peça `N-001` `nut`/`fair` com 3 imagens, *quando* a CLI roda, *então* sai com 0, `warnings` tem `small_stratum` de `nut/fair` e nenhum `below_floor`, e as 3 imagens de `N-001` estão em `train`.
- **CA-05 (função do estrato)** — *Dado* `coverage = {"pliers": {"graded": False, …}}` e, depois, `{"pliers": {"graded": True, …}}` (as outras manuais com `graded` falso), *então* `split_stratum("pliers", ("pliers","good"), coverage)` devolve `("pliers","none")` e, no segundo caso, `("pliers","good")`; `split_stratum("hammer", ("hammer","none"), coverage)` e `split_stratum("drill", ("drill","none"), coverage)` devolvem o tipo com `"none"`; e `split_stratum("screw", ("screw","fair"), coverage)` e `split_stratum("other", ("other","none"), coverage)` devolvem o estrato recebido.
- **CA-06 (ferramentas no `split_v1`)** — *Dado* `make_synthetic_dataset(items_per_stratum=3, images_per_item=3, include_nut=False, tool_items_per_stratum=1, identified_tool_items_per_type=3)` (cada manual com 5 peças, uma por grau; cada tipo novo com 3), *quando* a CLI roda, *então* sai com 0; cada uma das 5 manuais tem exatamente 1 peça em `test`, 1 em `val` e 3 em `train`; cada tipo novo tem 1 peça em cada split; e `warnings` não tem `small_stratum` com estrato `<manual>/<grau>`.
- **CA-07 (mesmo split sem ferramentas)** — *Dado* `make_synthetic_dataset(items_per_stratum=3, images_per_item=3)` (com porcas, sem ferramentas), *quando* a CLI roda, *então* o SHA-256 do `split_v1.csv` é igual ao que o código do commit base desta SPEC (o merge-base com a `main`) produz para o mesmo dataset e a mesma seed. O tester calcula o valor esperado nesse commit e o fixa no teste, com o hash do commit num comentário.
- **CA-08 (`--defer-types` no `split_v1`)** — *Dado* o dataset do CA-02 com `identified_tool_items_per_type=3`, *quando* a CLI roda com `--defer-types spirit_level`, *então* sai com 0, nenhuma linha do `split_v1.csv` tem caminho em `raw/spirit_level/`, e `split_v1.json` tem `"deferred_types": ["spirit_level"]`. *Quando* a CLI roda de novo sem decisão, *então* sai com 2 com `new object type without decision: spirit_level`; com `--extend-test-types spirit_level`, sai com 0 e grava `split_v2` com 1 peça `spirit_level` em cada split, sem mudar nenhuma linha do `split_v1`. *Dado* o dataset do CA-02 e nenhum split, *quando* a CLI roda com `--defer-types nut`, *então* sai com 2, a stderr tem `deferred type without images: nut` e nada é gravado.
- **CA-09 (tipo sem imagem fora do modelo)** — *Dado* o `df` de `load_manifest` do dataset do CA-02 com `identified_tool_items_per_type=3`, *quando* `derive_model_labels(df, df)` é chamado, *então* `object_types == ("screw", "other", "hammer", "wrench", "spirit_level")` e `ungraded_object_types == ("hammer", "wrench", "spirit_level")`.
- **CA-10 (avaliação sem porca, CI, sem torch)** — *Dado* o dataset e o `split_v1` do CA-09 e a fixture `tiny_model_no_nut`, *quando* `python -m qc_ml.thresholds` e `python -m qc_ml.evaluate` rodam, *então* os dois saem com 0; o `decision.json` tem os 3 limiares; o `metrics.json` tem `labels.object_types` igual ao da fixture, `type_confusion` 5 × 5, `grade_qwk` e `type_accuracy` não nulos e `n_items_test_by_grade` igual a 1 nos 5 graus; e a `type_confusion` não tem linha nem coluna `nut`.
- **CA-11 (gerador)** — *Dado* `make_synthetic_dataset` padrão em dois diretórios, um deles com `include_nut=True` explícito, *então* os arquivos são iguais byte a byte; e com `include_nut=False`, nenhuma linha do manifest tem `item_id` começando por `N-` ou `XN-`, e os `item_id` `S-` e `O-` são os mesmos da saída padrão.
- **CA-12 (dataset fora do Git, R-14)** — *Dado* o repositório, *quando* `git ls-files ml/data` roda, *então* a saída é vazia; e `git check-ignore ml/data/manifest.csv ml/data/sources.csv ml/data/raw/hammer/_/T-601__0__20261105T120000Z.jpg` lista os três caminhos.

### Operação e manuais (depois do merge)

- **CA-13 (operação: reimportação; ml-engineer executa, tester confere)** — Passos 1 a 4 do §4.7. Conferências, cada uma com a saída registrada no test-report da operação: (1) `python -m qc_edge.privacy --dataset-dir ml/data` sai com 0 e `0 with private data`; (2) `python -m qc_ml.data validate --dataset-dir ml/data` sai com 0; (3) o manifest tem 223 linhas de dados e o `sources.csv` 223 linhas `contributor`, com as mesmas contagens por `c01`, `c02` e `c03` do `sources.csv` do backup; (4) o número de `item_id` distintos por tipo é o da tabela do Anexo A (114 no total; `nut`, `adjustable_wrench` e `angle_grinder` com 0); (5) nenhum `item_id` tem dois tipos; (6) toda linha com `item_id` ou tipo diferente do plano original tem `notes` começando por `ADR-025:`; (7) as linhas não afetadas pelo Anexo A têm o mesmo `item_id`, tipo e grau do backup.
- **CA-14 (manual, dupla: concordância)** — §4.6. `ml/reports/agreement.json` com o QWK e a matriz, ou, se o humano dispensar, o registro da dispensa no PR do split. Com QWK < 0,6, o CA-15 espera a decisão do humano.
- **CA-15 (manual: `split_v1` por PR)** — Passo 6 do §4.7. A CLI sai com 0, sem `below_floor`; o PR traz só `ml/splits/split_v1.*`; a descrição do PR compara as peças por tipo e por split com a projeção do ADR-025 e explica cada diferença; e o reviewer confere que nenhuma peça tem imagens em dois splits (o teste do ADR-014 roda no CI).
- **CA-16 (manual: modelo oficial)** — Passo 7 do §4.7. `metrics.json` com a `type_confusion` completa (todos os tipos do modelo, sem omitir nenhum, R-11), o IC por bootstrap e os `warnings`; entrada no CHANGELOG com as limitações da decisão 7 do ADR-025 e o número de peças de teste junto de cada métrica `atingida`; Release com as notas do `qc_ml.report release-notes`. Depois do CA-15 da SPEC-044: o modelo no `MODEL_DIR` da borda, `GET /api/status` com a versão e o `sha256`, e uma foto de pelo menos um parafuso, um martelo ou uma chave de aperto e um objeto `other` pela página `/capture`, com o resultado registrado. Este CA fecha o CA-28 da SPEC-012 e o CA-16 da SPEC-008 (latência medida com este modelo).

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (ml-engineer) | `FLOOR_STRATA`, `split_stratum`, `--defer-types` no `split_v1`, gerador com `include_nut`, fixture | `ml/tests/` |
| Aceite (tester) | Um por CA de 01 a 12 | `ml/tests/acceptance/test_spec_045.py` |
| Operação (ml-engineer; conferência do tester) | CA-13 | test-report da operação em `reviews/SPEC-045/` |
| Manual (dupla) | CA-14 a CA-16 | descritos nos CAs |

Nenhum teste lê `ml/data/`, a pasta de entrada ou o backup: todos usam dados sintéticos. Nada é mockado além do que os testes do `qc-ml` já mockam.

## 7. Riscos e notas para o implementador

- **Paths mudam na reimportação:** o `labels_second.csv` tem de ser feito depois do passo 3 (§4.6).
- **Projeção não é garantia:** a tabela do Anexo A foi contada no manifest. Se o `validate` ou a contagem divergirem, pare e registre `SPEC_ISSUE`; não ajuste o plano sem o architect.
- **Graus divergentes dentro de uma peça fundida** (por exemplo, `S-509`): é esperado e fica como está; o estrato é o grau dominante, com empate para o mais severo.
- **Classes só com treino** (nível, chave Allen, furadeira, serra, parafusadeira): podem "roubar" previsões de outras classes, o que aparece na `type_confusion` do teste. Reportar como medido.
- **Nada de agente olhando foto** (§4.5): se uma conferência parecer exigir isso, ela é humana.

## 8. Definição de pronto

- [ ] CAs 01 a 12 com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED e security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `ml/README.md` com o §4.7; `docs/dataset-protocol.md` §4, §7 e §10 e `docs/architecture.md` §7 pelo architect
- [ ] PR aberto com os relatórios; merge conforme R-09
- [ ] Depois do merge: CA-13 (test-report da operação), CA-14, CA-15 (PR do split) e CA-16 registrados

## 9. Perguntas para a aprovação (humano)

As decisões de fundo estão no ADR-025 (perguntas 2, 4, 5 e 6). Aqui só:

1. O ml-engineer pode fazer a operação do §4.7 (passos 1 a 3, 6 e 7) com o tester conferindo, ou a dupla prefere rodar os comandos? **Recomendação:** o ml-engineer roda e o tester confere, sem nenhum agente abrir foto (§4.5); a dupla faz a concordância e apaga a pasta de entrada.
2. Onde treinar: no Colab (procedimento da SPEC-012) ou no notebook com o extra `train`? **Recomendação:** no notebook. São 223 fotos, e o Colab exige subir o dataset ao Drive.

## Anexo A: correções do dataset (ADR-025, decisão 4)

Fonte: a curadoria de 2026-11-04 (fora do repositório), aplicada ao `plano.csv` original. Regras para gerar o `plano-v2.csv`, linha a linha:

1. Toda linha cujo `item_id` antigo está na coluna "Antigos" de uma tabela abaixo recebe o `item_id` e o `object_type` "Novos".
2. Nas linhas que passam para `hammer`, `wrench` ou `spirit_level`, o `grade` fica vazio. Isso descarta os graus de 3 fotos (`T-506` `fair`, `T-542` `poor`, `T-546` `fair`). Nas outras, o grau não muda.
3. Toda linha cujo `item_id` ou `object_type` mudou recebe em `notes` o texto `ADR-025: era <item_id antigo> <tipo antigo>` (ex.: `ADR-025: era O-504 other`). Se a linha já tinha `notes`, o texto novo vem antes, seguido de um ponto e vírgula e um espaço. O total fica dentro de 200 caracteres.
4. As outras colunas (`file`, `labeler`, `angle`, `origin`, `contributor`, `source_id`, `source_ref`) não mudam. O `labeler` continua `a`, porque o grau continua sendo do Carlos.
5. Todo `item_id` que não aparece nas tabelas fica como está.

**Mudança de tipo** (de `other` para os tipos novos: `O-5NN` vira `T-6NN`, com os mesmos dois dígitos finais; grupos ficam com o menor número):

| Novo | Tipo novo | Antigos |
|---|---|---|
| `T-601` | `hammer` | `O-501` |
| `T-604` | `hammer` | `O-504`, `O-510`, `O-511` |
| `T-637` | `hammer` | `O-537` |
| `T-638` | `hammer` | `O-538` |
| `T-640` | `hammer` | `O-540` |
| `T-641` | `hammer` | `O-541` |
| `T-643` | `hammer` | `O-543` |
| `T-603` | `wrench` | `O-503` |
| `T-605` | `wrench` | `O-505`, `O-518` |
| `T-612` | `wrench` | `O-512`, `O-513`, `O-514`, `O-515` |
| `T-616` | `wrench` | `O-516`, `O-517`, `O-519`, `O-520` |
| `T-621` | `wrench` | `O-521`, `O-523`, `O-525`, `O-526`, `T-506` |
| `T-645` | `wrench` | `O-545` |
| `T-542` | `wrench` | `T-542` (era `pliers`) |
| `T-546` | `wrench` | `T-546` (era `adjustable_wrench`) |
| `T-607` | `spirit_level` | `O-507`, `O-508`, `O-528` |
| `T-609` | `spirit_level` | `O-509` |

**Fusões sem mudança de tipo** (ficam com o menor `item_id` do grupo):

| Novo | Tipo | Antigos |
|---|---|---|
| `S-508` | `screw` | `S-508`, `S-510`, `S-512`, `S-513`, `S-529` |
| `S-509` | `screw` | `S-509`, `S-511`, `S-517`, `S-519`, `S-520`, `S-521`, `S-523`, `S-526`, `S-527`, `S-528` |
| `S-514` | `screw` | `S-514`, `S-531`, `S-533` |
| `S-515` | `screw` | `S-515`, `S-516`, `S-518`, `S-522`, `S-524`, `S-525` |
| `S-530` | `screw` | `S-530`, `S-532` |
| `O-506` | `other` | `O-506`, `O-522`, `O-524`, `O-527` |
| `T-507` | `flat_screwdriver` | `T-507`, `T-508`, `T-522`, `T-526` |
| `T-509` | `phillips_screwdriver` | `T-509`, `T-514`, `T-516`, `T-517` |
| `T-510` | `saw` | `T-510`, `T-518`, `T-519`, `T-520` |
| `T-511` | `pliers` | `T-511`, `T-512`, `T-513`, `T-515` |
| `T-521` | `pliers` | `T-521`, `T-523`, `T-524`, `T-525` |
| `T-527` | `drill` | `T-527`, `T-528`, `T-529`, `T-530`, `T-531`, `T-539`, `T-541` |
| `T-532` | `drill` | `T-532`, `T-533`, `T-534`, `T-535` |
| `T-536` | `cordless_screwdriver` | `T-536`, `T-537`, `T-538`, `T-540` |

**Contagem esperada depois da reimportação** (CA-13, item 4): 223 imagens e 114 peças.

| Tipo | Peças | | Tipo | Peças |
|---|---|---|---|---|
| `screw` | 47 | | `phillips_screwdriver` | 7 |
| `other` | 23 | | `allen_key` | 1 |
| `hammer` | 7 | | `drill` | 2 |
| `wrench` | 8 | | `saw` | 1 |
| `spirit_level` | 2 | | `cordless_screwdriver` | 1 |
| `pliers` | 7 | | `nut`, `adjustable_wrench`, `angle_grinder` | 0 |
| `flat_screwdriver` | 8 | | | |

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-11-04 | SPEC criada como `Draft`: piso fixo sem porcas, `split_stratum` único, `--defer-types` no `split_v1`, gerador sem porca, fixture `tiny_model_no_nut`, operação de reimportação com o Anexo A, concordância, `split_v1` e treino; CAs 01 a 12 automatizados, CA-13 de operação e CAs 14 a 16 manuais | Decisão do humano de 2026-11-04 (ADR-025, `Proposto`) | Orquestrador, a pedido do humano |
| 2026-11-04 | Aprovada pelo humano (`Ready`): "Aprovar tudo", com as recomendações da §9; rotulagem dupla dispensada e declarada (ADR-025, resposta 5) | Aceite do ADR-025 | Humano |
