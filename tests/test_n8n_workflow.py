import json
from pathlib import Path


WORKFLOW_PATH = Path("n8n/nbfc_email_ticketing.json")


def load_workflow() -> dict:
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_workflow_is_inactive_and_has_a_valid_connected_graph() -> None:
    workflow = load_workflow()
    nodes = workflow["nodes"]
    node_names = [node["name"] for node in nodes]
    node_ids = [node["id"] for node in nodes]

    assert workflow["id"]
    assert workflow["active"] is False
    assert len(node_names) == len(set(node_names))
    assert len(node_ids) == len(set(node_ids))
    assert {"Gmail Trigger", "Gmail Reply", "HTTP Preflight", "HTTP Process Ticket"} <= set(node_names)
    assert {"Blocked or Duplicate?", "Close Ticket?", "Safe to Send?", "Gmail Delivery Succeeded?"} <= set(node_names)

    for source_name, outputs in workflow["connections"].items():
        assert source_name in node_names
        for branch in outputs["main"]:
            for connection in branch:
                assert connection["node"] in node_names


def test_workflow_targets_all_required_api_endpoints() -> None:
    workflow = load_workflow()
    urls = {
        node["parameters"].get("url")
        for node in workflow["nodes"]
        if node["type"] == "n8n-nodes-base.httpRequest"
    }
    assert "https://REPLACE_WITH_FASTAPI_HOST/api/v1/preflight" in urls
    assert "https://REPLACE_WITH_FASTAPI_HOST/api/v1/tickets/process" in urls
    assert "https://REPLACE_WITH_FASTAPI_HOST/api/v1/tickets/delivery" in urls


def test_workflow_contains_placeholders_but_no_embedded_secrets() -> None:
    workflow = load_workflow()
    serialized = json.dumps(workflow)

    assert "REPLACE_WITH_GOOGLE_SHEET_ID" in serialized
    assert "REPLACE_WITH_FASTAPI_HOST" in serialized
    assert "X-Internal-API-Key" in serialized
    assert "sk-" not in serialized.casefold()
    assert "bearer " not in serialized.casefold()

    credential_ids = [
        credential["id"]
        for node in workflow["nodes"]
        for credential in node.get("credentials", {}).values()
    ]
    assert credential_ids
    assert all(credential_id.startswith("REPLACE_WITH_") for credential_id in credential_ids)


def test_only_safe_send_branch_reaches_gmail_reply() -> None:
    workflow = load_workflow()
    safe_branches = workflow["connections"]["Safe to Send?"]["main"]
    assert [connection["node"] for connection in safe_branches[0]] == ["Gmail Reply"]
    assert all(connection["node"] != "Gmail Reply" for connection in safe_branches[1])

    blocked_branches = workflow["connections"]["Blocked or Duplicate?"]["main"]
    assert [connection["node"] for connection in blocked_branches[0]] == ["Stop - Blocked or Duplicate"]


def test_gmail_normalization_handles_raw_mime_payloads() -> None:
    workflow = load_workflow()
    normalize_node = next(node for node in workflow["nodes"] if node["name"] == "Normalize Email")
    script = normalize_node["parameters"]["jsCode"]
    assert "Array.isArray(rawHeaders)" in script
    assert "findPlainPart" in script
    assert "decodeBase64Url" in script
    assert "Buffer.from" in script


def test_preflight_includes_google_sheet_ticket_reference() -> None:
    workflow = load_workflow()
    preflight_node = next(node for node in workflow["nodes"] if node["name"] == "HTTP Preflight")
    body_expression = preflight_node["parameters"]["body"]
    assert "existing_ticket" in body_expression
    assert "Lookup Ticket by Thread" in workflow["connections"]


def test_processing_timeout_allows_internal_budget() -> None:
    workflow = load_workflow()
    process_node = next(node for node in workflow["nodes"] if node["name"] == "HTTP Process Ticket")
    assert process_node["parameters"]["options"]["timeout"] >= 50_000


def test_repeat_acknowledgement_is_visible_in_sheet_outcome() -> None:
    workflow = load_workflow()
    sent_node = next(node for node in workflow["nodes"] if node["name"] == "Update Ticket - SENT")
    outcome = sent_node["parameters"]["columns"]["value"]["outcome"]

    assert "repeat_query" in outcome
    assert "ALREADY_ANSWERED" in outcome
