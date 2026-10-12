# ADR-003: Capturar a foto com `<input capture>` sobre HTTP na LAN; vídeo ao vivo fica para a Fase 3

| Campo | Valor |
|---|---|
| Status | Aceito |
| Data | 2026-10-12 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-002, ADR-007, SPEC-007, SPEC-010, SPEC-019, R-02, R-14, N-09 |

## Contexto

O celular é o sensor (ADR-002), e o navegador só acessa a câmera por HTML/JS. A borda serve a página `/capture` em `http://<ip-lan>:8000`, sem certificado.

Fatos externos:

- `navigator.mediaDevices.getUserMedia()` só existe em **contexto seguro** (HTTPS ou `localhost`). Um IP da LAN via HTTP não é contexto seguro. Fonte: <https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia> (verificado em 2026-10-12).
- O atributo HTML `capture` tem **disponibilidade limitada** entre navegadores. Fonte: <https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Attributes/capture> (verificado em 2026-10-12). No Android, o navegador pode mostrar um seletor de apps (câmera ou galeria) em vez de abrir a câmera direto.

A dupla quer manter o JavaScript mínimo (pergunta 2 de `docs/professor-questions.md`).

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) `<input type="file" accept="image/*" capture="environment">` sobre HTTP, com redimensionamento no JS | Funciona sem HTTPS; usa a câmera nativa (foco e exposição bons); pouco JS; foto por disparo combina com a inspeção peça a peça | Comportamento varia por navegador; não há pré-visualização ao vivo; um toque a mais por foto |
| B `getUserMedia` com vídeo ao vivo, servido por HTTPS (certificado local `mkcert`; túnel público descartado pela R-02) | Pré-visualização e disparo contínuo | Exige HTTPS: instalar a CA do `mkcert` nos dois celulares, ou depender do túnel, que leva o tráfego para fora da LAN; mais JS |
| C Apps de câmera IP (IP Webcam, DroidCam) | Stream pronto, sem escrever JS | Só Android; apps de terceiros; outro protocolo a integrar; não roda nos dois celulares da dupla |

## Decisão

No MVP, a captura usa `<input type="file" accept="image/*" capture="environment">` na página `/capture`, servida por HTTP na LAN. Antes do envio, o JS redimensiona a foto para no máximo 1280 px no lado maior e a reencoda em JPEG (q = 0,9) via `<canvas>`, o que também corrige a orientação EXIF. O vídeo ao vivo (`getUserMedia` + HTTPS) fica para a Fase 3 (SPEC-019).

## Consequências

- **Positivas:**
  - nenhum certificado nem túnel no caminho principal;
  - o upload fica pequeno (estimativa: algumas centenas de KB, a medir na SPEC-007), o que ajuda a cumprir RNF-03;
  - a reencodagem descarta os metadados EXIF, incluindo GPS (R-14).
- **Negativas / custos aceitos:**
  - pode exigir um toque extra no seletor do Android;
  - sem pré-visualização, o enquadramento depende da marcação de posição na mesa (`docs/dataset-protocol.md` §3).
- **O que passa a ser obrigatório:**
  - **na S1**, testar a página nos **dois** celulares da dupla e registrar o navegador, a versão e o comportamento observado (câmera direta ou seletor);
  - o JS fica isolado em `edge/src/qc_edge/static/` (SPEC-007);
  - a borda valida o tipo da imagem pelo conteúdo (Pillow), não pela extensão, e aceita no máximo 10 MB;
  - o mesmo fluxo de captura serve aos modos `inspect` e `collect` (SPEC-010).

## Quando revisitar

- Se, no teste da S1, algum dos dois celulares não conseguir abrir a câmera traseira pelo `<input capture>`, nem mesmo pelo seletor.
- Se o professor exigir vídeo ao vivo ou recusar o HTML/JS (pergunta 2).
- Se a Fase 3 for liberada (Fase 2 fechada até 22/11): a SPEC-019 implementa a opção B sem remover a A.
