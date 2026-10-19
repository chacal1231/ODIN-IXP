# LibreNMS — Monitoreo SNMP

> Monitoreo en tiempo real de PEs Arista EOS: interfaces, sesiones BGP, CPU, memoria, temperatura y ópticas.

---

## Stack

| Componente | Versión | Función |
|---|---|---|
| LibreNMS | 26.9.1.1 (imagen `librenms/librenms`, fijada) | Monitoreo SNMP, autodiscovery, alertas |
| MariaDB | 10.11 | Base de datos |
| Redis | 7 | Cache y colas |
| Memcached | La del ejemplo oficial | Cache de polling |
| RRDcached | La del ejemplo oficial | Cache de gráficas RRD |

Versiones de servicios auxiliares: las que fija el ejemplo de Compose del tag `26.9.1.1-r1` de `librenms/docker`. Si alguna usa `latest`, fijarla igual que LibreNMS.

## Requisitos previos

- Docker y Docker Compose instalados en `odin.example.net`
- SNMP configurado en los PEs Arista
- Puerto 9001 disponible (Web UI)
- Conectividad SNMP desde el servidor hacia los PEs por la red de management

---

## Paso 1 — Descargar los archivos oficiales de una versión fijada

```bash
VERSION=26.9.1.1-r1
mkdir -p /opt/librenms
cd /opt/librenms
wget "https://github.com/librenms/docker/archive/refs/tags/${VERSION}.zip"
unzip "${VERSION}.zip"
cp "docker-${VERSION}"/examples/compose/* .
rm -rf "docker-${VERSION}" "${VERSION}.zip"
```

En `compose.yml`, fijar la imagen de LibreNMS (y la del dispatcher y demás servicios `librenms/librenms`) a la versión, en lugar de `latest`:

```yaml
image: librenms/librenms:26.9.1.1
```

Para actualizar: cambiar `VERSION` y la imagen a una versión publicada hace al menos dos semanas, revisar las notas de versión y validar en laboratorio.

## Paso 2 — Configurar variables de entorno

### Archivo `.env`

```bash
nano .env
```

Cambiar estos valores:

```
TZ=America/Bogota
MYSQL_PASSWORD=<GENERAR_PASSWORD_UNICO>
MYSQL_ROOT_PASSWORD=<GENERAR_PASSWORD_ROOT_UNICO>
```

### Archivo `librenms.env`

```bash
nano librenms.env
```

Cambiar:

```
TZ=America/Bogota
LIBRENMS_SNMP_COMMUNITY=<SNMP_COMMUNITY_PRIVADA>
```

## Paso 3 — Cambiar el puerto de la Web UI

Por defecto LibreNMS usa el puerto 8000. Para ODIN lo cambiamos a 9001 para evitar conflictos.

```bash
nano compose.yml
```

Buscar la sección de puertos del servicio `librenms` y cambiar:

```yaml
ports:
  - target: 8000
    published: 9001
    protocol: tcp
```

## Paso 4 — Levantar el stack

```bash
docker compose up -d
```

Verificar que todos los contenedores estén corriendo:

```bash
docker compose ps
```

Esperar 1-2 minutos mientras LibreNMS hace la migración inicial de la base de datos:

```bash
docker compose logs -f librenms
```

## Paso 5 — Crear usuario admin

Acceder a `http://odin.example.net:9001` y crear el usuario admin en el wizard inicial.

Si necesitas crear un usuario adicional por CLI:

```bash
docker compose exec --user librenms librenms lnms user:add admin -r admin
# Usar el mecanismo interactivo de la versión instalada; no poner passwords en argumentos.
```

## Paso 6 — Validar la instalación

```bash
docker compose exec --user librenms librenms php validate.php
```

Debe mostrar `[OK]` en la mayoría de componentes.

---

## Configuración de SNMP en PEs Arista EOS

```
configure terminal
snmp-server community <SNMP_COMMUNITY_PRIVADA> ro
snmp-server vrf MANAGEMENT
snmp-server host odin.example.net version 2c <SNMP_COMMUNITY_PRIVADA>
snmp-server enable traps
snmp-server location "Bogota, Colombia [4.6097, -74.0817]"
end
write memory
```

### Formato de location para el mapa

El campo `snmp-server location` debe incluir coordenadas entre corchetes para que LibreNMS las parsee y las muestre en el Geo Map:

```
snmp-server location "CIUDAD, Colombia [LATITUD, LONGITUD]"
```

Ejemplos por ciudad:

| Ciudad | Comando |
|---|---|
| Bogotá | `snmp-server location "Bogota, Colombia [4.6097, -74.0817]"` |
| Medellín | `snmp-server location "Medellin, Colombia [6.2442, -75.5812]"` |
| Cali | `snmp-server location "Cali, Colombia [3.4516, -76.5320]"` |
| Barranquilla | `snmp-server location "Barranquilla, Colombia [10.9685, -74.7813]"` |
| Yopal | `snmp-server location "Yopal, Colombia [5.3378, -72.3959]"` |
| Bucaramanga | `snmp-server location "Bucaramanga, Colombia [7.1254, -73.1198]"` |

---

## Agregar dispositivos

### Por la Web UI

Devices → Add Device → ingresar IP de management, community SNMP y versión.

### Por CLI (recomendado para batch)

```bash
# Agregar un PE
docker compose exec --user librenms librenms lnms device:add 192.0.2.2 --v2c -c <SNMP_COMMUNITY_PRIVADA>

# Agregar varios PEs
for IP in 192.0.2.2 192.0.2.3 192.0.2.4 192.0.2.5; do
  docker compose exec --user librenms librenms lnms device:add $IP --v2c -c <SNMP_COMMUNITY_PRIVADA>
done
```

### Forzar polling inmediato de un PE

```bash
docker compose exec --user librenms librenms php /opt/librenms/poller.php -h 192.0.2.2
```

**Nota:** LibreNMS registra los devices por IP de management (campo `hostname`), no por el nombre del equipo. El campo `display` muestra el nombre amigable (ej: PE-ODATA01) pero las consultas a la API deben usar la IP.

---

## API REST

### Habilitar la API

1. Settings (engranaje) → API → API Settings → Enable API → Activar → Save
2. Crear un usuario de solo lectura para el agente (nivel *Global Read*), no usar `admin`.
3. Settings → API → API Keys → Create API access token, para ese usuario, descripción: `ODIN`.
4. Guardar el token en el gestor de secretos y entregarlo al agente como `LIBRENMS_TOKEN`; no escribirlo en Skills, prompts ni archivos versionados.

### Verificar que funciona

Con el token en un archivo de cabecera externo (permisos 600, una línea `X-Auth-Token: <token>`), para que no quede en el historial ni en la lista de procesos:

```bash
curl --fail --silent --show-error --max-time 20 -H @"$LIBRENMS_HEADER_FILE" \
  "http://127.0.0.1:9001/api/v0/devices" | python3 -m json.tool | head -20
```

El agente exige HTTPS: publicar la API detrás de un proxy TLS para `LIBRENMS_URL`.

### Endpoints principales

| Endpoint | Descripción |
|---|---|
| `/api/v0/devices` | Listar todos los equipos |
| `/api/v0/devices?type=down` | Equipos caídos |
| `/api/v0/devices/{IP}` | Detalle de un equipo |
| `/api/v0/devices/{IP}/ports` | Interfaces de un equipo |
| `/api/v0/bgp` | Todas las sesiones BGP |
| `/api/v0/bgp?bgp_state=idle` | Sesiones BGP caídas |
| `/api/v0/bgp?bgp_state=established` | Sesiones BGP activas |
| `/api/v0/bgp?hostname={IP}` | BGP de un equipo |
| `/api/v0/bgp?remote_asn={ASN}` | BGP por ASN remoto |
| `/api/v0/routing/bgp/cbgp` | Contadores BGP (prefijos) |
| `/api/v0/alerts?state=1` | Alertas activas |
| `/api/v0/alerts?severity=critical` | Alertas críticas |
| `/api/v0/devices/{IP}/health` | Sensores (CPU, temp, voltaje) |
| `/api/v0/devices/{IP}/health/device_temperature` | Temperatura |
| `/api/v0/devices/{IP}/health/device_dbm` | Ópticas Tx/Rx |
| `/api/v0/logs/eventlog/{IP}` | Eventos de un equipo |
| `/api/v0/system` | Estado de LibreNMS |

Estos son los endpoints que usa `librenms_query.py`. Su formato de respuesta aún debe confirmarse contra esta versión (ver [plan](../docs/refactor/PLAN.md)).

### Unidades de tráfico en la API

Los campos `ifInOctets_rate` y `ifOutOctets_rate` están en **bytes por segundo (B/s)**.

| Para obtener | Fórmula |
|---|---|
| Mbps | valor × 8 / 1,000,000 |
| Gbps | valor × 8 / 1,000,000,000 |

Ejemplo: `ifOutOctets_rate = 125000000` → 125000000 × 8 / 1e6 = **1000 Mbps = 1 Gbps**

---

## Dashboard NOC

### Crear el dashboard

Dashboards (arriba a la derecha) → Create Dashboard → Nombre: `NOC TVYMAS`

### Widgets recomendados

| Widget | Función |
|---|---|
| **Alerts** | Alertas activas en tiempo real |
| **Availability Map** | Estado de todos los PEs (verde/rojo) |
| **Device Summary** | Resumen: up, down, warning |
| **Top Interfaces** | Interfaces con más tráfico |
| **Eventlog** | Últimos eventos |
| **Component Status** | Estado de sesiones BGP |
| **Geo Map** | Mapa geográfico de PEs (requiere coordenadas en SNMP location) |

Para agregar widgets: dentro del dashboard click **"+"** → seleccionar widget → configurar.

---

## Integración con ODIN

El agente consulta LibreNMS con `tools/librenms_query.py` siguiendo el [Skill LibreNMS](../ai-agent/OpenClaw/Skills/LibreNMS/SKILL.md):

- Resolución de nombre amigable a hostname (`resolve`)
- Equipos up/down, interfaces y tráfico
- Sesiones BGP y sus estados
- Alertas activas y eventlog
- Sensores, y ópticas con márgenes en dB ordenadas por riesgo (`optics`)

Configuración en el entorno del agente: `LIBRENMS_URL` (HTTPS), `LIBRENMS_TOKEN`, `LIBRENMS_ALLOWED_DEVICES` (hostnames, es decir, IPs de gestión) y `LIBRENMS_TIMEZONE=-05:00` (zona horaria del servidor, `TZ=America/Bogota`). Instalación en el [README de OpenClaw](../ai-agent/OpenClaw/README.md).

Para las ópticas, conviene que las descripciones de los sensores incluyan `Rx`/`Tx` y que los límites sean los del transceptor; el agente marca los límites como no verificados porque LibreNMS puede asignarlos por defecto.

### Correlación con Graylog

| Pregunta del usuario | LibreNMS responde | Graylog complementa |
|---|---|---|
| "¿Está caído PE-03?" | Estado actual (up/down) | Cuándo se cayó, eventos previos |
| "¿Cómo están las sesiones BGP?" | Estado actual de cada sesión | Histórico de flaps y cambios |
| "¿Qué interfaces están down?" | Lista actual de interfaces down | Cuándo cambiaron de estado |
| "¿Temperatura del PE-01?" | Valor actual de sensores | Alertas históricas de temperatura |

---

## Troubleshooting

### No se ven gráficas

Las gráficas necesitan varios ciclos de polling (cada 5 min) para poblarse. Esperar 15-20 minutos después de agregar un dispositivo. Para forzar un poll:

```bash
docker compose exec --user librenms librenms php /opt/librenms/poller.php -h IP_DEL_PE
```

### SNMP no responde

```bash
# Probar SNMP desde el contenedor
docker compose exec librenms snmpwalk -v2c -c <SNMP_COMMUNITY_PRIVADA> IP_DEL_PE sysName.0
```

Si falla:
1. Verificar que el PE tiene SNMP habilitado
2. Verificar que el PE permite SNMP desde la IP de odin.example.net
3. Verificar conectividad: `docker compose exec librenms ping IP_DEL_PE`

### Device aparece con IP en vez de hostname

LibreNMS registra por IP de management. Para renombrar (requiere un token con permisos de escritura, distinto del del agente):

```bash
curl --fail --silent --show-error -X PATCH -H @"$LIBRENMS_ADMIN_HEADER_FILE" \
  "http://127.0.0.1:9001/api/v0/devices/192.0.2.2/rename/pe-odata01"
```

Renombrar cambia `hostname`: actualizar `LIBRENMS_ALLOWED_DEVICES` del agente.

### Poller no corre

```bash
docker compose logs librenms-dispatcher
docker compose exec --user librenms librenms php validate.php
```

---

## Comandos útiles

```bash
# Ver logs
docker compose logs -f librenms

# Validar instalación
docker compose exec --user librenms librenms php validate.php

# Poll forzado de un PE
docker compose exec --user librenms librenms php /opt/librenms/poller.php -h IP

# Discovery forzado de un PE
docker compose exec --user librenms librenms php /opt/librenms/discovery.php -h IP

# Listar devices por CLI
docker compose exec --user librenms librenms lnms device:list

# Agregar device por CLI
docker compose exec --user librenms librenms lnms device:add IP --v2c -c COMMUNITY

# Ver estado del poller
docker compose exec --user librenms librenms lnms poller:status
```

---

## Archivos

```
/opt/librenms/
├── compose.yml          ← Docker Compose
├── .env                 ← Variables de Docker (MYSQL passwords)
├── librenms.env         ← Variables de LibreNMS (TZ, SNMP community)
├── msmtpd.env           ← Config de email (opcional)
├── librenms/            ← Datos persistentes de LibreNMS
└── db/                  ← Datos de MariaDB
```

## Acceso

- **Web UI:** http://odin.example.net:9001 (restringir por firewall a la red de gestión)
- **API:** http://odin.example.net:9001/api/v0/; para el agente, la misma API detrás de un proxy TLS
- **Puerto SNMP:** 161/UDP (desde LibreNMS hacia los PEs)