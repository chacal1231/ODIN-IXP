<p align="center">
  <img src="assets/odin-logo.svg" alt="ODIN Logo" width="400">
</p>

# ODIN — Omniscient Digital Infrastructure Nexus
> *"Un ojo en cada ruta, un cuervo en cada nodo"*

**ODIN** es la plataforma de observabilidad y el agente de IA de la red de **TVYMAS**. Reúne logs, estado SNMP, tráfico, eventos BGP e inventario del IXP, y un agente (OpenClaw) que consulta esas fuentes en modo solo lectura para diagnosticar y correlacionar incidentes.

El agente presenta hallazgos con fuente y hora, separa hipótesis de hechos e indica qué fuentes faltan. No ejecuta cambios en la red.

## Componentes

| Componente | Herramienta | Función | En este repositorio |
|---|---|---|---|
| Logs | Graylog 6.1 + OpenSearch 2.15 + MongoDB 7.0 | Syslog de los PEs | [graylog/](graylog/): Compose, setup, guía de PEs |
| Estado SNMP | LibreNMS | Equipos, interfaces, BGP, alertas, sensores | [LibreNMS/](LibreNMS/LibreNMS.md): guía de despliegue |
| Tráfico | Akvorado + ClickHouse | Flujos por ASN, PE, interfaz, IP | Solo el cliente del agente (despliegue externo) |
| Eventos BGP | pmacct (pmbmpd) + ClickHouse | BMP: updates, withdrawals, peer up/down | [Pmacct/](Pmacct/README.md): Compose, ingester, logrotate |
| Inventario IXP | IXP Manager | Miembros, ASN, puertos, IPs del peering LAN | Solo el cliente del agente (despliegue externo) |
| Telemetría | gNMIc | Contadores de interfaces y BGP | Skill deshabilitado; sin cliente |
| Agente IA | OpenClaw 2026.8.35 | Skills y clientes de consulta | [ai-agent/OpenClaw/](ai-agent/OpenClaw/README.md) |

Las menciones a «producción» en las guías describen el despliegue declarado por el equipo; la verificación de extremo a extremo con el agente está pendiente (ver [plan](docs/refactor/PLAN.md)).

## Estructura

Rama `ixp` del repositorio (el proyecto ISP vive en la rama `isp`):

```
./
├── README.md                  ← Este archivo
├── .github/workflows/ixp.yml  ← CI: pruebas de los clientes y gitleaks
├── docs/
│   ├── SECURITY.md            ← Acciones pendientes, configuración segura del agente, despliegue Graylog
│   ├── architecture/
│   │   ├── CURRENT_STATE.md   ← Inventario actual y hallazgos abiertos
│   │   └── TARGET_STATE.md    ← Arquitectura objetivo
│   └── refactor/
│       └── PLAN.md            ← Trabajo pendiente
├── graylog/                   ← Stack Graylog (Compose, scripts, guías)
├── LibreNMS/                  ← Guía de LibreNMS
├── Pmacct/                    ← Colector BMP e ingester a ClickHouse
└── ai-agent/
    └── OpenClaw/
        ├── README.md          ← Instalación de OpenClaw y de los Skills de IXP
        ├── IDENTITY.md        ← Instrucciones del agente
        ├── USER.md            ← Perfil del usuario
        ├── .env.example       ← Variables de los clientes
        ├── Skills/            ← Graylog, LibreNMS, Akavorado, IXPManager, Correlacion, Gnmi
        └── tools/             ← Clientes de consulta en Python y sus pruebas
```

## Inicio rápido

```bash
git clone --branch ixp https://github.com/chacal1231/ODIN.git
cd ODIN
```

Cada componente se despliega por separado en su host:

1. **Graylog:** [graylog/README.md](graylog/README.md). Copiar `.env.example`, ejecutar `02-setup-graylog.sh` solo en instalaciones nuevas, `docker compose up -d`.
2. **LibreNMS:** [LibreNMS/LibreNMS.md](LibreNMS/LibreNMS.md).
3. **PMACCT/BMP:** [Pmacct/README.md](Pmacct/README.md); incluye la migración desde el ingester anterior.
4. **Agente:** [ai-agent/OpenClaw/README.md](ai-agent/OpenClaw/README.md). Antes, leer [docs/SECURITY.md](docs/SECURITY.md).

Pruebas de los clientes del agente, desde la raíz del repositorio:

```bash
python -m unittest discover -s ai-agent/OpenClaw/tools -p "test_*.py" -v
```

## Convenciones

- Cada componente tiene su propio `docker-compose.yml`.
- Los `.env` nunca se versionan; cada componente incluye un `.env.example` sin valores.
- Imágenes y versiones fijadas; no usar `latest`.
- El agente consulta solo mediante los clientes de `tools/`, nunca con curl, SQL o Lucene escritos por el modelo.
- Los scripts de setup se numeran: `01-…`, `02-…`.

## Fuera del alcance actual

NetBox, Telegraf/InfluxDB/Grafana, Oxidized, BGPalerter, ExaBGP/GoBGP, SmokePing/RIPE Atlas y Zabbix no tienen configuración en este repositorio. Se añadirán solo con necesidad demostrada.

## Equipo

| Rol | Contacto |
|---|---|
| Arquitecto de red | TVYMAS NOC |
| Agente AI | ODIN (OpenClaw) |

## Licencia

Uso interno TVYMAS. Repositorio privado.
