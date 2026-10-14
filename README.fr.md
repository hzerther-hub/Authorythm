<!-- 此 README 的语言: fr。所有 16 语言 README 互链,见顶部跳转栏。 -->
[简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | **Français** | [Deutsch](README.de.md) | [Italiano](README.it.md) | [Português](README.pt.md) | [Español](README.es.md) | [Tiếng Việt](README.vi.md) | [Türkçe](README.tr.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [ภาษาไทย](README.th.md)

# Yihao Shorts · Édition PySide6

> Studio tout-en-un pour courts métrages, romans et bandes dessinées assistés par IA — 100 % parité avec la version Web open source, avec lecture à voix haute neuronale en 16 langues.

> 黑盒分析: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)
> 上游项目: [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版) · 集成组件: [golanse/easymerger](https://github.com/golanse/easymerger) · [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)

## ✨ Fonctionnalités clés

🎬 **5 objectifs créatifs**: roman · court métrage · bande dessinée · promotion (6 plateformes × 6 formats) · clonage viral
🔧 **Pipeline en 6 étapes**: texte brut → réécriture IA → histoire visuelle → storyboard → bande dessinée → fusion & export
🤖 **10 agents IA**: réécriture de script, extraction personnages/scènes, découpage de plans, prompts, écriture de roman, planification, revue 6 dimensions, édition, découpage BD, texte promo — System Prompts entièrement éditables
🎙️ **Lecture Edge TTS gratuite**: 16 langues × 2 genres = 32 voix neuronales Microsoft, aucune clé API, aucun pack de langue, juste une connexion internet. Réglage voix au niveau projet pour garder le chapitre cohérent
🎨 **Cohérence inter-planches**: la génération par lots de BD utilise un enchaînement keyframe (l'image de chaque planche nourrit la suivante) + références multi-angle `character_variants`, personnages et scènes stables d'une planche à l'autre

## 🚀 Démarrage rapide

- **Prérequis**: Python 3.10+ (validé en 3.13)
- **Lancer**: `py -3.13 -m app.main` ou double-cliquez sur `start.bat`
- **Documentation complète**: voir le [README principal](README.md)

---

📘 **完整文档 / Full docs / Dokümentlar / 文档全貌**: [主 README](README.md) (简中) — 包含「功能对照表」「项目结构」「许可」等全部章节。
