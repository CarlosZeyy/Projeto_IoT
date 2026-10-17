# SPEC-010: Modo coleta de dataset

| Campo | Valor |
|---|---|
| Status | In Test |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-007 |
| Semana alvo | S2 |
| Requisitos cobertos | RF-08, RNF-05 |
| ADRs relevantes | ADR-001, ADR-003, ADR-014 |

## 1. Contexto

Implementa `docs/architecture.md` §6.3: o celular vira a câmera de montagem do dataset, seguindo `docs/dataset-protocol.md` §3 (captura), §4 (metas) e §5 (manifest). As imagens e o manifest ficam só no notebook (R-02, R-14); o pipeline de ML (SPEC-011) consome esse manifest e falha se ele for inconsistente, por isso a validação acontece já na captura.

## 2. Objetivo

No modo coleta, cada foto vira um arquivo em `DATASET_DIR/raw/...` e uma linha válida em `DATASET_DIR/manifest.csv`, sem inferência e sem nada enviado à nuvem, e o console mostra a cobertura em relação às metas.

## 3. Escopo

### 3.1 Dentro

- `edge/src/qc_edge/collect.py`: `CollectRequest`, `DatasetWriter`, `CoverageReport`, `compute_coverage()`.
- `POST /api/capture` com `mode=collect` (substitui o 501 da SPEC-007).
- Campos de coleta em `capture.html`/`capture.js` (o limite de 200 linhas do JS da SPEC-007 continua valendo).
- Tabela de cobertura no console (`GET /`).
- `DATASET_DIR` em `EdgeSettings` (padrão `ml/data`, `docs/dataset-protocol.md` §8) e no `.env.example`; seção "Modo coleta" no `edge/README.md`.
- **Ajustes autorizados ao tester da SPEC-010 em `edge/tests/acceptance/test_spec_007.py`** (SPEC_ISSUE-01 de `reviews/SPEC-010/r1-dev-report.md`; aplicação explícita da regra "Testes de aceite de SPECs anteriores" de `docs/architecture.md` §10). São exatamente três, todos consequência direta desta SPEC:
  1. `test_ca15_capture_page`: a asserção `all("disabled" in a for a in collect)` deixa de exigir `disabled`, porque o CA-16 desta SPEC habilita "coleta" (a SPEC-007 §4.4 já o desabilitava só "até a SPEC-010"). Continua exigindo que a opção `collect` exista; as demais asserções do teste não mudam.
  2. `test_extra_collect_mode_is_501`: é removido, ou passa a esperar 422 (`mode=collect` sem os campos de coleta, §4.1), mantendo `stub.calls == 0` e `edge.captures() == []`, porque o §3.1 desta SPEC substitui o 501 da SPEC-007. É um teste extra, sem CA da SPEC-007 associado.
  3. `test_ca13_console_from_loopback`: `page.count("parafuso") == 10` passa a contar só dentro das linhas `<tr class="inspection" …>` do console, que continuam sendo exatamente 10. A tabela de cobertura do §4.4 acrescenta 5 linhas "parafuso" fora delas. As demais asserções do teste não mudam.

  Nenhuma outra linha desse arquivo muda e nenhum CA da SPEC-007 tem a intenção alterada. O test-report lista os três ajustes no formato do `docs/architecture.md` §10.

### 3.2 Fora

- Correções de rótulo (`labels_overrides.csv`), dupla rotulagem e validações do pipeline → SPEC-011.
- Ferramentas (`T-…`, Fase 2) → SPEC-016. Até lá, `item_id` com prefixo `T` é recusado.
- Inferência e outbox → SPECs 008 e 009 (não são chamados aqui).

## 4. Requisitos detalhados

### 4.1 Campos (`multipart/form-data`, header `X-Session-Token` como na SPEC-007)

| Campo | Regra | Erro |
|---|---|---|
| `image` | mesmas regras da SPEC-007 (≤ 3 MiB → senão 413; `qc_edge.limits.load_capture_image`, SPEC-007 §4.7: até 4 M pixels e depois o `load_image` → senão 415), dentro do limitador de decodificações (SPEC-007 §4.6) | 413 / 415 |
| `mode` | `collect` | 422 |
| `item_id` | `^[SNOT]-\d{3}$` | 422 |
| `object_type` | `screw` \| `nut` \| `other` (classe do modelo; `unknown` não é aceito) | 422 |
| `grade` | um dos 5 valores de `Grade` para `screw`/`nut`; **ausente ou vazio** para `other` | 422 |
| `labeler` | `a` \| `b` | 422 |
| `angle` | inteiro 0–4 | 422 |
| `notes` | opcional, ≤ 200 caracteres, sem caracteres de controle (incluindo `\r`, `\n`, `\t`) | 422 |
| `lot_id` | ignorado neste modo (não é validado nem gravado) | — |

Coerência do prefixo: `S` → `screw`, `N` → `nut`, `O` → `other`; `T` ou prefixo que não bate com `object_type` → 422.

Campos que viram nome de arquivo ou caminho (`item_id`, `object_type`, `grade`, `angle`, §4.2): `item_id` é validado com `re.fullmatch(r"[SNOT]-\d{3}", valor)` (ou o `pattern` do Pydantic), **nunca** com `re.match`/`re.search`, que aceitam um `\n` final (`architecture.md` §3.2); `angle` é validado com `re.fullmatch(r"[0-4]", valor)` **antes** de `int()` (que aceitaria `"2\n"` e `" 2"`); `object_type`, `grade` e `labeler`, por igualdade exata com os valores permitidos, sem `strip()`. Qualquer falha → 422, antes de tocar o disco.

### 4.2 Gravação

1. Sob um lock de processo (`threading.Lock`) **e** um lock de arquivo (`fcntl.flock` em `DATASET_DIR/manifest.csv.lock`):
   1. se `manifest.csv` existe e o cabeçalho é diferente do esperado → 500 `{"detail": "manifest header mismatch"}`, nada gravado;
   2. se o `item_id` já existe no manifest com outro `object_type` → 409 `{"detail": "item_id already registered with another object_type"}` (o mesmo item com outro `grade` é permitido: estágios de corrosão);
   3. `ts = clock()` (UTC); caminho relativo `raw/<object_type>/<grade ou _>/<item_id>__<angle>__<ts:%Y%m%dT%H%M%SZ>.jpg`; arquivo já existente → 409 `{"detail": "capture already exists, try again"}`;
   4. grava a imagem em arquivo temporário no mesmo diretório e renomeia (JPEG: bytes recebidos; PNG: reencodado em JPEG q=90);
   5. acrescenta a linha ao manifest (cria o arquivo com o cabeçalho se não existir); falha aqui → apaga a imagem e responde 500.
2. Manifest: UTF-8 sem BOM, `csv.writer` com `QUOTE_MINIMAL` e `lineterminator="\n"`, colunas **exatamente** na ordem de `docs/dataset-protocol.md` §5: `image_path,item_id,object_type,grade,labeler,angle,captured_at,capture_device,notes`.
   - `image_path`: o caminho relativo acima, com `/`; `grade`: vazio para `other`; `captured_at`: `ts` em `%Y-%m-%dT%H:%M:%SZ` (mesmo instante do nome do arquivo); `capture_device`: os 60 primeiros caracteres do header `User-Agent` (vazio se ausente).
3. Resposta 200: `{"mode": "collect", "image_path": "...", "item_id": "...", "angle": n, "item_images": <linhas do manifest com esse item_id>}`.
4. Não chama `Inferencer` nem `InspectionSink`; funciona com `inferencer=None`.
5. **Permissões (SEC-06 de `reviews/SPEC-007/r1-security-report.md`, R-14):** tudo o que o modo coleta **cria** sob `DATASET_DIR` fica legível só pelo dono, com modo exato, seja qual for o `umask` (`chmod`/`fchmod` explícito depois de criar):
   - diretórios (`DATASET_DIR`, quando é a borda que o cria, `raw/` e os subdiretórios de tipo e grau): `0700`;
   - imagens (o arquivo temporário já nasce com `0600`, e o `rename` preserva o modo), `manifest.csv` e `manifest.csv.lock`: `0600`.

   `DATASET_DIR` e arquivos que já existiam antes não são alterados. Um `OSError` ao aplicar o modo gera um `WARNING` com o caminho e a coleta segue. As fotos de inspeção (`captures/`) são da SPEC-025.

### 4.3 Página de captura

- Ativar "coleta" no seletor de modo mostra: `item_id` (texto, validado no cliente pela mesma regex), `object_type` (select com rótulos PT-BR: parafuso, porca, outro), `grade` (select com os 5 rótulos PT-BR de `qc_contracts.labels`, desabilitado e vazio quando `other`), `labeler` (a/b), `angle` (0–4) e `notes`.
- Todos persistidos em `localStorage` entre fotos; depois de cada sucesso, `angle` avança 1; depois do 4 volta a 0 e a página mostra "Peça completa — troque o item_id".
- Cartão de resultado: "Salvo: <item_id>, ângulo <n> (fotos desta peça: <item_images>)". Lembrete fixo: "Sem pessoas no quadro" (R-14).

### 4.4 Cobertura no console

```python
@dataclass(frozen=True)
class CoverageCell: object_type: str; grade: str | None; images: int; items: int; target_images: int; target_items: int
def compute_coverage(manifest_path: Path) -> list[CoverageCell]
```

Linhas: `screw` × 5 graus e `nut` × 5 graus (metas 120 imagens e 12 peças por célula, mínimo 8) e `other` (metas 150 imagens e 30 objetos), conforme `docs/dataset-protocol.md` §4. O console mostra a tabela (`<table id="coverage">`) com "imagens/meta" e "peças/meta", destacando as células que atingiram as duas metas, e o total de imagens. Manifest ausente → tabela zerada.

## 5. Critérios de aceite

- **CA-01** — *Dado* `DATASET_DIR` vazio e o relógio em `2026-10-22T14:15:03Z`, *quando* envio JPEG válido com `item_id=S-012`, `object_type=screw`, `grade=fair`, `labeler=a`, `angle=2`, `notes="dúvida fair/poor"` e `User-Agent` de 80 caracteres, *então* recebo 200 com `image_path="raw/screw/fair/S-012__2__20261022T141503Z.jpg"` e `item_images=1`; o arquivo existe; `manifest.csv` tem o cabeçalho de §4.2 e 1 linha com `captured_at=2026-10-22T14:15:03Z` e `capture_device` com 60 caracteres.
- **CA-02** — *Dado* `item_id=O-004`, `object_type=other` e `grade` vazio, *então* 200, arquivo em `raw/other/_/O-004__0__<ts>.jpg` e coluna `grade` vazia no manifest.
- **CA-03** — *Dado* `object_type=other` com `grade=good`, ou `object_type=screw` sem `grade`, ou `grade=excellent`, *então* 422 e nada gravado.
- **CA-04** — *Dado* `item_id=N-001` com `object_type=screw`, ou `item_id=T-001` com qualquer tipo, ou `object_type=unknown`, *então* 422.
- **CA-05** — *Dado* `item_id` igual a `S-12`, `s-012`, `S-0123` ou `../S-001`, ou `angle` igual a 5, -1 ou `x`, ou `labeler=c`, ou `notes` com 201 caracteres ou com `\n`, ou `item_id="S-012\n"`, `angle="2\n"` ou `object_type="screw\n"` (com os demais campos do CA-01), *então* 422 e nenhum arquivo criado fora de `DATASET_DIR`; nos três últimos casos, com `DATASET_DIR` vazio, ele continua vazio (nem imagem, nem `manifest.csv`).
- **CA-06** — *Dado* um manifest com uma linha (inserida direto no arquivo) de `O-007` com `object_type=screw`, *quando* envio `O-007` como `other`, *então* recebo 409 com o detalhe de §4.2, nenhuma imagem é gravada e o manifest não muda. (Com o prefixo amarrado ao tipo, o conflito só surge em manifest editado à mão; a regra existe para proteger a SPEC-011.)
- **CA-07** — *Dado* `S-012` já com uma foto `fair`, *quando* envio `S-012` como `poor`, *então* 200 e `item_images=2` (mudança de estágio é permitida).
- **CA-08** — *Dado* duas requisições idênticas no mesmo segundo do relógio (mesmo item e ângulo), *então* a primeira recebe 200 e a segunda 409, com 1 linha no manifest.
- **CA-09** — *Dado* duas requisições concorrentes (2 threads, itens `S-001` e `N-001`), *quando* terminam, *então* `manifest.csv` tem o cabeçalho e exatamente 2 linhas, ambas lidas por `csv.DictReader` com as 9 colunas e os valores enviados.
- **CA-10** — *Dado* `notes='tem "aspas", vírgula'`, *então* a linha é escrita com quoting CSV correto e `csv.DictReader` devolve o texto idêntico.
- **CA-11** — *Dado* `manifest.csv` existente com cabeçalho diferente, *quando* envio uma coleta válida, *então* 500 `{"detail": "manifest header mismatch"}`, o arquivo não muda e nenhuma imagem é gravada.
- **CA-12** — *Dado* `inferencer=None` e um `StubInferencer` contando chamadas em outro caso, *quando* faço 3 coletas válidas, *então* todas retornam 200, o stub tem 0 chamadas e o sink continua vazio (nada vai para a nuvem — R-02).
- **CA-13 (R-02)** — *Dado* uma coleta feita, *então* `GET /raw/screw/fair/<arquivo>`, `GET /ml/data/manifest.csv` e `GET /manifest.csv` retornam 404.
- **CA-14** — *Dado* coleta sem token ou com token errado, *então* 401 e nada gravado; com imagem de 3 145 729 bytes, 413; com texto renomeado para `.jpg` ou com um JPEG válido de 2001×2000 px (acima do limite da rota, SPEC-007 §4.7), 415; em todos os casos, `DATASET_DIR` não ganha imagem nem linha no manifest.
- **CA-15** — *Dado* um manifest com 130 linhas de `screw/perfect` em 9 itens, 40 de `nut/poor` em 3 itens e 10 de `other` em 10 itens, *quando* chamo `compute_coverage`, *então* as células têm `(130, 9)`, `(40, 3)` e `(10, 10)` com metas `(120, 12)`, `(120, 12)` e `(150, 30)`, e as outras 8 células de grau são `(0, 0)`; e o console (loopback) contém `<table id="coverage">` com "130/120".
- **CA-16** — *Dado* `GET /capture?t=<válido>`, *então* o HTML contém os campos `item_id`, `object_type`, `grade`, `labeler`, `angle` e `notes`, e o seletor de modo com "coleta" habilitado.
- **CA-17 (manual)** — 1. ligar `qc-edge` sem modelo; 2. no celular, ativar "coleta", preencher `S-001`, parafuso, perfeito, `a`, ângulo 0; 3. tirar 5 fotos: o ângulo avança 0→4 e aparece "Peça completa"; 4. recarregar a página: os campos continuam preenchidos; 5. trocar para "outro": o grau fica desabilitado; 6. conferir no notebook 5 arquivos em `raw/screw/perfect/` e 5 linhas no manifest, e a tabela de cobertura com `5/120` e `1/12`.
- **CA-18 (security, SEC-06, R-14)** — *Dado* `os.umask(0o022)` (e, numa segunda execução, `os.umask(0o077)`), com o umask original restaurado no fim, e `DATASET_DIR` inexistente, *quando* uma coleta válida com JPEG (`S-012`, `screw`, `fair`) e outra com PNG (`O-004`, `other`) são feitas, *então* `stat.S_IMODE` dá `0o700` para `DATASET_DIR`, `raw/`, `raw/screw/`, `raw/screw/fair/`, `raw/other/` e `raw/other/_/`, e `0o600` para as 2 imagens, para `manifest.csv` e, se existir, para `manifest.csv.lock`.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | validação, caminhos, manifest, cobertura, lock | `edge/tests/` |
| Aceite (tester) | Um por CA; `tmp_path` como `DATASET_DIR`; relógio falso; threads para CA-09 | `edge/tests/acceptance/test_spec_010.py` |
| Manual (dupla) | CA-17 com um celular real | notebook + celular |

## 7. Riscos e notas para o implementador

- `fcntl.flock` é só POSIX; serve para o Arch Linux da equipe (RNF-08). O lock em thread cobre o caso de um único processo.
- Ler o manifest inteiro a cada coleta é aceitável (≤ ~2 000 linhas); se pesar, mantenha um índice `item_id → object_type` em memória, recarregado quando o `mtime` mudar.
- O manifest é consumido pelo pipeline (pandas), não por planilha; não altere o conteúdo de `notes` além do quoting CSV.
- **Limitador:** o modo coleta usa o limitador único da borda (SPEC-007 §4.6). Se a SPEC-025 já estiver `Done`, a espera pelo slot acontece no event loop e os passos bloqueantes rodam numa única chamada `anyio.to_thread.run_sync` (SPEC-025 §4.2); siga essa forma também na gravação da coleta. Se a SPEC-025 vier depois, ela converte os dois modos.
- **Console nos testes:** se a SPEC-025 já estiver `Done`, o CA-15 chama o console com a URL base `http://127.0.0.1:<EDGE_PORT>` (`Host` de loopback, SPEC-025 §4.1).
- **`umask`:** o `mode` de `mkdir` e de `os.open` passa pelo `umask`; só o `chmod`/`fchmod` explícito torna o modo exato (§4.2, item 5). O teste do CA-18 restaura o `umask` num `finally`.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS); CA-17 registrado
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `edge/README.md` e `.env.example` atualizados
- [ ] PR aberto com os relatórios; merge humano

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-12 | §4.1 exige `re.fullmatch` em `item_id`, `re.fullmatch` em `angle` antes de `int()` e igualdade exata (sem `strip()`) em `object_type`, `grade` e `labeler`, por virarem nome de arquivo ou caminho. O CA-05 ganhou os casos `item_id="S-012\n"`, `angle="2\n"` e `object_type="screw\n"` (422, `DATASET_DIR` intacto). Nenhum outro requisito muda. SPEC marcada como "Aguardando reaprovação humana". | RV-04 de `reviews/SPEC-002/r1-review-report.md` (regra geral em `architecture.md` §3.2) | Humano, via orquestrador |
| 2026-10-12 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
| 2026-10-12 | §4.1: o campo `image` segue os limites próprios da rota da SPEC-007 §4.7 (3 MiB e 4 M pixels, via `load_capture_image`), dentro do limitador de decodificações. O CA-14 trocou 10 485 761 por 3 145 729 bytes e ganhou o JPEG de 2001×2000 (415) e a verificação de `DATASET_DIR` intacto. Nenhum outro requisito muda. SPEC marcada como "Aguardando reaprovação humana". | SEC-24-02 de `reviews/SPEC-024/r1-security-report.md` (decisão registrada na SPEC-007) | Orquestrador, a pedido do humano |
| 2026-10-12 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
| 2026-10-13 | Mudanças: (a) §4.2, item 5 novo: diretórios criados pelo modo coleta com `0700` e imagens, `manifest.csv` e `manifest.csv.lock` com `0600`, exatos, seja qual for o `umask`; (b) CA-18 novo; (c) §7: notas sobre o limitador e o console depois da SPEC-025 e sobre o `umask`. Nenhum CA existente muda. A espera do limitador fora do threadpool (SEC-03) e as permissões de `captures/` ficaram na SPEC-025, que mexe no código da SPEC-007 que esta reutiliza; a retenção das fotos de inspeção está em `docs/dataset-protocol.md` §9. SPEC marcada como "Aguardando reaprovação humana". | SEC-06 de `reviews/SPEC-007/r1-security-report.md` (parte de `DATASET_DIR`) | Orquestrador, a pedido do humano |
| 2026-10-13 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
| 2026-10-17 | §3.1: autoriza o tester a fazer exatamente três ajustes em `edge/tests/acceptance/test_spec_007.py`: (1) `test_ca15_capture_page` deixa de exigir `disabled` na opção `collect`; (2) `test_extra_collect_mode_is_501` é removido ou passa a esperar 422; (3) a contagem `parafuso == 10` de `test_ca13_console_from_loopback` passa a valer só nas linhas `<tr class="inspection" …>`. Nenhum requisito nem CA desta SPEC muda; nenhum CA da SPEC-007 tem a intenção alterada. SPEC marcada como "Aguardando reaprovação humana". | SPEC_ISSUE-01 de `reviews/SPEC-010/r1-dev-report.md` (três testes de aceite da SPEC-007 verificavam o comportamento que esta SPEC substitui de propósito) | Orquestrador |
| 2026-10-17 | Correção do SPEC_ISSUE-01 reaprovada, junto com a regra "Testes de aceite de SPECs anteriores" (`architecture.md` §10); `Blocked` → `In Dev`, retomando a r1 (o código da r1 já está pronto; segue para o tester). | Fluxo do loop (§4 da skill `features`) | Humano (Carlos) |
