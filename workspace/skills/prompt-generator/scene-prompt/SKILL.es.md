---
name: scene-prompt
description: Normativa del prompt final de escena — establishing shot nítido en gran angular: posiciones relativas fijas de primer plano/plano medio/fondo/accesos/suelo/paredes/ambientación principal; espacio continuo, autoconsistente y reutilizable, sin personas
---

# Prompt final de escena (establishing shot en gran angular · plano vacío sin personas)

Lo que se genera es una imagen de escena de **establishing shot nítido en gran angular**: un plano vacío de escena pura **absolutamente sin personas**, que muestra por completo **las posiciones relativas fijas del primer plano, el plano medio, el fondo, los accesos, el suelo, las paredes y la ambientación principal**; una estructura espacial continua, autoconsistente y reutilizable.

Esta imagen sirve de ancla de referencia de fondo para todas las tomas de esa escena: el público y el modelo deben poder leer en ella la disposición completa del espacio — por dónde se entra y se sale, qué textura tienen el suelo y las paredes, en qué posición fija está cada pieza clave de la ambientación. El punto de vista debe ser estable y de propósito general.

## Estructura de salida (ensambla un único párrafo coherente en este orden; el idioma sigue la directiva de idioma de la sesión)

```
toma gran angular con cámara fija, establishing shot nítido, [lugar + textura de época], [franja horaria],
composición por tres capas: primer plano ([elementos del primer plano]), plano medio ([espacio principal del plano medio]) y fondo ([profundidad del fondo]),
accesos ([posición y estilo de puertas/pasajes]), suelo ([material y estado del suelo]), paredes ([material y color de las paredes]),
[ambientación principal y sus posiciones relativas fijas],
estructura espacial continua y autoconsistente,
[fuentes de luz + temperatura de color + contraste de luz y sombra], [atmósfera],
sin ninguna persona en el cuadro, escena vacía, calidad cinematográfica
```

## Reglas de estructura espacial

El espacio debe ser **legible, coherente y reutilizable**:

- **Primer plano**: elementos de encuadre/oclusión (marcos de puerta, esquina de una mesa, plantas, bordes de equipos) que crean profundidad — escribe 1-2 elementos concretos
- **Plano medio**: el espacio principal de la escena y su ambientación central (una cadena de montaje, las camas, el mostrador)
- **Fondo**: la prolongación del espacio (paredes lejanas, ventanas, corredores, silueta de la ciudad)
- **Accesos**: la posición y el estilo de puertas, escaleras y pasajes deben quedar explícitos (p. ej. «una puerta metálica a la izquierda del cuadro»); es la base para dirigir las entradas y salidas de los personajes en las tomas posteriores
- **Suelo y paredes**: concreta material, color y estado (p. ej. «suelo de hormigón con manchas de aceite», «pared con cal desconchada»)
- **Ambientación principal**: escribe 2-4 piezas centrales y sus **posiciones relativas fijas** (p. ej. «la cadena de montaje se despliega junto a la pared y remata en la barra»); las relaciones izquierda-derecha/cerca-lejos entre las piezas deben ser autoconsistentes, no te limites a enumerar nombres de objetos

## Personas (regla estricta · máxima prioridad)

**En la imagen de la escena no puede aparecer ninguna persona; conserva solo la escena en sí.**

- El prompt no describe personas ni menciona nada relacionado con personas
- Toda información de personas que aparezca en la descripción de la escena (prompt) se ignora y no se escribe en el prompt
- El final del prompt debe incluir: «sin ninguna persona en el cuadro, escena vacía»

La ambientación, la textura de época y los elementos visuales clave del `prompt` (descripción de la escena) deben concretarse por completo; el `lighting` (luz de la escena) debe especificarse: dirección de las fuentes, temperatura cálida/fría del color, contraste de luz y sombra (p. ej. «los tubos del techo emiten luz blanca fría y proyectan sombras duras bajo las máquinas»).

## Punto de vista y atmósfera

- Gran angular estable a la altura de los ojos o ligeramente picado; sin picados/contrapicados extremos, ojo de pez ni composiciones inclinadas (va a reutilizarse una y otra vez como escena fija)
- Determina la franja horaria y la base de luz con `location` + `time` (la luz de día/noche/atardecer es completamente distinta)
- Concreta las palabras de atmósfera: «opresiva» → «aire bochornoso, luz tenue y apagada»; no escribas solo palabras de emoción abstractas
- La salida usa el idioma objetivo indicado por la directiva de idioma de la sesión, sin mezclar vocabulario ajeno

## Prohibiciones

- Cualquier persona — **en la imagen de la escena no puede aparecer ninguna persona; conserva solo la escena en sí**
- Texto, texto legible en rótulos, marcas de agua, firmas, logotipos de marcas reales
- Desenfoque de movimiento, objetos en movimiento (la imagen de referencia de la escena debe ser estática y estable)
- Limitarse a enumerar la lista de ambientación sin indicar posiciones relativas (la estructura espacial debe ser continua y autoconsistente)

## Guardado

