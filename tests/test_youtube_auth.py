import time
import unittest
from datetime import datetime, timedelta

from uploader.youtube_uploader.main import (
    YouTubeVideo,
    _is_google_login_url,
    _is_youtube_studio_url,
    _state_has_youtube_session,
    _schedule_date_text,
    _schedule_time_text,
)


class YouTubeAuthHelpersTest(unittest.TestCase):
    def test_saved_session_accepts_unexpired_youtube_login_cookie(self):
        state = {"cookies": [{
            "domain": ".youtube.com",
            "name": "LOGIN_INFO",
            "expires": time.time() + 3600,
        }]}
        self.assertTrue(_state_has_youtube_session(state))

    def test_saved_session_rejects_expired_youtube_login_cookie(self):
        state = {"cookies": [{
            "domain": ".youtube.com",
            "name": "LOGIN_INFO",
            "expires": time.time() - 1,
        }]}
        self.assertFalse(_state_has_youtube_session(state))

    def test_login_and_studio_url_classification(self):
        self.assertTrue(_is_google_login_url("https://accounts.google.com/v3/signin/identifier"))
        self.assertTrue(_is_youtube_studio_url("https://studio.youtube.com/"))
        self.assertTrue(_is_youtube_studio_url("https://studio.youtube.com/channel/UC123"))
        self.assertFalse(_is_youtube_studio_url("https://www.youtube.com/"))

    def test_video_accepts_immediate_publish_without_missing_setter(self):
        video = YouTubeVideo("title", "video.mp4", [], "youtube.json")
        self.assertEqual(video.publish_date, 0)

    def test_video_validates_scheduled_publish_time(self):
        target = datetime.now() + timedelta(hours=3)
        video = YouTubeVideo("title", "video.mp4", [], "youtube.json", publish_date=target)
        self.assertEqual(video.publish_date, target)

    def test_schedule_values_match_youtube_english_picker(self):
        target = datetime(2026, 11, 22, 10, 45)
        self.assertEqual(_schedule_date_text(target), "Nov 22, 2026")
        self.assertEqual(_schedule_time_text(target), "10:45 AM")

        afternoon = datetime(2026, 11, 22, 22, 5)
        self.assertEqual(_schedule_time_text(afternoon), "10:05 PM")

if __name__ == "__main__":
    unittest.main()
