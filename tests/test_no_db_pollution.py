# -*- coding: utf-8 -*-
"""测试**不许往用户真实库里写数据**,也不许留下垃圾行。

实测踩过两次:
1. `test_video_clone.py::test_chapter_count_not_overwritten_by_generated_count` 用
   `os.environ["YIHAO_DATA_DIR"]` 试图隔离,但 `config` 早在导入时就把
   DATA_DIR 算成 DB_PATH 了,之后改环境变量**完全无效** —— 每跑一次测试
   就往 data/yihao.sqlite3 塞一条名为「T」的 novel 项目(id 落在 88 万~97 万),
   用户删掉还会再出现。
   正确写法是 `monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "x.sqlite3")`。
2. `test_split_models.py` 里两处清理写在 **断言之后**,断言一失败就永远漏,
   同样会留下测试项目。

本文件做两件事:
- 锁住「隔离必须走 DB_PATH」这条写法
- 提供 autouse fixture,万一还有别的测试漏了,也至少能**事后发现**而不是静默污染
"""
from __future__ import annotations

import inspect

import pytest

from app.core import db
from tests import test_video_clone as tvc


def test_isolation_must_patch_config_db_path_not_env(tmp_path, monkeypatch):
    """隔离测试库的正确姿势是改 config.DB_PATH,不是设环境变量。

    环境变量在 config 导入后就失效了 —— 这正是「删掉的项目又出现」的根因。
    """
    src = inspect.getsource(tvc.test_chapter_count_not_overwritten_by_generated_count)
    # 只看代码行,不看注释 —— 注释里要说明这个坑,提到这个变量名是合理的
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.strip().startswith("#"))
    assert 'setattr(_db.config, "DB_PATH"' in code, \
        "该测试没用 config.DB_PATH 隔离,会写进用户真实库"
    assert 'environ["YIHAO_DATA_DIR"]' not in code and \
           "environ['YIHAO_DATA_DIR']" not in code, \
        "设 YIHAO_DATA_DIR 对已导入的 config 无效,不要再用它做隔离"


def test_cleanup_is_in_finally_not_after_assert():
    """清理语句必须在 finally 里,断言失败也要清。"""
    import re
    from tests import test_split_models as tsm
    src = inspect.getsource(tsm)
    # 每个 INSERT INTO dramas 都应处在一个含 finally 的 try 里
    inserts = len(re.findall(r"INSERT INTO dramas", src))
    deletes = len(re.findall(r"DELETE FROM dramas WHERE id=\?", src))
    finallys = len(re.findall(r"\bfinally:", src))
    assert inserts == 0 or (deletes >= 1 and finallys >= 1), \
        "测试建了 dramas 却把清理放在断言之后(断言一失败就漏)"


@pytest.fixture(autouse=True)
def _no_leftover_rows_in_real_db():
    """跑测试时若出现新的垃圾行,结束时报出来。

    只**检测**不删除 —— 真库是用户数据,测试无权替用户做删除决定。
    判据:标题为 'T' / 含「测试」且 id 落在测试自建区间(>=880000)。
    """
    before = {r["id"] for r in db.q(
        "SELECT id FROM dramas WHERE id>=880000 AND (title='T' OR title LIKE '%测试%')")}

    yield

    after = {r["id"] for r in db.q(
        "SELECT id FROM dramas WHERE id>=880000 AND (title='T' OR title LIKE '%测试%')")}
    leaked = after - before
    assert not leaked, (
        f"这些测试项目被留在了用户真实库里:{sorted(leaked)}。"
        f"隔离必须用 monkeypatch.setattr(db.config, 'DB_PATH', tmp_path/...);"
        f"清理语句必须放 finally 里。")
