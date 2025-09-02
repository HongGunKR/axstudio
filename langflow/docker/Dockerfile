# -------- Stage 1: Frontend build (npm) --------
FROM node:20-bookworm AS fe
WORKDIR /fe

# Node 메모리 상향(대규모 번들 대비)
ENV NODE_OPTIONS=--max-old-space-size=4096

# lock이 있으면 ci, 없으면 install
COPY src/frontend/package*.json ./src/frontend/
RUN if [ -f src/frontend/package-lock.json ]; then \
      npm -C src/frontend ci; \
    else \
      npm -C src/frontend install; \
    fi

# 소스 복사 및 빌드
COPY src/frontend ./src/frontend
ARG VITE_API_URL=/api
ENV VITE_API_URL=${VITE_API_URL}
RUN npm -C src/frontend run build

# 빌드 산출물 표준화: dist / build / .next 모두 케이스 처리
RUN set -eux; \
    OUT=/fe/build_out; mkdir -p "$OUT"; \
    if [ -d src/frontend/dist ]; then \
        cp -a src/frontend/dist/. "$OUT/"; \
    elif [ -d src/frontend/build ]; then \
        cp -a src/frontend/build/. "$OUT/"; \
    elif [ -d src/frontend/.next ]; then \
        # Next.js일 경우: 정적 자산만 복사(필요시 커스터마이즈)
        cp -a src/frontend/.next/static "$OUT/"; \
    else \
        echo "❌ No frontend build output found"; \
        ls -al src/frontend; \
        exit 1; \
    fi

# -------- Stage 2: Backend (Python) --------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS backend
ENV TZ=UTC
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ make git curl \
    python3-dev libffi-dev libssl-dev cargo \
    && rm -rf /var/lib/apt/lists/*

# 소스 복사
COPY . /app

# ↓ AstraDB Graph 컴포넌트 제거
RUN rm -f /app/src/backend/base/langflow/components/vectorstores/astradb_graph.py || true

# Langflow를 소스에서 설치(+ uvicorn 등 서버 런타임 의존성 같이)
# (루트/베이스 uv.lock 또는 pyproject가 없으면 --mount 바인딩은 실패하니, 단순 sync로 두는 편이 안전)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra postgresql

# 🔴 Langflow가 기대하는 경로로 프런트 정적 파일 복사
#   로그에 나온 것처럼 현재 버전은 /app/src/backend/base/langflow/frontend 를 확인합니다.
COPY --from=fe /fe/build_out/ /app/src/backend/base/langflow/frontend/

EXPOSE 7860
CMD ["uv", "run", "langflow", "run", "--host", "0.0.0.0", "--port", "7860"]