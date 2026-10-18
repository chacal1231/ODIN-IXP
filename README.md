<p align="center">
  <img src="assets/odin-logo.svg" alt="ODIN Logo" width="400">
</p>

# ODIN — Omniscient Digital Infrastructure Nexus
> *"Un ojo en cada ruta, un cuervo en cada nodo"*

**ODIN** es la plataforma de observabilidad, automatización y AI para la infraestructura de red de **TVYMAS**. Integra monitoreo, logging, telemetría, análisis de tráfico, gestión de configuraciones y un agente de inteligencia artificial que diagnostica, correlaciona y toma acciones sobre la red.

---

## Visión general

ODIN nace de la necesidad de tener un NOC inteligente que no dependa de operadores 24/7 para detectar y reaccionar ante problemas en la red. El sistema observa cada PE, cada ruta BGP, cada flujo de tráfico y cada log — y cuando algo se sale de lo normal, ODIN lo detecta, diagnostica la causa raíz y recomienda (o ejecuta) la acción correctiva.

## Stack tecnológico

| Componente | Herramienta | Función | Estado |
|---|---|---|---|
| Logs centralizados | Graylog 6.1 + OpenSearch 2.15 | Syslog de todos los PEs | ✅ Producción |
| Análisis de tráfico | Akvorado + ClickHouse | NetFlow/sFlow, volumen por ASN | ✅ Producción |
| Source of truth | NetBox | Inventario, IPAM, circuitos | ⬜ Pendiente |
| Monitoreo SNMP | LibreNMS | Estado de PEs, interfaces, BGP | ⬜ Pendiente |
| Telemetría streaming | Telegraf + InfluxDB + Grafana | gNMI/OpenConfig, métricas RT | ⬜ Pendiente |
| Backup de configs | Oxidized | Histórico Git de configs | ⬜ Pendiente |
| Rutas BGP internas | OpenBMP | Tabla BGP en tiempo real | ⬜ Pendiente |
| Monitoreo BGP externo | BGPalerter | Hijacks, leaks, RPKI | ⬜ Pendiente |
| BGP programático | ExaBGP/GoBGP | Inyección/retiro de rutas | ⬜ Pendiente |
| Medición de latencia | SmokePing + RIPE Atlas | Latencia, jitter, packet loss | ⬜ Pendiente |
| QoE por servicio | Akvorado + Telegraf probes | Calidad hacia Netflix, gaming | ⬜ Pendiente |
| Agente AI | OpenClaw + NetClaw (ODIN) | Diagnóstico y acciones automáticas | ⬜ Pendiente |

## Infraestructura

- **Servidor principal:** `odin.example.net`
- **OS:** Ubuntu 22.04/24.04 LTS
- **RAM:** 32 GB
- **Orquestación:** Docker Compose
- **Vendor de PEs:** Arista EOS
- **Conectividad:** Red de management dedicada

## Estructura del repositorio

```
odin/
├── README.md                    ← Este archivo
├── docs/
│   ├── architecture.md          ← Arquitectura general y flujos
│   ├── roadmap.md               ← Plan de implementación por fases
│   └── security.md              ← Consideraciones de seguridad
├── syslog/
│   ├── README.md                ← Guía de Graylog
│   ├── docker-compose.yml       ← Stack Graylog + OpenSearch + MongoDB
│   ├── .env                     ← Variables de entorno
│   ├── extractors/              ← JSONs de extractors por vendor
│   └── configs/                 ← Configuraciones de syslog por vendor
├── monitoring/
│   ├── librenms/                ← LibreNMS (SNMP)
│   ├── telegraf-influxdb-grafana/ ← Stack TIG (telemetría)
│   ├── smokeping/               ← Medición de latencia
│   └── ripe-atlas/              ← Sondas y mediciones RIPE Atlas
├── netbox/
│   └── README.md                ← NetBox como source of truth
├── bgp/
│   ├── openbmp/                 ← Monitoreo interno de rutas
│   ├── bgpalerter/              ← Monitoreo externo (hijacks/leaks)
│   └── exabgp/                  ← Speaker BGP programático
├── backup/
│   └── oxidized/                ← Backup de configuraciones
├── telemetry/
│   └── README.md                ← gNMI + OpenConfig
├── qoe/
│   ├── akvorado/                ← Análisis de tráfico por servicio
│   └── README.md                ← Monitoreo de QoE
├── ai-agent/
│   ├── openclaw/                ← Configuración de OpenClaw
│   ├── skills/                  ← Skills personalizados de ODIN
│   └── mcp-servers/             ← Servidores MCP para cada componente
├── addressing/
│   └── README.md                ← Esquema de direccionamiento IPv4/IPv6
└── scripts/
    └── README.md                ← Scripts de utilidad y mantenimiento
```

## Inicio rápido

```bash
# 1. Clonar el repositorio
git clone git@github.com:tvymas/odin.git
cd odin

# 2. Instalar Docker (si no está instalado)
sudo bash syslog/scripts/01-install-docker.sh
newgrp docker

# 3. Levantar Graylog (primer componente)
cd syslog
bash scripts/02-setup-graylog.sh
docker compose up -d

# 4. Verificar
docker compose ps
# Acceder a http://odin.example.net:9000
```

## Convenciones

- Cada componente tiene su propio `docker-compose.yml` independiente
- Los archivos `.env` nunca se commitean — se incluye un `.env.example`
- Las configuraciones de equipos van en `configs/` dentro de cada módulo
- Los scripts de setup se numeran secuencialmente: `01-install.sh`, `02-configure.sh`
- Los dashboards de Grafana se exportan como JSON en `dashboards/`

## Equipo

| Rol | Contacto |
|---|---|
| Arquitecto de red | TVYMAS NOC |
| Agente AI | ODIN (OpenClaw) |

## Licencia

Uso interno TVYMAS. Repositorio privado.