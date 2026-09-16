# Build the SPIRE server image used by this demo.
#
# Stage 1 compiles the `jti` CredentialComposer plugin (see spire-plugin/main.go
# for why it exists). Stage 2 drops the static binary into the stock SPIRE
# server image; k8s/spire/spire-server.yaml then points server.conf at it via
# plugin_cmd.
#
# go.mod/go.sum are committed, so the build is deterministic (no `go mod tidy`).
# Build context = repo root:
#   docker build -f docker/spire-server.Dockerfile -t agent-nhi/spire-server-jti:demo .
ARG SPIRE_VERSION=1.12.4

FROM golang:1.25 AS build
ARG TARGETARCH
WORKDIR /src
COPY spire-plugin/go.mod spire-plugin/go.sum ./
RUN go mod download
COPY spire-plugin/main.go ./
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} \
    go build -trimpath -ldflags="-s -w" -o /out/jti-plugin .

FROM ghcr.io/spiffe/spire-server:${SPIRE_VERSION}
COPY --from=build /out/jti-plugin /opt/spire/plugins/jti-plugin
