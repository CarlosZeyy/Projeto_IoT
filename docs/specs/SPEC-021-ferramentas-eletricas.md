# SPEC-021: Fase 3 — ferramentas elétricas (identificação)

| Campo | Valor |
|---|---|
| Status | Draft |
| Rodada atual | — |
| Autor da implementação | ml-engineer (dados e modelo) + developer (contrato, migração, borda e dashboard) |
| Tags | contrato |
| Depende de | SPEC-016 |
| Semana alvo | S8 (só se a Fase 2 fechar no prazo) |
| Requisitos cobertos | PRD §4.3 |
| ADRs relevantes | ADR-001, ADR-004, ADR-014; o mesmo ADR novo da SPEC-016 sobre grau nulo |

> **Rascunho.** Precisa de refinamento do `architect`, da resolução das perguntas em aberto da SPEC-016 e de aprovação humana antes de virar `Ready`.

## 1. Contexto

O PRD §4.3 prevê, só se a Fase 2 fechar no prazo, a **identificação** de ferramentas elétricas: esmerilhadeira, serra, furadeira e parafusadeira. O estado interno (motor, escovas) está fora do escopo (PRD §4.4), por isso **não há grau**. `docs/architecture.md` §3.1 lista os valores `angle_grinder`, `saw`, `drill` e `cordless_screwdriver`.

## 2. Objetivo

Um modelo novo que identifica as 4 ferramentas elétricas, além dos tipos anteriores, sem atribuir grau a elas.

## 3. Escopo

### 3.1 Dentro

- Contrato (`qc-contracts` minor): os 4 valores novos de `ObjectType` e os rótulos PT-BR (esmerilhadeira, serra, furadeira, parafusadeira).
- Migração do `check` de `object_type`.
- Dados: fotos próprias e conjuntos públicos (§4); os 4 tipos como **sem grau** (loss de grau mascarada).
- Borda e dashboard: exibir os tipos novos sem grau.

### 3.2 Fora

- Grau de estado de ferramentas elétricas; tornos e fresadoras (PRD §4.4).

## 4. Requisitos-chave (preliminares)

- **Fontes** (licença e números **a verificar** antes de usar):
  - Angle grinder (<https://universe.roboflow.com/shaheens-workspace-3ut7f/angle-grinder>): cerca de 183 imagens, CC BY 4.0, exige atribuição;
  - a classe de serra do I3D-Tools (ver SPEC-016);
  - fotos próprias, com distância maior que a do protocolo (as ferramentas não cabem a 20 cm).
- Imagens públicas só em treino e validação; o teste usa fotos próprias.
- O comportamento depende da decisão da SPEC-016 sobre `grade = null` para tipos sem grau: sem ela, esta SPEC não pode ser implementada.
- Métricas no `metrics.json` com os tipos novos, sem omitir nenhum (R-11).

## 5. Critérios de aceite (preliminares)

- **CA-01 (preliminar)** — *Dado* o contrato novo, *quando* um `InspectionCreate` com `object_type="drill"` é validado conforme a regra de grau nulo definida no ADR, *então* é aceito, e `OBJECT_TYPE_LABELS_PT["drill"] == "furadeira"`.
- **CA-02 (preliminar)** — *Dado* uma inspeção de ferramenta elétrica, *quando* a carta p é calculada, *então* ela não entra no SPC (não tem grau, como `unknown`).
- **CA-03 (preliminar, R-11)** — *Dado* o split com ferramentas elétricas, *quando* verificado, *então* nenhum `item_id` aparece em dois splits e nenhuma imagem pública está no teste.
- **CA-04 (preliminar)** — *Dado* o modelo novo, *quando* avaliado, *então* o `metrics.json` traz a matriz de confusão de tipo com todos os tipos.

## 6. Perguntas em aberto

1. **Invariante do contrato:** a mesma da SPEC-016 (`grade` nulo só para `unknown`). Aqui ela é obrigatória, porque nenhum tipo elétrico tem grau.
2. Furadeira e parafusadeira são muito parecidas na foto. Juntar as duas numa classe só, ou aceitar uma confusão alta e reportá-la?
3. Há dados próprios suficientes? A dupla tem acesso às 4 ferramentas? Meta mínima por classe (ex.: 100 imagens de ≥ 5 unidades)?
4. As ferramentas elétricas entram no "teste estendido" proposto na SPEC-016 (pergunta 2)?
