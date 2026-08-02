import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srt_translate import orchestrator as orch


class _FakeStore:
    def __init__(self, payload):
        self._payload = payload

    def get_task(self, _video_id):
        return SimpleNamespace(payload=self._payload)


class _FakeSourceStorage:
    def list_dir(self, _directory):
        return [
            ("Whistle.ai.srt", "file", 100),
            ("Whistle.en.srt", "file", 100),
            ("Whistle.json", "file", 200),
        ]


class TestMigratePreplan(unittest.TestCase):
    def test_stale_plan_is_reclassified_and_pending_plan_is_not_applied(self):
        stale_payload = {
            "source": {"video_size_bytes": 1},
            "normalized_basename": "Wrong.Movie.Path",
            "dest_dir": "/Movies4K/2024/Wrong.Movie.Path",
            "subtitle_moves": [],
        }
        store = _FakeStore({"plan": stale_payload})
        source_storage = _FakeSourceStorage()
        migrate_cfg = SimpleNamespace(subtitle=SimpleNamespace(extensions=(".srt",)))
        fresh_plan = orch.MovePlan(
            source=orch.SourceFiles("Show/Season 01/Show.mkv", (), 1),
            normalized_basename="Show",
            dest_dir="",
            dest_video_path="Show/Season 01/Show.mkv",
            subtitle_moves=(),
            skip_reason="classification pending: episode is missing",
        )

        with (
            patch.object(orch, "plan_one", return_value=fresh_plan) as replan,
            patch.object(orch, "apply_one") as apply,
        ):
            ok, err = orch._migrate_task(
                migrate_cfg=migrate_cfg,
                llm=object(),
                source_storage=source_storage,
                dest_storage=object(),
                video_remote_path="/Downloads/Show/Season 01/Show.mkv",
                root_path="/Downloads",
                dry_run=False,
                store=store,
                video_id="vid-stale",
            )

        self.assertFalse(ok)
        self.assertIn("CLASSIFICATION_PENDING", err or "")
        replan.assert_called_once()
        apply.assert_not_called()

    def test_locked_plan_keeps_root_json_move(self):
        plan_payload = {
            "classification_version": 2,
            "source": {"video_size_bytes": 1},
            "normalized_basename": "Whistle.2025.1080p.WEB-DL.x265-BONE",
            "dest_dir": "/X-Movie/2025/Whistle.2025.1080p.WEB-DL.x265-BONE",
            "subtitle_moves": [
                [
                    "Whistle.json",
                    "/X-Movie/2025/Whistle.2025.1080p.WEB-DL.x265-BONE/Whistle.2025.1080p.WEB-DL.x265-BONE.json",
                ]
            ],
        }
        store = _FakeStore({"plan": plan_payload})
        source_storage = _FakeSourceStorage()
        dest_storage = object()
        migrate_cfg = SimpleNamespace(subtitle=SimpleNamespace(extensions=(".srt", ".ai.srt")))

        captured = {}

        def _fake_apply(_cfg, _source, _dest, plan):
            captured["plan"] = plan
            return True, None, None

        with patch.object(orch, "apply_one", side_effect=_fake_apply):
            ok, err = orch._migrate_task(
                migrate_cfg=migrate_cfg,
                llm=None,
                source_storage=source_storage,
                dest_storage=dest_storage,
                video_remote_path="/Downloads/Whistle.mkv",
                root_path="/Downloads",
                dry_run=False,
                store=store,
                video_id="vid-1",
            )

        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertIn("plan", captured)
        moved_sources = {src for src, _dst in captured["plan"].subtitle_moves}
        self.assertIn("Whistle.json", moved_sources)


if __name__ == "__main__":
    unittest.main()
