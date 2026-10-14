<!-- 此 README 的语言: pt。所有 16 语言 README 互链,见顶部跳转栏。 -->
[简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Italiano](README.it.md) | **Português** | [Español](README.es.md) | [Tiếng Việt](README.vi.md) | [Türkçe](README.tr.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [ภาษาไทย](README.th.md)

# Yihao Shorts · Edição PySide6

> Estúdio IA tudo-em-um para curtas-metragens, romances e quadrinhos — 100% de paridade com a versão Web open source, agora com leitura em voz alta neural em 16 idiomas.

> 黑盒分析: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)
> 上游项目: [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版) · 集成组件: [golanse/easymerger](https://github.com/golanse/easymerger) · [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)

## ✨ Recursos principais

🎬 **5 objetivos criativos**: romance · curta-metragem · quadrinho · promoção (6 plataformas × 6 formatos) · clonagem viral
🔧 **Pipeline de 6 etapas**: texto bruto → reescrita IA → história visual → storyboard → quadrinho → fusão & exportação
🤖 **10 agentes de IA**: reescrita de roteiro, extração de personagens/cenas, divisão de planos, prompts, escrita de romance, planejamento, revisão 6 dimensões, edição, divisão de quadrinho, texto promo — System Prompts totalmente editáveis
🎙️ **Leitura Edge TTS gratuita**: 16 idiomas × 2 gêneros = 32 vozes neurais Microsoft, sem chave API, sem pacotes de idioma, só internet. Configuração de voz no nível do projeto para manter o capítulo coerente
🎨 **Coerência entre painéis**: a geração em lote de quadrinhos usa encadeamento de keyframes (a imagem de cada painel alimenta o próximo) + referências multi-ângulo `character_variants`, personagens e cenas estáveis entre os painéis

## 🚀 Início rápido

- **Requisitos**: Python 3.10+ (testado em 3.13)
- **Executar**: `py -3.13 -m app.main` ou clique duplo em `start.bat`
- **Documentação completa**: veja o [README principal](README.md)

---

📘 **完整文档 / Full docs / Dokümentlar / 文档全貌**: [主 README](README.md) (简中) — 包含「功能对照表」「项目结构」「许可」等全部章节。
