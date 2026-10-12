# [ARQUIVO HISTÓRICO] Especificação v0 — Sistema de Inspeção Visual de Qualidade (frutas + webcam)

> **Este documento está superado.** Ele registra a ideia inicial, antes das conversas de planejamento de 2026-10-12. As decisões vigentes estão em `docs/PRD.md`, `docs/architecture.md` e `docs/adr/`. Principais mudanças:
>
> - frutas → parafusos e porcas (ferramentas em fases posteriores);
> - classificação binária ou de 6 classes → tipo + 5 graus de estado;
> - webcam do notebook → câmera do celular via página web, com o notebook como gateway de borda;
> - TensorFlow/Keras → PyTorch/timm com export ONNX;
> - lote de 50 inspeções consecutivas → lote informado pelo operador.
>
> O texto abaixo é a cópia da versão recebida, que termina na seção 9.4.

---

**Matéria:** Aplicações de Cloud, IoT e Indústria 4.0 (Python)
**Equipe:** dupla (2 pessoas)
**Estado do documento:** pré-planejamento. Nada foi implementado ainda e o escopo ainda não foi validado com o professor.
**Custo alvo:** R$ 0 (somente free tiers e software livre)

## 1. Visão geral

Um sistema de controle de qualidade automatizado. Uma webcam faz o papel de câmera de linha de produção. Um modelo de visão computacional roda **localmente (edge)** e classifica cada fruta como **fresca** ou **estragada**. Cada inspeção é enviada para uma **API na nuvem**, gravada em um banco de dados e exibida em um **dashboard** com indicadores de qualidade e uma **carta de controle estatístico de processo (SPC)**.

| Frente | Como aparece no projeto |
|---|---|
| IoT / Edge | Dispositivo de borda (webcam + notebook) captura e processa localmente. Só o resultado sobe, não o vídeo. Há telemetria de saúde do dispositivo (heartbeat, FPS). |
| Cloud | API, banco e dashboard hospedados em nuvem, acessíveis remotamente. |
| Indústria 4.0 | Inspeção visual automatizada, dados de qualidade em tempo quase real e controle estatístico de processo (SPC). |

Fluxo: Webcam → recorte da área de inspeção → modelo (borda) → decisão estável → fila local (SQLite) → envio (HTTP ou MQTT) → API → Postgres → Dashboard.

## 2. Objetivos

**Geral:** desenvolver um sistema de inspeção visual automatizada que integre visão computacional, processamento na borda e computação em nuvem, classificando itens em tempo real, armazenando o histórico e disponibilizando indicadores de qualidade (incluindo SPC) em um painel acessível remotamente.

**Específicos:**

1. Treinar um classificador de imagens por transferência de aprendizado que distinga fruta fresca de estragada.
2. Capturar e classificar imagens da webcam em tempo real, exibindo o resultado na tela.
3. Enviar cada inspeção para uma API na nuvem de forma confiável (sem perder nem duplicar registros).
4. Armazenar o histórico em banco de dados na nuvem.
5. Exibir taxa de defeito, série temporal e carta de controle (SPC) em um dashboard.
6. Demonstrar a integração entre IoT, Cloud e Indústria 4.0 com um sistema funcional e de custo zero.

## 3. Escopo

- **MVP:** treino e avaliação com dataset público; app de borda com overlay ao vivo e disparo manual; API REST com Postgres; dashboard com visão geral, histórico e carta p; simulador; deploy em free tier.
- **Fase 2:** disparo automático; fila offline com reenvio; heartbeat; fine-tuning com imagens da webcam; MQTT; alertas por Telegram; TFLite.
- **Fora:** hardware dedicado; múltiplos dispositivos reais; autenticação de usuários; treino distribuído/MLOps; detecção com caixas.

## 4. Decisões (na época)

| ID | Decisão | Status |
|---|---|---|
| D-01 | Projeto de IoT separado do projeto de Big Data | DECIDIDO |
| D-02 | Tema: inspeção visual de qualidade com webcam | DECIDIDO |
| D-03 | Dataset: Kaggle "Fruits Fresh and Rotten for Classification" (6 classes) | PROPOSTO |
| D-04 | Transfer learning com MobileNetV2 | PROPOSTO |
| D-05 | Inferência na borda, só o resultado vai para a nuvem | PROPOSTO |
| D-06 | FastAPI + Postgres no Supabase | PROPOSTO |
| D-07 | Streamlit + Plotly | PROPOSTO |
| D-08 | Hospedagem em free tier | PROPOSTO |
| D-09 | 6 classes ou binária | ABERTO |
| D-10 | HTTP ou MQTT | ABERTO |
| D-11 | Disparo manual ou automático | ABERTO |
| D-12 | Como lidar com "nenhuma fruta na imagem" | ABERTO |
| D-13 | TensorFlow/Keras ou PyTorch | ABERTO |
| D-14 | Dashboard via API ou direto do banco | ABERTO |
| D-15 | Definição de "lote" para o SPC (50 inspeções consecutivas) | ABERTO |
| D-16 | Onde hospedar API e dashboard | ABERTO |
| D-17 | Versão do Python | ABERTO |

## 5–9. Arquitetura, stack, modelo, borda e API (resumo da v0)

- **Componentes:** `ml/`, `edge/`, `api/`, `dashboard/`, `scripts/`, `infra/`. Princípios: contrato primeiro, idempotência por `inspection_id`, dependências separadas (sem TensorFlow na API e no dashboard), `source` live/simulated e falha graciosa com fila local.
- **Modelo:** MobileNetV2 com ImageNet, `GlobalAveragePooling2D`, `Dropout(0.2)` e `Dense(softmax)`; fase A com a cabeça e fase B com fine-tuning; métricas por classe e binárias; recall de "estragada" como prioridade; metas de acurácia ≥ 90% e recall ≥ 90%.
- **Riscos identificados:** mudança de domínio dataset × webcam, e o classificador não saber dizer "não há objeto".
- **Borda:** módulos `capture`, `roi`, `inference`, `decision`, `overlay`, `publisher`, `outbox`, `heartbeat`, `config` e `main`; máquina de estados `IDLE → DETECTING → EMIT → WAIT_REMOVAL`; outbox SQLite com backoff.
- **API:** `/api/v1` com `GET /health`, `POST /inspections` (idempotente), `POST /inspections/batch`, `GET /inspections`, `GET /metrics/summary|timeseries|spc`, heartbeat e devices; `X-API-Key` com `compare_digest`; RLS sem políticas públicas; chave de serviço só no servidor.
