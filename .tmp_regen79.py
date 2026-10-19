import sys, time
sys.path.insert(0, ".")
from app.pipeline import comic_pipeline
from app.pipeline import stitch as stitch_mod
from app.core import config, db

t0 = time.time()
r = comic_pipeline.generate_full_comic(79)
print(f"重出结果: 共 {r.get('panels')} 格, 出 {r.get('generated')} / 跳过 {r.get('skipped')} / 失败 {r.get('failed')}, 耗时 {time.time()-t0:.0f}s", flush=True)
out = stitch_mod.stitch_panels(79)
row = db.q1("SELECT id FROM video_merges WHERE episode_id=79 AND model='comic_stitch'")
if row:
    db.ex("UPDATE video_merges SET merged_url=?, updated_at=? WHERE id=?",
          (config.path_to_media_url(out), db.now(), row["id"]))
else:
    db.ex("""INSERT INTO video_merges(episode_id,provider,model,status,merged_url,created_at,updated_at)
             VALUES(79,'pillow','comic_stitch','completed',?,?,?)""",
          (config.path_to_media_url(out), db.now(), db.now()))
print("长条图:", out, flush=True)
