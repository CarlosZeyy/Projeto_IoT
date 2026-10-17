# SPEC-016: Fase 2 — ferramentas manuais

| Campo | Valor |
|---|---|
| Status | Draft |
| Rodada atual | — |
| Autor da implementação | ml-engineer (dados, treino e modelo) + developer (contrato, migração, borda e dashboard) |
| Tags | contrato |
| Depende de | SPEC-012 (e SPEC-002, SPEC-003, SPEC-008, SPEC-011, SPEC-013 para os ajustes) |
| Semana alvo | S6 |
| Requisitos cobertos | RF-16; PRD §4.2 |
| ADRs relevantes | ADR-001, ADR-004, ADR-005, ADR-014; **ADR novo** sobre grau nulo em tipos sem grau (pendente) |

> **Rascunho.** Precisa de refinamento do `architect`, do ADR indicado em §6 e de aprovação humana antes de virar `Ready`.

## 1. Contexto

O PRD §4.2 prevê a identificação de ferramentas manuais na Fase 2, com grau de estado só quando houver dados suficientes. `docs/architecture.md` §3.1 já lista os valores futuros de `ObjectType`: `pliers`, `adjustable_wrench`, `allen_key`, `flat_screwdriver`, `phillips_screwdriver`. A rubrica de ferramentas está em rascunho em `docs/dataset-protocol.md` §1.1.

## 2. Objetivo

Um modelo `partqc-mnv3-v<N>` que identifica as 5 ferramentas manuais (além de parafuso, porca e `other`) e, para cada ferramenta que cumprir o critério de dados, também classifica o grau.

## 3. Escopo

### 3.1 Dentro

- Contrato: `qc-contracts` minor (0.x → 0.x+1) com os 5 valores novos de `ObjectType` e os rótulos PT-BR (alicate, chave inglesa, chave Allen, chave de fenda, chave Phillips).
- Banco: migração `infra/migrations/NNN_tool_object_types.sql` que atualiza o `check` de `object_type` (e o da invariante de grau, conforme o ADR).
- Dados: prefixo `T-` no `item_id`; tipos novos em `qc_ml.data`; finalização da rubrica §1.1 do protocolo.
- Modelo: `labels.json` com os tipos novos; loss de grau mascarada para ferramentas sem grau (já prevista na skill `ml-pipeline` §4).
- Borda (SPEC-008) e dashboard (SPEC-013): exibir os tipos novos e tratar ferramenta sem grau.

### 3.2 Fora

- Ferramentas elétricas: SPEC-021. Detecção com caixas na inferência: fora do escopo (PRD §4.4).

## 4. Requisitos-chave (preliminares)

- **Identificação obrigatória** para os 5 tipos.
- **Critério de grau por tipo:** grau só se houver **≥ 60 imagens por grau, vindas de ≥ 5 peças físicas**, nos 5 graus. Senão, o grau do tipo fica mascarado no treino e o tipo entra em `labels.json` → `ungraded_object_types` (chave nova, a confirmar com a SPEC-008).
- **Fontes de dados** (licença e números **a verificar** na fonte antes de usar):
  - fotos próprias, com o protocolo de captura (`dataset-protocol.md` §3);
  - I3D-Tools (<https://huggingface.co/datasets/i3dlabiisc/I3D-Tools-Dataset>): MIT, cerca de 35 mil imagens, 16 classes, incluindo alicate, chave inglesa, chave de fenda e serra; formato de detecção → recortar as caixas; **não** tem chave Allen;
  - Workshop Tools (<https://universe.roboflow.com/long-oybdw/workshop-tools-swpfs>): CC BY 4.0, exige atribuição.
- Imagens públicas: só treino e validação; o teste das ferramentas usa **só fotos próprias** (domínio da demo). Cada imagem pública é tratada como uma peça (`item_id` próprio).
- A ordem de deploy segue a skill `contrato-api`: contracts → banco → API → dashboard → borda.
- **Carta p (SPC):** a SPEC diz se os tipos novos entram na carta agregada (hoje, a consulta da SPEC-006 usa `object_type <> 'unknown'`, então um tipo novo entraria sozinho) e no filtro `object_type` da rota. Hoje, o `SpcObjectType` de `qc_api.routers.metrics` deriva de `ObjectType` menos `unknown` e aceitaria um valor novo sem decisão explícita. A SPEC troca esse enum dinâmico por uma classe declarada (`class SpcObjectType(StrEnum)`), com um teste que compara os membros com a lista decidida, e atualiza o CA-13 da SPEC-006 se a lista mudar (RV-01 de `reviews/SPEC-006/r1-review-report.md`).

## 5. Critérios de aceite (preliminares)

- **CA-01 (preliminar)** — *Dado* o contrato novo, *quando* um `InspectionCreate` com `object_type="pliers"` é validado, *então* é aceito, e `OBJECT_TYPE_LABELS_PT["pliers"] == "alicate"`.
- **CA-02 (preliminar)** — *Dado* a migração aplicada, *quando* uma inspeção `adjustable_wrench` é gravada, *então* o banco aceita; com `object_type="hammer"`, a API responde 422.
- **CA-03 (preliminar)** — *Dado* um tipo com 59 imagens em algum grau, *quando* o relatório de dados roda, *então* o tipo aparece como sem grau e a loss de grau é mascarada para ele.
- **CA-04 (preliminar, R-11)** — *Dado* o split com ferramentas, *quando* verificado, *então* nenhum `item_id` aparece em dois splits e nenhuma imagem pública está no teste.
- **CA-05 (preliminar)** — *Dado* o modelo novo, *quando* avaliado, *então* o `metrics.json` traz `type_accuracy` e a matriz de confusão com os 8 tipos, sem omitir nenhum.

## 6. Perguntas em aberto

1. **Invariante do contrato (bloqueante):** hoje `grade` é `null` **se e somente se** `object_type == unknown` (`architecture.md` §3.2 e `check` do banco). Uma ferramenta sem grau precisaria de `grade = null` com `object_type != unknown`. Opções: (a) mudar a invariante para `grade is None ⇔ object_type ∈ {unknown} ∪ tipos sem grau` (ADR + versão major ou minor? a skill `contrato-api` não classifica mudança de invariante); (b) só aceitar ferramentas que cumpram o critério de grau; (c) campo novo `graded: bool`. Precisa de ADR e decisão humana.
2. **Teste congelado:** a skill `ml-pipeline` §2 manda peças novas só para treino/val. Sem um ADR, as ferramentas **não teriam teste**. Proposta: ADR que permita estender o teste **só com peças das classes novas**, sem mexer nas atribuições existentes.
3. `item_id` de imagens públicas: o padrão `^[SNOT]-\d{3}$` não comporta milhares de imagens. Novo prefixo e mais dígitos? Isso muda o protocolo e a SPEC-011.
4. `labels_overrides.csv` só corrige grau. Corrigir tipo (ex.: uma imagem `other` que é uma ferramenta) exige coluna nova?
5. Mapeamento de classes públicas (ex.: "wrench" genérico × chave inglesa) e quantos recortes por imagem usar.
6. A rubrica §1.1 (dano funcional de ferramentas) precisa de um piloto de concordância como o de parafusos?
7. As ferramentas entram na carta p junto com parafusos e porcas, em cartas separadas por tipo, ou ficam fora do SPC (§4, "Carta p")?

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-17 | §4 ganha o requisito "Carta p (SPC)" e §6 ganha a pergunta 7: os tipos novos e o filtro `object_type` do SPC precisam de decisão explícita. A SPEC continua `Draft`. | RV-01 de `reviews/SPEC-006/r1-review-report.md` | Orquestrador, a pedido do humano |
