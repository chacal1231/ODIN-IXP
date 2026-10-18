#!/bin/bash
# Initial setup only; preserve the encryption secret of existing installations.
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -f .env ]]; then cp -- .env.example .env; fi
chmod 600 .env
if grep -Eq '^GRAYLOG_PASSWORD_SECRET=.+$' .env; then
    echo 'Secret existente conservado. No se cambia la configuración.'
    exit 0
fi
read -r -p 'Instalación NUEVA sin datos existentes: escriba NUEVA: ' CONFIRM
if [[ "$CONFIRM" != NUEVA ]]; then
    echo 'Cancelado. Para instalaciones existentes restaure el secret original.' >&2
    exit 1
fi
read -r -s -p 'Password admin (mínimo 16 caracteres): ' ADMIN_PASSWORD
echo
if [[ ${#ADMIN_PASSWORD} -lt 16 ]]; then
    unset ADMIN_PASSWORD
    echo 'Password demasiado corto.' >&2
    exit 1
fi
read -r -s -p 'Confirmar password: ' ADMIN_CONFIRM
echo
if [[ "$ADMIN_PASSWORD" != "$ADMIN_CONFIRM" ]]; then
    unset ADMIN_PASSWORD ADMIN_CONFIRM
    echo 'Los passwords no coinciden.' >&2
    exit 1
fi
PASSWORD_SHA2=$(printf '%s' "$ADMIN_PASSWORD" | sha256sum | awk '{print $1}')
unset ADMIN_PASSWORD ADMIN_CONFIRM
PASSWORD_SECRET=$(openssl rand -hex 32)
ENV_TMP=$(mktemp .env.setup.XXXXXX)
trap 'rm -f -- "$ENV_TMP"' EXIT
awk '!/^GRAYLOG_(ROOT_PASSWORD|ROOT_PASSWORD_SHA2|PASSWORD_SECRET)=/' .env > "$ENV_TMP"
printf '\nGRAYLOG_PASSWORD_SECRET=%s\nGRAYLOG_ROOT_PASSWORD_SHA2=%s\n' "$PASSWORD_SECRET" "$PASSWORD_SHA2" >> "$ENV_TMP"
mv -- "$ENV_TMP" .env
unset PASSWORD_SECRET PASSWORD_SHA2
sudo sysctl -w vm.max_map_count=262144
printf '%s\n' 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-opensearch.conf > /dev/null
echo 'Configuración guardada sin imprimir secretos; API local por defecto.'
echo 'Restrinja syslog a los PEs autorizados mediante firewall de host/red.'
echo 'Para iniciar: docker compose up -d'
