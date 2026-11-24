import unittest
from unittest.mock import patch

from uploader.douyin_uploader.main import (
    DOUYIN_BROWSER_ARGS,
    _build_browser_launch_kwargs,
)


class DouyinBrowserLaunchTests(unittest.TestCase):
    def test_uses_configured_executable(self):
        edge_path = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"

        with patch("uploader.douyin_uploader.main.LOCAL_CHROME_PATH", edge_path):
            launch_kwargs = _build_browser_launch_kwargs(headless=False)

        self.assertEqual(
            launch_kwargs,
            {
                "headless": False,
                "args": DOUYIN_BROWSER_ARGS,
                "executable_path": edge_path,
            },
        )

    def test_falls_back_to_bundled_chromium(self):
        with patch("uploader.douyin_uploader.main.LOCAL_CHROME_PATH", ""):
            launch_kwargs = _build_browser_launch_kwargs(headless=True)

        self.assertEqual(
            launch_kwargs,
            {
                "headless": True,
                "args": DOUYIN_BROWSER_ARGS,
                "channel": "chromium",
            },
        )


if __name__ == "__main__":
    unittest.main()
