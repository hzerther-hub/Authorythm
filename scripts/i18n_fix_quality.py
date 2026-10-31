"""i18n 第 2 轮质量修复:四类「不是漏译、但用户一眼看得出错」的问题。

第 1 轮把「没翻译」的键全补齐了(漏译 0),但补进来的译文本身还有 4 类毛病。
这 4 类**不会触发任何既有判据**,因为它们都是「有值、但是错的值」:

1. **量词/正文被吞**:译文只剩占位符。
   实测 'items_n'(中文 '{0} 个')有 7 个语种只剩 '{0}' —— 量词「个/件/items」没了,
   界面上就显示成一个孤零零的数字。'＋ 添加{}' 的西语槽、'确定删除「{}」?…'
   的韩语/印地语槽同样被清空。

2. **葡语串进西语槽**:本轮合并的译员把 pt 的译文原样塞进了 es 槽。
   这类**最难发现**:葡语和西语都是拉丁字母,既不含汉字、又不等于英文槽,
   「露中文」和「回落英文」两条判据都抓不到。
   靠**逐字比对**能抓到完全相同的那种;靠**葡语特征词表**能抓到微调过的。

3. **整句留英文**:机翻只翻了半句,后半句(尤其带占位符的)整段留了英文原文。
   ',{} 章失败' 有 6 个语种全是 ',{} Chapter Failure'。

4. **词义错**:同一个键在不同语境下含义不同,译文只按一种语境译。
   最典型的是 '应用':项目里只有 3 处调用,全是 **Apply 按钮**,
   但整行 15 个槽全按「应用程序 / app」译(ja「アプリ」、ko「애플리케이션」、
   fr「Application」…),按钮上写着 "Application"。

用法:python scripts/i18n_fix_quality.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.core import ui_strings as U  # noqa: E402

# key -> {lang: 新译文}(只写要改的槽,没写的槽保持原样)
FIXES: dict[str, dict[str, str]] = {
    # ── 1. 量词/正文被吞 ────────────────────────────────────────────
    "items_n": {
        # 中文 '{0} 个'。英文槽曾只剩 '{0}' —— 量词整个丢了。
        "en": "{0} items",
        "ja": "{0}件",
        "hi": "{0} आइटम",
        "fr": "{0} éléments",
        "pt": "{0} itens",
        "it": "{0} elementi",
    },
    "＋ 添加{}": {
        "es": "+ Añadir {}",
    },
    "确定删除「{}」?该资产的关联记录会一并移除。": {
        "ko": '"{}"을(를) 삭제하시겠습니까? 이 자산의 연결 기록도 함께 삭제됩니다.',
        "hi": 'क्या "{}" को 삭제할지 확인하시겠습니까? 이 자산의 연결된 기록도 함께 제거됩니다.',
    },
    # ── 2. 葡语串进西语槽 ────────────────────────────────────────────
    "从 Unsplash / Pexels / Pixabay 搜参考图,选中后作为本次改图的源图": {
        "es": "Busque imágenes de referencia en Unsplash / Pexels / Pixabay; la elegida será la fuente de esta edición",
    },
    "以上八项在「应用调整」时按全分辨率计算": {
        "es": "Los ocho anteriores se calculan a resolución completa al pulsar «Aplicar»",
    },
    "修复分镜中": {
        "es": "Reparando los storyboards",
        "pt": "Reparando os storyboards",
    },
    "找不到聊天改图入口,请从主窗口的图片处理页发送": {
        "es": "No se encontró la edición de imagen del chat: envíala desde la página de procesamiento de imágenes",
    },
    "转到聊天改图(支持大图)": {
        "es": "Ir a la edición de imagen del chat (admite imágenes grandes)",
    },
    # ── 3. 整句留英文 ────────────────────────────────────────────────
    ",{} 章失败": {
        "de": ",{} Kapitel fehlgeschlagen",
        "es": ",{} capítulo fallido",
        "fr": ",{} chapitre en échec",
        "it": ",{} capitolo non riuscito",
        "pt": ",{} capítulo falhou",
        "vi": ",{} chương thất bại",
    },
    "{} 角色 · {} 场景 · {} 集": {
        "tr": "{} karakter · {} sahne · {} bölüm",
        "vi": "{} nhân vật · {} cảnh · {} tập",
        "pt": "{} personagens · {} cenas · {} episódios",
    },
    "✅ 已是最新版本(v{})": {
        "de": "✅ Bereits die neueste Version (v{})",
    },
    "【修改要求】{}": {
        "pt": "[Requisitos de modificação] {}",
    },
    "尚未写作(目标 {} 字)": {
        "pt": "Ainda não escrito (alvo de {} palavras)",
    },
    "复古港风": {
        "tr": "Retro Hong Kong tarzı",
    },
    "故事合约: ": {
        "de": "Story-Vertrag:",
        "pt": "Contrato de História:",
    },
    "下载": {
        "pt": "Baixar",
    },
    # ── 4. 词义错 ───────────────────────────────────────────────────
    "shot_n": {
        # de 槽把「镜头」翻成了「眼镜」(Gläser),pt 翻成「Específicos」(细节)。
        "de": "Storyboard {0}",
        "pt": "Storyboard {0}",
    },
    "应用": {
        # 项目里只有 3 处调用,全是 Apply 按钮,不是「应用程序」。
        "en": "Apply",
        "ja": "適用",
        "ko": "적용",
        "hi": "लागू करें",
        "id": "Terapkan",
        "th": "ใช้งาน",
        "tr": "Uygula",
        "vi": "Áp dụng",
        "fr": "Appliquer",
        "de": "Anwenden",
        "es": "Aplicar",
        "pt": "Aplicar",
        "it": "Applica",
    },
    # ── 5. 葡语槽自身错(译员把「角色」翻成了「职能」)────────────────
    " 个角色(角色已同步到资产库)": {
        "pt": "Um personagem (o personagem foi sincronizado com o banco de ativos)",
    },
    "已保存:{} 章计划 · {} 个角色(角色已同步到资产库)": {
        "pt": "Salvado: {} planos de capítulo · {} personagens "
              "(os personagens foram sincronizados com o repositório de ativos)",
    },
    "新书已创建:《{}》· {} 个角色 · 计划 {} 章": {
        "pt": "Novo livro criado: «{}» · {} personagens · {} capítulos planejados",
    },
    "分析完成:{} 章已归为仿写档案": {
        "pt": "Análise concluída: {} capítulos arquivados como arquivo de imitação",
    },
    "批量完成:{} 章成功": {
        "pt": "Conclusão em lote: {} capítulos com sucesso",
    },
    "已填入简介与题材,确认无误后点保存": {
        "pt": "A descrição e o gênero foram preenchidos. Clique em Salvar para confirmar.",
    },
    "状态台账门控(TypeSafe AI):长篇连续性自动判读。未配置时台账照常维护,只是不做矛盾判定": {
        "pt": "Controle de portão do registro de estado (TypeSafe AI): interpretação automática da "
              "continuidade longa. Sem configuração, o registro é mantido normalmente, apenas sem "
              "julgamento de contradições.",
    },
    "生成 {} 章计划中": {
        "pt": "Gerando o plano de {} capítulos",
    },
    "将重新生成这 {} 章,已有正文会被覆盖且无法撤销。确定继续?": {
        "pt": "Regenerar estes {} capítulos? O conteúdo existente será sobrescrito e não poderá ser "
              "desfeito. Tem certeza de continuar?",
    },
    # ── 6. 死键的错译('第 ' 是碎片键,ja 槽原本是「いいえ。」= 不)────
    "第 ": {
        "ja": "第",
    },
    # ── 7. 不用汉字的语种漏出中文(ar/hi/th)────────────────────────
    # 这三个语种**不使用汉字**,槽里出现汉字 = 中文漏出来了。
    # 既有判据为什么都抓不到:
    #   · 漏译判据要求与中文基准**逐字相同** —— 差一个字(妆造 vs 妆容)就逃逸;
    #   · 运行时体检对非拉丁语种的判据是「没有本族文字却有拉丁字母」,
    #     而中文**没有拉丁字母** → 两个方向都漏。
    "tts_gender_hint": {
        # 'يتح切换' = 阿拉伯语词根里塞了个汉字「切换」
        "ar": "Edge TTS صوت عصبي مجاني، يتغير حسب لغة النص؛ لا حاجة لتنزيل حزمة لغوية، "
              "يكفي الاتصال بالإنترنت",
    },
    "{} → 剧情推进,本镜着装应已不同于基础形象(置信度 {}%):按剧本语境描写当前服装,不要直接套用参考图妆造": {
        # 整槽是中文原文
        "ar": "{} → مع تقدم الحبكة، يجب أن تكون ملابس هذه اللقطة مختلفة عن الصورة الأساسية "
              "(درجة الثقة {}%): صِف الملابس الحالية وفق سياق السيناريو، ولا تنقل مكياج "
              "الصورة المرجعية مباشرة",
    },
    "concept_ref_note_ph": {
        # '要求出现这个场景' 是中文
        "ar": "كيف تُستخدم الصورة {n}؟ مثال: اطلب ظهور هذا المشهد في الحلقة 1",
    },
    "正在补第 {a}-{b} 卷的细节…": {
        # '第 ' 是中文
        "hi": "खंड {a}-{b} का विवरण भरा जा रहा है…",
    },
    "人物三视图已重建,重新生成首帧即可生效": {
        # 结尾的「生效」是中文
        "th": "สร้างภาพสามมุมมองใหม่แล้ว สร้างเฟรมแรกใหม่เพื่อให้มีผล",
    },
    # ── 8. 语言列表:ja/id/th 三个语种共用中文列表 + 标签重复词 ──────
    # 11 个语种把列表里的语言名翻成了自己语言(zh 用中文母语名,天然正确),
    # 但 ja/id/th 三行**整行照抄了中文列表** → 泰语/印尼语用户看到的是中文语言列表。
    "语言 / Languages: {}(中文/EN/日本語/한국어/Français/Deutsch/Italiano/Português/Español/Tiếng Việt/Türkçe/العربية/हिन्दी/Bahasa Indonesia/ภาษาไทย)": {
        "ja": "言語 / Languages: {}(中国語/英語/日本語/韓国語/フランス語/ドイツ語/イタリア語/"
              "ポルトガル語/スペイン語/ベトナム語/トルコ語/アラビア語/ヒンディー語/"
              "インドネシア語/タイ語)",
        "id": "Bahasa / Languages: {}(Mandarin/Inggris/Jepang/Korea/Prancis/Jerman/Italia/"
              "Portugis/Spanyol/Vietnam/Turki/Arab/Hindi/Bahasa Indonesia/Thai)",
        "th": "ภาษา: {}(ภาษาจีน/อังกฤษ/ญี่ปุ่น/เกาหลี/ฝรั่งเศส/เยอรมัน/อิตาลี/โปรตุเกส/"
              "สเปน/เวียดนาม/ตุรกี/อาหรับ/ฮินดี/บาฮาซาอินโดนีเซีย/ไทย)",
        # 下面两个是标签/列表的**前缀重复词**(机翻照抄了「X / Y」双语模式)
        "vi": "Ngôn ngữ: {}(Tiếng Trung/EN/Tiếng Nhật/Tiếng Hàn/Tiếng Pháp/Tiếng Đức/Tiếng Ý/"
              "Tiếng Bồ Đào Nha/Tiếng Tây Ban Nha/Tiếng Việt/Tiếng Thổ Nhĩ Kỳ/Tiếng Ả Rập/"
              "Tiếng Hindi/Tiếng Indonesia/Tiếng Thái)",
    },
    "语言 / Languages: ": {
        # 机翻把「语言 / Languages」这个双语标签模式照抄成同一个词两遍
        "tr": "Diller:",
        "th": "ภาษา:",
        "vi": "Ngôn ngữ:",
        "pt": "Idiomas:",
    },
}


def main() -> None:
    """按**槽位下标**改写整行(见 scripts/i18n_rowedit.py 的说明)。"""
    from i18n_rowedit import set_rows

    rows: dict[str, list[str]] = {}
    slots = 0
    for key, langs in FIXES.items():
        row = U.S.get(key)
        if row is None:
            raise SystemExit(f"键不在补充词典里:{key!r}")
        vals = list(row)
        for lang, new in langs.items():
            if lang not in U.LANGS:
                raise SystemExit(f"未知语种 {lang!r}(键 {key!r})")
            vals[U.LANGS.index(lang)] = new
        rows[key] = vals
        slots += len(langs)

    n = set_rows(rows)
    print(f"改写 {n} 行,{slots} 个槽位")


if __name__ == "__main__":
    main()
