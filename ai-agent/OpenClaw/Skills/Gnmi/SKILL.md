---
name: gnmic_metrics
description: Consultar métricas gNMIc vía /metrics. Usar para contadores de tráfico de interfaces y actividad BGP (UPDATEs).
---

# gNMIc Metrics

## ESTADO: ejecución autónoma deshabilitada

No ejecutar curl/grep contra el endpoint de métricas desde el agente. Este Skill queda como referencia de métricas y labels hasta que exista un cliente acotado (fase P3 de `docs/refactor/PLAN.md`). Si preguntan por estas métricas, responder que la fuente gNMI no está habilitada para consultas del agente. Nunca interpolar texto del operador en grep ni en shell.

Endpoint Prometheus text format: configurado por el administrador fuera del Skill; no incluir IPs ni hostnames aquí.

## Métricas
Interfaces (prefijo `interfaces_interface_state_counters_`):
- `in_octets`, `out_octets`, `in_pkts`, `out_pkts`

BGP (prefijo `network_instances_network_instance_protocols_protocol_bgp_neighbors_neighbor_state_messages_`):
- `received_UPDATE`, `sent_UPDATE`

## Labels clave
- `source` — PE (filtrar siempre)
- `interface_name` — para interfaces
- `neighbor_neighbor_address` — para BGP

## Reglas
- No asumir métricas; las listadas son referencia, confirmar con el cliente cuando exista
- Siempre filtrar por source
- Datos son counters monotónicos (no rates)