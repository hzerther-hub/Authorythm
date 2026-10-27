# -*- coding: utf-8 -*-
"""同款复刻(video-clone-lite 逻辑):看懂原片 → 备新料 → 逐镜重拍 → 按原片节奏拼接。

数据落在 dramas.metadata.clone:* 与 sys_task(type=clone_*)。
"""
from __future__ import annotations

import base64
import json
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
    if kind == "presenter":
        # 标记「用户上传过出镜照」:prepare_presenter 的防覆盖守卫读这个键,
        # 但此前**全仓库没有任何地方写入它**(只有建项目时的 presenter_src 兜底)
        # —— 建项目没传照、事后才补传的用户,再点「AI 生成出镜模特」会把照片
        # 顶掉(实测漏洞,守卫形同虚设)。
        clone["presenter_uploaded"] = True
    meta["clone"] = clone
    _save_meta(drama_id, meta)
    return str(dst)


def refresh_clone_prompts(drama_id: int) -> str | None:
    """复刻出镜人物:按角色行字段**重新生成最终提示词**(写回 final_prompt)。

    换出镜照后样貌重读、旧提示词作废,由这里按新字段重出一份 —— 用户要求
    「上传后要将提示词按图片重新生成」。失败打印日志返回 None,不打断业务。
    """
    row = _clone_asset_row(drama_id, "presenter")
    if not row:
        return None
    from . import prompts_gen
    try:
        return str(prompts_gen.character_prompt(row["id"]))
    except Exception as exc:  # noqa: BLE001
        print(f"[clone] 最终提示词重生成失败({exc})", flush=True)
        return None


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
        # ── 分镜文本跟着产品走(通用,不限品类)──
        # 换产品图后 product_desc 只管生图提示词,已生成分镜里的
        # action / product_use / **line(推测口播)** 还写着旧产品 ——
        # 实测:动作都换成玉手镯了,口播还在说"刚到的新口红"(旧产品),
        # 合成的片子嘴上夸的是换掉前的货。这里用现成的
        # rewrite_boards_for_product 把整份分镜文本按新产品重写一遍;
        # 改写失败保留原表(用户可手动改口播,见 _shot_line)。
        boards = clone.get("storyboards") or []
        if boards and desc:
            new_boards = rewrite_boards_for_product(
                boards, desc, str(clone.get("presenter_desc") or ""),
                config_id=config_id)
            if new_boards and new_boards != boards:
                clone["storyboards"] = new_boards
                print("[clone] 产品已更换,分镜文本(action/口播)已按新产品重写",
                      flush=True)
    else:
        # 换出镜照 = 换了人:旧三视图还是**上一张脸**,必须作废重生成,否则分镜
        # 参考锁的仍是旧人(实测:换照后首帧出的是前一张脸);描述同样作废,
        # 让 sync_assets 用新照片重读外观/服装。
        clone.pop("turnaround_image", None)
        clone.pop("turnaround_swapped", None)
        clone.pop("presenter_desc", None)
        clone.pop("presenter_styling", None)
        cid, pid, _sid = sync_assets(drama_id, config_id=config_id)
        if cid:
            clone["presenter_asset_id"] = cid
            # 样貌已按新照片重读(见 sync_assets),最终提示词跟着重生成 ——
            # 否则提示词描述的还是上一张照片的人物(用户实测反馈)。
            refresh_clone_prompts(drama_id)
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
    # ffprobe 优先;本机没有系统 ffprobe(实测:Anaconda/用户 PATH 都没有,
    # 只有剪映自带的裸 ffmpeg)→ 用 cv2 兜底读帧数/FPS,opencv 本就是依赖。
    fp = config.find_ffprobe()
    if fp:
        out = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", str(video_path)], capture_output=True, text=True, timeout=30)
        try:
            return float(out.stdout.strip())
        except Exception:  # noqa: BLE001
            return 0.0
    try:
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        dur = float(n) / float(fps) if fps and fps > 0 else 0.0
        return dur if dur > 0 else 0.0
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
    prompt = """这张照片是一个带货视频里要出镜的真人模特。请只描述**这个人的长相**,
**完全忽略背景、灯光、道具、画面氛围**,输出 JSON:
{
 "appearance": "外观:性别年龄、脸型、五官特征、肤色、发型发色(30字内)"
}
要求:
1. 只写照片里**真实可见**的头部与体貌特征,**不要臆造**;
2. **不要描述服装/配饰/鞋履** —— 复刻的着装跟原片分镜走,与出镜照无关;
3. 不要写背景描述。"""
    try:
        raw = text_client.chat(prompt, temperature=0.3, max_tokens=1024,
                               json_mode=True, config_id=config_id,
                               image_urls=[_image_data_url(p, mime)])
        data = runner.extract_json(raw) or {}
        app_ = str(data.get("appearance") or "").strip()
        # **只回长相**:服装/配饰不取出镜照(用户要求)—— 复刻的着装跟原片
        # 分镜文案走,锁定到照片衣服反而让成片服装跟原片对不上。
        return {"appearance": app_} if app_ else None
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
- shot(景别)、camera(运镜方式)—— 完全沿用

═══ 必须完全重新设计的(原片的动作一律作废)═══
- action / action_steps / product_use / prompt
- **line(推测口播/字幕)也必须同步改写** —— 口播是博主在夸产品,夸的必须是
  **新产品**。实测教训:动作都换成玉手镯了,口播还在说"打开看着口红正红",
  合成出来的片子嘴上说的是旧产品。要求:
  · 保留原 line 的结构(如「无明确商品字幕;推测口播:"…"」这类前缀照留),
    只替换引号内的口播内容;
  · 字数与原口播相近(视频要按它对口型,差太多会超时/不够长);
  · 只夸新产品描述里明确写出的颜色/材质/质感,**不许臆造**它没有的功效。

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
characters(本镜出镜人物名数组), props(本镜出现的道具名数组), scene(本镜场景名)

其中 prompt 是该镜的重绘提示词(英文),必须满足:
- 只描述**新产品与新人物**,原片产品与原片包装一个字都不许出现
- 写出时间锚点(如"0-4 seconds: ..."),必须与该镜 start/end 一致
- 只讲一个重点,只用一种主运镜

**characters / props / scene 是资产绑定字段**(与短剧分镜同构):写本镜里
**实际出现**的人物/道具/场景的名字;没出现就写空数组/空串。这三个字段
决定本镜把哪些参考图喂给模型、特写镜是否带人物立绘 —— 写错会导致
画面里的人物与设定图对不上。名称沿用原分镜表里已有的写法,不要新造。"""


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
            # 资产绑定(角色/道具/场景):改写后的画面内容变了,绑定可能也变
            # (原片里只摆手镯的镜,新产品是戒指 → 道具引用要跟着变)。
            # 但模型给的可能是编的名字,所以**只在原表已有绑定时**才采纳,
            # 原表没绑定就不凭空造(否则会引入对不上的名字)。
            for k in ("characters", "props", "scene"):
                if row.get(k) and new.get(k):
                    row[k] = new[k]
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

    **资产引用字段**(characters/props/scene)与短剧侧分镜同构:短剧分镜的
    video_prompt 里带 @角色名/@场景名/@道具名,模型据此把画面里的对象
    对上参考图;复刻此前完全没有这一层,三个资产是「每镜无差别全带」,
    提示词里也没有名字可指 —— 于是「这一镜到底该锁谁」无处表达。
    这里给复刻补上同构的三个字段。
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
        # 资产引用(名字数组/单值),与短剧侧同构;模型没给就空,后面按需补
        "characters": [str(x).strip() for x in (s.get("characters") or []) if str(x).strip()],
        "props": [str(x).strip() for x in (s.get("props") or []) if str(x).strip()],
        "scene": str(s.get("scene") or s.get("location") or "").strip(),
    }


CLONE_PRESENTER_NAME = "出镜人物"
CLONE_PRODUCT_NAME = "主推产品"

# 「通用重绘要求」的默认值(用户可改可清空,见 main_window 的 ghint 弹窗):
# 通用质量规则不写死在管线里 —— 比如对戒/情侣款产品合法地需要两个人,
# 写死的「严禁第二个人」会毁掉那类项目。管线只在设置表有值时才注入。
DEFAULT_CLONE_RULES = (
    "画面中只有出镜人物一个人,产品在她本人手上或身前,严禁出现第二个或多个人物;"
    "产品的颜色只属于产品本身,不得染到人物的服装、皮肤或背景")
CLONE_SCENE_NAME = "主场景"

# ── 复刻资产的「身份键」:一律用 id,不用名字 ──
#
# 背景(2026-10-27 实测):复刻的三个资产(出镜人物/主推产品/主场景)此前有 8 处
# **按名字**查库(SELECT ... WHERE drama_id=? AND name='出镜人物'),于是用户一旦
# 在资产详情弹窗里改名字,整条复刻链就断了:
#   · 素材行点「当前出镜人/当前产品图」→ 按旧名查不到 → 弹窗打不开(提示
#     「还没有生成该资产」),用户以为资产没了;
#   · sync_assets._upsert 按旧名 upsert → **新建一条重复资产**(旧名那条还在),
#     于是资产页出现两个「出镜人物」,三视图写进旧行、新行是空壳;
#   · refresh_clone_prompts / build_presenter_turnaround 读样貌 → 读到空,
#     人物文字锚静默消失(服装/发型逐镜漂的老毛病又回来了);
#   · 提示词里的名字却**是对的**(generate_shot_image 按 id 读名字)—— 于是
#     用户看到「名字生效了」,其它却全坏,极难自查。
#
# 修法:资产身份一律以 metadata.clone 里的 *_asset_id 为准,名字只是**展示**。
# 名字改成什么都无所谓;id 丢了(老项目/手工删过资产)才回退到按名字找一次。
_ASSET_KINDS = {
    "presenter": ("characters", "presenter_asset_id", CLONE_PRESENTER_NAME),
    "product":   ("props",      "product_asset_id",   CLONE_PRODUCT_NAME),
    "scene":     ("scenes",     "scene_asset_id",     CLONE_SCENE_NAME),
}


def _clone_asset_row(drama_id: int, kind: str) -> dict | None:
    """按 id 查复刻资产行(名字不是身份)。找不到再回退按名字找一次。

    kind ∈ {"presenter", "product", "scene"}。
    """
    table, id_key, default_name = _ASSET_KINDS[kind]
    meta = _meta(drama_id)
    clone = meta.get("clone", {}) or {}
    aid = clone.get(id_key)
    row = None
    if aid:
        try:
            r = db.q1(f"SELECT * FROM {table} WHERE id=?", (int(aid),))
        except (TypeError, ValueError):
            r = None
        if r:
            row = dict(r)
    if row is None:
        # 回退:老项目没记 id,或资产被手工删过 → 按默认名找一次
        r = db.q1(f"SELECT * FROM {table} WHERE drama_id=? AND name=?",
                  (drama_id, default_name))
        if r:
            row = dict(r)
            # 顺手把 id 记回 metadata,下次就都走 id 了
            clone[id_key] = row.get("id")
            meta["clone"] = clone
            try:
                _save_meta(drama_id, meta)
            except Exception:  # noqa: BLE001 —— 回退写回失败不影响主流程
                pass
    return row


def _clone_asset_id(drama_id: int, kind: str) -> int | None:
    row = _clone_asset_row(drama_id, kind)
    return (row or {}).get("id")


def _turnaround_block() -> str:
    """角色三视图规范块(复用漫画侧的既有实现,不另造一套)。

    复刻项目的主图必须是**你自己的人物三视图**(正面/侧面/背面),而不是参考视频里
    的人 —— 这是「换掉主角」的前提:参考图锚的是脸与服装,锚的是原片主角就白搭。
    """
    from .comic import _TURNAROUND_BLOCK
    return _TURNAROUND_BLOCK


def build_presenter_turnaround(presenter_path,
                               config_id: int | None = None,
                               style_value: str = "",
                               drama_id: int | None = None) -> Path:
    """用**你上传的人物照**生成全身三视图主图,返回本地路径。

    为什么要有这一步(一致性问题的根):
    一张正脸特写能锁五官,但锁不住**体型、身高比例、服装全貌**;而复刻要跨 4–6 镜
    保持同一人,短剧侧早就用三视图解决这件事(comic._TURNAROUND_BLOCK:正脸特写 +
    正面/侧面/背面三张等高全身),这里直接复用同一份规范。

    参考图只传**你那张人物照**本身(单图,不给模型第二张图去对称融合)。

    视觉风格**跟随项目**(用户定版:「复刻时要将视觉风格带入生成」):建项目时
    选的「视觉风格」(dramas.style)必须贯穿复刻全链路,三视图不例外 —— 否则
    首帧是 3D、角色资产是写实,同一部片两种画风。此前「写死写实底」的理由
    (插画笔触让五官失真)只对插画类风格成立,不该替用户做决定;写实预设的
    负面词(NOT illustration 等)只在写实底时带上,不然与插画类风格自相矛盾。
    未选风格时退回写实电商底(角色资产图用中性背景最稳)。
    """
    style = (db.style_prompt(style_value).strip() if style_value else "")
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
    # 设定图的底色与「全身入镜」要求与风格解耦,必须单独强调:风格预设里没有
    # 这两条,漏了就会出七分身/带场景的设定图,切格与换脸都会被干扰。
    backdrop = ("clean seamless pure-white studio backdrop, the full body is "
                "visible head to toe in every view, crisp sharp focus, "
                "true-to-life body proportions, high detail")
    look = f"{style}, {backdrop}" if style else f"{realistic}"
    # 样貌/妆造**文字**必须跟着进提示词:实测只靠参考图,agnes 会照收自拍却把
    # 服装自由发挥(上传白毛衣自拍 → 三视图出青蓝色套装,用户实测「衣服不到位」)。
    # 但只能给**压缩后的要点**:完整叙述有 250+ 字还带姿态描写(「双肩微含」),
    # 实测把四格布局稀释成两个重复立绘(用户实测「也不是三视图了」)——生图模型
    # 的提示词预算有限,布局规格必须占大头。
    person = ""
    if drama_id:
        # 按 id 查(改名后按名字查会落空 → 人物文字锚静默消失 → 服装发型逐镜漂)
        row = _clone_asset_row(drama_id, "presenter")

        def _compact(t: str, limit: int) -> str:
            t = " ".join(str(t or "").split())
            return t[:limit].rstrip("，。,;； ") if len(t) > limit else t

        if row:
            a = _compact(row["appearance"], 60)
            s = _compact(row["styling"], 60)
            person = "；".join(x for x in (a, s) if x)
    prompt = (f"{look}\n"
              "以参考图中的人物为原型,生成该角色的**标准参考图**。"
              + (f"\n外观与服装要点(与参考图一致,不得换装):{person}\n"
                 if person else "")
              + f"{_turnaround_block()}\n"
              "FINAL CHECK: exactly 4 panels in ONE horizontal row — panel 1 "
              "front-face close-up, panels 2-4 front/side/back full-body of the "
              "SAME single character. No duplicated figures outside these 4 panels.")
    out, _ = image_client.generate_image(prompt, out_name="clone_turnaround.png",
                                         config_id=config_id,
                                         reference_images=[str(presenter_path)],
                                         skip_guard=True)  # 三视图自含构图,人数守卫会砍特写格
    return out


def swap_clone_face(source_path, template_path,
                    swap_cfg_id: int | None = None) -> Path:
    """把 source 里的脸换到 template 图上,返回换好脸的新图路径。

    复刻线的两个用途:
    · 三视图:template=整张三视图,swap_all_faces=True(默认)把**所有视图**的脸
      都换掉(特写格 + 正/侧/背面全身格)—— 只换一张 = 半张是本人半张是路人。
    · 单镜首帧:自动链路(三视图换脸 + 首帧参考立绘)已把脸锚住,但生图模型
      偶尔仍画偏,这是成本最低的兜底(只动人脸像素,不重新生图)。

    为什么走 swap_one_by_provider 而不是写死 swap_remote:本地 InsightFace 引擎的
    用户此前在管线里走不了换脸(写死远程),失败还被静默吞掉,拿着「路人脸」
    当参考图而不自知。
    失败**向上抛**,由调用方降级并标记 turnaround_swapped=False 让界面如实提示;
    不在本函数里吞异常。
    """
    from ..ai import face_swap   # face_swap 在 app.ai,不是 app.pipeline
    # provider 必须显式传:用户选 remote-faceswap 配置时,不传 provider 会落进
    # 本地兼容路径 swap_one —— 它发请求**不带 X-API-Key**,远程服务直接
    # 401「无效的 API Key」(实测:任务台账 sys_task #1621,配置 face.mei.biz)。
    # 选了哪条配置就按它的 provider 路由。
    provider = None
    if swap_cfg_id:
        row = db.q1("SELECT provider FROM ai_service_configs WHERE id=?",
                    (int(swap_cfg_id),))
        provider = (row or {}).get("provider") if row else None
    return face_swap.swap_one_by_provider(str(source_path), str(template_path),
                                          provider=provider, config_id=swap_cfg_id)


def standing_ref_of(turnaround_path) -> Path | None:
    """三视图 → **单人立绘**(切出其中一格),这才是分镜用的参考主图。

    为什么必须切格(实测教训):三视图里同一角色出现 4 次(1 特写 + 正/侧/背面),
    整张喂给分镜当参考,模型照着「参考图里有多个人」画,画面必然复制人
    (实测中近景镜出三个并排人物)。漫画线在 ep79 用切格根治了同一问题
    (comic._single_pose_ref:按列空白检测立绘簇、裁出单姿势一格,不依赖
    「恰好四格」),这里直接复用,不另造一套。
    切格失败(打不开图等)退回整图 —— 有多实例风险也好过没有参考图。
    """
    ta = _resolve_local(turnaround_path)
    if not ta:
        return None
    try:
        from .comic import _single_pose_ref
        return Path(_single_pose_ref(str(ta)))
    except Exception as exc:  # noqa: BLE001
        print(f"[clone] 三视图切格失败({exc}),整图兜底", flush=True)
        return ta


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

    def _upsert(table: str, name: str, url: str, extra: dict,
                id_key: str = "") -> int | None:
        """按 **id** 找现有行(名字不是身份),找到就更新、找不到才建。

        为什么不能按名字找:用户可以在资产详情弹窗里改名字(需求:自定义
        角色名/场景名/道具名)。按名字 upsert 的后果是**改名后这里认不出
        旧行 → 新建一条重复资产**(资产页出现两个「出镜人物」,三视图写进
        旧行、新行是空壳),而且**每次 sync_assets 都会再复制一份**。
        名字是**展示字段**,用户改了就该保留,不能被这里覆盖回默认值。

        id_key:metadata.clone 里存该资产 id 的键(presenter_asset_id 等)。
        """
        row = None
        if id_key:
            aid = clone.get(id_key)
            if aid:
                r = db.q1(f"SELECT id, name FROM {table} WHERE id=?", (int(aid),))
                if r:
                    row = r
        if row is None:
            # 回退:老项目没记 id → 按默认名找一次
            r = db.q1(f"SELECT id, name FROM {table} WHERE drama_id=? AND name=?",
                      (drama_id, name))
            if r:
                row = r
        cols = {"drama_id": drama_id, "name": name, "image_url": url,
                "updated_at": ts, **extra}
        if row:
            # **不覆盖 name**:用户自定义的名字保留(只有"还没有名字"才填默认)
            cols["name"] = (row["name"] or "").strip() or name
            sets = ",".join(f"{k}=?" for k in cols)
            db.ex(f"UPDATE {table} SET {sets} WHERE id=?",
                  (*cols.values(), row["id"]))
            return row["id"]
        db.ex(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
              tuple(cols.values()))
        return db.get_db().execute(
            f"SELECT id FROM {table} WHERE drama_id=? AND name=? ORDER BY id DESC LIMIT 1",
            (drama_id, name)).fetchone()["id"]

    # 资产名支持自定义(2026-10-27 用户要求:建项目时填产品名/出镜人名字,
    # 分镜绑定与提示词里直接叫名字,不再是笼统的「出镜人物/主推产品」)
    presenter_name = clone.get("presenter_name") or CLONE_PRESENTER_NAME
    product_name = clone.get("product_name") or CLONE_PRODUCT_NAME
    cid = _upsert("characters", presenter_name,
                  config.path_to_media_url(presenter) if presenter else "",
                  # appearance / styling 填上:短剧侧的漫画链路会读这两个字段做
                  # **文字层**的资产锁定(comic.py:287),只靠图锁不住服装/妆造。
                  # 这里至少把人物描述与产品描述分别写进去,供后续提示词引用。
                  {"role_type": "presenter",
                   "appearance": clone.get("presenter_desc") or "",
                   "styling": clone.get("presenter_styling") or "",
                   "created_at": ts}, id_key="presenter_asset_id") if presenter else None
    # 人物外观/服装描述只读一次并落库:generate_shot_image / rewrite /
    # characters.appearance 都读 clone.presenter_desc,但此前**没有任何地方给它
    # 赋值**(read_presenter_desc 的结果只在全身像函数内部用完即弃),首帧提示词
    # 里的人物描述一直是兜底文案「亲和力强的出镜人物(见模特形象)」。
    if presenter and not (clone.get("presenter_desc") or "").strip():
        desc = read_presenter_desc(presenter, config_id=_selected_text_cfg())
        if desc:
            clone["presenter_desc"] = desc.get("appearance") or ""
            clone.pop("presenter_styling", None)   # 出镜照不提供服装描述(用户要求)
            # 新照片的描述必须写回角色行,否则详情弹窗还显示上一张照的样貌/妆造
            # (实测:换成白毛衣自拍照后,妆造仍写「黑色细肩带上装」,与三视图
            # 服装对不上)。妆造清空(出镜照不提供服装描述);最终提示词一并作废
            # —— 它描述的还是旧照片,由 refresh_clone_prompts 按新字段重生成。
            if cid:
                db.ex("UPDATE characters SET appearance=?, styling='', "
                      "final_prompt='', updated_at=? WHERE id=?",
                      (clone["presenter_desc"], db.now(), cid))
    # 角色资产 = **三视图**(正脸特写 + 正面/侧面/背面)+ 生成后立刻换脸 —— 用户定版:
    # 复刻不要全身像。此前「单人全身像当分镜参考」的路线(纯文字底图 + 换脸)实测
    # 两个致命伤,正是用户抱怨的「首帧的人跟三视图不是同一人 / 衣服变了」:
    #   · 服装是模型按文字描述自由发挥的,与上传照/三视图对不上;
    #   · 脸经「换到全身像 → 全身像再当参考图」两次转手,与三视图不是同一人。
    # 三视图从上传照生成(服装/体型同源),换脸把五官钉死;多实例问题不在生成端
    # 解决而在**使用端**解决 —— 分镜参考用切出的单人立绘(standing_ref_of)。
    _cfg = config_id or _selected_image_cfg()
    _drow = db.q1("SELECT style FROM dramas WHERE id=?", (drama_id,))
    _style_value = (_drow["style"] if _drow else "") or ""
    if presenter and not clone.get("turnaround_image"):
        try:
            ta = build_presenter_turnaround(presenter, config_id=_cfg,
                                            style_value=_style_value,
                                            drama_id=drama_id)
            swapped = True
            try:
                ta = swap_clone_face(presenter, ta,
                                     swap_cfg_id=_selected_swap_cfg())
            except Exception as exc:  # noqa: BLE001
                swapped = False
                print(f"[clone] 三视图换脸失败({exc}),保留生成底图,"
                      f"可在界面点「手动换脸」重试", flush=True)
            clone["turnaround_image"] = str(ta)
            clone["turnaround_swapped"] = swapped
            clone["clone_turnaround_at"] = ts
            print(f"[clone] 人物三视图已生成(换脸{'成功' if swapped else '失败'}):"
                  f"{Path(str(ta)).name}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[clone] 三视图生成失败({exc})", flush=True)
    # 资产图两列都写**三视图整张**。image_url 曾写「三视图切出的单人立绘」,
    # 用户已定版废弃单人全身展示(实测:重建后角色资产页变成单人全身,被质疑
    # 「早就不用了为什么还弹」)。切格立绘只在管线内部由 standing_ref_of 即时
    # 计算,不落库;生成端读 clone["turnaround_image"],不读 characters 列。
    # 只动 name=出镜人物 这一行 —— 用户手动添加的角色不会被碰。
    if clone.get("turnaround_image"):
        _ta_url = config.path_to_media_url(clone["turnaround_image"])
        # 按 **id** 写回:按名字写的话,用户改了角色名就写不进去(静默失效),
        # 三视图生成好了却没进资产行 → 首帧参考图仍是旧图。
        _prow = _clone_asset_row(drama_id, "presenter")
        if _prow:
            db.ex("UPDATE characters SET comic_image_url=?, image_url=? "
                  "WHERE id=?",
                  (_ta_url, _ta_url, _prow["id"]))
    pid = _upsert("props", product_name,
                  config.path_to_media_url(product) if product else "",
                  {"type": "product", "description": clone.get("product_desc") or "",
                   "created_at": ts}, id_key="product_asset_id") if product else None
    if pid and clone.get("product_desc"):
        db.ex("UPDATE props SET description=? WHERE id=?", (clone["product_desc"], pid))

    # 场景资产:复刻的镜头虽然每镜换内容,但**场景应当统一**(同一间房/同一个
    # 布景),否则跨镜背景漂移最明显。首镜出图后把它的图存成场景资产,后续镜
    # 以它为背景参照。没有场景图时用场景描述建一条无图资产,至少能锁文字。
    sid = _upsert("scenes", CLONE_SCENE_NAME, clone.get("scene_image") or "",
                  {"location": clone.get("scene_location") or "",
                   "prompt": clone.get("scene_prompt") or "",
                   "lighting": clone.get("scene_lighting") or "",
                   "created_at": ts}, id_key="scene_asset_id")
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


def _asset_names_block(clone: dict) -> str:
    """分镜 prompt 的「已知资产」段 —— 绑定字段必须**逐字**用这些名字。

    自定义名(建项目时填的产品名/出镜人名字,见 new_project_dialog)优先,
    缺省回落 出镜人物/主推产品。
    实测教训:不把名字喂给模型,它会自创绑定名(「女生」「窗边木桌前」),
    与资产名对不上 → 绑定全部失锚 → 参考图被裁得只剩主图,一致性崩坏
    (窗外人脸、服装漂移都由此来,2026-10-27 实测)。
    """
    pn = clone.get("presenter_name") or CLONE_PRESENTER_NAME
    gd = clone.get("presenter_gender") or "女"
    pr = clone.get("product_name") or CLONE_PRODUCT_NAME
    return (f"已知资产(本片固定,绑定字段只能用这些名字):\n"
            f"- 出镜人物:「{pn}」({gd}性,所有出镜的都是这一个人)\n"
            f"- 主推产品:「{pr}」\n"
            f"- 主场景:「主场景」\n"
            f"characters 只能填 [\"{pn}\"] 或空数组;props 出现产品时填 [\"{pr}\"];"
            f"scene 场景出现时填 \"主场景\";自创名字会被系统忽略。")


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
        prompt = (UNDERSTAND_PROMPT + "\n\n" + _asset_names_block(clone)
                  + (f"\n\n总时长 {dur:.1f} 秒。"
                     f"{('补充说明: ' + extra_hint) if extra_hint else ''}"))
        raw = runner.run_agent("storyboard_breaker", prompt, temperature=0.3,
                               config_id=config_id, image_urls=[_inline_video(work)],
                               lang=config.resolve_content_language(drama_id))
        data = runner.extract_json(raw) or {}
        # 直传用 shots/duration/dialogue,统一映射到抽帧版的字段名,
        # 这样下游(rewrite / generate_shot_image / _shot_video_prompt)
        # 完全不用关心这条分镜表是哪条路产出的。
        # 模型也可能直接回 shots 数组(不带外层对象):先 isinstance 再 .get,
        # 否则 list.get 直接 AttributeError(rewrite 那条路就是这么写的)。
        shots = data if isinstance(data, list) else data.get("shots")
        boards = [_normalize_shot(s, i + 1) for i, s in enumerate(shots or [])]
    else:
        frames = extract_frames(ref, count=8)
        # 帧目录落库:场景锚提取(extract_scene_anchor)要靠这些帧挑代表帧。
        # 此前目录用完即弃也不落库,首帧阶段想参照原片背景都拿不到图。
        clone["frames_dir"] = str(frames[0].parent)
        image_urls = [_image_data_url(f) for f in frames]
        frame_desc = "\n".join(
            f"第{i}帧(约 {dur * i / (len(frames) + 1):.1f} 秒处)"
            for i, _ in enumerate(frames, 1))
        prompt = f"""下面是一条待复刻的带货/种草类视频,已按时间均匀抽出 {len(frames)} 帧随消息附上(顺序对应):
总时长: {dur:.1f} 秒
{frame_desc}
{_asset_names_block(clone)}
{('补充说明: ' + extra_hint) if extra_hint else ''}

请逐帧仔细看图,推断该视频的完整分镜表(8 秒上下每镜,共 2-6 镜):
- 每帧识别:场景、人物与景别(远/全/中/近/特)、人物动作、出现的商品及其使用方式、画面字幕或口播要点
- 相邻两帧画面差异明显即发生了镜头切换,据此划分镜头边界与起止时间
每镜输出:
- number, start, end, shot(景别), camera(运镜:固定/推/拉/摇/移/跟/升降等,选一词)
- action(一句话动作概述), action_steps(连续动作时序数组,2-5 步,每步一句按时间先后排列的可见动作)
- line(推测台词/字幕), product_use(产品如何出现)
- prompt(给文生视频模型的重拍提示词:主体+动作+运镜+光线+氛围,不写人名)
- characters(本镜出镜人物名数组), props(本镜出现的道具名数组), scene(本镜场景名)
  —— 资产绑定字段,与短剧分镜同构:决定本镜把哪些参考图喂给模型,
  取值规则见上方「已知资产」,自创名字会被系统忽略。
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
        # 模型可能直接回分镜数组(不带 storyboards 外层)。必须先判 isinstance
        # 再 .get —— 原来 `data.get(...) or (data if isinstance...)` 的写法在
        # data 是 list 时先执行 data.get,AttributeError,兜底分支永远走不到。
        boards = ((data.get("storyboards") if isinstance(data, dict) else None)
                  or (data if isinstance(data, list) else []))
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
    # 场景锚:分析阶段就从原视频提取(挑帧→环境描述→空景图),第一镜生成时
    # 就能带上场景参考。旧实现等首镜出图后写死一句与原片无关的场景描述,
    # 用户实测「背景跟原片对不上」的根因之一。失败不阻塞,退回纯文字锚。
    extract_scene_anchor(drama_id, config_id=_selected_image_cfg(),
                         text_cfg_id=config_id)
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


SCENE_PICK_PROMPT = """下面是同一条视频按时间均匀抽出的 {n} 帧画面(顺序对应,总时长 {dur:.1f} 秒)。
这是要被「换人复刻」的原片:人物会换成别人,但**拍摄环境必须原样保留**。
请挑出最能代表该视频发生环境的一帧,并给出整个视频**统一**的环境描述:
- 优先选**人物占比小、环境信息最多**的帧(墙面/家具/窗景/光源越全越好);
- 描述只写环境,一个字都不要提画面里的人。
只输出 JSON:
{{"frame": 帧序号(从 1 开始), "location": "地点一句话", "lighting": "光源与色温一句话", "prompt": "给文生图用的场景描述(60字内,不含任何人物)"}}"""


def extract_scene_anchor(drama_id: int, config_id: int | None = None,
                         text_cfg_id: int | None = None) -> bool:
    """从**原视频**提取场景锚:挑代表帧 → 多模态描述环境 → 生成同机位空景图。

    为什么必须在分析阶段就锁场景(用户实测痛点:「要拍出原视频的背景,
    保持场景一致性」):旧实现 scene_prompt 是首镜出图后**硬编码**的一句
    「室内夜间:书桌+台灯+城市夜景」—— 与用户原视频毫无关系,后续镜全被
    这句假描述带偏;而旧 scene_image = 首镜生成图,图里**带着人**,当第二
    参考图时模型照抄出「半透明第二人」(见 generate_shot_image 的注释)。

    空景图(去人)才是安全的场景锚:图里没有人可抄,才能与人物立绘组成
    「人 + 景」双参考。视觉风格(dramas.style)同样注入空景图 —— 场景锚与
    首帧同画风,模型不用自己跨风格翻译(用户定版:视觉风格带入全部生成)。
    任一步失败返回 False 不阻塞分镜分析,退回纯文字锚(旧项目行为)。
    """
    clone = _meta(drama_id).get("clone", {})
    ref = _resolve_local(clone.get("reference"))
    if not ref:
        return False
    try:
        frames = sorted(Path(str(clone["frames_dir"])).glob("f*.jpg")) \
            if clone.get("frames_dir") else []
        if len(frames) < 2:
            frames = extract_frames(ref, count=8)
            clone["frames_dir"] = str(frames[0].parent)
        dur = _duration(ref)
        raw = text_client.chat(
            SCENE_PICK_PROMPT.format(n=len(frames), dur=dur),
            system="你是影视美术指导,负责在原片里锁定拍摄环境。只输出 JSON。",
            temperature=0.2, json_mode=True, config_id=text_cfg_id,
            image_urls=[_image_data_url(f) for f in frames])
        d = runner.extract_json(raw) or {}
        idx = int(d.get("frame") or 1)
        pick = frames[max(0, min(len(frames) - 1, idx - 1))]
        location = str(d.get("location") or "").strip()
        lighting = str(d.get("lighting") or "").strip()
        prompt = str(d.get("prompt") or "").strip()
        if not prompt:
            print("[clone] 场景描述为空,跳过场景锚提取", flush=True)
            return False
        _drow = db.q1("SELECT style FROM dramas WHERE id=?", (drama_id,))
        style = db.style_prompt((_drow["style"] if _drow else "") or "")
        body = ("Remove every person from this photo. Keep the exact same camera "
                "angle, room structure, furniture, props, walls, windows and "
                "lighting positions. An empty establishing shot of the same "
                "location: no people, no silhouettes, no mannequins, "
                "no text, no watermark. 场景:" + prompt)
        if style:
            # 空景图与首帧同画风:首帧生成时拿它当参考,不用自己跨风格翻译
            body += f"。渲染风格严格参照:{style}"
        out = None
        # people=0 + 启用守卫(2026-10-27 实测:skip_guard=True 时「去人」指令
        # 只有一句英文,模型照样把参考帧里的人原样保留 —— 场景锚里坐着个人,
        # 后续每镜参考它都会多人)。people=0 会注入「画面不出现任何人物,
        # 也没有手/影子/倒影」强守卫 + 完整禁人负面词;reference_lock=False
        # 是必须的:参考帧里有人,绝不能说「参考图1=人物1的外貌来源」。
        for attempt in (1, 2):
            try:
                out, _ = image_client.generate_image(
                    body, out_name=f"clone_scene_{drama_id}.png", config_id=config_id,
                    reference_images=[str(pick)], people=0,
                    skip_guard=False, reference_lock=False)
                break
            except Exception as exc:
                if attempt == 2:
                    raise
                import time as _t
                print(f"[clone] 场景锚生图第{attempt}次失败({str(exc)[:120]}),3 秒后重试",
                      flush=True)
                _t.sleep(3)
        clone["scene_image"] = str(out)
        clone["scene_location"] = location
        clone["scene_lighting"] = lighting
        clone["scene_prompt"] = "。".join(x for x in (location, lighting, prompt) if x)
        sid = clone.get("scene_asset_id")
        if sid:
            db.ex("UPDATE scenes SET image_url=?, prompt=?, location=?, lighting=?,"
                  " updated_at=? WHERE id=?",
                  (config.path_to_media_url(str(out)), clone["scene_prompt"],
                   location, lighting, db.now(), sid))
        meta = _meta(drama_id)
        meta["clone"] = clone
        _save_meta(drama_id, meta)
        print(f"[clone] 场景锚已从原视频提取:第{idx}帧 → 空景图 {out.name}", flush=True)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[clone] 场景锚提取失败({exc}),退回纯文字锚", flush=True)
        return False


def _resolve_local(p) -> Path | None:
    """素材字段可能是本地绝对路径或 /static/ 媒体地址,统一转本地路径;不存在返回 None。"""
    if not p:
        return None      # 只传了出镜照没传产品图时 clone.product 是 None,直接 Path(None) 会炸
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


def board_asset_names(drama_id: int, board: dict) -> dict:
    """本镜要锁定的资产(名字)—— 与短剧侧同构的「@名字」来源。

    返回 {"characters": [名...], "props": [名...], "scene": 名}。

    规则:
    · 角色/道具:取 board 里的 characters/props 数组(模型拆解时给的),
      名字对不上已知资产时丢弃(拼错的名字进提示词比没有更糟);
    · 场景:单值,board["scene"];复刻只有「主场景」一个场景资产,认它;
    · board 没给(老分镜/模型没给)→ 全部回落到默认三资产
      (出镜人物 / 主推产品 / 主场景),保持既有行为不变。

    为什么要有这一层:短剧分镜的 video_prompt 带 @角色名/@场景名/@道具名,
    模型据此把画面里的对象对上参考图;复刻此前完全没有名字可指,
    三个资产「每镜无差别全带」—— 于是「这一镜该锁谁」无处表达,
    特写镜硬带人物立绘只能靠文字守卫硬压。
    """
    known = {}
    for kind in ("presenter", "product", "scene"):
        row = _clone_asset_row(drama_id, kind)
        known[kind] = (row or {}).get("name") or _ASSET_KINDS[kind][2]
    # 角色名白名单:已知资产名 + 分镜里给的名字(后者的合法性靠「能不能对上
    # 某个已知资产」判断 —— 复刻目前只有一个人物资产,分镜写别的名字说明
    # 模型在编,直接丢弃)。
    char_names = [str(x).strip() for x in (board.get("characters") or []) if str(x).strip()]
    valid_chars = [n for n in char_names if n == known["presenter"]]
    prop_names = [str(x).strip() for x in (board.get("props") or []) if str(x).strip()]
    valid_props = [n for n in prop_names if n == known["product"]]
    scene = str(board.get("scene") or "").strip()
    if scene and scene != known["scene"]:
        scene = ""
    return {
        "characters": valid_chars or ([known["presenter"]] if known["presenter"] else []),
        "props": valid_props or ([known["product"]] if known["product"] else []),
        "scene": scene or (known["scene"] or ""),
    }


def asset_ref_header(names: dict) -> str:
    """「出场人物 / 场景 / 道具」头行 —— 与短剧分镜 video_prompt 的写法对齐。

    短剧侧的分镜提示词第一行就是:
        出场人物:@陈默 @张雯 @赵刚  场景:@云脉科技大厦会议室
    模型据此把「@名字」与参考图对应起来。复刻此前只有英文 prompt,
    没有任何名字可指 —— 这行头就是补上的那一层。
    """
    bits = []
    if names.get("characters"):
        bits.append("出场人物:" + " ".join("@" + n for n in names["characters"]))
    if names.get("props"):
        bits.append("道具:" + " ".join("@" + n for n in names["props"]))
    if names.get("scene"):
        bits.append("场景:@" + names["scene"])
    return "  ".join(bits)


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
    # ── 人物文字锚惰性补齐 ──
    # sync_assets 里的填充是「一次性且静默」的:read_presenter_desc 那次若失败
    # (文本服务抖动/网关超时),presenter_desc 就永远空着,首帧提示词的人物
    # 描述退化为兜底文案 —— 实测表现就是发型/服装逐镜漂(用户截图:updo →
    # 披肩发,深色裙 → 绿裙)。这里在生成入口**惰性补齐**:空就现场读一次图
    # 并落库(只取长相,不提取服装 —— 着装跟原片分镜文案走),失败仅跳过
    # (下一镜再试),不阻断生成。
    if _resolve_local(clone.get("presenter")) and \
            not (clone.get("presenter_desc") or "").strip():
        try:
            # **必须用文本配置**:本函数的 config_id 参数是生图配置(agnes-image),
            # 塞进 read_presenter_desc 的多模态文本调用必然失败 —— 实测 6 镜
            # 连续提取失败、文字锚始终为空,就是这里错用了命名空间。
            _pd = read_presenter_desc(clone.get("presenter"),
                                      config_id=_selected_text_cfg())
        except Exception as exc:  # noqa: BLE001
            _pd = None
            print(f"[clone] 人物描述惰性提取失败({exc}),本镜用兜底描述", flush=True)
        if _pd and _pd.get("appearance"):
            clone["presenter_desc"] = _pd["appearance"]
            clone.pop("presenter_styling", None)   # 出镜照不提供服装描述(用户要求)
            meta["clone"] = clone
            _save_meta(drama_id, meta)
            print(f"[clone] 人物文字锚已补齐:外观 {len(clone['presenter_desc'])} 字",
                  flush=True)
        presenter_desc = clone.get("presenter_desc") or presenter_desc
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

        人物这一项用**三视图切出的单人立绘**(standing_ref_of):整张三视图里
        同一角色出现 4 次(1 特写 + 正面/侧面/背面),直接喂会把多实例一起画进
        画面(实测中近景镜出三个并排人物);切格后参考里只有 1 个人,复制人
        从源头消失,且脸/服装/体型与角色资产**完全同源** —— 用户实测痛点
        「首帧的人跟三视图不是同一人、衣服变了」由此对锚。
        旧路线的 presenter_fullshot(纯文字底图+换脸的单人全身图)已按用户要求
        **整体删除**(用户:「单人全身的字段也要删掉」)—— 三视图路线接管后
        它只剩误导性:文件还在时会被当成参考注入,把已废弃的全身图又拉回来。
        """
        if kind == "presenter":
            ta = clone.get("turnaround_image")
            if ta:
                s = standing_ref_of(ta)
                if s:
                    return s
            return _resolve_local(clone.get("presenter"))
        key = f"{kind}_asset_id"
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

    # ── 参考图:人物镜双锚「人物立绘 + 空景图」,特写镜单锚「产品图」──
    #
    # 历史实测,别退回去:
    # · 两张**同类型**图(人物+产品正面照)→ 对称融合出双头图 → 主体参考每镜
    #   只有 1 张,这条不变;
    # · 「主体 + 场景图」也出过半透明第二人 —— 但根因是当年场景图 = 首镜生成图,
    #   图里**本身画着人**,模型照抄了第二个人;不是「两张参考图」这件事的错。
    # · 现在场景锚是**从原视频抽帧去人**的空景图(extract_scene_anchor),图里
    #   没有人可抄,人物镜才能安全带第二锚:人锁三视图立绘(用户痛点「脸/衣服
    #   不是同一人」),景锁原视频空镜(痛点「背景跟原片对不上」)。
    scene_img = _resolve_local(clone.get("scene_image"))
    product_img = _asset_img("product")
    standing_img = _asset_img("presenter")     # 三视图切格立绘
    refs: list = []
    if main_img:
        refs.append(main_img)
    # ── 三要素(用户定版「每一镜都要有主图:三视图/产品图(道具)/场景图,
    # 结合提示生成」)── 默认**每一镜都带齐三张**,包括特写镜:特写的手部肤质
    # 也要有立绘可锚。角色分工靠提示词逐一点名(参考图1/2/3 各锁什么),
    # 特写镜的守卫(见下方 core 单肢规则)压住「照人物设定图画出全身」。
    # 人物照+产品照曾实测「对称融合双头」—— 那是两张同类型正面照互相抢主体;
    # 现在逐字点名分工,若再出融合,用「重绘备注」写一句即可压(见 user_hint)。
    #
    # 【本镜绑定裁剪】:分镜若**显式**声明了绑定(有 characters/props/scene 字段),
    # 就只带这一镜真正用到的资产 —— 特写镜声明了「只要产品」就不必再带人物
    # 立绘(那张图里有全身,模型容易照着画出人,靠文字守卫硬压不如直接不给)。
    # 没声明(老分镜/模型没给)→ 保持「三张全带」的既有行为,一个都不少。
    _anames_early = board_asset_names(drama_id, b)
    _has_binding = bool(b.get("characters") or b.get("props") or b.get("scene"))
    _want_person = True
    _want_product = True
    _want_scene = True
    if _has_binding:
        # 只要名字对得上已知资产才生效(对不上的名字是模型在编,忽略)
        _pn = _anames_early["characters"][0] if _anames_early["characters"] else ""
        _wn = (_clone_asset_row(drama_id, "presenter") or {}).get("name") or ""
        _want_person = bool(_pn and _pn == _wn)
        _pp = _anames_early["props"][0] if _anames_early["props"] else ""
        _wp = (_clone_asset_row(drama_id, "product") or {}).get("name") or ""
        _want_product = bool(_pp and _pp == _wp)
        _sc = _anames_early["scene"]
        _ws = (_clone_asset_row(drama_id, "scene") or {}).get("name") or ""
        _want_scene = bool(_sc and _sc == _ws)
        if not (_want_person or _want_product or _want_scene):
            # 绑定名**全部**对不上已知资产 → 是模型在编名字(实测 2026-10-27:
            # 新分镜绑定写「女生/窗边木桌前」,与资产名 出镜人物/主场景 对不上),
            # 按绑定裁剪会把三张锚全裁掉只剩主图 → 一致性全崩(窗外人脸、服装
            # 漂移都由此来)。此时无视绑定,回到**三张全带**(用户定版:
            # 「只要将三张图喂给模型,不就能保持一致性了」)。
            _want_person = _want_product = _want_scene = True
    _extras = ((scene_img, product_img) if main_kind == "presenter"
               else (scene_img, standing_img))
    for extra in _extras:
        if not extra or extra in refs:
            continue
        # 裁剪:额外图若对应的是本镜没绑的资产,就不带
        if extra is scene_img and not _want_scene:
            continue
        if extra is product_img and not _want_product:
            continue
        if extra is standing_img and not _want_person:
            continue
        refs.append(extra)
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
        # 单参考图时措辞只说「参考图」(说了"参考图2"模型会去找不存在的第 2 张);
        # **多锚时必须逐一点名**各图锁什么 —— 不点名,模型会把几张图平均融合。
        multi = len(refs) > 1
        if main_kind == "presenter" and has_presenter_ref:
            consist += (", 同一人物跨镜完全一致:五官、脸型、发型、肤色、"
                        "**服装款式与颜色**与"
                        + ("参考图1(人物设定图)" if multi else "参考图")
                        + "完全相同,是同一个人,不是长相相近的另一个人;服装不得逐镜变化")
            # 服装**文字锚**(2026-10-27 起恢复注入):只靠参考图,实测 agnes 会被
            # 提示词里的产品颜色带偏 —— 分镜文案「emerald-green jade bangle」×3,
            # 出图把翡翠绿染到了连衣裙上(用户实测「三视图服装跟首帧不同」)。
            # 旧决策「不锁服装」是原片人物当出镜照时代的产物(衣服跟原片走);
            # 用户换上自己的照片后,衣服就该跟新照走。取角色行妆造要点(≤80字)。
            # 注:这是**数据驱动**的机制(读各项目自己的妆造字段),不是写死的规则;
            # 「单人物/颜色隔离」这类通用规则已移入「通用重绘要求」默认值,用户可改。
            _person_style = ""
            _pa = clone.get("presenter_asset_id")
            if _pa:
                _prow = db.q1("SELECT styling FROM characters WHERE id=?", (_pa,))
                if _prow and (_prow["styling"] or "").strip():
                    _person_style = " ".join(_prow["styling"].split())[:80]
            if _person_style:
                consist += (f";人物服装文字锚:{_person_style}"
                            "(与参考图1里的人是同一套衣服)")
            if multi:
                consist += (";背景环境、陈设、窗景与光源方向严格参照"
                            "**参考图2(场景图)**,就是同一间房、同一时间")
            if product_img and product_img in refs:
                consist += (";产品外形 1:1 还原**参考图3(产品图)**的形状、颜色与材质,"
                            "全片是同一件产品,不凭空改变形状")
        elif main_kind == "product" and has_product_ref:
            consist += (", 产品外形 1:1 还原"
                        + ("参考图1(产品图)" if multi else "参考图")
                        + "的形状与轮廓,颜色、材质、光泽一致,"
                        "全片是同一件产品,不做成别的形状(既不变方也不变圆),"
                        "不改变大小比例,不凭空增加包装盒或外壳")
            if multi:
                consist += (";背景环境严格参照**参考图2(场景图)**,同一间房、同一时间")
            if standing_img and standing_img in refs:
                # 特写镜带立绘只为锚**手部肤质**,必须点名「只参照手,不画全身」,
                # 否则模型照着设定图把整个人画进腕部特写(实测 #03 的病灶)。
                # 图序号动态算:场景图缺失时立绘是参考图2,写死 3 会指错图。
                _sn = refs.index(standing_img) + 1
                consist += (f";出镜者的手部肤质与指甲参照**参考图{_sn}(人物设定图)**中"
                            "同一人的手,但本镜只拍手,严禁画出她的面部或身体")
    # ── 场景一致性:靠**空景图参考**(上面 refs 已注入)+ consist 里「参照
    # 参考图2」的点名。场景文字描写不再拼进提示词(用户要求:「环境描写也
    # 不要出现,用参考图就行」—— 文字里的陈设清单会跟空景图打架,画面冒出
    # 图片上没有的家具)。
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
        # 特写镜的文案写「女性手腕」,模型会把「坐着的完整女主」和「特写手腕」
        # 画进同一张 → 出现第二只伸进画面的手臂(用户实测截图)。文案改不了
        # (rewrite 产物),单肢硬规则拼在后面压。
        if _no_person:
            # 措辞必须是「本人的手,不许第二个人的手」,而不是「只允许一只手」
            # —— 分镜里大量正常动作是**双手**调整/佩戴(实测镜04/05),限一只
            # 会把正常画面改坏;真正的缺陷是**别人的手**伸进画面(用户实测截图)
            core += ("。画面中只允许出现出镜者本人的手与手腕(按本镜动作,一手或"
                     "双手皆可),不得出现第二个人的手或手臂,没有旁人的手臂从画外"
                     "伸入,不出现完整人物面部或身体")
    elif _no_person:
        core = (f"{b.get('shot','特写')},{action_txt},"
                f"画面只有产品与手部特写,{product_desc}:{b.get('product_use','')}")
    else:
        core = (f"{b.get('shot','中景')},{presenter_desc},{action_txt},"
                f"画面突出{product_desc}:{b.get('product_use','')}")
    # 场景环境靠**空景图参考**(参考图2)+ consist 点名,不拼场景文字描写
    # (用户要求:环境描写不要出现,用参考图就行 —— 文字陈设清单会跟空景图打架)
    tail = consist + ", 运镜与光线参考带货实拍视频, 清晰锐利, 电影质感"
    # 重绘要求注入,两层(修图能力留在软件里,用户自己可修,不用改代码):
    # · 全局(设置表 yihao.clone_redraw_hint):跨项目生效,所有镜重绘都带 ——
    #   「只允许一只手」这类规则往往整条片都要,不该逐镜重抄;
    # · 单镜(分镜条目 user_hint):只针对这一镜的问题。
    global_hint = str(db.get_setting("yihao.clone_redraw_hint") or "").strip()
    # 单人守卫(2026-10-27 实测:特写镜三参考融合出第二个人,用户反馈
    # 「复刻要只有一个人才行」)。分镜文案没写多人词就默认「一镜一人」;
    # 对戒/情侣款这类**合法双人**项目在分镜文案里写「两人/情侣/对戒」
    # 即自动豁免,不必改代码(比旧 DEFAULT_CLONE_RULES 的写死禁令更稳)。
    # 全局重绘要求里已写过同类约束时不重复注入。
    if (not any(w in _shot_text for w in
                ("两人", "两个人", "双人", "情侣", "对戒", "闺蜜", "多人"))
            and "一个人" not in global_hint):
        tail += ("。画面中只有出镜人物一个人,严禁出现第二个或多个人物、背景路人;"
                 "窗户外、玻璃、镜面、屏幕上不得出现任何人影或倒影,"
                 "墙面不得出现带人脸的照片或海报")
    if global_hint:
        tail += f"。{global_hint}"
    user_hint = str(b.get("user_hint") or "").strip()
    if user_hint:
        tail += f"。{user_hint}"
    # 预算只约束**本镜的内容部分**(风格前缀 + 参考项目尾套合计 ~590 字符,
    # 它们是平台级固定文案,砍它等于换风格/丢掉一致性约束)。
    # 之前把全长一起塞进 200 字上限,算下来留给内容的额度是 **负 410** ——
    # 于是每镜内容都被砍到 40 字符,只剩 "A young woman with long dark hair wearin"…
    # 模型看不到「白色纸盒」「口红」,于是 6 镜全画成同一张「沙发上女性」插画
    # (实测:提示词两两差异很大,出的图却几乎一样)。这就是根因。
    if len(core) > SHOT_PROMPT_MAX_CHARS:
        print(f"[clone] 分镜#{board_number} 内容超 {SHOT_PROMPT_MAX_CHARS} 字,已截断", flush=True)
        core = core[:SHOT_PROMPT_MAX_CHARS]
    # ── 参考图分工 + 身份锁定块(移植短剧首帧 shot_tools.generate_first_frame
    # 的做法 —— 用户实测短剧分镜没有发型/服装/陈设漂移,让复刻照抄):在提示词
    # **开头**逐张点名「参考图 N = 什么、锁什么」。克隆此前的一致性约束堆在
    # 提示词末尾(tail),没有「图 N = 谁」的绑定关系,模型会把几张图平均融合。
    def _role_of(p: str) -> str:
        if standing_img and p == standing_img:
            return "person"
        if product_img and p == product_img:
            return "product"
        if scene_img and p == scene_img:
            return "scene"
        return "other"
    identity = ""
    if refs:
        # 逐张绑定 + **逐属性枚举** —— 照抄短剧首帧的原文样式(用户实测短剧
        # 「人物服装脸对不上变化」零漂移,复刻要的就是这个力度):每条绑定都
        # 点名五官/发型/体型/年龄/服装/配饰并禁止自由改动,而不是只给角色标签。
        # 名字从资产行现读(按 **id** 查,不再按名字查 —— 改名后按名字查会
        # 全部落空,用户改个名整条复刻链就断了;详见 _clone_asset_row 注释)。
        _person_name = (_clone_asset_row(drama_id, "presenter") or {}).get("name") or CLONE_PRESENTER_NAME
        _product_name = (_clone_asset_row(drama_id, "product") or {}).get("name") or CLONE_PRODUCT_NAME
        _scene_name = (_clone_asset_row(drama_id, "scene") or {}).get("name") or CLONE_SCENE_NAME
        # 注意行是动态的:复刻的主图随景别变(特写=产品),人物不一定是图1,
        # 必须算出人物是第几张图再指认 —— 短剧侧人物恒为图1,写死没错,这里不行。
        lines = []
        person_no = 0
        for i, p in enumerate(refs, start=1):
            role = _role_of(p)
            if role == "person":
                person_no = i
                lines.append(f"- 参考图{i}(人物设定图)= 角色「{_person_name}」本人:"
                             f"严格按图{i}的五官、发型、体型、年龄、服装、配饰 —— "
                             "禁止模型自由改动。")
            elif role == "product":
                lines.append(f"- 参考图{i}(产品图)= 产品「{_product_name}」:"
                             f"外形、颜色、材质、光泽严格按图{i} —— 禁止改动形状。")
            elif role == "scene":
                lines.append(f"- 参考图{i}(场景图)= 场景「{_scene_name}」:"
                             f"陈设、窗景、光源方向严格按图{i},就是同一间房。")
            else:
                lines.append(f"- 参考图{i} = 参考图。")
        note = (f"(注意:参考图{person_no}是角色「{_person_name}」的人物参考,"
                "头发/服装/体型以它为准;分镜文案里若提到其他发型或服装,"
                "一律以人物设定图为准。)"
                if person_no else "")
        identity = ("【人物身份锁定 / 严格按参考图外貌生成】\n"
                    + "\n".join(lines)
                    + (("\n" + note) if note else "")
                    + "\n")
    # ── 画幅指令 + size(同样移植自短剧首帧):克隆此前从不传 size,首帧全是
    # provider 默认 16:9(2624x1472);项目画幅写进提示词让模型先想清楚构图,
    # size 参数让接口按画幅出图。
    _arow = db.q1("SELECT aspect_ratio FROM dramas WHERE id=?", (drama_id,))
    aspect = ((_arow or {}).get("aspect_ratio") if _arow else None) or "16:9"
    from .shot_tools import _aspect_to_size
    size = _aspect_to_size(aspect)
    if aspect in ("9:16", "3:4"):
        layout_hint = f"【画幅】竖屏构图({aspect}),主体人物居中或略偏下,上下留更多空间,不要横构图。"
    elif aspect in ("16:9", "4:3", "21:9"):
        layout_hint = f"【画幅】横屏构图({aspect}),主体居中或略偏左,左右留更多空间。"
    else:
        layout_hint = f"【画幅】{aspect} 构图。"
    # ── 「出场人物 / 场景 / 道具」头行(@名字)──
    #
    # 与短剧分镜的 video_prompt 写法对齐:短剧侧第一行就是
    #   出场人物:@陈默 @张雯 @赵刚  场景:@云脉科技大厦会议室
    # 模型据此把画面里的对象对上参考图。复刻此前只有英文 prompt、没有任何
    # 名字可指,于是「这一镜该锁谁」无处表达 —— 三个资产只能每镜无差别全带。
    # 现在把本镜的资产名字显式点名,并让**参考图集合由绑定决定**(见下方
    # _extras 的按需裁剪),头行与图一一对应。
    _anames = board_asset_names(drama_id, b)
    _ref_header = asset_ref_header(_anames)
    prompt = f"{identity}{layout_hint}\n{_ref_header}\n{style}, {span}{core}{tail}" if _ref_header \
        else f"{identity}{layout_hint}\n{style}, {span}{core}{tail}"
    out = None
    # reference_lock=False:复刻的提示词里已有**逐张点名**的精确身份块
    # (参考图1=人物/2=场景/3=产品);image_client 的通用锁「参考图N=人物N」
    # 会把场景图、产品图也当成要画的人 —— 实测诱导出第二个人、窗外人脸。
    # 网络抖动重试(与场景锚同款;2026-10-27 实测 agnes 连接超时,一批 6 镜挂 3 镜)
    for attempt in (1, 2):
        try:
            out, _ = image_client.generate_image(
                prompt, out_name=f"clone_s{board_number}_{uuid.uuid4().hex[:6]}.png",
                config_id=config_id, reference_images=refs,
                people=1, size=size, reference_lock=False)
            break
        except Exception as exc:
            if attempt == 2:
                raise
            import time as _t
            print(f"[clone] 分镜#{board_number} 生图第{attempt}次失败"
                  f"({str(exc)[:120]}),3 秒后重试", flush=True)
            _t.sleep(3)
    # 记录首帧
    for x in boards:
        if int(x.get("number", 0)) == int(board_number):
            x["first_frame"] = str(out)
    # 场景锚不再在这里固化:旧实现拿首镜生成图当 scene_image(图里带人,当参考
    # 会抄出第二人)、scene_prompt 硬编码一句与原片无关的描述。现在锚在**分析
    # 阶段**就从原视频提取(见 extract_scene_anchor),首镜同样享受场景参考。
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
    # 三要素喂视频模型(用户定版「每镜都要以三视图/场景图/商品为要素喂给视频
    # 生成的模型」,且**每一镜都带齐**,含特写):首帧之外再注入 人物立绘/
    # 场景空景/产品图,视频动起来的过程中人/景/物才有图可锚,而不是只在
    # 第一帧对、后面漂。特写镜靠提示词守卫压「照设定图画出全身」。
    # agnes 走多模态参考注入;不支持的 provider 忽略(video_client 文档)。
    clone = _meta(drama_id).get("clone", {})
    _standing = standing_ref_of(clone.get("turnaround_image"))
    _scene = _resolve_local(clone.get("scene_image"))
    _product = _resolve_local(clone.get("product"))
    video_refs = [str(p) for p in (_standing, _scene, _product) if p]
    _shot_kind_v = str(b.get("shot") or "")
    if any(w in _shot_kind_v for w in ("特写", "微距")):
        # 特写守卫与首帧同口径:只许本人的手,不许第二个人的手/全身入画
        video_prompt += ("。画面中只出现出镜者本人的手与手腕(一手或双手皆可),"
                         "不得出现第二个人的手或手臂,不得出现完整人物面部或身体")
    path, _ = video_client.generate_video(
        video_prompt, resolution=resolution,
        duration=dur, first_frame=first, config_id=config_id,
        reference_images=video_refs)
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
    """第 4 步:按原片节奏拼接成片 —— **固定走短剧的统一参数拼接路径**。

    用户实测复刻合并后「声音很卡,基本听不清」:旧实现走 auto_merge(concat
    demuxer 无损拼接),要求所有镜头音轨参数完全一致 —— 复刻镜头各自独立
    生成,音轨有/无、采样率不一,拼出来声音就卡。短剧分镜合并
    (merge.py:_merge_filtered)对每镜做音频归一(aformat 48k 立体声 + apad,
    无音轨的补 anullsrc 静音)再重编码,音频稳;片头(标题卡前置/文字叠加)
    也由同一条滤镜路径处理。所以这里**无条件**走 _merge_filtered,与短剧
    merge_episode 的重编码分支同一份代码。

    片头:复刻页「标题」开关开启时(clone.intro_enabled),读 dramas 片头
    字段(标题/方式/字体/字号/位置/时长 —— IntroEditorDialog 写入),
    字号时长按多数派真实画幅计算(与 merge_episode 同口径)。
    """
    from . import merge as merge_mod
    from . import intro as _intro
    shots = [Path(p) for p in clone_done_videos(drama_id) if Path(p).exists()]
    if len(shots) < 2:
        raise RuntimeError("至少完成 2 个镜头视频才能拼接")
    out = out or (config.STATIC_DIR / "merged" / f"clone_{drama_id}_{uuid.uuid4().hex[:8]}.mp4")
    # 片头:开关在 clone.intro_enabled,配置在 dramas 片头字段;
    # 字号/时长按多数派真实分辨率算(与 merge_episode 同口径)
    meta = _meta(drama_id)
    intro = None
    if (meta.get("clone") or {}).get("intro_enabled"):
        try:
            ref_w, ref_h = merge_mod._majority_size(shots)
            intro = _intro.build_intro_spec(drama_id, ref_w=ref_w, ref_h=ref_h)
        except Exception as exc:  # noqa: BLE001
            print(f"[clone] 片头配置异常({exc}),本次合并不带片头", flush=True)
            intro = None
    # **无条件走统一参数拼接**:音频归一 + 可选片头(标题卡前置/文字叠加)
    path = merge_mod._merge_filtered(shots, [], Path(out), intro, progress)
    # ── 合并历史(用户要求「最多生成 8 个合并视频」,新的顶掉最旧的)──
    # 成片要在红框区可见可播;反复合并不能无限堆文件。海报帧顺手抽出
    # (黑底标题卡的成片开头是纯黑,poster 自带黑帧探测),供列表缩略使用。
    from . import video_poster
    poster = video_poster.extract_video_poster(Path(path))
    meta = _meta(drama_id)
    clone = meta.get("clone") or {}
    merges = [m for m in (clone.get("merges") or []) if m.get("path") != str(path)]
    merges.insert(0, {"path": str(path), "poster": str(poster) if poster else "",
                      "at": db.now()})
    # 超出 8 个的旧成片:**文件与海报一并删除**(用户要求「旧的要删掉」)——
    # 只从列表移除会留下孤儿大文件,磁盘悄悄被吃满
    import os as _os
    for dropped in merges[8:]:
        for key in ("path", "poster"):
            f = _resolve_local(dropped.get(key))
            if f and f.exists():
                try:
                    f.unlink()
                except OSError as exc:
                    print(f"[clone] 旧成片删除失败({exc}): {f}", flush=True)
    clone["merges"] = merges[:8]
    meta["clone"] = clone
    _save_meta(drama_id, meta)
    return path


def clone_merges(drama_id: int) -> list[dict]:
    """合并成片历史(新在前,最多 8 条)。"""
    return _meta(drama_id).get("clone", {}).get("merges") or []


def delete_clone_merge(drama_id: int, path: str) -> int:
    """删除一条合并成片:从历史移除,文件与海报一并删除。返回剩余条数。"""
    import os
    meta = _meta(drama_id)
    clone = meta.get("clone") or {}
    kept = [m for m in (clone.get("merges") or []) if m.get("path") != str(path)]
    old = next((m for m in (clone.get("merges") or []) if m.get("path") == str(path)), None)
    if old:
        for key in ("path", "poster"):
            f = _resolve_local(old.get(key))
            if f and f.exists():
                try:
                    f.unlink()
                except OSError as exc:
                    print(f"[clone] 成片文件删除失败({exc}): {f}", flush=True)
    clone["merges"] = kept
    meta["clone"] = clone
    _save_meta(drama_id, meta)
    return len(kept)


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
2b. 资产绑定字段(与短剧分镜同构):characters(本镜出镜人物名数组)、props(本镜出现的道具名数组)、
scene(本镜场景名) —— 决定本镜把哪些参考图喂给模型,没出现就写空数组/空串。
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
    # 克隆项目注入「已知资产」段,绑定名才不会自创(与 analyze_reference 同理)
    clone = (_meta(ep["drama_id"]).get("clone") or {}) if ep else {}
    if clone:
        prompt = (UNDERSTAND_PROMPT + "\n\n" + _asset_names_block(clone)
                  + "\n\n参考视频(base64 内联,直接读取):")
    else:
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
