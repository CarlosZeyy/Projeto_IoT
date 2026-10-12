# Plano, cronograma e quadro de SPECs

Atualizado pelo orquestrador (sessão principal) a cada mudança de status de SPEC. O status oficial de cada SPEC fica **no próprio arquivo da SPEC**; esta tabela é o espelho para leitura rápida.

## 1. Cronograma

| Semana | Período | Entregas | Marco |
|---|---|---|---|
| S1 | 12–18/out | Documentação aprovada. Peças catalogadas (as que a dupla já tem) e **corrosão iniciada** só para completar os graus intermediários. Piloto da rubrica (30 fotos, QWK). Teste de rede em casa com os dois celulares (Wi-Fi e hotspot). SPEC-001 e SPEC-002 (pergunta 4 já resolvida: uso de IA autorizado) | **M1** |
| S2 | 19–25/out | SPEC-003, 004, 007, 010. API rodando localmente (Postgres local/Supabase dev). Cerca de 500 imagens coletadas | |
| S3 | 26/out–01/nov | SPEC-008, 009, 011, 012 (baseline v1). Cerca de 1.200 imagens. Dupla rotulagem e QWK. Teste final congelado | |
| S4 | 02–08/nov | SPEC-005, 006, 013, 014, 015. API publicada no Render. **MVP de ponta a ponta** com demo interna | **M2** |
| S5 | 09–15/nov | Melhorias do modelo (ablação CORN, `unusable_threshold`, classe `other`); relatório de métricas; endurecimento (RNF-04, cobertura) | |
| S6 | 16–22/nov | SPEC-016 (ferramentas manuais: identificação); SPEC-017/018 se der tempo. **Congelamento do modelo** | **M3** |
| S7 | 23–29/nov | Testes finais, documentação final, vídeo de backup da demo, ensaio completo em casa com a topologia da apresentação (hotspot do celular) | **M4** |
| S8 | 30/nov–04/dez | Folga, relatório e slides, apresentação. Fase 3 só se a S6 fechou no prazo | **M5** |

### Tarefas humanas (fora do loop de agentes)

| Quando | Tarefa | Responsável |
|---|---|---|
| S1 | Catalogar as peças que a dupla já tem (parafusos/porcas novos e enferrujados, pregos, ferramentas) com `item_id`; montar lotes de corrosão só se faltarem graus intermediários (`good`, `fair`) | Dupla |
| S1 | Confirmar com o professor as perguntas ainda abertas (1, 2, 3, 5, 6, 7) quando houver oportunidade; nenhuma bloqueia o início do código | Dupla |
| S1 | ~~Criar contas: Supabase, Render, Streamlit Community Cloud~~ **Feito em 2026-10-12** (projeto Supabase já criado). Configuração dos serviços só na SPEC-015 | Dupla |
| S1 | Instalar o `uv` no notebook (`sudo pacman -S uv`) antes da SPEC-001 | Dupla |
| S2 | Testar `<input capture>` nos dois celulares e a conexão celular → notebook, em casa, pelo Wi-Fi e pelo hotspot (CA manual da SPEC-007) | Dupla |
| S1–S3 | Fotografar no modo coleta (assim que a SPEC-010 estiver pronta; antes disso, com a câmera normal, seguindo o protocolo e anotando o `item_id`) | Dupla |
| S3 | Rotulagem dupla (20%) | Dupla |
| Contínuo | Aprovar SPECs (`Draft` → `Ready`) e fazer o merge dos PRs | Dupla |

## 2. Quadro de SPECs

Status possíveis: `Draft` → `Ready` → `In Dev` → `In Test` → `In Review` → `In Security` (só com a tag `security`/`deploy`) → `Done`. Também existem `Blocked` e `Escalated` (estourou as 3 rodadas).

| SPEC | Título | Dono | Tags | Depende de | Semana | Status |
|---|---|---|---|---|---|---|
| [001](specs/SPEC-001-setup-repositorio.md) | Setup do repositório e ferramentas | developer | infra | — | S1 | Done |
| [002](specs/SPEC-002-pacotes-compartilhados.md) | Pacotes compartilhados v0 (`qc-contracts` e `qc-preprocess`) | developer | contrato | 001 | S1 | In Test (r2) |
| [003](specs/SPEC-003-schema-banco.md) | Schema Supabase, migrações e RLS | developer | security | 002 | S2 | Ready |
| [004](specs/SPEC-004-api-ingestao.md) | API de ingestão e autenticação de dispositivos | developer | security | 002, 003 | S2 | Ready |
| [005](specs/SPEC-005-api-leitura-metricas.md) | API de leitura e métricas | developer | security | 004 | S4 | Ready |
| [006](specs/SPEC-006-spc.md) | SPC: carta p por lote | developer | security | 004 | S4 | Ready |
| [007](specs/SPEC-007-edge-gateway-captura.md) | Gateway de borda, página de captura e pareamento | developer | security | 002 | S2 | Ready |
| [008](specs/SPEC-008-edge-inferencia-decisao.md) | Inferência ONNX e decisão na borda | developer | — | 002, 007 | S3 | Ready |
| [009](specs/SPEC-009-edge-outbox-publisher.md) | Outbox SQLite e publisher HTTP | developer | security | 004, 007 | S3 | Ready |
| [010](specs/SPEC-010-modo-coleta.md) | Modo coleta de dataset | developer | security | 007 | S2 | Ready |
| [011](specs/SPEC-011-ml-dados-split.md) | ML: manifest, split e augmentations | ml-engineer | — | 001, 002, 010 | S3 | Ready |
| [012](specs/SPEC-012-ml-treino-export.md) | ML: treino, avaliação, ONNX e paridade | ml-engineer | — | 011 (e 002) | S3 | Ready |
| [013](specs/SPEC-013-dashboard.md) | Dashboard Streamlit | developer | security | 005, 006 (e 002, 012) | S4 | Ready |
| [014](specs/SPEC-014-simulador.md) | Simulador de lotes | developer | security | 004, 006 | S4 | Ready |
| [015](specs/SPEC-015-deploy.md) | Deploy e keep-alive | security-devops | deploy, security | 004, 013 (e 003, 005, 006) | S4 | Ready |
| [016](specs/SPEC-016-ferramentas-manuais.md) | Fase 2: ferramentas manuais | ml-engineer + developer | contrato | 012 (e 002, 003, 008, 011, 013) | S6 | Draft |
| [017](specs/SPEC-017-alertas-telegram.md) | Fase 2: alertas no Telegram | developer | security | 006 (e 003, 004) | S6 | Draft |
| [018](specs/SPEC-018-heartbeat-dispositivos.md) | Fase 2: heartbeat e dispositivos | developer | contrato, security | 004 (e 002, 003, 009, 013) | S6 | Draft |
| [019](specs/SPEC-019-modo-ao-vivo.md) | Fase 3: modo vídeo ao vivo (HTTPS) | developer | security | 008 (e 007, 009) | S8 | Draft |
| [020](specs/SPEC-020-mqtt.md) | Fase 3: transporte MQTT | developer | security | 009 (e 004) | S8 | Draft |
| [021](specs/SPEC-021-ferramentas-eletricas.md) | Fase 3: ferramentas elétricas (identificação) | ml-engineer + developer | contrato | 016 | S8 | Draft |

> As SPECs `Ready` foram escritas na fundação documental e **aguardam a confirmação humana** antes da primeira execução do loop. Na prática, ao pedir "rode o loop da SPEC-XXX", a dupla está aprovando aquela SPEC.

## 3. Ordem sugerida (caminho crítico)

```text
001 → 002 ─┬─► 003 → 004 ─┬─► 005, 006, 014 ─► 013 ─► 015 ─┐
           │              └─► 009 ◄──┐                      ├─► MVP (S4)
           └─► 007 ─┬─► 008 ─────────┼──────────────────────┤
                    ├────────────────┘                      │
                    └─► 010 ─► 011 ─► 012 (modelo v1 → usado pela 008) ┘
```

- O **ML depende de dados**: a coleta (humana) começa já na S1, mesmo antes da SPEC-010.
- A SPEC-008 é desenvolvida com um **modelo dummy** (ONNX gerado nos testes, com as mesmas entradas e saídas) e não depende da SPEC-012. O modelo real é só um artefato trocado via `MODEL_DIR`.

## 4. Registro de decisões de escopo

| Data | Decisão |
|---|---|
| 2026-10-12 | Escopo em camadas: MVP parafuso/porca; Fase 2 ferramentas manuais; Fase 3 elétricas (só identificação); tornos e fresadoras fora |
