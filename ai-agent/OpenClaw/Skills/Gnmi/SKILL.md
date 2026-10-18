---
name: gnmic_metrics
description: Consultar métricas gNMIc vía /metrics. Usar para contadores de tráfico de interfaces y actividad BGP (UPDATEs).
---

# gNMIc Metrics

Endpoint Prometheus text format: `curl -s http://odin.example.net:9804/metrics`

Patrón de consulta: `curl -s URL | grep '^METRICA{' | grep 'source="PE"'`

## Métricas
Interfaces (prefijo `interfaces_interface_state_counters_`):
- `in_octets`, `out_octets`, `in_pkts`, `out_pkts`

BGP (prefijo `network_instances_network_instance_protocols_protocol_bgp_neighbors_neighbor_state_messages_`):
- `received_UPDATE`, `sent_UPDATE`

## Labels clave
- `source` — PE (filtrar siempre)
- `interface_name` — para interfaces
- `neighbor_neighbor_address` — para BGP

## Descubrimiento
```sh
# Métricas disponibles
curl -s http://odin.example.net:9804/metrics | grep -E '^[a-zA-Z_]' | cut -d'{' -f1 | sort -u
# Sources/PEs activos
curl -s http://odin.example.net:9804/metrics | grep -oP 'source="\K[^"]+' | sort -u
```

## Reglas
- No asumir métricas; descubrir primero con el comando de arriba
- Siempre filtrar por source
- Datos son counters monotónicos (no rates)