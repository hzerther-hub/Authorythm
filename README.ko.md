<!-- 此注释表明此 README 的语言。其它语言的 README 见同目录下的兄弟文件。 -->
> **语言 / Language / 言語 / 언어**: [简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [English](README.en.md) | [日本語](README.ja.md) | **한국어** | [Français](README.fr.md) | [Deutsch](README.de.md) | [Italiano](README.it.md) | [Português](README.pt.md) | [Español](README.es.md) | [Tiếng Việt](README.vi.md) | [Türkçe](README.tr.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [ภาษาไทย](README.th.md)

# 易好短剧 · PySide6 版 / Yihao Shorts (PySide6 Edition)

AI 短剧/小说/漫画一站式制作工具。功能 100% 对齐开源项目 [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版),并集成了两个社区工具的核心能力:
- **[golanse/easymerger](https://github.com/golanse/easymerger)** — 无损视频合并(参数检测/智能直通/一键对齐异类)
- **[liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)** — 同款复刻(爆款视频结构迁移到你的产品)

> 黑盒分析报告: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)

---
<a name="한국어"></a>
# 🎬 이하오 숏드라마 PySide6 판(한국어)

**AI로 만드는 숏드라마·소설·만화 올인원 제작 도구**(Python 3.10+ / PySide6). 오픈소스 [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git)의 전체 기능을 재구현하고, [golanse/easymerger](https://github.com/golanse/easymerger)(무손실 병합)와 [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)(영상 복제)의 핵심 로직을 통합했습니다.

## 🌐 지원 언어 — 15 개

**UI 언어와 AI 출력 언어가 하나의 스위치로 동작**하며 15 개 언어를 지원합니다:

중국어 / English / 日本語 / 한국어 / Français / Deutsch / Italiano / Português / Español / Tiếng Việt / Türkçe / العربية / हिन्दी / Bahasa Indonesia / ภาษาไทย

전환하면 화면 문구와 AI가 생성하는 모든 콘텐츠(대본·에셋·스토리보드·프롬프트·소설·홍보 문구)가 같은 언어로 출력됩니다.

## 주요 기능

- **5 가지 창작 목표**: 소설 / 숏드라마 / 만화 / 홍보 마케팅 / 영상 복제
- **6 단계 워크벤치**: 원문 → AI 각색 → 에셋 → 스토리보드 → 만화 → 병합·내보내기
- **10 종 AI Agent**(System Prompt 전체 편집 가능)
- **멀티 프로바이더 AI**(OpenAI 호환 / Gemini / 버섹 Seedance / MiniMax / 알리 Wan / Agnes / 로컬 얼굴 교체)
- **무손실 병합 도구**: ffprobe 파라미터 일치 검사(해상도/코덱/FPS/Profile) → `-c copy` / 스마트 패스스루 / 이상치 정렬 3 채널 + 실패 폴백
- **소설 제작**: 기획 → 챕터 생성 → 6 항목 검토 → 수정 → 전체 내보내기

## 📊 기능 대응표(원본 Web ↔ 본 데스크톱 버전)

### 원본 모듈 — 전부 대응

| 원본 모듈 | 원본 파일 | 본 버전 | |
|---|---|---|---|
| 프로젝트 런처 | `pages/index.vue` | `ProjectsPage` | ✅ |
| 새 프로젝트(5 목표) | 동일 | `NewProjectDialog` | ✅ |
| 프로젝트 상세 / 회차 목록 | `views/drama/detail.vue` | `ProjectPage` | ✅ |
| 프로젝트 설정 | detail.vue 대화상자 | `ProjectSettingsDialog` | ✅ |
| 에셋 라이브러리 | detail.vue | `AssetDetailDialog` | ✅ |
| 에피소드 스튜디오(6단계) | `episode.vue`(11.6k줄) | `EpisodePage` | ✅ |
| 원문 / AI 각색 | scriptStep | `raw` / `rewrite` 패널 | ✅ |
| 에셋 | prodTab assets | `assets` 패널(일반/만화) | ✅ |
| 스토리보드 / 영상 | prodTab videos | `storyboard` 패널 | ✅ |
| 만화 | prodTab comic | `comic` 패널 | ✅ |
| 병합·내보내기 | prodTab export | `export` 패널 | ✅ |
| 설정(6개 섹션) | `pages/settings.vue` | `SettingsDialog` | ✅ |
| Agent 설정 | settings.vue | System Prompt / Skills 탭 | ✅ |
| 스타일 프리셋 | settings.vue | 20개 시드 + 편집 | ✅ |
| AI 서비스(5종) | settings.vue | `ServiceDialog` | ✅ |
| 얼굴 교체 | `tools/face-swap.vue` | 에셋 캐릭터 카드 내 | ✅ |
| 태스크 패널 | `useTaskDrawer` | `TaskPanel` | ✅ |

### 다국어 깊이 — 원본을 넘어선 부분

| 기능 | 원본 Web | 본 버전 |
|---|---|---|
| UI 언어 | 15 | 15 |
| AI 콘텐츠 언어 | 15 | 15(전역 + **프로젝트별 독립**) |
| Agent 프롬프트 변형 | 4개 고정 | **15개 언어**(150개 파일) |
| Skill 변형 | 4 | **15**(165개 파일) |

### 신뢰성 강화

| 기능 | 목적 |
|---|---|
| LLM 행 타임아웃 | `AI_LLM_TIMEOUT_MS`(기본 300초) — 응답 없는 제공자 대비 |
| 태스크 단계 가시성 | `writing → reviewing → repairing → splitting` 기록 |
| 기록 후 검증 | 성공 여부를 DB로 판정, `content < 200` 은 실패 처리 |
| 스토리보드 백그라운드 분할 | 재진입 방지 + 쓰레기 행 정리 + 6초 폴링 |
| 덮어쓰기 방지 | 본문 있는 회차는 batch 거부, 명시적 "다시 쓰기" 시에만 허용 |
| 중단 태스크 정리 | 재시작 시 실제 산출물 존재 여부로 completed/failed 판정 |
| 참조 이미지 인덱스 | 단일 진실 원천, `@이미지N ≡ reference_image_urls[N-1]` |

### 원본에 없는 추가 기능

| 기능 | 비고 |
|---|---|
| 회차 일괄 생성 | 1~999회 한 번에 삽입 |
| 복선 장부 | LCS≥5 중복 제거, 상한 40, 대화형 토글 |
| 검토 상세 / 전체 검토 목록 | 항목별 체크, 해당 회차로 이동 |
| 회차 전체 음성 읽기 | 600자 분할, 순차 TTS 를 MP3 로 결합 |
| 3구간 진행률 | 성공 / 실패 / 진행 중 + 범례 + 회차별 단계 |
| 제작 단계 바 | 산출물로부터 5단계 판정 |
| 분자 수 진행 | `X / Y 자`, 80% 미만은 호박색 |
| 커버 체계 | 프로젝트 / 회차 커버, 모두 3:4 |
| 속도 적응 TTS | 듀얼 엔진 + 실측 초과 시 재합성 |
| AI 미설정 가드 | 설정/Key 누락 시 버튼 즉시 안내 |
| 자동 업데이트 | Releases 확인 → 백업 덮어쓰기 → 재시작 확인 |
| 무손실 병합 | 파라미터 검사 + 3채널 병합 + 폴백 |
| 동款式 복제 | 바이럴 영상 구조를 내 제품으로 이전 |

## 빠른 시작

```bash
pip install -r requirements.txt   # Python 3.10+
python app/main.py
```

라이선스: CC BY-NC-SA 4.0(원 프로젝트 승계).
