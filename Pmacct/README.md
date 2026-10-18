# BMP — Visibilidad de tabla BGP en tiempo real

> Monitoreo BMP (BGP Monitoring Protocol) usando pmacct/pmbmpd para dar a ODIN visibilidad completa de la RIB del PE-ODATA01, con ingesta a ClickHouse para consultas SQL eficientes.

---

## Decisión de arquitectura

### OpenBMP vs pmacct

Inicialmente se desplegó **OpenBMP** (`/opt/openbmp`) pero se migró a **pmacct** por:

- OpenBMP requiere Kafka + Zookeeper + PostgreSQL → stack pesado
- pmacct/pmbmpd es un solo contenedor con un archivo de config
- pmacct está más activo y mejor documentado
- Salida directa a JSON sin intermediarios

### Flujo final

```
PE-ODATA01 (Arista EOS)
    │ BMP (TCP :5000)
    ▼
pmbmpd (contenedor Docker)
    │ JSON → /data/bmp-logs/
    ▼
bmp-ingester (Python, tail -F)
    │ HTTP INSERT
    ▼
ClickHouse (198.51.100.37:8123)
    │ tabla bmp_events, TTL 90 días
    ▼
ODIN consulta con SQL
```

---

## Componentes

| Componente | Ubicación | Función |
|---|---|---|
| pmbmpd | Docker en `/opt/pmacct` | Colector BMP, escucha TCP :5000 |
| bmp-ingester | Docker en `/opt/pmacct` ([ingester/](ingester/)) | Lee el JSON por offset con checkpoint y lo inserta en ClickHouse (at-least-once) |
| ClickHouse | `198.51.100.37:8123` (ya existente por Akvorado) | Almacena tabla `bmp_events` con 90 días de retención |
| logrotate | `/etc/logrotate.d/pmbmpd` ([config/logrotate-pmbmpd](config/logrotate-pmbmpd)) | Rota el JSON por hora o tamaño sin perder lo no confirmado |

---

## Instalación

### Paso 1 — Bajar OpenBMP (si existía)

```bash
cd /opt/openbmp
docker compose down
```

### Paso 2 — Crear estructura de pmacct

Los archivos de despliegue están versionados en este directorio (`IXP/Pmacct/`). Copiarlos al host:

```bash
mkdir -p /opt/pmacct/data/{bmp-logs,ingester-state}
cp -r IXP/Pmacct/{config,ingester,docker-compose.yml,.env.example} /opt/pmacct/
cp /opt/pmacct/.env.example /opt/pmacct/.env   # completar credenciales; no versionar
chmod 600 /opt/pmacct/.env
# El ingester corre como uid 10001 y guarda allí su checkpoint
chown 10001 /opt/pmacct/data/ingester-state
```

### Paso 3 — Configuración de pmbmpd

[config/pmbmpd.conf](config/pmbmpd.conf):

```
daemonize: false
bmp_daemon_ip: 0.0.0.0
bmp_daemon_port: 5000
bmp_daemon_max_peers: 20
bmp_daemon_msglog_file: /data/bmp-logs/bmp-events-$peer_src_ip.json
```

Incluye `timestamps_utc: true` comentado: sin él pmbmpd escribe hora local. Activarlo cambia el significado de las filas nuevas frente a las existentes; coordinarlo antes.

**Notas sobre la config:**

- `bmp_dump_file` se eliminó para evitar dumps de 336MB cada 5 minutos (666K+ rutas en JSON)
- `bmp_daemon_msglog_file` NO soporta `%Y%m%d` (solo `$peer_src_ip`). La rotación se maneja con logrotate externo
- Los keys correctos son `bmp_daemon_msglog_file` (NO `bmp_log_file` ni `bmp_log_output` — esos generan warnings de "Unknown key")
- Sin dump, pmbmpd solo registra cambios incrementales, que es lo que ODIN necesita para alertar

### Paso 4 — Docker Compose

[docker-compose.yml](docker-compose.yml) define `pmbmpd` (imagen fijada `pmacct/pmbmpd:v1.8.0`, la que `latest` señalaba el 2026-09-24) y `bmp-ingester`. El ingester lee los logs en solo lectura, guarda su estado en `data/ingester-state` y toma las credenciales de `.env`. Antes de recrear `pmbmpd`, confirmar la versión en ejecución con `docker inspect pmbmpd --format '{{.Image}}'`.

### Paso 5 — Ingester a ClickHouse

[ingester/bmp_ingester.py](ingester/bmp_ingester.py) (Python 3 sin dependencias) sustituye al script con `tail -F`:

| Antes | Ahora |
|---|---|
| POST sin timeout; un error solo se imprimía y el lote se descartaba | Timeout configurable; reintento con backoff hasta 60 s; el lote se conserva hasta que ClickHouse lo confirma |
| El flush por tiempo dependía de que llegara otra línea | Flush cada `BMP_FLUSH_SECONDS` aunque no haya líneas nuevas |
| Sin estado: un reinicio perdía el lote en memoria y releía desde `tail` | Checkpoint durable (`dev`, `inode`, `offset`) que solo avanza tras la confirmación |
| `except: continue` ocultaba errores | Líneas inválidas contadas y registradas; filas sin `timestamp` rechazadas antes de enviar |
| SQL construido por concatenación con escape manual | `INSERT ... FORMAT JSONEachRow`, sin construir SQL con datos |
| Un solo archivo fijo | Todos los `bmp-events-*.json` (un archivo por peer de pmbmpd) |
| — | Errores 4xx no recuperables (p. ej. esquema) pasan a `dead-letter.jsonl` para no bloquear la ingesta |
| — | Métricas cada 60 s en stderr: insertadas, rechazadas, reintentos, inválidas y lag en bytes por archivo |
| — | SIGTERM vacía el lote pendiente (hasta 20 s) antes de salir |

Garantía: at-least-once. Puede haber duplicados si el proceso cae entre la confirmación de ClickHouse y la escritura del checkpoint, o al releer un `.1` tras rotación. Cada envío lleva `insert_deduplication_token`; ClickHouse solo deduplica si la tabla tiene `non_replicated_deduplication_window` (ver Paso 7).

Configuración en [.env.example](.env.example). HTTPS por defecto; para el ClickHouse HTTP actual en red privada hay que fijar `CLICKHOUSE_ALLOW_HTTP=1` de forma explícita. Usar una cuenta con `INSERT` solo sobre `bmp_events`, distinta de la cuenta SELECT del agente.

### Paso 6 — Dockerfile del ingester

[ingester/Dockerfile](ingester/Dockerfile): `python:3.12-slim`, sin `pip install`, usuario sin privilegios (uid 10001).

### Paso 7 — Crear tabla en ClickHouse

```bash
curl -X POST "http://198.51.100.37:8123/" --data "
CREATE TABLE IF NOT EXISTS bmp_events (
    timestamp DateTime64(3),
    log_type String,
    afi UInt8,
    safi UInt8,
    ip_prefix String,
    bgp_nexthop String,
    as_path String,
    comms String,
    lcomms String,
    origin String,
    local_pref UInt32,
    med UInt32,
    peer_ip String,
    bmp_router String,
    bmp_msg_type String,
    inserted_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (timestamp, peer_ip, ip_prefix)
TTL inserted_at + INTERVAL 90 DAY
"
```

Opcional, para que los reenvíos del ingester no dupliquen filas (afecta solo a inserciones nuevas):

```sql
ALTER TABLE bmp_events MODIFY SETTING non_replicated_deduplication_window = 1000
```

### Paso 8 — Levantar

```bash
cd /opt/pmacct
docker compose up -d --build
```

### Paso 9 — Rotación y control de disco

**Retirar el cron `truncate-bmp`.** Reescribía el archivo con `tail -100` + `mv`: el nuevo archivo tenía otro inode mientras pmbmpd seguía escribiendo en el anterior (ya desenlazado), así que se perdían eventos y el disco no se liberaba; además descartaba lo que el ingester no hubiera leído.

```bash
rm /etc/cron.hourly/truncate-bmp
```

**Logrotate** ([config/logrotate-pmbmpd](config/logrotate-pmbmpd)): rota por hora o al superar 200 MB, con `copytruncate` (pmbmpd mantiene el archivo abierto) y `delaycompress`, para que el contenido anterior quede sin comprimir en `<archivo>.1`. Si el ingester no había terminado, retoma desde su checkpoint en ese `.1` antes de seguir con el archivo vivo; si el `.1` no existe o es más corto, registra `rotation_gap` en lugar de saltarse datos en silencio.

```bash
cp /opt/pmacct/config/logrotate-pmbmpd /etc/logrotate.d/pmbmpd
```

`hourly` solo se aplica si logrotate se ejecuta cada hora; en Ubuntu corre a diario por defecto. Añadir una ejecución horaria:

```bash
ln -s /usr/sbin/logrotate /etc/cron.hourly/logrotate-pmbmpd   # o un timer systemd equivalente
```

Limitación conocida de `copytruncate`: lo que pmbmpd escriba entre la copia y el truncado se pierde. Medir en laboratorio (conteo de líneas generadas frente a filas insertadas en varias rotaciones) antes de aceptar la estrategia. La alternativa sin esa ventana es rotar por renombrado si pmbmpd reabre el archivo; el ingester ya soporta ese caso, pero no se ha verificado que pmbmpd reabra.

### Migración desde el ingester anterior

1. Respaldar `cp /opt/pmacct/docker-compose.yml /opt/pmacct/docker-compose.yml.bak` y copiar los archivos nuevos (Paso 2) sin borrar `bmp-to-clickhouse.py` ni `Dockerfile.ingester`, que son la vuelta atrás.
2. En `.env`, fijar `BMP_INITIAL_POSITION=end` para no reinsertar lo que el ingester anterior ya cargó. Se pierden como mucho los eventos de su último lote sin enviar (≤ 5 s o 500 filas).
3. `docker compose up -d --build bmp-ingester` y comprobar en `docker logs bmp-ingester` los eventos `started_at_end`, `stats` y la ausencia de `insert_failed` sostenidos.
4. Retirar el cron `truncate-bmp` e instalar logrotate.
5. Volver a `BMP_INITIAL_POSITION=start` (solo afecta a archivos sin checkpoint, como un peer nuevo).

Rollback: `cp docker-compose.yml.bak docker-compose.yml` y `docker compose up -d --build bmp-ingester`. El ingester anterior vuelve a sus limitaciones (lotes descartados ante fallos); no reinstalar el cron `truncate-bmp`.

---

## Configuración en Arista EOS (PE-ODATA01)

### Prerequisito: multi-agent mode

Necesario para large-community-list en route-maps. **Requiere reboot del switch.**

```
service routing protocols model multi-agent
```

### Configuración BMP

```
router bgp 273103
   monitoring
      station ODIN
         connection address 198.51.100.43
         connection mode active port 5000
         export-policy received routes post-policy
         export-policy bgp rib bestpaths disabled
         no shutdown
```

**Decisiones de configuración:**

| Parámetro | Valor | Por qué |
|---|---|---|
| `connection mode` | `active` | El PE inicia la conexión TCP hacia el colector (estándar BMP) |
| `export-policy` | `post-policy` | Solo envía best paths después del route-map (no pre-policy que manda todas las rutas de todos los peers = millones de entradas) |
| `bestpaths disabled` | Sí | Desactiva el envío de la RIB completa al conectar. Solo cambios incrementales. Evita dumps de 200MB+ en cada reconexión |
| `no shutdown` | Sí | La habilitación es por estación, no global. Sin esto queda en `idle` |

**Notas sobre sintaxis EOS:**

- NO existe `url tcp://...` → el comando correcto es `connection address X` + `connection mode active port Y`
- NO existe `monitoring enabled` a nivel global → la habilitación es `no shutdown` dentro de la estación
- `export-policy received routes additional-paths` fue configurado inicialmente pero luego reemplazado por `post-policy` para reducir volumen

### Verificación

```
show bgp monitoring
```

Debe mostrar:

```
BGP Monitoring status: enabled
Station - ODIN
  Station received route export policies: post-policy
  Connection mode: active
  Address: 198.51.100.43
  Port: 5000
  Connection: connected
  State: up
```

---

## Problemas encontrados y soluciones

### 1. Keys de config incorrectos

**Problema:** `WARN: Unknown key: bmp_log_output / bmp_log_file`

**Solución:** Los keys correctos son:
- `bmp_daemon_msglog_file` (NO `bmp_log_file`)
- `bmp_dump_file` para dumps periódicos
- NO existen `bmp_log_output` ni `bmp_dump_output` como keys separados

### 2. Fecha no parsea en msglog

**Problema:** Archivo se crea como `bmp-events-198_51_100_42-%Y%m%d.json` (literal)

**Solución:** `bmp_daemon_msglog_file` no soporta `%Y%m%d` (solo `$peer_src_ip`). Usar logrotate externo para rotación diaria.

### 3. Dumps de 336MB cada 5 minutos

**Problema:** `bmp_dump_refresh_time: 300` con 666K+ rutas genera 336MB por dump → 96GB/día

**Solución:** Eliminar `bmp_dump_file` y quedarse solo con `bmp_daemon_msglog_file` para eventos incrementales. Si se necesita la tabla completa, consultar directo del PE con `show ip bgp`.

### 4. RIB completa en cada reconexión

**Problema:** Cada vez que el PE reconecta (flap count: 5+), envía toda la RIB (~200K rutas post-policy) como dump inicial. El archivo crece a 2.1GB en segundos.

**Solución:** Aplicar en el PE:

```
export-policy bgp rib bestpaths disabled
```

Esto desactiva el envío de la RIB inicial. Solo cambios incrementales a partir de la conexión. Desventaja: pmbmpd no tiene snapshot de la tabla completa.

### 5. pre-policy vs post-policy

**Problema:** Con `pre-policy` se reciben TODAS las rutas de TODOS los peers (incluyendo non-best paths) → millones de entradas.

**Solución:** Cambiar a `post-policy` → solo best paths después del route-map. Reduce de 666K+ a ~200K entradas.

### 6. BGP Monitoring status: disabled

**Problema:** `show bgp monitoring` muestra `disabled` a pesar de tener la estación configurada.

**Solución:** La habilitación es por estación con `no shutdown`, no existe un comando global `monitoring enabled` en esta versión de EOS.

### 7. Conexión idle/disconnected

**Problema:** Estación en estado `idle` o `disconnected`.

**Solución:** Verificar:
1. Que el colector esté corriendo: `docker logs pmbmpd --tail 10`
2. Que el puerto esté abierto: `ss -tlnp | grep 5000`
3. Conectividad desde el PE: `ping 198.51.100.43`
4. Que `no shutdown` esté aplicado en la estación

---

## Datos confirmados vía BMP

Al conectar por primera vez, BMP confirmó que el tagging de communities está funcionando:

| Peer | peer_ip | LP | Large Community | AS-path | Estado |
|---|---|---|---|---|---|
| Google vía WEBM (IPv6) | `2001:db8:4890:1::9` | 200 | `273103:60:1` (IMPORT-GOOGLE-PNI) | `272156 15169` | ✅ |
| Meta PNI (IPv6) | `2001:db8:32::1432`, `::223c` | 200 | `273103:60:0` (META PNI) | `32934` | ✅ |
| POPs (iBGP) | `fd00:0:0:e000::2`, etc. | 250 | `273103:10:X`, `273103:20:X`, `273103:30:X` | clientes | ✅ |
| BGP Tools | `2001:db8:9459::b19` | — | — | end-of-rib, 0 rutas | ✅ (deny funciona) |
| EdgeUNO (IPv6) | `2001:db8:7195::c` | 180 | `273103:40:2` | transits (Cogent, Lumen) | ✅ |

---

## Consultas útiles

### Desde el archivo JSON (debug rápido)

```bash
# Ver eventos en tiempo real
tail -f /opt/pmacct/data/bmp-logs/bmp-events-198_51_100_42.json | jq -c '{prefix: .ip_prefix, lp: .local_pref, path: .as_path, lcomms: .lcomms, type: .log_type}'

# Buscar una ruta específica
grep '"ip_prefix": "95.217.0.0"' /opt/pmacct/data/bmp-logs/bmp-events-*.json | jq '.'

# Solo withdrawals
tail -f /opt/pmacct/data/bmp-logs/bmp-events-*.json | jq -c 'select(.log_type == "withdraw") | {prefix: .ip_prefix, peer: .peer_ip}'

# Filtrar por peer
tail -f /opt/pmacct/data/bmp-logs/bmp-events-*.json | jq -c 'select(.peer_ip == "2001:db8:32::1432") | {prefix: .ip_prefix, lp: .local_pref, path: .as_path}'

# Rutas con community de Google
grep '273103:60:1' /opt/pmacct/data/bmp-logs/bmp-events-*.json | jq '.ip_prefix, .local_pref, .as_path'
```

### Desde ClickHouse (ODIN)

```bash
# Total de eventos
curl "http://198.51.100.37:8123/" --data "SELECT count() FROM bmp_events"

# Rutas por peer
curl "http://198.51.100.37:8123/" --data "SELECT peer_ip, count() FROM bmp_events GROUP BY peer_ip"

# Buscar ruta específica
curl "http://198.51.100.37:8123/" --data "
SELECT ip_prefix, local_pref, as_path, lcomms, peer_ip 
FROM bmp_events 
WHERE ip_prefix = '95.217.0.0/16' 
ORDER BY timestamp DESC LIMIT 5"

# Withdrawals recientes
curl "http://198.51.100.37:8123/" --data "
SELECT timestamp, ip_prefix, peer_ip 
FROM bmp_events 
WHERE log_type = 'withdraw' 
ORDER BY timestamp DESC LIMIT 20"

# Cambios de LP en las últimas 24h
curl "http://198.51.100.37:8123/" --data "
SELECT ip_prefix, peer_ip, local_pref, as_path, timestamp 
FROM bmp_events 
WHERE timestamp > now() - INTERVAL 24 HOUR 
AND log_type = 'update'
ORDER BY timestamp DESC LIMIT 50"
```

---

## Estructura de archivos

```
/opt/pmacct/
├── docker-compose.yml          ← pmbmpd + bmp-ingester
├── .env                        ← Credenciales ClickHouse (no versionar)
├── ingester/
│   ├── Dockerfile              ← Imagen del ingester
│   └── bmp_ingester.py         ← Ingesta con checkpoint
├── config/
│   ├── pmbmpd.conf             ← Config del colector BMP
│   └── logrotate-pmbmpd        ← Copiar a /etc/logrotate.d/pmbmpd
└── data/
    ├── bmp-logs/
    │   ├── bmp-events-198_51_100_42.json    ← Buffer (rotado por logrotate)
    │   └── bmp-events-198_51_100_42.json.1  ← Rotación anterior sin comprimir
    └── ingester-state/
        ├── checkpoint.json     ← Offset confirmado por archivo
        └── dead-letter.jsonl   ← Lotes rechazados por ClickHouse (4xx)
```

---

## Comandos útiles

```bash
# Ver logs del colector
docker logs pmbmpd --tail 20

# Ver si el ingester está insertando (evento "stats" cada 60 s con lag_bytes)
docker logs bmp-ingester --tail 5

# Lotes rechazados por ClickHouse
wc -l /opt/pmacct/data/ingester-state/dead-letter.jsonl

# Reiniciar
cd /opt/pmacct && docker compose restart

# Rotar manualmente el JSON (no usar truncate -s 0: descarta lo no confirmado)
logrotate -f /etc/logrotate.d/pmbmpd

# Verificar tamaño del archivo
ls -lh /opt/pmacct/data/bmp-logs/

# Contar líneas (eventos acumulados)
wc -l /opt/pmacct/data/bmp-logs/bmp-events-*.json
```

---
