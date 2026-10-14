<!-- 此 README 的语言: ar。所有 16 语言 README 互链,见顶部跳转栏。 -->
[简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Italiano](README.it.md) | [Português](README.pt.md) | [Español](README.es.md) | [Tiếng Việt](README.vi.md) | [Türkçe](README.tr.md) | **العربية** | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [ภาษาไทย](README.th.md)

# Yihao Shorts · إصدار PySide6

> استوديو ذكاء اصطناعي شامل لكل شيء للأفلام القصيرة والروايات والقصص المصورة — تكافؤ ميزات 100% مع إصدار الويب مفتوح المصدر، مع قراءة صوتية عصبية بـ 16 لغة.

> 黑盒分析: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)
> 上游项目: [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版) · 集成组件: [golanse/easymerger](https://github.com/golanse/easymerger) · [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)

## ✨ الميزات الأساسية

🎬 **5 أهداف إبداعية**: رواية · فيلم قصير · قصة مصورة · ترويج (6 منصات × 6 صيغ) · استنساخ فيديو فيروسي
🔧 **خط أنابيب من 6 مراحل**: نص خام → إعادة كتابة بالذكاء الاصطناعي → قصة بصرية → لوحة تصوير → قصة مصورة → دمج وتصدير
🤖 **10 وكلاء ذكاء اصطناعي**: إعادة كتابة السيناريو، استخراج الشخصيات/المشاهد، تقسيم اللقطات، الموجهات، كتابة الرواية، التخطيط، مراجعة 6 أبعاد، التحرير، تقسيم القصة المصورة، نص ترويجي — جميع System Prompts قابلة للتعديل
🎙️ **قراءة Edge TTS مجانية**: 16 لغة × 2 جنس = 32 صوتًا عصبيًا من Microsoft، لا حاجة لمفتاح API، لا حاجة لحزم لغوية، فقط إنترنت. إعداد الصوت على مستوى المشروع للحفاظ على اتساق الفصل
🎨 **اتساق عبر اللوحات**: توليد القصص المصورة على دفعات يستخدم تغذية keyframe متسلسلة (صورة كل لوحة تغذي التالية) + مراجع متعددة الزوايا من `character_variants`، الشخصيات والمشاهد تبقى ثابتة عبر اللوحات

## 🚀 بداية سريعة

- **المتطلبات**: Python 3.10+ (تم التحقق على 3.13)
- **التشغيل**: `py -3.13 -m app.main` أو انقر مرتين على `start.bat`
- **الوثائق الكاملة**: راجع [README الرئيسي](README.md)

---

📘 **完整文档 / Full docs / Dokümentlar / 文档全貌**: [主 README](README.md) (简中) — 包含「功能对照表」「项目结构」「许可」等全部章节。
