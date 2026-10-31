"""修「串语种」的槽位 —— 某个语种的槽里装的是**别的语种**的译文。

实测抓到的几类:
- 印尼语串进阿拉伯语槽('Belum ada model' 出现在 ar);
- 法语串进日语槽("Aucun instantané d'origine à restaurer" 出现在 ja);
- 中文串进越南语槽('Vá bản vá局部');
- 机翻没翻完,直接留了英文(ar/fr/vi 槽里是 en 的原文);
- 印地语槽里是中文原文。

这些**不会**被漏译判据抓到 —— 漏译判据只比「是不是中文」,
「泰语槽里是英语」对它来说不算漏译。所以要用 scripts/i18n_runtime_check.py
在**运行时**逐语种扫(查原始表没用:各语种主表是从英文表继承的,全是假警报)。

用法:python scripts/i18n_fix_mixed_lang.py
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
    "kbd_r_desc": {
        "tr": "AI kullanmadan belirli kelimeleri mekanik olarak değiştirme: "
              "\"他\" yerine \"她\", \"师父\" yerine \"师尊\" gibi toplu değişiklikler yapma işi.",
    },
    "local_ops": {
        "fr": "Opérations locales",
    },
    "model_no_reference": {
        "hi": "वर्तमान इमेज मॉडल「{0}」रेफ़रेंस इमेज का समर्थन नहीं करता, इसलिए एडिटिंग "
              "टेक्स्ट-टू-इमेज में बदल जाती है और मूल से मेल नहीं खाती। कोई रेफ़रेंस-सक्षम मॉडल चुनें, जैसे Agnes।",
    },
    "no_models_yet": {
        "ar": "لم يتم إدخال اسم النموذج بعد",
    },
    "no_snapshot_to_restore": {
        "ja": "復元できる元画像のスナップショットがありません",
    },
    "restored_original": {
        "ja": "元画像を復元しました",
    },
    "patch_local": {
        "vi": "Bản vá cục bộ",
    },
    "patch_local_tip": {
        "vi": "Bản vá cục bộ: tô phần cần xóa; chỉ phần đó đổi, tỷ lệ giữ nguyên",
    },
    "patch_title": {
        "vi": " Bản vá cục bộ (giữ nguyên, không đổi phần khác)",
    },
    "quick_config": {
        "ar": "إعداد يي هاو السريع",
    },
    "{lab}生成中 {done}/{total} 章…": {
        "ar": "{lab} جارٍ إنشاء الفصول {done}/{total}…",
        "hi": "{lab} अध्याय बनाए जा रहे हैं {done}/{total}…",
    },
    "{} → 剧情推进,本镜着装应已不同于基础形象(置信度 {}%):按剧本语境描写当前服装,不要直接套用参考图妆造": {
        # 原来这里填的是**中文原文**(当时只是把中文从 th 槽挪到 ar 槽,没真翻译),
        # 等于把「串语种」换了个方向继续串。ar 是阿拉伯文,必须给阿拉伯语译文。
        # 与 scripts/i18n_fix_quality.py 的同键条目保持**逐字一致** ——
        # 两个脚本都改这个键,值不一致的话谁后跑谁说了算。
        "ar": "{} → مع تقدم الحبكة، يجب أن تكون ملابس هذه اللقطة مختلفة عن الصورة الأساسية "
              "(درجة الثقة {}%): صِف الملابس الحالية وفق سياق السيناريو، ولا تنقل مكياج "
              "الصورة المرجعية مباشرة",
        "fr": "{} → À mesure que l’intrigue avance, le costume de ce plan devrait avoir changé "
              "par rapport à l’image de base (confiance {}%) : décrivez le costume actuel selon "
              "le contexte du scénario, sans reprendre directement le maquillage de l’image de référence",
    },
    "{}保存失败:{}": {
        "ar": "{} فشل الحفظ: {}",
        "vi": "{} Lưu thất bại: {}",
        "fr": "{} Échec de l’enregistrement : {}",
    },
    "{}起草失败:{}": {
        "ar": "{} فشل المسودة: {}",
        "fr": "{} Échec de la rédaction : {}",
    },
    "易好短剧 · {} {}": {
        "th": "ยี่เฮา ซอร์ตดราม่า · {} {}",
    },
}


def main() -> None:
    """按**槽位下标**改写整行(见 scripts/i18n_rowedit.py 的说明)。

    早先这里用的是 `line.replace(旧值, 新值, 1)`,而同行的 en 槽与目标槽
    **值完全相同**(机翻没翻完,两处都留着同一段英文)→ replace 打到第一个(en 槽),
    目标槽没动、en 槽被写坏,命令却报「成功」。改 3 个键连锁串了 5 个槽。
    必须按槽位下标改。
    """
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
