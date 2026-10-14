<!-- 此 README 的语言: hi。所有 16 语言 README 互链,见顶部跳转栏。 -->
[简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Italiano](README.it.md) | [Português](README.pt.md) | [Español](README.es.md) | [Tiếng Việt](README.vi.md) | [Türkçe](README.tr.md) | [العربية](README.ar.md) | **हिन्दी** | [Bahasa Indonesia](README.id.md) | [ภาษาไทย](README.th.md)

# Yihao Shorts · PySide6 संस्करण

> शॉर्ट फ़िल्म, उपन्यास और कॉमिक्स के लिए ऑल-इन-वन AI स्टूडियो — ओपन-सोर्स Web संस्करण के साथ 100% फ़ीचर समता, अब 16 भाषाओं में न्यूरल पढ़ने की सुविधा के साथ.

> 黑盒分析: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)
> 上游项目: [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版) · 集成组件: [golanse/easymerger](https://github.com/golanse/easymerger) · [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)

## ✨ मुख्य विशेषताएँ

🎬 **5 रचनात्मक लक्ष्य**: उपन्यास · लघु फिल्म · कॉमिक · प्रचार (6 प्लेटफ़ॉर्म × 6 प्रारूप) · वायरल-वीडियो क्लोन
🔧 **छह-चरणीय पाइपलाइन**: कच्चा पाठ → AI पुनर्लेखन → दृश्य कहानी → स्टोरीबोर्ड → कॉमिक → मर्ज और निर्यात
🤖 **10 AI एजेंट**: स्क्रिप्ट पुनर्लेखन, पात्र/दृश्य निष्कर्षण, शॉट विभाजन, प्रॉम्प्ट, उपन्यास लेखन, योजना, 6-आयामी समीक्षा, संपादन, कॉमिक विभाजन, प्रचार पाठ — System Prompts पूरी तरह संपादन योग्य
🎙️ **मुफ़्त Edge TTS पढ़ना**: 16 भाषाएँ × 2 लिंग = 32 Microsoft तंत्रिका आवाज़ें, API कुंजी नहीं, भाषा पैक नहीं, केवल इंटरनेट। परियोजना स्तर पर आवाज़ सेटिंग अध्याय को सुसंगत रखती है
🎨 **पैनल-भर संगति**: सामूहिक कॉमिक जनरेशन श्रृंखला keyframe फीडिंग (पिछले पैनल की छवि अगले को पोषित करती है) + `character_variants` बहु-कोण संदर्भों का उपयोग करता है, पात्र और दृश्य पैनलों के बीच स्थिर रहते हैं

## 🚀 त्वरित प्रारंभ

- **आवश्यकताएँ**: Python 3.10+ (3.13 पर विकसित)
- **चलाएँ**: `py -3.13 -m app.main` या `start.bat` पर डबल-क्लिक
- **पूर्ण दस्तावेज़**: [मुख्य README](README.md) देखें

---

📘 **完整文档 / Full docs / Dokümentlar / 文档全貌**: [主 README](README.md) (简中) — 包含「功能对照表」「项目结构」「许可」等全部章节。
