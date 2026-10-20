---
name: script-rewriter
description: Metodologia e padrões para reescrever romance em roteiro formatado
---

# Guia de Reescrita de Roteiro

## Princípios de Reescrita

1. **Preservar o enredo central**: não mudar a linha principal da história nem os relacionamentos entre personagens
2. **Reforçar a visualidade**: converter prosa narrativa em descrições de cena visualizáveis
3. **Dirigido por diálogo**: usar falas para empurrar a trama e reduzir a narração
4. **Controle de ritmo**: manter cada cena entre 30-60 segundos, adequada a vídeo curto
5. **Sem linguagem de câmera**: nada de enquadramento, ângulo ou movimento de câmera — isso pertence à etapa de decomposição do storyboard

## Formato do Roteiro Formatado

```
## S01 | INT · Cafeteria | Entardecer

A luz do entardecer entra pelas janelas de vidro de piso ao teto da cafeteria; vapor sobe das xícaras de café no balcão.

João senta sozinho no banco do canto, cabeça baixa sobre o celular, com ar um tanto ansioso.

A campainha toca e Maria empurra a porta ao entrar. Ela vê João e caminha até ele sorrindo.

Maria: (sorrindo) Esperou muito?
João: (erguendo os olhos) Nem tanto, acabei de chegar.
```

### Regras de Formato

- `## S<número> | INT/EXT · Local | Período` — cabeçalho de cena
- Descrição de ação em parágrafos naturais — sem nenhuma linguagem de câmera
- `NomeDoPersonagem: (estado/expressão) conteúdo da fala` — formato de diálogo

### Referência de Volume de Conteúdo

O roteiro formatado fica cerca de 20-30% mais longo que o conteúdo original; o acréscimo vem principalmente das marcações de cabeçalho de cena e da formatação de diálogo — não é expansão.

## Passos de Reescrita

1. Primeiro chame `read_episode_script` para ler o conteúdo original
2. Analise a estrutura do conteúdo (proporção entre diálogo, narração e monólogo interior)
3. Chame `rewrite_to_screenplay` para executar a reescrita
4. Confira o resultado da reescrita e verifique se segue o formato de roteiro formatado
5. Chame `save_script` para salvar o resultado final

## Observações

- O monólogo interior deve ser exteriorizado em expressões/ações/decisões da personagem ou em palavras ditas em voz alta — **voz off, narração e monólogo interior são proibidos**
- Cada cena precisa de pelo menos duas personagens interagindo diante da câmera; não escreva uma cena de uma só pessoa em um quarto vazio
- Troque o lugar ou a hora entre cenas consecutivas; não repita a mesma sala vez após vez
- Divida narrações longas em várias cenas curtas
- Garanta que cada cena tenha um ponto de virada emocional claro
- Mantenha a consistência do estilo de fala de cada personagem
- A numeração das cenas cresce em sequência (S01, S02, S03...)
- Os períodos devem ser específicos (entardecer, madrugada, amanhecer) — não escreva um vago "dia"
