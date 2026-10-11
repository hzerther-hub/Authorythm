---
name: storyboard-breaker
description: Padrão profissional de decomposição de storyboard — dividir o roteiro em segmentos de storyboard capazes de carregar múltiplos subplanos
---

# Guia de Decomposição de Storyboard

## Definição Central: Segmento de Storyboard

Um storyboard = um **segmento de storyboard** (segment) = uma tarefa de geração de vídeo.

- Cada segmento dura **8-15 segundos** e carrega internamente **2-4 subplanos**
- Entre subplanos **é permitido cortar**: troca de enquadramento, ângulo ou sujeito, emendados por corte seco
- Entre subplanos **não se atravessam cenários**: um segmento acontece dentro de um único cenário (`scene_id` é vínculo de nível de segmento)
- Cada subplano dura 2-6 segundos, focado numa unidade visual (uma ação, uma reação, um close)

## Fluxo de Decomposição (quatro passos)

2. **Identificação de beats**: primeiro identifique os beats narrativos do roteiro — marcações como 【Abertura】【Gatilho】【Clímax】【Desfecho】, ou pontos de virada narrativos (mudança de lugar, revelação de regra, explosão emocional, reviravolta). **A fronteira de um beat força o corte do segmento**; os subplanos de um mesmo beat devem preferencialmente ir para o mesmo segmento — não espalhe uma cadeia de causa e efeito (preparação-acontecimento-reação) por segmentos diferentes
3. **Ancoragem de volume**: duração total alvo = número de caracteres do roteiro ÷ 500 caracteres/minuto; número de segmentos ≈ duração total alvo ÷ 12 segundos, com flutuação tolerada de ±20%. Não ultrapasse nem fique aquém de forma evidente

## Durações por Camada de Ritmo

Defina a duração pela função do segmento — não use uma régua única:

| Tipo de segmento | Duração | Observações |
|---|---|---|
| Segmento de transição | 8-10 s | deslocamento, planos vazios, estabelecimento de ambiente, transições |
| Segmento narrativo | 10-15 s | avanço normal da trama, diálogos |
| Segmento de clímax | 12-15 s | closes, revelação de regras, explosão emocional, reviravolta; o ritmo dos subplanos desacelera, um subplano pode se deter por 4-6 s |

## Piso de Duração de Diálogo (regra rígida)

**Duração do segmento ≥ número total de caracteres de falas e narração dentro do segmento (a parte escrita no description) ÷ 4.5 caracteres/segundo + 2 segundos de folga de atuação**

Fala que não cabe deve ser dividida para o segmento seguinte; não é permitido entupir num só segmento fala que não dá para atuar.

## Elementos do Plano

1. **Título do plano**: resumo em 3-5 caracteres do conteúdo central do segmento (ex.: "acorda de pesadelo")
2. **Horário**: hora concreta + descrição da luz
3. **Lugar**: descrição completa da cena + layout espacial + detalhes do ambiente
4. **Enquadramento**: enquadramento dominante do segmento; segmentos com vários escrevem a combinação, ex.: "plano médio + close"
5. **Ângulo**: nível do olhar/contra-plongée/plongée/lateral/costas
6. **Movimento de câmera** `movement`: cada subplano precisa de um movimento de câmera, escolhido do vocabulário e escrito (subplanos do mesmo segmento podem diferir). Vocabulário: fixo com micromovimento (ondulação de respiração) / avanço lento / recuo revelador / travelling lateral de acompanhamento / grua de elevação e descida / órbita em arco / câmera na mão tremida / ângulo de espião / foco no olhar / tremor / órbita terna / cauda em alta velocidade / travessia de luta / mergulho aéreo / contra-plongée extremo / inclinação holandesa / plano próximo sobre o ombro / POV / panorâmica chicote / transição por obstrução / parada brusca congelada / bullet time. Escolha pelo tipo de segmento: preparação → recuo revelador, grua, travelling lateral; diálogo → plano sobre o ombro, avanço lento, ondulação de respiração; emoção → avanço lento em pulso cardíaco, câmera na mão, tremor; ação → para luta/ação em alta velocidade, priorize a fórmula de posicionamento da skill fight-cinematography, nos demais use cauda em alta velocidade, travessia de luta, travelling lateral; clímax → bullet time, parada brusca congelada, foco no olhar; suspense/terror → ângulo de espião, inclinação holandesa, POV. Truques de realce (bullet time/câmera lenta/olho de peixe): no máximo 1-2 por episódio
7. **Descrição visual** `description`: descreva subplano a subplano como `【镜头1】…【镜头2】…` o que o público efetivamente vê e ouve — como o plano é filmado (o movimento de câmera, ex.: "a câmera avança lenta e uniformemente do plano médio até o close") vem no início de cada subplano, e a imagem (quem + ação concreta + detalhes corporais + expressão) vem depois do movimento; quando o subplano tem fala, escreva "NomeDoPersonagem diz: "fala"" dentro do `【镜头N】` correspondente, e a narração como "Narração: conteúdo"
8. **Resultado visual** `result`: consequência imediata no fim do segmento + detalhes visuais
9. **Atmosfera** `atmosphere`: luz + tonalidade + som + clima geral
10. **Duração** `duration`: duração total do segmento de 8-15 segundos, atendendo também ao piso de duração de diálogo
11. **Vínculo de cena**: se houver correspondência com uma cena existente, `scene_id` deve ser preenchido
12. **Vínculo de personagens**: preencha `character_ids`, vinculando de 0 a vários personagens envolvidos no segmento
13. **Vínculo de props**: preencha `prop_ids`, vinculando de 0 a vários props-chave que apareçam no segmento

## Regras de Vínculo de Cena

- Quando `location + time` casar sem ambiguidade, o `scene_id` correto deve ser preenchido de volta
- Não invente IDs de cena que não existem
- Se o conteúdo do roteiro claramente se passa numa cena existente, não crie descrição de cena nova duplicada

## Regras de Vínculo de Personagens

- Um segmento pode não ter personagens ou pode vincular vários
- Qualquer personagem com presença clara no segmento — visto, agindo ou falando — deve ser vinculado
- Segmentos puramente ambientais, planos vazios e closes de objeto podem passar array vazio

## Regras de Vínculo de Props

- Quando o prop é usado por personagem, entregue, em close, ou claramente visível no quadro e relevante para a narrativa, deve ser vinculado ao segmento
- Segmentos de close de prop (sem personagens) também devem vincular o prop; `character_ids` pode ficar vazio
- Não vincule objetos de fundo ou ambientação de cena irrelevantes à trama; segmentos sem props passam array vazio
- Os props vinculados servem de imagens de referência para a geração de vídeo (imagem de item único em fundo branco), garantindo a consistência da aparência do prop entre segmentos

## Requisitos de Qualidade

- O `description` deve ser legível para humanos, descrevendo em detalhe subplano a subplano o que o público efetivamente vê e ouve; falas/narração escritas direto dentro do `【镜头N】` correspondente
- O `image_prompt` deve destacar a composição do fotograma único, a aparência dos personagens, o ambiente e a luz (corresponde ao primeiro subplano do segmento)
- `bgm_prompt` e `sound_effect` podem ser frases curtas, mas não tão vagas que se reduzam a "tenso" ou "triste"
- Para ajustes, chame `update_storyboard` para modificar o segmento específico

## Naturalidade e Plausibilidade de Identidade (regras rígidas)

- `description` / `result` devem ser linguagem narrativa visual natural: apenas o que o público vê e ouve; proibido tom analítico e enumeração em itens (exposição do tipo "primeiro/segundo", "1. 2. 3."); a numeração `【镜头N】` é a única marcação estrutural permitida
- O comportamento dos personagens deve condizer com identidade, idade e habilidades estabelecidas: analfabeto não sabe ler, não podem aparecer ações de escrever, ler carta ou ler texto em voz alta; criança pequena demais também não pode exibir lógica de escrita; personagem que não sabe uma língua estrangeira não a lê nem a escreve. A única exceção é o roteiro original declarar explicitamente tal ação — se o roteiro não traz, não acrescente por conta própria
- Sem base de habilidade como alfabetização/cálculo, expresse emoção e informação por ação, expressão e props — nunca recaindo em "escrever/ler texto"
