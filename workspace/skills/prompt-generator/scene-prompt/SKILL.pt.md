---
name: scene-prompt
description: Padrão do prompt final de cena — plano de estabelecimento amplo e nítido: posições relativas fixas de primeiro plano/plano médio/fundo/entradas e saídas/chão/paredes/ambientação principal; espaço contínuo, autoconsistente e reutilizável, sem pessoas
---

# Prompt Final de Cena (plano de estabelecimento em grande angular · cenário vazio sem pessoas)

O que se gera é uma imagem de cena do tipo **plano de estabelecimento nítido em grande angular (establishing shot)**: um cenário vazio **totalmente sem pessoas**, que mostra por inteiro **as posições relativas fixas do primeiro plano, plano médio, fundo, entradas e saídas, chão, paredes e ambientação principal**, com estrutura espacial contínua, autoconsistente e reutilizável.

Esta imagem serve de âncora de referência de fundo para todos os planos da cena: tanto o público quanto o modelo precisam conseguir ler nela o layout completo do espaço — por onde se entra e sai, qual a textura do chão e das paredes, onde cada peça-chave da ambientação está fixada. O ponto de vista deve ser estável e de uso geral.

## Estrutura de Saída (monte um único parágrafo coeso nesta ordem, seguindo a diretiva de idioma da sessão)

```
plano em grande angular com câmera fixa, plano de estabelecimento nítido, [local + textura de época], [período do dia],
composição em três camadas — primeiro plano ([elementos do primeiro plano]), plano médio ([espaço principal do plano médio]), fundo ([profundidade do fundo]),
entradas e saídas ([posição e estilo de portas/passagens]), chão ([material e estado do piso]), paredes ([material e cor das paredes]),
[ambientação principal e suas posições relativas fixas],
estrutura espacial contínua e autoconsistente,
[fonte de luz + temperatura de cor + contraste claro-escuro], [atmosfera],
nenhuma pessoa no quadro, cenário vazio, qualidade cinematográfica
```

## Regras de Estrutura Espacial

O espaço precisa ser **legível, coerente e reutilizável**:

- **Primeiro plano**: elementos de moldura/oclusão (batente, canto de mesa, plantas, borda de equipamento) que criam profundidade — escreva 1-2 elementos concretos
- **Plano médio**: o espaço principal da cena e a ambientação-chave (linha de produção, camas, balcão)
- **Fundo**: a extensão do espaço (parede ao longe, janelas, corredor, silhueta da cidade)
- **Entradas e saídas**: a posição e o estilo de portas, escadas e passagens devem estar explícitos (ex.: "uma porta de ferro à esquerda do quadro") — é a base para dirigir as entradas e saídas dos personagens nos planos seguintes
- **Chão e paredes**: concrete material, cor e estado (ex.: "piso de cimento com manchas de óleo", "parede de cal descascando")
- **Ambientação principal**: escreva 2-4 peças-chave e suas **posições relativas fixas** (ex.: "a linha de produção se estende ao longo da parede e termina no balcão"); as relações esquerda-direita/perto-longe entre as peças devem ser autoconsistentes — não fique apenas listando nomes de objetos

## Pessoas (Regra Rígida · Prioridade Máxima)

**Nenhuma pessoa pode aparecer na imagem da cena — mantenha apenas o cenário.**

- O prompt não descreve pessoas nem menciona qualquer conteúdo ligado a pessoas
- Toda informação de pessoas que apareça na descrição da cena (prompt) deve ser ignorada e não entrar no prompt
- O prompt deve terminar com: "nenhuma pessoa no quadro, cenário vazio"

Os elementos de ambientação, a textura de época e os elementos visuais-chave do `prompt` (descrição da cena) devem ser todos materializados; o `lighting` (luz da cena) deve ser concreto: direção da fonte de luz, temperatura quente/fria, contraste claro-escuro (ex.: "lâmpadas no teto emitem luz branca fria, lançando sombras duras sob as máquinas").

## Ponto de Vista e Atmosfera

- Grande angular estável em altura do olhar ou levemente de cima; sem ângulos extremos para cima/baixo, olho de peixe ou composição inclinada (será reutilizada repetidamente como cena fixa)
- Defina o período e a base de luz a partir de `location` + `time` (a luz de dia/noite/entardecer é completamente diferente)
- Concrete as palavras de atmosfera: "opressivo" → "ar abafado, luz escura e baixa"; não fique apenas em palavras de emoção abstratas
- Escreva a saída no idioma-alvo indicado pela diretiva de idioma da sessão, sem misturar palavras estranhas

## Proibições

- Qualquer pessoa — **nenhuma pessoa pode aparecer na imagem da cena; mantenha apenas o cenário**
- Textos, texto legível em placas, marcas d'água, assinaturas, logos de marcas reais
- Desfoque de movimento, objetos em movimento (a imagem de referência da cena deve ser estática e estável)
- Apenas listar a ambientação sem explicitar posições relativas (a estrutura espacial deve ser contínua e autoconsistente)

## Salvamento

