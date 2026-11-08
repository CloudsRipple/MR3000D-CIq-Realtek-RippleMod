#!/bin/sh
# Custom UserScript - Status Query
running="false"
has_script="false"

if [ -f /tmp/plugin_custom_userscript.active ]; then
    running="true"
fi

[ -f "${0%/*}/user_run.sh" ] && has_script="true"

cat << EOF
{
  "status": 0,
  "plugin": "custom_userscript",
  "running": $running,
  "has_script": $has_script
}
EOF
exit 0
