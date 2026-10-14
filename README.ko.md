<!-- 此 README 的语言: ko。所有 16 语言 README 互链,见顶部跳转栏。 -->
[简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [English](README.en.md) | [日本語](README.ja.md) | **한국어** | [Français](README.fr.md) | [Deutsch](README.de.md) | [Italiano](README.it.md) | [Português](README.pt.md) | [Español](README.es.md) | [Tiếng Việt](README.vi.md) | [Türkçe](README.tr.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [ภาษาไทย](README.th.md)

# 이하오 숏드라마 · PySide6 판

> AI 단편 드라마 / 소설 / 만화를 한 번에 제작하는 도구. 오픈소스 Web 버전과 100% 기능 동등, 16개 언어 신경망 음성 낭독 통합.

> 黑盒分析: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)
> 上游项目: [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版) · 集成组件: [golanse/easymerger](https://github.com/golanse/easymerger) · [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)

## ✨ 핵심 기능

🎬 **5가지 창작 목표**: 소설 · 단편 드라마 · 만화 · 홍보(6 플랫폼 × 6 형식) · 동급 복제
🔧 **6단계 파이프라인**: 원문 → AI 윤문 → 비주얼 스토리 → 스토리보드 → 만화 → 병합 내보내기
🤖 **10종 AI Agent**: 대본 개작, 캐릭터/장면 추출, 샷 분할, 프롬프트, 소설 생성, 기획, 6차원 심사, 윤문, 만화 분할, 홍보문 — System Prompt 전부 편집 가능
🎙️ **무료 Edge TTS 낭독**: 16개 언어 × 2성별 = 32개 Microsoft 신경망 voice, API Key 불필요, 언어 팩 불필요, 인터넷만 있으면 됨. 프로젝트 단위로 낭독 음성 통일
🎨 **컷 간 일관성**: 만화 일괄 생성은 연쇄 키프레임 공급(이전 컷 이미지를 다음 컷에) + `character_variants` 다각도 참조로, 캐릭터와 장면이 컷을 넘어 안정

## 🚀 빠른 시작

- **요구 사항**: Python 3.10+ (개발 검증 3.13)
- **실행**: `py -3.13 -m app.main` 또는 `start.bat` 더블 클릭
- **전체 문서**: [메인 README](README.md) 참조

---

📘 **完整文档 / Full docs / Dokümentlar / 文档全貌**: [主 README](README.md) (简中) — 包含「功能对照表」「项目结构」「许可」等全部章节。
