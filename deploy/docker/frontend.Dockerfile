FROM oven/bun:1.4.2 AS build
WORKDIR /app
COPY package.json bun.lock tsconfig.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src
COPY tests ./tests
RUN bun install --frozen-lockfile && bun run test && bun run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 9898
