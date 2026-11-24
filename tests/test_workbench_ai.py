import unittest
from unittest.mock import Mock, patch

from workbench_server import app, generate_ai_copy


class WorkbenchAiTests(unittest.TestCase):
    def test_openai_uses_responses_api_and_parses_copy(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "output": [{
                "content": [{
                    "type": "output_text",
                    "text": '{"title":"新标题","description":"新正文","tags":"AI工具,效率"}',
                }],
            }],
        }
        with patch("workbench_server.requests.post", return_value=response) as post:
            result = generate_ai_copy(
                "openai", "sk-test", "gpt-6-astra", "generate_all",
                "介绍发布工具", "", "", "",
            )

        self.assertEqual(result["title"], "新标题")
        self.assertEqual(result["tags"], "AI工具, 效率")
        self.assertEqual(post.call_args.args[0], "https://api.openai.com/v1/responses")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer sk-test")
        self.assertFalse(post.call_args.kwargs["json"]["store"])

    def test_deepseek_uses_chat_completions_json_mode(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '{"title":"标题","description":"正文","tags":["创作","工具"]}',
                },
            }],
        }
        with patch("workbench_server.requests.post", return_value=response) as post:
            result = generate_ai_copy(
                "deepseek", "ds-test", "deepseek-flash", "optimize_tags",
                "", "标题", "正文", "旧标签",
            )

        self.assertEqual(result["tags"], "创作, 工具")
        self.assertEqual(post.call_args.args[0], "https://api.deepseek.com/chat/completions")
        self.assertEqual(post.call_args.kwargs["json"]["response_format"], {"type": "json_object"})

    def test_missing_api_key_is_rejected_before_network_call(self):
        with patch("workbench_server.requests.post") as post:
            with self.assertRaisesRegex(ValueError, "API Key"):
                generate_ai_copy("openai", "", "gpt-6-astra", "generate_all", "介绍工具", "", "", "")
        post.assert_not_called()

    def test_provider_metadata_never_contains_api_keys(self):
        response = app.test_client().get("/api/ai/providers")
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("openai", body)
        self.assertIn("deepseek", body)
        self.assertNotIn("api_key", str(body).lower())


if __name__ == "__main__":
    unittest.main()
