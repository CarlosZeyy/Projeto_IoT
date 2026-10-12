# PartQC — Inspeção visual de qualidade com celular, borda e nuvem

Projeto acadêmico da disciplina **Aplicações de Cloud, IoT e Indústria 4.0 (Python)**.

O operador fotografa uma peça (parafuso ou porca) com o **celular**. O **notebook**, atuando como gateway de borda, classifica o tipo e o **grau de estado**:

| Código | Grau |
|---|---|
| `perfect` | perfeito |
| `good` | bom |
| `fair` | mediano |
| `poor` | ruim |
| `unusable` | inutilizável |

A **nuvem** guarda o histórico e mostra indicadores e uma **carta de controle p (SPC)** por lote.

```text
Celular (câmera, navegador) ──HTTP/LAN──► Notebook (FastAPI + ONNX Runtime + outbox SQLite)
                                                        │ HTTPS (só resultados, nunca imagens)
                                                        ▼
                                  API FastAPI (Render) ─► Postgres (Supabase) ◄─ Dashboard (Streamlit)
```

- **Custo:** R$ 0 (free tiers e software livre)
- **Stack:** Python 3.12 · uv · FastAPI · Pydantic v2 · PyTorch/timm → ONNX · onnxruntime · Supabase Postgres · Streamlit + Plotly

## Status

🚧 Fase de fundação: documentação concluída; implementação começa pela [SPEC-001](docs/specs/SPEC-001-setup-repositorio.md). Acompanhe em [docs/plan.md](docs/plan.md).

## Documentação

- [Índice](docs/README.md)
- [PRD](docs/PRD.md)
- [Arquitetura](docs/architecture.md)
- [Regras](docs/rules.md)
- [Plano](docs/plan.md)
- [Protocolo de dataset](docs/dataset-protocol.md)
- [Deploy](docs/deployment-plan.md)
- [ADRs](docs/adr/)
- [SPECs](docs/specs/)

## Como o desenvolvimento funciona

Cada entrega é uma SPEC, implementada por um loop de agentes com papéis separados: autor → tester → reviewer → (segurança). Depois, um PR com merge humano. Detalhes em [reviews/README.md](reviews/README.md) e em [CLAUDE.md](CLAUDE.md).

## Como rodar

Esta seção será preenchida conforme as SPECs forem concluídas (SPEC-001: ambiente; SPEC-007: borda; SPEC-015: deploy).
