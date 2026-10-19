# Graylog — logs de los PEs

> Centralización del syslog de los PEs Arista EOS. Fuente de los eventos que consulta el agente con `tools/graylog_query.py`.

## Stack

| Componente | Versión | Función |
|---|---|---|
| Graylog | 6.1 | Recepción, procesamiento, UI y API |
| OpenSearch | 2.15.0 | Indexado y almacenamiento de logs |
| MongoDB | 7.0 | Configuración de Graylog |

## Despliegue

Desde este directorio (`graylog/`), en el host Linux de Graylog:

```bash
sudo bash 01-install-docker.sh      # solo si Docker no está instalado; actualiza el sistema y añade el usuario al grupo docker
cp .env.example .env                # solo en instalación nueva
bash 02-setup-graylog.sh            # solo en instalación nueva: genera secretos sin imprimirlos y fija vm.max_map_count
docker compose up -d
docker compose ps                   # todos los servicios healthy
```

En una instalación existente no ejecutar el setup para «regenerar» nada: `GRAYLOG_PASSWORD_SECRET` cifra datos y debe conservarse. Ver [docs/SECURITY.md](../docs/SECURITY.md#despliegue-graylog).

Después, configurar inputs, PEs, extractors, streams y alertas según [03-configuracion-PEs.md](03-configuracion-PEs.md).

## Acceso

| Servicio | Dirección | Notas |
|---|---|---|
| Web UI y API | `127.0.0.1:9000` en el host | Acceder por túnel SSH o proxy TLS autenticado. `GRAYLOG_HTTP_BIND` permite enlazar otra dirección de gestión, restringida por firewall |
| Syslog TCP/UDP | `:1514` | Restringir orígenes a los PEs autorizados |
| Beats / GELF | `:5044`, `:12201` | Opcionales; cerrarlos en el firewall si no se usan |
| OpenSearch | Solo red interna de Compose | Sin autenticación: no publicar |

Usuario `admin`; password definido en el setup (solo se guarda su hash). Para el agente, crear un usuario de solo lectura con token propio.

## Retención

- Rotación: un índice por día.
- Retención: 90 índices (`GRAYLOG_ELASTICSEARCH_MAX_NUMBER_OF_INDICES` en `docker-compose.yml`).
- Journal: hasta 10 GB en disco si OpenSearch no está disponible.

## Campos que usa el agente

`graylog_query.py` filtra y devuelve estos campos. Deben existir con estos nombres, creados por los extractors (ver la [guía de configuración](03-configuracion-PEs.md#4-extractors)):

| Campo | Ejemplo | Descripción |
|---|---|---|
| `arista_event` | BGP-5-ADJCHANGE | Evento completo (facility-severity-mnemonic) |
| `arista_facility` | BGP | Subsistema |
| `arista_severity` | 5 | Severidad (0 = emergencia … 7 = debug) |
| `arista_mnemonic` | ADJCHANGE | Tipo de evento |
| `bgp_neighbor_ip` | 192.0.2.1 | Peer BGP |
| `bgp_vrf` | default | VRF de la sesión |
| `bgp_remote_asn` | 65001 | ASN del peer |
| `bgp_state` | Established | Estado de la sesión |
| `interface_name` | Ethernet1/1 | Interfaz |
| `interface_state` | down | Estado de la interfaz |
| `config_user` | admin | Usuario de un cambio de configuración |
| `igp_neighbor_ip` | 10.0.0.1 | Vecino OSPF/IS-IS |

El campo `source` debe coincidir exactamente con los nombres de `GRAYLOG_ALLOWED_SOURCES` del agente.

## API

El agente usa `tools/graylog_query.py` (ver el [Skill](../ai-agent/OpenClaw/Skills/Graylog/SKILL.md)). Para comprobaciones manuales desde el host, con un archivo netrc externo (`GRAYLOG_NETRC_FILE`, permisos 600, cuenta de consulta):

```bash
# Total de mensajes
curl --fail --silent --show-error --connect-timeout 5 --max-time 20 --netrc-file "$GRAYLOG_NETRC_FILE" \
  http://127.0.0.1:9000/api/count/total

# Logs de un PE en la última hora
curl --fail --silent --show-error --connect-timeout 5 --max-time 20 --netrc-file "$GRAYLOG_NETRC_FILE" \
  -H "Accept: application/json" \
  "http://127.0.0.1:9000/api/search/universal/relative?query=source:PE-ODATA01&range=3600&limit=20"
```

No poner tokens ni passwords en la línea de comandos.

## Troubleshooting

### No llegan logs
1. Conectividad desde el PE al servidor (`ping` por la VRF de gestión).
2. Puerto: `ss -tlnp | grep 1514` y `ss -ulnp | grep 1514`.
3. Errores: `docker compose logs graylog | grep -i error`.
4. Input en estado RUNNING: System → Inputs.
5. Firewall del host: el origen del PE debe estar permitido.

### OpenSearch no arranca
1. `sysctl vm.max_map_count` debe ser 262144 (el setup lo deja en `/etc/sysctl.d/99-opensearch.conf`).
2. Memoria: `docker stats graylog-opensearch`.
3. `docker compose logs opensearch`.

### «Journal utilization is too high»
OpenSearch no procesa al ritmo de entrada.
1. Salud: `docker compose exec opensearch curl -s http://localhost:9200/_cluster/health`.
2. Aumentar `GRAYLOG_PROCESSBUFFER_PROCESSORS` si hay CPU disponible.
3. Si persiste, aumentar el heap de OpenSearch (`OPENSEARCH_JAVA_OPTS`).

## Archivos

```
graylog/
├── README.md                  ← Este archivo
├── 03-configuracion-PEs.md    ← Inputs, PEs, extractors, streams, alertas y verificación
├── docker-compose.yml         ← Graylog + OpenSearch + MongoDB
├── .env.example               ← Plantilla sin valores (.env no se versiona)
├── 01-install-docker.sh       ← Instalación de Docker
└── 02-setup-graylog.sh        ← Setup inicial (solo instalación nueva)
```

Los extractors, streams y alertas se configuran en la UI y no están versionados. Exportar los extractors (Manage extractors → Actions → Export) y guardarlos aquí como `extractors/arista-eos-extractors.json` cuando estén estables.
