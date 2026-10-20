# Imagem do qc-dashboard para a VPS (SPEC-015 §4.3, §4.10, ADR-018). Contexto de build: a raiz do
# repositório, filtrada por infra/docker/dashboard.Dockerfile.dockerignore (§4.11). A chave de
# leitura chega em tempo de execução pelo env_file do compose (R-03), e API_BASE_URL vem do
# próprio compose. Só o pacote qc-dashboard e as dependências dele: sem ML (R-12) e sem driver
# de banco (ADR-007).

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

# Instalação editável (o padrão do uv sync): qc_dashboard.config.REPO_ROOT é /app, e a página
# "Sobre o modelo" acha ml/models/<versão>/metrics.json e ml/reports/ dentro da imagem (RV-06
# da SPEC-013). O cache do uv fica no cache mount do BuildKit, fora das camadas da imagem:
# UV_CACHE_DIR aponta para o alvo do mount (sem ele, o uv usaria $HOME/.cache/uv, ou seja,
# /home/app/.cache dentro da camada).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package qc-dashboard --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

LABEL partqc.component="dashboard"

USER 10001:10001

EXPOSE 8501

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=5).status == 200 else 1)"]

# Roda a partir de /app (WORKDIR), para o Streamlit ler /app/.streamlit/config.toml (§4.4).
CMD ["streamlit", "run", "dashboard/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.fileWatcherType=none"]
