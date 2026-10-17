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
| Contínuo | Aprovar SPECs (`Draft` → `Ready`) e ADRs (`Proposto` → `Aceito`); vetar um merge quando quiser (o merge dos PRs é feito pelo orquestrador sob delegação, ADR-016) | Dupla |

## 2. Quadro de SPECs

Status possíveis: `Draft` → `Ready` → `In Dev` → `In Test` → `In Review` → `In Security` (só com a tag `security`/`deploy`) → `Done`. Também existem `Blocked` e `Escalated` (estourou as 3 rodadas).

| SPEC | Título | Dono | Tags | Depende de | Semana | Status |
|---|---|---|---|---|---|---|
| [001](specs/SPEC-001-setup-repositorio.md) | Setup do repositório e ferramentas | developer | infra | — | S1 | Done |
| [002](specs/SPEC-002-pacotes-compartilhados.md) | Pacotes compartilhados v0 (`qc-contracts` e `qc-preprocess`) | developer | contrato | 001 | S1 | Done |
| [003](specs/SPEC-003-schema-banco.md) | Schema Supabase, migrações e RLS | developer | security | 002 | S2 | Done |
| [004](specs/SPEC-004-api-ingestao.md) | API de ingestão e autenticação de dispositivos | developer | security | 002, 003, 023, 024 | S2 | Done |
| [005](specs/SPEC-005-api-leitura-metricas.md) | API de leitura e métricas | developer | security | 004 | S4 | Done |
| [006](specs/SPEC-006-spc.md) | SPC: carta p por lote | developer | security | 004 | S4 | Done |
| [007](specs/SPEC-007-edge-gateway-captura.md) | Gateway de borda, página de captura e pareamento | developer | security | 002, 023, 024 | S2 | Done (CA-20/21 manuais pendentes) |
| [008](specs/SPEC-008-edge-inferencia-decisao.md) | Inferência ONNX e decisão na borda | developer | — | 002, 007 | S3 | Ready |
| [009](specs/SPEC-009-edge-outbox-publisher.md) | Outbox SQLite e publisher HTTP | developer | security | 004, 007, 025 | S3 | Ready |
| [010](specs/SPEC-010-modo-coleta.md) | Modo coleta de dataset | developer | security | 007 | S2 | In Security (r1) |
| [011](specs/SPEC-011-ml-dados-split.md) | ML: manifest, split e augmentations | ml-engineer | — | 001, 002, 010 | S3 | Ready |
| [012](specs/SPEC-012-ml-treino-export.md) | ML: treino, avaliação, ONNX e paridade | ml-engineer | — | 011 (e 002) | S3 | Ready |
| [013](specs/SPEC-013-dashboard.md) | Dashboard Streamlit | developer | security | 005, 006, 026 (e 002, 012) | S4 | Ready |
| [014](specs/SPEC-014-simulador.md) | Simulador de lotes | developer | security | 004, 006 | S4 | Done |
| [015](specs/SPEC-015-deploy.md) | Deploy e keep-alive | security-devops | deploy, security | 004, 013, 026, 027 (e 003, 005, 006, 014) | S4 | Ready |
| [016](specs/SPEC-016-ferramentas-manuais.md) | Fase 2: ferramentas manuais | ml-engineer + developer | contrato | 012 (e 002, 003, 008, 011, 013) | S6 | Draft |
| [017](specs/SPEC-017-alertas-telegram.md) | Fase 2: alertas no Telegram | developer | security | 006 (e 003, 004) | S6 | Draft |
| [018](specs/SPEC-018-heartbeat-dispositivos.md) | Fase 2: heartbeat e dispositivos | developer | contrato, security | 004 (e 002, 003, 009, 013) | S6 | Draft |
| [019](specs/SPEC-019-modo-ao-vivo.md) | Fase 3: modo vídeo ao vivo (HTTPS) | developer | security | 008 (e 007, 009) | S8 | Draft |
| [020](specs/SPEC-020-mqtt.md) | Fase 3: transporte MQTT | developer | security | 009 (e 004) | S8 | Draft |
| [021](specs/SPEC-021-ferramentas-eletricas.md) | Fase 3: ferramentas elétricas (identificação) | ml-engineer + developer | contrato | 016 | S8 | Draft |
| [022](specs/SPEC-022-manutencao-setup.md) | Manutenção do setup (hook, CI sem senha, commits do architect) | developer | infra | 001 | S1 | Done |
| [023](specs/SPEC-023-pacotes-compartilhados-0-2.md) | Pacotes compartilhados 0.2.0 (teto de `latency_ms`, proporção da imagem, flag de JPEG truncado) | developer | contrato, security | 002 | S2 | Done |
| [024](specs/SPEC-024-preprocess-0-3-scans-jpeg.md) | `qc-preprocess` 0.3.0 (limite de scans do JPEG) | developer | security | 023 | S2 | Done |
| [025](specs/SPEC-025-manutencao-borda-host-rede.md) | Manutenção da borda (Host do console, rede, limitador e permissões) | developer | security | 007 | S3 | Ready |
| [026](specs/SPEC-026-spc-teto-de-lotes.md) | Carta p com teto de lotes (`qc-contracts` 0.3.0) | developer | contrato, security | 006 (e 004, 023) | S4 | In Security (r1) |
| [027](specs/SPEC-027-manutencao-api-banco-simulador.md) | Manutenção da API, do banco e do simulador (`check` da `002`, SQLSTATE, argparse, teste intermitente) | developer | security | 003, 005, 014 (e 004) | S4 | Ready |

> As SPECs `Ready` foram escritas na fundação documental e **aguardam a confirmação humana** antes da primeira execução do loop. Na prática, ao pedir "rode o loop da SPEC-XXX", a dupla está aprovando aquela SPEC.

## 3. Ordem sugerida (caminho crítico)

```text
001 → 002 ─┬─► 003 → 004 ─┬─► 005, 006, 014 ─► 026 ─► 013 ─► 027 ─► 015 ─┐
           │              └─► 009 ◄──┐                                    ├─► MVP (S4)
           └─► 007 ─┬─► 008 ─────────┼────────────────────────────────────┤
                    ├─► 025 ─────────┘                                    │
                    └─► 010 ─► 011 ─► 012 (modelo v1 → usado pela 008) ───┘
```

- A **SPEC-023** (pacotes 0.2.0, pendências do review da SPEC-002) entra **antes** da 004 e da 007 e pode correr em paralelo com a 003 (`002 → 023 → 004/007`).
- A **SPEC-024** (`qc-preprocess` 0.3.0, SEC-01 do security-report da SPEC-023) entra **antes** da 007 (`023 → 024 → 007`). A 004 depende dela só pela migração das expectativas de versão (abaixo), e a 024 já está mergeada (PR #9).
- As pendências de produção do executor de migrações (SPEC-003) ficam na **SPEC-015**. As duas regras de testes de `architecture.md` §10, "sem suíte dentro da suíte" e "expectativas de versão" (migração única), são aplicadas pelo tester da **SPEC-004**.
- As pendências da SPEC-024: o dimensionamento do limitador e os limites próprios da rota de captura (3 MiB e 4 M pixels) entram na **SPEC-007** (§4.6 e §4.7) e são herdados pela **SPEC-010**. O problema `too_many_jpeg_scans` entra na **SPEC-011**, e a "foto com movimento" desligada, no `docs/dataset-protocol.md` §3.
- As pendências dos portões r1 da **SPEC-007** (PR #12):
  - **SPEC-025** (nova): validação do `Host` do console contra DNS rebinding (SEC-01, média), espera do limitador fora do threadpool (SEC-03), `EDGE_HOST` só IPv4 (SEC-04), permissões de `captures/` (SEC-06), CLI estrita (RV-05) e o `edge/README.md` (firewall por sub-rede e só em runtime, token novo a cada subida, aviso das bridges do Docker: SEC-05, SEC-07, RV-04). Ela tem de estar `Done` **antes do merge da SPEC-009** (`007 → 025 → 009`), que passou a depender dela;
  - **SPEC-010**: permissões de `DATASET_DIR` (SEC-06). A retenção das fotos de inspeção está em `docs/dataset-protocol.md` §9;
  - **SPEC-007** (texto, sem reaprovação): os números medidos do custo por slot (SEC-02).
  - **Decisão futura:** depois do passo 6 do CA-20 da SPEC-007, se o maior arquivo real dos dois celulares ficar bem abaixo de 3 MiB, uma SPEC posterior pode baixar `CAPTURE_MAX_BYTES` e `CAPTURE_MAX_REQUEST_BYTES` para ~2× o maior medido (o custo da inundação de segmentos cai na mesma proporção). Pode entrar como emenda da SPEC-010, se ela ainda não tiver começado, ou numa SPEC curta.
- As pendências da **SPEC-004** (mergeada):
  - **SPEC-005**: `IntegrityError` na escrita → 422 com log só do SQLSTATE e 500 genérico sem a mensagem de `psycopg.Error` (SEC-04-01 = RV-01; regra em `architecture.md` §4);
  - **SPEC-009**: o publisher registra do 422 só um resumo, nunca o corpo (SEC-04-04);
  - **SPEC-015**: riscos aceitos no `deployment-plan.md` (rajada anônima no pool e log do `psycopg.pool`) e registro de dispositivos com `--env-file` (SEC-04-02, 03 e 05);
  - **SPEC-025** (tester): as docstrings desatualizadas dos testes de aceite das SPECs 022 e 023 (RV-02).
- As pendências das **SPECs 005, 006 e 014** (portões r1, mergeados):
  - **SPEC-026** (nova): teto da carta p (SEC-06-01, média): últimos `max_points` lotes válidos (padrão 100, máximo 500), 50 excluídos mais recentes, totais na resposta, base de `p̄` na história inteira e corte no SQL (ADR-017, `Proposto`); `qc-contracts` 0.3.0; `LotCounts` mais estrito (RV-03 da 006). Ela tem de estar `Done` **antes de a SPEC-013 entrar em `In Dev`** (`026 → 013`);
  - **SPEC-027** (nova): migração `002` com os `check` de `model_version`, `inspection_id` v4 e faixa das datas (RV-01/SEC-05-02 da 005, INFO-01 da 006); SQLSTATE no log da escrita (RV-03 da 005); simulador sem eco de valores, URL só com ASCII visível e números de lote limitados (SEC-01 a SEC-04 da 014); correção, pelo tester, do teste intermitente da SPEC-004 (RV-02 da 005). Ela entra antes da SPEC-015, para a produção receber a `002` na primeira migração e o simulador corrigido;
  - **SPEC-013**: cache com TTL em toda leitura, origem sempre visível, uma carta por origem e o aviso de carta cortada (INFO-01/02 das 005 e 006);
  - **SPEC-015**: `statement_timeout` por `alter role`, geração e troca da `READ_API_KEY`, limites do Render (512 MB e 0,1 CPU) e uso do simulador em produção (SEC-05-01, INFO-02, SEC-07);
  - **SPEC-014** (só texto, sem reaprovação): comportamentos de 3xx/4xx e validação extra de URL (RV-04);
  - **SPEC-016** e **SPEC-017** (rascunhos): tipos da Fase 2 na carta (RV-01 da 006) e alertas sem recalcular a história inteira (SEC-06-01).
- O **ML depende de dados**: a coleta (humana) começa já na S1, mesmo antes da SPEC-010.
- A SPEC-008 é desenvolvida com um **modelo dummy** (ONNX gerado nos testes, com as mesmas entradas e saídas) e não depende da SPEC-012. O modelo real é só um artefato trocado via `MODEL_DIR`.

## 4. Registro de decisões de escopo

| Data | Decisão |
|---|---|
| 2026-10-12 | Escopo em camadas: MVP parafuso/porca; Fase 2 ferramentas manuais; Fase 3 elétricas (só identificação); tornos e fresadoras fora |
| 2026-10-13 | SPEC-025 (manutenção da borda) criada para as pendências da SPEC-007; a SPEC-009 passa a depender dela. Fotos de inspeção fora do dataset, com retenção até a entrega (`docs/dataset-protocol.md` §9) |
| 2026-10-17 | ADR-017 (`Proposto`): carta p limitada aos últimos lotes válidos, com a base de `p̄` na história inteira. SPEC-026 (teto da carta, contrato 0.3.0) e SPEC-027 (manutenção da API, do banco e do simulador) criadas como `Draft`. SPEC-013 e SPEC-015 alteradas, aguardando reaprovação. Ordem: `026 → 013 → 027 → 015` |
