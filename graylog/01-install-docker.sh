#!/bin/bash
# ============================================================
# Instalación de Docker y Docker Compose en Ubuntu 22.04/24.04
# Para: odin.example.net
# ============================================================

set -e

echo "========================================="
echo " Instalando Docker en odin.example.net"
echo "========================================="

# 1. Actualizar sistema
echo "[1/6] Actualizando sistema..."
sudo apt update && sudo apt upgrade -y

# 2. Instalar dependencias
echo "[2/6] Instalando dependencias..."
sudo apt install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    apt-transport-https \
    software-properties-common

# 3. Agregar clave GPG de Docker
echo "[3/6] Agregando repositorio de Docker..."
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 4. Instalar Docker Engine + Compose
echo "[4/6] Instalando Docker Engine y Compose..."
sudo apt update
sudo apt install -y \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

# 5. Agregar usuario actual al grupo docker
echo "[5/6] Configurando permisos..."
sudo usermod -aG docker $USER

# 6. Habilitar Docker al inicio
echo "[6/6] Habilitando servicio..."
sudo systemctl enable docker
sudo systemctl start docker

echo ""
echo "========================================="
echo " Docker instalado correctamente"
echo "========================================="
echo " Version: $(docker --version)"
echo " Compose: $(docker compose version)"
echo ""
echo " IMPORTANTE: Cierra sesión y vuelve a"
echo " entrar para que el grupo docker aplique."
echo " O ejecuta: newgrp docker"
echo "========================================="
