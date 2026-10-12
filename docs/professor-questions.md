# Perguntas para o professor

Enviar na S1. Registrar a resposta e a data. Se uma resposta mudar uma decisão, abra ou atualize o ADR indicado.

| # | Pergunta | Por que importa | Padrão se não houver resposta | ADR afetado | Resposta (data) |
|---|---|---|---|---|---|
| 1 | O transporte borda → nuvem por **HTTP/REST** é suficiente, ou a disciplina espera **MQTT**? | MQTT costuma pesar em matéria de IoT; os brokers gratuitos estão limitados | HTTP no MVP; MQTT só na Fase 3, com Mosquitto local | ADR-009 | |
| 2 | É aceitável uma página **HTML/JS mínima** (até cerca de 200 linhas de JS, sem framework) para a câmera do celular, com todo o resto em Python? | O navegador só acessa a câmera via HTML/JS | Sim; o JS fica isolado em `edge/src/qc_edge/static/` | ADR-003, ADR-007 | |
| 3 | Um **dataset próprio** (parafusos e porcas fotografados pela dupla, com corrosão induzida) é aceito, no lugar de um dataset público? | Define o esforço de coleta | Sim; documentado em `dataset-protocol.md` | ADR-001 | |
| 4 | É permitido usar **agentes de IA (Claude Code)** no desenvolvimento, desde que documentado e revisado pela dupla? | Integridade acadêmica | **Condição para iniciar o código (SPEC-001):** obter a resposta **ou** a dupla decidir explicitamente seguir, declarando o uso de IA no relatório conforme a política da instituição. Registrar a decisão nesta tabela | ADR-011 | **Autorizado** previamente pelo professor (registrado em 2026-10-12): uso de agentes de IA e ML no desenvolvimento, seguindo práticas atuais como o **SDD (Spec-Driven Development)**, para mostrar como a IA está sendo usada no desenvolvimento de software. O uso será descrito no relatório. |
| 5 | Qual o **formato da entrega**: relatório (modelo ABNT?), slides, vídeo, repositório, demo ao vivo? | Planejamento da S7–S8 | Relatório + slides + demo ao vivo + vídeo de backup | — | **Parcial (2026-10-12):** o projeto deve ser levado **completo** à faculdade; o desenvolvimento e os testes rodam em casa. Formato do relatório e dos slides ainda a confirmar. |
| 6 | O escopo em camadas (parafusos/porcas no MVP; ferramentas depois) atende à expectativa? | Validação do escopo | Sim | ADR-001 | |
| 7 | É necessário que o repositório seja **público** para a avaliação? | Acesso do professor ao código | — | ADR-015 | **Resolvido (2026-10-12):** o repositório é público por decisão da dupla; basta enviar o link |
