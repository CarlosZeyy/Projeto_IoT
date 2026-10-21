# Glossário

| Termo | Significado no projeto |
|---|---|
| **ADR** | Architecture Decision Record. Registro curto de uma decisão (contexto, decisão, consequências). Fica em `docs/adr/` |
| **Borda / edge / gateway** | O notebook que recebe as fotos do celular, roda o modelo e envia os resultados à nuvem |
| **Carta p** | Gráfico de controle da proporção de itens defeituosos por subgrupo (lote), com linha central p̄ e limites de ±3σ |
| **Caddy** | Servidor web usado como proxy reverso na VPS: obtém o certificado HTTPS (Let's Encrypt) e encaminha `/api/*` para a API e o resto para o dashboard (ADR-018) |
| **Cold start** | Demora da primeira requisição depois que um serviço free tier "dormiu". Desde o ADR-018, só acontece na reserva da API no Render |
| **Docker Compose** | Ferramenta que sobe vários contêineres descritos num arquivo (`infra/compose.yaml`): Caddy, API e dashboard na VPS |
| **Contrato** | Schemas Pydantic do pacote `qc-contracts` que borda, API e dashboard compartilham |
| **CORN / CORAL** | Técnicas de regressão ordinal para redes neurais (respeitam a ordem dos graus) |
| **Defeituoso** | Inspeção com grau `poor` ou `unusable` (ADR-013) |
| **Grau** | Estado da peça em 5 níveis: perfeito, bom, mediano, ruim, inutilizável |
| **Idempotência** | Enviar a mesma inspeção várias vezes produz um único registro |
| **Imagem externa** | Imagem de um dataset público ou da internet, com licença aceita e fonte registrada em `ml/external_sources.csv`. Tem `item_id` `X<tipo>-NNNN` e vai só para o treino (ADR-020) |
| **Importação** | Entrada no dataset de um arquivo que não veio da página `/capture` (foto de conhecido ou imagem externa), por `python -m qc_edge.importer` (SPEC-036) |
| **`item_id`** | Identificador da **peça física** (ex.: `S-012`). Várias fotos podem ter o mesmo `item_id`. Nas imagens externas, `XS-0001` etc. (ADR-020) |
| **Origem da imagem** | `capture` (página `/capture`), `contributor` (foto de conhecido) ou `external` (imagem externa). Fica em `DATASET_DIR/sources.csv`; a imagem sem linha nele é `capture` (SPEC-035) |
| **Lote (`lot_id`)** | Grupo de peças inspecionadas juntas, informado pelo operador. É o subgrupo do SPC |
| **Loop** | Ciclo developer → tester → reviewer (→ security) de uma SPEC, com no máximo 3 rodadas |
| **Manifest** | CSV que lista cada imagem do dataset com seus rótulos |
| **`needs_review`** | Sinalização de que o modelo ficou em dúvida e um humano deveria conferir |
| **ONNX / onnxruntime** | Formato portátil de modelo e o motor leve que executa esse formato na CPU |
| **Orquestrador** | A sessão principal do Claude Code, que conduz o loop chamando os subagentes |
| **Outbox** | Fila local (SQLite) onde cada inspeção é gravada antes do envio; garante que nada se perca |
| **Paridade** | Teste que garante que o modelo exportado em ONNX produz as mesmas saídas do modelo PyTorch |
| **QWK** | Quadratic Weighted Kappa. Concordância entre duas classificações ordinais, penalizando mais os erros distantes |
| **Rodada (r1, r2, r3)** | Cada passagem de uma SPEC pelo loop |
| **RLS** | Row Level Security do Postgres. Ligado sem políticas, impede o acesso pelas chaves públicas do Supabase |
| **SPC** | Statistical Process Control (controle estatístico de processo) |
| **SPEC** | Especificação de uma entrega, com critérios de aceite testáveis. Fica em `docs/specs/` |
| **Split agrupado** | Divisão treino/validação/teste em que todas as fotos de uma mesma peça ficam no mesmo conjunto |
| **VPS** | Servidor virtual privado. No projeto, a máquina pessoal do humano, que já existia e hospeda outros projetos dele, onde rodam a API e o dashboard (ADR-018) |
| **`unknown` / `other`** | `other` é a classe do modelo para "não é parafuso nem porca"; `unknown` é como isso (ou a confiança baixa) aparece no contrato |
