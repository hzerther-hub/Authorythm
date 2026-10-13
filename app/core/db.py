# -*- coding: utf-8 -*-
"""SQLite 数据层:23 张表 DDL(对齐原版 schema)+ 风格种子 + 示例项目种子。"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config

class Row(sqlite3.Row):
    """带 .get() 的 Row —— sqlite3.Row 原生没有 .get(),业务代码里

    反复出现 row.get("字段") 直接 AttributeError 崩溃(实测 episode_page
    _page_title / _gen_image 兜底两处)。在数据层统一兜住:所有查询行
    都自带 .get(),索引/keys()/len 等原有行为不变。
    """

    def get(self, key, default=None):
        try:
            return self[key]
        except (IndexError, KeyError):
            return default


_local = threading.local()


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def get_db() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(config.DB_PATH), timeout=30)
        conn.row_factory = Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def q(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    return get_db().execute(sql, args).fetchall()


def q1(sql: str, args: tuple = ()) -> sqlite3.Row | None:
    return get_db().execute(sql, args).fetchone()


def ex(sql: str, args: tuple = ()) -> int:
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


def exmany(sql: str, rows: list[tuple]) -> None:
    db = get_db()
    db.executemany(sql, rows)
    db.commit()


DDL: list[str] = [
    # 项目
    """CREATE TABLE IF NOT EXISTS dramas (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      style TEXT NOT NULL DEFAULT '3d',
      aspect_ratio TEXT NOT NULL DEFAULT '16:9',
      work_type TEXT NOT NULL DEFAULT 'drama',
      novel_style TEXT, comic_style TEXT,
      novel_outline TEXT, novel_world TEXT, novel_contract TEXT,
      novel_plan TEXT, novel_volume TEXT, novel_chapters TEXT, novel_meta TEXT,
      ethnicity TEXT DEFAULT 'auto',
      creative_description TEXT, skip_creative INTEGER DEFAULT 0, total_episodes INTEGER,
      language TEXT DEFAULT 'auto',
      intro_title TEXT, intro_font TEXT, intro_font_size REAL,
      intro_pos_x REAL, intro_pos_y REAL, intro_duration REAL,
      intro_card INTEGER DEFAULT 1, intro_overlay INTEGER DEFAULT 0,
      metadata TEXT,
      thumbnail TEXT, status TEXT DEFAULT 'pending',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    # 剧集(集)
    """CREATE TABLE IF NOT EXISTS episodes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      drama_id INTEGER NOT NULL,
      episode_number INTEGER NOT NULL,
      title TEXT,
      content TEXT DEFAULT '',
      script_content TEXT DEFAULT '',
      status TEXT DEFAULT 'pending',
      video_url TEXT,
      image_config_id INTEGER, video_config_id INTEGER,
      resolution TEXT DEFAULT '720p',
      target_words INTEGER, review_json TEXT, style_override TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    # 角色 / 造型变体
    """CREATE TABLE IF NOT EXISTS characters (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      drama_id INTEGER NOT NULL,
      name TEXT NOT NULL, role_type TEXT DEFAULT 'supporting',
      appearance TEXT, styling TEXT,
      final_prompt TEXT, final_prompt_style TEXT,
      image_url TEXT, comic_image_url TEXT,
      ethnicity_override TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS character_variants (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      character_id INTEGER NOT NULL,
      label TEXT NOT NULL, tags TEXT, costume_desc TEXT,
      final_prompt TEXT, image_url TEXT, comic_image_url TEXT,
      is_default INTEGER DEFAULT 0, sort_order INTEGER DEFAULT 0,
      created_at TEXT NOT NULL)""",
    # 场景 / 道具
    """CREATE TABLE IF NOT EXISTS scenes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      drama_id INTEGER NOT NULL, episode_id INTEGER,
      name TEXT NOT NULL, location TEXT, time TEXT,
      prompt TEXT, lighting TEXT, setting_tags TEXT,
      final_prompt TEXT, image_url TEXT, comic_image_url TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS props (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      drama_id INTEGER NOT NULL,
      name TEXT NOT NULL, type TEXT DEFAULT 'prop',
      description TEXT, final_prompt TEXT, image_url TEXT, comic_image_url TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    # 剧集关联
    """CREATE TABLE IF NOT EXISTS episode_characters (episode_id INTEGER NOT NULL, character_id INTEGER NOT NULL, PRIMARY KEY(episode_id, character_id))""",
    """CREATE TABLE IF NOT EXISTS episode_scenes (episode_id INTEGER NOT NULL, scene_id INTEGER NOT NULL, PRIMARY KEY(episode_id, scene_id))""",
    """CREATE TABLE IF NOT EXISTS episode_props (episode_id INTEGER NOT NULL, prop_id INTEGER NOT NULL, PRIMARY KEY(episode_id, prop_id))""",
    # 分镜
    """CREATE TABLE IF NOT EXISTS storyboards (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      episode_id INTEGER NOT NULL, scene_id INTEGER,
      storyboard_number INTEGER NOT NULL,
      content TEXT, shot_type TEXT, angle TEXT, movement TEXT,
      image_prompt TEXT, video_prompt TEXT, bgm_prompt TEXT,
      narration TEXT, narration_audio_url TEXT, narration_voice TEXT, narration_duration REAL,
      composed_image TEXT, first_frame_image TEXT, last_frame_image TEXT,
      reference_images TEXT, title TEXT, location TEXT, time TEXT, result TEXT,
      atmosphere TEXT, sound_effect TEXT, description TEXT, subtitle_url TEXT,
      setting_tags TEXT, deleted_at TEXT,
      video_url TEXT, composed_video_url TEXT, duration REAL,
      status TEXT DEFAULT 'pending', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS storyboard_characters (storyboard_id INTEGER NOT NULL, character_id INTEGER NOT NULL, variant_id INTEGER, PRIMARY KEY(storyboard_id, character_id))""",
    """CREATE TABLE IF NOT EXISTS storyboard_props (storyboard_id INTEGER NOT NULL, prop_id INTEGER NOT NULL, PRIMARY KEY(storyboard_id, prop_id))""",
    # 漫画格
    """CREATE TABLE IF NOT EXISTS comic_panels (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      episode_id INTEGER NOT NULL, panel_number INTEGER NOT NULL,
      description TEXT, dialogue TEXT, narration TEXT, composition TEXT,
      image_prompt TEXT, image_url TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS comic_panel_characters (panel_id INTEGER NOT NULL, character_id INTEGER NOT NULL, PRIMARY KEY(panel_id, character_id))""",
    """CREATE TABLE IF NOT EXISTS comic_panel_scenes (panel_id INTEGER NOT NULL, scene_id INTEGER NOT NULL, PRIMARY KEY(panel_id, scene_id))""",
    """CREATE TABLE IF NOT EXISTS comic_panel_props (panel_id INTEGER NOT NULL, prop_id INTEGER NOT NULL, PRIMARY KEY(panel_id, prop_id))""",
    # AI 服务配置
    """CREATE TABLE IF NOT EXISTS ai_service_configs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      service_type TEXT NOT NULL,
      provider TEXT NOT NULL, base_url TEXT NOT NULL,
      api_key TEXT, model TEXT NOT NULL,
      priority INTEGER DEFAULT 0, is_default INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1,
      remark TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    # 风格预设
    """CREATE TABLE IF NOT EXISTS style_presets (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL, value TEXT NOT NULL UNIQUE,
      prompt TEXT NOT NULL, description TEXT,
      work_type TEXT NOT NULL DEFAULT 'all',
      sort_order INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1,
      created_at TEXT NOT NULL)""",
    # 统一任务表
    """CREATE TABLE IF NOT EXISTS sys_task (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      type TEXT NOT NULL,
      drama_id INTEGER, episode_id INTEGER, storyboard_id INTEGER,
      scene_id INTEGER, character_id INTEGER, prop_id INTEGER,
      provider TEXT, model TEXT, params TEXT,
      task_id TEXT, result_url TEXT, local_path TEXT,
      status TEXT DEFAULT 'processing', error_msg TEXT, progress INTEGER DEFAULT 0,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    # 拼接记录
    """CREATE TABLE IF NOT EXISTS video_merges (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      episode_id INTEGER NOT NULL, provider TEXT DEFAULT 'ffmpeg', model TEXT,
      scenes TEXT, merged_url TEXT, status TEXT DEFAULT 'processing',
      error_msg TEXT, duration REAL,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    # 素材库
    """CREATE TABLE IF NOT EXISTS assets (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      url TEXT NOT NULL, thumbnail TEXT, kind TEXT,
      width INTEGER, height INTEGER, duration REAL,
      is_favorite INTEGER DEFAULT 0, created_at TEXT NOT NULL)""",
    # 全局 KV 设置
    "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)",
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_episodes_drama ON episodes(drama_id)",
    "CREATE INDEX IF NOT EXISTS idx_characters_drama ON characters(drama_id)",
    "CREATE INDEX IF NOT EXISTS idx_scenes_drama ON scenes(drama_id)",
    "CREATE INDEX IF NOT EXISTS idx_props_drama ON props(drama_id)",
    "CREATE INDEX IF NOT EXISTS idx_storyboards_ep ON storyboards(episode_id)",
    "CREATE INDEX IF NOT EXISTS idx_panels_ep ON comic_panels(episode_id)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_ep ON sys_task(episode_id)",
    "CREATE INDEX IF NOT EXISTS idx_merges_ep ON video_merges(episode_id)",
]

# ── 风格预设种子(完整复刻原版 stylePresetSeeds,电影质感锚点) ──
STYLE_PRESETS: list[dict] = [
    ("3D 漫剧", "3d", 1, "drama,novel,comic",
     "high-quality 3D CG animation still, modern game-engine cinematic render, Unreal Engine and Pixar grade quality, semi-realistic stylized characters with refined facial features, clean sculpted anatomy, detailed skin shader with subtle subsurface scattering, PBR materials with crisp detailed textures, volumetric cinematic lighting with soft rim light, rich depth of field, polished film color grading, detailed environment art, sharp focus, consistent character design across shots, avoid flat lighting, avoid plastic waxy skin, avoid low-poly blurry look, avoid 2D flat cel shading, avoid anime line art",
     "游戏引擎级 3D 渲染,半写实角色,当前短剧主流的 3D 漫剧质感"),
    ("日漫赛璐璐", "anime", 2, "drama,novel,comic",
     "Japanese TV anime style, clean cel shading with hard-edged shadow shapes, crisp uniform black line art, vivid saturated color palette, expressive large-eyed character design with on-model proportions, detailed hand-painted anime backgrounds, dramatic anime key lighting with screentone highlights, key-visual poster quality, consistent character design across shots, avoid 3D CGI look, avoid painterly soft blending, avoid watercolor texture, avoid photorealism, avoid thick western comic outlines",
     "日式赛璐璐动画风格"),
    ("吉卜力手绘", "ghibli", 3, "drama,novel,comic",
     "Studio Ghibli hand-drawn animation style, soft painterly brushwork with organic hand-crafted line quality, lush warm watercolor painted backgrounds, gentle natural daylight with nostalgic warm glow, muted earthy natural color palette, whimsical cozy storybook atmosphere, subtle film-grain softness, theatrical background art quality, consistent character design across shots, avoid hard cel shading, avoid 3D render look, avoid neon over-saturated colors, avoid sharp digital edges, avoid photorealism",
     "吉卜力手绘治愈风"),
    ("水彩绘本", "watercolor", 4, "drama,novel,comic",
     "delicate watercolor storybook illustration, soft translucent color washes, visible cold-press paper texture, fluid hand-painted brushstrokes with gentle pigment bleeds, light airy atmosphere, harmonious pastel palette, whimsical children book charm, loose expressive edges, consistent character design across shots, avoid bold black outlines, avoid digital airbrush look, avoid harsh contrast, avoid 3D rendering, avoid photorealism",
     "水彩插画质感"),
    ("美式漫画", "comic", 5, "drama,novel,comic",
     "Western graphic-novel comic book style, bold confident black ink outlines, halftone dot shading and screentone gradients, dynamic saturated colors with dramatic contrast, dramatic spotlight lighting, flat graphic print look, sharp inking details, dynamic cinematic composition, consistent character design across shots, avoid painterly soft blending, avoid watercolor washes, avoid photorealistic rendering, avoid 3D CGI look, avoid anime cel shading",
     "美式漫画粗线条风格"),
    ("皮克斯 3D", "disney3d", 6, "drama,novel,comic",
     "Pixar Disney-style 3D CG animation still, soft stylized character design with rounded friendly proportions and appealing cartoon features, large expressive eyes with catchlights, vibrant saturated color palette with warm primaries, soft warm cinematic three-point lighting with gentle rim light, subtle subsurface scattering skin shader, cloth-like soft fuzz on hair and fabrics, whimsical storybook atmosphere, detailed environments with painterly depth of field, consistent character design across shots, avoid photorealistic skin pores and pores detail, avoid horror dark mood, avoid anime line art, avoid cel shading, avoid photorealistic 35mm film look",
     "皮克斯/迪士尼 3D 动画,圆润可爱的造型,鲜艳饱和的色彩,温暖柔和的灯光"),
    ("国风 2.5D", "guofeng", 7, "drama,novel,comic",
     "Chinese guofeng 2.5D illustration style, semi-realistic donghua-quality character art, elegant flowing line work, rich traditional Chinese aesthetic elements, layered ink-wash inspired atmospheric backgrounds, refined silk and fabric textures, soft luminous lighting with gentle haze, sophisticated muted jewel-tone palette, xianxia drama poster quality, consistent character design across shots, avoid flat cel shading, avoid western comic ink style, avoid photorealism, avoid plastic 3D look, avoid modern clothing and props unless specified",
     "国风动画/仙侠剧质感,2.5D 半写实"),
("韩系网漫", "webtoon", 8, "drama,novel,comic",
     "Korean webtoon manhwa style, clean digital painting with soft gradient shading, slim elegant character proportions, large expressive eyes with detailed highlights, soft glowing skin rendering, romantic dreamy lighting, modern pastel-to-vivid color palette, detailed fashion and fabric rendering, webtoon key visual quality, consistent character design across shots, avoid heavy black ink outlines, avoid halftone dots, avoid 3D render look, avoid watercolor paper texture, avoid chibi proportions",
     "韩国条漫/网漫精致上色风"),
    ("治愈系", "healing", 100, "all",
     "healing lifestyle illustration style, soft warm diffused natural lighting, gentle low-saturation pastel palette of peach mint and cream, dreamy shallow depth of field with creamy bokeh, cozy intimate atmosphere, low-contrast filmic color grading with subtle warm glow, organic natural texture, consistent design across frames, avoid harsh shadows, avoid high saturation neon, avoid cyberpunk dark, avoid harsh black outlines, avoid photorealism",
     "治愈系生活插画,小红书/视频号生活方式类"),
    ("ins 风", "ins", 101, "all",
     "Instagram aesthetic minimalist lifestyle photography style, high-key overexposed clean composition, warm beige white and off-white neutral palette, plant life and natural materials, geometric architectural concrete and wood background, casual candid pose, soft natural daylight with bright airy feel, consistent design across frames, avoid heavy filters, avoid dark moody lighting, avoid cartoon illustration, avoid anime style, avoid chinese characters",
     "ins 风极简生活,小红书穿搭/探店/家居"),
    ("赛博朋克", "cyberpunk", 102, "all",
     "cyberpunk neon city style, dominant neon cyan and magenta accent lighting, rain-soaked night city street with reflective wet asphalt, holographic signage and Chinese-katakana neon glyphs, futuristic chrome and glass surfaces, glitch UI overlay accent, dramatic high contrast chiaroscuro, consistent design across frames, avoid warm pastoral palettes, avoid pastel colors, avoid anime cel shading, avoid painterly soft brush, avoid photorealism",
     "赛博朋克霓虹城市,抖音/B站科技/二次元"),
    ("复古港风", "hk_retro", 103, "all",
     "retro Hong Kong cinema style, warm tungsten and amber practical lighting, vintage film grain and slight color bleed, rich saturated reds emerald greens and mustard yellows, dramatic chiaroscuro side lighting, retro typography and signage motif, 80s 90s Hong Kong street vibe, consistent design across frames, avoid clean digital sharp edges, avoid modern flat design, avoid pastel palette, avoid anime cel shading, avoid photorealism",
     "复古港风,小红书/抖音怀旧/时尚"),
    ("国潮", "guochuang", 104, "all",
     "modern Chinese guochuang style, traditional Chinese elements fused with modern graphic design, dominant vermilion and ink-wash splashes, silk brocade texture, dragon cloud pattern accents, symmetrical grand ceremonial composition, gold and red contrast palette, consistent design across frames, avoid western aesthetic, avoid flat cel shading, avoid photorealism, avoid plastic 3D look, avoid neon cyberpunk",
     "国潮文创风,抖音/视频号国风/文创"),
    ("商务科技", "biz_tech", 105, "promotion",
     "modern corporate technology style, cool blue white and silver minimal palette, sleek metallic and glassmorphism surfaces, abstract data flow and particle visualization, clean executive professional headshot lighting, geometric circuit motif accent, premium minimal Apple-style composition, consistent design across frames, avoid warm earthy palettes, avoid cartoon mascot, avoid painterly brush, avoid anime style, avoid retro film grain",
     "商务科技冷调,公众号/B站企业宣传/SaaS"),
    ("医疗健康", "medical", 106, "promotion",
     "clean medical and health style, sterile white with soft sky-blue and mint accents, soft diffused even lighting, warm approachable doctor smile, gentle infographic overlay elements, trustworthy medical iconography in teal and white, consistent design across frames, avoid harsh dramatic shadows, avoid neon cyberpunk, avoid horror moody lighting, avoid cartoon mascot, avoid photorealism",
     "医疗健康蓝白,公众号/视频号医院/医药"),
    ("教育卡通", "edu_cartoon", 107, "promotion",
     "friendly educational cartoon style, rounded friendly mascot character with simple geometric features, playful pastel mint peach yellow and lavender palette, simple flat iconography with hand-drawn doodle accents, encouraging upbeat mood with smiling characters, soft even lighting, consistent design across frames, avoid harsh dramatic shadows, avoid photorealism, avoid cyberpunk neon, avoid horror dark mood, avoid anime cel shading",
     "教育卡通可爱风,视频号/抖音儿童/在线教育"),
    ("餐饮美食", "food", 108, "promotion",
     "appetizing food photography style, warm overhead natural kitchen lighting, visible steam and sizzle effect on hot dishes, vibrant close-up food macro, rich saturated natural food colors, shallow depth of field with creamy background blur, rustic wood table and copper cookware accents, consistent design across frames, avoid cold blue clinical lighting, avoid cartoon illustration, avoid photorealistic harsh shadow, avoid dark moody food, avoid anime cel shading",
     "餐饮美食诱人,抖音/小红书探店"),
    ("财经金融", "finance", 109, "promotion",
     "premium finance and banking style, deep navy with gold and ivory accents, geometric candlestick chart and abstract data motif, classical marble and leather texture accents, executive authority formal composition, premium restrained muted palette with selective gold highlight, consistent design across frames, avoid playful cartoon, avoid neon cyberpunk, avoid warm earthy palette, avoid manga line art, avoid photorealistic harsh shadow",
     "财经金融高冷,公众号/视频号银行/理财"),
    ("极简产品", "minimal_product", 110, "promotion",
     "minimalist product photography style, pure white seamless studio backdrop, single-product hero shot with soft diffused floor shadow, color-block accent in pastel or brand color, clean Apple-style sans-serif typography hint, studio softbox lighting, consistent design across frames, avoid busy cluttered background, avoid warm vintage tone, avoid cartoon illustration, avoid painterly brush, avoid manga line art",
     "极简产品图,适合数码/美妆/家居/全平台"),
    ("真人写实", "live", 120, "all",
     "ultra-realistic cinematic live-action look, professional film photography, natural skin tones with detailed pores and realistic texture, true human anatomy and proportions, shallow depth of field with creamy bokeh, cinematic three-point lighting, subtle film grain, 35mm lens cinematic framing, true-to-life color grading, detailed real-world environments, consistent actor appearance across shots, avoid cartoon or anime features, avoid 3D render look, avoid illustration style, avoid plastic waxy skin, avoid over-smoothing beauty filter",
     "电影级真人质感(注意:真人影像过不了部分平台真人内容审核)"),
]

# 示例项目(与原版演示数据同题材:《归乡的井》两界穿梭第 1 集)
SAMPLE_RAW = """# 归乡的井

王安平四十二岁生日那天,智术科技园区的门禁刷不开他了。

他试了三次,第四次保安从岗亭里探出头,认得他,也认得他手里那个装了十九年杂物的纸箱,于是没拦,只是把闸机旁的侧门推开一条缝。王安平从那条缝里挤出去,肩膀蹭到铁门框,油漆掉了一小块,他没回头看。

纸箱里没有绿萝——那盆绿萝他上周就送给前台小姑娘了。剩下的东西不多:一把用了七年的机械键盘,一副镜腿松了的眼镜,一本翻烂了的《高性能计算架构》,还有一个硬盘盒。

那天下午,人事把他叫进小会议室,递过来劳动合同解除通知书。补偿金按基本工资那一栏算,N+1,二十个月。人事的小姑娘声音压得很低,说王工,公司把月薪拆得细,年终奖、项目奖、股票都不进基数,有公司的算法。

从园区出来,六月的太阳很晃眼。他在停车场站了很久,直到手机响,是他母亲打来的。他接了,说,妈,我过几天回去一趟。

绿皮慢车减速进小站,站台上没几个人,雨水顺着顶棚的缺口往下淌。出站口没有出租车,只有一辆三轮摩托等在雨里。老宅在镇子最东边,院墙是碎砖垒的,塌了半边。墙角那口老井还在,水泥板压着,青苔从缝里挤出来。

父亲是四年前走的。王安平十二岁那年,父亲突然不让靠近那口井了。他问为什么,父亲只说,井底下东西坏了。父亲发现他偷看后打了他一顿,那是父亲唯一一次打他。打完了,父亲蹲在井台边抽了半包烟:记住了,不要靠近那口井。

夜里他是被水声吵醒的。那声音很轻,咕——咕——咕,像是有什么在很深的地方翻了个身。那轻响里,又像隔着好几层墙漏进来一片集市的吵闹。院子里的水龙头早就关了。他想起奶奶说过,井水通着河,河通着山,山底下有个龙王。

王安平没有睁眼。他的手放在床头那块指针停在三点十七分的手表上,像是某种一直在呼吸的东西。"""

SAMPLE_SCRIPT = """## S01 | 外景 · 智术科技园区门口 | 六月午后

六月的阳光白晃晃地刺眼。王安平站在闸机前,手里抱着一个纸箱,刷卡。闸机没反应。他又刷了一次,红灯。第三次,依然是红灯。

保安从岗亭里探出头,看了他一眼,又看了一眼他怀里的纸箱,没说话,伸手把闸机旁的侧门推开一条缝。

王安平侧身从那条缝里挤出去,肩膀蹭到铁门框,铁皮上掉下一小块灰漆。他没回头,径直往外走。

## S02 | 内景 · 智术科技 · 小会议室 | 下午早些时候(回忆)

小会议室的日光灯白得刺眼。人事专员低着头,把一份劳动合同解除通知书推到王安平面前。

人事专员:(没抬头)王工,因业务调整,及个人能力与岗位要求不匹配……您签这儿就行。

王安平看了一眼通知书的补偿条款,提起笔。签字的笔迹横平竖直,跟二十年前刚入职时签的一样。

## S03 | 内景 · 绿皮慢车车厢 | 下午

车厢里暖气开得过了头,玻璃上凝出一层水雾。王安平用袖子擦开一小块,望向窗外。窗外是灰扑扑的平原,电线杆一根接一根地往后倒。

## S04 | 外景 · 王家洼老宅院门 | 黄昏

院墙是碎砖垒的,塌了半边,缺口处爬满枯死的藤。王安平推开吱呀作响的木门。院里的草长到膝盖高。

他站在院子中央,目光落在墙角那口井上。井口的水泥板裂了一道缝,青苔从缝里挤出来,颜色深得发黑。

## S05 | 内景 · 老宅堂屋(童年回忆) | 午后(回忆)

烈日下,十二岁的王安平趴在井沿往下看。黑洞洞的,什么都看不见。

父亲:(远处厉声)安平!

皮带抽在背上,疼得他咬着牙。打完了,父亲蹲在井台边抽烟,抽到最后一根。

父亲:(哑声)记住了,不要靠近那口井。

## S06 | 内景 · 老宅堂屋 · 深夜 | 凌晨

王安平被一阵轻微的咕——咕——咕声吵醒。那声音很轻,像是有什么在很深很深的地方翻了个身。可那轻响里,又像隔着好几层墙漏进来一片集市的吵闹。

水声停了。集市的吵闹也一并断了。他竖着耳朵听了很久,只有自己的心跳。

院子里那口井的方向,又传来一声极轻的咕响。

王安平没有睁眼。他的手放在床头那块停摆的手表上,像是某种一直在呼吸的东西。"""


def init_db() -> None:
    db = get_db()
    for stmt in DDL:
        db.execute(stmt)
    for stmt in INDEXES:
        db.execute(stmt)
    # 增量加列(幂等,对齐原版 sqlite-schema.ts 老库迁移做法)
    for col in ("ALTER TABLE ai_service_configs ADD COLUMN models TEXT",
                "ALTER TABLE ai_service_configs ADD COLUMN temperature REAL",
    "ALTER TABLE episodes ADD COLUMN duration REAL",
                # 每条文本服务配置的最大输出 token(思考型模型需要给足,否则正文被截断)
                "ALTER TABLE ai_service_configs ADD COLUMN max_tokens INTEGER",
                # 造型变体:补排序位与漫画风格图(对齐原版 variant-resolution 的 is_default/sort_order
                # tie-break,以及 comic.ts 的「variant.comicImageUrl 优先」取图优先级)
                "ALTER TABLE character_variants ADD COLUMN sort_order INTEGER DEFAULT 0",
                "ALTER TABLE character_variants ADD COLUMN comic_image_url TEXT",
                "ALTER TABLE ai_service_configs ADD COLUMN settings TEXT",
                "ALTER TABLE dramas ADD COLUMN creative_description TEXT",
                "ALTER TABLE dramas ADD COLUMN skip_creative INTEGER DEFAULT 0",
                "ALTER TABLE dramas ADD COLUMN total_episodes INTEGER",
                "ALTER TABLE storyboards ADD COLUMN reference_images TEXT",
                # 首帧图预审状态:none/generating/pending_review/approved/failed(对齐参考)
                "ALTER TABLE storyboards ADD COLUMN image_status TEXT DEFAULT 'none'",
                "ALTER TABLE storyboards ADD COLUMN title TEXT",
                "ALTER TABLE storyboards ADD COLUMN location TEXT",
                "ALTER TABLE storyboards ADD COLUMN time TEXT",
                "ALTER TABLE storyboards ADD COLUMN result TEXT",
                "ALTER TABLE storyboards ADD COLUMN atmosphere TEXT",
                "ALTER TABLE storyboards ADD COLUMN sound_effect TEXT",
                "ALTER TABLE storyboards ADD COLUMN description TEXT",
                "ALTER TABLE storyboards ADD COLUMN subtitle_url TEXT",
                "ALTER TABLE storyboards ADD COLUMN setting_tags TEXT",
                "ALTER TABLE storyboards ADD COLUMN deleted_at TEXT",
                # 旁白起播时间(用户要求:不必一开始讲,但 default 是 0)
                "ALTER TABLE storyboards ADD COLUMN narration_start REAL DEFAULT 0",
                "ALTER TABLE dramas ADD COLUMN language TEXT DEFAULT 'auto'",
                "ALTER TABLE dramas ADD COLUMN intro_title TEXT",
                "ALTER TABLE dramas ADD COLUMN intro_font TEXT",
                "ALTER TABLE dramas ADD COLUMN intro_font_size REAL",
                "ALTER TABLE dramas ADD COLUMN intro_pos_x REAL",
                "ALTER TABLE dramas ADD COLUMN intro_pos_y REAL",
                "ALTER TABLE dramas ADD COLUMN intro_duration REAL",
                "ALTER TABLE dramas ADD COLUMN intro_card INTEGER DEFAULT 1",
                "ALTER TABLE dramas ADD COLUMN intro_overlay INTEGER DEFAULT 0",
                "ALTER TABLE ai_service_configs ADD COLUMN api_format TEXT DEFAULT 'openai'"):
        try:
            db.execute(col)
        except Exception:  # noqa: BLE001
            pass
    # 风格种子(幂等:存在则跳过)
    for name, value, order, wt, prompt, desc in STYLE_PRESETS:
        db.execute(
            "INSERT OR IGNORE INTO style_presets(name,value,prompt,description,work_type,sort_order,is_active,created_at) VALUES(?,?,?,?,?,?,1,?)",
            (name, value, prompt, desc, wt, order, now()))
    # 默认设置(ui_language_explicit=0:未手选过语言,启动时跟随系统,判断不出回退英文)
    db.execute("INSERT OR IGNORE INTO app_settings(key,value,updated_at) VALUES('content_language','zh',?)", (now(),))
    db.execute("INSERT OR IGNORE INTO app_settings(key,value,updated_at) VALUES('ui_language','zh',?)", (now(),))
    db.execute("INSERT OR IGNORE INTO app_settings(key,value,updated_at) VALUES('ui_language_explicit','0',?)", (now(),))
    db.execute("INSERT OR IGNORE INTO app_settings(key,value,updated_at) VALUES('theme','light',?)", (now(),))
    db.execute("INSERT OR IGNORE INTO app_settings(key,value,updated_at) VALUES('tours_seen','0',?)", (now(),))
    # 恢复中断任务(对齐原版):按"产出是否已落"归位,而不是一律标 failed
    settle_interrupted_tasks(db, now())
    # 首帧预审老数据兜底:first_frame_image 已有内容说明用户隐式批准过(已能出视频),
    # 自动升级 approved,不破坏现有可出视频的分镜(对齐参考 sqlite-schema.ts)
    try:
        cur = db.execute(
            "UPDATE storyboards SET image_status='approved' "
            "WHERE (first_frame_image IS NOT NULL AND first_frame_image != '') "
            "AND (image_status IS NULL OR image_status='none')")
        if cur.rowcount:
            print(f"🖼️ {cur.rowcount} 条历史分镜首帧图已回填为 approved")
    except Exception:  # noqa: BLE001 —— 列还没建出来时忽略(全新库走 DDL 默认值)
        pass
    db.commit()
    _seed_sample_project()


def _seed_sample_project() -> None:
    if q1("SELECT id FROM dramas LIMIT 1"):
        return
    ts = now()
    drama_id = ex(
        "INSERT INTO dramas(title,style,aspect_ratio,work_type,ethnicity,status,created_at,updated_at) VALUES(?,?,?,?,?,'pending',?,?)",
        ("两界穿梭·科技修仙·中年逆袭·经营种田(示例)", "3d", "9:16", "drama", "east_asian", ts, ts))
    ep_id = ex(
        "INSERT INTO episodes(drama_id,episode_number,title,content,script_content,status,resolution,created_at,updated_at) VALUES(?,1,'第1集',?,?, 'scripted','720p',?,?)",
        (drama_id, SAMPLE_RAW, SAMPLE_SCRIPT, ts, ts))
    chars = [
        ("王安平", "lead", "男性,四十二岁,身形清瘦,眼袋沉坠,鬓角零星白发,眼神克制内敛,透出被消磨后的钝重与倦意。",
         "洗旧的深灰夹克,内搭深色衬衫,深色长裤,脚穿旧款皮鞋,单肩旧皮包。"),
        ("母亲", "supporting", "中年女性,五十岁上下,面部皱纹明显,眼神温厚而敏锐,身形微胖,脚步碎而快。",
         "深色棉布上衣,蓝布围裙,黑布鞋。"),
        ("人事专员", "supporting", "年轻女性,二十多岁,五官清秀但表情拘谨,始终低头,肩膀内收。",
         "浅色职业衬衫扎入深色西裤,胸前别公司工牌,低马尾。"),
        ("父亲", "supporting", "中年男性,瘦削黝黑,五官硬朗,皱纹深刻,眼神锐利阴郁,不怒自威。",
         "洗褪色灰夹克,泛黄白汗衫,军绿色解放鞋。"),
    ]
    char_ids = {}
    for name, role, app, sty in chars:
        char_ids[name] = ex(
            "INSERT INTO characters(drama_id,name,role_type,appearance,styling,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (drama_id, name, role, app, sty, ts, ts))
        ex("INSERT INTO episode_characters(episode_id,character_id) VALUES(?,?)", (ep_id, char_ids[name]))
    scenes = [
        ("智术科技园区门口", "现代科技园区入口,金属闸机与人脸识别立柱,侧开锈迹铁皮小门,保安岗亭。", "六月午后强烈日光,冷白偏蓝,冷峻疏离"),
        ("智术科技小会议室", "狭小会议室,长条桌配黑色办公椅,日光灯嵌在白色吊顶,无窗。", "白色日光灯冷光,苍白,压迫疏离"),
        ("绿皮慢车车厢", "老式绿皮火车硬座车厢,墨绿人造革座椅,车窗凝水雾。", "暖黄顶灯,窗外灰白天光,昏暗压抑"),
        ("王家洼老宅院门", "北方乡村老宅,碎砖院墙塌半边,枯藤,木门红漆剥落,院内杂草齐膝。", "黄昏散射光,铅灰,阴郁荒凉"),
        ("老宅堂屋", "灰砖地木梁堂屋,八仙桌漆皮翘起,旧年画,无玻璃窗框。", "黄昏余晖暖橙暗淡,昏黄压抑"),
    ]
    scene_ids = []
    for name, prompt, lighting in scenes:
        sid = ex(
            "INSERT INTO scenes(drama_id,episode_id,name,prompt,lighting,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (drama_id, ep_id, name, prompt, lighting, ts, ts))
        scene_ids.append(sid)
        ex("INSERT INTO episode_scenes(episode_id,scene_id) VALUES(?,?)", (ep_id, sid))
    prop_id = ex(
        "INSERT INTO props(drama_id,name,type,description,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        (drama_id, "上海牌机械手表", "信物",
         "老式国产男士机械表,表盘旧象牙色,边缘铜绿,指针停在三时十七分,深棕皮表带开裂。", ts, ts))
    ex("INSERT INTO episode_props(episode_id,prop_id) VALUES(?,?)", (ep_id, prop_id))
    boards = [
        (1, "【镜头1】中景,王安平站在闸机前,怀里抱着纸箱,抬手刷卡,红灯连亮三次。【镜头2】特写保安岗亭,保安把侧门推开一条缝。【镜头3】中景,王安平侧身挤出,径直往外走。", 9, 0),
        (2, "【镜头1】中景俯视,人事专员把解除通知书推到王安平面前。【镜头2】特写签字,笔迹横平竖直。", 12, 1),
        (3, "【镜头1】中景,车厢内王安平用袖子擦开水雾望向窗外。【镜头2】特写玻璃上模糊的脸。", 8, 2),
        (4, "【镜头1】全景,老宅院门,杂草齐膝。【镜头2】中景,王安平目光落在墙角老井。【镜头3】特写,井口裂缝青苔。", 10, 3),
        (5, "【镜头1】回忆,烈日下十二岁王安平趴在井沿。【镜头2】父亲皮带抽背。【镜头3】父亲蹲井台边抽烟:不要靠近那口井。", 12, 4),
        (6, "【镜头1】深夜,王安平被咕声吵醒睁眼。【镜头2】特写停摆手表。【镜头3】井的方向又传来一声轻响,他没有睁眼。", 10, 4),
    ]
    for num, content, dur, scene_idx in boards:
        ex("INSERT INTO storyboards(episode_id,scene_id,storyboard_number,content,duration,status,created_at,updated_at) VALUES(?,?,?,?,?,'completed',?,?)",
           (ep_id, scene_ids[scene_idx] if scene_idx < len(scene_ids) else None, num, content, dur, ts, ts))
    panels = [
        (1, "四十二岁的王安平站在智术科技园区侧门缝隙旁,手里抱着纸箱,保安从岗亭探身推开侧门,阳光刺眼", "王工,闸机刷不过,从这边走吧。", "构图:中景,侧身构图,浅景深"),
        (2, "小会议室,人事专员低头递过解除通知书,王安平面无表情签字", "王工,公司把月薪拆得细,有公司的算法。你签这儿就行。", "构图:俯视中景,桌面构图"),
        (3, "绿皮慢车车厢,王安平独坐窗边,用袖子擦开水雾,窗外灰扑扑平原", "无", "构图:中景,窗框构图,逆光"),
        (4, "老宅院,碎砖院墙塌了半边,王安平蹲在井边触碰水泥板裂缝青苔", "无", "构图:中景,略俯视,井台为视觉中心"),
        (5, "堂屋昏灯下,王安平从布包取出父亲的手表,指针停在三时十七分", "无", "构图:近景特写,暖黄侧光"),
        (6, "深夜,王安平被井中咕声吵醒,手放在停摆的手表上,没有睁眼", "无", "构图:中近景,月光冷色,低机位"),
    ]
    for num, desc, dial, comp in panels:
        ex("INSERT INTO comic_panels(episode_id,panel_number,description,dialogue,composition,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
           (ep_id, num, desc, dial, comp, ts, ts))


# ── 通用读写助手 ──

def get_setting(key: str, default: str = "") -> str:
    row = q1("SELECT value FROM app_settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    ex("INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
       (key, value, now()))


def style_prompt(style_value: str, ethnicity: str = "", content_lang: str = "") -> str:
    """风格预设提示词 + 人物面孔文化片段(对齐原版 style-preset.ts 的 appendEthnicityFragment)。

    ethnicity 为空时按内容语言推断;角色级覆盖在 prompts_gen 里优先于本函数。
    """
    row = q1("SELECT prompt FROM style_presets WHERE value=? AND is_active=1", (style_value,))
    base = row["prompt"] if row else ""
    if not ethnicity:
        from ..pipeline.ethnicity import LANG_TO_ETHNICITY, DEFAULT_ETHNICITY, append_ethnicity_fragment
        ethnicity = LANG_TO_ETHNICITY.get((content_lang or "").lower(), DEFAULT_ETHNICITY)
    from ..pipeline.ethnicity import append_ethnicity_fragment
    return append_ethnicity_fragment(base, ethnicity)


def drama_style(drama_id: int) -> str:
    row = q1("SELECT style FROM dramas WHERE id=?", (drama_id,))
    return row["style"] if row else "3d"


def touch(table: str, row_id: int) -> None:
    ex(f"UPDATE {table} SET updated_at=? WHERE id=?", (now(), row_id))


def jload(text: str | None, default=None):
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def settle_interrupted_tasks(conn, ts: str, reason: str = "启动清理",
                             min_age_s: float = 0.0) -> tuple[int, int, int]:
    """收尾 processing 任务:有产出 → completed(只是收尾没跑完),否则 failed。

    reason 仅用于日志区分「启动清理」与「运行期巡检」。
    min_age_s:只收尾已「静默」至少这么多秒的任务。启动清理传 0(此刻所有
    processing 都来自已退出的进程,全是孤儿);运行期巡检要传 REAP_INTERVAL_S,
    否则会把本进程正在正常生成的任务误杀 —— 这是本改动最大的回归风险。
    """
    if min_age_s > 0:
        rows = conn.execute(
            "SELECT id, type, episode_id, local_path, result_url, created_at FROM sys_task "
            "WHERE status='processing' "
            "AND (julianday('now') - julianday(created_at)) * 86400.0 >= ?",
            (float(min_age_s),)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, type, episode_id, local_path, result_url, created_at FROM sys_task "
            "WHERE status='processing'"
        ).fetchall()
    done = failed = 0
    for r in rows:
        has_output = bool(r["local_path"])
        if not has_output and r["type"] in ("novel", "novel_batch") and r["episode_id"]:
            ep = conn.execute("SELECT content FROM episodes WHERE id=?", (r["episode_id"],)).fetchone()
            has_output = bool(ep and (ep["content"] or "").strip())
        if has_output:
            conn.execute("UPDATE sys_task SET status='completed', updated_at=? WHERE id=?", (ts, r["id"]))
            done += 1
        else:
            # 措辞不能再写「服务重启」——运行期巡检也会触发,那不是重启
            conn.execute("UPDATE sys_task SET status='failed', error_msg=?, updated_at=? WHERE id=?",
                         (ORPHAN_TASK_ERROR, ts, r["id"]))
            failed += 1
    if rows:
        print(f"[reap] {reason}:已收尾 {len(rows)} 个中断任务"
              f"(已完成 {done} / 失败 {failed})")
    sb_rows = _settle_storyboard_status(conn, ts, min_age_s=min_age_s)
    # 必须在函数内自己提交:启动路径后面还有 init_db 兜底 commit,但运行期巡检
    # 没有调用方,不提交的话 UPDATE 只活在本连接的事务里 —— 巡检日志照打,
    # 界面上的「生成中」永远不变。
    if rows or sb_rows:
        conn.commit()
    return len(rows), done, failed


def _settle_storyboard_status(conn, ts: str, min_age_s: float = 0.0) -> int:
    """收尾卡在 processing 的分镜。

    界面上的「生成中」读的是 storyboards.status(见 EpisodePage._sb_state),而
    settle_interrupted_tasks 只处理 sys_task —— 进程在生成中被杀时,分镜的 status
    会永远停在 'processing',界面上就一直显示"生成中",但其实没有任何任务在跑,
    点重试也没用(按钮被禁用了)。

    已出片的按 completed 归位(可能只是收尾没跑完),其余退回 failed 让用户能重试。
    """
    if min_age_s > 0:
        rows = conn.execute(
            "SELECT id, video_url, composed_video_url, updated_at FROM storyboards "
            "WHERE status='processing' "
            "AND (julianday('now') - julianday(updated_at)) * 86400.0 >= ?",
            (float(min_age_s),)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, video_url, composed_video_url, updated_at FROM storyboards "
            "WHERE status='processing'"
        ).fetchall()
    for r in rows:
        has_output = bool(r["video_url"] or r["composed_video_url"])
        conn.execute("UPDATE storyboards SET status=?, updated_at=? WHERE id=?",
                     ("completed" if has_output else "failed", ts, r["id"]))
    if rows:
        print(f"[reap] 已收尾 {len(rows)} 个中断分镜(状态从 processing 归位)")
    return len(rows)


# 巡检间隔:**必须大于单个任务可能停留在 processing 的最长时间**,否则会把正在正常
# 生成的任务判成僵尸(用户看到「失败」+ 重试按钮,点下去就是重复计费的双份生成)。
#
# 曾经按任务书的说法取 45 分钟,理由是「视频生成约 30 分钟」—— 那个 30 分钟是从
# 参考项目继承的,没对照 pydrama 推导。实际 video_client._poll(…, 10, 300) = 50 分钟
# 跑满单次尝试,叠加限流档 30 分钟尝试间预算,真实上界约 80 分钟。45 < 50,于是跑满
# 轮询的任务有约 11% 概率在还在正常生成时被误杀,重试烧完预算的则高达 78%。
#
# 现取 2 小时:高于 video_client.max_task_processing_s()(~80min),而原始 bug 是
# 挂了 6h20m,仍然修得住(快 3 倍多)。
#
# **改这个值前先看 max_task_processing_s()**,tests/test_stuck_task_watchdog.py 会
# 拿两者对质,别只按"感觉够大"拍。
REAP_INTERVAL_S = 2 * 60 * 60

ORPHAN_TASK_ERROR = "任务已失去回执(服务重启或提交中断),请重试"


def start_stuck_task_watchdog(conn=None, interval_s: float = REAP_INTERVAL_S):
    """周期巡检僵尸生成任务(对齐参考项目 3e1a3f2)。

    settle_interrupted_tasks 只在启动时跑一次,而孤儿任务常产生于**运行期**
    (提交上游阶段崩溃、超时判定丢失),届时无人回收,界面永远显示「生成中」。
    参考项目实测有任务挂了 6 小时 20 分钟。

    巡检时只收尾「静默超过一个间隔」的任务(min_age_s=interval_s),本进程正在
    生成的任务自然被排除 —— 这是本改动最大的回归风险点。

    conn 只作兼容参数,实际不使用:连接是 thread-local 的(见 get_db),主线程
    的连接在巡检线程里一碰就抛 "SQLite objects created in a thread can only
    be used in that same thread",看门狗会静默失效。这里在 tick 里现取,让
    巡检线程拿到属于自己那份连接。
    """
    import threading

    def _tick():
        try:
            settle_interrupted_tasks(get_db(), now(), reason="运行期巡检",
                                     min_age_s=interval_s)
        except Exception as exc:  # noqa: BLE001
            print(f"[reap] 巡检失败: {exc}")
        finally:
            t = threading.Timer(interval_s, _tick)
            t.daemon = True
            t.start()

    t = threading.Timer(interval_s, _tick)
    t.daemon = True          # 否则程序退不出
    t.start()
    return t
