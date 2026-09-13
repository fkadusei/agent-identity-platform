{{/*
Common labels and helpers for the agent-platform chart.
*/}}

{{- define "agent-platform.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/* Image reference: <registry>/<repository>/<name>:<tag> (registry optional). */}}
{{- define "agent-platform.image" -}}
{{- $img := printf "%s/%s:%s" .root.Values.image.repository .name .root.Values.image.tag -}}
{{- if .root.Values.image.registry -}}
{{- printf "%s/%s" .root.Values.image.registry $img -}}
{{- else -}}
{{- $img -}}
{{- end -}}
{{- end -}}

{{/* Env every service gets: telemetry endpoint and a read-only-friendly Python. */}}
{{- define "agent-platform.commonEnv" -}}
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: {{ .Values.observability.otelEndpoint | quote }}
- name: PYTHONDONTWRITEBYTECODE
  value: "1"
{{- end -}}

{{/* Hardened container securityContext shared by every workload. */}}
{{- define "agent-platform.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}

{{- define "agent-platform.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 1000
seccompProfile:
  type: RuntimeDefault
{{- end -}}
