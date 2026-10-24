# SPEC-035: ML — origem das imagens (fotos de conhecidos e imagens externas), split só no treino para as externas e atribuições

| Campo | Valor |
|---|---|
| Status | In Review |
| Rodada atual | r1 |
| Autor da implementação | ml-engineer |
| Tags | — |
| Depende de | SPEC-031 (`ITEM_ID_PATTERN` único), SPEC-011, SPEC-012 |
| Semana alvo | S3, **antes** do `split_v1` (só as fotos de conhecidos importadas antes dele podem cair no teste, ADR-014) |
| Requisitos cobertos | RF-08 (consumo do manifest), RF-12 (`metrics.json`), RNF-07; R-11, R-14 |
| ADRs relevantes | ADR-020 (`Aceito`), ADR-014, ADR-004, ADR-001 |

## 1. Contexto

Pela decisão do humano de 2026-10-19 (ADR-020), o dataset passa a receber, além das fotos da página `/capture`:

- **fotos de conhecidos** (origem `contributor`), tiradas em outros celulares, que valem como fotos próprias e seguem o split normal (R-11);
- **imagens externas** (origem `external`), de datasets públicos ou da internet, com licença da lista fechada do §4.3 (sem NonCommercial nem ShareAlike, decisão do humano de 2026-10-23), que vão **só para o treino**.

Esta SPEC é a parte do `qc-ml` (`docs/architecture.md` §7; skill `ml-pipeline` §1, §2 e §5): o formato que identifica a origem de cada imagem, a validação, a regra do split, o relatório de dados, as métricas e as atribuições. Quem grava as imagens importadas e os arquivos novos no `DATASET_DIR` é a CLI de importação da borda, `python -m qc_edge.importer` (SPEC-036, developer), que segue os formatos definidos aqui (§4.2 e §4.3).

**Por que duas SPECs.** O hook de guarda de caminhos (SPEC-001 §4.6) limita o ml-engineer a `ml/**` e proíbe o developer de escrever em `ml/**`. A gravação no dataset reaproveita o `DatasetWriter`, o `flock`, as permissões e o `fsync` de `qc_edge.collect` (SPECs 010 e 025), que o `qc-ml` não importa. Por isso a importação fica na borda e a leitura, no `qc-ml`.

**Por que o manifest não muda** (ADR-020, opção D): o manifest tem 9 colunas fixas, e a borda recusa outro cabeçalho (SPEC-010 §4.2). Uma coluna nova exigiria reescrever todas as linhas já gravadas. A origem fica num arquivo à parte, `DATASET_DIR/sources.csv`, como o `labels_overrides.csv` e o `exclusions.csv`. A regra de integridade (externa nunca em validação ou teste) depende só do `item_id`, que está em toda linha do manifest, e não desse arquivo.

## 2. Objetivo

`python -m qc_ml.data validate` aceita e confere as imagens importadas, `python -m qc_ml.split` põe toda imagem externa no treino em todas as versões do split (e recusa o contrário), e o relatório de dados, o `metrics.json` e o CHANGELOG mostram a contagem por origem e citam as fontes externas com a licença.

## 3. Escopo

### 3.1 Dentro

- `ml/src/qc_ml/data.py`:
  - `ITEM_ID_PATTERN` com o formato das externas, `item_type_letter` e `is_external_item` (§4.1);
  - `load_sources` e a leitura de `DATASET_DIR/sources.csv` no `load_manifest` (§4.2);
  - `load_external_sources` e o registro `ml/external_sources.csv` (§4.3);
  - colunas novas no resultado do `load_manifest` (§4.2) e chaves novas no relatório de dados (§4.5);
  - opção `--external-sources` nas CLIs `validate` e `report`.
- `ml/src/qc_ml/split.py`: regra das externas, teto, `IMAGE_FILE_PATTERN` e a guarda do `rows_for` (§4.4); opções `--external-sources` e `--max-external-fraction` da CLI.
- `ml/src/qc_ml/evaluate.py`: `by_origin` e `by_source` em `counts` (§4.6).
- `TrainConfig` (no módulo em que está definido hoje): campo `external_sources` (§4.6).
- `ml/src/qc_ml/report.py`: seção "Dados" da entrada do CHANGELOG, opção `--external-sources` e subcomando `release-notes`, que gera as notas do GitHub Release do modelo com os créditos das fontes externas (§4.6).
- `ml/src/qc_ml/synthetic.py`: parâmetros `external_items_per_stratum` e `contributor_items_per_stratum` (§4.7).
- `ml/external_sources.csv` (novo, só com o cabeçalho; as linhas são acrescentadas pela dupla, §4.3).
- `ml/README.md`: seção "Origem das imagens" (§4.8).
- Testes do autor em `ml/tests/` (fora de `acceptance/`).
- **Tester:** `ml/tests/acceptance/test_spec_035.py`. Nenhum ajuste em testes de aceite antigos é esperado: com `sources.csv` ausente e as contagens novas zeradas, os resultados das SPECs 011 e 012 não mudam, e os testes delas conferem as colunas e as chaves de `counts` por inclusão. Se algum falhar por causa de um requisito escrito aqui, vale a regra "Testes de aceite de SPECs anteriores" de `docs/architecture.md` §10.

### 3.2 Fora

- A CLI de importação, a normalização da imagem, a gravação de `sources.csv` e a tabela de cobertura do console: SPEC-036.
- Ferramentas (`T-`, `XT-`): SPEC-016. Até lá, `T-` e `XT-` continuam recusados (`item_prefix_mismatch`, §4.1).
- Detectar automaticamente pessoas ou rostos: não adotado (ADR-020; checagem humana, `docs/dataset-protocol.md` §10.5).
- Baixar datasets, recortar caixas de datasets de detecção e escolher as fontes: tarefa da dupla (§4.3 e Anexo A).
- Mostrar a origem na página "Sobre o modelo" do dashboard (SPEC-028): fora; o painel continua lendo só o que já lê do `metrics.json`.
- Usar imagens externas na validação ou no teste: exige um ADR novo (ADR-020).

## 4. Requisitos detalhados

### 4.1 `item_id` das imagens externas

- `qc_ml.data.ITEM_ID_PATTERN = re.compile(r"[SNOT]-[0-9]{3}|X[SNOT]-[0-9]{4}")`, conferido sempre com `fullmatch` (`docs/architecture.md` §3.2). É o único objeto com essa regex no `qc_ml` (SPEC-031 §4.6): o `qc_ml.split` a importa.
- `item_type_letter(item_id: str) -> str`: a letra do tipo, `item_id[1]` quando o `item_id` começa com `X` e `item_id[0]` nos demais. `is_external_item(item_id: str) -> bool`: `True` se, e só se, o `item_id` casa o padrão e começa com `X`.
- `item_prefix_mismatch` passa a comparar `ITEM_PREFIX_TYPES.get(item_type_letter(item_id))` com o `object_type`. Com isso, `XS-0001` exige `screw`, `XN-` exige `nut` e `XO-` exige `other`; `XT-` e `T-` continuam sem tipo válido no MVP.
- `qc_ml.split.IMAGE_FILE_PATTERN` (a fonte 3 do `item_id`, SPEC-011 §4.4) passa a ser montado a partir de `ITEM_ID_PATTERN.pattern`: `re.compile("(" + ITEM_ID_PATTERN.pattern + r")__[0-4]__[0-9]{8}T[0-9]{6}Z\.jpg")`. A fonte 2 (`excluded_items`) usa `ITEM_ID_PATTERN.fullmatch`. Nenhuma regex de `split.py` tem `[SNOT]` literal (CA-09 da SPEC-031).
- A origem `external` de uma imagem é decidida **só** por `is_external_item`, nunca pelo `sources.csv`. O `sources.csv` confirma a origem e traz a fonte (§4.2).

### 4.2 `DATASET_DIR/sources.csv`

Gravado pela SPEC-036, uma linha por imagem importada. UTF-8 sem BOM, `\n`, cabeçalho **exatamente** `image_path,origin,contributor,source_id,source_ref,input_sha256`. Uma imagem do manifest sem linha aqui tem origem `capture`. O arquivo é opcional: ausente, todas as imagens são `capture` (e nenhuma pode ser externa).

| Coluna | Regra |
|---|---|
| `image_path` | mesma regra do manifest (`invalid_image_path`, SPEC-011 §4.1); tem de existir no manifest |
| `origin` | `contributor` ou `external` (igualdade exata) |
| `contributor` | `re.fullmatch(r"c[0-9]{2}", valor)` quando `origin=contributor`; vazio quando `external`. É um código de pseudônimo (`c01`): nunca o nome nem o telefone do conhecido |
| `source_id` | quando `external`: presente no registro (§4.3); vazio quando `contributor` |
| `source_ref` | quando `external`: de 1 a 200 caracteres, nenhum nas categorias Unicode `Cc`, `Cs`, `Cf`, `Zl` e `Zp` (o caminho ou o nome do arquivo dentro da fonte); vazio quando `contributor` |
| `input_sha256` | 64 caracteres hexadecimais minúsculos (`re.fullmatch(r"[0-9a-f]{64}", valor)`): o SHA-256 do arquivo **recebido**, antes da normalização. Serve para recusar a mesma importação duas vezes |

```python
def load_sources(dataset_dir: Path | str, registry: Mapping[str, ExternalSource]) -> pd.DataFrame
```

- Leitura só com `csv`/`pandas` (`dtype=str`, `keep_default_na=False`), como o manifest (SPEC-011 §4.1).
- No `load_manifest`, depois das exclusões e das overrides, cada linha do resultado ganha:
  - `origin`: `capture`, `contributor` ou `external`;
  - `contributor`: o código, ou `None`;
  - `source_id`: o id da fonte, ou `None`.
- As linhas de `sources.csv` cujo `image_path` está em `exclusions.csv` são ignoradas, como as overrides (SPEC-011 §4.1): não geram problema de linha nem entram em `duplicate_input`. O `source_unknown_image` e o `duplicate_source_row` continuam conferidos sobre o arquivo inteiro.
- `df.attrs` ganha `sources_sha256` (hash do `sources.csv` lido, ou `None` sem o arquivo) e `external_sources_sha256` (hash do registro lido, ou `None` sem o arquivo).
- `load_manifest` ganha o parâmetro nomeado `external_sources: Path | str | None = None`. Com `None`, usa `DEFAULT_EXTERNAL_SOURCES = Path(qc_ml.__file__).resolve().parents[2] / "external_sources.csv"` (o `ml/external_sources.csv` do repositório, também no Colab, que clona o repositório). Registro ausente = registro vazio: não é erro, mas toda linha `external` vira `unknown_source_id`.
- Os problemas entram na mesma `ManifestError` (um por linha, com `file="sources.csv"` ou `file="external_sources.csv"`), e o `validate` os conta no resumo `count <code>: <n>` (SPEC-011 §4.1).

| `code` | Condição |
|---|---|
| `missing_column`, `unreadable_csv`, `malformed_row`, `invalid_image_path` | como na SPEC-011 §4.1, agora também para `sources.csv` e `external_sources.csv` |
| `source_unknown_image` | linha de `sources.csv` com `image_path` ausente do manifest |
| `duplicate_source_row` | o mesmo `image_path` em duas linhas de `sources.csv` |
| `invalid_origin` | `origin` fora de `contributor` e `external` (inclusive `capture` e vazio) |
| `invalid_contributor` | `contributor` fora do formato quando `contributor`, ou preenchido quando `external` |
| `source_fields_mismatch` | `source_id` ou `source_ref` preenchido numa linha `contributor` |
| `unknown_source_id` | linha `external` com `source_id` vazio ou ausente do registro |
| `invalid_source_ref` | `source_ref` vazio, com mais de 200 caracteres ou com caractere proibido numa linha `external` |
| `invalid_input_sha256` | `input_sha256` fora do formato |
| `duplicate_input` | o mesmo `input_sha256` em duas linhas não excluídas |
| `missing_source` | imagem de um `item_id` externo (`is_external_item`) sem linha em `sources.csv` |
| `external_item_mismatch` | linha `external` cujo `item_id` (no manifest) não é externo, ou linha `contributor` cujo `item_id` é externo |

### 4.3 Registro das fontes externas (`ml/external_sources.csv`, no Git)

Uma linha por fonte (dataset ou página da internet). É o arquivo de atribuições do projeto: entra no Git, nunca contém imagens e nunca perde linhas (uma fonte retirada continua listada, porque um modelo antigo foi treinado com ela; as imagens dela saem por `exclusions.csv`, `docs/dataset-protocol.md` §8.1). As linhas são acrescentadas pela dupla, por PR, depois de conferir a licença na página oficial da fonte.

UTF-8 sem BOM, `\n`, cabeçalho **exatamente** `source_id,title,url,license,license_url,attribution,retrieved_at`.

| Coluna | Regra | `code` |
|---|---|---|
| `source_id` | `re.fullmatch(r"[a-z0-9][a-z0-9-]{2,39}", valor)`; único no arquivo | `invalid_source_id`, `duplicate_source_id` |
| `title` | 1 a 200 caracteres, sem as categorias proibidas do §4.2 | `invalid_text` |
| `url` | `https://`, de 9 a 300 caracteres, só ASCII visível (`0x21`–`0x7E`) | `invalid_url` |
| `license` | um de `ALLOWED_LICENSES = ("CC0-1.0", "PDDL-1.0", "CC-BY-4.0", "MIT", "Apache-2.0", "BSD-3-Clause")` (igualdade exata, ADR-020, decisão 3). Qualquer outro valor, inclusive as NonCommercial e ShareAlike (`CC-BY-NC-4.0`, `CC-BY-SA-4.0`, `CC-BY-NC-SA-4.0`), as NoDerivatives e o vazio, é recusado | `invalid_license` |
| `license_url` | mesma regra de `url` | `invalid_url` |
| `attribution` | 1 a 500 caracteres, sem as categorias proibidas: o texto de crédito que a licença exige (autores, título, link) | `invalid_text` |
| `retrieved_at` | data `AAAA-MM-DD` válida (`date.fromisoformat` com `re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", valor)`) | `invalid_date` |

```python
@dataclass(frozen=True)
class ExternalSource: source_id: str; title: str; url: str; license: str; license_url: str; attribution: str; retrieved_at: date
def load_external_sources(path: Path | str) -> dict[str, ExternalSource]   # levanta ManifestError com os problemas acima
```

- O repositório passa a ter `ml/external_sources.csv` com o cabeçalho e nenhuma linha. Ele não pode ser ignorado pelo Git.
- O registro é validado inteiro sempre que o `load_manifest` o lê, mesmo que nenhuma imagem o use.

### 4.4 Split (`qc_ml.split`)

Muda só isto na SPEC-011 §4.4:

- **Externas sempre no treino.** Em `make_split`, toda imagem cujo `item_id` é externo vai para `train`, em qualquer versão, com ou sem `previous` e `history`. As peças externas **não** entram nos estratos, na permutação nem no arredondamento: a alocação das demais peças é feita como se elas não existissem. Assim, acrescentar ou tirar imagens externas não muda o split de nenhuma peça própria ou de conhecido, e o aviso `small_stratum` só conta as peças não externas.
- **Integridade.** Uma peça externa com imagem em `val` ou `test` no `previous`, ou com `history[item_id]` diferente de `train`, levanta `SplitIntegrityError` com o `item_id` na mensagem. O mesmo vale no `item_history`, para qualquer versão anterior. Nada é gravado.
- **`rows_for` (guarda única).** `rows_for(df, split_df, "val")` e `rows_for(df, split_df, "test")` levantam `SplitIntegrityError("external image in <which>: <item_id>")` se alguma linha devolvida tiver `item_id` externo. Como o `rows_for` é a única forma de obter as linhas de um split (SPEC-011 §4.4), os limiares e o early stopping (validação) e o `evaluate` (teste) nunca veem uma imagem externa, mesmo com um split editado à mão.
- **Teto da fração externa no treino.** `make_split` ganha o último parâmetro `max_external_fraction: float = 0.30`. Depois da alocação, se `Fraction(n_externas_treino, n_imagens_treino) > Fraction(str(max_external_fraction))`, levanta `SplitError` com a mensagem `external fraction in train <n_externas>/<n_treino> above <max_external_fraction>`. A comparação é exata (sem `float`), então o teto em si é aceito. Fora de `0 < max_external_fraction <= 1` → `ValueError`. Sem imagens no treino, não há teto a conferir.
- **CLI.** `python -m qc_ml.split ... [--external-sources <arquivo>] [--max-external-fraction <x>]`. O segundo aceita um número decimal em `(0, 1]`; outro valor sai com 2, sem gravar nada. O `SplitError` do teto sai com 2, com a mensagem acima na saída de erro, e não grava nada.
- **`split_v<N>.json`** ganha `max_external_fraction` (o valor usado), `external_fraction_train` (`n_externas_treino / n_imagens_treino`, ou `null` sem treino) e, nas contagens por split, `n_external_images`. O `split_v<N>.csv` e o `.sha256` não mudam de formato.

### 4.5 Relatório de dados (`build_data_report`)

Chaves novas, além das da SPEC-011 §4.2:

- `counts_by_origin`: origem (`capture`, `contributor`, `external`, sempre as três) → `{"n_images", "n_items", "by_split"}`, em que `by_split` tem sempre as chaves `train`, `val` e `test` (nº de imagens, inclusive 0), ou é `{}` sem split;
- `n_contributors`: nº de códigos `contributor` distintos (nunca os códigos);
- `by_source`: `source_id` → nº de imagens (vazio sem externas);
- `external_fraction_train`: como no `split_v<N>.json`, ou `null` sem split.

Mudam de escopo, sem mudar de formato: `items_per_grade`, `images_per_item`, `below_target` e `below_minimum` passam a contar **só** as imagens não externas. As metas de volume (`docs/dataset-protocol.md` §4) são de peças físicas fotografadas pela dupla ou por conhecidos, e cada imagem externa é uma peça. `n_images`, `n_items` e `counts` continuam contando todas as imagens. Sem imagens externas, todas as chaves antigas dão os mesmos valores de hoje.

### 4.6 Métricas, CHANGELOG e notas do Release

- **Registro nas etapas do pipeline:** `TrainConfig` (SPEC-012 §4.2) ganha o campo `external_sources: str | None = None`, o caminho do registro passado ao `load_manifest` por `train`, `thresholds`, `evaluate` e `pipeline` (`None` = `DEFAULT_EXTERNAL_SOURCES`, §4.2). Não é um hiperparâmetro e não entra em `deviations_from_defaults`. As configs existentes, sem o campo, continuam válidas.
- `qc_ml.evaluate.split_counts` acrescenta a cada split de `counts`:
  - `by_origin`: `{"capture": n, "contributor": n, "external": n}` (nº de imagens, sempre as três chaves);
  - `by_source`: `source_id` → nº de imagens (vazio quando não há externas).

  As chaves de topo do `metrics.json` **não** mudam (SPEC-012 §4.7). Pela §4.4, `counts.val.by_origin.external` e `counts.test.by_origin.external` são sempre 0; é o que mostra, no próprio artefato, que validação e teste não têm imagem externa.
- `python -m qc_ml.report changelog ... [--external-sources <arquivo>]` acrescenta à entrada, depois da tabela de métricas, a seção `### Dados`:
  - `- Validação e teste: <e_val> e <e_test> imagens externas (ADR-020).`;
  - `- Treino: <e_train> imagens externas de <n_train> (<fração>).`, com a fração exibida com 4 casas e vírgula decimal, arredondada para cima (`ROUND_CEILING`, a mesma forma de `docs/architecture.md` §7: a fração exibida nunca fica menor que a medida);
  - uma linha por fonte de `counts.train.by_source`, em ordem de `source_id`: `` - `<source_id>`: <n> imagens, <license>. Crédito: <attribution> `` (lidos do registro); fonte ausente do registro → `` - `<source_id>`: <n> imagens, licença não encontrada no registro ``.

  Um `metrics.json` sem `by_origin` (gerado antes desta SPEC) não ganha a seção. A tabela de métricas e as demais seções não mudam (CA-25 da SPEC-012).

**Notas do Release (`release-notes`).** Os créditos das fontes externas têm de aparecer na **própria página** do GitHub Release do modelo, e não só no CHANGELOG ou no registro (decisão do humano de 2026-10-23). O texto das notas é gerado, nunca escrito à mão:

```text
python -m qc_ml.report release-notes --model-dir <dir> [--external-sources <arquivo>] [--output <arquivo>]
```

- **Entradas:** `<dir>/model.sha256` (64 hex minúsculos + `\n`, SPEC-012 §4.3) e `<dir>/metrics.json`. `--external-sources` tem o mesmo padrão do `changelog` (`DEFAULT_EXTERNAL_SOURCES`, §4.2) e é lido com `load_external_sources` (§4.3). Registro ausente = registro vazio.
- **Saída:** sem `--output`, o texto vai para o stdout. Com `--output`, o arquivo é criado ou sobrescrito, em UTF-8 sem BOM, com `\n`, e o stdout fica vazio. Nos dois casos, o conteúdo é o mesmo, byte a byte, e termina com um único `\n`.
- **Texto** (Markdown, que a página do Release renderiza), nesta ordem, com uma linha em branco entre os blocos:
  1. `sha256: <os 64 hex do model.sha256>` (a mesma linha que a SPEC-012 §4.9 punha em `--notes`);
  2. `## Fontes externas e créditos`;
  3. **com fonte externa** (`counts.train.by_source` presente e não vazio): uma linha por fonte, na **mesma ordem** da seção `### Dados` do CHANGELOG (ordem de `source_id`) e com o mesmo `<n>`, `` - `<source_id>`: <n> imagens, <license>. Crédito: <attribution> | Licença: <license_url> | Fonte: <url> `` (lidos do registro). Toda fonte de `counts.train.by_source` tem de estar no registro: se alguma faltar, o comando **falha** (ver "Erros"), para que nunca se gere notas sem o crédito completo. O `changelog` continua só marcando a linha (`licença não encontrada no registro`), sem falhar;
     **sem fonte externa** (`counts.train.by_source` vazio, ou `counts` sem `by_source`, caso de um `metrics.json` gerado antes desta SPEC, quando o pipeline recusava `item_id` externo): a linha única `Este modelo não usa imagens externas (ADR-020).`;
  4. ``Registro das fontes: `ml/external_sources.csv`. Histórico do modelo: `ml/models/CHANGELOG.md`.``
- **Erros** (código 2, mensagem na saída de erro, stdout vazio e `--output` nem criado nem alterado): `model.sha256` ausente ou fora do formato; `metrics.json` ausente ou JSON inválido; registro com algum problema do §4.3 (`ManifestError`); **fonte usada no treino ausente do registro**. Neste último caso, a saída de erro tem uma linha `source not in registry: <source_id>` por fonte ausente, em ordem de `source_id`. O `source_id` vem do `metrics.json` e só é impresso se casar `re.fullmatch(r"[a-z0-9][a-z0-9-]{2,39}", valor)` (o formato do §4.3); senão, a linha é `source not in registry: <invalid source_id>`, sem ecoar o valor. Toda a validação é feita antes de abrir o `--output`.
- Os textos vêm do registro, que já recusa caracteres de controle e separadores de linha (§4.3): cada fonte ocupa exatamente uma linha. Nenhuma outra informação do `metrics.json` entra nas notas.

### 4.7 Dataset sintético

`make_synthetic_dataset(root, *, items_per_stratum=4, images_per_item=2, include_other=True, seed=0, external_items_per_stratum=0, contributor_items_per_stratum=0)`. "Estrato" = cada um dos 10 pares `screw`/`nut` × grau e, com `include_other`, o `other`.

- `contributor_items_per_stratum = c`: em cada estrato, `c` peças de conhecido, numeradas a partir de 501 por letra (`S-501`, `S-502`…; a numeração continua entre os estratos da mesma letra), cada uma com `images_per_item` imagens, e uma linha `contributor` em `sources.csv` por imagem, com `contributor=c01`.
- `external_items_per_stratum = k`: em cada estrato, `k` peças externas, numeradas a partir de `0001` por letra (`XS-0001`…), cada uma com **1** imagem (ângulo 0), e uma linha `external` por imagem, com `source_id=synthetic` e `source_ref=synthetic/<item_id>.png`. O gerador grava também `root/external_sources.csv` com uma única fonte `synthetic` (`CC0-1.0`, `url` = `https://example.org/synthetic`, `license_url` = `https://creativecommons.org/publicdomain/zero/1.0/`, atribuição `Synthetic test images`, `retrieved_at` = `2026-10-20`).
- O `input_sha256` das linhas é o SHA-256 do arquivo gravado (o sintético não tem arquivo recebido).
- Com `c = 0` e `k = 0` (o padrão), os arquivos gerados são iguais, byte a byte, aos de hoje, e nem o `sources.csv` nem o `external_sources.csv` são criados.

### 4.8 `ml/README.md`

Seção "Origem das imagens": as três origens; o formato do `item_id` externo; `sources.csv` (gravado só pela importação da SPEC-036, nunca à mão); o registro `ml/external_sources.csv` e as licenças aceitas; "externas só no treino" e o teto (`--max-external-fraction`); e a referência a `docs/dataset-protocol.md` §10.

A mesma seção traz o passo do Release (SPEC-012 §4.9), que passa a ser o abaixo. O passo antigo do README, com `--notes "sha256: …"`, é trocado por uma referência a esta seção:

```text
python -m qc_ml.report release-notes --model-dir ml/models/<v> --output ml/models/<v>/release-notes.md
gh release create model-<v> ml/models/<v>/model.onnx --title "Modelo <v>" --notes-file ml/models/<v>/release-notes.md
```

O README diz que: as notas do Release são **sempre** o arquivo gerado (nunca `--notes` à mão); se o modelo usou imagens externas, a seção "Fontes externas e créditos" com o crédito, a licença e os links de cada fonte é **obrigatória** na página do Release (as licenças com atribuição, como `CC-BY-4.0`, `MIT`, `Apache-2.0` e `BSD-3-Clause`, exigem o crédito); e, se o `release-notes` sair com `source not in registry`, a fonte tem de ser registrada (§4.3) antes de gerar as notas de novo: sem isso, não há notas nem Release. A linha `licença não encontrada no registro` só aparece no CHANGELOG, como marca. O `release-notes.md` pode ir para o Git junto com o `model.sha256`.

## 5. Critérios de aceite

Contexto comum: datasets do `make_synthetic_dataset` em `tmp_path`, sempre com `external_sources=<root>/external_sources.csv` (nunca o registro do repositório, salvo no CA-14). "Dataset 4/2" = `items_per_stratum=4, images_per_item=2`; "dataset 20/3" = `items_per_stratum=20, images_per_item=3` (o do CA-12 da SPEC-011).

- **CA-01** — *Dado* `qc_ml.data.ITEM_ID_PATTERN`, *quando* `fullmatch` é aplicado, *então* casam `S-012`, `O-500`, `XS-0001`, `XN-9999` e `XO-0042`, e não casam `XS-001`, `XS-00001`, `X-0001`, `XX-0001`, `xS-0001`, `SX-0001`, `XS-0001\n` e `XS-０００１` (dígitos de largura total); `is_external_item("XN-0002")` é `True` e `is_external_item("N-002")` é `False`; `item_type_letter("XO-0042") == "O"`; `qc_ml.split.ITEM_ID_PATTERN is qc_ml.data.ITEM_ID_PATTERN`; e `qc_ml.split.IMAGE_FILE_PATTERN.fullmatch("XS-0001__0__20261022T141503Z.jpg").group(1) == "XS-0001"`, enquanto `XS-001__0__20261022T141503Z.jpg` não casa.
- **CA-02** — *Dado* o dataset 4/2 com `contributor_items_per_stratum=1` e `external_items_per_stratum=1`, *quando* `load_manifest` é chamado, *então* não há erro, o resultado tem 121 linhas, `origin` vale `capture` em 88, `contributor` em 22 e `external` em 11, a coluna `contributor` é `c01` nas 22 e `None` nas outras, `source_id` é `synthetic` nas 11 e `None` nas outras, e `df.attrs["sources_sha256"]` é o SHA-256 do `sources.csv`.
- **CA-03 (compatibilidade)** — *Dado* o dataset 4/2 sem `sources.csv` e com `external_sources` apontando para um arquivo inexistente, *quando* `load_manifest` é chamado, *então* não há erro, há 88 linhas, todas com `origin == "capture"`, `contributor` e `source_id` `None`, e `df.attrs["sources_sha256"]` e `df.attrs["external_sources_sha256"]` são `None`.
- **CA-04 (`sources.csv`)** — *Dado* o dataset 4/2 do CA-02, *quando*, em casos separados (um teste por caso, com o `sources.csv` reescrito pelo teste com `csv.writer`), uma linha `external` tem `source_id=desconhecida`, uma `external` tem `source_ref` vazio, uma `external` tem `source_ref` com U+202E, uma `contributor` tem `contributor=C01`, uma `contributor` tem `source_id=synthetic`, uma linha tem `origin=capture`, uma linha tem `input_sha256` com 63 caracteres, duas linhas têm o mesmo `input_sha256`, uma linha repete o `image_path` de outra, uma linha tem um `image_path` fora do manifest, a linha de uma imagem `XS-` é apagada do arquivo, uma linha de uma imagem `S-001` (do manifest) é acrescentada com `origin=external`, e o cabeçalho perde a coluna `input_sha256` (cada caso muda só o que está descrito; numa linha acrescentada, os demais campos são válidos e o `input_sha256` é novo), *então* `load_manifest` levanta uma `ManifestError` cujos problemas incluem, respectivamente, `unknown_source_id`, `invalid_source_ref`, `invalid_source_ref`, `invalid_contributor`, `source_fields_mismatch`, `invalid_origin`, `invalid_input_sha256`, `duplicate_input`, `duplicate_source_row`, `source_unknown_image`, `missing_source`, `external_item_mismatch` e `missing_column`; e, no caso `missing_source`, `python -m qc_ml.data validate --dataset-dir <root> --external-sources <root>/external_sources.csv` sai com 2 e imprime `count missing_source: 1`.
- **CA-05 (registro)** — *Dado* o dataset do CA-02 com o `external_sources.csv` reescrito pelo teste, *quando*, em casos separados, a fonte tem `license=CC-BY-ND-4.0`, `license=unknown`, `license` vazio, `license=CC-BY-NC-SA-4.0`, `license=CC-BY-SA-4.0`, `license=CC-BY-NC-4.0`, `url=http://example.org/x`, `retrieved_at=2026-02-30`, `source_id=Synthetic` ou `attribution` com `\n`, ou o arquivo tem duas linhas `synthetic`, *então* `load_manifest` levanta uma `ManifestError` cujos problemas incluem, respectivamente, `invalid_license` (6 casos), `invalid_url`, `invalid_date`, `invalid_source_id`, `invalid_text` e `duplicate_source_id`, cada um com `file="external_sources.csv"`. *Dado* o registro só com o cabeçalho e um dataset sem externas, *então* não há erro.
- **CA-06 (R-14, exclusão)** — *Dado* o dataset do CA-02 com a imagem de `XS-0001` apagada do disco e registrada em `exclusions.csv` (`reason=other`), *quando* `load_manifest` é chamado, *então* não há erro (nem `missing_file`, nem `missing_source`), há 120 linhas e nenhuma com `item_id == "XS-0001"`.
- **CA-07 (R-11)** — *Dado* o dataset 20/3 com `external_items_per_stratum=2` lido com `load_manifest` (`df`), *quando* `make_split(df, seed=42)` é chamado, *então* as 22 imagens externas estão em `train`; cada estrato tem exatamente 14 peças não externas em treino, 3 em val e 3 em teste (como no CA-13 da SPEC-011); e o split das imagens não externas é idêntico ao de `make_split(df[~df["item_id"].map(is_external_item)], seed=42)`.
- **CA-08 (R-11, versões seguintes)** — *Dado* o `split_v1` do dataset 20/3 sem externas, gerado pela CLI, e depois 11 imagens externas novas (uma por estrato, `XS-`/`XN-`/`XO-` a partir de `0001`, cada uma com a linha do manifest, a do `sources.csv` e o arquivo em disco, mais o registro sintético do §4.7 gravado pelo teste), *quando* a CLI de split roda, *então* sai com 0, cria `split_v2.csv`, as 11 imagens novas estão em `train`, todas as linhas do `split_v1` mantêm o split, e o `split_v2.json` tem `n_external_images` 11 no treino e 0 em val e em teste.
- **CA-09 (R-11, integridade)** — *Dado* o dataset 20/3 com `external_items_per_stratum=1` e o `split_v1` gerado pela CLI, *quando*:
  - (a) a CLI de split roda depois de o teste trocar, no `split_v1.csv`, o split da imagem de `XS-0001` para `test` e reescrever o `split_v1.sha256` com o hash do arquivo editado, e de acrescentar uma peça nova de `screw/fair` com 2 imagens (para a CLI ter o que gravar);
  - (b) `make_split(df, seed=42, previous=<o split_v1 editado como em (a)>)` é chamado;
  - (c) `rows_for(df, <o split_v1 editado como em (a)>, "test")` e `rows_for(df, <o mesmo split com a imagem em val>, "val")` são chamados;

  *então* em (a) a CLI sai com 2, a saída de erro contém `XS-0001`, e o conteúdo de `--splits-dir` (nomes e bytes) fica igual ao de antes da execução; em (b) e (c), `SplitIntegrityError` com `XS-0001` na mensagem; e `rows_for(df, <split original>, "train")` não levanta erro e devolve, entre as linhas, as 11 imagens externas.
- **CA-10 (teto)** — *Dado* o dataset 20/3 com `external_items_per_stratum=18` (198 externas e 462 imagens não externas no treino: fração exatamente 0,30), *quando* a CLI de split roda em diretórios vazios, *então* sai com 0 e o `split_v1.json` tem `max_external_fraction == 0.3` e `external_fraction_train == 0.3`. *Dado* `external_items_per_stratum=19` (209 externas, 209/671 > 0,30), *então* sai com 2, a saída de erro contém `external fraction` e `209/671`, e nenhum arquivo é gravado; com `--max-external-fraction 0.35`, sai com 0. *Dado* `--max-external-fraction` igual a `0`, `1.5` ou `abc`, *então* sai com 2 sem gravar nada.
- **CA-11 (relatório de dados)** — *Dado* o dataset 20/3 com `contributor_items_per_stratum=1` e `external_items_per_stratum=2`, com o `split_v1` gerado pela CLI, *quando* `python -m qc_ml.data report` roda, *então* o JSON tem as chaves da SPEC-011 §4.2 e as de §4.5; `counts_by_origin` dá `capture` 660 imagens e 220 peças, `contributor` 33 e 11, `external` 22 e 22, e `by_split` de `external` é `{"train": 22, "val": 0, "test": 0}`; `n_contributors == 1`; `by_source == {"synthetic": 22}`; `items_per_grade["screw"]["perfect"] == 21`; `below_target` tem as 10 combinações `screw`/`nut` × grau, todas com `n_images == 63` e `n_items == 21`; `below_minimum == []`; e `external_fraction_train == 22 / 517` (±1e-12).
- **CA-12 (`metrics.json`)** — *Dado* a fixture `ml/tests/fixtures/tiny_model/`, o dataset 4/2 com `external_items_per_stratum=1`, com split, e uma config com `external_sources=<root>/external_sources.csv`, *quando* `thresholds` e depois `evaluate` rodam (CI, sem torch), *então* as chaves de topo do `metrics.json` são exatamente as da SPEC-012 §4.7; `counts.train.by_origin == {"capture": 44, "contributor": 0, "external": 11}`; `counts.val.by_origin.external == 0` e `counts.test.by_origin.external == 0`; `counts.train.by_source == {"synthetic": 11}`; e `counts.val.by_source == counts.test.by_source == {}`.
- **CA-13 (CHANGELOG e atribuição)** — *Dado* o `metrics.json` do CA-12 e o registro sintético, *quando* `python -m qc_ml.report changelog --model-dir <dir> --external-sources <root>/external_sources.csv` roda, *então* a entrada contém a seção `### Dados`, a linha `- Validação e teste: 0 e 0 imagens externas (ADR-020).`, a linha `- Treino: 11 imagens externas de 55 (0,2000).` e a linha `` - `synthetic`: 11 imagens, CC0-1.0. Crédito: Synthetic test images ``; com um registro só com o cabeçalho, a linha da fonte termina com `licença não encontrada no registro`; e, com um `metrics.json` cujo `counts` não tem `by_origin`, a entrada não tem `### Dados`.
- **CA-14 (registro do repositório)** — *Dado* o repositório, *quando* `ml/external_sources.csv` é lido, *então* a primeira linha é exatamente `source_id,title,url,license,license_url,attribution,retrieved_at`, `load_external_sources` não levanta erro, e `git check-ignore ml/external_sources.csv` sai com 1 (não ignorado).
- **CA-15 (gerador)** — *Dado* `make_synthetic_dataset` com os parâmetros padrão em dois diretórios, um deles com `external_items_per_stratum=0, contributor_items_per_stratum=0` explícitos, *então* os dois diretórios têm os mesmos arquivos com os mesmos bytes, e nenhum tem `sources.csv` nem `external_sources.csv`.
- **CA-16 (notas do Release, com fonte)** — *Dado* o diretório de modelo do CA-12 (`model.sha256` da fixture e o `metrics.json` gerado) e o registro sintético, *quando* `python -m qc_ml.report release-notes --model-dir <dir> --external-sources <root>/external_sources.csv --output <tmp>/notes.md` roda, *então* sai com 0, o stdout fica vazio e o arquivo é UTF-8, termina com um único `\n` e tem, nesta ordem: a primeira linha `sha256: <conteúdo do model.sha256 sem o \n>`; a linha `## Fontes externas e créditos`; exatamente uma linha que começa com `` - ` ``, igual a `` - `synthetic`: 11 imagens, CC0-1.0. Crédito: Synthetic test images | Licença: https://creativecommons.org/publicdomain/zero/1.0/ | Fonte: https://example.org/synthetic ``; e a linha ``Registro das fontes: `ml/external_sources.csv`. Histórico do modelo: `ml/models/CHANGELOG.md`.``. O arquivo não contém `não usa imagens externas`. A linha da fonte começa com a linha da fonte da seção `### Dados` do `changelog` do CA-13 (mesmos dados). *Quando* o mesmo comando roda sem `--output`, *então* o stdout é igual, byte a byte, ao arquivo.
- **CA-17 (notas do Release, fonte fora do registro bloqueia, e ordem)** — *Dado* o `metrics.json` do CA-16 editado pelo teste para `counts.train.by_source == {"zz-fora": 2, "synthetic": 11}` e o registro sintético, *quando* `release-notes` roda com `--output <tmp>/notes.md`, em dois casos, (a) sem o arquivo e (b) com `<tmp>/notes.md` já contendo `antigo\n`, *então* sai com 2, o stdout fica vazio, a saída de erro contém `source not in registry: zz-fora` e não contém `source not in registry: synthetic`, e em (a) o arquivo não existe e em (b) continua com `antigo\n`; e o `changelog` com o mesmo `metrics.json` e o mesmo registro sai com 0 e tem a linha `` - `zz-fora`: 2 imagens, licença não encontrada no registro ``. *Dado* o `metrics.json` do CA-16 sem edição e um registro só com o cabeçalho, *então* `release-notes` sai com 2 e a saída de erro contém `source not in registry: synthetic`. *Dado* o `metrics.json` com `by_source == {"bad<marcador>‮": 1, "synthetic": 11}` (marcador gerado no teste), *então* sai com 2, a saída de erro contém `source not in registry: <invalid source_id>` e não contém o marcador. *Dado* o registro sintético com uma segunda fonte válida, `aa-fonte` (`CC-BY-4.0`, `https://example.org/aa`, `license_url` `https://creativecommons.org/licenses/by/4.0/`, atribuição `Fonte AA`), e o `metrics.json` com `by_source == {"synthetic": 11, "aa-fonte": 2}`, *então* sai com 0, as linhas que começam com `` - ` `` são, nesta ordem, `` - `aa-fonte`: 2 imagens, CC-BY-4.0. Crédito: Fonte AA | Licença: https://creativecommons.org/licenses/by/4.0/ | Fonte: https://example.org/aa `` e a linha `synthetic` do CA-16, e cada uma começa com a linha de fonte de mesma posição na seção `### Dados` do `changelog` com o mesmo `metrics.json` e o mesmo registro.
- **CA-18 (notas do Release, sem externas)** — *Dado* o diretório de modelo do CA-16 com o `metrics.json` editado pelo teste, em casos separados, (a) com `by_source` igual a `{}` e `by_origin.external` igual a 0 nos três splits e (b) sem as chaves `by_origin` e `by_source` em nenhum split (como um `metrics.json` anterior a esta SPEC), *quando* `release-notes` roda com o registro sintético, *então* sai com 0, as notas têm a linha `sha256: …`, a linha `## Fontes externas e créditos`, a linha `Este modelo não usa imagens externas (ADR-020).` e a linha dos caminhos do CA-16, e nenhuma linha começa com `` - ` ``.
- **CA-19 (notas do Release, erros)** — *Dado* o diretório de modelo do CA-16, *quando*, em casos separados, o `model.sha256` é apagado, o `model.sha256` tem 63 caracteres hexadecimais, o `metrics.json` é apagado, o `metrics.json` não é JSON válido, ou o registro tem a fonte com `license=CC-BY-NC-4.0`, e `release-notes` roda com `--output <tmp>/notes.md`, *então* sai com 2, o stdout fica vazio e `<tmp>/notes.md` não existe. *Dado* `<tmp>/notes.md` já existente com o conteúdo `antigo\n`, no caso do `model.sha256` apagado, *então* o arquivo continua com `antigo\n`.
- **CA-20 (README)** — *Dado* `ml/README.md`, *quando* se isola o trecho da seção cujo título contém `Origem das imagens` até o próximo título de nível igual ou superior, *então* ele contém `ml/external_sources.csv`, `--max-external-fraction`, `qc_ml.report release-notes`, `--notes-file` e `source not in registry`.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Regex e letra do tipo; cada problema de `sources.csv` e do registro; exclusão × `sources.csv`; split com externas (v1, versões seguintes, `history`, teto no limite e acima, `Fraction`); guarda do `rows_for`; relatório; `split_counts`; seção do CHANGELOG; notas do Release (com fonte, fonte fora do registro bloqueia, ordem, sem externas, erros); gerador | `ml/tests/` |
| Aceite (tester) | Um por CA, com `make_synthetic_dataset` em `tmp_path`; CLIs via `main(argv)` ou subprocesso | `ml/tests/acceptance/test_spec_035.py` |

- Nada é mockado além do sistema de arquivos temporário. Sem internet e sem dados reais. Nenhum CA usa torch.
- Os CA-07 a CA-11 usam o dataset 20/3 (1.000 imagens sintéticas pequenas); se o tempo de CI pesar, o autor pode gerar o dataset uma vez por módulo (`scope="module"`) e copiá-lo por teste.

## 7. Riscos e notas para o implementador

- **A regra de integridade depende só do `item_id`.** Não use o `sources.csv` para decidir o split: uma queda de energia entre a gravação do manifest e a do `sources.csv` (SPEC-036 §4.4) deixaria uma imagem externa sem linha, e ela iria para a validação. Com o prefixo `X`, ela continua no treino, e o `validate` acusa `missing_source`. A correção é a do `docs/dataset-protocol.md` §10.7 (excluir e importar de novo).
- **Por que as externas ficam fora dos estratos:** a permutação da SPEC-011 percorre um único gerador em ordem de estrato. Uma peça a mais num estrato muda a posição de todas as seguintes. Se as externas entrassem e saíssem do sorteio, mudar o conjunto de fontes mudaria o `split_v1` das peças próprias (antes do congelamento) e tornaria o split dependente de imagens que nunca serão avaliadas.
- **Teto:** é uma regra de qualidade (ADR-020: "complemento, não base"), não da R-11. O valor usado fica no `split_v<N>.json`. Não aplique o teto por estrato nem descarte imagens para caber nele: o split nunca escolhe imagens.
- **Contagem por imagem:** cada imagem externa é uma peça. Um dataset público com várias fotos do mesmo objeto pode usar o mesmo `item_id` externo para elas (decisão da dupla na importação). Como as externas só vão para o treino, isso não afeta a R-11.
- **Colunas novas do `load_manifest`:** `origin`, `contributor` e `source_id` entram depois de `grade_original` e `overridden`. O `PartsDataset` e o `predict` não as usam.
- **`DEFAULT_EXTERNAL_SOURCES`:** depende do layout do repositório (`ml/src/qc_ml/` → `ml/`). Num pacote instalado fora do repositório (não é o caso do projeto), o arquivo não existe e o registro fica vazio.
- **Licenças NonCommercial e ShareAlike:** o registro **recusa** `CC-BY-NC-4.0`, `CC-BY-SA-4.0` e `CC-BY-NC-SA-4.0` (`invalid_license`), por decisão do humano de 2026-10-23 (ADR-020, decisão 3): o `model.onnx` é publicado num Release público (SPEC-012 §4.9). Não acrescente outro identificador à tupla sem um ADR novo. As licenças da lista que exigem crédito (`CC-BY-4.0`, `MIT`, `Apache-2.0`, `BSD-3-Clause`) são atendidas pela coluna `attribution`, pela seção `### Dados` do CHANGELOG e pelas notas do Release geradas pelo `release-notes` (§4.6), que põem o crédito na própria página do Release.
- **Notas do Release:** reaproveite a mesma função que monta as linhas de fonte do CHANGELOG (ordem e contagem), para que as duas saídas nunca divirjam (CA-17). Não escape nem reformate o `attribution`: o registro já é revisado por PR e recusa quebras de linha (§4.3).
- **Planilhas:** `sources.csv` e `external_sources.csv` têm texto vindo de fora (`source_ref`, `title`, `attribution`). A regra do manifest vale para eles: não abrir em planilha (`docs/dataset-protocol.md` §5).

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED
- [ ] CI verde (sem torch); `ruff` limpo
- [ ] `ml/README.md` atualizado (§4.8, inclusive o passo do Release com `--notes-file`) e `ml/external_sources.csv` no Git
- [ ] ADR-020 `Aceito` pelo humano
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)

## 9. Decisões confirmadas na aprovação (humano, 2026-10-23)

1. **Teto** de 30% de imagens externas no treino (§4.4): confirmado.
2. **Lista de licenças** (§4.3): só `CC0-1.0`, `PDDL-1.0`, `CC-BY-4.0`, `MIT`, `Apache-2.0` e `BSD-3-Clause`. Ficam fora as NonCommercial e as ShareAlike (`CC-BY-NC-4.0`, `CC-BY-SA-4.0`, `CC-BY-NC-SA-4.0`), inclusive o MVTec AD, porque o `model.onnx` é publicado num Release público.
3. **Faixa 500–999** para as peças de conhecidos (`docs/dataset-protocol.md` §10.3): convenção recomendada, sem validação no código: confirmada.

## Anexo A — Datasets públicos avaliados (referência para a escolha da dupla)

Consultados pelo architect em **2026-10-20**; a coluna "Uso possível" foi revista em **2026-10-23** com a lista de licenças do §4.3 (sem NonCommercial nem ShareAlike, ADR-020). Nada foi baixado. Nenhum tem os 5 graus da rubrica: toda imagem externa é rotulada pela dupla (§1 do `docs/dataset-protocol.md`), nunca pelo rótulo da fonte. "Verificado" = lido na página oficial ou na API pública do Kaggle (`/api/v1/datasets/view/<dono>/<nome>`); "pela busca" = o Roboflow Universe recusou a consulta direta (HTTP 403), e o dado veio só do resultado da busca: conferir na página antes de registrar a fonte.

| # | Nome | URL | Licença | Imagens | Classes / tarefa | Corrosão ou graus | Uso possível no PartQC |
|---|---|---|---|---|---|---|---|
| 1 | MVTec AD (`screw`, `metal_nut`) | <https://www.mvtec.com/company/research/datasets/mvtec-ad> | CC BY-NC-SA 4.0 (verificado) | mais de 5.000 no total, 15 categorias; `screw` 480 e `metal_nut` 335 (<https://datasetninja.com/mvtec-ad>) | detecção de anomalia: treino só sem defeito; teste com defeitos por tipo | sem corrosão; defeitos mecânicos (rosca, riscos, porca torta ou virada); `screw` em tons de cinza; 700 a 1.024 px | **não permitido** (NonCommercial/ShareAlike, ADR-020). Traria `perfect` e `unusable` (dano funcional, pela rubrica) |
| 2 | MVTec Screws | <https://mvtec.com/company/research/datasets/mvtec-screws> | CC BY-NC-SA 4.0 (verificado) | 384 fotos, 4.426 objetos | 13 tipos de parafusos e porcas; caixas orientadas; fundo de madeira | sem estado | **não permitido** (NonCommercial/ShareAlike, ADR-020) |
| 3 | SDNET 2025 — Defective Bolts and Nuts Steel | <https://data.mendeley.com/datasets/cxnj6cp4rb/1> (DOI 10.17632/cxnj6cp4rb.1) | CC BY 4.0 (verificado) | mais de 826 originais (1.500 com aumento de dados) | fixed, loosened, missing, corroded; caixas e máscaras | classe `corroded`, sem graus | `poor`/`fair` pela rubrica, recortando as caixas; peças montadas em estruturas (domínio distante). Usar só as originais |
| 4 | NPU-BOLT | <https://www.kaggle.com/datasets/yartinz/npu-bolt> | CC0 (verificado) | 337 fotos, cerca de 1.275 objetos | blur bolt, bolt head, bolt nut, bolt side; caixas | não citada | pouco útil: parafusos montados em cena natural |
| 5 | The Fasteners | <https://www.kaggle.com/datasets/alexandrparkhomenko/the-fasteners> | CC0 (verificado) | não informado (82 MB) | parafusos, porcas e arruelas isolados | não citada | `perfect` e arruelas para `other`; conferir o conteúdo |
| 6 | SortScrews | <https://github.com/ATATC/SortScrews> (artigo <https://arxiv.org/abs/2603.13027>) | Apache-2.0 (licença do repositório; o artigo não define licença dos dados) | 560, 512×512 | 6 tipos de parafuso e fundo | não citada | `perfect`; confirmar que a licença cobre as imagens |
| 7 | screw dataset (ruruamour) | <https://www.kaggle.com/datasets/ruruamour/screw-dataset> | CC BY-NC-SA 4.0 (verificado) | 300 PNG de treino e um teste | normal × defeituoso | não | **não permitido** (NonCommercial/ShareAlike, ADR-020); é cópia do MVTec AD `screw` (#1) |
| 8 | Images of mechanical parts (Bolt, Nut, Washer, Pin) | <https://www.kaggle.com/datasets/manikantanrnair/images-of-mechanical-parts-boltnut-washerpin> | ODbL (base) + DbCL (conteúdo); fonte declarada "Internet" (verificado) | não informado (52 MB) | 4 classes | não | **não permitido** (licença fora da lista: a ODbL é ShareAlike, ADR-020); além disso, as imagens foram coletadas da internet, e o direito de cada uma é incerto |
| 9 | Screw-Washer Dataset for Small Object Detection | <https://www.kaggle.com/datasets/wjybuqi/screwwasher-dataset-for-small-object-detection> | "Data files © Original Authors" (verificado) | 100 | parafusos, porcas e arruelas em cenas | não | **não permitido** (sem licença de uso) |
| 10 | Rusty iron components | <https://www.kaggle.com/datasets/omkarmb/iron-rust-components> | Unknown (verificado) | não informado | peças de ferro com ferrugem | sim, sem graus | **não permitido** (licença desconhecida) |
| 11 | Rust-Iron-Dataset | <https://www.kaggle.com/datasets/benpepperpots/rust-iron-dataset> | Unknown (verificado) | não informado (cerca de 780 MB) | corrosão × sem corrosão (superfícies) | sim, binário | **não permitido** (licença desconhecida) |
| 12 | rusty bolts (oumaima) | <https://universe.roboflow.com/oumaima-6jfwk/rusty-bolts> | CC BY 4.0 (pela busca) | não informado | detecção | sim, sem graus | `fair`/`poor` pela rubrica; conferir |
| 13 | RustedYolov5 | <https://universe.roboflow.com/shwetark/rustedyolov5> | CC BY 4.0 (pela busca) | 73 (pela busca) | nut, bolt, rusted | sim, sem graus | idem; conferir |
| 14 | nut and rust | <https://universe.roboflow.com/mydataset-heun9/nut-and-rust> | CC BY 4.0 (pela busca) | não informado | Hex-Nut, Rust_detection | sim, sem graus | porcas com ferrugem; conferir |
| 15 | screw-nut-washer | <https://universe.roboflow.com/annotation-svf3l/screw-nut-washer> | CC BY 4.0 (pela busca) | 391 (pela busca) | detecção | não | `perfect`, recortando |
| 16 | NutsNBolts 2 | <https://universe.roboflow.com/tktk-hodc3/nutsnbolts-2> | CC BY 4.0 (pela busca) | não informado | nut, bolt, washer | não | `perfect`, recortando |
| 17 | Nails (Ghefira Zahra Nur Fadhilah) | <https://universe.roboflow.com/ghefira-zahra-nur-fadhilah-ard5j/nails-pcxq3-zityw> | CC BY 4.0 (pela busca) | 303 (pela busca) | segmentação de pregos | não | pregos para `other` (negativos difíceis, protocolo §2) |
| 18 | Nail (Alec) | <https://universe.roboflow.com/alec/nail-by26a> | CC BY 4.0 (pela busca) | 46 (pela busca) | detecção de pregos | não | idem |

**Referência sem dados publicados:** Mandolini et al. (2026), "Automatic assessment of rust level on screws using convolutional neural networks" (<https://iris.univpm.it/handle/11566/359994>, DOI 10.1017/pds.2026.10602): classifica níveis de ferrugem em parafusos (câmara de névoa salina, 0, 48, 96 e 168 h) com ResNet-18 e MobileNetV3. É o trabalho mais próximo dos graus do PartQC, mas a página consultada não diz se os dados são públicos.

**Leitura para a escolha.** Com a lista do §4.3, saem o MVTec AD (#1), o MVTec Screws (#2), o espelho do Kaggle (#7) e o #8. Entre as fontes permitidas, a de licença verificada que traz algo que falta à dupla é o SDNET 2025 (corrosão real → `fair`/`poor` pela rubrica). The Fasteners (CC0), SortScrews (Apache-2.0, confirmando que a licença cobre as imagens) e as do Roboflow servem para `perfect`; as do Roboflow, também para pregos em `other`, mas a licença e o conteúdo têm de ser conferidos na página. **O dano funcional (`unusable`) deixa de ter fonte externa permitida:** só o MVTec AD o trazia. O `unusable` depende só das peças da dupla e de conhecidos, com o dano mecânico controlado do `docs/dataset-protocol.md` §2, passo 5. Usar uma fonte NonCommercial ou ShareAlike exige um ADR novo (ADR-020, "Quando revisitar").

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-20 | SPEC criada (`Draft`). Decisões do architect: (a) duas SPECs, esta para o `qc-ml` (ml-engineer) e a SPEC-036 para a importação na borda (developer), por causa do hook de caminhos e do reuso do `DatasetWriter`; (b) manifest inalterado e origem em `DATASET_DIR/sources.csv`, em vez de colunas novas; (c) `item_id` externo `X<tipo>-NNNN`, que decide sozinho a regra do split; (d) externas fora dos estratos, sempre no treino, com teto de 30% e guarda no `rows_for`; (e) registro de fontes `ml/external_sources.csv` no Git como arquivo de atribuições, com lista fechada de licenças; (f) contagem por origem no relatório de dados e no `counts` do `metrics.json`, sem mudar as chaves de topo; (g) Anexo A com os datasets avaliados. ADR-020 (`Proposto`) criado. | Decisão do humano de 2026-10-19 (fotos de conhecidos e imagens externas) | Orquestrador, a pedido do humano |
| 2026-10-23 | §4.3: `ALLOWED_LICENSES` reduzida a `CC0-1.0`, `PDDL-1.0`, `CC-BY-4.0`, `MIT`, `Apache-2.0` e `BSD-3-Clause` (NonCommercial e ShareAlike recusadas com `invalid_license`). CA-05: 3 casos novos (`CC-BY-NC-SA-4.0`, `CC-BY-SA-4.0`, `CC-BY-NC-4.0` → `invalid_license`; agora 6 casos). §1 e §7 (nota das licenças) alinhados. §9 passa a registrar as decisões confirmadas: teto de 30%, lista nova e faixa 500–999 só como recomendação. Anexo A: #1, #2, #7 e #8 marcados como não permitidos e "Leitura para a escolha" reescrita (o `unusable` fica sem fonte externa permitida). Cabeçalho: ADR-020 `Aceito`. | Decisão do humano de 2026-10-23 (o `model.onnx` é publicado num Release público) | Architect, a pedido do humano |
| 2026-10-23 | Aprovada pelo humano (`Draft` → `Ready`), com as decisões confirmadas: rotação EXIF aplicada e reencode na importação, teto de 30%, faixa 500–999 só como convenção e lista de licenças sem NonCommercial nem ShareAlike. | Mensagem do humano de 2026-10-23 | Orquestrador, a pedido do humano |
| 2026-10-23 | §4.6: subcomando novo `python -m qc_ml.report release-notes --model-dir <dir> [--external-sources <arquivo>] [--output <arquivo>]`, que gera as notas do GitHub Release: linha `sha256:`, seção "Fontes externas e créditos" com uma linha por fonte (mesma ordem e mesmos dados da seção `### Dados` do CHANGELOG, mais o link da licença e o da fonte; fonte fora do registro com a mesma linha do CHANGELOG e aviso), a frase "Este modelo não usa imagens externas (ADR-020)." sem externas, e os caminhos de `ml/external_sources.csv` e do CHANGELOG. §4.7: o registro sintético ganha `license_url` fixo. §4.8: o passo do Release no `ml/README.md` usa `--notes-file` com o arquivo gerado, e o arquivo de créditos é obrigatório quando o modelo usou fontes externas. §3.1, §6, §7 e §8 alinhados. CAs novos CA-16 a CA-20. Nenhum CA existente muda; contrato e chaves do `metrics.json` não mudam. Classificação ADR-019: exige humano (X-5: comando e comportamento novos; X-2: ADR-020 alterado junto). SPEC marcada como "**Aguardando reaprovação humana**". | Decisão do humano de 2026-10-23 (créditos visíveis no Release) | Architect, a pedido do humano |
| 2026-10-23 | §4.6: fonte de `counts.train.by_source` ausente do registro passa a **bloquear** o `release-notes` (código 2, stdout vazio, `--output` nem criado nem alterado, `source not in registry: <source_id>` na saída de erro, com o `source_id` impresso só se casar o formato do §4.3; senão, `<invalid source_id>`). O `changelog` continua só marcando a linha. §4.8: o README troca a proibição de publicar com `licença não encontrada no registro` pela orientação de registrar a fonte quando o `release-notes` falhar. CA-17 reescrito (bloqueio com e sem `--output` existente, `source_id` inseguro não ecoado, ordem com duas fontes registradas, `changelog` ainda marcando a linha); CA-20: `source not in registry` no lugar de `licença não encontrada no registro`; §6 alinhado. Nenhum outro CA muda. | Decisão do humano de 2026-10-23, na reaprovação do `release-notes`: não gerar notas sem o crédito completo | Architect, a pedido do humano |
| 2026-10-23 | Reaprovada pelo humano: notas do Release com créditos; fonte fora do registro bloqueia o `release-notes` (código 2). | Mensagem do humano de 2026-10-23 | Orquestrador, a pedido do humano |
