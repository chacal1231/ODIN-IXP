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
| bmp-ingester | Docker en `/opt/pmacct` | Lee JSON con tail -F, inserta en ClickHouse |
| ClickHouse | `198.51.100.37:8123` (ya existente por Akvorado) | Almacena tabla `bmp_events` con 90 días de retención |
| cron truncate | `/etc/cron.hourly/truncate-bmp` | Trunca JSON cada hora para no llenar disco |

---

## Instalación

### Paso 1 — Bajar OpenBMP (si existía)

```bash
cd /opt/openbmp
docker compose down
```

### Paso 2 — Crear estructura de pmacct

```bash
mkdir -p /opt/pmacct/{config,data/bmp-logs}
```

### Paso 3 — Configuración de pmbmpd

```bash
cat > /opt/pmacct/config/pmbmpd.conf << 'EOF'
daemonize: false
bmp_daemon_ip: 0.0.0.0
bmp_daemon_port: 5000
bmp_daemon_max_peers: 20

! Solo eventos en tiempo real (cambios de ruta, peer up/down)
bmp_daemon_msglog_file: /data/bmp-logs/bmp-events-$peer_src_ip.json
EOF
```

**Notas sobre la config:**

- `bmp_dump_file` se eliminó para evitar dumps de 336MB cada 5 minutos (666K+ rutas en JSON)
- `bmp_daemon_msglog_file` NO soporta `%Y%m%d` (solo `$peer_src_ip`). La rotación se maneja con logrotate externo
- Los keys correctos son `bmp_daemon_msglog_file` (NO `bmp_log_file` ni `bmp_log_output` — esos generan warnings de "Unknown key")
- Sin dump, pmbmpd solo registra cambios incrementales, que es lo que ODIN necesita para alertar

### Paso 4 — Docker Compose

```bash
cat > /opt/pmacct/docker-compose.yml << 'EOF'
services:
  pmbmpd:
    restart: unless-stopped
    container_name: pmbmpd
    image: pmacct/pmbmpd:latest
    init: true
    ports:
      - "5000:5000"
    volumes:
      - ./config/pmbmpd.conf:/etc/pmacct/pmbmpd.conf:ro
      - ./data/bmp-logs:/data/bmp-logs
    environment:
      - LC_ALL=en_US.UTF-8
      - LANG=en_US.UTF-8

  bmp-ingester:
    build:
      context: .
      dockerfile: Dockerfile.ingester
    restart: unless-stopped
    container_name: bmp-ingester
    volumes:
      - ./data/bmp-logs:/opt/pmacct/data/bmp-logs:ro
    network_mode: host
EOF
```

### Paso 5 — Script de ingesta a ClickHouse

```bash
cat > /opt/pmacct/bmp-to-clickhouse.py << 'PYEOF'
#!/usr/bin/env python3
import json, subprocess, requests, time, sys

CLICKHOUSE = "http://198.51.100.37:8123/"
TABLE = "bmp_events"
BMP_FILE = "/opt/pmacct/data/bmp-logs/bmp-events-198_51_100_42.json"
BATCH_SIZE = 500

def insert_batch(rows):
    if not rows:
        return
    values = []
    for r in rows:
        values.append("({ts},'{lt}',{afi},{safi},'{pfx}','{nh}','{asp}','{comms}','{lcomms}','{orig}',{lp},{med},'{peer}','{rtr}','{mt}')".format(
            ts="parseDateTimeBestEffort('{0}')".format(r.get('timestamp','')),
            lt=r.get('log_type',''),
            afi=r.get('afi',0),
            safi=r.get('safi',0),
            pfx=r.get('ip_prefix',''),
            nh=r.get('bgp_nexthop',''),
            asp=r.get('as_path','').replace("'","\\'"),
            comms=r.get('comms','').replace("'","\\'"),
            lcomms=r.get('lcomms','').replace("'","\\'"),
            orig=r.get('origin',''),
            lp=r.get('local_pref',0),
            med=r.get('med',0),
            peer=r.get('peer_ip',''),
            rtr=r.get('bmp_router',''),
            mt=r.get('bmp_msg_type','')
        ))
    sql = "INSERT INTO {t} (timestamp,log_type,afi,safi,ip_prefix,bgp_nexthop,as_path,comms,lcomms,origin,local_pref,med,peer_ip,bmp_router,bmp_msg_type) VALUES {v}".format(
        t=TABLE, v=",".join(values))
    try:
        resp = requests.post(CLICKHOUSE, data=sql)
        if resp.status_code != 200:
            print(f"ERROR: {resp.text}", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)

# Tail -f del archivo
proc = subprocess.Popen(['tail', '-F', BMP_FILE], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
batch = []
last_flush = time.time()

print(f"BMP→ClickHouse ingester started, watching {BMP_FILE}")

for line in iter(proc.stdout.readline, b''):
    try:
        row = json.loads(line.decode().strip())
        if row.get('log_type') in ('update', 'withdraw', 'peer_up', 'peer_down'):
            batch.append(row)
    except:
        continue

    if len(batch) >= BATCH_SIZE or (time.time() - last_flush > 5 and batch):
        insert_batch(batch)
        batch = []
        last_flush = time.time()
PYEOF
chmod +x /opt/pmacct/bmp-to-clickhouse.py
```

### Paso 6 — Dockerfile del ingester

```bash
cat > /opt/pmacct/Dockerfile.ingester << 'EOF'
FROM python:3.11-slim
RUN pip install requests
COPY bmp-to-clickhouse.py /app/ingester.py
CMD ["python3", "-u", "/app/ingester.py"]
EOF
```

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

### Paso 8 — Levantar

```bash
cd /opt/pmacct
docker compose up -d --build
```

### Paso 9 — Rotación y control de disco

**Cron para truncar JSON cada hora** (el ingester ya metió los datos en ClickHouse):

```bash
cat > /etc/cron.hourly/truncate-bmp << 'EOF'
#!/bin/bash
FILE=/opt/pmacct/data/bmp-logs/bmp-events-198_51_100_42.json
# Guardar últimas 100 líneas por si el ingester está leyendo
tail -100 "$FILE" > "${FILE}.tmp"
mv "${FILE}.tmp" "$FILE"
EOF
chmod +x /etc/cron.hourly/truncate-bmp
```

**Logrotate como respaldo:**

```bash
cat > /etc/logrotate.d/pmbmpd << 'EOF'
/opt/pmacct/data/bmp-logs/bmp-events-*.json {
    daily
    rotate 30
    compress
    missingok
    notifempty
    copytruncate
}
EOF
```

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
├── Dockerfile.ingester         ← Imagen del ingester Python
├── bmp-to-clickhouse.py        ← Script de ingesta
├── config/
│   └── pmbmpd.conf             ← Config del colector BMP
└── data/
    └── bmp-logs/
        └── bmp-events-198_51_100_42.json  ← Buffer temporal (truncado cada hora)
```

---

## Comandos útiles

```bash
# Ver logs del colector
docker logs pmbmpd --tail 20

# Ver si el ingester está insertando
docker logs bmp-ingester --tail 5

# Reiniciar
cd /opt/pmacct && docker compose restart

# Truncar manualmente el JSON
truncate -s 0 /opt/pmacct/data/bmp-logs/bmp-events-198_51_100_42.json

# Verificar tamaño del archivo
ls -lh /opt/pmacct/data/bmp-logs/

# Contar líneas (eventos acumulados)
wc -l /opt/pmacct/data/bmp-logs/bmp-events-*.json
```

---
