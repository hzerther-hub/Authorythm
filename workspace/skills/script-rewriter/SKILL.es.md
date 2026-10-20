---
name: script-rewriter
description: Metodología y normativa para reescribir una novela como guion formateado
---

# Guía de reescritura de guiones

## Principios de reescritura

1. **Conservar la trama central**: no cambiar la línea argumental principal ni las relaciones entre personajes
2. **Reforzar la visualidad**: convertir el texto narrativo en descripciones de escena visualizables
3. **Motor de diálogo**: hacer avanzar la trama con diálogos y reducir la narración
4. **Control del ritmo**: mantener cada escena entre 30-60 segundos, apta para vídeo corto
5. **Sin lenguaje de cámara**: nada de tamaños de plano, ángulos ni movimientos de cámara — eso pertenece al paso de desglose del storyboard

## Formato del guion formateado

```
## S01 | INT · Cafetería | Atardecer

La luz del atardecer se cuela por los ventanales hasta el suelo de la cafetería; el vapor se alza de las tazas de café sobre la barra.

Javier está sentado solo en un reservado del rincón, cabeza gacha sobre el teléfono, con cierto aire de ansiedad.

Suena el timbre de la puerta y Lucía la empuja para entrar. Ve a Javier y se acerca sonriendo.

Lucía: (sonriendo) ¿Has esperado mucho?
Javier: (alzando la vista) No, acabo de llegar.
```

### Reglas de formato

- `## Snúmero | INT/EXT · lugar | franja horaria` — cabecera de escena
- Párrafos naturales de descripción de acción — sin ningún lenguaje de cámara
- `NombreDelPersonaje: (estado/expresión) contenido de la réplica` — formato de diálogo

### Referencia de volumen de contenido

El guion formateado crece alrededor de un 20-30 % respecto al contenido original; el aumento viene sobre todo de las marcas de cabecera de escena y del formateo de los diálogos, no de una ampliación del texto.

## Pasos de reescritura

1. Llama primero a `read_episode_script` para leer el contenido original
2. Analiza la estructura del contenido (proporciones de diálogo, narración y monólogo interior)
3. Llama a `rewrite_to_screenplay` para ejecutar la reescritura
4. Revisa el resultado reescrito y confirma que cumple el formato del guion formateado
5. Llama a `save_script` para guardar el resultado final

## Notas

- El monólogo interior debe exteriorizarse en expresiones/acciones/decisiones del personaje o en palabras dichas en voz alta — **se prohíben la voz en off, la narración y el monólogo interior**
- Cada escena debe tener al menos dos personajes interactuando ante la cámara; no escribas una escena de una sola persona en una habitación vacía
- Cambia lugar u hora entre escenas consecutivas; no repitas la misma habitación una y otra vez
- Divide los pasajes narrativos largos en varias escenas cortas
- Asegúrate de que cada escena tiene un punto de giro emocional claro
- Mantén la coherencia del estilo de habla de cada personaje
- La numeración de escenas crece de forma consecutiva (S01, S02, S03...)
- Las franjas horarias deben ser concretas (atardecer, altas horas de la noche, madrugada); no escribas un genérico "día"
