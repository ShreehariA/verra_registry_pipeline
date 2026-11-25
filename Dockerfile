# One image for the pipeline job and the dashboard. No data inside: both read a mounted folder.
# How to run it: docs/sop.md, section 8.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never

# uid 1000 matches the mount options in deploy/main.tf, so the job can write to the bucket.
RUN useradd --uid 1000 --create-home verra
WORKDIR /app
# The locked dependencies first, in their own layer, so a code change doesn't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md pipeline.toml ./
COPY .streamlit .streamlit
COPY src src
COPY sql sql
COPY dashboard dashboard
RUN uv sync --frozen --no-dev

USER verra
ENV PATH="/app/.venv/bin:$PATH" VERRA_LAKE=/data/lake PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "exec streamlit run dashboard/app.py --server.port=$PORT --server.address=0.0.0.0"]
