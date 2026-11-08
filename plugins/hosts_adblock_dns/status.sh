#!/bin/sh
# Hosts AdBlock DNS - Status Query
running="false"
rule_count=0

if [ -f /tmp/plugin_hosts_adblock_dns.active ] || grep -q "# MOD_ADBLOCK_START" /var/tmp/hosts 2>/dev/null || [ -f /var/app/conf/dnsmasq.d/adblock.conf ]; then
    running="true"
fi

if [ -f /var/app/conf/dnsmasq.d/adblock.conf ]; then
    rule_count=$(wc -l < /var/app/conf/dnsmasq.d/adblock.conf 2>/dev/null || echo "0")
fi

cat << EOF
{
  "status": 0,
  "plugin": "hosts_adblock_dns",
  "running": $running,
  "rule_count": $rule_count
}
EOF
exit 0
