---
name: prop-prompt
description: Normativa del prompt final de atrezzo — bodegón de una sola pieza sobre fondo blanco, punto de vista estándar de fotografía de producto: proporciones precisas, bordes completos, fondo sin carga narrativa
---

# Prompt final de atrezzo (pieza única sobre fondo blanco · fotografía de producto estándar)

Lo que se genera es una imagen de producto de una sola pieza sobre fondo blanco (product shot): **con un punto de vista estándar de fotografía de producto**, en el cuadro solo aparece la pieza de atrezzo en sí, aislada sobre un fondo blanco puro, **sin mezclar ningún otro elemento** — sin otros objetos, sin personas, sin entorno de escena, sin manos que la sujeten.

Tres requisitos estrictos:
1. **Proporciones precisas de todas las partes del objeto** — sin exageración, deformación ni estiramiento estilizado; las relaciones de tamaño relativo del atrezzo deben ser reales
2. **Bordes completos** — la pieza entra completa en el cuadro como un todo, con margen por los cuatro lados; ninguna parte puede quedar recortada por el borde del cuadro
3. **El fondo no transporta ningún contenido narrativo** — el fondo blanco puro es solo un soporte, sin sensación de lugar, sin insinuaciones argumentales, sin elementos decorativos

## Estructura de salida (ensambla un único párrafo coherente en este orden; el idioma sigue la directiva de idioma de la sesión)

```
imagen de producto de una sola pieza, punto de vista estándar de fotografía de producto, [nombre del atrezzo + material/color/forma/tamaño + grado de antigüedad y detalles de desgaste],
proporciones precisas de todas las partes del objeto, colocado aislado sobre un fondo blanco puro, centrado y completo en cuadro, bordes completos sin recorte,
fondo limpio que no transporta ningún contenido narrativo, sin otros objetos, sin personas, sin escena,
luz de estudio suave y uniforme, sombras tenues, alto detalle
```

## Reglas de generación

- Toma como núcleo el `name` (nombre) y la `description` (apariencia del objeto) del atrezzo: material, color, forma, tamaño, grado de antigüedad, señales de desgaste y demás detalles físicos se concretan **punto por punto**; de ahí viene la reconocibilidad del atrezzo
- Punto de vista estándar de fotografía de producto: vista 3/4 ligeramente picada (se aprecian a la vez la cara superior y un lateral, la que da mayor volumen); para piezas planas (papeles, documentos, fotos), toma cenital plana en extensión total
- La pieza única se presenta centrada y completa, con margen por los cuatro lados, proporciones precisas y bordes completos; no recortes el cuerpo del atrezzo
- Luz de estudio suave y uniforme, sombras tenues, alto detalle
- Describe solo el objeto en sí; no menciones la trama, los personajes ni el uso (ni el fondo ni el cuadro transportan contenido narrativo)
- La salida usa el idioma objetivo indicado por la directiva de idioma de la sesión, sin mezclar vocabulario ajeno; **sin** palabras tipo «calidad cinematográfica» (la imagen del atrezzo es una foto de producto, no un fotograma)

## Prohibiciones

- Manos sujetándola, personas, otros objetos o entorno de escena en el cuadro
- Envases, pedestales, expositores (salvo que formen parte del propio atrezzo)
- Texto, marcas de agua, firmas, logotipos de marcas reales (los textos y gráficos impresos sobre el propio atrezzo pueden conservarse y describirse)
- Reflejos del entorno, luz de colores
- Perspectiva exagerada, deformación, proporciones falseadas, recorte de bordes

## Guardado

