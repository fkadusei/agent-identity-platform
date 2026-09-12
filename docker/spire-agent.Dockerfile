# Build the SPIRE AGENT image used by this demo.
#
# WHY A CUSTOM AGENT IMAGE
# The agent caches JWT-SVIDs per (SPIFFE ID, audience). A cached SVID carries
# the same `jti`, and Keycloak correctly rejects reuse of a client assertion
# ("Token reuse detected") — so the second token exchange in a session would
# fail. A single-use client assertion needs a fresh SVID per request, so we
# patch GetJWTSVID to always miss the cache; every Workload API fetch then
# mints a fresh JWT-SVID (with a fresh jti from the `jti` CredentialComposer).
#
# The patch is a one-line early return; X.509-SVID caching is untouched.
#
# Build context = repo root:
#   docker build -f docker/spire-agent.Dockerfile -t agent-nhi/spire-agent-nocache:demo .
ARG SPIRE_VERSION=1.11.2

FROM golang:1.23 AS build
ARG TARGETARCH
ARG SPIRE_VERSION
RUN git clone --depth 1 --branch v${SPIRE_VERSION} https://github.com/spiffe/spire.git /src
WORKDIR /src
# Insert an early return at the top of JWTSVIDCache.GetJWTSVID.
RUN sed -i '/func (c \*JWTSVIDCache) GetJWTSVID(spiffeID spiffeid.ID/a\        return nil, false // PATCH: JWT-SVID cache disabled (see docker/spire-agent.Dockerfile)' \
        pkg/agent/manager/cache/jwt_cache.go \
 && grep -A1 'func (c \*JWTSVIDCache) GetJWTSVID' pkg/agent/manager/cache/jwt_cache.go
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} \
    go build -trimpath -ldflags="-s -w" -o /out/spire-agent ./cmd/spire-agent

FROM ghcr.io/spiffe/spire-agent:${SPIRE_VERSION}
COPY --from=build /out/spire-agent /opt/spire/bin/spire-agent
