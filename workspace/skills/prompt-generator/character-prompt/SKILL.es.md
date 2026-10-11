---
name: character-prompt
description: Normativa del prompt final de personaje — primerísimo primer plano de frente + vista triple (character turnaround: frente/perfil a 90 grados/espalda), como ancla de apariencia para todas las generaciones posteriores
---

# Prompt final de personaje (izquierda: primerísimo primer plano de frente + derecha: vista triple)

Lo que se genera es una **imagen de referencia del personaje con el look definitivo (character turnaround sheet / character reference sheet, multi-view concept art layout)**, con una composición estrictamente fija:

- **Izquierda: primerísimo primer plano de frente** — plano cercano frontal de cabeza y hombros, con rasgos faciales, peinado y textura de piel bien visibles, como ancla de la reconocibilidad del rostro
- **Derecha: tres vistas de cuerpo entero de la misma altura, yuxtapuestas — frente, perfil a 90 grados y espalda** — las tres vistas de cuerpo entero del mismo personaje a la misma altura y en paralelo, con las coronillas y las plantas de los pies alineadas

**Principio básico: coherencia > belleza.** Esta imagen es el ancla de apariencia para todas las imágenes de personaje y referencias de vídeo posteriores; debe ser neutra, nítida y reutilizable — no persigas la artisticidad de una imagen suelta.

## Estructura de salida (ensambla un único párrafo coherente en este orden; el idioma sigue la directiva de idioma de la sesión)

```
character turnaround sheet, character reference sheet, multi-view concept art layout, orthographic views, no perspective distortion;
a la izquierda un primerísimo primer plano de frente, a la derecha tres vistas de cuerpo entero de la misma altura, yuxtapuestas, mostrando frente, perfil a 90 grados y espalda;
las tres vistas de cuerpo entero evenly spaced panels, coronillas y plantas de los pies alineadas;
el primerísimo primer plano y las vistas de cuerpo entero son el mismo personaje, cuerpo completo en cuadro, A-pose con postura neutra, expresión natural sin gesto marcado;
[edad aparente + impresión de género + complexión], [rasgos faciales], [peinado], [vestuario + accesorios];
el rostro, el peinado y el vestuario del primerísimo primer plano de frente y de las tres vistas son completamente idénticos;
fondo blanco puro, luz suave y uniforme, calidad cinematográfica
```

## Reglas del orden de descripción

Pon **los rasgos más reconocibles al principio** y despliega en este orden cada elemento clave de `appearance` (apariencia) y `styling` (caracterización), sin omisiones:

1. Anclas de identidad: edad aparente (p. ej. «veintipocos años»), impresión de género, complexión (estatura y constitución, hábitos posturales)
2. Rasgos faciales: forma del rostro, ojos, otros rasgos notables (cicatrices, lunares, gafas, etc.) — el primerísimo primer plano de frente depende especialmente de esta parte
3. Peinado: color, longitud, estilo
4. Vestuario: corte, color, material, estado (p. ej. «un uniforme de trabajo arrugado con restos de soldadura en los puños»)
5. Accesorios: escribe solo los reconocibles, no los acumules

Los rasgos de personalidad del personaje se convierten en descripciones de presencia exterior y de gesto (p. ej. «demacrado» → «mirada cansada, hombros ligeramente caídos»); las palabras de personalidad no deben aparecer directamente.

## Composición y coherencia

- Primerísimo primer plano de frente a la izquierda: de frente a cámara, expresión neutra, desde la coronilla hasta los hombros completamente en cuadro
- Las tres vistas de cuerpo entero a la derecha: frente, perfil a 90 grados y espalda del mismo personaje, **a la misma altura, en paralelo y con separación uniforme**, con coronillas y plantas de los pies en la misma línea horizontal
- El primer plano y las tres vistas de cuerpo entero deben tener el mismo rostro, el mismo peinado y el mismo vestuario — escribe explícitamente «el rostro, el peinado y el vestuario del primerísimo primer plano de frente y de las tres vistas de cuerpo entero son completamente idénticos»
- Postura neutra, expresión natural — para que sea fácil reutilizarlo como imagen de referencia
- Manos y pies normales: en las vistas de cuerpo entero, manos con cinco dedos y pies con cinco dedos, dos brazos y dos piernas, sin extremidades de más; manos relajadas de forma natural, sin gestos complejos (reduce la probabilidad de deformación de las manos)
- **Límite duro del total de instancias del personaje: 1 primerísimo primer plano de frente + 3 vistas de cuerpo entero = 4 instancias de personaje en total, prohibido que aparezcan más** (ojo: las 3 vistas de cuerpo entero son por diseño el mismo personaje en ángulos distintos — frente / perfil a 90 grados / espalda; esa es la intención del diseño, no una «copia»; lo que está prohibido es dibujar al mismo personaje una vez adicional, o colar más instancias en cuadro además de las 3 vistas de cuerpo entero; entre las 3 vistas de cuerpo entero debe haber orientaciones claramente distintas: izquierda / centro / derecha son respectivamente frente / perfil a 90 grados / espalda, nunca las tres de frente)
- Una sola persona: toda la imagen solo puede contener las 4 instancias de personaje indicadas; sin dobles, clones ni réplicas de varias personas; rasgos faciales estables, sin distorsión ni derretimiento
- Luz de estudio suave y uniforme, sin claroscuros dramáticos (la imagen de referencia debe servir en todo tipo de escenas)
- La salida usa el idioma objetivo indicado por la directiva de idioma de la sesión, sin mezclar vocabulario ajeno

## Prohibiciones

- Posturas dinámicas, expresiones exageradas, objetos en la mano, aparecer en cuadro con otras personas
- **Más de 4 instancias del personaje (1 primer plano + 3 vistas de cuerpo entero); las 3 vistas de cuerpo entero son ángulos distintos del mismo personaje (frente / perfil a 90 grados / espalda) — es la intención del diseño, no un punto prohibido; lo prohibido es copiar al mismo personaje adicionalmente fuera de las 3 vistas de cuerpo entero, o que las 3 vistas de cuerpo entero salgan todas de frente / amontonadas en el centro del cuadro / superpuestas / a alturas distintas**
- Recortar el cuerpo (las vistas de cuerpo entero deben ser full body, de coronilla a plantas de los pies completamente en cuadro; el primer plano debe tener cabeza y hombros completos en cuadro)
- Seis dedos, dedos unidos, dedos ausentes, fusión deformada; tres manos, tres piernas, extremidades de más, duplicación distorsionada
- Dobles, clones, réplica de varias personas; rasgos faciales deformados, rostro derretido
- Texto, etiquetas, marcas de agua, firmas; logotipos de marcas reales, rostros de celebridades reales
- Sombras duras, luz de fondo de colores, atrezzo de fondo

## Guardado

