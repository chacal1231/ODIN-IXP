#!/bin/bash
# ============================================================
# Setup Graylog Stack - odin.example.net
# Ejecutar después de instalar Docker
# ============================================================

set -e

echo "========================================="
echo " Configurando Graylog Stack"
echo " odin.example.net"
echo "========================================="

# 1. Configurar kernel para OpenSearch
echo "[1/5] Configurando kernel para OpenSearch..."
sudo sysctl -w vm.max_map_count=262144
echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.d/99-opensearch.conf
sudo sysctl --system

# 2. Generar password secret
echo "[2/5] Generando password secret..."
PASSWORD_SECRET=$(openssl rand -hex 32)
echo ""
echo "  Password secret generado: $PASSWORD_SECRET"

# 3. Solicitar password del admin
echo ""
read -sp "[3/5] Ingresa el password para el admin de Graylog: " ADMIN_PASSWORD
echo ""
PASSWORD_SHA2=$(echo -n "$ADMIN_PASSWORD" | sha256sum | awk '{print $1}')
echo "  SHA256 generado correctamente"

# 4. Actualizar .env con los valores generados
echo "[4/5] Actualizando archivo .env..."
sed -i "s/GRAYLOG_PASSWORD_SECRET=.*/GRAYLOG_PASSWORD_SECRET=$PASSWORD_SECRET/" .env

# Agregar la variable SHA2 al .env si no existe
if grep -q "GRAYLOG_ROOT_PASSWORD_SHA2" .env; then
    sed -i "s/GRAYLOG_ROOT_PASSWORD_SHA2=.*/GRAYLOG_ROOT_PASSWORD_SHA2=$PASSWORD_SHA2/" .env
else
    echo "" >> .env
    echo "# SHA256 del password de admin (generado automáticamente)" >> .env
    echo "GRAYLOG_ROOT_PASSWORD_SHA2=$PASSWORD_SHA2" >> .env
fi

# 5. Crear directorios y ajustar permisos
echo "[5/5] Creando directorios..."
mkdir -p ./data/{mongodb,opensearch,graylog,graylog-journal}

# 6. Configurar firewall (UFW)
echo ""
echo "========================================="
echo " Configurando firewall (UFW)"
echo "========================================="
read -p "¿Quieres configurar UFW automáticamente? (s/n): " CONFIGURE_UFW

if [ "$CONFIGURE_UFW" = "s" ]; then
    # Permitir SSH
    sudo ufw allow 22/tcp comment "SSH"
    # Graylog Web UI + API
    sudo ufw allow 9000/tcp comment "Graylog Web UI + API REST"
    # Syslog desde PEs
    sudo ufw allow 1514/tcp comment "Syslog TCP desde PEs"
    sudo ufw allow 1514/udp comment "Syslog UDP desde PEs"
    # Habilitar UFW si no está activo
    sudo ufw --force enable
    echo "  Firewall configurado correctamente"
else
    echo "  Saltando configuración de firewall"
    echo "  Recuerda abrir los puertos: 9000/tcp, 1514/tcp, 1514/udp"
fi

echo ""
echo "========================================="
echo " Setup completado"
echo "========================================="
echo ""
echo " Para iniciar el stack ejecuta:"
echo ""
echo "   docker compose up -d"
echo ""
echo " Para ver los logs en tiempo real:"
echo ""
echo "   docker compose logs -f"
echo ""
echo " Una vez arriba, accede a:"
echo ""
echo "   URL:      http://odin.example.net:9000"
echo "   Usuario:  admin"
echo "   Password: (el que acabas de configurar)"
echo ""
echo " Siguiente paso: configurar los inputs"
echo " de syslog desde la interfaz web de Graylog."
echo "========================================="
