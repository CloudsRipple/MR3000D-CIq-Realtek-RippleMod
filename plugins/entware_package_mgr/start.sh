#!/bin/sh
# Lifecycle scripts for entware_package_mgr
case "$(basename "$0")" in
    start.sh)
        # Ensure /opt symlink exists
        if [ ! -L /opt ] && [ -d /var/app/opt ]; then
            ln -sf /var/app/opt /opt
        fi
        echo "Entware environment ready."
        ;;
    stop.sh)
        echo "Entware environment unhooked."
        ;;
    status.sh)
        "${0%/*}/api.sh" status
        ;;
    install.sh)
        mkdir -p /var/app/opt
        [ ! -L /opt ] && ln -sf /var/app/opt /opt 2>/dev/null || true
        echo "Entware package manager plugin initialized."
        ;;
esac
exit 0
