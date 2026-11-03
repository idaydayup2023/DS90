#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ds_stage_preset.py — transmission 暂存区预置件（案2固化，2026-11-02 zhero 案B 破案）。

破案出处：logs/zhero_planB_report_2026-11-02.md
  铁律：**暂存目录 = /volume1/@download/<裸任务号>/（无 dbid_ 前缀）**。
  18232 实证：`18232/` 里有 .part+.torrent+.filelist+.resume；
  18240 把 .part 塞进 `dbid_18240/` = 塞进 DS 根本不读的目录（CHECK_RESUME_LOW 真根因，
  并非时序问题）。
  配套规矩：
  · 预置前先 cp 保真副本（独立副本、sha256 回读记台账），防续写污染；
  · 预置件属主 chown DownloadStation:DownloadStation、权限 666；
  · 落位后 **sha256 回读全等** 才算预置成功；
  · 预置 → v2 resume → **≥阈值闸**（时间窗轮询 size_downloaded，达标 PASS，
    不达标 CHECK_RESUME_LOW 停手候裁，不反复重试）。
  已知坑（18245）：出生 1 秒即 pause 的单可能从未被引擎装载（BT File 1913 壳态），
  resume 回 True 但恒 waiting——此时别硬刷，报站长选裁（Web UI 手工建单 / 出生不抢
  pause 同卷 CoW 抢先落位）。

用法：
  实弹: python3 ds_stage_preset.py --task dbid_18245 --src /volume1/Downloads/_dl_stage/hold/x.mp4.part \
            --part-name "X 2021 1080p ....mp4.part" --resume --floor 390000000 [--window 600]
  预演: 加 --dry-run（只读 ls/du 现状 + 打印将执行动作，不落任何写）
  第三姿势: 加 --adopt-race（出生不抢 pause + CoW 抢先落位、不 resume；18246 实测
            可装载、未采纳，仅用于验证装载态——默认关闭，须显式开）
  自测: python3 ds_stage_preset.py --selftest （零网络零 SSH，路径/闸逻辑断言）
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ds_common import bare_id, login, logout, resume_v2, ssh, task_list

STAGE_ROOT = "/volume1/@download"


def stage_dir(task_id):
    return "%s/%s" % (STAGE_ROOT, bare_id(task_id))  # 案2铁律：裸任务号


def stage_snapshot(task_id):
    return ssh("ls -la %s 2>/dev/null || echo NOTEXIST" % stage_dir(task_id))


def size_downloaded(sid, task_id):
    for t in task_list(sid, additional="transfer", limit=500):
        if t.get("id") == task_id or bare_id(t.get("id")) == bare_id(task_id):
            ad = t.get("additional") or {}
            return int((ad.get("transfer") or {}).get("size_downloaded")
                       or t.get("size_downloaded") or 0), t.get("status")
    return None, None


def posture(adopt_race, do_resume):
    """姿势唯一裁决（主流程与自测共用，防 dry-run 展示与实际执行漂移）。

    steady（默认，站长稳态）：cp -f 落位 + v2 resume + 阈值闸。
    adopt-race（第三姿势，--adopt-race 显式开）：同卷 CoW 抢先落位（--reflink=auto）
      且**不动 resume**，只观察装载。18246 实测：可装载（7 秒出 .torrent/.filelist）、
      预置 421M 未被采纳、计数从 0 起 —— 半成品姿势，用于验证装载态，勿当稳态用。
    """
    return {"name": "adopt-race(第三姿势)" if adopt_race else "steady(站长稳态)",
            "cp": "cp -f --reflink=auto" if adopt_race else "cp -f",
            "resume": bool(do_resume) and not adopt_race}


def preset(sid, task_id, src, part_name, do_resume, floor, window, dry, adopt_race=False):
    pos = posture(adopt_race, do_resume)
    ev = {"task": task_id, "stage": stage_dir(task_id), "src": src, "part": part_name,
          "dry_run": dry, "posture": pos["name"]}
    print("[1] 预置前暂存现场:", stage_snapshot(task_id).replace("\n", " | ")[:300])
    ev["stage_before"] = stage_snapshot(task_id)
    cp = pos["cp"]
    if dry:
        print("[DRY-RUN] 将执行：")
        print("   mkdir -p %s" % stage_dir(task_id))
        print("   %s '%s' '%s/%s'" % (cp, src, stage_dir(task_id), part_name))
        print("   chown DownloadStation:DownloadStation + chmod 666")
        print("   sha256sum 回读全等校验 → %s" % ("v2 resume" if pos["resume"] else
              ("不动 resume（adopt-race 观察装载）" if adopt_race else "（不 resume）")))
        if floor and pos["resume"]:
            print("   ≥%d 闸，窗口 %ds" % (floor, window))
        print("[DRY-RUN] 未落任何写操作。")
        return ev

    # 1) 保真：源件可读且报 sha（源本身即 hold 副本时不重复 cp）
    src_stat = ssh("stat -c '%%s' '%s' 2>/dev/null || echo MISSING" % src)
    if src_stat == "MISSING":
        raise SystemExit("ABORT 源件不存在: %s" % src)
    print("[2] 源件 %s B" % src_stat)

    # 2) 落位（裸任务号目录；adopt-race 用 CoW reflink 抢先落位）
    dst = "%s/%s" % (stage_dir(task_id), part_name)
    ssh("mkdir -p %s && %s '%s' '%s' && chown DownloadStation:DownloadStation '%s' && chmod 666 '%s'"
        % (stage_dir(task_id), cp, src, dst, dst, dst))
    ev["stage_after"] = stage_snapshot(task_id)

    # 3) sha 回读全等
    s_src = ssh("sha256sum '%s' | cut -d' ' -f1" % src)
    s_dst = ssh("sha256sum '%s' | cut -d' ' -f1" % dst)
    ev["sha_src"], ev["sha_dst"] = s_src, s_dst
    if s_src != s_dst:
        raise SystemExit("ABORT 预置件 sha 回读不一致 src=%s dst=%s（暂存件已留场候裁，勿删）" % (s_src[:12], s_dst[:12]))
    print("[3] sha 回读全等:", s_dst[:12])

    # 4) resume + 阈值闸（adopt-race 不动 resume，只候装载观察窗）
    if pos["resume"]:
        rr = resume_v2(sid, task_id)
        print("[4] v2 resume:", json.dumps(rr))
        t0 = time.time()
        last = None
        while time.time() - t0 < window:
            dl, st = size_downloaded(sid, task_id)
            last = (dl, st)
            if dl is not None and dl >= floor:
                print("[5] 闸 PASS: dl=%d ≥ %d (status=%s) @+%.0fs" % (dl, floor, st, time.time() - t0))
                ev["gate"] = {"verdict": "PASS", "dl": dl, "status": st}
                return ev
            time.sleep(15)
        ev["gate"] = {"verdict": "CHECK_RESUME_LOW", "last": last, "window_s": window}
        print("[5] 闸未过:", json.dumps(ev["gate"]), "→ 停手候裁（18245 教训：恒 waiting 勿硬刷）")
    return ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", help="任务 id（dbid_18245 或 18245 均可，内部按裸号解析）")
    ap.add_argument("--src", help="NAS 上保真副本绝对路径")
    ap.add_argument("--part-name", help="落位件名（须与 torrent 内文件同名的 .part）")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--floor", type=int, default=0, help="阈值闸字节数")
    ap.add_argument("--window", type=int, default=600)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--adopt-race", action="store_true",
                    help="显式开第三姿势：出生不抢 pause + 同卷 CoW（--reflink=auto）抢先落位、"
                         "不动 resume 只观察装载。18246 实测：可装载、未采纳，用于验证装载态，"
                         "非稳态姿势（默认走站长稳态：cp -f + v2 resume + 阈值闸）")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    for k in ("task", "src", "part_name"):
        if not getattr(a, k):
            raise SystemExit("需要 --%s（或 --selftest）" % k.replace("_", "-"))
    sid = login()
    try:
        ev = preset(sid, a.task, a.src, a.part_name, a.resume, a.floor, a.window, a.dry_run,
                    adopt_race=a.adopt_race)
        ev["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs("logs", exist_ok=True)
        p = "logs/stage_preset_%s_%s.json" % (bare_id(a.task), time.strftime("%H%M%S"))
        json.dump(ev, open(p, "w"), ensure_ascii=False, indent=1)
        print("-> 台账", p)
        return 0 if ev.get("gate", {}).get("verdict", "PASS") == "PASS" else 2
    finally:
        logout(sid)


def selftest():
    """零联网零 SSH：路径解析与闸逻辑回归（含 18240 反例）。"""
    # 案2核心：dbid_ 前缀绝不进暂存路径
    assert stage_dir("dbid_18240") == "/volume1/@download/18240"
    assert stage_dir(18232) == "/volume1/@download/18232"
    assert "dbid_" not in stage_dir("dbid_18240")  # 18240 反例：dbid_ 目录 DS 不读
    print("selftest[裸任务号路径] OK（含 dbid_ 剥离）")
    # 闸逻辑（不 import preset，纯函数复刻同判据）：dl≥floor PASS；窗口尽不达标 CHECK_RESUME_LOW
    import types
    fake = types.SimpleNamespace()
    def fake_dl():
        return fake.dl, fake.st

    def gate(floor, window):
        t0 = time.time()
        while time.time() - t0 < window:
            dl, st = fake_dl()
            if dl is not None and dl >= floor:
                return "PASS"
            time.sleep(0.2)
        return "CHECK_RESUME_LOW"

    fake.dl, fake.st = 400_000_000, "downloading"
    assert gate(390_000_000, 2) == "PASS"
    fake.dl, fake.st = 65536, "waiting"
    assert gate(390_000_000, 1) == "CHECK_RESUME_LOW"  # 18245 形态：恒 waiting dl 小 → 候裁不硬刷
    print("selftest[阈值闸] OK（PASS/CHECK_RESUME_LOW 双分支）")
    # 姿势裁决（站长 11-02 批复：第三姿势不默认、显式开关；dry-run 展示与实际执行同源）
    st = posture(False, True); ar = posture(True, True)
    assert st["cp"] == "cp -f" and st["resume"] is True  # 默认=稳态：装载优先
    assert "--reflink=auto" in ar["cp"]                  # CoW 抢先落位
    assert ar["resume"] is False                         # adopt-race 不动 resume（18246：可装载未采纳）
    assert posture(True, False)["resume"] is False
    print("selftest[姿势裁决] OK（默认稳态 / --adopt-race 显式 CoW 不 resume）")
    print("SELFTEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
