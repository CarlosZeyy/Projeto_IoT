# Imagem do Caddy do PartQC (SPEC-039 §4.3, ADR-023): a oficial, fixada por tag e digest, com o
# infra/Caddyfile embutido (sem bind nem "Preserve repository" no Coolify). Contexto de build: a
# raiz do repositório, filtrada por infra/docker/caddy.Dockerfile.dockerignore, que só deixa
# entrar o Caddyfile. Usuário, portas, entrypoint e comando são os da imagem oficial
# (caddy run --config /etc/caddy/Caddyfile --adapter caddyfile). Sem healthcheck (ADR-023).
# Atualizar a versão: docs/deployment-plan.md §2, linha "Imagens base".

FROM caddy:2.11.7@sha256:685ae3d7c34d9b5f8caeddc5d14051db7bbd88ff1f5a2fa0c16bd8ca328fb7af

COPY infra/Caddyfile /etc/caddy/Caddyfile

# Para o "docker image prune -f --filter label=partqc.component" da atualização.
LABEL partqc.component="caddy"
