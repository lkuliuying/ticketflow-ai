FROM node:24.21.0-bookworm-slim AS build
WORKDIR /app
RUN npm install --global pnpm@11
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# The app's install hooks need source files. Build assets after copying the app.
RUN --mount=type=cache,id=ticketflow-pnpm-store,target=/root/.local/share/pnpm/store,sharing=locked \
    npm pkg delete scripts.preinstall scripts.postinstall scripts.prepare \
    && pnpm install --frozen-lockfile --prefer-offline
COPY . .
RUN pnpm run prebuild
RUN pnpm build

FROM nginx:1.31.5-alpine
COPY --from=build /app/dist /usr/share/nginx/html
