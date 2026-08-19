from typing import Any

import pytest

from app.ai.crew import STAGE_OUTPUTS


def assert_strict_object_schemas(node: Any) -> None:
    if isinstance(node, dict):
        assert "default" not in node
        properties = node.get("properties")
        if isinstance(properties, dict):
            assert node.get("additionalProperties") is False
            assert set(node.get("required", [])) == set(properties)
        for value in node.values():
            assert_strict_object_schemas(value)
    elif isinstance(node, list):
        for value in node:
            assert_strict_object_schemas(value)


@pytest.mark.parametrize(
    "output_model",
    STAGE_OUTPUTS.values(),
    ids=lambda model: model.__name__,
)
def test_agent_output_schema_is_openai_strict_compatible(output_model: type) -> None:
    schema = output_model.model_json_schema()

    assert_strict_object_schemas(schema)
