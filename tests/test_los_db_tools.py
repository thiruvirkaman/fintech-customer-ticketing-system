from app.tools.los_db import LosDataTools


def test_db_tool_rejects_non_allowlisted_and_write_operations() -> None:
    tools = LosDataTools.__new__(LosDataTools)
    tools._tools = {}
    for operation in ("execute_sql", "insert", "update", "delete", "drop", "alter", "truncate"):
        try:
            tools.invoke(operation, query="ignored")
        except ValueError as exc:
            assert "not allowlisted" in str(exc)
        else:
            raise AssertionError(f"{operation} should have been rejected")
