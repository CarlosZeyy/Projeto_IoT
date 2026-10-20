# Imagem da qc-api para a VPS (SPEC-015 §4.10, ADR-018). Contexto de build: a raiz do repositório,
# filtrada por infra/docker/api.Dockerfile.dockerignore (§4.11). Nenhum segredo entra na imagem:
# DATABASE_URL e a chave de leitura chegam em tempo de execução pelo env_file do compose (R-03).
# Só o pacote qc-api e as dependências dele são instalados: nada de ML (R-12).

FROM python:3.12.15-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

COPY --from=ghcr.io/astral-sh/uv:0.13.2@sha256:b9fddcde095a7aeafd499024adb8927df6619c7c5672f5ff7126474715f62ba4 /uv /uvx /bin/

ENV UV_PYTHON_DOWNLOADS=0 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/root/.cache/uv \
    PYTHONUNBUFFERED=1 \
    HOME=/home/app

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid 10001 --home-dir /home/app --create-home \
       --shell /usr/sbin/nologin app

WORKDIR /app
COPY . /app

# Instalação como root (código e .venv de dono root, só leitura para o usuário app). Os membros do
# workspace ficam editáveis a partir de /app, o padrão do uv sync. O cache do uv fica no cache
# mount do BuildKit, fora das camadas da imagem: UV_CACHE_DIR aponta para o alvo do mount (sem
# ele, o uv usaria $HOME/.cache/uv, ou seja, /home/app/.cache dentro da camada).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package qc-api --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

LABEL partqc.component="api"

USER 10001:10001

EXPOSE 8000

# Também é o keep-alive do Supabase: /api/v1/health faz SELECT 1 a cada 60 s (ADR-018). Com o
# banco fora do ar, o contêiner fica unhealthy, mas continua rodando.
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=5).status == 200 else 1)"]

CMD ["uvicorn", "qc_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
