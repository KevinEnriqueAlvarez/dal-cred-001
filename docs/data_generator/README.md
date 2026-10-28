# Generador de datos sintéticos · Actividad 3.1

> Produce los 24 meses de datos de Banco Cumbre, S.A. (ficticio) que alimentan toda la plataforma: 98 archivos, unos 5 millones de filas y Q4.754 millones de cartera al corte. Corre en unos 100 segundos y la misma semilla da siempre los mismos datos.

## Para qué existe

Un proyecto de riesgo de crédito necesita datos con la estructura, el volumen y los problemas de un banco real. Usar datos reales de un banco no es posible: son confidenciales y están protegidos por la Ley de Bancos y Grupos Financieros. Este generador simula los sistemas que, en un banco, entregarían esos datos:

| Sistema simulado | Archivos que entrega |
| --- | --- |
| Core bancario | Préstamos, saldos de cierre de mes, pagos, garantías y castigos |
| Flujo de originación | Solicitudes de crédito con su decisión y controles |
| Gestión de clientes | Clientes, grupos económicos |
| Contabilidad | Mayor contable de las cuentas de cartera |
| Catálogos | Productos, agencias, canales, analistas, políticas de crédito |

## Cómo correrlo

```bash
pip install -e ".[dev]"
python -m data_generator                    # banco completo en ./data (~100 s, 344 MB)
python -m data_generator --escala 0.05      # versión pequeña para probar rápido
python -m data_generator.calibracion        # reporte de calibración contra los objetivos
pytest                                      # pruebas automáticas (escala 0,02)
pytest -m calibracion                       # prueba lenta de objetivos de negocio (escala 0,3)
```

Los datos generados no se suben al repositorio (`data/` está en `.gitignore`): se reconstruyen idénticos con el comando.

## Cómo funciona

```
parametros.yaml
      │
      ▼
 1. Catálogos ─► 2. Clientes ─► 3. Originación ─► 4. Simulación de cartera ─► 5. Contabilidad
                  (riesgo z)     (5 C's, score,     (Markov mes a mes:         (mayor, garantías,
                                  política)          mora, pagos, castigos)     castigos)
                                                                │
                                                                ▼
                                          6. Errores inyectados ─► 7. Landing + manifiesto
```

| Paso | Módulo | Qué hace |
| --- | --- | --- |
| 1 | `catalogos.py` | Productos, 55 agencias en 17 departamentos, canales, 18 analistas, versiones de política |
| 2 | `clientes.py` | Personas y empresas, cada una con un riesgo latente `z` que no se publica |
| 3 | `originacion.py` | Solicitudes con variables de las 5 C's; decisión por criterio del analista (2025) o por scorecard (2026) |
| 3b | `scorecard_referencia.py` | Tabla de puntos SC-CONS v1.0 que el banco pone en producción el 1-ene-2026 |
| 4 | `cartera.py` | Cada crédito avanza mes a mes entre tramos de mora; amortiza, paga, se cura, se cancela o se castiga |
| 5 | `contabilidad.py` | Mayor contable con partidas en tránsito; garantías; castigos |
| 6 | `errores.py` | Daña una parte de los datos a propósito y guarda la lista exacta |
| 7 | `escritura.py` | Un CSV por fuente y mes, con hash SHA-256 y hora de llegada en `_manifest.json` |

### El riesgo latente `z`

Cada cliente tiene un número `z` (normal estándar; mayor = más riesgo) que explica su comportamiento de pago. Las variables que el banco sí ve (atraso en el SIRC, endeudamiento, antigüedad laboral, relación cuota/ingreso) se calculan como `z` más ruido. Así pasa en la realidad: las variables dan pistas del riesgo, pero no lo revelan completo. Por eso ningún scorecard es perfecto: el de referencia logra un **Gini de 0,43**.

`z` nunca sale en los archivos. Las pruebas verifican que ninguna columna interna se publique.

### La cadena de mora

Cada mes, un crédito al día cae en mora con una probabilidad que depende de:

- **Producto:** `riesgo_base`, de 0,6 % mensual en hipotecario y empresarial mayor a 2,2 % en microcrédito.
- **Cliente:** el factor `exp(0,7 × z)`.
- **Madurez:** los primeros meses de tarjeta, consumo y microcrédito tienen menos riesgo, por eso la curva de cosecha sube.
- **Mes calendario:** julio (Bono 14) y diciembre (aguinaldo) mejoran el pago; enero y febrero lo empeoran.

Un crédito en mora puede curarse, avanzar de tramo o quedarse. Tras 6 meses en 90+ días se castiga y sale de la cartera.

### Cómo se simula el efecto del proyecto

El proyecto entra en producción el 1-ene-2026. A partir de esa fecha cambian tres cosas, todas declaradas como **efecto simulado**:

1. **Scorecard en tarjeta y consumo.** La decisión deja de depender del criterio del analista, que tiene ruido y sesgo personal, y pasa al puntaje SC-CONS v1.0. Se aprueba con mejor selección y las cosechas nuevas salen mejores.
2. **Alertas tempranas para cobros.** La cura de los tramos 1–30 y 31–60 días mejora un 20 %.
3. **Proceso de originación.** El tiempo de respuesta baja de 72 a 30 horas en seis meses, el expediente completo sube de 93 % a 99,5 % y la cobertura del screening LD sube de 86 % a 100 %.

El hipotecario no recibe el scorecard. Sirve como **grupo de control** para medir el efecto con diferencia en diferencias.

### El caso de la política P-07

El 15-abr-2026 el banco relaja la política de tarjeta: baja el corte de score de 600 a 560 y lanza una campaña digital de "aprobación inmediata" que atrae solicitantes más riesgosos. Es la causa que la vista 3 debe detectar. La cosecha de junio de 2026 sale al doble de la media de 2025 a 4 meses de antigüedad (3,4 % contra 1,5 %), y la de mayo queda en el límite de la banda.

## Errores inyectados

| Error | Cantidad (escala 1) | Dimensión | Lo debe detectar |
| --- | --- | --- | --- |
| Pagos duplicados (mismo `pago_id`) | 2.214 | Unicidad | Silver, prueba de llave única |
| Pagos con fecha imposible (1900, 2099, 30 de febrero) | 214 | Validez | Silver, prueba de rango de fechas |
| Saldos de capital negativos | 48 | Validez | Silver, prueba de rango |
| Clientes individuales sin DPI | 753 | Completitud | Silver, prueba not null |
| DPI con formato inválido | 37 | Validez | Silver, prueba de formato (13 dígitos) |
| Mismo cliente con dos códigos | 20 | Unicidad | Silver, deduplicación por DPI |
| Desembolsos ligados a solicitud rechazada | 3 | Control OB-05 | Gold, prueba de integridad de originación |
| Solicitudes de oct-2026 llegan 06:42 (SLA 06:00) | 1 archivo | Oportunidad | Monitor de cierre, frescura |

La lista exacta de registros dañados queda en `data/_control/errores_inyectados.json`. El pipeline nunca lee esa carpeta; solo las pruebas la usan para confirmar que se detectó cada error.

## Reproducibilidad

- Una sola semilla (`semilla: 20260101`) controla todo el azar. Los errores usan una semilla derivada, así que cambiar los errores no altera los datos limpios.
- Cada archivo queda registrado en el manifiesto con su hash SHA-256. Si un archivo cambia un solo byte, el hash lo delata.
- La prueba `test_misma_semilla_mismos_datos` genera dos veces y exige resultados idénticos.

## Limitaciones conocidas

- La mora se modela por tramos de 30 días y no por cuota. Los intereses moratorios no se acumulan en el saldo de los créditos a plazo.
- "Vencido" se aproxima como más de 90 días de atraso. La regla exacta de traslado a cartera vencida se aplica en Silver.
- El formato de los archivos imita la estructura típica de un core bancario; no es el formato oficial de ningún sistema ni del SIRC.
- Las cifras de calibración aproximan el sistema bancario guatemalteco, pero Banco Cumbre no representa a ninguna entidad real.

Ver también: [diccionario de fuentes](diccionario_fuentes.md) · [calibración](calibracion.md) · [ADR-008](../adr/ADR-008-generador-sintetico.md)
