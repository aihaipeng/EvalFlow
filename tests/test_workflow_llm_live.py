import asyncio
import os

import pytest

from execution.workflow_adapters import WorkflowNodeAdapter
from execution.workflow_contract import LlmNode
from execution.model_providers import ModelProviderRepository


pytestmark = pytest.mark.live


def test_real_llm_adapter_returns_text_and_runtime_facts():
    provider_id = os.getenv("WORKFLOW_LIVE_PROVIDER_ID")
    model_name = os.getenv("WORKFLOW_LIVE_MODEL")
    if not provider_id or not model_name:
        pytest.skip("WORKFLOW_LIVE_PROVIDER_ID and WORKFLOW_LIVE_MODEL are required")
    node = LlmNode.model_validate(
        {
            "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
            "type": "LLM",
            "name": "Live LLM",
            "description": "",
            "model": {"provider_id": provider_id, "model_name": model_name},
            "prompt": {"system": "只输出简短中文文本。", "user": "回复：工作流验证通过"},
            "generation": {"stream": False, "parameters": {"temperature": 0, "max_tokens": 1024}},
            "execution": {"timeout_ms": 120000, "max_attempts": 0, "delay_ms": 0},
            "outputs": [{"name": "llm_text", "type": "string"}],
        }
    )

    result = asyncio.run(WorkflowNodeAdapter()(node, {}))

    assert isinstance(result.response, str) and result.response.strip()
    assert result.outputs == {"llm_text": result.response}
    assert result.request["user"] == "回复：工作流验证通过"
    assert result.model == {"provider_id": provider_id, "model_name": model_name}


@pytest.mark.parametrize("model_name", ["grok-4.5", "qwen3.7-max", "deepseek-v4-pro"])
def test_configured_real_model_matrix(model_name):
    if os.getenv("WORKFLOW_LIVE_MATRIX") != "1":
        pytest.skip("WORKFLOW_LIVE_MATRIX=1 is required")
    provider = next((item for item in ModelProviderRepository().list() if model_name in item.models), None)
    if provider is None:
        pytest.skip(f"Configured provider for {model_name} is required")
    node = LlmNode.model_validate(
        {
            "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
            "type": "LLM",
            "name": f"Live {model_name}",
            "description": "",
            "model": {"provider_id": provider.id, "model_name": model_name},
            "prompt": {"system": "只输出一句简短中文。", "user": "回复：模型节点验证通过"},
            "generation": {"stream": False, "parameters": {"temperature": 0, "max_tokens": 1024}},
            "execution": {"timeout_ms": 180000, "max_attempts": 0, "delay_ms": 0},
            "outputs": [{"name": "llm_text", "type": "string"}],
        }
    )

    result = asyncio.run(WorkflowNodeAdapter()(node, {}))

    assert isinstance(result.response, str) and result.response.strip()
    assert result.outputs == {"llm_text": result.response}
    assert result.inputs == {}
    assert result.request["user"] == "回复：模型节点验证通过"
    assert result.model == {"provider_id": provider.id, "model_name": model_name}
    assert result.usage is not None
