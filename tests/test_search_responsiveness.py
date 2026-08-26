import os
import unittest
from unittest.mock import Mock, patch

import httpx


class SearchResponsivenessTest(unittest.TestCase):
    def test_public_search_uses_bounded_timeout(self):
        response = Mock()
        response.text = '<a class="result__a" href="https://ustc.edu.cn/news">通知</a>'
        response.raise_for_status.return_value = None

        from tools.search import SEARCH_TIMEOUT, _search_web_results

        with patch("tools.search.httpx.get", return_value=response) as request:
            results = _search_web_results("USTC", max_results=1)

        self.assertEqual(results[0]["title"], "通知")
        timeout = request.call_args.kwargs["timeout"]
        self.assertIsInstance(timeout, httpx.Timeout)
        self.assertEqual(timeout.connect, SEARCH_TIMEOUT.connect)
        self.assertEqual(timeout.read, SEARCH_TIMEOUT.read)
        self.assertLessEqual(timeout.connect, 5.0)
        self.assertLessEqual(timeout.read, 15.0)

    def test_search_error_tells_agent_not_to_retry(self):
        from tools.search import search_web

        # 显式锁定 DDG 路径：.env 中 WEBSEARCH_PROVIDER=tavily 时真实
        # Tavily 请求会先于被 mock 的 DDG 成功，测不到错误文案。
        env = {"WEBSEARCH_PROVIDER": "ddg"}
        with patch.dict(os.environ, env, clear=False):
            with patch("tools.search.httpx.get", side_effect=OSError("proxy unavailable")):
                result = search_web.invoke({"query": "USTC"})

        self.assertIn("搜索失败", result)
        self.assertIn("请不要重复调用此工具", result)


class LLMConfigCompatibilityTest(unittest.TestCase):
    def test_rag_llm_accepts_chat_agent_environment_names(self):
        from campus_rag import llm_factory

        env = {
            "OPENAI_API_KEY": "",
            "OPENAI_BASE_URL": "",
            "OPENAI_MODEL": "",
            "LLM_API_KEY": "test-key",
            "LLM_BASE_URL": "https://example.invalid/v1",
            "LLM_MODEL": "test-model",
            "LLM_TIMEOUT_SECONDS": "12",
            "LLM_PROVIDER": "openai",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch.object(llm_factory, "_read_settings", return_value={}):
                with patch("llama_index.llms.openai.OpenAI") as openai:
                    llm_factory.get_llm()

        kwargs = openai.call_args.kwargs
        self.assertEqual(kwargs["api_key"], "test-key")
        self.assertEqual(kwargs["api_base"], "https://example.invalid/v1")
        self.assertEqual(kwargs["model"], "test-model")
        self.assertEqual(kwargs["timeout"], 12.0)

    def test_rag_llm_fails_fast_without_credentials(self):
        from campus_rag import llm_factory

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "",
                "LLM_API_KEY": "",
                "LLM_PROVIDER": "openai",
            },
            clear=False,
        ):
            with patch.object(llm_factory, "_read_settings", return_value={}):
                with self.assertRaisesRegex(RuntimeError, "未配置 LLM API Key"):
                    llm_factory.get_llm()


if __name__ == "__main__":
    unittest.main()
