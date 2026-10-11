---
name: storyboard-breaker
description: Normativa profesional del desglose de storyboard — divide el guion en segmentos de storyboard capaces de albergar varios sub-planos
---

# Guía de desglose de storyboard

## Definición central: segmento de storyboard

Un storyboard = un **segmento de storyboard** = una tarea de generación de vídeo.

- Cada segmento dura **8-15 segundos** y alberga internamente **2-4 sub-planos**
- Entre sub-planos **se puede cortar**: cambiar tamaño de plano, ángulo u objeto filmado, enlazando con corte en seco
- Los sub-planos **no cruzan de escena**: un segmento ocurre dentro de una única escena (`scene_id` es un vínculo a nivel de segmento)
- Cada sub-plano dura 2-6 segundos y se centra en una unidad visual (una acción, una reacción, un primerísimo primer plano)

## Proceso de desglose (cuatro pasos)

2. **Identificación de beats**: identifica primero los beats narrativos del guion — las marcas 【开场】【触发】【高潮】【收尾】 presentes en el guion, o los puntos de giro narrativos (cambio de lugar, revelación de una regla, explosión emocional, giro). **El límite de un beat obliga a cortar el segmento**; los sub-planos de un mismo beat entran preferentemente en el mismo segmento, y no disperses una cadena causal (preparación-ocurrencia-reacción) por segmentos distintos
3. **Anclaje del volumen total**: duración total objetivo = número de caracteres del guion ÷ 500 caracteres/minuto; número de segmentos ≈ duración total objetivo ÷ 12 segundos, con una tolerancia de ±20 %. No te pases ni te quedes claramente corto

## Duraciones por capa de ritmo

Fija la duración según la función del segmento, sin aplicarle la misma medida a todo:

| Tipo de segmento | Duración | Notas |
|---|---|---|
| Segmento de transición | 8-10 segundos | Desplazamientos, planos vacíos, establecimiento del entorno, transiciones |
| Segmento narrativo | 10-15 segundos | Avance argumental normal, diálogo |
| Segmento de punto de explosión | 12-15 segundos | Primerísimos primeros planos, revelación de reglas, explosión emocional, giros; el ritmo de los sub-planos se ralentiza, un solo sub-plano puede detenerse 4-6 segundos |

## Duración mínima por diálogo (regla dura)

**Duración del segmento ≥ total de caracteres de diálogo y narración dentro del segmento (la parte escrita en description) ÷ 4.5 caracteres/segundo + 2 segundos de margen de interpretación**

El diálogo que no quepa debe pasarse al segmento siguiente; no se permite amontonar en un segmento diálogo que no da tiempo a interpretar.

## Elementos del plano

1. **Título del plano**: resumen del contenido central del segmento en 3-5 caracteres (p. ej. «Despierta de la pesadilla»)
2. **Hora**: hora concreta + descripción de la luz
3. **Lugar**: descripción completa de la escena + disposición espacial + detalles del entorno
4. **Tamaño de plano**: el tamaño dominante dentro del segmento; en segmentos con varios tamaños, escribe la combinación, p. ej. "plano medio + primerísimo primer plano"
5. **Ángulo**: a la altura de los ojos/contrapicado/picado/lateral/de espaldas
6. **Movimiento de cámara** `movement`: cada sub-plano debe tener un movimiento de cámara, elegido del vocabulario y puesto por escrito (los sub-planos de un mismo segmento pueden diferir). Vocabulario: fijo con micromovimiento (vaivén de respiración)/acercamiento lento/alejamiento/travelling lateral de seguimiento/grúa de elevación y vista aérea/órbita en arco/vaivén en mano/ángulo de mirón furtivo/enfoque de mirada/temblor/órbita tierna/persecución a toda velocidad/zigzag de pelea/picado en vuelo/contrapicadísimo/ángulo holandés/plano sobre el hombro/punto de vista subjetivo/látigo rápido de cámara/transición por oclusión/parada a cuadro congelado/bullet time. Elige por tipo de segmento: preparación → alejamiento revelador, grúa aérea, travelling lateral de seguimiento; diálogo → plano sobre el hombro, acercamiento lento, vaivén de respiración; emoción → acercamiento lento tipo pulso cardíaco, vaivén en mano, temblor; acción → para peleas/acción a alta velocidad elige primero la fórmula de posiciones de la skill fight-cinematography, y para lo demás persecución a toda velocidad, zigzag de pelea, travelling lateral de seguimiento; punto de explosión → bullet time, parada a cuadro congelado, enfoque de mirada; suspense/terror → ángulo de mirón furtivo, ángulo holandés, punto de vista subjetivo. Trucos de realce (bullet time/cámara lenta/ojo de pez): como máximo 1-2 por episodio
7. **Descripción visual** `description`: describe sub-plano a sub-plano como `【镜头1】…【镜头2】…` lo que el público ve y oye realmente — cómo se filma el plano (el movimiento de cámara, p. ej. "la cámara se acerca lenta y uniformemente desde un plano medio hasta un primerísimo primer plano") se escribe al principio del sub-plano, y la imagen (quién + acción concreta + detalles corporales + expresión) después del movimiento de cámara; si el sub-plano tiene diálogo, escríbelo dentro del `【镜头N】` correspondiente como «NombreDelPersonaje dice: "réplica"», y la narración como «Narración: contenido»
8. **Resultado visual** `result`: la consecuencia inmediata al final del segmento + detalles visuales
9. **Atmósfera** `atmosphere`: luz + tonalidad + sonido + atmósfera general
10. **Duración** `duration`: duración total del segmento de 8-15 segundos, y además debe cumplir la duración mínima por diálogo
11. **Vínculo con la escena**: si se puede emparejar con una escena existente, hay que rellenar `scene_id`
12. **Vínculo con personajes**: rellena `character_ids`, vinculando de 0 a varios personajes implicados en este segmento
13. **Vínculo con atrezzo**: rellena `prop_ids`, vinculando de 0 a varias piezas clave de atrezzo que aparezcan en este segmento

## Reglas de vínculo con escenas

- Cuando `location + time` permita una coincidencia clara, hay que rellenar el `scene_id` correcto
- No generes ID de escena inexistentes
- Si el contenido del guion cae claramente dentro de una escena existente, no crees una descripción de escena nueva duplicada

## Reglas de vinculación de personajes

- Un segmento puede quedarse sin personajes o vincular varios
- Cualquier personaje con aparición clara en el segmento —visible, actuando o hablando— debe vincularse
- Los segmentos de puro entorno, los planos vacíos y los primerísimos primeros planos de objetos pueden pasar un array vacío

## Reglas de vinculación de atrezzo

- Cuando el atrezzo lo usa un personaje, se entrega, sale en primerísimo primer plano o es claramente visible en el cuadro y con sentido narrativo, debe vincularse a ese segmento
- Los segmentos de primerísimo primer plano de atrezzo (sin personajes) también deben vincular el atrezzo; `character_ids` puede quedar vacío
- No vincules objetos de fondo ni ambientación de escena ajenos a la trama; los segmentos sin atrezzo pasan un array vacío
- El atrezzo vinculado sirve de imagen de referencia para la generación de vídeo (imagen de producto sobre fondo blanco) y garantiza que su apariencia sea coherente entre segmentos

## Requisitos de calidad

- `description` debe ser apta para lectura humana, describiendo sub-plano a sub-plano lo que el público ve y oye realmente; los diálogos/narración se escriben directamente dentro del `【镜头N】` correspondiente
- `image_prompt` debe resaltar la composición del fotograma único, la apariencia de los personajes, el entorno y la luz (corresponde al primer sub-plano del segmento)
- `bgm_prompt` y `sound_effect` pueden ser frases concisas, pero sin quedar tan vacíos como un simple "tenso" o "triste"
- Para ajustar algo, llama a `update_storyboard` y modifica el segmento concreto

## Naturalidad y verosimilitud de la identidad (reglas duras)

- `description` / `result` deben ser lenguaje narrativo visual natural: solo lo que el espectador ve y oye; prohibido el tono analítico y la enumeración tipo lista («en primer lugar/en segundo lugar», exposiciones estilo «1, 2, 3»); la numeración `【镜头N】` es la única marca estructural permitida
- La conducta de los personajes debe ajustarse a su identidad, edad y capacidades: un analfabeto no sabe leer ni escribir, y no pueden aparecer acciones como escribir, leer cartas o leer un texto en voz alta; los niños muy pequeños tampoco pueden aparecer con lógica de escritura; los personajes que no saben una lengua extranjera no la leen ni la escriben. La única excepción es que el guion original indique explícitamente esa conducta — si el guion no la trae, no la añadas por tu cuenta
- Cuando falte una base de alfabetización/cálculo u otra capacidad especializada, expresa la emoción y la información mediante acciones, gestos, atrezzo, etc.; no recurras a «escribir/leer»
