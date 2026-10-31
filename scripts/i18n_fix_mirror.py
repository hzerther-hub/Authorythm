"""修「镜(镜头)」被机翻成「镜子/mirror」的误译。

为什么单独修:中文「镜」在分镜语境是**镜头**(shot / plan / 컷 / ช็อต / cảnh),
不是「镜子」。早期机翻把它当镜子翻,于是短剧软件里出现
「Commentary for this mirror」「全部 5 面镜子(已完成的也重新生成)」
「Iniciar a separação do espelho」这种文案。

本文件是**人工定稿**的逐键逐语种修正表,语种口径对齐项目既有译法:
ar لقطة / hi शॉट / id shot / th ช็อต / vi cảnh / fr plan / de Shot /
es plano / pt plano / it inquadratura / ja カット / ko 컷 / tr sahne / en shot。

**按行定位替换**:同一个译文串可能在文件里出现多次(如 'แยกกระจก'),
所以只在「以该键开头的行」内替换,不做全文替换。

用法:python scripts/i18n_fix_mirror.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import ui_strings as U  # noqa: E402

UI_STRINGS_PY = ROOT / "app" / "core" / "ui_strings.py"

# key -> {lang: 新译文}
FIXES: dict[str, dict[str, str]] = {
    # ── 本镜解说词 ──
    "sb_narration_ph": {
        "en": "Commentary for this shot, ≤200 words",
        "ja": "このカットのナレーション、200文字以内",
        "ko": "이 컷의 내레이션, 200자 이내",
        "ar": "نص السرد الخاص بهذا اللقطة، ≤ 200 كلمة",
        "tr": "Bu sahnenin anlatım metni, en fazla 200 kelime olmalıdır.",
        "vi": "Lời dẫn cho cảnh này, tối đa 200 từ",
        "pt": "Narração desta cena (limite de 200 palavras)",
        "it": "Narrazione di questa inquadratura, ≤200 parole",
    },
    "sb_empty_title": {
        "pt": "Iniciar a separação dos planos",
    },
    # ── 拆分开场 / 结果提示(英文把 storyboard split 当成 mirror)──
    "分镜拆解已开始(后台运行,约 5-10 分钟)": {
        "en": "Storyboard breakdown has started (running in the background, about 5-10 minutes)",
    },
    "分镜拆分超时,请到任务面板查看": {
        "en": "Storyboard split timed out, please check the task panel",
    },
    "分镜拆分完成": {
        "en": "Storyboard split completed",
    },
    "分镜拆分失败": {
        "en": "Storyboard split failed",
    },
    "拆分分镜": {
        "th": "แยกช็อต",
    },
    # ── 镜 → 镜头(片段键,保留原有首尾空白与结构)──
    " → 剧情推进,本镜着装应已不同于基础形象(置信度 ": {
        "ja": "→ 物語が進むにつれ、このカットの服装は基本イメージとは異なるはずです (信頼度",
        "pt": "→ À medida que a trama avança, a aparência deste plano deve diferir da imagem base "
              "(grau de confiança)",
    },
    "{} → 剧情推进,本镜着装应已不同于基础形象(置信度 {}%):按剧本语境描写当前服装,不要直接套用参考图妆造": {
        "th": "{}→พล็อตก้าวหน้าการแต่งกายช็อตนี้ควรแตกต่างจากภาพพื้นฐาน "
              "(ความเชื่อมั่น {}%): อธิบายชุดปัจจุบันตามบริบทของสคริปต์อย่าใช้แต่งหน้าอ้างอิงโดยตรง",
        "de": "{} → Handlung voran: Die Kleidung in diesem Shot sollte vom Basisbild abweichen "
              "(Konfidenz {}%): Beschreiben Sie die aktuelle Kleidung nach Skriptkontext, "
              "übernehmen Sie nicht direkt das Referenz-Make-up",
        "pt": "{} → À medida que a trama avança, a roupa deste plano deve diferir da imagem de base "
              "(confiabilidade {}%): descreva a roupa atual conforme o contexto do roteiro, "
              "não aplique diretamente a maquiagem de referência",
        "it": "{} → Progresso della trama, l'abbigliamento in questa inquadratura è diverso "
              "dall'immagine di base (fiducia {}%): descrivere l'abbigliamento attuale in base "
              "al contesto della sceneggiatura, non applicare direttamente il trucco di riferimento",
    },
    " 个分镜": {
        "it": "Una inquadratura",
    },
    "全部 {} 镜(已完成的也重新生成)": {
        "tr": "Tüm {} planlar (tamamlananlar yeniden oluşturulur)",
        "vi": "Tất cả {} cảnh (kể cả những cảnh đã hoàn thành cũng được tạo lại)",
        "pt": "Todos os planos {} (os concluídos também são regenerados)",
    },
    # ── 其它 ──
    "pop_out_player_tip": {
        "ja": "第 {0} カット · 大画面再生",
    },
    "batch_atmos_tip": {
        "ja": "光+色調+音+全体の雰囲気という4層の基準に従って、エピソード全体がそれぞれのカットの雰囲気を書き換えます。"
              "光は、一致するシーンの光と影の記録から取得されます。",
        "it": "Premere luce + tonalità + suono + atmosfera generale Quattro livelli di specifiche "
              "per riscrivere l'atmosfera di ogni inquadratura, la luce viene prelevata dalla "
              "registrazione della luce e dell'ombra della scena corrispondente",
    },
    "download_project_prompts_tip": {
        "ja": "プロジェクト全作品分のカットプロンプトを1つの TXT にまとめる(話ごとに区切り)",
    },
    # ── 上一轮已改但仍需复核的槽位(已生效则自动跳过)──
    "wt_clone_desc": {
        "th": "อ้างอิงวิดีโอป๊อปอัพ + ภาพถ่ายผลิตภัณฑ์ของคุณ, AI รีเมครุ่นเดียวกันทีละช็อต",
        "de": "Referenz-Viralvideo + Ihr Produktfoto, KI dreht dieselbe Szene Shots für Shots nach",
    },
    " 个镜头(约 ": {
        "vi": " cảnh (khoảng ",
    },
    "生成出镜模特": {
        "de": "Modelle erzeugen",
    },
    "复刻流程:AI 看懂原片出分镜表 → 备好产品/主角素材 → 逐镜重拍 → 按原片节奏无损拼接成片。": {
        "de": "Reproduktionsprozess: KI versteht das Original und erstellt ein Storyboard "
              "→ Produkt-/Hauptfigurenmaterial vorbereiten → Shot für Shot neu drehen "
              "→ verlustfrei im Originalrhythmus zusammengefügt.",
    },
    "分镜带这些标签时优先命中本变体(参考图里出现「战斗服」就选战斗变体)": {
        "th": "โปรดคลิกที่ตัวแปรนี้เมื่อแท็กเหล่านี้ถูกแยกออกจากช็อต "
              "(ตัวแปรการต่อสู้จะถูกเลือกโดยการอ้างอิง \"fightwear\" ที่ปรากฏในภาพ)",
    },
    "分镜还没有画面描述(image_prompt),请先拆分": {
        "th": "ช็อตยังไม่มีคำอธิบายภาพ (image_prompt) โปรดแยกก่อน",
    },
    "仅缺失与失败({} 镜:{})——已有视频不重复生成": {
        "hi": "केवल लापता और विफल ({} शॉट: {}) - मौजूदा वीडियो को दोबारा नहीं बनाया जाता",
    },
}


def main() -> None:
    """按**槽位下标**改写整行(见 scripts/i18n_rowedit.py 的说明)。"""
    from i18n_rowedit import set_rows

    rows: dict[str, list[str]] = {}
    for key, langs in FIXES.items():
        row = U.S.get(key)
        if row is None:
            raise SystemExit(f"键不在补充词典里:{key!r}")
        vals = list(row)
        for lang, new in langs.items():
            vals[U.LANGS.index(lang)] = new
        rows[key] = vals

    n = set_rows(rows)
    print(f"改写 {n} 行,{sum(len(v) for v in FIXES.values())} 个槽位")


if __name__ == "__main__":
    main()
