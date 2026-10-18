# Syslog — Graylog 6.1

> Centralización de logs de todos los PEs Arista EOS.

## Stack

| Componente | Versión | Función |
|---|---|---|
| Graylog | 6.1 | Collector, procesamiento, UI, API |
| OpenSearch | 2.15.0 | Indexado y almacenamiento de logs |
| MongoDB | 7.0 | Almacenamiento de configuración de Graylog |

## Despliegue

```bash
cd syslog/
cp .env.example .env
# Editar .env con tus valores

bash scripts/02-setup-graylog.sh   # Genera secrets y configura kernel
docker compose up -d
docker compose ps                  # Verificar que todo está healthy
```

## Acceso

- **Web UI:** http://odin.example.net:9000
- **API REST:** http://odin.example.net:9000/api/
- **Usuario:** admin
- **Password:** (configurado durante setup)

## Inputs configurados

| Input | Puerto | Protocolo | Estado |
|---|---|---|---|
| Syslog TCP - PEs | 1514 | TCP | ✅ Activo |
| Syslog UDP - PEs | 1514 | UDP | ✅ Activo |

### Parámetros recomendados para los inputs

- `recv_buffer_size`: 1048576 (1MB) — especialmente en UDP
- `store_full_message`: true
- `number_worker_threads`: 8

## Configuración de PEs Arista EOS

### Configuración en producción (TVYMAS)

```
configure terminal
logging buffered 1000000
logging host 198.51.100.43 1514 protocol tcp
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
| `logging buffered 1000000` | 1M líneas | Buffer local en caso de pérdida de conexión al servidor |
| `logging host` | 198.51.100.43:1514 TCP | IP de odin.example.net, puerto 1514, protocolo TCP |
| `logging format timestamp high-resolution` | — | Timestamps con precisión de microsegundos |
| `logging format hostname fqdn` | — | Incluye hostname completo en cada mensaje |
| `logging format sequence-numbers` | — | Numera los mensajes para detectar pérdidas |
| `logging facility local7` | local7 | Facility dedicada para identificar en Graylog |
| `logging source-interface Vlan1545` | Vlan1545 | Interfaz de management como origen del syslog |

### Verificación desde el PE

```
show logging
send log level informational message "Test syslog hacia Graylog desde PE-XX"
ping 198.51.100.43
```

## Extractors

Los extractors parsean los campos de los mensajes Arista automáticamente.

**Importar:** System → Inputs → [tu input] → Manage extractors → Actions → Import extractors

Archivo: `extractors/arista-eos-extractors.json`

### Campos extraídos

| Campo | Ejemplo | Descripción |
|---|---|---|
| `arista_event` | BGP-5-ADJCHANGE | Evento completo (facility-severity-mnemonic) |
| `arista_facility` | BGP | Protocolo/subsistema de Arista |
| `arista_severity` | 5 | Nivel de severidad (0=emergencia, 7=debug) |
| `arista_mnemonic` | ADJCHANGE | Tipo específico de evento |
| `bgp_neighbor_ip` | 203.0.113.74 | IP del peer BGP afectado |
| `bgp_vrf` | default | VRF de la sesión BGP |
| `bgp_remote_asn` | 64512 | ASN del vecino BGP |
| `bgp_state` | Established | Estado de la sesión BGP |
| `interface_name` | Ethernet1/1 | Nombre de interfaz afectada |
| `interface_state` | down | Estado de la interfaz |
| `config_user` | admin | Usuario que hizo un cambio de config |
| `igp_neighbor_ip` | 10.0.0.1 | IP del vecino OSPF/ISIS |

## Streams

| Stream | Regla | Propósito |
|---|---|---|
| BGP Events | `arista_facility:BGP` | Todos los eventos de BGP |
| Interface Events | `message contains "changed state"` | Cambios de estado de interfaces |
| Config Changes | `message contains "configured"` | Cambios de configuración |
| Critical Alerts | `arista_severity < 4` | Emergencias, alertas, críticos, errores |
| ODIN Actions | `source:odin` | Acciones del agente AI (futuro) |

## Alertas

### BGP Session Down
- **Stream:** BGP Events
- **Condición:** Mensaje contiene "Idle" o "Active" en los últimos 60 segundos
- **Notificación:** Telegram
- **Prioridad:** CRÍTICA

### Interface Down
- **Stream:** Interface Events
- **Condición:** `interface_state:down` en los últimos 60 segundos
- **Notificación:** Telegram
- **Prioridad:** ALTA

### Config Change
- **Stream:** Config Changes
- **Condición:** Cualquier mensaje nuevo
- **Notificación:** Telegram
- **Prioridad:** INFORMATIVA

### High Error Rate
- **Stream:** Critical Alerts
- **Condición:** Más de 50 mensajes en 5 minutos
- **Notificación:** Telegram
- **Prioridad:** CRÍTICA

## Retención de datos

- **Rotación:** 1 índice por día
- **Retención:** 90 días (configurable en `GRAYLOG_ELASTICSEARCH_MAX_NUMBER_OF_INDICES`)
- **Journal:** 10 GB máximo (buffer en disco si OpenSearch no está disponible)

## API REST — Ejemplos útiles

```bash
# Total de mensajes
curl -u TOKEN http://localhost:9000/api/count/total

# Buscar logs de un PE específico
curl -u TOKEN \
  "http://localhost:9000/api/search/universal/relative?query=source:PE-ODATA01&range=3600"

# Buscar eventos BGP
curl -u TOKEN \
  "http://localhost:9000/api/search/universal/relative?query=arista_facility:BGP&range=86400"

# Buscar por neighbor IP
curl -u TOKEN \
  "http://localhost:9000/api/search/universal/relative?query=bgp_neighbor_ip:203.0.113.74&range=86400"
```

## Troubleshooting

### No llegan logs
1. Verificar conectividad: `ping` desde el PE al servidor
2. Verificar puerto: `ss -tlnp | grep 1514`
3. Verificar Docker: `docker compose logs graylog | grep -i error`
4. Verificar input: Graylog UI → System → Inputs → verificar estado "RUNNING"

### OpenSearch no arranca
1. Verificar `vm.max_map_count`: `sysctl vm.max_map_count` (debe ser 262144)
2. Verificar RAM: `docker stats graylog-opensearch`
3. Verificar logs: `docker compose logs opensearch`

### Graylog muestra "Journal utilization is too high"
El journal está lleno porque OpenSearch no puede procesar los mensajes tan rápido.
1. Verificar salud de OpenSearch: `curl http://localhost:9200/_cluster/health`
2. Aumentar `GRAYLOG_PROCESSBUFFER_PROCESSORS` si hay CPU disponible
3. Si persiste, aumentar el heap de OpenSearch

## Archivos

```
syslog/
├── README.md                     ← Este archivo
├── docker-compose.yml            ← Stack Graylog + OpenSearch + MongoDB
├── .env.example                  ← Plantilla de variables de entorno
├── extractors/
│   └── arista-eos-extractors.json ← Extractors para Arista EOS
├── configs/
│   ├── arista-eos-syslog.conf    ← Config de syslog para Arista
│   ├── cisco-iosxr-syslog.conf   ← Config de syslog para Cisco IOS-XR
│   └── juniper-junos-syslog.conf ← Config de syslog para Juniper
└── scripts/
    ├── 01-install-docker.sh      ← Instalación de Docker
    └── 02-setup-graylog.sh       ← Setup inicial de Graylog
```