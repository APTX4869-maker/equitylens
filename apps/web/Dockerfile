# EquityLens Web — Next.js 16 前端（开发模式容器；生产 standalone 构建后续硬化）
# 构建：docker compose build web
FROM node:24-alpine

WORKDIR /app
RUN corepack enable

# 依赖层缓存
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
EXPOSE 3000
CMD ["pnpm", "exec", "next", "dev", "-H", "0.0.0.0"]
