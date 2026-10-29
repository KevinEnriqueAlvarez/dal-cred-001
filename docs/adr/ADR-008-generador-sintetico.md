# ADR-008 · Generador sintético con riesgo latente, cadena de Markov y errores inyectados

- **Estado:** Aprobada (merge del PR #1, 28-oct-2026)
- **Fecha:** 28-oct-2026
- **Decide:** Arquitecto e ingeniero de datos · **Aprueba:** Dueño de producto

## Contexto

El proyecto necesita 24 meses de datos de cartera con cuatro propiedades:

1. Comportamiento creíble para un analista de riesgo: cosechas que suben con la madurez, estacionalidad de pagos, curas y castigos.
2. Un efecto del proyecto medible con un grupo de control.
3. Una causa de deterioro detectable: la política P-07.
4. Errores conocidos para probar la calidad por capa.

No se pueden usar datos reales.

## Decisión

1. **Riesgo latente por cliente (`z`).** Un solo número oculto explica el comportamiento. Las variables observables son `z` más ruido, de modo que un scorecard discrimina sin ser perfecto (Gini 0,43).
2. **Cadena de Markov mensual por tramos de mora.** Se vectoriza sobre todos los créditos con numpy: 2,4 millones de filas de saldo en unos 100 segundos.
3. **Un año de "burn-in" (2024) que no se publica.** Así la cartera llega a enero de 2025 con una mezcla realista de mora y de cosechas.
4. **El efecto del proyecto entra por mecanismos, no por cifras fijas.** El scorecard mejora la selección y las alertas mejoran la cura. Los indicadores resultan de la simulación y no se escriben a mano.
5. **Errores inyectados con lista de control separada.** El pipeline nunca lee `_control/`.
6. **Todo parámetro en YAML con una semilla única.** Más un manifiesto con hash SHA-256 por archivo.

## Alternativas descartadas

| Alternativa | Por qué se descartó |
| --- | --- |
| Datos públicos de scoring (Home Credit, Lending Club) como base | No tienen la estructura de un banco guatemalteco (segmentos JM-47-2022, SIRC, quetzales) ni 24 meses de saldos. Se reservan para validar el método del scorecard en F4 |
| Faker puro con distribuciones independientes | No produce cosechas, transiciones ni relación entre riesgo y comportamiento; las vistas de diagnóstico no tendrían nada que mostrar |
| Escribir las cifras objetivo directamente (mora por mes fija) | El efecto no sería auditable ni reproducible por mecanismo; un revisor detectaría datos "hechos a la medida" |
| Simular día a día | El volumen sube unas 30 veces sin aportar a las preguntas mensuales (coherente con ADR-006) |

## Consecuencias

- **Positivas:** reproducible al byte; calibrado contra cifras públicas; cada efecto tiene una causa explicable en entrevista; los errores permiten medir la calidad con un valor esperado conocido.
- **Negativas:**
  - Los datos completos pesan 344 MB y no se versionan en Git; se regeneran con el comando.
  - La mora se modela por tramos y no por cuota.
  - Las líneas base del charter deben ajustarse a la calibración (O3: 2,60 %).
