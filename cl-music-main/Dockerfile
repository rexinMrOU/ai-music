FROM node:22-slim AS base

ENV NPM_HOME="/npm"
ENV PATH="$NPM_HOME:$PATH"
ENV REACT_APP_API_BASE="https://music-api.ucds.me/api"
RUN corepack enable
COPY . /app
WORKDIR /app

FROM base AS build
RUN --mount=type=cache,id=npm,target=/npm/store  npm i --frozen-lockfile
RUN npm run build

# Production stage
FROM nginx:alpine-slim AS production-stage
COPY ./conf/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]