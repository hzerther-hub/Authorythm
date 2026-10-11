---
name: character-prompt
description: Padrão do prompt final de personagem — close frontal + folha de três vistas (character turnaround: frente/lado a 90 graus/costas), âncora visual para todas as gerações seguintes
---

# Prompt Final de Personagem (à esquerda: close frontal + à direita: três vistas)

O que se gera é uma **folha de referência de personagem (character turnaround sheet / character reference sheet, multi-view concept art layout)**, com composição estritamente fixa:

- **Esquerda: close frontal** — plano próximo frontal de cabeça e ombros, com traços faciais, penteado e textura de pele nítidos, servindo de âncora para a legibilidade do rosto
- **Direita: três vistas de corpo inteiro de mesma altura, lado a lado — frente, lado a 90 graus e costas** — três vistas de corpo inteiro do mesmo personagem alinhadas em altura, com topo da cabeça e solas dos pés alinhados

**Princípio central: consistência > beleza.** Esta imagem é a âncora visual para todas as imagens de personagem e referências de vídeo seguintes; precisa ser neutra, nítida e reutilizável — não busque o valor artístico de uma imagem única.

## Estrutura de Saída (monte um único parágrafo coeso nesta ordem, seguindo a diretiva de idioma da sessão)

```
character turnaround sheet, character reference sheet, multi-view concept art layout, orthographic views, no perspective distortion;
à esquerda um close frontal do rosto, à direita três vistas de corpo inteiro de mesma altura
lado a lado mostrando frente, lado a 90 graus e costas,
as três vistas de corpo inteiro em evenly spaced panels, com topo da cabeça e solas dos pés alinhados;
o close e as vistas de corpo inteiro são do mesmo personagem, corpo inteiro no quadro, postura neutra em A-pose, expressão natural sem revelar emoção,
[idade aparente + gênero percebido + físico], [traços faciais], [penteado], [roupas + acessórios],
o rosto, o penteado e as roupas do close frontal e das três vistas são completamente idênticos,
fundo branco puro, luz suave e uniforme, qualidade cinematográfica
```

## Regras de Ordem de Descrição

Coloque **os traços mais reconhecíveis primeiro**, cobrindo nesta ordem cada elemento-chave de `appearance` (aparência) e `styling` (figurino), sem omissões:

1. Âncoras de identidade: idade aparente (ex.: "pouco mais de vinte"), gênero percebido, físico (altura e porte, hábitos posturais)
2. Traços faciais: formato do rosto, olhos, outras marcas notáveis (cicatriz, pinta, óculos etc.) — o close frontal depende especialmente desta parte
3. Penteado: cor, comprimento, estilo
4. Roupas: corte, cor, material, estado (ex.: "uniforme amassado com marcas de solda nos punhos")
5. Acessórios: escreva apenas os reconhecíveis, sem acúmulo

Os traços de personalidade do personagem devem ser convertidos em descrição de presença exterior e expressão (ex.: "esgotado" → "olhar cansado, ombros levemente caídos"); palavras de personalidade não podem aparecer diretamente.

## Composição e Consistência

- Close frontal à esquerda: voltado de frente para a câmera, expressão neutra, do topo da cabeça aos ombros totalmente no quadro
- Três vistas de corpo inteiro à direita: frente, lado a 90 graus e costas do mesmo personagem, **de mesma altura, lado a lado, com espaçamento uniforme**, topo da cabeça e solas dos pés na mesma linha horizontal
- O close e as três vistas de corpo inteiro devem ter o mesmo rosto, o mesmo penteado e as mesmas roupas — escreva explicitamente "o rosto, o penteado e as roupas do close frontal e das três vistas de corpo inteiro são completamente idênticos"
- Postura neutra em pé, expressão natural — fácil de reutilizar como imagem de referência
- Mãos e pés normais: nas vistas de corpo inteiro, as mãos têm cinco dedos normais e os pés cinco artelhos, dois braços e duas pernas, sem membros extras; mãos naturalmente relaxadas, sem gestos complexos (reduz a probabilidade de deformação das mãos)
- **Limite rígido do total de instâncias do personagem: 1 close frontal + 3 vistas de corpo inteiro = 4 instâncias de personagem no total, proibido aparecer mais** (atenção: as 3 vistas de corpo inteiro são, por desenho, o mesmo personagem em ângulos diferentes — frente / lado a 90 graus / costas; isso é intenção de design, não "cópia"; o que é proibido é desenhar o mesmo personagem uma vez extra além disso, ou encaixar mais instâncias no quadro além das 3 vistas de corpo inteiro; entre as 3 vistas de corpo inteiro deve haver orientações claramente distintas — esquerda / centro / direita são, respectivamente, frente / lado a 90 graus / costas — jamais todas de frente)
- Pessoa única: a imagem inteira só pode ter as 4 instâncias de personagem acima, sem fantasma, sósia ou cópia múltipla; traços estáveis, sem distorção nem derretimento
- Luz de estúdio suave e uniforme, sem sombras dramáticas (a imagem de referência precisa funcionar em qualquer tipo de cena)
- Escreva a saída no idioma-alvo indicado pela diretiva de idioma da sessão, sem misturar palavras estranhas

## Proibições

- Posturas dinâmicas, expressões exageradas, objetos na mão, dividir o quadro com outras pessoas
- **Mais de 4 instâncias de personagem (1 close + 3 vistas de corpo inteiro). As 3 vistas de corpo inteiro são, intencionalmente, o mesmo personagem em ângulos diferentes (frente / lado a 90 graus / costas) — isso é intenção de design, NÃO é item proibido; o que é proibido: copiar o mesmo personagem extra além das 3 vistas de corpo inteiro, ou fazer as 3 vistas todas de frente / todas empilhadas no centro do quadro / sobrepostas / em alturas diferentes**
- Cortar o corpo (as vistas de corpo inteiro devem ser full body, do topo da cabeça às solas totalmente no quadro; o close deve ter cabeça e ombros completos no quadro)
- Seis dedos, dedos fundidos, dedos faltando, deformação por fusão; três mãos, três pernas, membros extras, distorção por duplicação
- Fantasmas, sósias, cópias múltiplas; traços distorcidos, rosto derretendo
- Textos, etiquetas, marcas d'água, assinaturas; logos de marcas reais, rostos de celebridades reais
- Sombras pesadas, luz de fundo colorida, adereços ao fundo

## Salvamento

