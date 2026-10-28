## Qué cambia

<!-- Una o dos frases: qué hace este cambio y por qué. -->

## Actividad del plan

- Actividad: <!-- ej. 3.1 Generador sintético -->
- Obligaciones que toca (OB-xx): <!-- o "ninguna" -->

## Cómo probarlo

```bash
pip install -e ".[dev]"
pytest
```

## Checklist de revisión (segunda línea)

- [ ] El CI está en verde (estilo, pruebas y escaneo de secretos)
- [ ] No hay datos reales, credenciales ni nombres de entidades reales
- [ ] Los supuestos nuevos están documentados en `docs/`
- [ ] Las decisiones de arquitectura nuevas tienen su ADR
- [ ] El cambio es reproducible (misma semilla, mismos datos)

## Segregación de funciones

| Rol | Quién | Acción |
| --- | --- | --- |
| Elabora | <!-- quien abre el PR --> | Abre el pull request |
| Revisa y aprueba | Kevin Enrique Alvarez (dueño de producto) | Revisa el checklist y hace el merge |
