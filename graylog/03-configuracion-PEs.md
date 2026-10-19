# Graylog — configuración posterior a la instalación

Inputs, envío de syslog desde los PEs, extractors, streams, alertas y verificación. Requiere el stack levantado según el [README](README.md). La UI está en `127.0.0.1:9000` del host: acceder por túnel SSH o proxy TLS.

## 1. Inputs de syslog

System → Inputs → seleccionar el tipo → Launch new input:

| Título | Tipo | Bind address | Puerto | Opciones |
|---|---|---|---|---|
| Syslog TCP - PEs | Syslog TCP | 0.0.0.0 | 1514 | Store full message; 8 worker threads |
| Syslog UDP - PEs | Syslog UDP | 0.0.0.0 | 1514 | Store full message; `recv_buffer_size` 1048576 |

El input escucha en todas las interfaces del contenedor: el control de origen se hace en el firewall del host, permitiendo solo las IPs de gestión de los PEs.

## 2. Envío de syslog desde los PEs

### Arista EOS (configuración en producción TVYMAS)

```
configure terminal
logging buffered 1000000
logging host 198.51.100.43 1514 protocol tcp
logging trap informational
logging format timestamp high-resolution
logging format hostname fqdn
logging format sequence-numbers
logging facility local7
logging source-interface Vlan1545
end
write memory
```

| Parámetro | Valor | Descripción |
|---|---|---|
| `logging buffered 1000000` | 1M líneas | Buffer local si se pierde la conexión |
| `logging host` | 198.51.100.43:1514 TCP | Servidor Graylog (`odin.example.net`) |
| `logging trap informational` | informational | Nivel mínimo enviado |
| `logging format timestamp high-resolution` | — | Timestamps con microsegundos |
| `logging format hostname fqdn` | — | Hostname completo en cada mensaje |
| `logging format sequence-numbers` | — | Numeración para detectar pérdidas |
| `logging facility local7` | local7 | Facility dedicada |
| `logging source-interface Vlan1545` | Vlan1545 | Interfaz de gestión como origen |

El hostname que envía el PE es el `source` en Graylog y debe coincidir con `GRAYLOG_ALLOWED_SOURCES` del agente.

### Cisco IOS-XR (plantilla, si hay PEs Cisco)

```
logging <IP_GRAYLOG> vrf MGMT port 1514
logging source-interface Loopback0
logging trap informational
logging facility local7
logging hostnameprefix PE-NOMBRE
commit
```

### Juniper JunOS (plantilla, si hay PEs Juniper)

```
set system syslog host <IP_GRAYLOG> port 1514
set system syslog host <IP_GRAYLOG> any info
set system syslog host <IP_GRAYLOG> facility-override local7
set system syslog host <IP_GRAYLOG> source-address <IP_LOOPBACK>
commit
```

Los extractors de la sección 4 son para Arista; otros vendors requieren los suyos.

## 3. Verificación del envío

En el PE:

```
show logging
send log level informational message "Test syslog hacia Graylog desde PE-XX"
```

En Graylog → Search, buscar `Test syslog`: debe aparecer en segundos. Desde el host, el contador de mensajes:

```bash
curl --fail --silent --show-error --connect-timeout 5 --max-time 20 --netrc-file "$GRAYLOG_NETRC_FILE" \
  http://127.0.0.1:9000/api/count/total
```

## 4. Extractors

System → Inputs → input → Manage extractors → Add extractor → Regular expression, sobre el campo `message`. Los nombres de campo son los que consulta el agente; no cambiarlos sin actualizar `graylog_query.py`.

| Campo | Expresión regular | Mensaje de ejemplo |
|---|---|---|
| `arista_event` | `%([A-Z0-9_]+-\d-[A-Z0-9_]+)` | `%BGP-5-ADJCHANGE: …` |
| `arista_facility` | `%([A-Z0-9_]+)-\d-` | |
| `arista_severity` | `%[A-Z0-9_]+-(\d)-` (convertir a número) | |
| `arista_mnemonic` | `%[A-Z0-9_]+-\d-([A-Z0-9_]+)` | |
| `bgp_neighbor_ip` | `peer ([0-9A-Fa-f:.]+)` | `peer 192.0.2.1 (VRF default AS 65001) old state OpenConfirm event Established new state Established` |
| `bgp_vrf` | `\(VRF (\S+)` | |
| `bgp_remote_asn` | `AS (\d+)\)` | |
| `bgp_state` | `new state (\w+)` | |
| `interface_name` | `Interface (\S+?),` | `Line protocol on Interface Ethernet1/1, changed state to down` |
| `interface_state` | `changed state to (\w+)` | |
| `config_user` | `by (\S+) on` | `Configured from console by admin on vty3` |

Condicionar cada extractor BGP a mensajes que contengan `ADJCHANGE`, los de interfaz a `changed state` y `config_user` a `%SYS-5-CONFIG`. Probar cada expresión con mensajes reales en el diálogo del extractor antes de guardarla.

Cuando estén estables, exportarlos (Manage extractors → Actions → Export) a `extractors/arista-eos-extractors.json` en este directorio.

## 5. Streams

| Stream | Regla | Propósito |
|---|---|---|
| BGP Events | `arista_facility` = `BGP` | Eventos BGP |
| Interface Events | `message` contiene `changed state` | Cambios de estado de interfaces |
| Config Changes | `arista_event` coincide con `SYS-5-CONFIG` | Cambios de configuración |
| Critical Alerts | `arista_severity` < 4 | Emergencias, alertas, críticos y errores |

Cada stream puede tener su propia retención y alertas.

## 6. Alertas

Alerts → Event Definitions, con notificación a Telegram:

| Alerta | Stream | Condición | Prioridad |
|---|---|---|---|
| BGP Session Down | BGP Events | `bgp_state` en `Idle` o `Active` en los últimos 60 s | Crítica |
| Interface Down | Interface Events | `interface_state:down` en los últimos 60 s | Alta |
| Config Change | Config Changes | Cualquier mensaje nuevo | Informativa |
| High Error Rate | Critical Alerts | Más de 50 mensajes en 5 min | Crítica |

Las alertas de Graylog son independientes del agente: el agente no recibe ni ejecuta nada a partir de ellas.
