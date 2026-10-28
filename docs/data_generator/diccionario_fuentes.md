# Diccionario de fuentes · zona Landing

> Los 98 archivos que entrega el generador, con el significado de cada columna. Montos en quetzales (GTQ), fechas en ISO 8601 (AAAA-MM-DD), tasas como fracción anual (0,21 = 21 %).

Cantidades a escala 1, con corte al 31-oct-2026.

## Resumen de archivos

| Carpeta | Archivo | Grano (una fila por) | Frecuencia | Filas |
| --- | --- | --- | --- | --- |
| `core_bancario/saldos/` | `saldos_AAAAMM.csv` | Préstamo activo y mes | Mensual (22) | 2.399.902 |
| `core_bancario/pagos/` | `pagos_AAAAMM.csv` | Pago recibido | Mensual (22) | 2.216.670 |
| `clientes/` | `clientes_20261031.csv` | Cliente o prospecto | Foto al corte | 190.138 |
| `core_bancario/prestamos/` | `prestamos_20261031.csv` | Préstamo vivo en algún momento desde ene-2025 | Foto al corte | 164.560 |
| `originacion/solicitudes/` | `solicitudes_AAAAMM.csv` | Solicitud de crédito | Mensual (22) | 87.079 |
| `core_bancario/castigos/` | `castigos_20261031.csv` | Préstamo castigado | Foto al corte | 10.904 |
| `core_bancario/garantias/` | `garantias_20261031.csv` | Garantía | Foto al corte | 4.672 |
| `contabilidad/mayor/` | `mayor_AAAAMM.csv` | Cuenta contable y mes | Mensual (22) | 132 |
| `clientes/` | `grupos_economicos_20261031.csv` | Grupo económico (unidad de riesgo) | Foto al corte | 60 |
| `catalogos/` | 5 archivos | Elemento del catálogo | Estático | 90 |
| raíz | `_manifest.json` | Archivo entregado | Por corrida | 98 entradas |

## saldos_AAAAMM.csv · extracto de cierre de mes del core

| Columna | Tipo | Descripción |
| --- | --- | --- |
| periodo | texto AAAA-MM | Mes del cierre |
| fecha_corte | fecha | Último día del mes |
| prestamo_id | texto | Préstamo (PR-0000001) |
| saldo_capital | decimal | Capital pendiente al cierre. En tarjeta, saldo utilizado |
| dias_atraso | entero | Días de atraso al cierre (0 = al día) |
| cuotas_pagadas | entero | Cuotas pagadas acumuladas. En tarjeta, meses con pago |
| limite_credito | decimal | Solo tarjeta: límite autorizado |

## pagos_AAAAMM.csv · pagos recibidos

| Columna | Tipo | Descripción |
| --- | --- | --- |
| pago_id | texto | Identificador único del pago (PG-00000001) |
| prestamo_id | texto | Préstamo al que se aplica |
| fecha_pago | fecha | Fecha de aplicación. Consumo se concentra en quincena |
| monto_pagado | decimal | Monto total recibido |
| interes | decimal | Porción aplicada a intereses |
| capital | decimal | Porción aplicada a capital (monto − interés) |
| tipo_pago | texto | Cuota · Pago de tarjeta · Pago de cuotas en mora · Abono extraordinario · Cancelación anticipada |
| canal_pago | texto | Agencia · Banca en línea · App móvil · Débito automático · Corresponsal |

## prestamos_20261031.csv · maestro de préstamos

| Columna | Tipo | Descripción |
| --- | --- | --- |
| prestamo_id | texto | Identificador del préstamo |
| cliente_id | texto | Deudor |
| producto_codigo | texto | TC · CONS · HIPO · EMP_MAYOR · EMP_MENOR · MICRO |
| solicitud_id | texto | Solicitud que lo originó; vacío en la cartera previa a 2024 |
| fecha_desembolso | fecha | Fecha de desembolso o de apertura de la tarjeta |
| monto_desembolsado | decimal | Monto desembolsado o límite de la tarjeta |
| plazo_meses | entero | Plazo pactado (0 = revolvente) |
| tasa_anual | decimal | Tasa de interés nominal anual |
| cuota | decimal | Cuota nivelada; en tarjeta, pago de referencia (3 % del límite) |
| canal_codigo | texto | Canal de originación (AGE, DIG, FVE, BEM) |
| politica_id | texto | Versión de política con la que se aprobó |
| origen | texto | stock_inicial · originacion |
| estado_final | texto | Activo · Cancelado · Castigado (al corte) |
| fecha_fin | fecha | Fecha de cancelación o castigo |
| saldo_castigado | decimal | Capital castigado, si aplica |
| agencia_codigo | texto | Agencia del cliente |

## solicitudes_AAAAMM.csv · flujo de originación

| Columna | Tipo | Descripción |
| --- | --- | --- |
| solicitud_id | texto | Identificador (SOL-0000001) |
| fecha_ingreso | fecha y hora | Ingreso de la solicitud |
| cliente_id | texto | Solicitante |
| producto_codigo, canal_codigo, analista_codigo | texto | Producto, canal y analista asignado |
| monto_solicitado, plazo_meses, tasa_anual, cuota_estimada | número | Condiciones solicitadas |
| ingreso_mensual_declarado | decimal | Ingreso (personas) o ventas mensuales (empresas) |
| atraso_max_sirc_12m | entero | **Carácter.** Máximo atraso en el SIRC en los últimos 12 meses (días) |
| entidades_con_deuda_sirc | entero | **Carácter.** Entidades con deuda vigente en el SIRC |
| endeudamiento_sirc_meses_ingreso | decimal | **Capital.** Deuda total en el SIRC expresada en meses de ingreso |
| relacion_cuota_ingreso | decimal | **Capacidad.** Cuota estimada ÷ ingreso mensual |
| antiguedad_laboral_meses | entero | **Condiciones.** Estabilidad del ingreso |
| metodo_decision | texto | Criterio del analista · Scorecard SC-CONS v1.0 |
| puntaje_decision | entero | Puntaje con el que se decidió (escala del scorecard) |
| score_sc_cons_v1 | entero | Puntaje del scorecard; solo TC y CONS desde el go-live |
| politica_id, corte_politica | texto, entero | Política vigente y su corte de score |
| es_excepcion, aprobador_excepcion | booleano, texto | Aprobada bajo el corte y quién la autorizó |
| decision | texto | Aprobada · Rechazada · Desistida · En análisis |
| monto_aprobado | decimal | Monto aprobado |
| fecha_resolucion | fecha y hora | Resolución; vacío si sigue en análisis al corte |
| expediente_completo | booleano | Checklist de documentos completo (OB-05) |
| screening_ld_realizado | booleano | Se revisaron listas y PEP antes de resolver (OB-06) |
| coincidencia_listas | booleano | Coincidencia en listas de sanciones o restrictivas |
| enganche_efectivo_gtq | decimal | Hipotecario: enganche pagado en efectivo |
| origen_fondos_documentado | booleano | Hipotecario: se documentó el origen del efectivo |

## clientes_20261031.csv

| Columna | Tipo | Descripción |
| --- | --- | --- |
| cliente_id | texto | Identificador (CL-0000001) |
| tipo_persona | texto | Individual · Jurídica |
| nombre | texto | Nombre inventado (persona) o razón social inventada (empresa) |
| dpi | texto | CUI de 13 dígitos terminado en 9999 (departamento y municipio inexistentes: no puede ser real) |
| nit | texto | NIT inventado (empresas) |
| fecha_nacimiento | fecha | Personas |
| departamento, region, agencia_codigo | texto | Ubicación |
| tipo_empleo | texto | Asalariado · Independiente · Profesional |
| ingreso_mensual | decimal | Ingreso o ventas mensuales |
| sector | texto | Empresas: actividad económica |
| grupo_economico_id | texto | Unidad de riesgo a la que pertenece |
| es_pep | booleano | Persona expuesta políticamente |
| fecha_alta | fecha | Alta como cliente o prospecto |

## Otros archivos

- **garantias_20261031.csv:** garantia_id, prestamo_id, tipo_garantia (Hipotecaria · Prendaria · Fiduciaria), valor_avaluo, fecha_avaluo. Solo para hipotecario y empresarial.
- **castigos_20261031.csv:** prestamo_id, fecha_castigo, saldo_castigado.
- **mayor_AAAAMM.csv:** periodo, fecha_corte, cuenta_contable, producto_codigo, saldo_contable. Difiere de la suma de saldos en menos de 0,004 % por partidas en tránsito.
- **grupos_economicos_20261031.csv:** grupo_economico_id, grupo_nombre, sector.
- **catalogos/:**
  - `productos.csv`: código, nombre, familia, segmento según JM-47-2022, cuenta contable.
  - `agencias.csv`: 55 agencias con departamento y región.
  - `canales.csv`.
  - `analistas.csv`: código y nivel de autorización.
  - `politicas.csv`: versión, corte de score y relación cuota/ingreso máxima, con vigencia.
- **_manifest.json:** por archivo, filas, hash SHA-256 y hora de llegada. El SLA de llegada son las 06:00 del día siguiente al cierre.
