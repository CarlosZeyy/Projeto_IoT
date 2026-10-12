# ADR-002: Usar arquitetura em 3 camadas: celular (sensor) → notebook (borda) → nuvem

| Campo | Valor |
|---|---|
| Status | Aceito |
| Data | 2026-10-12 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-003, ADR-004, ADR-006, ADR-008, ADR-009, SPEC-007, SPEC-008, SPEC-009, R-01, R-02, R-05, R-14 |

## Contexto

A matéria cobre IoT, Cloud e Indústria 4.0, e o avaliador espera ver um dispositivo, um processamento na borda e um serviço remoto. As restrições são:

- custo R$ 0 (R-01);
- imagens não saem da LAN (R-02, R-14);
- inferência em até 300 ms (p95) e resposta ao celular em até 3 s (RNF-02, RNF-03);
- a nuvem free tier dorme e pode estar fora do ar (ADR-008).

A v0 usava a webcam do notebook. Com o domínio de parafusos e porcas (ADR-001), a câmera do celular é melhor: tem foco de perto e pode ser posicionada sobre a peça.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) Celular como sensor → notebook como gateway de borda (inferência, outbox, fotos locais) → nuvem (API + Postgres + dashboard) | Mostra as 3 camadas de IoT; inferência local com baixa latência e sem custo; imagens ficam na LAN; outbox absorve queda e cold start da nuvem | Exige rede local que deixe o celular alcançar o notebook; o notebook precisa estar ligado na demo |
| B Inferência na nuvem (celular envia a foto direto para a API) | Borda mais simples | Imagens saem da LAN (viola R-02); o free tier tem pouca memória para o modelo e o onnxruntime (Koyeb: 512 MB; Render: não informado, estimado em cerca de 512 MB sem confirmação, ADR-008); cold start de cerca de 1 min trava cada inspeção |
| C Inferência no navegador do celular (ONNX Runtime Web) | Sem gateway; funciona offline no próprio celular | Muito mais JavaScript (contra o foco em Python); pré-processamento duplicado em JS, com risco de divergir do treino; o celular passa a falar direto com a nuvem e perde-se a camada de borda |
| D Só webcam no notebook (v0) | Menos peças móveis | Sem dispositivo separado (IoT fraco); câmera ruim para peças pequenas; difícil posicionar |

## Decisão

O sistema tem três camadas:

- o **celular** apenas captura e mostra o resultado;
- o **notebook** (`qc-edge`) recebe a foto pela LAN, pré-processa com `qc-preprocess`, roda o ONNX, decide, salva a foto no disco local e grava o resultado num outbox SQLite antes de responder;
- a **nuvem** (`qc-api` + Supabase + `qc-dashboard`) recebe só o JSON do contrato e serve histórico, métricas e SPC.

## Consequências

- **Positivas:**
  - privacidade por construção: nenhum endpoint da nuvem aceita imagem;
  - a borda funciona sem internet (RF-07);
  - a latência depende só da LAN e da CPU do notebook.
- **Negativas / custos aceitos:**
  - dependência da rede do campus, mitigada pelos planos B (hotspot do celular) e C (ancoragem USB) de `docs/architecture.md` §8;
  - mais um processo para operar no dia da demo.
- **O que passa a ser obrigatório:**
  - nenhum endpoint de `qc-api` aceita imagem nem multipart (R-02); o security-devops revisa o tráfego da borda;
  - o outbox grava antes de responder ao celular, e o reenvio é idempotente por `inspection_id` (R-05, SPEC-009);
  - o pré-processamento da borda é o mesmo pacote usado no treino (`qc-preprocess`, SPEC-002);
  - o teste de rede com os dois celulares (Wi-Fi e hotspot) é feito em casa, e a apresentação usa por padrão o hotspot do celular (`docs/architecture.md` §8).

## Quando revisitar

- Se o teste de rede da S1 mostrar que nem o plano B nem o plano C funcionam no local da apresentação.
- Se a latência na CPU do notebook passar de 300 ms (p95) com o backbone escolhido (RNF-02).
- Se o professor exigir que a inferência rode em hardware embarcado.
