"""一次性:给陈默(char 25)重新生成 3D image_url,覆盖之前的漫画图。

跑法:PYTHONPATH=. python scripts/regen_char25.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from app.core import db
from app.pipeline import prompts_gen
from app.ai import image_client
from app.core import config

db.init_db()

CHAR_ID = 25
print(f"=== 重画 char {CHAR_ID} ===")

# 1. 重新起草 final_prompt(走新代码 → 3D 前缀)
print("Step 1: 重新起草 final_prompt...")
new_fp = prompts_gen.character_prompt(CHAR_ID)
ok = ("3D" in new_fp) or ("CG" in new_fp)
print(f"  前缀: {new_fp[:60]}...")
print(f"  是 3D 前缀: {ok}")

# 2. 调用 image_client 重新生成
print("Step 2: 调用 image_client.generate_image (config_id=9=qwen)...")
prev = dict(db.q1("SELECT image_url FROM characters WHERE id=?", (CHAR_ID,)))
print(f"  旧 image_url: {prev.get('image_url')}")

try:
    out, provider = image_client.generate_image(
        new_fp,
        out_name=f"char_{CHAR_ID}_3d.png",
        config_id=9,           # 9=qwen-image
        size="1024x1024",     # 角色三视图用 1024
        people=1,
    )
    url = config.path_to_media_url(out)
    db.ex("UPDATE characters SET image_url=?, updated_at=? WHERE id=?",
          (url, db.now(), CHAR_ID))
    print(f"  OK: provider={provider}")
    print(f"  新 URL: {url}")
    print("Done.")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"  FAIL: {e}")
