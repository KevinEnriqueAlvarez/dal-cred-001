# Decisiones de arquitectura (ADR)

Cada decisión técnica relevante queda registrada con su contexto, la alternativa descartada y la razón. ADR-001 a ADR-007 se aprobaron en G2 (27-oct-2026), dentro del documento de diseño del proyecto.

| ADR | Decisión | Estado |
| --- | --- | --- |
| ADR-001 | SQL Server 2022 Developer como almacén en desarrollo y pruebas | Aprobada (G2) |
| ADR-002 | dbt Core con dbt-expectations para transformar y probar | Aprobada (G2) |
| ADR-003 | Doble destino: Airflow sobre SQL Server en local; GitHub Actions sobre DuckDB a diario | Aprobada (G2) |
| ADR-004 | Scorecard con regresión logística y WoE; gradient boosting como modelo retador | Aprobada (G2) |
| ADR-005 | Formato SIRC simulado y parametrizado | Aprobada (G2) |
| ADR-006 | Saldo mensual para 24 meses; saldo diario solo 90 días | Aprobada (G2) |
| ADR-007 | Umbrales LD y de política en tabla de parámetros | Aprobada (G2) |
| [ADR-008](ADR-008-generador-sintetico.md) | Generador sintético con riesgo latente, cadena de Markov y errores inyectados | Propuesta (PR de la actividad 3.1) |
