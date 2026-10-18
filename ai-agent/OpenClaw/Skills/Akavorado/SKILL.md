---
name: akvorado
description: Consultar trafico de red via Akvorado/ClickHouse. Usar cuando pregunten sobre trafico por ASN, PE, interfaz, proveedor, cliente, IP publica, top talkers, distribucion transit/peer, o flows.
---

# Akvorado — ClickHouse

Query: `curl -s "http://198.51.100.37:8123/" --data-binary "SQL FORMAT JSON"`

CRITICO: volumen real = `sum(Bytes*SamplingRate)`. Siempre multiplicar.

## Tablas
| Tabla | Uso | Tiene IPs |
|---|---|---|
| flows | IPs, puertos, AS-path, communities | si |
| flows_1m0s | ultima hora | no |
| flows_5m0s | ultimo dia | no |
| flows_1h0m0s | semanas/meses | no |
| exporters | inventario PEs e interfaces | - |
| asns | nombres de ASN | - |

REGLA: si necesitas IP/puerto/AS-path/communities → tabla `flows`. Si no → flows_Xm0s segun rango.

## Descubrimiento (SIEMPRE primero, nunca asumir nombres)
```sql
-- PEs activos
SELECT DISTINCT ExporterName FROM exporters ORDER BY ExporterName
-- Interfaces de un PE
SELECT DISTINCT IfName, IfDescription, IfConnectivity, IfProvider, IfBoundary, IfSpeed FROM exporters WHERE ExporterName='PE' AND IfName != '' ORDER BY IfName
-- Proveedores externos
SELECT DISTINCT IfProvider, IfConnectivity, ExporterName FROM exporters WHERE IfBoundary='external' AND IfProvider != '' ORDER BY IfProvider
-- Clientes/tenants activos
SELECT DISTINCT DstNetTenant, DstNetSite FROM flows_1m0s WHERE DstNetTenant != '' AND TimeReceived > now() - INTERVAL 1 HOUR GROUP BY DstNetTenant, DstNetSite ORDER BY DstNetTenant
-- ASNs
SELECT * FROM asns
```

## Queries agregadas (tablas flows_Xm0s)

Patron base: `SELECT campos, sum(Bytes*SamplingRate) as total_bytes FROM flows_Xm0s WHERE filtros AND TimeReceived > now() - INTERVAL X GROUP BY campos ORDER BY total_bytes DESC`

Campos disponibles: ExporterName, InIfName/OutIfName, InIfDescription/OutIfDescription, InIfConnectivity/OutIfConnectivity, InIfProvider/OutIfProvider, InIfBoundary/OutIfBoundary, SrcAS, DstAS, DstCountry, DstNetTenant, DstNetSite, EType, Proto, Packets.

JOIN para nombres ASN: `LEFT JOIN asns a ON DstAS = a.asn` → `any(a.name) as asn_name`

Filtros comunes:
- Por PE: `ExporterName='PE'`
- Por ASN: `DstAS=NUM` o `SrcAS=NUM`
- Externos: `InIfBoundary='external' AND InIfProvider != ''`
- Por conectividad: `InIfConnectivity` (transit/peering/PNI/PIT)
- Por tenant: `DstNetTenant='NOMBRE'`
- IPv4 vs IPv6: `if(EType=2048,'IPv4','IPv6') as version`

Tendencias: usar `toStartOfHour(TimeReceived)` o `toDate(TimeReceived)` como GROUP BY.

Comparar periodos: `UNION ALL` con `TimeReceived > today()` vs `TimeReceived BETWEEN today()-1 AND today()`.

## Queries por IP (tabla flows)

IPs en formato IPv6. IPv4 se busca asi: `toIPv6('::ffff:1.2.3.4')`
Mostrar limpia: `replaceRegexpOne(CAST(SrcAddr,'String'),'^::ffff:','') as src_ip`
Rango /24: `BETWEEN toIPv6('::ffff:x.x.x.0') AND toIPv6('::ffff:x.x.x.255')`

Campos adicionales en flows: SrcAddr, DstAddr, SrcPort, DstPort, DstASPath, DstCommunities.

Ejemplos de filtro:
- IP especifica: `SrcAddr = toIPv6('::ffff:IP') OR DstAddr = toIPv6('::ffff:IP')`
- Que envia una IP: `SrcAddr = toIPv6(...)` → agrupar por DstAS, DstPort, Proto
- Que recibe una IP: `DstAddr = toIPv6(...)` → agrupar por SrcAS, SrcPort, Proto
- Top talkers: agrupar por dst_ip o src_ip sin filtro de IP
- AS-Path: `SELECT DstASPath, ExporterName ... WHERE DstAS=NUM`
- Communities: `SELECT DstCommunities, ExporterName ... WHERE DstAS=NUM`
- IP por PE/interfaz: `SELECT ExporterName, OutIfName, OutIfDescription ... WHERE DstAddr=...`

## Conversion
- Mbps = total_bytes * 8 / segundos / 1e6
- 1 hora = 3600s. Protocolos: TCP=6, UDP=17, ICMP=1. EType: IPv4=2048, IPv6=34525.

## Reglas
- Descubrir PEs/interfaces antes de consultar
- Siempre Bytes*SamplingRate
- Convertir a Mbps/Gbps/TB al reportar
- Nunca inventar datos