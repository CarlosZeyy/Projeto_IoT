# PRD — PartQC: Inspeção Visual de Qualidade com Celular, Borda e Nuvem

| Campo | Valor |
|---|---|
| Matéria | Aplicações de Cloud, IoT e Indústria 4.0 (Python) |
| Equipe | Dupla |
| Prazo | Apresentação entre 30/11 e 04/12/2026 |
| Custo alvo | R$ 0 (R-01) |
| Versão do documento | 1.0 — 2026-10-12 |
| Histórico | Ideia original (frutas + webcam) em `docs/archive/ideia-original.md` |

## 1. Problema

Em linhas de produção e almoxarifados, inspecionar peças metálicas (parafusos, porcas) e ferramentas ainda é trabalho manual, subjetivo e sem registro. Não se sabe a taxa de reprovação por lote, não se detecta quando o processo sai de controle e não há histórico consultável à distância.

## 2. Solução

Um sistema de inspeção visual em três camadas:

1. **Celular** do operador como câmera: abre uma página web, fotografa a peça e vê o resultado na hora.
2. **Notebook** como gateway de borda: recebe a foto pela rede local, roda um modelo de visão computacional e classifica a peça em **tipo** e **grau de estado** (perfeito, bom, mediano, ruim, inutilizável). Guarda os resultados numa fila resiliente.
3. **Nuvem**: API e banco guardam o histórico, e um dashboard mostra os indicadores de qualidade e a **carta de controle p (SPC)** por lote.

### Por que cobre as três frentes da matéria

| Frente | Onde aparece |
|---|---|
| IoT / Edge | Celular como sensor; notebook como gateway que processa localmente e só envia o resultado; fila offline com reenvio; pareamento por QR |
| Cloud | API REST, Postgres gerenciado e dashboard hospedados em free tier, acessíveis de qualquer lugar |
| Indústria 4.0 | Inspeção automatizada com visão computacional, rastreabilidade por lote, indicadores em tempo quase real e controle estatístico de processo |

### Metodologia de desenvolvimento

O projeto usa **SDD (Spec-Driven Development)** com agentes de IA, com autorização prévia do professor: toda entrega nasce de uma especificação (SPEC) com critérios de aceite testáveis, é implementada por um agente e verificada por outros agentes independentes (teste, revisão e segurança) antes do merge humano. Isso também é conteúdo da disciplina: mostra como IA e ML estão sendo usados hoje no desenvolvimento de software (ADR-011, `reviews/README.md`).

## 3. Personas

| Persona | Objetivo | Usa |
|---|---|---|
| **Operador** | Inspecionar peças de um lote rapidamente e saber se cada uma passa | Página `/capture` no celular |
| **Supervisor de qualidade** | Acompanhar a taxa de defeito, ver se o processo está sob controle e consultar o histórico | Dashboard |
| **Equipe (dupla)** | Coletar o dataset, treinar e avaliar o modelo, operar o sistema | Modo coleta, `ml/`, console da borda |
| **Avaliador (professor)** | Verificar a integração IoT + Cloud + Indústria 4.0 e a qualidade técnica | Demo ao vivo, dashboard, documentação |

## 4. Escopo

### 4.1 MVP (até a S4 — 08/11)

- Tipos de objeto: **parafuso** e **porca** de aço, mais o resultado `unknown` para o que não for reconhecido.
- Cinco graus de estado com rubrica objetiva (`docs/dataset-protocol.md`).
- Fluxo completo: celular → borda → nuvem → dashboard, com SPC por lote.
- Modo coleta para montar o dataset com o próprio celular.
- Fila offline com reenvio idempotente.
- Simulador de lotes (dados marcados `simulated`).
- Deploy em free tier.

### 4.2 Fase 2 (S5–S6 — até 22/11)

- Ferramentas manuais (alicate, chave inglesa, chave Allen, chave de fenda, chave Phillips): **identificação** obrigatória; grau de estado só se houver dados suficientes (critério na SPEC-016).
- Opcionais: alerta no Telegram quando o lote sai de controle (SPEC-017) e heartbeat com página de dispositivos (SPEC-018).

### 4.3 Fase 3 (só se a Fase 2 fechar no prazo)

- Ferramentas elétricas (esmerilhadeira, serra, furadeira, parafusadeira): **só identificação** (SPEC-021).
- Modo vídeo ao vivo com HTTPS (SPEC-019).
- Transporte MQTT (SPEC-020).

### 4.4 Fora do escopo

- Tornos e fresadoras. São grandes demais para fotografar com o celular e não há como gerar exemplos de estado. O parafuso inspecionado *é* o produto dessas máquinas.
- Hardware dedicado (Raspberry Pi, câmera industrial, esteira).
- Login de usuários no dashboard, retreino automático e MLOps completo.
- Detecção com caixas delimitadoras: o modelo classifica a imagem inteira, uma peça por foto.
- Avaliar o estado interno de ferramentas elétricas (motor, escovas).

## 5. Requisitos funcionais

| ID | Requisito | Prioridade | SPEC |
|---|---|---|---|
| RF-01 | O operador pareia o celular com a borda lendo um QR code exibido no console do notebook | Must | 007 |
| RF-02 | O operador informa o lote e fotografa a peça pela câmera traseira do celular, a partir do navegador | Must | 007 |
| RF-03 | A borda classifica tipo e grau e devolve ao celular, em até 3 s na LAN, o rótulo PT-BR, a confiança e a indicação "aprovada/reprovada" | Must | 008 |
| RF-04 | Objetos não reconhecidos ou com confiança baixa aparecem como "desconhecido" e não recebem grau | Must | 008 |
| RF-05 | Inspeções com confiança marginal são marcadas `needs_review` | Should | 008 |
| RF-06 | Cada inspeção é registrada na nuvem exatamente uma vez, mesmo com falhas de rede e reenvios | Must | 004, 009 |
| RF-07 | Sem nuvem, a borda continua funcionando e envia as pendências quando a conexão volta | Must | 009 |
| RF-08 | Modo coleta: o operador escolhe item, tipo, grau, rotulador e ângulo e fotografa; a imagem e uma linha do manifest são salvas localmente | Must | 010 |
| RF-09 | O dashboard mostra totais, distribuição dos 5 graus, taxa de defeito, série temporal e quebra por tipo, com filtros | Must | 005, 013 |
| RF-10 | O dashboard mostra a carta p por lote com limites e pontos fora de controle destacados | Must | 006, 013 |
| RF-11 | O dashboard mostra o histórico paginado com filtros | Must | 005, 013 |
| RF-12 | O dashboard tem a página "Sobre o modelo" com as métricas do `metrics.json` | Must | 013 |
| RF-13 | O dashboard indica claramente quando há dados simulados e permite filtrar por origem | Must | 013 |
| RF-14 | O simulador gera lotes com taxa de defeito configurável, incluindo lotes fora de controle | Must | 014 |
| RF-15 | Apenas dispositivos registrados podem gravar; o dashboard lê com uma chave de leitura | Must | 004 |
| RF-16 | Identificação de ferramentas manuais | Should (Fase 2) | 016 |
| RF-17 | Alerta no Telegram quando o lote sai de controle | Could | 017 |
| RF-18 | Heartbeat e página de dispositivos | Could | 018 |

## 6. Requisitos não funcionais

| ID | Requisito | Meta |
|---|---|---|
| RNF-01 | Custo | R$ 0 (R-01) |
| RNF-02 | Latência de inferência na borda (pré-processamento + modelo, CPU do notebook) | p95 ≤ 300 ms |
| RNF-03 | Tempo total foto → resultado no celular (LAN, foto já redimensionada) | p95 ≤ 3 s |
| RNF-04 | Confiabilidade do envio | 0 perdas e 0 duplicatas em teste com 200 inspeções e a nuvem derrubada por 2 min |
| RNF-05 | Privacidade | Nenhuma imagem sai da LAN (R-02) |
| RNF-06 | Segurança | Escritas autenticadas por dispositivo; RLS sem políticas públicas; segredos fora do Git |
| RNF-07 | Reprodutibilidade de ML | Seeds fixas, `training_config.json` e hash do split; teste de paridade torch × ONNX |
| RNF-08 | Portabilidade | Python 3.12; `uv sync` reproduz o ambiente; roda no Arch Linux do notebook da equipe |
| RNF-09 | Qualidade de código | ruff sem erros; pytest verde no CI; cobertura ≥ 80% em `qc_api.services` e `qc_edge.decision`/`outbox` |
| RNF-10 | Operação | Cold start da API absorvido pelo outbox; checklist do dia da demo (`docs/deployment-plan.md`) |

## 7. Métricas de sucesso

As metas são **iniciais** e serão revisadas depois do primeiro treino (S3). Não são garantias.

| Métrica | Meta MVP | Onde medir |
|---|---|---|
| Acurácia de tipo (parafuso/porca/outro) no teste | ≥ 95% | `metrics.json` |
| Kappa ponderado quadrático (QWK) do grau | ≥ 0,75 | `metrics.json` |
| Acerto do grau com tolerância de ±1 | ≥ 90% | `metrics.json` |
| Recall de `unusable` | ≥ 90% | `metrics.json` |
| Recall de "defeituoso" (`poor` + `unusable`) | ≥ 90% | `metrics.json` |
| Concordância entre rotuladores (QWK na amostra dupla) | ≥ 0,6 (mínimo) e ≥ 0,8 (desejável) | `ml/reports/agreement.json` |
| Demo de ponta a ponta sem intervenção manual | 20 peças seguidas | Ensaio da S7 |
| RNF-04 (0 perdas e 0 duplicatas) | Cumprido | Teste de aceite da SPEC-009 |

## 8. Premissas e riscos principais

| Risco | Impacto | Mitigação |
|---|---|---|
| O Wi-Fi do campus isola os clientes e o celular não alcança o notebook | Demo inviável | Na apresentação, usar por padrão a **rede própria** (hotspot do celular), que independe do campus; ancoragem USB como plano C; sem túnel público (R-02). Ensaiar essa topologia em casa |
| A corrosão demora ou não aparece (peça zincada ou inox) | Falta de dados nos graus intermediários | Comprar aço comum; lotes escalonados a partir da S1; ver `dataset-protocol.md` |
| Graus subjetivos, com rotuladores discordando | Modelo instável | Rubrica com % de área e regra de precedência; dupla rotulagem com kappa |
| Pouco dado nos extremos (`perfect`, `unusable`) | Recall ruim | Meta por grau; peças novas para `perfect`; dano mecânico controlado para `unusable` |
| Mudança de domínio (luz, fundo, celular) | Erro na demo | Dataset capturado com os mesmos celulares e o mesmo fundo; ensaio no local da apresentação |
| Free tier hiberna ou pausa | Primeira chamada lenta ou banco pausado | Outbox; ping por GitHub Actions; checklist pré-demo |
| Escopo de ferramentas cresce demais | Atraso | Camadas; Fase 3 só se a Fase 2 fechar |
| Professor não aceitar HTTP no lugar de MQTT ou o uso de agentes de IA | Retrabalho | `docs/professor-questions.md` respondido até a S2 |

## 9. Marcos

Ver `docs/plan.md`. Resumo:
- **M1 (18/10):** documentação aprovada e corrosão iniciada.
- **M2 (08/11):** MVP de ponta a ponta.
- **M3 (22/11):** modelo congelado e Fase 2.
- **M4 (29/11):** ensaio final.
- **M5:** apresentação.
