#!/bin/ash
# Busybox entrypoint for prom/alertmanager: expand ${VAR} and ${VAR:-default}
# placeholders in the mounted template, then exec the alertmanager binary.
# Alertmanager's built-in config loader only does plain ${VAR} expansion, so
# shell-style defaults (:-) and any ${VAR} that is unset land in the URL
# parser as literals and fail the load.
set -eu

TEMPLATE=/etc/alertmanager/alertmanager.yml.tmpl
RENDERED=/tmp/alertmanager.yml

awk '
  function expand(s,   parts, n, name, def, val, i) {
    while (match(s, /\$\{[A-Za-z_][A-Za-z0-9_]*(:-[^}]*)?\}/)) {
      var = substr(s, RSTART + 2, RLENGTH - 3)
      n = split(var, parts, ":-")
      name = parts[1]
      def  = (n > 1) ? parts[2] : ""
      val  = ENVIRON[name]
      if (val == "") val = def
      s = substr(s, 1, RSTART - 1) val substr(s, RSTART + RLENGTH)
    }
    return s
  }
  {
    print expand($0)
  }
' "$TEMPLATE" > "$RENDERED"

exec /bin/alertmanager --config.file="$RENDERED" --storage.path=/alertmanager
