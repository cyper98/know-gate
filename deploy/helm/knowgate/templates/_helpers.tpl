{{/*
Expand the name of the chart.
*/}}
{{- define "knowgate.name" -}}
{{- default .Chart.Name .Values.global.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some K8s name fields are limited to this.
*/}}
{{- define "knowgate.fullname" -}}
{{- if .Values.global.fullnameOverride -}}
{{- .Values.global.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.global.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Chart name and version label value.
*/}}
{{- define "knowgate.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels applied to every resource.
*/}}
{{- define "knowgate.labels" -}}
helm.sh/chart: {{ include "knowgate.chart" . }}
{{ include "knowgate.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: knowgate
{{- end -}}

{{/*
Selector labels (subset of common labels used in matchLabels selectors).
*/}}
{{- define "knowgate.selectorLabels" -}}
app.kubernetes.io/name: {{ include "knowgate.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Component selector labels (adds component key for deployment selectors).
Pass a list with two elements: [rootContext, componentName].
*/}}
{{- define "knowgate.componentSelectorLabels" -}}
{{- $top := index . 0 -}}
{{- $component := index . 1 -}}
app.kubernetes.io/name: {{ include "knowgate.name" $top }}
app.kubernetes.io/instance: {{ $top.Release.Name }}
app.kubernetes.io/component: {{ $component }}
{{- end -}}

{{/*
Resolve image tag: explicit value > .Chart.AppVersion.
Usage: {{ include "knowgate.imageTag" .Values.api.image }}
*/}}
{{- define "knowgate.imageTag" -}}
{{- if .tag -}}
{{- .tag -}}
{{- else -}}
{{- $.Chart.AppVersion -}}
{{- end -}}
{{- end -}}

{{/*
Image reference. Usage: {{ include "knowgate.image" (dict "image" .Values.api.image "Chart" .Chart) }}
*/}}
{{- define "knowgate.image" -}}
{{- $img := .image -}}
{{- $tag := include "knowgate.imageTag" (dict "tag" $img.tag "Chart" .Chart) -}}
{{- printf "%s:%s" $img.repository $tag -}}
{{- end -}}

{{/*
ServiceAccount name. The chart uses the default ServiceAccount for all pods
unless global.serviceAccount.create is true.
*/}}
{{- define "knowgate.serviceAccountName" -}}
{{- $global := index .Values "global" -}}
{{- $sa := index $global "serviceAccount" | default dict -}}
{{- $saCreate := index $sa "create" | default false -}}
{{- $saName := index $sa "name" | default "" -}}
{{- if $saCreate -}}
{{- default (include "knowgate.fullname" .) $saName -}}
{{- else -}}
{{- default "default" $saName -}}
{{- end -}}
{{- end -}}

{{/*
Common env entries shared by api, worker, and beat. Expects the root context
(.) plus a "component" key in the dict.
Usage: {{ include "knowgate.commonEnv" (dict "Values" .Values "component" "api" "Chart" .Chart "Release" .Release) }}
*/}}
{{- define "knowgate.commonEnv" -}}
{{- $v := .Values -}}
{{- $component := .component -}}
- name: KNOWGATE_ENV
  value: {{ $v.global.env | quote }}
- name: KNOWGATE_COMPONENT
  value: {{ $component | quote }}
- name: POSTGRES_HOST
  value: {{ $v.postgres.host | quote }}
- name: POSTGRES_PORT
  value: {{ $v.postgres.port | quote }}
- name: POSTGRES_DB
  value: {{ $v.postgres.database | quote }}
- name: REDIS_HOST
  value: {{ $v.redis.host | quote }}
- name: REDIS_PORT
  value: {{ $v.redis.port | quote }}
- name: QDRANT_HOST
  value: {{ $v.qdrant.host | quote }}
- name: QDRANT_HTTP_PORT
  value: {{ $v.qdrant.httpPort | quote }}
- name: QDRANT_GRPC_PORT
  value: {{ $v.qdrant.grpcPort | quote }}
- name: MINIO_HOST
  value: {{ $v.minio.host | quote }}
- name: MINIO_API_PORT
  value: {{ $v.minio.apiPort | quote }}
- name: LITELLM_HOST
  value: {{ include "knowgate.fullname" (dict "Chart" .Chart "Release" .Release "Values" .Values) }}-litellm
- name: LITELLM_PORT
  value: {{ $v.litellm.service.port | quote }}
{{- if $v.global.env }}
- name: APP_ENV
  value: {{ $v.global.env | quote }}
{{- end }}
{{- end -}}

{{/*
Secret envFrom block: reference an external Secret (created via Sealed
Secrets or by an external operator). When secrets.existingSecret is empty the
template emits nothing, and the caller decides whether to fail fast.
*/}}
{{- define "knowgate.secretEnvFrom" -}}
{{- if .Values.secrets.existingSecret -}}
secretRef:
  name: {{ .Values.secrets.existingSecret }}
{{- end -}}
{{- end -}}

{{/*
Image pull secrets helper.
*/}}
{{- define "knowgate.imagePullSecrets" -}}
{{- if .Values.global.imagePullSecrets -}}
imagePullSecrets:
{{ toYaml .Values.global.imagePullSecrets }}
{{- end -}}
{{- end -}}
