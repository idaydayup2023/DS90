#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台账一页纸共用库（站长 11-07 18:20 裁定⑤，仓级规矩）。

禁「纯 append 当唯一真值」。两条合法姿势，本库各给一个原语：

A. 快照台账（低频、量小）：tmp + os.replace 全量重写 —— atomic_write_json()
B. 流水台账（高频逐条）：append 带键 + 消费者按键重算 done 集 ——
   append_record() 写入（必带键），recompute_done() 读侧按键取**最后一条**
   定性，可后置 status="undone" 撤单。绝不允许 set(所有行) 当 done。

高危名单（11-07 点名的存量件，新改一律迁本库）：
  acgs_s05 两支 journal、gap_scan 五支 STATE、newseed AUDIT/POOL。

fsync 姿势：数据落盘才 rename，断电不留半截 JSON；append 行尾 flush。
"""
import json
import os
import tempfile

DEFAULT_KEY = "k"
DONE_STATUS = "done"
UNDONE_STATUS = "undone"


# ---------------------------------------------------------------- A 快照


def atomic_write(path, text):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_", suffix=".swap")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def atomic_write_json(path, obj):
    atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- B 流水


def append_record(path, rec, key=DEFAULT_KEY):
    """rec 必须含键字段；落盘 flush，行即事实、真值在读侧重算。"""
    if key not in rec:
        raise ValueError("流水台账必须带键 %r" % key)
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def iter_records(path, key=DEFAULT_KEY, on_bad=None):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                if on_bad:
                    on_bad(ln, line)
                continue
            if isinstance(o, dict) and key in o:
                yield o
            elif on_bad:
                on_bad(ln, line)          # 无 i/无键的批级记录不算条目


def recompute_done(path, key=DEFAULT_KEY, status_field="status",
                   done_values=(DONE_STATUS,), key_field=None):
    """消费者按键重算：同键后写覆盖先写；undone 撤单。返回 {键: 记录}。

    key_field：done 集取记录里哪个字段当键（默认同 key）；
    done_values：哪些 status 值算在场（默认 done；corrected 等可自加）。
    """
    kf = key_field or key
    latest = {}
    for o in iter_records(path, key):
        k = o.get(kf)
        if k is None:
            continue
        latest[k] = o
    return {k: o for k, o in latest.items()
            if o.get(status_field, DONE_STATUS) in tuple(done_values)}


def done_keys(path, **kw):
    return set(recompute_done(path, **kw))


def selftest():
    import shutil
    d = tempfile.mkdtemp(prefix="ledger_selftest_")
    fails = []
    try:
        # A 快照：全量重写不留 tmp、内容即终值
        p = os.path.join(d, "rounds.json")
        atomic_write_json(p, {"rounds": [1, 2]})
        atomic_write_json(p, {"rounds": [1, 2, 3]})
        if json.load(open(p, encoding="utf-8"))["rounds"] != [1, 2, 3]:
            fails.append("atomic_write_json 终值不对")
        if [f for f in os.listdir(d) if f.startswith(".tmp_")]:
            fails.append("atomic 留了 tmp 残留")
        # B 流水①：无键记录必须拒写
        j = os.path.join(d, "journal.jsonl")
        try:
            append_record(j, {"status": "done"})
            fails.append("无键记录未被拒")
        except ValueError:
            pass
        # B 流水②：同键后写覆盖先写；undone 撤单；无键行跳过
        append_record(j, {"k": 1, "status": "done"})
        append_record(j, {"k": 2, "status": "done"})
        with open(j, "a", encoding="utf-8") as f:
            f.write('{"status": "done"}\n')          # 无 i 批级记录
            f.write('not json\n')                    # 坏行
        append_record(j, {"k": 1, "status": "undone"})
        got = done_keys(j)
        if got != {2}:
            fails.append("recompute_done=%r 应为 {2}（后写覆盖+undone 撤单）" % sorted(got))
        bad = []
        list(iter_records(j, on_bad=lambda ln, s: bad.append(ln)))
        if sorted(bad) != [3, 4]:
            fails.append("on_bad 未捕获无键/坏行: %r" % bad)
        # B 流水③：done_values 可扩（corrected 也算在场）
        c = os.path.join(d, "c.jsonl")
        append_record(c, {"k": 5, "status": "corrected"})
        if done_keys(c, done_values=("done", "corrected")) != {5}:
            fails.append("done_values 扩展失效")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if fails:
        print("LEDGER SELFTEST FAIL %d 项" % len(fails))
        for f in fails:
            print("  " + f)
        return 1
    print("LEDGER SELFTEST PASS 全部用例通过（快照全量重写/带键流水+按键重算+撤单）")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
