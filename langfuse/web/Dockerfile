# ─────────────────────────────────────────────────────────────────────────────
# Stage 0) Node 20 Alpine (보안패치)
# ─────────────────────────────────────────────────────────────────────────────
FROM --platform=${TARGETPLATFORM:-linux/amd64} node:20-alpine AS alpine
RUN apk update && apk upgrade --no-cache libcrypto3 libssl3 libc6-compat busybox ssl_client

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1) Base: pnpm/turbo 툴 체인
# ─────────────────────────────────────────────────────────────────────────────
FROM --platform=${TARGETPLATFORM:-linux/amd64} alpine AS base
RUN npm install turbo@^2.5.6 --global
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable && corepack prepare pnpm@9.5.0 --activate

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2) Pruner: web 서브워크스페이스만 추출
# ─────────────────────────────────────────────────────────────────────────────
FROM --platform=${TARGETPLATFORM:-linux/amd64} base AS pruner
WORKDIR /app
COPY . .
RUN turbo prune --scope=web --docker

# ─────────────────────────────────────────────────────────────────────────────
# Stage 3) Builder: **메모리 절약 빌드**
#  - turbo 그래프 빌드 대신: 공유패키지(있으면) 선빌드 → web만 빌드
#  - 힙 상한 2560MB, SWC 스레드 1, 소스맵/텔레메트리 비활성
# ─────────────────────────────────────────────────────────────────────────────
FROM --platform=${TARGETPLATFORM:-linux/amd64} base AS builder

WORKDIR /app

# (1) 의존성 설치 (prune 결과물 기반)
COPY --from=pruner /app/out/pnpm-lock.yaml ./pnpm-lock.yaml
COPY --from=pruner /app/out/pnpm-workspace.yaml ./pnpm-workspace.yaml
COPY --from=pruner /app/out/json/ .
RUN pnpm fetch && pnpm install --frozen-lockfile

# (2) 빌드 환경 변수: 메모리/스레드/소스맵/텔레메트리 최소화
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    TURBO_TELEMETRY_DISABLED=1 \
    SENTRY_SOURCEMAPS_DISABLE=1 \
    RAYON_NUM_THREADS=1 \
    NODE_OPTIONS="--max-old-space-size=2560" \
    DOCKER_BUILD=1 \
    NEXT_MANUAL_SIG_HANDLE=true \
    CI=true

# (3) 공개 빌드 변수를 필요 시 주입
ARG NEXT_PUBLIC_PLAIN_APP_ID
ARG NEXT_PUBLIC_LANGFUSE_CLOUD_REGION
ENV NEXT_PUBLIC_LANGFUSE_CLOUD_REGION=$NEXT_PUBLIC_LANGFUSE_CLOUD_REGION
ARG NEXT_PUBLIC_DEMO_ORG_ID
ENV NEXT_PUBLIC_DEMO_ORG_ID=$NEXT_PUBLIC_DEMO_ORG_ID
ARG NEXT_PUBLIC_DEMO_PROJECT_ID
ENV NEXT_PUBLIC_DEMO_PROJECT_ID=$NEXT_PUBLIC_DEMO_PROJECT_ID
ARG NEXT_PUBLIC_SIGN_UP_DISABLED
ENV NEXT_PUBLIC_SIGN_UP_DISABLED=$NEXT_PUBLIC_SIGN_UP_DISABLED
ARG NEXT_PUBLIC_TURNSTILE_SITE_KEY
ENV NEXT_PUBLIC_TURNSTILE_SITE_KEY=$NEXT_PUBLIC_TURNSTILE_SITE_KEY
ARG NEXT_PUBLIC_POSTHOG_KEY
ENV NEXT_PUBLIC_POSTHOG_KEY=$NEXT_PUBLIC_POSTHOG_KEY
ARG NEXT_PUBLIC_POSTHOG_HOST
ENV NEXT_PUBLIC_POSTHOG_HOST=$NEXT_PUBLIC_POSTHOG_HOST
ARG NEXT_PUBLIC_LANGFUSE_TRACING_SAMPLE_RATE
ENV NEXT_PUBLIC_LANGFUSE_TRACING_SAMPLE_RATE=$NEXT_PUBLIC_LANGFUSE_TRACING_SAMPLE_RATE
ARG NEXT_PUBLIC_SENTRY_ENVIRONMENT
ENV NEXT_PUBLIC_SENTRY_ENVIRONMENT=$NEXT_PUBLIC_SENTRY_ENVIRONMENT
ARG NEXT_PUBLIC_SENTRY_DSN
ENV NEXT_PUBLIC_SENTRY_DSN=$NEXT_PUBLIC_SENTRY_DSN
ARG NEXT_PUBLIC_BASE_PATH
ENV NEXT_PUBLIC_BASE_PATH=$NEXT_PUBLIC_BASE_PATH
ARG NEXT_PUBLIC_BUILD_ID
ENV NEXT_PUBLIC_BUILD_ID=$NEXT_PUBLIC_BUILD_ID
ENV SENTRY_RELEASE=$NEXT_PUBLIC_BUILD_ID

# (4) Sentry 토큰류 (사용 안 하면 비워둠)
ARG SENTRY_AUTH_TOKEN
ENV SENTRY_AUTH_TOKEN=$SENTRY_AUTH_TOKEN
ARG SENTRY_ORG
ENV SENTRY_ORG=$SENTRY_ORG
ARG SENTRY_PROJECT
ENV SENTRY_PROJECT=$SENTRY_PROJECT

# (5) pruned 소스 복사 (web 및 의존 서브패키지 포함)
COPY --from=pruner /app/out/full/ .

# (6) self-host용 미들웨어 제거(존재 시)
RUN rm -f ./web/src/middleware.ts || true

# (7) **공유 패키지 선(先)빌드**: TS → dist (있을 때만)
#     - packages/shared 가 존재하면 그 안에서 build 스크립트를 실행
RUN if [ -d "/app/packages/shared" ]; then \
      echo "Building packages/shared ..."; \
      cd /app/packages/shared && pnpm run -s build || true; \
    else \
      echo "No packages/shared; skipping"; \
    fi

# (8) **web만 단독 빌드** (turbo 미사용 → 메모리 피크 최소화)
WORKDIR /app/web
RUN pnpm run -s build

# ─────────────────────────────────────────────────────────────────────────────
# Stage 4) Runner: Next.js standalone 런타임
# ─────────────────────────────────────────────────────────────────────────────
FROM --platform=${TARGETPLATFORM:-linux/amd64} base AS runner

ARG TARGETPLATFORM
ARG BUILDPLATFORM

WORKDIR /app

ARG NEXT_PUBLIC_BUILD_ID
ENV BUILD_ID=$NEXT_PUBLIC_BUILD_ID
ARG NEXT_PUBLIC_LANGFUSE_CLOUD_REGION
ENV NEXT_PUBLIC_LANGFUSE_CLOUD_REGION=$NEXT_PUBLIC_LANGFUSE_CLOUD_REGION

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    DOCKER_BUILD=0 \
    NEXT_MANUAL_SIG_HANDLE=true

RUN apk add --no-cache dumb-init tzdata

# 비루트 사용자
ARG UID=1001
ARG GID=1001
RUN addgroup --system --gid ${GID} nodejs \
 && adduser --system --uid ${UID} nextjs

# 런타임 도구 (prisma, 선택적 dd-trace)
RUN npm install -g --no-package-lock --no-save prisma@6.3.0
ARG NEXT_PUBLIC_LANGFUSE_CLOUD_REGION
RUN if [ -n "$NEXT_PUBLIC_LANGFUSE_CLOUD_REGION" ]; then \
        npm install --no-package-lock --no-save dd-trace@5.36.0; \
    fi

# golang-migrate 바이너리
RUN MIGRATE_TARGET_ARCH=$(echo ${TARGETPLATFORM:-linux/amd64} | sed 's/\//-/g') && \
    wget -q -O- https://github.com/golang-migrate/migrate/releases/download/v4.18.3/migrate.$MIGRATE_TARGET_ARCH.tar.gz | tar xvz && \
    mv migrate /usr/bin/migrate

# next standalone + 정적파일 + public
COPY --from=builder --chown=nextjs:nodejs /app/web/next.config.mjs .
COPY --from=builder --chown=nextjs:nodejs /app/web/package.json .
COPY --from=builder --chown=nextjs:nodejs /app/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/web/.next/static ./web/.next/static
COPY --from=builder --chown=nextjs:nodejs /app/web/public ./web/public

# shared의 prisma/clickhouse 산출물 필요 시 포함
COPY --from=builder --chown=nextjs:nodejs /app/packages/shared/prisma ./packages/shared/prisma
COPY --from=builder --chown=nextjs:nodejs /app/packages/shared/clickhouse ./packages/shared/clickhouse

# 엔트리포인트/스크립트
COPY --chown=nextjs:nodejs ./web/entrypoint.sh ./web/entrypoint.sh
COPY --chown=nextjs:nodejs ./packages/shared/scripts/cleanup.sql ./packages/shared/scripts/cleanup.sql
RUN chmod +x ./web/entrypoint.sh

USER nextjs
ENV PORT 3000

ENTRYPOINT ["dumb-init", "--", "./web/entrypoint.sh"]
CMD if [ -n "$NEXT_PUBLIC_LANGFUSE_CLOUD_REGION" ]; then \
      node --import dd-trace/initialize.mjs ./web/server.js --keepAliveTimeout 110000; \
    else \
      node ./web/server.js --keepAliveTimeout 110000; \
    fi
