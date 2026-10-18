---
name: graylog
description: Consultar logs de PEs Arista EOS via API REST de Graylog. Usar cuando pregunten sobre estado de la red, eventos BGP, interfaces, cambios de config o cualquier log de los equipos.
---

# Graylog — Logs de PEs Arista

REGLA: ejecutar curl ANTES de responder. Nunca inventar datos.

## Comando
```sh
curl -s -u TOKEN:token -H "Accept: application/json" -H "X-Requested-By: ODIN" "http://198.51.100.43:9000/api/search/universal/relative?query=QUERY&range=SECONDS&limit=20"
```

query usa Lucene URL-encoded. range en segundos (300=5min, 3600=1h, 86400=24h). Combinar con AND/OR/NOT.

## Queries
- Estado red: query=arista_severity%3A%3C4
- BGP events: query=arista_facility%3ABGP
- BGP caidas: query=arista_mnemonic%3AADJCHANGE
- Interfaces down: query=interface_state%3Adown
- PE especifico: query=source%3ANOMBRE_PE
- Config changes: query=arista_facility%3ASYS
- Peer BGP: query=bgp_neighbor_ip%3AIP_AQUI
- Todos recientes: query=*

## Campos en resultados (results[].message)
source (PE), timestamp, arista_event, arista_facility, arista_severity (0=emergencia..7=debug), arista_mnemonic, bgp_neighbor_ip, bgp_vrf, bgp_remote_asn, bgp_state, interface_name, interface_state, config_user, message