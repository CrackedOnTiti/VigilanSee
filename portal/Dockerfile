FROM docker.io/library/node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM docker.io/library/nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
