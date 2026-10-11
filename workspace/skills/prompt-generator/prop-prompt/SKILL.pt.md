---
name: prop-prompt
description: Padrão do prompt final de prop — item único em fundo branco, ponto de vista padrão de fotografia de produto: proporções precisas, bordas completas, fundo sem carga narrativa
---

# Prompt Final de Prop (item único em fundo branco · fotografia padrão de produto)

O que se gera é uma imagem de item único em fundo branco (product shot): **com ponto de vista padrão de fotografia de produto**, o quadro contém apenas o prop em si, isolado sobre um fundo branco puro, **sem misturar nenhum outro elemento** — nenhum outro objeto, nenhuma pessoa, nenhum ambiente de cena, nenhuma mão segurando.

Três exigências inflexíveis:
1. **Proporções precisas entre as partes do item** — sem exagero, deformação ou estilização por esticamento; as relações de tamanho relativo do prop devem ser reais
2. **Bordas completas** — o prop entra inteiro no quadro, com margem em todos os lados; nenhuma parte pode ser cortada pela borda do quadro
3. **O fundo não carrega nenhum conteúdo narrativo** — o fundo branco puro é só um suporte, sem sensação de lugar, sem insinuação de enredo, sem elementos decorativos

## Estrutura de Saída (monte um único parágrafo coeso nesta ordem, seguindo a diretiva de idioma da sessão)

```
imagem de produto de item único, ponto de vista padrão de fotografia de produto, [nome do prop + material/cor/forma/tamanho + grau de novo e detalhes de desgaste],
proporções precisas entre as partes do item, isolado sobre fundo branco puro,
centralizado e inteiro no quadro, bordas completas sem corte,
fundo limpo sem carregar nenhum conteúdo narrativo, sem outros objetos, sem pessoas, sem cena,
luz de estúdio suave e uniforme, sombras leves, alto nível de detalhe
```

## Regras de Geração

- Tome como núcleo o `name` (nome) e o `description` (aparência do item) do prop: os detalhes físicos — material, cor, forma, tamanho, grau de novo, marcas de desgaste etc. — devem ser **materializados item a item**; é daí que vem a identificabilidade do prop
- Ponto de vista padrão de fotografia de produto: ângulo 3/4 levemente de cima (mostra de uma vez o topo e o lado, com máximo volume); props planos (papel, documentos, fotos) usam vista superior direta em flat lay
- Apresente o item único centralizado e completo, com margem em volta, proporções precisas e bordas completas — não corte o corpo do prop
- Luz de estúdio suave e uniforme, sombras leves, alto detalhe
- Descreva apenas o item em si; não mencione enredo, personagens ou uso (nem o fundo nem o quadro carregam conteúdo narrativo)
- Escreva a saída no idioma-alvo indicado pela diretiva de idioma da sessão, sem misturar palavras estranhas; **não** use termos do tipo "qualidade cinematográfica" (imagem de prop é foto de produto, não still de filme)

## Proibições

- Mãos segurando, pessoas, outros objetos ou ambiente de cena no quadro
- Embalagem, base, suporte de exibição (a menos que façam parte do próprio prop)
- Textos, marcas d'água, assinaturas, logos de marcas reais (textos e grafismos impressos no corpo do prop podem permanecer e ser descritos)
- Reflexos de ambiente, luz colorida
- Perspectiva exagerada, deformação, proporções falseadas, corte de bordas

## Salvamento

