"""多LLM客户端 - 免费优先，付费兜底，自动降级"""
import os
import json
import time
import re
from typing import Optional, List
from pathlib import Path

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def _load_config() -> dict:
    """加载config.yaml"""
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        config_path = Path("config.yaml")
    if HAS_YAML:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    else:
        # 简单YAML解析器 (仅支持本项目的简单格式)
        return _simple_yaml_parse(config_path)


def _simple_yaml_parse(path: Path) -> dict:
    """简单YAML解析 - 仅处理本项目的嵌套结构"""
    result = {}
    stack = [(result, -1)]
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.split("#")[0].rstrip()
            if not stripped:
                continue
            indent = len(line) - len(line.lstrip())
            while len(stack) > 1 and indent <= stack[-1][1]:
                stack.pop()
            if ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if value:
                    # 尝试转换类型
                    if value.lower() == "true":
                        value = True
                    elif value.lower() == "false":
                        value = False
                    elif value.lower() == "null":
                        value = None
                    elif value.startswith("[") and value.endswith("]"):
                        try:
                            value = json.loads(value)
                        except:
                            pass
                    else:
                        try:
                            value = int(value) if "." not in value else float(value)
                        except:
                            pass
                    stack[-1][0][key] = value
                else:
                    stack[-1][0][key] = {}
                    stack.append((stack[-1][0][key], indent))
    return result


class LLMClient:
    """
    多LLM客户端:
    - 自动使用免费API (Gemini free tier)
    - 失败时按配置的 fallback_chain 自动降级
    - 支持 rate limiting
    - 统一的 chat() 接口
    """

    def __init__(self, config: dict = None):
        if config is None:
            config = _load_config()
        self.config = config.get("llm", {})
        self.provider = self.config.get("provider", "gemini")
        self.model = self.config.get("model", "gemini-2.0-flash")
        self.temperature = self.config.get("temperature", 0.1)
        self.max_tokens = self.config.get("max_tokens", 4096)
        self.timeout = self.config.get("timeout", 30)
        self.fallback_chain = self.config.get("fallback_chain", ["gemini", "zhipu", "qwen", "deepseek"])
        self._last_call_time = 0
        self._call_count = 0
        self._active_provider = self.provider

        # 导入 openai 客户端 (兼容所有 OpenAI-compatible API)
        try:
            from openai import OpenAI
            self._OpenAI = OpenAI
        except ImportError:
            self._OpenAI = None
            print("[WARN] openai 包未安装，LLM功能不可用: pip install openai")

    def _get_client(self, provider: str):
        """为指定provider创建OpenAI-compatible客户端"""
        if self._OpenAI is None:
            raise ImportError("需要安装 openai: pip install openai")

        provider_config = self.config.get(provider, {})
        api_key = provider_config.get("api_key", "")

        # 也检查环境变量
        env_keys = {
            "gemini": "GEMINI_API_KEY",
            "zhipu": "ZHIPU_API_KEY",
            "qwen": "QWEN_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
        }
        if not api_key:
            api_key = os.environ.get(env_keys.get(provider, ""), "")

        if not api_key:
            raise ValueError(f"{provider} API key未配置。请在config.yaml或环境变量中设置。")

        base_url = provider_config.get("base_url", "")
        model = provider_config.get("model", self.model)

        return self._OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=self.timeout,
        ), model

    def _rate_limit(self, provider: str):
        """简单的速率限制"""
        provider_config = self.config.get(provider, {})
        rpm_limit = provider_config.get("rpm_limit", 60)
        min_interval = 60.0 / rpm_limit

        elapsed = time.time() - self._last_call_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_call_time = time.time()
        self._call_count += 1

    def chat(self, prompt: str, system: str = "", use_fallback: bool = True) -> str:
        """
        发送聊天请求。自动降级。
        
        Args:
            prompt: 用户消息
            system: 系统提示词
            use_fallback: 是否启用降级链
            
        Returns:
            LLM响应文本
        """
        providers = [self.provider]
        if use_fallback:
            for p in self.fallback_chain:
                if p != self.provider:
                    providers.append(p)

        last_error = None
        for provider in providers:
            try:
                self._rate_limit(provider)
                client, model = self._get_client(provider)

                messages = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages.append({"role": "user", "content": prompt})

                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )

                result = response.choices[0].message.content.strip()
                self._active_provider = provider
                return result

            except Exception as e:
                last_error = e
                print(f"  [LLM] {provider} 失败: {str(e)[:100]}")
                continue

        # 所有provider都失败
        raise RuntimeError(f"所有LLM provider均失败。最后错误: {last_error}")

    def chat_json(self, prompt: str, system: str = "") -> dict:
        """发送请求并解析JSON响应"""
        response = self.chat(prompt, system)
        # 清理markdown代码块
        cleaned = re.sub(r'```(?:json)?\s*\n?', '', response).strip()
        cleaned = cleaned.rstrip('`').strip()
        return json.loads(cleaned)

    @property
    def is_available(self) -> bool:
        """检查是否有可用的LLM provider"""
        if self._OpenAI is None:
            return False
        for provider in [self.provider] + self.fallback_chain:
            provider_config = self.config.get(provider, {})
            api_key = provider_config.get("api_key", "") or os.environ.get(
                {"gemini": "GEMINI_API_KEY", "zhipu": "ZHIPU_API_KEY",
                 "qwen": "QWEN_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}.get(provider, ""), ""
            )
            if api_key:
                return True
        return False

    def test_connection(self) -> dict:
        """测试所有配置的LLM连接"""
        results = {}
        for provider in self.fallback_chain:
            try:
                client, model = self._get_client(provider)
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "Say hello in 5 words."}],
                    max_tokens=20,
                )
                results[provider] = {
                    "status": "ok",
                    "model": model,
                    "response": response.choices[0].message.content.strip()
                }
            except Exception as e:
                results[provider] = {"status": "error", "error": str(e)[:200]}
        return results


# 全局实例
_client_instance = None

def get_llm_client(config: dict = None) -> LLMClient:
    """获取全局LLM客户端实例"""
    global _client_instance
    if _client_instance is None:
        _client_instance = LLMClient(config)
    return _client_instance
