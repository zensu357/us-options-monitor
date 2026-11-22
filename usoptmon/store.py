"""极简 CSV 存储:每张表一个文件,按 date 键 upsert。无 pandas 依赖。"""

import csv
import os

from . import config


def _path(name):
    config.DATA.mkdir(parents=True, exist_ok=True)
    return config.DATA / f"{name}.csv"


def read(name):
    """读取整表为 list[dict];不存在返回空列表。"""
    p = _path(name)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(name, rows, fieldnames=None):
    if not rows:
        return
    if fieldnames is None:
        seen = []
        for r in rows:
            for k in r:
                if k not in seen:
                    seen.append(k)
        fieldnames = seen
    with open(_path(name), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def upsert(name, rows, key="date"):
    """按 key(单列或列元组)合并(新值覆盖旧值),排序后整表重写。"""
    if not rows:
        return
    if isinstance(key, str):
        keycols = (key,)
        key_of = lambda r: r[key]  # noqa: E731
    else:
        keycols = tuple(key)
        key_of = lambda r: tuple(r[c] for c in keycols)  # noqa: E731
    existing = {key_of(r): r for r in read(name)}
    for r in rows:
        existing[key_of(r)] = r
    merged = sorted(existing.values(), key=key_of)
    write(name, merged)
    return len(merged)


def prune_raw(keep_days=10):
    """删除 raw/ 下超过 keep_days 的日期目录,控制磁盘占用。"""
    import datetime
    import shutil

    if not config.RAW.exists():
        return
    cutoff = datetime.date.today() - datetime.timedelta(days=keep_days)
    for d in config.RAW.iterdir():
        if d.is_dir():
            try:
                if datetime.date.fromisoformat(d.name) < cutoff:
                    shutil.rmtree(d)
            except ValueError:
                pass
