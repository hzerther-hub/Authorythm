# -*- coding: utf-8 -*-
"""同款复刻(video-clone-lite 逻辑):看懂原片 → 备新料 → 逐镜重拍 → 按原片节奏拼接。

数据落在 dramas.metadata.clone:* 与 sys_task(type=clone_*)。
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import uuid
from pathlib import Path

from ..agents import runner
from ..ai import image_client, text_client, video_client
from ..core import config, db

# 单镜**内容**字数上限(不含风格前缀与尾部一致性约束)。
#
# 参考项目 video-clone-lite/references/seedance-knowledge.md 给的是「单镜头提示词
# ≤200 字(建议 120)」,那是**中文**口径。rewrite 产出的 prompt 是**英文**,信息密度
# 大得多(实测本项目 6 镜内容 366-509 字符),按 200 砍会把每镜砍掉一半 ——
# 砍掉的正是「白色纸盒」「口红」这类产品名,模型看不到就只能自由发挥,
# 结果 6 镜全画成同一张「沙发上女性」插画。
# 800 是实测校准出来的:rewrite 产出的英文重绘句实测 435–522 字符
# (4 镜全部超出)。原先设 400 导致**每一镜都被截断**,而截掉的恰好是句尾的
# 运镜与氛围(fixed camera / cinematic shallow depth of field)—— 那正是
# 「复刻原片节奏」的核心信息,丢了等于白复刻。
# 上限仍要存在:超长提示词是模型信息过载的主因,但这个量级(≤800)远未过载。
SHOT_PROMPT_MAX_CHARS = 800


def _meta(drama_id: int) -> dict:
    d = db.q1("SELECT metadata FROM dramas WHERE id=?", (drama_id,))
    return db.jload(d["metadata"], {}) if d else {}


def _save_meta(drama_id: int, meta: dict) -> None:
    db.ex("UPDATE dramas SET metadata=?, updated_at=? WHERE id=?",
          (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))


def import_reference(drama_id: int, video_path: str | Path) -> dict:
    """导入参考视频(拷入 data/static/uploads),记录元数据。"""
    src = Path(video_path)
    dst = config.STATIC_DIR / "uploads" / f"ref_{uuid.uuid4().hex[:10]}{src.suffix or '.mp4'}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
    meta = _meta(drama_id)
    meta["clone"] = {**meta.get("clone", {}), "reference": str(dst)}
    _save_meta(drama_id, meta)
    return {"path": str(dst), "size": dst.stat().st_size}


def upload_material(drama_id: int, kind: str, image_path: str | Path) -> str:
    """上传素材:kind = product(产品图,必须)/ presenter(出镜人照片,可选)。"""
    src = Path(image_path)
    dst = config.STATIC_DIR / "uploads" / f"{kind}_{uuid.uuid4().hex[:10]}{src.suffix or '.png'}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
    meta = _meta(drama_id)
    clone = meta.get("clone", {})
    clone[kind] = str(dst)
    meta["clone"] = clone
    _save_meta(drama_id, meta)
    return str(dst)


def replace_material(drama_id: int, kind: str, image_path: str | Path,
                     config_id: int | None = None) -> str:
    """项目内换素材(产品图 / 出镜人照片),返回新素材路径。

    换产品图时**必须同步重读 product_desc**:它是建项目时用多模态模型看图写死的
    一句话描述,直接注入 generate_shot_image 的提示词。不刷新的话,提示词里还在
    描述旧产品(比如"翠绿色玉镯"),新图会被旧文案拖偏 —— 这是换产品后画面仍不对
    的头号原因,所以这里宁可多花一次模型调用也不能沿用旧描述。

    已生成的首帧不会自动重跑:重生成要花一次生图额度,而且用户可能只想先看素材
    换没换成功。由界面提示用户点「重绘」逐镜刷新。
    """
    if kind not in ("product", "presenter"):
        raise ValueError(f"未知素材类型:{kind}")
    path = upload_material(drama_id, kind, image_path)
    meta = _meta(drama_id)
    clone = meta.get("clone", {})
    # 换完立刻同步资产:资产图是跨镜一致性锚点,不更新它 = 后面 6 镜还锁着旧脸/旧产品。
    # 资产表优先于 metadata 原图(见 generate_shot_image 取图顺序),这里漏更新过一次,
    # 表现为换完照界面缩略图是新的、生图却还是旧脸。
    url = config.path_to_media_url(path)
    if kind == "product":
        cid, pid, _sid = sync_assets(drama_id, config_id=config_id)
        if pid:
            clone["product_asset_id"] = pid
        if cid:
            clone["presenter_asset_id"] = cid
        desc = read_product_desc(path, config_id=config_id)
        if desc:
            clone["product_desc"] = desc
        else:
            # 读图失败不能静默:删掉旧描述,让 generate_shot_image 退回"见产品图",
            # 好过拿旧产品的文案去描述新图
            clone.pop("product_desc", None)
    else:
        cid, pid, _sid = sync_assets(drama_id, config_id=config_id)
        if cid:
            clone["presenter_asset_id"] = cid
        if pid:
            clone["product_asset_id"] = pid
    meta["clone"] = clone
    _save_meta(drama_id, meta)
    return path


def extract_frames(video_path: str | Path, count: int = 8) -> list[Path]:
    """ffmpeg 均匀抽帧(供视觉模型理解原片)。"""
    ff = config.find_ffmpeg()
    if not ff:
        raise RuntimeError("未找到 ffmpeg")
    out_dir = config.STATIC_DIR / "uploads" / f"frames_{uuid.uuid4().hex[:8]}"
    out_dir.mkdir(parents=True, exist_ok=True)
    fps_expr = f"{count}/{_duration(video_path) or 15:.2f}"
    subprocess.run([ff, "-y", "-i", str(video_path), "-vf",
                    f"fps={fps_expr},scale=640:-2",
                    "-frames:v", str(count), str(out_dir / "f%02d.jpg")],
                   capture_output=True, timeout=180)
    frames = sorted(out_dir.glob("f*.jpg"))
    if not frames:
        raise RuntimeError("抽帧失败,请检查视频文件")
    return frames


def _duration(video_path: str | Path) -> float:
    fp = config.find_ffprobe()
    if not fp:
        return 0.0
    out = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(video_path)], capture_output=True, text=True, timeout=30)
    try:
        return float(out.stdout.strip())
    except Exception:  # noqa: BLE001
        return 0.0


def _image_data_url(path: str | Path, mime: str = "image/jpeg") -> str:
    import base64
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def read_presenter_desc(presenter_path: str | Path,
                       config_id: int | None = None) -> dict | None:
    """多模态读你上传的人物照,提取**外观 + 服装**描述,供纯文字生图使用。

    为什么需要它:分镜参考图必须**不含任何氛围/背景元素**,否则模型会把原照的
    背景光影当成画面内容(实测:红橙舞台背景 → 生成出两个半透明发光人影,
    且会被原样带进每张分镜)。所以全身像改成纯文字生成 + 换脸,长相与服装
    就得从这张原照里「读」出来。

    返回 {"appearance": 外观, "styling": 服装},失败返回 None。
    """
    p = Path(str(presenter_path))
    if not p.exists():
        return None
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    prompt = """这张照片是一个带货视频里要出镜的真人模特。请只描述**这个人本身**,
**完全忽略背景、灯光、道具、画面氛围**,输出 JSON:
{
 "appearance": "外观:性别年龄、脸型、五官特征、肤色、发型发色(30字内)",
 "styling": "服装:上衣/下装的款式与颜色、面料质感、配饰首饰(40字内)",
 "footwear": "鞋履与下肢配件:鞋子款式与颜色、袜子、裤脚露出情况(25字内)"
}
要求:
1. 只写照片里**真实可见**的特征,**不要臆造**;
2. **画面里看不到脚或鞋时,footwear 留空字符串**,不要猜测;
3. 不要写背景描述。"""
    try:
        raw = text_client.chat(prompt, temperature=0.3, max_tokens=1024,
                               json_mode=True, config_id=config_id,
                               image_urls=[_image_data_url(p, mime)])
        data = runner.extract_json(raw) or {}
        app_ = str(data.get("appearance") or "").strip()
        sty = str(data.get("styling") or "").strip()
        shoe = str(data.get("footwear") or "").strip()
        if shoe:                      # 鞋履单独一栏,拼进服装描述一起喂给生图
            sty = f"{sty}, 穿{shoe}" if sty else f"穿{shoe}"
        return ({"appearance": app_, "styling": sty, "footwear": shoe}
                if (app_ or sty) else None)
    except Exception as exc:  # noqa: BLE001
        print(f"[clone] 人物描述提取失败: {exc}", flush=True)
        return None


def read_product_desc(product_path: str | Path, config_id: int | None = None) -> str | None:
    """多模态读产品图,产出注入生成提示词的产品描述(供 clone.product_desc 落库)。

    独立于分镜分析的小调用:图与视频帧不混传,避免干扰分镜判断;失败返回 None。
    """
    p = Path(product_path)
    if not p.exists():
        return None
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    prompt = """这张图片是带货视频要推广的产品照片。请识别并输出一段用于文生图/文生视频提示词的产品描述:
- 产品类别与形态(如"圆柱形保温杯")
- 颜色与材质质感
- 1-3 个最有辨识度的外观细节
- 适合画面呈现的一句话使用场景
只输出 JSON:{"product_desc": "一句话中文描述(60字内),串起上述要点,不含品牌名"}"""
    raw = text_client.chat(prompt, temperature=0.3, max_tokens=512, json_mode=True,
                           config_id=config_id, image_urls=[_image_data_url(p, mime)])
    data = runner.extract_json(raw)
    if isinstance(data, dict):
        desc = str(data.get("product_desc") or "").strip()
        return desc or None
    return None


REWRITE_PROMPT = """下面是一条带货视频的**镜头节奏表**,以及用户要推广的**新产品**。

【原片镜头节奏表】{boards}
【新产品描述】{product_desc}
【新出镜人物描述】{presenter_desc}

任务:沿用原片的**镜头节奏**,但把每一镜的**画面内容整个换成新产品**。

═══ 必须照抄的(这是「复刻」的本质,一个字都不能改)═══
- number / start / end —— 每镜的编号与起止秒数
- shot(景别)、camera(运镜方式)、line(台词)—— 完全沿用

═══ 必须完全重新设计的(原片的动作一律作废)═══
- action / action_steps / product_use / prompt

**为什么动作要整个丢掉重写**:用户的新产品与原片产品**品类往往不同**。
例:原片是口红(动作是"开盒→取出→涂抹→展示上色"),新产品是玉手镯
(动作只能是"陈列→拿起→试戴→特写"),两者根本没有共通的动作序列。
硬套原片动作只会得到两种坏结果:要么画面里还是原产品,要么凭空造出
新产品根本不存在的东西(实测手镯被改写成了"白色纸盒 + 膏体")。

所以 action_steps 必须由**新产品自身的使用方式**推导,每步都是该产品
真实存在的动作。步数保持与原片相同(节奏对齐),但内容重新想。

═══ 铁律 ═══
1. 输出里**不得出现原片的任何具体产品名、部件名、包装**(如"口红""膏体"
   "纸盒""膏体色号"这类原片特有物)。
2. **不得臆造新产品描述里没有的物件**。没写"包装盒"就不许出现盒子。
3. 只使用新产品描述里明确写出的形态、颜色、材质与场景。
4. 出镜人物沿用【新出镜人物描述】。
5. **连同原片的「包装形态」一起清除**。原片若出现快递盒/纸盒/礼盒/管状容器/
   开箱动作,一律不许沿用 —— 除非新产品描述里明确写明有此包装(实测:新产品是
   翡翠手镯,改写却保留"快递盒置于桌面""从纸盒中取出",包装形态原封不动,
   画面仍是旧货)。新产品没有写包装 = 画面里就不该出现任何盒子/管子。

逐镜输出 JSON:{{"storyboards":[...]}},字段:
number, start, end, shot, camera, action, action_steps, line, product_use, prompt

其中 prompt 是该镜的重绘提示词(英文),必须满足:
- 只描述**新产品与新人物**,原片产品与原片包装一个字都不许出现
- 写出时间锚点(如"0-4 seconds: ..."),必须与该镜 start/end 一致
- 只讲一个重点,只用一种主运镜"""


def rewrite_boards_for_product(boards: list[dict], product_desc: str,
                               presenter_desc: str = "", config_id: int | None = None) -> list[dict]:
    """按新产品改写分镜表 —— 让「换掉原片产品」真正成立的关键一步。

    **保留什么**:每镜的 number/start/end/shot/camera/line —— 即「节奏与镜头语言」。
    **重新设计什么**:action/action_steps/product_use/prompt —— 即「画面内容」。

    **为什么动作要整个重设计而不是照搬**(实测踩坑):用户的 新产品 与原片产品
    **品类常常不同**。实测案例:原片是口红带货片(动作链「开盒→取出→涂抹→
    展示上色」),新产品是玉手镯(动作只能是「陈列→拿起→试戴→特写」),两者
    没有共通的动作序列。

    早先版本让模型「照搬 action_steps 只换主体」,结果两次都失败:
      1) 保留原产品 —— 原片动作与场景自洽,新产品描述是孤立一句,模型选自洽的;
      2) 硬造不存在的东西 —— 手镯被改写成「白色纸盒 + 口红管 + 膏体」。
    参考项目 video-clone-lite 的「动作照搬」前提是**新旧同品类**(精华→口红),
    跨品类时该前提不成立,所以这里改为保留镜头语言、重设计画面内容。

    改写失败返回原表(不抛错):分镜表是用户的既有资产,改写只是增强手段,
    不该因为一次模型调用失败就毁掉已经拆好的结果。
    """
    if not boards:
        return boards
    try:
        import json as _json
        raw = text_client.chat(
            REWRITE_PROMPT.format(
                boards=_json.dumps(boards, ensure_ascii=False, indent=1),
                product_desc=product_desc or "用户产品(见产品参考图)",
                presenter_desc=presenter_desc or "亲和力强的出镜人物"),
            # **不传 max_tokens**:让它由 text_client 按「模型配置」取值
            # (见 text_client._build_body:显式值 > cfg.max_tokens > 8192 兜底)。
            # 此前写死 4096 时,推理型模型(minimax-M3 会吐上万字符 <think>)
            # 把预算全花在思考上,正文 JSON 被截断 → extract_json 解析失败,
            # 分镜改写整份回退(实测连续失败两次)。这类参数属于**厂商/模型**差异,
            # 该在设置里按服务配,不该写死在业务代码里。
            temperature=0.3, json_mode=True, config_id=config_id)
        data = runner.extract_json(raw)
        out = data.get("storyboards") if isinstance(data, dict) else data
        if not isinstance(out, list) or not out:
            # 失败时必须留下诊断:此前只打一行「改写失败」,而真实原因是模型返回了
            # 16KB 的 <think> 推理块把 max_tokens(4096)吃光、正文 JSON 被截断 ——
            # 排查时完全看不出是哪一步断的。
            print(f"[clone] 分镜表改写失败(响应 {len(raw or '')} 字符,"
                  f"解析后类型 {type(data).__name__},"
                  f"storyboards 镜数 {len(out) if isinstance(out, list) else 0}),保留原表",
                  flush=True)
            print(f"[clone] 响应尾部 200 字: {(raw or '')[-200:]!r}", flush=True)
            return boards
        # 逐镜对齐:模型可能改 number/漏镜,按原表顺序兜底,宁可少改不可丢镜
        merged = []
        rewritten_only = []      # 仅模型**真的输出过内容**的镜次,用于残留校验
        for i, orig in enumerate(boards):
            new = out[i] if i < len(out) and isinstance(out[i], dict) else {}
            row = dict(orig)
            # 画面内容:用改写结果(动作已按新产品重新设计)
            touched = False
            for k in ("action", "action_steps", "product_use", "prompt", "line"):
                if new.get(k):
                    row[k] = new[k]
                    touched = True
            # 镜头语言:**强制用原片的**,无视模型输出。节奏对齐是复刻的本质,
            # 模型一旦自作主张改 start/end/shot,成片节奏就跟原片对不上了。
            for k in ("start", "end", "duration", "shot", "camera", "number"):
                if k in orig and orig[k] is not None:
                    row[k] = orig[k]
            merged.append(row)
            if touched:
                rewritten_only.append({k: new.get(k) for k in
                                       ("action", "action_steps", "product_use", "prompt")})
        # 原片产品残留检测:**交给模型判断**,不用词表穷举。
        # 词表方案实测连续误杀三次:中文没有词边界,「亮相」「展示真实」
        # 「完成产品-效果闭环」这类描述词怎么列都列不全,而误杀的代价是
        # 整份改写被丢弃、用户白跑一次拆解。宁可漏报不可误杀。
        stale = _residual_by_llm(rewritten_only, product_desc, config_id)
        if stale:
            print(f"[clone] ⚠ 改写结果仍含原片产品:{stale};判定为改写失败,丢弃本次改写", flush=True)
            return boards
        print(f"[clone] 分镜表已按新产品改写 {len(rewritten_only)}/{len(merged)} 镜", flush=True)
        # 这里**不再**调 _warn_if_product_mismatch:它靠 2-gram 词表判定,
        # 与 _residual_by_llm 同属启发式,重复报警只会制造噪音(实测拿旧描述
        # 比出「的佩」这种无意义的告警)。语义层面的残留判定已由上面的模型调用负责。
        return merged
    except Exception as exc:  # noqa: BLE001
        print(f"[clone] 分镜表改写异常({exc}),保留原表", flush=True)
        return boards


def _normalize_shot(shot: dict, index: int) -> dict:
    """直传产出的 shot(shots/duration/dialogue)→ 抽帧版的字段名。

    两条拆解路径合并成一条能力(抽帧 / 整段直传只是喂给模型的东西不同),
    产物必须同构,否则下游 rewrite / generate_shot_image / _shot_video_prompt
    要分两套写法 —— 那正是当初两套分镜并存、各自缺功能的根源。
    """
    s = dict(shot or {})
    acts = [str(x).strip() for x in (s.get("action_steps") or []) if str(x).strip()]
    dlg = [str(x).strip() for x in (s.get("dialogue") or []) if str(x).strip()]
    try:
        dur = float(s.get("duration") or 5)
    except (TypeError, ValueError):
        dur = 5.0
    start = float(s.get("start") or 0)
    return {
        "number": index,
        "start": start,
        "end": start + dur,
        "duration": dur,
        "shot": str(s.get("shot_type") or s.get("shot") or "中景").strip(),
        "camera": str(s.get("camera") or "").strip(),
        "action": str(s.get("action") or ("，".join(acts) if acts else "")).strip(),
        "action_steps": acts,
        "line": " / ".join(dlg) or str(s.get("line") or "").strip(),
        "product_use": str(s.get("product_use") or "").strip(),
        "prompt": str(s.get("prompt") or "").strip(),
    }


CLONE_PRESENTER_NAME = "出镜人物"
CLONE_PRODUCT_NAME = "主推产品"
CLONE_SCENE_NAME = "主场景"


def _turnaround_block() -> str:
    """角色三视图规范块(复用漫画侧的既有实现,不另造一套)。

    复刻项目的主图必须是**你自己的人物三视图**(正面/侧面/背面),而不是参考视频里
    的人 —— 这是「换掉主角」的前提:参考图锚的是脸与服装,锚的是原片主角就白搭。
    """
    from .comic import _TURNAROUND_BLOCK
    return _TURNAROUND_BLOCK


def build_presenter_turnaround(presenter_path,
                               config_id: int | None = None) -> Path:
    """用**你上传的人物照**生成全身三视图主图,返回本地路径。

    为什么要有这一步(一致性问题的根):
    一张正脸特写能锁五官,但锁不住**体型、身高比例、服装全貌**;而复刻要跨 4–6 镜
    保持同一人,短剧侧早就用三视图解决这件事(comic._TURNAROUND_BLOCK:正脸特写 +
    正面/侧面/背面三张等高全身),这里直接复用同一份规范。

    参考图只传**你那张人物照**本身(单图,不给模型第二张图去对称融合)。

    **写实阳光,不跟项目画风**:三视图是「角色资产图」,用途是锁长相/体型/服装,
    必须中性、清晰、可辨认。带项目画风(本项目默认"治愈系插画")会出一张插画风的
    设定图 —— 实测正是如此,插画笔触让五官与服装的细节全部失真,锁不住人。
    成品镜头仍按项目画风出图(见 generate_shot_image 的 style)。
    """
    realistic = ("photorealistic e-commerce lookbook photograph of a real person, "
                 "clean fresh natural makeup, clear healthy skin with fine natural "
                 "texture, bright airy high-key daylight lighting, soft even studio "
                 "light on a clean seamless pure-white backdrop, crisp sharp focus, "
                 "high detail, true-to-life body proportions, professional catalog "
                 "photography look, "
                 "NOT illustration, NOT anime, NOT cartoon, NOT painting, "
                 "NOT 3d render, no dirty or grimy or dull appearance, "
                 "no heavy shadows, no grime, no dark circles, no messy hair, "
                 "no wrinkled clothes, everything neat and tidy")
    prompt = (f"{realistic}\n"
              "以参考图中的人物为原型,生成该角色的**标准参考图**。"
              f"{_turnaround_block()}")
    out, _ = image_client.generate_image(prompt, out_name="clone_turnaround.png",
                                         config_id=config_id,
                                         reference_images=[str(presenter_path)],
                                         skip_guard=True)  # 三视图自含构图,人数守卫会砍特写格
    return out


def _selected_image_cfg() -> int | None:
    """读用户当前选中的生图配置(全局记忆 yihao.model.image,与界面下拉同源)。

    不写死任何配置 id —— 各厂商额度/可用性不同(实测百炼月度额度耗尽会 429),
    用哪个模型必须由用户在界面上选。
    """
    return db.resolve_selected_config_id("image")


def _selected_text_cfg() -> int | None:
    """读用户选中的文本服务(读原照提取外观/服装描述用)。"""
    return db.resolve_selected_config_id("text")


def _selected_swap_cfg() -> int | None:
    """读用户选中的换脸服务;未选则用默认。"""
    return db.resolve_selected_config_id("faceswap")


def build_presenter_fullshot(presenter_path, config_id: int | None = None,
                             text_cfg_id: int | None = None,
                             swap_cfg_id: int | None = None) -> Path:
    """生成「纯文字底图 + 换脸」的单人全身像 —— 分镜真正使用的参考主图。

    ── 为什么要拆成两步(实测踩坑的完整链路)──
    1. 直接拿用户原照当参考图生全身像 → 生成出**两个半透明人影**(实测)。
       根因:原照背景是大面积红橙舞台光晕,模型把「背景的暖色光斑」读成
       「旁边还有发光的人」。这是**从参考图继承的构图惯性**,不是凭空生成,
       所以负面词压不住(补齐短剧侧张嘴/极端表情负面词后重影反增)。
    2. 只传 1 张图(排除了多图融合) → 重影一模一样,再次证明是继承而非融合。
    3. 连通域裁剪 → 半透明边缘与主体粘连,裁不掉。

    所以换一条路:**底图完全不传参考图**(纯文字,重影从根上不存在),
    再用 face.mei.biz 把用户的脸换上去 —— 换脸只动人脸像素,不动背景与服装。
    实测两步产物:单人、干净、服装清晰、纯白背景,无重影。

    face/styling 描述由 read_presenter_desc 多模态读原照自动提取(用户选的 B 方案):
    手写容易漏,读图更省事;原照里真实存在的特征它都能读到。
    """
    desc = read_presenter_desc(presenter_path, config_id=text_cfg_id) or {}
    appearance = desc.get("appearance") or "年轻女性，五官清晰，棕色中分长发"
    styling = desc.get("styling") or "简洁得体的日常服装"
    # 原照常常是半身照、看不到鞋(read_presenter_desc 会如实留空),此时**显式补一个
    # 电商通用鞋款**,而不是留空让模型自由发挥 —— 空白等于失控,分镜真要拍到脚时
    # 穿什么鞋完全不可控。换成全身照后这里会自动用照片里真实的鞋。
    if not desc.get("footwear"):
        styling += ", 穿黑色细高跟一字带凉鞋,露出完整双脚与脚踝"
    prompt = (
        "photorealistic e-commerce lookbook photograph of a real person, "
        "clean fresh natural makeup, bright airy high-key daylight lighting, "
        "soft even studio light on a seamless pure white backdrop, "
        "crisp sharp focus, true-to-life body proportions, professional catalog "
        "photography look. "
        f"Subject: {appearance}. Wearing {styling}. "
        # 必须**硬性**要求全身入镜:电商模特图的默认输出就是七分身,
        # 写 "full body" / "head to toe" 都不够(实测两轮都只到大腿)。
        # 有效写法是把脚与画幅底边直接绑在一起,并给出人物占比。
        "Full-length fashion catalog shot: the figure is photographed from head "
        "to toe and the soles of her feet are fully visible, resting on the "
        "bottom edge of the frame. The whole figure occupies about 80% of the "
        "image height, centered, with white margin on all four sides. "
        "Nothing is cropped: not the top of the head, not the feet, not the "
        "skirt hem. Full-length shot, front view standing, arms relaxed at "
        "sides, neutral A-pose, calm natural expression. "
        "NOT a half-body shot, NOT a three-quarter length shot, NOT cropped, "
        "NOT cropped at the knees, NOT cropped at the thighs. "
        "NOT illustration, NOT anime, NOT cartoon, NOT painting, NOT 3d render, "
        "no dirty or grimy appearance, no heavy shadows, no text, no watermark, "
        "no logo")
    extra_neg = ("multiple people, second person, extra person, bystander, onlooker, "
                 "background figures, faded silhouettes, ghost figure, "
                 "translucent figure, reflections of people, double exposure, "
                 "open mouth, screaming, exaggerated emotion, "
                 "solid white background, seamless white backdrop, "
                 "no colored background, no furniture, no props, no text, no watermark")
    # 画幅必须给**竖版**:16:9 横画幅装不下头顶到脚底,模型只能给七分身
    # (实测加了 "head to toe" 强调仍无效 —— 是画幅不够高,不是提示词没说清)。
    # 竖版 1080x1920 是标准电商模特图比例。
    out, _ = image_client.generate_image(prompt, out_name="clone_fullshot.png",
                                         config_id=config_id, people=1,
                                         size="1080x1920",
                                         extra_negative=extra_neg)
    # 换脸:只动人脸像素,服装与白底保持不变(实测 face.mei.biz / inswapper_128 可用)
    try:
        from ..ai import face_swap   # face_swap 在 app.ai,不是 app.pipeline
        out = face_swap.swap_remote(str(presenter_path), str(out), "jpg",
                                    config_id=swap_cfg_id)
        print(f"[clone] 换脸完成:{Path(str(out)).name}", flush=True)
    except Exception as exc:  # noqa: BLE001
        # 换脸失败不阻塞:退回纯文字底图,长相不像但至少干净无重影
        print(f"[clone] 换脸失败({exc}),退回文字底图", flush=True)
    return out


def sync_assets(drama_id: int,
                config_id: int | None = None) -> tuple[int | None, int | None, int | None]:
    """把复刻项目的产品图/出镜照**存成正式资产**(characters / props),返回两个资产 id。

    为什么必须资产化:复刻是**逐镜独立生图**,每一镜的提示词都要重新描述
    「这个人的脸长什么样」「这个房间什么样」。模型没有跨镜记忆,于是实测 6 张图
    里人脸、房间背景、产品形状全在漂(口红时方时圆)—— 提示词里写多少遍
    「保持一致」都没用,那是文字约束,不是锚点。

    资产是**跨镜共享的锚点**:同一张形象图被 6 镜反复当作参考图注入,模型才
    有机会保持同一个人/同一间房/同一件产品。这也正是短剧项目一直用的机制
    (characters/props + reference_images),这里直接复用,不另造一套。

    复刻项目的分镜不在 storyboards 表里(走 metadata),所以绑不上
    storyboard_characters —— 这里退一步用**项目级注入**:每镜生成都带上
    这两个资产,效果等价,只是没法逐镜挑选。
    """
    meta = _meta(drama_id)
    clone = meta.get("clone", {})
    presenter = _resolve_local(clone.get("presenter"))
    product = _resolve_local(clone.get("product"))
    if not (presenter or product):
        return None, None
    ts = db.now()

    def _upsert(table: str, name: str, url: str, extra: dict) -> int | None:
        row = db.q1(f"SELECT id FROM {table} WHERE drama_id=? AND name=?", (drama_id, name))
        cols = {"drama_id": drama_id, "name": name, "image_url": url,
                "updated_at": ts, **extra}
        if row:
            sets = ",".join(f"{k}=?" for k in cols)
            db.ex(f"UPDATE {table} SET {sets} WHERE id=?",
                  (*cols.values(), row["id"]))
            return row["id"]
        db.ex(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
              tuple(cols.values()))
        return db.get_db().execute(
            f"SELECT id FROM {table} WHERE drama_id=? AND name=? ORDER BY id DESC LIMIT 1",
            (drama_id, name)).fetchone()["id"]

    cid = _upsert("characters", CLONE_PRESENTER_NAME,
                  config.path_to_media_url(presenter) if presenter else "",
                  # appearance / styling 填上:短剧侧的漫画链路会读这两个字段做
                  # **文字层**的资产锁定(comic.py:287),只靠图锁不住服装/妆造。
                  # 这里至少把人物描述与产品描述分别写进去,供后续提示词引用。
                  {"role_type": "presenter",
                   "appearance": clone.get("presenter_desc") or "",
                   "styling": clone.get("presenter_styling") or "",
                   "created_at": ts}) if presenter else None
    # 分镜参考主图 = **单人全身像**:正脸照锁不住服装(逐镜会自己换衣服),
    # 三视图锁得住却含 4 个人物实例(会被一起画进画面)。全身像两头都要。
    # 三视图仍然生成,存 clone.turnaround_image 供人工核对/换脸,但**不进分镜**。
    _cfg = config_id or _selected_image_cfg()
    if presenter and not clone.get("presenter_fullshot"):
        try:
            fs = build_presenter_fullshot(
                presenter, config_id=_cfg,
                text_cfg_id=_selected_text_cfg(),
                swap_cfg_id=_selected_swap_cfg())
            clone["presenter_fullshot"] = str(fs)
            print(f"[clone] 人物全身像已生成:{Path(str(fs)).name}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[clone] 全身像生成失败({exc}),退回上传原照", flush=True)
    if presenter and not clone.get("turnaround_image"):
        try:
            ta = build_presenter_turnaround(presenter, config_id=_cfg)
            clone["turnaround_image"] = str(ta)
            clone["clone_turnaround_at"] = ts
            print(f"[clone] 人物三视图已生成(仅供核对):{Path(str(ta)).name}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[clone] 三视图生成失败({exc})", flush=True)
    # 资产图分列存(与短剧侧同构,见 comic.comic_asset_image):
    #   image_url       = 分镜用的单人全身像(锁脸 + 锁服装)
    #   comic_image_url = 三视图(正脸特写 + 正面/侧面/背面),仅供人工核对与换脸
    # 两张图各有分工,不互相覆盖 —— 三视图含 4 个人物实例,当分镜参考会出多人画面。
    if presenter and clone.get("presenter_fullshot"):
        db.ex("UPDATE characters SET image_url=? WHERE drama_id=? AND name=?",
              (config.path_to_media_url(clone["presenter_fullshot"]),
               drama_id, CLONE_PRESENTER_NAME))
    if clone.get("turnaround_image"):
        db.ex("UPDATE characters SET comic_image_url=? WHERE drama_id=? AND name=?",
              (config.path_to_media_url(clone["turnaround_image"]),
               drama_id, CLONE_PRESENTER_NAME))
    pid = _upsert("props", CLONE_PRODUCT_NAME,
                  config.path_to_media_url(product) if product else "",
                  {"type": "product", "description": clone.get("product_desc") or "",
                   "created_at": ts}) if product else None
    if pid and clone.get("product_desc"):
        db.ex("UPDATE props SET description=? WHERE id=?", (clone["product_desc"], pid))

    # 场景资产:复刻的镜头虽然每镜换内容,但**场景应当统一**(同一间房/同一个
    # 布景),否则跨镜背景漂移最明显。首镜出图后把它的图存成场景资产,后续镜
    # 以它为背景参照。没有场景图时用场景描述建一条无图资产,至少能锁文字。
    sid = _upsert("scenes", CLONE_SCENE_NAME, clone.get("scene_image") or "",
                  {"location": clone.get("scene_location") or "",
                   "prompt": clone.get("scene_prompt") or "",
                   "lighting": clone.get("scene_lighting") or "",
                   "created_at": ts})
    print(f"[clone] 资产已同步:出镜人物={cid} 主推产品={pid} 场景={sid}", flush=True)
    # 必须写回 meta:三视图路径、场景图等只改了局部 clone 字典,调用方
    # (analyze_reference)拿的是自己那份引用,不会自动落库 —— 实测生成了
    # clone_turnaround.png 但 DB 里 turnaround_image 仍是空,等于白生成。
    meta["clone"] = clone
    _save_meta(drama_id, meta)
    return cid, pid, sid


def _residual_by_llm(rewritten: list[dict], product_desc: str,
                     config_id: int | None = None) -> str:
    """问模型:改写后的分镜里,还有没有原片产品的残留?返回问题描述(无残留则空串)。

    为什么不自己比对词表(实测教训):中文没有词边界,「亮相」「展示真实」
    「完成产品-效果闭环」「面对镜头」这类描述词穷举不完 —— 实测连续三次
    把正常的改写结果误判成残留,导致整份改写被丢弃、用户白跑一次拆解。
    语义判断交给模型,一次调用换掉一个不可靠的启发式。

    模型调用失败一律当作「无残留」放行:宁可让一次坏结果进到下一阶段
    (生成首帧前还能肉眼看出不对),也不要在这里把好结果误杀。
    """
    if not rewritten:
        return ""
    import json as _json
    try:
        raw = text_client.chat(
            "【新产品】" + (product_desc or "") + "\n\n【改写后的分镜】\n"
            + _json.dumps(rewritten, ensure_ascii=False, indent=1)
            + "\n\n上面这份分镜,是把一条**旧视频**的镜头节奏套用到新产品上重写的。"
              "请只判断一件事:里面是否还提到了**旧视频里那个商品**(它的品类名、"
              "部件名、包装形态等)?\n"
              "注意:「展示」「亮相」「同框」「完整」「呈现」这类**描述性词**"
              "不算残留,只有真正指向旧商品实体的词才算。\n"
              "若已无残留,输出 {\"residual\": \"\"};有残留则输出 "
              "{\"residual\": \"简述残留了什么\"}。只输出 JSON。",
            temperature=0.1, json_mode=True, config_id=config_id)
        d = runner.extract_json(raw) or {}
        return str(d.get("residual") or "").strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[clone] 残留检测调用失败({exc}),按无残留放行", flush=True)
        return ""






# 通用词:命中它们不代表画面里出现了新产品(旧分镜里本来就有这些)




def analyze_reference(drama_id: int, extra_hint: str = "", config_id: int | None = None,
                      direct: bool = False) -> list[dict]:
    """第 1 步:看懂原片 → 分镜表。**结果统一落 clone.storyboards**(单一事实来源)。

    direct=False(默认):ffmpeg 均匀抽 8 帧 → 多模态模型看图分镜。快、便宜,
        适合静态为主的开箱/特写类带货片。
    direct=True:整段视频 base64 直传给模型。慢、体积大,但模型看得到**连续运动**,
        抽 8 帧看不到「手抬起→凑近→涂抹」这类帧间才成立的时序,快速运镜/翻转类选它。

    两条模式**产物同构**(见 _normalize_shot),下游完全无感 —— 这正是把原先
    并存的两套拆解路径合并成一条的目的:只有一套分镜表,才谈得上"换产品"。

    有产品图时顺带读图写 clone.product_desc,并按新产品改写分镜表
    (rewrite_boards_for_product),失败不阻塞拆解。
    """
    meta = _meta(drama_id)
    clone = meta.get("clone", {})
    ref = clone.get("reference")
    if not ref:
        raise RuntimeError("请先导入参考视频")
    dur = _duration(ref)
    if direct:
        # 整段直传:模型看连续运动,信息密度高于抽帧推断(抽 8 帧看不到
        # 「手抬起→凑近→涂抹」这类帧间才成立的时序)。代价是慢、体积大。
        work, _cut = transcode_if_needed(Path(ref), drama_id)
        prompt = UNDERSTAND_PROMPT + (
            f"\n\n总时长 {dur:.1f} 秒。"
            f"{('补充说明: ' + extra_hint) if extra_hint else ''}")
        raw = runner.run_agent("storyboard_breaker", prompt, temperature=0.3,
                               config_id=config_id, image_urls=[_inline_video(work)],
                               lang=config.resolve_content_language(drama_id))
        data = runner.extract_json(raw) or {}
        # 直传用 shots/duration/dialogue,统一映射到抽帧版的字段名,
        # 这样下游(rewrite / generate_shot_image / _shot_video_prompt)
        # 完全不用关心这条分镜表是哪条路产出的。
        boards = [_normalize_shot(s, i + 1) for i, s in enumerate(data.get("shots") or [])]
    else:
        frames = extract_frames(ref, count=8)
        image_urls = [_image_data_url(f) for f in frames]
        frame_desc = "\n".join(
            f"第{i}帧(约 {dur * i / (len(frames) + 1):.1f} 秒处)"
            for i, _ in enumerate(frames, 1))
        prompt = f"""下面是一条待复刻的带货/种草类视频,已按时间均匀抽出 {len(frames)} 帧随消息附上(顺序对应):
总时长: {dur:.1f} 秒
{frame_desc}
{('补充说明: ' + extra_hint) if extra_hint else ''}

请逐帧仔细看图,推断该视频的完整分镜表(8 秒上下每镜,共 2-6 镜):
- 每帧识别:场景、人物与景别(远/全/中/近/特)、人物动作、出现的商品及其使用方式、画面字幕或口播要点
- 相邻两帧画面差异明显即发生了镜头切换,据此划分镜头边界与起止时间
每镜输出:
- number, start, end, shot(景别), camera(运镜:固定/推/拉/摇/移/跟/升降等,选一词)
- action(一句话动作概述), action_steps(连续动作时序数组,2-5 步,每步一句按时间先后排列的可见动作)
- line(推测台词/字幕), product_use(产品如何出现)
- prompt(给文生视频模型的重拍提示词:主体+动作+运镜+光线+氛围,不写人名)
以 JSON 输出:{{"storyboards":[...]}}"""
        # **不走 storyboard_breaker agent**:它的 system prompt 是给
        # 「剧本 → 分镜」设计的,开篇就要求「从用户消息中读取剧本与可用资产清单」,
        # 而这里给的是 8 张抽帧图。指令与输入错配 → 模型困惑于「剧本在哪」,
        # 推理块发散把输出预算吃光,最终抛「输出无法解析为 JSON」(实测)。
        # 这里直接用自带的 system,输入形态与指令对齐。
        raw = text_client.chat(
            prompt,
            system=("你是资深影视分镜师,专门分析带货类视频的分镜结构。"
                    "用户会给你视频的若干抽帧图与总时长,你逐帧观察后"
                    "输出结构化的分镜表。只输出 JSON。"),
            temperature=0.3, json_mode=True,
            config_id=config_id, image_urls=image_urls)
        data = runner.extract_json(raw)
        if data is None:
            # 留下诊断:此前只抛一句「无法解析」,排查时看不出响应是被截断
            # 还是模型压根没输出 JSON(两种情况修法完全不同)。
            raise RuntimeError(
                f"分镜表生成失败:模型响应 {len(raw or '')} 字符但无法解析为 JSON。"
                f"若响应含大量 <think> 说明输出预算被推理块吃光(调大模型配置的"
                f"「最大输出 token」);尾部 200 字: {(raw or '')[-200:]!r}")
        boards = data.get("storyboards") or (data if isinstance(data, list) else [])
    if not boards:
        raise RuntimeError("分镜表生成失败:模型未产出任何分镜")
    clone["boards_mode"] = "direct" if direct else "frames"
    clone["storyboards"] = boards
    product = clone.get("product")
    if product:
        try:
            desc = read_product_desc(product, config_id=config_id)
            if desc:
                clone["product_desc"] = desc
        except Exception:  # noqa: BLE001
            pass  # 可选步骤:读产品图失败不阻塞分镜分析
    # 拆解完立刻按新产品改写分镜表(参考项目 video-clone-lite 的关键做法)。
    # 不改写的话,原片实物名会留在 action_steps 里,后续生成时新旧描述打架,
    # 模型必然选跟场景自洽的原片实物 —— 表现为"换了产品图但画面没变"。
    if clone.get("product_desc"):
        boards = rewrite_boards_for_product(
            boards, clone["product_desc"],
            presenter_desc=clone.get("presenter_desc") or "", config_id=config_id)
        clone["storyboards"] = boards
    # 产品图/出镜照存成正式资产:跨镜一致性靠资产锚点,不靠提示词措辞(实测
    # 人脸/房间/产品形状逐镜漂,写多少遍「保持一致」都没用)
    try:
        cid, pid, sid = sync_assets(drama_id, config_id=config_id)
        if cid:
            clone["presenter_asset_id"] = cid
        if pid:
            clone["product_asset_id"] = pid
        if sid:
            clone["scene_asset_id"] = sid
    except Exception as exc:  # noqa: BLE001
        print(f"[clone] 资产同步失败({exc}),退回 metadata 原图", flush=True)
    meta["clone"] = clone
    _save_meta(drama_id, meta)
    return boards


def prepare_presenter(drama_id: int, style_value: str, config_id: int | None = None) -> str:
    """AI 生成一位出镜模特形象图(**仅当用户没上传出镜照时**)。

    **不要覆盖用户上传的照片** —— 这是实测踩过的坑:原来无条件写
    clone["presenter"],用户传了自己的照片后又点了「AI 生成出镜模特」,
    上传图被系统生成的模特顶掉,于是:
      · 外观/服装描述从男模特图提取 → 分镜里人物性别乱跳、有的变男人;
      · 换成用户的女性脸 → 女的体配男的服装。
    所以用户传过就直接返回原图,生成结果另存 clone.ai_presenter 供查阅。
    """
    meta = _meta(drama_id)
    clone = meta.get("clone", {})
    user_uploaded = _resolve_local(clone.get("presenter_uploaded") or clone.get("presenter_src"))
    if user_uploaded:
        print("[clone] 已上传出镜照,跳过 AI 生成模特(不覆盖用户素材)", flush=True)
        return str(user_uploaded)
    prompt_prefix = db.style_prompt(style_value)
    prompt = (f"{prompt_prefix}, 单人全身模特形象参考图,正面站姿,纯白背景,柔和影棚光, "
              "人物形象干净亲和,适合带货出镜, 电影质感")
    out, _ = image_client.generate_image(prompt, out_name=f"clone_presenter_{drama_id}.png", config_id=config_id)
    clone["presenter"] = str(out)          # 仅在用户没上传时才是主角素材
    clone["ai_presenter"] = str(out)       # 留档,便于分辨是不是 AI 生成的
    meta["clone"] = clone
    _save_meta(drama_id, meta)
    return str(out)


def _clone_storyboards(drama_id: int) -> list[dict]:
    return _meta(drama_id).get("clone", {}).get("storyboards", [])


def _resolve_local(p) -> Path | None:
    """素材字段可能是本地绝对路径或 /static/ 媒体地址,统一转本地路径;不存在返回 None。"""
    s = str(p).replace("\\", "/")
    path = config.media_url_to_path(s) if s.startswith(("/static/", "static/")) else Path(p)
    return path if path.exists() else None


def _shot_video_prompt(b: dict) -> str:
    """重拍视频提示词:显式 prompt 字段优先作主体;缺失时按原版 videoPrompt 口径合成
    (景别+运镜+动作时序);有台词时追加口型同步标注。"""
    steps = [str(s).strip() for s in (b.get("action_steps") or []) if str(s).strip()]
    cam = str(b.get("camera") or "").strip()
    line = str(b.get("line") or "").strip()
    body = str(b.get("prompt") or "").strip()
    if not body:
        body = "，".join(filter(None, (str(b.get("shot") or ""), cam,
                                       "，".join(steps) or str(b.get("action") or ""))))
    elif steps:
        # 改写过的 prompt 已经把动作时序写进去了(rewrite 提示词明确要求),
        # 再拼一遍 action_steps 是重复描述,徒增字数并挤掉 200 字预算
        body = f"{body}，动作按 {'，'.join(steps)} 的时序推进"
    if line:
        body = f"{body}。台词（口型同步）：{line}"
    # 时间锚点:此前 start/end 拆了却从不进提示词,视频模型拿不到本镜的时间轴。
    # 改写过的 prompt 里通常已含锚点(rewrite 提示词要求写),重复加会出现
    # "0-4秒:0-4秒:...",所以先探一下再加。
    span = ""
    try:
        st, en = float(b.get("start") or 0), float(b.get("end") or 0)
        if en > st and f"{st:g}-{en:g}秒" not in body:
            span = f"{st:g}-{en:g}秒:"
    except (TypeError, ValueError):
        span = ""
    return f"{span}{body}"


def _pick_ref_kind(shot_text: str, shot: str = "") -> str:
    """这一镜该用哪张参考图:"product"(产品图)或 "presenter"(人物照)。

    **每镜只给一张**:同时传人物照+产品照两张,Agnes 会把两张的构图一起对称
    融合,产出**左右完全对称的双头图**(一个人被劈成两半)。这是实测踩过的。

    **判定看"画面主体",不看"文案里提到什么"** —— 这是实测踩出来的关键区别:
    分镜 #1 写「女子坐在桌前低头看向桌面上的手镯」(中景),文案同时含人物词与
    静物词;按词表判会选产品图,但这一镜拍的是**人**,产品只是她手里的道具 ——
    于是生成出"画面里描述了人物、却只给了产品参照"的双重人像(一个人 + 一个
    半透明重影)。

    优先级:
      1. **景别**:特写/大特写 → 产品图(细节展示);中景/近景/全景/中近景 → 人物图
      2. 景别缺失时才看文案:明确的静物动作 > 人物动作 > 弱产品词
    """
    t = shot_text or ""
    # 1) 景别优先 —— 它直接反映"这一镜拍的是谁/什么"
    close_shots = ("特写", "大特写", "微距")
    wide_shots = ("中景", "近景", "全景", "远景", "中近景", "半身")
    if any(w in (shot or "") for w in close_shots):
        return "product"
    if any(w in (shot or "") for w in wide_shots):
        return "presenter"
    # 2) 无景别信息 → 回退到文案判断
    static_words = ("静置", "陈列", "底座", "木座", "静物", "同框", "亮相",
                    "产品特写", "产品完整", "产品展示")
    person_words = ("人物", "女子", "女生", "女性", "出镜", "佩戴", "试戴",
                    "手举", "手持展示", "微笑", "模特")
    weak_product = ("产品", "特写", "光泽", "质感", "形态", "质地")
    if any(w in t for w in static_words):
        return "product"
    if any(w in t for w in person_words):
        return "presenter"
    if any(w in t for w in weak_product):
        return "product"
    return "presenter"          # 判断不了 → 以人物为锚(人物图信息量更大)


def generate_shot_image(drama_id: int, board_number: int, style_value: str,
                        config_id: int | None = None) -> Path:
    """第 3 步 a:按分镜表生成该镜首帧图(注入产品/模特形象描述)。

    有产品图/模特形象图时作为参考图注入(agnes extra_body.image):人物锁脸、产品保外观,
    提示词附一致性约束;无图退回纯文生图。
    """
    boards = _clone_storyboards(drama_id)
    b = next((x for x in boards if int(x.get("number", 0)) == int(board_number)), None)
    if not b:
        raise RuntimeError(f"分镜 #{board_number} 不存在,请先分析参考视频")
    meta = _meta(drama_id)
    clone = meta.get("clone", {})
    style = db.style_prompt(style_value)
    product_desc = clone.get("product_desc") or "用户产品(见产品图)"
    presenter_desc = clone.get("presenter_desc") or "亲和力强的出镜人物(见模特形象)"
    # ── 参考图:1 张主图 + 最多 4 张参考图,靠**名字**在提示词里关联 ──
    #
    # 官方能力(agnes-image-25-flash 文档):`image` 是 string[],明确支持
    # 「多图合成时传入多张图像」,核心能力里列的就是「多图合成」。所以多图是支持的。
    #
    # 为什么仍要分「主图 / 参考图」而不是 5 张平铺:模型对**多张同类型正面照**
    # 会试图同时满足,实测把「人物正面照 + 产品正面特写」硬凑,产出过**左右
    # 对称的双头图**。而「主体 + 场景」这类语义搭配是自然的,不会互相打架。
    # 主图决定画面主体,参考图补上下文,提示词里逐一点名各自的用途。
    def _asset_img(kind: str):
        """分镜参考图。

        人物这一项**不用三视图**:三视图里有 4 个人物实例(1 特写 + 正面/侧面/背面),
        喂给分镜时模型会把多个实例一起画进画面(实测中近景镜出三个并排人物)。
        而「不是三视图、多视角设定图或拼版」那条守卫又与它自相矛盾,模型两头为难。

        用**单人全身像**:既有清晰正脸(锁五官),又看得到完整服装(锁款式与颜色),
        一个人物实例不会引发多视角歧义 —— 短剧侧锁服装也是靠单人全身形象图。
        三视图仍然生成并存进 characters 表,供人工核对与换脸用,只是不进分镜。
        """
        if kind == "presenter":
            full = _resolve_local(clone.get("presenter_fullshot"))
            if full:
                return full
            return _resolve_local(clone.get("presenter"))
        key = f"{kind}_asset_id"
        name = CLONE_PRESENTER_NAME if kind == "presenter" else CLONE_PRODUCT_NAME
        table = "characters" if kind == "presenter" else "props"
        aid = clone.get(key)
        if aid:
            row = db.q1(f"SELECT image_url FROM {table} WHERE id=?", (aid,))
            p = _resolve_local(row["image_url"]) if row else None
            if p:
                return p
        return _resolve_local(clone.get(kind))

    _shot_text = " ".join(str(b.get(k) or "") for k in
                          ("action", "action_steps", "product_use", "prompt"))
    _shot_kind = str(b.get("shot") or "")
    main_kind = _pick_ref_kind(_shot_text, _shot_kind)
    main_img = _asset_img(main_kind)

    # ── 参考图:每镜**只传一张** ──
    #
    # 我先前做成了「主体 + 另一类 + 场景」共 2 张,结果实测第 1 镜右侧冒出一个
    # 半透明第二人 —— 参考图里明确画了第二个人,提示词里的 no onlookers /
    # no background silhouettes 拗不过图像参照。场景改用**文字锚**锁定
    # (见下方 scene_lock),不占参考图位。
    refs = [main_img] if main_img else []
    if not refs:                       # 主图缺失 → 退回另一类资产,再退回空
        refs = [p for p in (_asset_img("presenter"), _asset_img("product"))
                if p][:1]
    print(f"[clone] 分镜#{board_number} 景别={_shot_kind or '未标'} "
          f"主图={main_kind} 参考图={len(refs)}张", flush=True)
    # B) 一致性校验:**只报不补**。提示词里描述了人物却只给了产品参照(反之亦然),
    # 模型会自己补一个不存在的人 → 双重人像(实测:中景人物镜配了产品图,
    # 产出"一个人 + 一个半透明重影")。自动补第二张图又会踩"双图对称融合"的坑,
    # 所以这里只把它报出来,让用户知道这一镜的参照与描述对不上。
    # 只认**出镜人物**类词,不算局部肢体。"female wrist"(手腕特写)里也有 woman/female,
    # 但特写根本不拍脸,不需要人物参照图 —— 按原逻辑会对每一镜都误报(实测 #3 就是)。
    _has_person_words = any(w in _shot_text for w in
                            ("woman's face", "her face", "人物", "女子",
                             "女生", "女性", "出镜", "模特", "人物出镜"))
    # 特写/大特写即便提到人物,主体也是物件;仅当明确拍到脸/上半身才需要人物参照
    if any(w in _shot_kind for w in ("特写", "微距")) and             not any(w in _shot_text for w in ("face", "脸", "上半身", "半身")):
        _has_person_words = False
    if _has_person_words and main_kind != "presenter":
        print(f"[clone] ⚠ 分镜#{board_number} 提示词描述了人物,但主图是产品参考图"
              f"(景别={_shot_kind or '未标'}),可能出现多余人物。", flush=True)
    has_product_ref = bool(_asset_img("product"))
    has_presenter_ref = bool(_asset_img("presenter"))
    # 一致性约束必须**逐项点名**具体锁定对象,不能只说「必须与参考图一致」。
    # 原因(实测):逐镜生成的图里,人物脸、房间背景、产品形状都在漂 ——
    # 「人物长相与服装必须与参考图中的模特完全一致」这种笼统话模型执行不了,
    # 它不知道该锁哪几项。参考项目把它拆成可核对的清单
    # (references/seedance-knowledge.md:「产品外形 1:1 还原参考图,颜色与实物一致」)。
    consist = ""
    if refs:
        # **每镜只有一张参考图**,所以措辞只能是「参考图」而不是「参考图1/参考图2」——
        # 此前写成"参考图1…参考图2…",而本镜实际只传了一张,模型会去找不存在的第 2 张。
        if has_presenter_ref:
            consist += (", 同一人物跨镜完全一致:五官、脸型、发型、肤色、**服装款式与颜色**"
                        "与参考图完全相同,是同一个人,不是长相相近的另一个人;"
                        "服装不得逐镜变化")
        if has_product_ref:
            consist += (", 产品外形 1:1 还原参考图的形状与轮廓,颜色、材质、光泽一致,"
                        "全片是同一件产品,不做成别的形状(既不变方也不变圆),"
                        "不改变大小比例,不凭空增加包装盒或外壳")
    # ── 场景一致性:同一条片子应当在同一间房里拍 ──
    # 短剧侧锁场景靠 scenes.image_url 作参考图,但那是「每镜都传全量参考图」;
    # 复刻这边每镜只传一张,再塞一张场景图就回到双图对称融合的坑。
    # 折中:**文字锁场景** —— 把首镜的场景描述固化进后续所有镜的提示词。
    # 这解决的是「同一间房」这个最显眼的漂移(实测 6 镜各画各的房间)。
    scene_lock = str(clone.get("scene_prompt") or "").strip()
    if not scene_lock:
        first_done = next((x for x in boards
                           if int(x.get("number", 0)) == 1 and x.get("first_frame")), None)
        if first_done is not None and int(b.get("number", 0)) != 1:
            scene_lock = ("与本片第一镜完全相同的同一间室内场景、同一时间(夜晚)、"
                          "同一光源方向与色温、同一组陈设与背景布置")
    # 静帧取动作时序串(姿态更具体),无时序退回动作概述
    steps = [str(s).strip() for s in (b.get("action_steps") or []) if str(s).strip()]
    action_txt = "，".join(steps) if steps else str(b.get("action") or "展示产品")
    # 优先用 rewrite_boards_for_product 改写过的 prompt —— 它已经把原片实物
    # 全替换成新产品了;退回拼装时用 action_steps,而 action_steps 同样已改写。
    # 时间锚点此前完全没用上(start/end 拆了却不进提示词),视频模型拿不到时间轴。
    span = ""
    try:
        st, en = float(b.get("start") or 0), float(b.get("end") or 0)
        if en > st and f"{st:g}-{en:g}秒" not in str(b.get("prompt") or ""):
            span = f"{st:g}-{en:g}秒:"
    except (TypeError, ValueError):
        span = ""
    rewritten = str(b.get("prompt") or "").strip()
    # 特写/微距镜**不拼人物描述**:这类镜头只拍手与产品,提示词里一旦出现
    # "XX出镜人物…",模型就会在纯产品画面里凭空造出一张脸(实测镜 2 右侧
    # 出现一个张嘴嘶吼的半透明女鬼,守卫里的 no onlookers 压不住 —— 那是
    # 提示词自己要求出现人物的)。
    _no_person = any(w in _shot_kind for w in ("特写", "微距"))
    if rewritten:
        core = rewritten
    elif _no_person:
        core = (f"{b.get('shot','特写')},{action_txt},"
                f"画面只有产品与手部特写,{product_desc}:{b.get('product_use','')}")
    else:
        core = (f"{b.get('shot','中景')},{presenter_desc},{action_txt},"
                f"画面突出{product_desc}:{b.get('product_use','')}")
    tail = consist + (", " + scene_lock if scene_lock else "") + \
        ", 运镜与光线参考带货实拍视频, 清晰锐利, 电影质感"
    # 预算只约束**本镜的内容部分**(风格前缀 + 参考项目尾套合计 ~590 字符,
    # 它们是平台级固定文案,砍它等于换风格/丢掉一致性约束)。
    # 之前把全长一起塞进 200 字上限,算下来留给内容的额度是 **负 410** ——
    # 于是每镜内容都被砍到 40 字符,只剩 "A young woman with long dark hair wearin"…
    # 模型看不到「白色纸盒」「口红」,于是 6 镜全画成同一张「沙发上女性」插画
    # (实测:提示词两两差异很大,出的图却几乎一样)。这就是根因。
    if len(core) > SHOT_PROMPT_MAX_CHARS:
        print(f"[clone] 分镜#{board_number} 内容超 {SHOT_PROMPT_MAX_CHARS} 字,已截断", flush=True)
        core = core[:SHOT_PROMPT_MAX_CHARS]
    prompt = f"{style}, {span}{core}{tail}"
    out, _ = image_client.generate_image(prompt, out_name=f"clone_s{board_number}_{uuid.uuid4().hex[:6]}.png",
                                         config_id=config_id, reference_images=refs)
    # 记录首帧
    for x in boards:
        if int(x.get("number", 0)) == int(board_number):
            x["first_frame"] = str(out)
    # 首镜(#1)出图后,把它的场景锚固化:图存进 scenes 资产,描述写回 clone。
    # 后续镜据此锁「同一间房、同一时间、同一光源」—— 复刻每镜只传一张参考图,
    # 塞不进场景图,只能靠这个文字锚(实测 6 镜原本各画各的房间)。
    if int(board_number) == 1:
        clone["scene_image"] = config.path_to_media_url(out)
        clone["scene_prompt"] = ("室内夜间场景:同一张书桌、同一盏暖光台灯、"
                                 "窗外同一片城市夜景散景,墙面与陈设全程不变")
        sid = clone.get("scene_asset_id")
        if sid:
            db.ex("UPDATE scenes SET image_url=?, prompt=?, updated_at=? WHERE id=?",
                  (clone["scene_image"], clone["scene_prompt"], db.now(), sid))
        print("[clone] 场景锚已由首镜固化,后续镜将锁定同一场景", flush=True)
    clone["storyboards"] = boards
    meta["clone"] = clone
    _save_meta(drama_id, meta)
    return out


def generate_shot_video(drama_id: int, board_number: int, resolution: str = "720p",
                        config_id: int | None = None) -> Path:
    """第 3 步 b:图生视频(首帧=上一步生成的镜头图)。"""
    boards = _clone_storyboards(drama_id)
    b = next((x for x in boards if int(x.get("number", 0)) == int(board_number)), None)
    if not b:
        raise RuntimeError(f"分镜 #{board_number} 不存在")
    first = b.get("first_frame")
    if not first:
        raise RuntimeError(f"分镜 #{board_number} 还没有首帧图,请先生成镜头图")
    dur = max(4, min(12, int(float(b.get("end", 8)) - float(b.get("start", 0))) or 8))
    # 同 shot_tools.compose_from_image:必须拼风格前缀,raw prompt 没画风会被视频
    # 模型默认成通用动画/二次元风格
    style = db.style_prompt(db.drama_style(drama_id))
    body = _shot_video_prompt(b)
    video_prompt = f"{style}。{body}" if body else style
    path, _ = video_client.generate_video(
        video_prompt, resolution=resolution,
        duration=dur, first_frame=first, config_id=config_id)
    for x in boards:
        if int(x.get("number", 0)) == int(board_number):
            x["video"] = str(path)
    meta = _meta(drama_id)
    clone = meta.get("clone", {})
    clone["storyboards"] = boards
    meta["clone"] = clone
    _save_meta(drama_id, meta)
    return path


def clone_done_videos(drama_id: int) -> list[Path]:
    return [Path(x["video"]) for x in _clone_storyboards(drama_id) if x.get("video")]


def merge_clone(drama_id: int, out: str | Path | None = None, progress=None) -> Path:
    """第 4 步:按原片节奏无损拼接成片(复用 easymerger auto_merge)。"""
    from . import merge as merge_mod
    files = [str(p) for p in clone_done_videos(drama_id) if p.exists()]
    if len(files) < 2:
        raise RuntimeError("至少完成 2 个镜头视频才能拼接")
    out = out or (config.STATIC_DIR / "merged" / f"clone_{drama_id}_{uuid.uuid4().hex[:8]}.mp4")
    path, _channel = merge_mod.auto_merge(files, out, progress=progress)
    return path


# ═══ 升级:整段视频直传多模态理解(对齐原版 aedab02 / 7ae518c)═══
# 原版不再抽 8 帧,而是把整段 mp4 转 base64 data URL 内联给多模态模型,
# 模型直接给出按原片节奏的 duration / action_steps / dialogue / sound,
# 再替换式写回本集分镜(参考视频是唯一事实来源)。

MAX_DURATION_S = 120
MAX_SIZE_MB = 38

UNDERSTAND_PROMPT = """这是一条参考短视频。请逐镜头分析并输出分镜表 JSON,要求:
1. 结构照搬原片的镜头切点,覆盖整条视频,不遗漏开头结尾;
2. 每个镜头输出:index(从1递增)、duration(秒数,按原片节奏估)、title(4-10字镜头名)、
shot_type(景别:近景/中景/全景/特写)、camera(运镜)、action_steps(连续动作时序数组,每步一句可见的动作描述)、
dialogue(台词数组,格式"说话人:内容",无则空数组)、sound(环境音/音效描述)。
3. 只输出 JSON:{"shots":[…]},不要解释。"""


def probe_video(path) -> dict:
    """ffprobe 探测时长/体积。"""
    ff = config.find_ffprobe()
    dur = 0.0
    if ff and Path(path).exists():
        try:
            r = subprocess.run([ff, "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(path)],
                               capture_output=True, text=True, timeout=30)
            dur = float((r.stdout or "0").strip() or 0)
        except Exception:  # noqa: BLE001
            dur = 0.0
    size_mb = (Path(path).stat().st_size / 1048576) if Path(path).exists() else 0.0
    return {"duration": dur, "size_mb": size_mb}


def transcode_if_needed(path, episode_id: int):
    """超时长(>120s)或超体积(>38MB)先转码(原版同参数:scale=-2:720 -t 120 crf 28)。"""
    info = probe_video(path)
    if info["duration"] <= MAX_DURATION_S and info["size_mb"] <= MAX_SIZE_MB:
        return Path(path), False
    ff = config.find_ffmpeg()
    if not ff:
        return Path(path), False
    out_dir = config.STATIC_DIR / "temp"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"clone-{episode_id}-{uuid.uuid4().hex[:8]}.mp4"
    r = subprocess.run([ff, "-y", "-i", str(path), "-vf", "scale=-2:720", "-t", "120",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out)],
                       capture_output=True, timeout=900)
    # 转码可能失败(超时 / 缺 libx264 编码器 / 磁盘满),ffmpeg 不抛异常。
    # 原来无条件 return out, True —— 坏文件被当成"已转码"往下传,后面
    # 报的是"看不懂这个视频",根因完全指不到转码这步。
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass
        return Path(path), False
    return out, True


def _inline_video(path: Path) -> str:
    """整段视频转 data URL 内联(多模态模型直读,免抽帧丢时序)。"""
    return "data:video/mp4;base64," + base64.b64encode(path.read_bytes()).decode()


def understand_video(episode_id: int, video_url: str, config_id=None) -> int:
    """整段视频直传理解 → 替换式写回本集分镜,返回分镜数。"""
    src = (config.media_url_to_path(video_url)
           if str(video_url).startswith(("/static/", "static/")) else Path(video_url))
    if not src.exists():
        raise RuntimeError("参考视频文件不存在")
    work, _t = transcode_if_needed(src, episode_id)
    from ..agents import runner
    ep = db.q1("SELECT drama_id FROM episodes WHERE id=?", (episode_id,))
    prompt = UNDERSTAND_PROMPT + "\n\n参考视频(base64 内联,直接读取):"
    raw = runner.run_agent("storyboard_breaker", prompt, temperature=0.3,
                           config_id=config_id, image_urls=[_inline_video(work)],
                           lang=config.resolve_content_language(
                               ep["drama_id"] if ep else None))
    data = runner.extract_json(raw) or {}
    shots = data.get("shots") if isinstance(data, dict) else None
    if not shots:
        raise RuntimeError("视频理解未产出任何分镜,请重试")
    return replace_storyboards_from_shots(episode_id, shots)


def replace_storyboards_from_shots(episode_id: int, shots) -> int:
    """替换式写回本集分镜(参考视频是唯一事实来源:先清子表关联再删旧,再逐条 insert)。"""
    ts = db.now()
    for o in db.q("SELECT id FROM storyboards WHERE episode_id=?", (episode_id,)):
        db.ex("DELETE FROM storyboard_characters WHERE storyboard_id=?", (o["id"],))
        db.ex("DELETE FROM storyboard_props WHERE storyboard_id=?", (o["id"],))
    db.ex("DELETE FROM storyboards WHERE episode_id=?", (episode_id,))
    num = 0
    for shot in shots:
        num += 1
        actions = [str(x) for x in (shot.get("action_steps") or []) if str(x)]
        dialogue = [str(x) for x in (shot.get("dialogue") or []) if str(x)]
        desc = "\n".join(x for x in [
            ("动作:" + "；".join(actions)) if actions else "",
            ("台词:" + " / ".join(dialogue)) if dialogue else "",
        ] if x)
        video_prompt = "。".join(x for x in [
            str(shot.get("shot_type") or ""),
            str(shot.get("camera") or ""),
            "，".join(actions),
            ("台词(口型同步):" + " / ".join(dialogue)) if dialogue else "",
        ] if x)
        try:
            dur = int(round(float(shot.get("duration") or 5)))
        except (TypeError, ValueError):
            dur = 5
        db.ex("""INSERT INTO storyboards(episode_id,storyboard_number,title,shot_type,movement,
                  description,video_prompt,atmosphere,duration,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
              (episode_id, num, str(shot.get("title") or f"镜头{num}")[:60],
               str(shot.get("shot_type") or "")[:40] or None,
               str(shot.get("camera") or "")[:40] or None,
               desc, video_prompt, str(shot.get("sound") or "")[:200] or None,
               min(30, max(2, dur)), "pending", ts, ts))
    return num
