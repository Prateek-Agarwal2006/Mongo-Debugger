{{/*
Construct DATABASE_URL from postgres values, unless overridden.
*/}}
{{- define "mongo-debugger.databaseUrl" -}}
{{- if .Values.secrets.databaseUrlOverride -}}
{{ .Values.secrets.databaseUrlOverride }}
{{- else -}}
postgresql://{{ .Values.postgres.user }}:{{ .Values.postgres.password | default "password" }}@postgres:5432/{{ .Values.postgres.database }}
{{- end -}}
{{- end -}}
