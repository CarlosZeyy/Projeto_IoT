# SPEC-011: ML — manifest, split agrupado e augmentations

| Campo | Valor |
|---|---|
| Status | Ready — **Aguardando reaprovação humana** |
| Rodada atual | — |
| Autor da implementação | ml-engineer |
| Tags | — |
| Depende de | SPEC-001, SPEC-002, SPEC-010 |
| Semana alvo | S3 |
| Requisitos cobertos | RF-08 (consumo do manifest), RNF-07; meta de concordância do PRD §7; R-11; R-14 (exclusão de foto com pessoa) |
| ADRs relevantes | ADR-001, ADR-004, ADR-014 |

## 1. Contexto

O modo coleta (SPEC-010) grava as imagens em `DATASET_DIR/raw/...` e uma linha por imagem em `DATASET_DIR/manifest.csv` (`docs/dataset-protocol.md` §5). Antes de treinar (SPEC-012), o pipeline precisa validar o manifest, aplicar as correções de rótulo e as exclusões, medir a concordância entre rotuladores, gerar um split **por peça física** (R-11) e entregar as imagens ao treino com as augmentations corretas. As convenções obrigatórias estão na skill `ml-pipeline` (§1, §2 e §3) e em `docs/architecture.md` §7.

Pendências do portão r1 da SPEC-010 (`reviews/SPEC-010/r1-security-report.md`) que entram aqui:

| Pendência | O que entra aqui |
|---|---|
| SEC-10-02 (controle compensatório) | Arquivo `.jpg` sem linha no manifest vira o problema `orphan_image` (§4.1); a linha sem arquivo já era `missing_file` |
| SEC-10-03 | O manifest é lido só com `csv`/`pandas`, nunca por quebra de linhas (§4.1) |
| SEC-10-04 | Nenhuma saída desta SPEC é CSV para planilha; regra para uma futura (§7) |
| SEC-10-06 | O pipeline não toma o `flock` do manifest (§7) |
| SEC-10-08 (R-14) | `exclusions.csv` tira do dataset uma foto que precisa sair (por exemplo, com pessoa), sem reescrever o manifest e sem quebrar o split (§4.1, §4.3, §4.4); o procedimento humano está em `docs/dataset-protocol.md` §8.1 |

## 2. Objetivo

Com `python -m qc_ml.split`, gerar `ml/splits/split_v<N>.csv` reprodutível, sem nenhum `item_id` em dois conjuntos e com o teste congelado a partir do `split_v1`, a partir de um manifest validado.

## 3. Escopo

### 3.1 Dentro

- `ml/src/qc_ml/errors.py`: `ManifestError`, `ManifestProblem`, `SplitError`, `SplitIntegrityError` (esta última usada pela SPEC-012).
- `ml/src/qc_ml/data.py` (módulo, **não** pacote: o `.gitignore` ignora diretórios `data/`): `load_manifest`, overrides, exclusões (`load_exclusions`), detecção de arquivos órfãos, relatório de dados, CLI `python -m qc_ml.data validate|report`.
- `ml/src/qc_ml/agreement.py`: CLI `python -m qc_ml.agreement` → `ml/reports/agreement.json`.
- `ml/src/qc_ml/split.py`: `make_split`, `load_split`, `rows_for`, CLI `python -m qc_ml.split`; arquivos `ml/splits/split_v<N>.csv`, `.sha256` e `.json`.
- `ml/src/qc_ml/augment.py`: augmentations de treino só com Pillow + numpy (sem torch).
- `ml/src/qc_ml/dataset.py`: `PartsDataset` (exige o extra `train`, com torch).
- `ml/src/qc_ml/synthetic.py`: `make_synthetic_dataset`, gerador de dataset sintético (Pillow) usado pelos testes desta SPEC e da SPEC-012.
- Testes em `ml/tests/` (autor) e `ml/tests/acceptance/test_spec_011.py` (tester).

### 3.2 Fora

- Modelo, treino, avaliação, limiares e export ONNX: SPEC-012.
- Captura e escrita do manifest: SPEC-010.
- Tipos de ferramenta (prefixo `T-`, classes da Fase 2): SPEC-016.
- Recriar o conjunto de teste: exige ADR; esta SPEC **não** oferece opção para isso. Tirar do teste uma imagem excluída (§4.4) não é recriar o teste.
- Remover EXIF, XMP e trailers das imagens e a varredura de privacidade antes do backup: SPEC-025 (`python -m qc_edge.privacy`) e `docs/dataset-protocol.md` §8.

## 4. Requisitos detalhados

### 4.1 `load_manifest`

```python
def load_manifest(dataset_dir: Path | str, *, apply_overrides: bool = True,
                  verify_images: bool = True) -> pd.DataFrame
```

- Lê `manifest.csv` (UTF-8, colunas de `dataset-protocol.md` §5). Grau vazio vira `None`.
- **Leitura (SEC-10-03):** só com `pandas.read_csv(..., dtype=str, keep_default_na=False)` ou `csv.DictReader` sobre um arquivo aberto com `newline=""`. **Nunca** por quebra de linhas (`str.splitlines()`, `readlines()`, contagem de `\n`, `wc -l`): linhas gravadas antes da SPEC-025 podem ter, em `notes` ou `capture_device`, U+2028, U+2029 ou U+0085, que `splitlines()` conta como quebra. O número de linhas citado nos problemas (`line`) é o número do registro CSV (cabeçalho = 1), não o da linha física.
- **Exclusões (SEC-10-08, R-14):** se `exclusions.csv` existir em `dataset_dir` (UTF-8, cabeçalho `image_path,reason`; `reason` ∈ {`person`, `other`}), as linhas do manifest com esses `image_path` saem do resultado **antes** das demais validações de linha: não geram `missing_file` (o arquivo **tem** de ter sido apagado), nem problemas de rótulo, e as overrides delas são ignoradas. A exclusão vale com `apply_overrides` verdadeiro ou falso. `duplicate_image_path` continua conferido sobre o manifest inteiro.
- Se `labels_overrides.csv` existir e `apply_overrides=True`, aplica as correções **antes** das validações (uma override pode corrigir um grau ausente). Para o mesmo `image_path`, vale a **última** linha do arquivo. Colunas adicionadas ao resultado: `grade_original` (grau do manifest) e `overridden` (bool).
- **Arquivos órfãos (SEC-10-02):** sempre (com ou sem `verify_images`), todo arquivo regular `*.jpg` sob `dataset_dir/raw/` (recursivo, sem seguir links simbólicos) cujo caminho relativo não é `image_path` de nenhuma linha do manifest (excluídas inclusive) vira um problema `orphan_image`, com `line = None` e o caminho relativo em `image_path`. Arquivos que não terminam em `.jpg` (como o temporário do `mkstemp` da SPEC-010) são ignorados.
- `load_exclusions(dataset_dir) -> frozenset[str]`: os `image_path` de `exclusions.csv` (vazio se o arquivo não existir), com as mesmas validações; usada por `load_manifest`, pela concordância (§4.3) e pelo split (§4.4).
- Tipos aceitos nesta SPEC: `KNOWN_OBJECT_TYPES = ("screw", "nut", "other")`; com grau obrigatório: `GRADED_OBJECT_TYPES = ("screw", "nut")`. Graus válidos: os valores de `qc_contracts.Grade`.
- Coleta **todos** os problemas e, se houver algum, levanta **uma** `ManifestError` com a lista `problems: list[ManifestProblem]` (`code`, `file`, `line`, `image_path`, `message`). `str(err)` mostra um problema por linha.

| `code` | Condição |
|---|---|
| `missing_column` | coluna obrigatória ausente no manifest (aborta as demais validações) |
| `missing_file` | `DATASET_DIR/<image_path>` não existe |
| `unreadable_image` | `qc_preprocess.load_image` falha por qualquer motivo que não seja o de `too_many_jpeg_scans` (só com `verify_images=True`) |
| `too_many_jpeg_scans` | `qc_preprocess.load_image` levanta `InvalidImageError` cuja mensagem contém `JPEG scans` (limite de 64 marcadores, SPEC-024 §4.1); só com `verify_images=True`. A `message` do problema traz a mensagem original e a dica `motion photo? see docs/dataset-protocol.md section 3` |
| `item_type_conflict` | mesmo `item_id` com dois ou mais `object_type` |
| `grade_on_other` | grau preenchido em `other` |
| `missing_grade` | grau vazio em `screw`/`nut` |
| `invalid_grade` / `invalid_object_type` | valor fora dos enums acima |
| `invalid_item_id` | não casa `^[SNOT]-\d{3}$` |
| `item_prefix_mismatch` | prefixo incoerente com o tipo (`S`→`screw`, `N`→`nut`, `O`→`other`) |
| `invalid_angle` | `angle` fora de 0–4 ou não inteiro |
| `duplicate_image_path` | `image_path` repetido no manifest |
| `override_unknown_image` | override para `image_path` ausente do manifest |
| `override_missing_reason` | override com `reason` vazio |
| `orphan_image` | arquivo `.jpg` sob `raw/` sem linha no manifest (SEC-10-02) |
| `exclusion_unknown_image` | linha de `exclusions.csv` com `image_path` ausente do manifest |
| `exclusion_invalid_reason` | `reason` fora de `person` e `other` (inclusive vazio) |
| `excluded_file_present` | o arquivo de uma imagem excluída ainda existe em disco: a foto tem de ser apagada (`docs/dataset-protocol.md` §8.1) |

**Rejeições por motivo (SEC-24-03).** O `python -m qc_ml.data validate` imprime um problema por linha e, depois deles, uma linha de resumo por `code` presente, em ordem alfabética, no formato `count <code>: <n>` (ex.: `count too_many_jpeg_scans: 3`). Assim, uma câmera com a "foto com movimento" ligada aparece logo na primeira validação, e não como um punhado de `unreadable_image` soltos. A classificação usa só a mensagem, que a SPEC-024 garante conter `JPEG scans`. O pipeline **não** conta os marcadores de novo nem trata o arquivo de outra forma.

### 4.2 Relatório de dados

`build_data_report(df, split_df | None) -> dict`, gravado por `python -m qc_ml.data report --dataset-dir D --split S --out ml/reports/data_report.json`. Chaves: `generated_at` (UTC ISO), `manifest_sha256`, `split_file`, `split_sha256` (ou `null`), `n_images`, `n_items`, `n_overridden`, `n_excluded` (linhas de `exclusions.csv` aplicadas; os motivos não entram no relatório), `counts` (tipo → grau → split → nº de imagens; grau `"none"` para `other`), `items_per_grade` (tipo → grau → nº de peças), `images_per_item` (`min`, `median`, `mean`, `max`), `below_target` (lista de `{object_type, grade, n_images, n_items}` de `screw`/`nut` com menos de 120 imagens ou menos de 12 peças, `dataset-protocol.md` §4), `below_minimum` (mesmo formato, só as combinações `screw`/`nut` com menos de 8 peças). O relatório não contém pixels nem caminhos absolutos.

### 4.3 Concordância (`qc_ml.agreement`)

`python -m qc_ml.agreement --first <manifest.csv> --second <labels_second.csv> [--out ml/reports/agreement.json]`

- `labels_second.csv`: `image_path,grade,labeler`. O primeiro rótulo é o grau **original** do manifest (as overrides não se aplicam: elas resultam da discordância).
- **Exclusões:** os `image_path` de `load_exclusions(<diretório do --first>)` saem dos dois arquivos antes de formar os pares; um `image_path` excluído no segundo arquivo não é erro. O JSON ganha `n_excluded_pairs` (pares descartados por exclusão).
- Pares considerados: `image_path` presente nos dois, tipo `screw`/`nut`, grau não vazio nos dois. `image_path` do segundo arquivo ausente do primeiro, ou grau inválido → exit 2 com a lista dos problemas.
- Graus mapeados para 0..4 na ordem de `Grade`. `qwk = sklearn.metrics.cohen_kappa_score(a, b, weights="quadratic", labels=[0,1,2,3,4])`.
- JSON: `generated_at`, `n_pairs`, `qwk`, `exact_agreement`, `off_by_one_agreement`, `confusion` (5×5, linhas = primeiro, colunas = segundo), `grades` (ordem), `labeler_first`, `labeler_second`, `targets` (`{"minimum": 0.6, "desired": 0.8}`), `meets_minimum`, `meets_desired`, `first_sha256`, `second_sha256`. Com `n_pairs = 0` → exit 2.

### 4.4 Split (`qc_ml.split`)

```python
def make_split(df: pd.DataFrame, seed: int = 42, ratios: tuple[float, float, float] = (0.70, 0.15, 0.15),
               previous: pd.DataFrame | None = None,
               excluded: frozenset[str] = frozenset()) -> SplitResult  # .frame (image_path, split), .warnings
```

- **Unidade:** a peça (`item_id`). Todas as imagens de uma peça ficam no mesmo split (R-11).
- **Estrato** de cada peça: `(object_type, grau dominante)`. Grau dominante = o mais frequente entre as imagens da peça; empate → o mais severo; `other` → `"none"`.
- **Alocação determinística** (sem `previous`): estratos em ordem lexicográfica; dentro de cada um, `item_id` ordenados e permutados por um único `np.random.default_rng(seed)` percorrido nessa ordem. Com `n` peças: `n_test = round_half_up(0.15·n)`, `n_val = round_half_up(0.15·n)`, resto em treino; com `n ≥ 3`, no mínimo 1 em val e 1 em teste; com `n < 3`, todas em treino e um aviso `small_stratum` em `warnings`.
- **Congelamento (`previous` = split anterior):** peças já presentes mantêm o split (inclusive as **imagens novas** de uma peça antiga, que herdam o split da peça). Peças novas vão só para treino/val, na proporção 70:15 por estrato com a mesma regra de arredondamento. Imagem de **teste** do split anterior ausente do manifest → `SplitError`; imagem de treino/val ausente → aviso `missing_previous_image`.
- **Imagem excluída (SEC-10-08, R-14):** uma imagem do split anterior que está em `excluded` (de `load_exclusions`) sai do split novo, **inclusive do teste**, sem `SplitError`, com o aviso `excluded_previous_image` (`{"image_path", "split"}`). As demais linhas do split anterior não mudam, e nenhuma imagem muda de split. Tirar uma foto do teste por privacidade não usa o teste para nenhuma escolha e não é recriar o teste (R-11; `docs/dataset-protocol.md` §7). Uma imagem ausente do manifest **sem** exclusão continua como acima (`SplitError` no teste).
- **CLI:** `python -m qc_ml.split --dataset-dir ml/data --splits-dir ml/splits --seed 42` (passa `excluded=load_exclusions(dataset_dir)`). Sem `split_v*.csv` → cria `split_v1`. Com split existente → usa o de maior N como `previous` e grava `split_v{N+1}` **só se** houver mudança; sem mudança, não grava nada, imprime `split unchanged: split_v<N>` e sai com 0. Erros → exit 2.
- **Arquivos:** `split_v<N>.csv` com colunas `image_path,split` (ordenado por `image_path`, UTF-8, `\n`, sem índice); `split_v<N>.sha256` com `<hex>  split_v<N>.csv\n`; `split_v<N>.json` com `seed`, `ratios`, `parent` (`null` ou `split_v<N-1>`), `manifest_sha256`, contagens de imagens e peças por split e os `warnings`. Os três vão para o Git.
- `load_split(path) -> pd.DataFrame` confere o `.sha256` (diferente → `SplitError`). `rows_for(df, split_df, which: Literal["train","val","test"]) -> pd.DataFrame` é a **única** forma de obter as linhas de um split; imagem do manifest sem split → `SplitError("split outdated: run qc_ml.split")`.

### 4.5 Augmentations e dataset

- `augment.train_transform(img: PIL.Image, rng: np.random.Generator) -> PIL.Image` (RGB), na ordem: rotação uniforme em ±20° (preenchimento com a mediana RGB da borda da imagem, nunca preto); `RandomResizedCrop` para 256×256 com escala 0,7–1,0 e razão 3/4–4/3; flip horizontal e vertical (p = 0,5 cada); `ColorJitter` (brilho e contraste 0,3; saturação 0,2; matiz 0,02); blur gaussiano com p = 0,2 e sigma 0,1–1,0. Nada além disso (skill `ml-pipeline` §3).
- `PartsDataset(frame, dataset_dir, labels, params: PreprocessParams, *, train: bool, seed: int = 42)`; `__getitem__(i) -> (torch.Tensor float32 [3,224,224], type_idx: int, grade_idx: int)`. `type_idx` = posição em `labels.object_types` (`["screw","nut","other"]`); `grade_idx` = posição em `Grade` ou **−1** quando não há grau (máscara da loss na SPEC-012).
- Treino: `train_transform` com `rng = np.random.default_rng([seed, epoch, i])` (método `set_epoch(epoch)`), depois `qc_preprocess.preprocess`. Avaliação (`train=False`): **somente** `qc_preprocess.preprocess`.
- `data`, `split`, `agreement`, `augment` e `synthetic` não importam torch.

### 4.6 Dataset sintético

`make_synthetic_dataset(root: Path, *, items_per_stratum: int = 4, images_per_item: int = 2, include_other: bool = True, seed: int = 0) -> Path` cria `root/raw/<object_type>/<grade ou _>/<item_id>__<angle>__<ts>.jpg` (formato da SPEC-010) com JPEGs 256×256 (fundo claro; parafuso = retângulo, porca = hexágono, `other` = círculo; fração laranja crescente com o grau) e um `manifest.csv` válido. Item IDs `S-001…`, `N-001…`, `O-001…`.

## 5. Critérios de aceite

- **CA-01** — *Dado* um dataset sintético com 5 graus × 4 peças × 2 imagens para `screw` e `nut` e 4 peças `other` com 2 imagens, *quando* `load_manifest(root)` é chamado, *então* retorna 88 linhas, com as colunas do manifest mais `grade_original` e `overridden`, e grau `None` nas 8 linhas `other`.
- **CA-02** — *Dado* o dataset do CA-01 com o arquivo de 1 imagem apagado, *quando* `load_manifest` é chamado, *então* levanta `ManifestError` com exatamente 1 problema de código `missing_file` contendo o `image_path` apagado.
- **CA-03** — *Dado* 1 imagem sobrescrita com os bytes `b"not an image"`, *quando* `load_manifest` é chamado, *então* há 1 problema `unreadable_image`; com `verify_images=False`, nenhum erro.
- **CA-04** — *Dado* o `item_id` `S-001` com uma linha alterada para `object_type=nut`, *quando* `load_manifest` é chamado, *então* há um problema `item_type_conflict` citando `S-001` (e um `item_prefix_mismatch` na linha alterada).
- **CA-05** — *Dado* uma linha `other` com `grade=fair` e uma linha `screw` com grau vazio, *quando* `load_manifest` é chamado, *então* os problemas incluem `grade_on_other` e `missing_grade`, cada um com o número da linha correto.
- **CA-06** — *Dado* linhas com `grade=rusty`, `angle=7` e `item_id=X-1`, *quando* `load_manifest` é chamado, *então* os códigos `invalid_grade`, `invalid_angle` e `invalid_item_id` aparecem.
- **CA-07** — *Dado* um manifest com 3 problemas de tipos diferentes (arquivo ausente, `grade_on_other`, `invalid_angle`), *quando* `load_manifest` é chamado, *então* uma única `ManifestError` lista os 3, e `python -m qc_ml.data validate --dataset-dir <root>` sai com código 2 e imprime as 3 linhas.
- **CA-08** — *Dado* `labels_overrides.csv` com `image_path=<imagem fair de S-003>,grade=poor,labeler=b,reason=crosta`, *quando* `load_manifest` é chamado, *então* a linha tem `grade="poor"`, `grade_original="fair"`, `overridden=True`, e as demais linhas têm `overridden=False`.
- **CA-09** — *Dado* duas overrides para a mesma imagem (`good` e depois `poor`), *quando* aplicadas, *então* o grau final é `poor`. *Dado* uma override para um `image_path` inexistente, *então* há o problema `override_unknown_image`.
- **CA-10** — *Dado* uma linha `screw` com grau vazio e uma override que lhe atribui `good`, *quando* `load_manifest` é chamado, *então* não há erro.
- **CA-11** — *Dado* o dataset do CA-01 e o seu split, *quando* `python -m qc_ml.data report` roda, *então* o JSON tem as chaves de §4.2, `n_images = 88`, `n_items = 44`, e `below_target` tem exatamente as 10 combinações `screw`/`nut` × grau (todas com < 120 imagens).
- **CA-12 (R-11)** — *Dado* um dataset sintético com `items_per_stratum=20` e `images_per_item=3`, *quando* `make_split(df, seed=42)` roda, *então* a interseção dos conjuntos de `item_id` de treino, val e teste, dois a dois, é vazia, e todas as imagens de uma peça têm o mesmo split.
- **CA-13** — *Dado* o dataset do CA-12, *quando* o split é gerado, *então* cada estrato tem exatamente 14 peças em treino, 3 em val e 3 em teste.
- **CA-14** — *Dado* um estrato com 2 peças, *quando* o split é gerado, *então* as 2 peças estão em treino e `warnings` contém `small_stratum` com o nome do estrato.
- **CA-15** — *Dado* o mesmo manifest, *quando* a CLI de split roda duas vezes em diretórios vazios com `--seed 42`, *então* os dois `split_v1.csv` são idênticos byte a byte e o `.sha256` confere com `hashlib.sha256` do arquivo; com `--seed 7`, ao menos uma peça muda de split.
- **CA-16 (R-11, congelamento)** — *Dado* `split_v1` gerado e, depois, 5 peças novas de `screw/fair` e 2 imagens novas de uma peça que estava em teste, *quando* a CLI de split roda de novo, *então* é criado `split_v2.csv` em que todas as linhas do v1 mantêm o split, as imagens das 5 peças novas estão só em treino/val, e o teste tem exatamente as linhas de teste do v1 mais as 2 imagens novas.
- **CA-17** — *Dado* `split_v1` e nenhuma imagem nova, *quando* a CLI de split roda, *então* nenhum `split_v2.csv` é criado, a saída contém `split unchanged: split_v1` e o código de saída é 0.
- **CA-18** — *Dado* `split_v1` e uma imagem de teste removida do manifest e do disco, sem linha em `exclusions.csv`, *quando* a CLI de split roda, *então* sai com código 2, cita a imagem e não grava arquivo novo.
- **CA-19** — *Dado* `split_v1.csv` editado à mão (1 linha trocada de `test` para `train`), *quando* `load_split` é chamado, *então* levanta `SplitError` por hash divergente.
- **CA-20** — *Dado* um manifest com uma imagem ausente do split, *quando* `rows_for(df, split_df, "train")` é chamado, *então* levanta `SplitError` com `split outdated`.
- **CA-21** — *Dado* `first` com graus `[0,1,2,3,4,0,1,2,3,4]` e `second` com `[0,1,2,3,4,1,1,3,3,3]` (10 imagens `screw`, mapeados para os nomes de `Grade`), *quando* a CLI de concordância roda, *então* `agreement.json` tem `n_pairs = 10`, `qwk` = 0,9143 (32/35, tolerância 1e-4, igual ao `cohen_kappa_score` com `weights="quadratic"`), `exact_agreement = 0.7`, `off_by_one_agreement = 1.0`, `confusion[0][1] = 1`, `meets_minimum = true` e `meets_desired = true`.
- **CA-22** — *Dado* `first = [0,0,1,1,2,2,3,3,4,4]` e `second` invertido (`[4,4,3,3,2,2,1,1,0,0]`), *quando* a CLI roda, *então* `qwk` = −1,0 (±1e-6) e `meets_minimum = false`.
- **CA-23** — *Dado* `labels_second.csv` com um `image_path` que não está no manifest, *quando* a CLI de concordância roda, *então* sai com código 2 e não grava `agreement.json`.
- **CA-24** — *Dado* uma imagem RGB 300×200 e `rng = np.random.default_rng(1)`, *quando* `train_transform` é chamado duas vezes com geradores de mesma seed, *então* as duas saídas são idênticas, têm 256×256 e modo `RGB`.
- **CA-25** — *Dado* `PartsDataset(..., train=False)` (com `pytest.importorskip("torch")`), *quando* o item de uma imagem `nut/poor` é lido, *então* o tensor tem shape `(3, 224, 224)` e dtype `float32`, é igual a `qc_preprocess.preprocess(load_image(path), params)[0]` com `np.array_equal`, `type_idx = 1` e `grade_idx = 3`; para uma imagem `other`, `grade_idx = -1`.
- **CA-26 (CI sem torch)** — *Dado* um subprocesso Python com `sys.modules["torch"] = None`, *quando* importa `qc_ml.data`, `qc_ml.split`, `qc_ml.agreement`, `qc_ml.augment` e `qc_ml.synthetic`, *então* não ocorre `ImportError`.
- **CA-27 (R-02/R-14)** — *Dado* o repositório depois da SPEC, *quando* `git ls-files ml` é listado, *então* não há nenhum `.jpg`, `.jpeg` ou `.png` fora de `ml/reports/`; os testes criam as imagens em `tmp_path`.
- **CA-28 (SEC-24-03)** — *Dado* o dataset do CA-01 com 1 imagem `screw` reescrita como os próprios bytes seguidos de `b"\xff\xda" * 64` depois do EOI (o JPEG sintético é baseline, com 1 marcador, e o arquivo passa a ter 65; simula o vídeo anexado pela "foto com movimento") e outra imagem sobrescrita com `b"not an image"`, *quando* `load_manifest` é chamado, *então* a `ManifestError` tem exatamente 1 problema `too_many_jpeg_scans`, com o `image_path` da primeira e uma `message` que contém `JPEG scans` e `dataset-protocol`, e exatamente 1 `unreadable_image`, com o `image_path` da segunda; `python -m qc_ml.data validate --dataset-dir <root>` sai com código 2, e a saída contém as linhas `count too_many_jpeg_scans: 1` e `count unreadable_image: 1`, nessa ordem; e, com `verify_images=False`, nenhum erro.
- **CA-29 (SEC-10-03)** — *Dado* o dataset do CA-01 com o manifest reescrito pelo teste (com `csv.writer`) de modo que uma linha tenha `notes="a b c‮d"` e outra `capture_device="Phone\x85X"`, *quando* `load_manifest` é chamado, *então* retorna 88 linhas, sem erro, e as duas células voltam iguais às escritas; e o `str.splitlines()` do arquivo dá mais de 89 linhas (o teste confirma que a leitura não depende dele).
- **CA-30 (SEC-10-02)** — *Dado* o dataset do CA-01 com mais um arquivo `raw/screw/fair/S-099__0__20261022T141503Z.jpg` (JPEG válido, sem linha no manifest) e um arquivo `raw/screw/fair/tmpab12cd` (sem extensão), *quando* `load_manifest` é chamado com `verify_images=True` e, depois, com `verify_images=False`, *então* nos dois casos a `ManifestError` tem exatamente 1 problema, `orphan_image`, com `image_path="raw/screw/fair/S-099__0__20261022T141503Z.jpg"` e `line` igual a `None`; e `python -m qc_ml.data validate` sai com código 2 e imprime `count orphan_image: 1`.
- **CA-31 (SEC-10-08, R-14)** — *Dado* o dataset do CA-01 com o arquivo de 1 imagem de `S-002` apagado e `exclusions.csv` com `image_path=<essa imagem>,reason=person`, *quando* `load_manifest` é chamado, *então* não há erro, o resultado tem 87 linhas e não contém o `image_path` excluído, e o relatório de dados tem `n_excluded = 1`. *Dado* o mesmo `exclusions.csv` com o arquivo ainda em disco, *então* há o problema `excluded_file_present` com esse `image_path`; com `reason=selfie`, `exclusion_invalid_reason`; com um `image_path` que não está no manifest, `exclusion_unknown_image`. *Dado* um `labels_override` para a imagem excluída, *então* ele é ignorado sem erro. *Dado* `labels_second.csv` com essa imagem e outras 9 do manifest (`screw`/`nut`), *quando* a CLI de concordância roda, *então* sai com 0, `n_pairs = 9` e `n_excluded_pairs = 1`.
- **CA-32 (SEC-10-08, R-11)** — *Dado* `split_v1` gerado e, depois, 1 imagem que estava em **teste** apagada do disco e registrada em `exclusions.csv` (`reason=person`), *quando* a CLI de split roda, *então* sai com 0 e cria `split_v2.csv` sem essa imagem, com todas as outras linhas do `split_v1` no mesmo split, e o `split_v2.json` tem em `warnings` um `excluded_previous_image` com esse `image_path` e `split="test"`.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Cada validação, overrides, estratos, arredondamento, congelamento, augment, gerador sintético | `ml/tests/` |
| Aceite (tester) | Um por CA, com `make_synthetic_dataset` em `tmp_path`; CLIs via `main(argv)` ou subprocesso | `ml/tests/acceptance/test_spec_011.py` |
| Manual (dupla) | Rodar `validate`, `split` e `agreement` com os dados reais (S3) e commitar `split_v1.*`, `data_report.json` e `agreement.json` | — |

Nada é mockado além do sistema de arquivos temporário. O CA-25 usa `pytest.importorskip("torch")` e não roda no CI; os demais rodam sem torch.

## 7. Riscos e notas para o implementador

- Cada CLI expõe `main(argv: list[str] | None = None) -> int`; use `logging`, não `print`, exceto na saída da CLI.
- O `.gitignore` ignora qualquer diretório `data/`: `qc_ml/data.py` precisa ser um **módulo**.
- `round_half_up` explícito (o `round` do Python arredonda para o par).
- Proporções finais de **imagens** podem divergir de 70/15/15 porque o número de fotos por peça varia; o `split_v<N>.json` registra as contagens reais.
- Com poucos dados por estrato (ex.: `unusable` de porca), o teste pode ficar com 1 peça só. Registre no relatório de dados; não altere a regra sem ADR.
- `split_v1` só deve ser gerado com os dados reais da S3 (marco "teste final congelado" do `docs/plan.md`).
- **Planilhas (SEC-10-04):** nenhuma saída desta SPEC é CSV para abrir em planilha (`split_v<N>.csv` só tem caminhos montados pela borda e o nome do split). Se uma SPEC futura exportar para planilha um CSV com texto livre (`notes`, `capture_device`, `reason`), as células que começam com `=`, `+`, `-` ou `@` recebem o prefixo `'`. O manifest não é aberto em planilha (`docs/dataset-protocol.md` §5).
- **`flock` do manifest (SEC-10-06):** o pipeline não toma o `manifest.csv.lock` da borda e lê o manifest de uma vez. Se um script de backup ou de cópia precisar do lock, segura-o só pelo tempo da cópia; um lock segurado por muito tempo faz o modo coleta esperar e o modo inspeção responder 503 `server busy`.
- **Exclusões:** `exclusions.csv` vai para o backup junto com o manifest (não contém imagem). O `reason` é um código fixo, nunca texto livre, para não guardar dado pessoal da foto.
- **`too_many_jpeg_scans` (SEC-24-03):** não "conserte" a foto no pipeline. Não corte os bytes depois do primeiro `FF D9` e não reconte os marcadores de outro jeito: um `FF D9` pode aparecer dentro de um segmento APPn ou COM, e a contagem ficaria abaixo do número real de scans, o que reabriria o ataque fechado pela SPEC-024. Também não use `verify_images=False` para fazer a validação passar. O caminho é refotografar com a "foto com movimento" desligada (`docs/dataset-protocol.md` §3).

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED
- [ ] CI verde (sem torch); `ruff` limpo
- [ ] README de `ml/` com os comandos de `validate`, `report`, `split` e `agreement`
- [ ] PR aberto com os relatórios; merge humano

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-12 | §4.1: problema novo `too_many_jpeg_scans` (a mensagem do `load_image` contém `JPEG scans`), separado de `unreadable_image`, e linhas de resumo `count <code>: <n>` no `validate`. CA-28 novo. §7: não cortar no `FF D9`, não recontar e não usar `verify_images=False` para contornar. Nenhum CA existente muda (o CA-07 continua imprimindo as 3 linhas de problema; o resumo vem depois delas). SPEC marcada como "Aguardando reaprovação humana". | SEC-24-03 de `reviews/SPEC-024/r1-security-report.md` | Orquestrador, a pedido do humano |
| 2026-10-12 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
| 2026-10-17 | Mudanças: (a) §1 com as pendências da SPEC-010; (b) §3: `load_exclusions` e órfãos no `data.py`; a varredura de privacidade fica na SPEC-025; (c) §4.1: leitura só com `csv`/`pandas`, `exclusions.csv` (`image_path,reason`, `reason` ∈ `person`/`other`) e problemas novos `orphan_image`, `exclusion_unknown_image`, `exclusion_invalid_reason` e `excluded_file_present`; (d) §4.2: `n_excluded`; (e) §4.3: exclusões na concordância e `n_excluded_pairs`; (f) §4.4: parâmetro `excluded` e aviso `excluded_previous_image` (imagem excluída sai do split novo, inclusive do teste, sem `SplitError`); (g) CA-18 passa a apagar também o arquivo (senão o `orphan_image` passaria o CA pelo motivo errado); CAs novos CA-29 a CA-32; (h) §7: planilhas, `flock` e exclusões. Nenhum outro CA muda. SPEC marcada como "Aguardando reaprovação humana". | SEC-10-02, SEC-10-03, SEC-10-04, SEC-10-06 e SEC-10-08 de `reviews/SPEC-010/r1-security-report.md` | Orquestrador, a pedido do humano |
