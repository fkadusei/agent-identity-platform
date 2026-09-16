# Build the Keycloak image used by this demo.
#
# WHY A CUSTOM IMAGE
# The stock image is built for development defaults. Running it with `start`
# re-augments the Quarkus application *at startup* into
# /opt/keycloak/lib/quarkus — which is why Keycloak was the one container that
# could not have a read-only root filesystem, and why that exception sat in
# .trivyignore.yaml.
#
# `kc.sh build` bakes that augmentation into the image instead, so the runtime
# never writes to /opt/keycloak at all: the container runs with `--optimized`
# and readOnlyRootFilesystem: true, and the exception is gone (S4).
#
# The build-time options must match what the runtime sets, or `--optimized`
# refuses to start. They mirror deploy/kind/manifests/keycloak/keycloak-env.yaml:
# Postgres, HTTP listener with TLS terminated in front, health endpoints, and the
# `ispn` cache discovering peers through the database.
#
# Build context = repo root:
#   docker build -f docker/keycloak.Dockerfile -t agent-platform/keycloak:demo .
ARG KEYCLOAK_VERSION=26.6.4

FROM quay.io/keycloak/keycloak:${KEYCLOAK_VERSION} AS build

ENV KC_DB=postgres
ENV KC_HEALTH_ENABLED=true
ENV KC_HTTP_ENABLED=true
ENV KC_CACHE_STACK=jdbc-ping

RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:${KEYCLOAK_VERSION}

# Stamp the revision, so scripts/check-images.sh can tell whether the running
# pod is the build you just made (same contract as the app images).
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}

COPY --from=build /opt/keycloak/ /opt/keycloak/

# Run as the image's non-root `keycloak` user by default. The base image declares
# no USER, which Trivy flags (DS-0002), and an image that can run as root by
# accident is one credential away from a container escape. The Kubernetes
# manifests set runAsNonRoot and runAsUser: 1000 as well, so this is the floor,
# not the only guard.
USER 1000
