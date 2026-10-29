# Calibración del generador

> Los datos reproducen un banco mediano guatemalteco: Q4.754 millones de cartera al 31-oct-2026, con crecimiento de 10,7 % anual. La mora 30+ baja de 3,8 % en enero de 2025 a 3,15 % al corte, en línea con el sistema bancario, que cerró junio de 2026 con 2,63 % de mora general.

Resultados de la corrida completa (escala 1, semilla 20260101). El archivo `data/_control/calibracion.json` los recalcula en cada corrida.

## Referencias públicas usadas

| Referencia | Valor | Fuente |
| --- | --- | --- |
| Mora general del sistema bancario, jun-2026 | 2,63 % (bajó desde 2,76 %) | SIB, citada por [La Hora, 3-ago-2026](https://lahora.gt/lh-economia/esmith/2026/08/03/sistema-financiero-crece-la-mora-en-tarjetas-de-credito-supera-el-43-y-la-provincia-inquieta-now/) |
| Crecimiento de la cartera bancaria, ene–jun 2026 | 2,25 % en el semestre | Misma fuente |
| Cartera con plazo mayor a 72 meses | 44,71 % | Misma fuente |
| Cartera vencida y cobertura de un grupo grande, jun-2026 | CVC 1,45 %; cobertura 99,53 % | [BAC Credomatic, indicadores del grupo financiero](https://www.baccredomatic.com/sites/default/files/2026-07/gt_indicadores_grupo_financiero_0626.pdf) |
| Estructura de la publicación de activos por categoría A–E | Segmentos JM-47-2022 | [Banco Promerica, publicación feb-2024](https://bancopromerica.com.gt/media/772733/publicacion-febrero-2024.pdf) |

Banco Cumbre tiene la mora algo arriba del sistema a propósito. El caso de negocio es un banco que necesita mejorar, y su mezcla tiene más tarjeta y consumo que el promedio.

## Resultados contra objetivos

| Indicador | Objetivo | Resultado | Estado |
| --- | --- | --- | --- |
| Cartera al corte | ≈ Q4.800 M | Q4.754 M | ✅ |
| Crecimiento anual (oct-2026 vs oct-2025) | ≈ 9 % | 10,7 % | ✅ |
| Participación de tarjeta | 22 % | 22,3 % | ✅ |
| Participación de consumo | 31 % | 29,9 % | ✅ |
| Participación de hipotecario | 29 % | 30,0 % | ✅ |
| Participación de empresarial mayor | 12 % | 12,5 % | ✅ |
| Participación de empresarial menor | 4 % | 4,0 % | ✅ |
| Participación de microcrédito | 2 % | 1,3 % | ⚠️ Bajo, sin efecto en los casos de uso |
| Mora 30+ total, línea base (ene-2025) | 3,5 %–4,0 % | 3,81 % | ✅ |
| Mora 30+ total al corte (oct-2026) | Menor que oct-2025 | 3,15 % (oct-2025: 3,54 %) | ✅ |
| Gini del score de referencia, cosechas 2025 | ≥ 0,40 | 0,43 | ✅ |
| Concentración del grupo G-014 | ≈ 4,2 % | 4,10 % (top 20 grupos: 8,9 %) | ✅ |

## Mora 30+ por producto (% del saldo)

| Producto | ene-2025 | oct-2025 | oct-2026 |
| --- | --- | --- | --- |
| Tarjeta de crédito | 6,72 % | 6,97 % | 6,01 % |
| Consumo | 5,05 % | 4,76 % | 4,03 % |
| Hipotecario | 1,09 % | 1,10 % | 1,02 % |
| Empresarial mayor | 1,72 % | 0,31 % | 1,23 % |
| Empresarial menor | 3,42 % | 2,89 % | 2,32 % |
| Microcrédito | 7,43 % | 6,08 % | 4,45 % |
| **Total** | **3,81 %** | **3,54 %** | **3,15 %** |

Empresarial mayor varía mucho de un mes a otro porque son pocos créditos grandes: un solo deudor mueve el indicador.

## Efecto simulado del proyecto

| Medida | 2025 (antes) | 2026 (después) |
| --- | --- | --- |
| Mora 30+ a 6 meses, cosechas de tarjeta y consumo (grupo tratado) | 2,60 % | 2,23 % |
| Mora 30+ a 6 meses, cosechas hipotecarias (grupo control) | 0,68 % | 0,58 % |
| Tasa de aprobación (todas las solicitudes) | 72,1 % | 75,2 % |
| Horas de respuesta, mediana | 73 h | 42 h (30 h desde julio) |
| Expedientes completos | 92,9 % | 99,5 % |
| Screening LD antes de resolver | 86 % | 100 % |

Diferencia en diferencias del objetivo O3: (2,23 − 2,60) − (0,58 − 0,68) = **−0,27 puntos**, atribuibles al scorecard. La política P-07 se come parte de la mejora. La vista 5 lo mostrará así.

**Ajuste al charter.** Las líneas base de O3 del charter (4,8 % → 3,8 %) eran ilustrativas y anteriores a la calibración. Con los datos generados, la línea base real de O3 es **2,60 %**. Una meta equivalente (−20 %) sería **2,08 %**. Ajuste aprobado por el patrocinador el 28-oct-2026 y registrado en el charter.

## Cosechas de tarjeta a 4 meses (detección de P-07)

| Cosechas | Mora 30+ a 4 MOB |
| --- | --- |
| 2025, media (banda: media ± 1 desviación) | 1,52 % (1,13 %–1,91 %) |
| ene–mar 2026 (scorecard, antes de P-07) | 1,19 % · 1,43 % · 1,55 % |
| abr-2026 (P-07 desde el día 15) | 1,62 % |
| may-2026 | 1,93 % (en el límite de la banda) |
| jun-2026 | **3,43 % (fuera de banda: 2,3 veces la media)** |

La cosecha de junio llega a 4 meses en octubre de 2026. La alerta de la vista 3 la detecta con el cierre de octubre, antes de que su mora 90+ suba.
