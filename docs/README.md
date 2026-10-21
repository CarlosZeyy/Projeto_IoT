# Documentação — índice

Leia nesta ordem na primeira vez. Os agentes devem ler pelo menos os itens 1 a 3 antes de qualquer tarefa.

| # | Documento | Conteúdo | Quem mantém |
|---|---|---|---|
| 1 | [rules.md](rules.md) | Regras inegociáveis e negociáveis, convenções | Humano (mudança via ADR) |
| 2 | [PRD.md](PRD.md) | Problema, personas, escopo em camadas, requisitos, métricas de sucesso | architect |
| 3 | [architecture.md](architecture.md) | Componentes, contrato v0, API, banco, borda, artefatos do modelo, rede | architect |
| 4 | [plan.md](plan.md) | Cronograma semanal e quadro de SPECs | orquestrador |
| 5 | [dataset-protocol.md](dataset-protocol.md) | Rubrica dos 5 graus, corrosão, captura, manifest, split, fotos de conhecidos e imagens externas (§10) | Dupla (alterações via architect) |
| 6 | [deployment-plan.md](deployment-plan.md) | VPS (Docker Compose + Caddy), Supabase e reserva no Render: serviços, limites, segredos, publicação, atualização, checklist da demo | security-devops |
| 7 | [adr/](adr/) | Decisões de arquitetura (ADR-001…020) | architect |
| 8 | [specs/](specs/) | Especificações de entrega (SPEC-001…036) | architect |
| 9 | [glossary.md](glossary.md) | Termos | architect |
| 10 | [professor-questions.md](professor-questions.md) | Pendências de validação externa | Dupla |
| — | [archive/ideia-original.md](archive/ideia-original.md) | Especificação v0 (frutas + webcam), só como histórico | — |

Processo de entrega (loop de agentes): [../reviews/README.md](../reviews/README.md) · Checklist do reviewer: [../reviews/checklist.md](../reviews/checklist.md)

## Hierarquia de autoridade

Em caso de conflito, vale o primeiro da lista:

1. `rules.md`
2. ADR aceito mais recente
3. `architecture.md`
4. SPEC
5. Demais documentos

Todo conflito encontrado deve ser reportado; não escolha em silêncio.
