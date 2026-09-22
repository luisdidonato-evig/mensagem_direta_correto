FROM node:24-alpine AS build
WORKDIR /app
ARG VITE_API_URL=/api/v1
ARG VITE_AUTH_ENABLED=true
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_AUTH_ENABLED=$VITE_AUTH_ENABLED
COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile=false
COPY . .
RUN pnpm build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
