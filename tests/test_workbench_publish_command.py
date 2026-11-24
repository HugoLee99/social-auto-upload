import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from workbench_server import build_publish_command, make_preset_draft


class WorkbenchPublishCommandTests(unittest.TestCase):
    def test_bilibili_upload_does_not_receive_browser_runtime_flag(self):
        task = {
            "video": "demo.mp4",
            "title": "demo",
            "description": "description",
            "tags": "tag",
            "bilibili_tid": 21,
            "headed": True,
        }

        command = build_publish_command(task, {"platform": "bilibili", "alias": "hugo"})

        self.assertNotIn("--headed", command)
        self.assertNotIn("--headless", command)
        self.assertEqual(command[-2:], ["--tid", "21"])

    def test_browser_platform_keeps_requested_runtime_flag(self):
        task = {
            "video": "demo.mp4",
            "title": "demo",
            "description": "description",
            "tags": "tag",
            "headed": True,
        }

        command = build_publish_command(task, {"platform": "douyin", "alias": "creator"})

        self.assertEqual(command[-1], "--headed")

    def test_xiaohongshu_uses_only_portrait_cover(self):
        task = {
            "video": "demo.mp4",
            "title": "demo",
            "description": "description",
            "tags": "tag",
            "cover": "landscape.png",
            "cover_portrait": "portrait.png",
            "headed": True,
        }

        command = build_publish_command(
            task, {"platform": "xiaohongshu", "alias": "creator"}
        )

        thumbnail_index = command.index("--thumbnail")
        self.assertEqual(command[thumbnail_index + 1], "portrait.png")
        self.assertNotIn("landscape.png", command)

    def test_xiaohongshu_does_not_fall_back_to_landscape_cover(self):
        task = {
            "video": "demo.mp4",
            "title": "demo",
            "description": "description",
            "tags": "tag",
            "cover": "landscape.png",
            "cover_portrait": None,
            "headed": True,
        }

        command = build_publish_command(
            task, {"platform": "xiaohongshu", "alias": "creator"}
        )

        self.assertNotIn("--thumbnail", command)
        self.assertNotIn("landscape.png", command)

    def test_reused_publish_becomes_safe_draft_with_new_schedule_required(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir:
            uploads = Path(temp_dir)
            original_folder = uploads / "original"
            original_folder.mkdir()
            video = original_folder / "demo.mp4"
            video.write_bytes(b"video")
            task = {
                "id": "original",
                "status": "completed",
                "created_at": "2026-11-17T10:00:00+08:00",
                "video": str(video),
                "cover": None,
                "cover_portrait": None,
                "schedule": "2026-11-17 18:00",
                "results": [{"status": "success"}],
                "cancel_requested": True,
            }

            with patch("workbench_server.UPLOADS", uploads):
                draft = make_preset_draft(task)

        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["schedule"], "")
        self.assertEqual(draft["copied_from"], "original")
        self.assertEqual(draft["results"], [])
        self.assertNotIn("cancel_requested", draft)


if __name__ == "__main__":
    unittest.main()
