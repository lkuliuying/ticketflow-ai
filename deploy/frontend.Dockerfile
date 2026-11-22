FROM node:24.21.0-bookworm-slim AS build
WORKDIR /app
RUN npm install --global pnpm@11
COPY . .
RUN pnpm install --frozen-lockfile
RUN pnpm run prebuild
RUN pnpm build

FROM nginx:1.31.5-alpine
COPY --from=build /app/dist /usr/share/nginx/html
