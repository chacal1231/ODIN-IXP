---
name: librenms
description: Consultar equipos, interfaces, BGP, alertas y sensores en LibreNMS via API REST. Usar para estado actual, trafico, sesiones BGP, CPU, memoria, temperatura y potencia optica.
---

# LibreNMS

## Conexion
```sh
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/ENDPOINT"
Regla clave

LibreNMS usa hostname en las URLs, no display.

hostname: IP/host real de management → usar en endpoints
display: nombre amigable → mostrar al usuario
sysName: hostname del equipo

Si el usuario dice PE-ODATA01, primero buscarlo en /devices, obtener su hostname real y luego usar ese valor en las demás consultas.

Endpoints utiles
Devices
# listar devices
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/devices"

# devices down
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/devices?type=down"

# detalle device
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/devices/192.0.2.2"
Interfaces
# puertos de un device
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/devices/192.0.2.2/ports?columns=ifName,ifAlias,ifOperStatus,ifAdminStatus,ifSpeed,ifInOctets_rate,ifOutOctets_rate"

# puertos admin up / oper down
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/ports?columns=ifName,ifAlias,ifOperStatus,device_id&ifOperStatus=down&ifAdminStatus=up"

# buscar interfaz
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/ports/search/ifName/Ethernet1"
BGP
# todas las sesiones
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/bgp"

# sesiones por device
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/bgp?hostname=192.0.2.2"

# sesiones por estado
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/bgp?bgp_state=idle"
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/bgp?bgp_state=active"
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/bgp?bgp_state=established"

# filtros
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/bgp?remote_asn=64512"
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/bgp?remote_address=203.0.113.74"

# contadores de prefijos
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/routing/bgp/cbgp"
Alertas
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/alerts?state=1"
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/alerts?severity=critical"
Sensores
# todos
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/devices/192.0.2.2/health"

# temperatura
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/devices/192.0.2.2/health/device_temperature"

# potencia optica
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/devices/192.0.2.2/health/device_dbm"

# voltaje
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/devices/192.0.2.2/health/device_voltage"
Eventos
curl -s -H "X-Auth-Token: TOKEN" "http://198.51.100.43:9001/api/v0/logs/eventlog"
Campos clave
Devices: hostname, display, sysName, status, uptime, hardware, version
Ports: ifName, ifAlias, ifOperStatus, ifAdminStatus, ifSpeed, ifInOctets_rate, ifOutOctets_rate
BGP: bgpPeerRemoteAddr, bgpPeerRemoteAs, bgpPeerState, bgpPeerFsmEstablishedTime
Alerts: state, severity, rule, hostname, timestamp
Sensors: sensor_class, sensor_descr, sensor_current, sensor_limit, sensor_limit_low
Unidades

ifInOctets_rate y ifOutOctets_rate vienen en bytes/s.

Mbps = valor * 8 / 1000000
Gbps = valor * 8 / 1000000000
Reglas
Usar LibreNMS para estado actual
Si el usuario da un nombre amigable, primero resolverlo en /devices
En endpoints por equipo, usar siempre hostname, nunca display
Reportar con nombre amigable + métricas relevantes
No inventar datos
Graylog sirve para histórico; LibreNMS para estado actual