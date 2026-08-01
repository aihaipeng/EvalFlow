import pytest

from execution.resource_names import next_copy_name


def test_next_copy_name_keeps_appending_until_unique():
    assert next_copy_name(
        "诊断流程", {"诊断流程", "诊断流程_copy", "诊断流程_copy_copy"}
    ) == "诊断流程_copy_copy_copy"


def test_next_copy_name_rejects_names_over_resource_limit():
    with pytest.raises(ValueError, match="不能超过 200"):
        next_copy_name("x" * 200, {"x" * 200})
