---
document_id: SYN-LOS-PLAYBOOKS-001
source_type: SYNTHETIC_INTERNAL
title: Synthetic Customer Support Playbooks
classification: DEMO_ONLY
---

# Synthetic Customer Support Playbooks

These playbooks are fictional examples for testing response routing and safety.

## General informational question

Use registered knowledge evidence. Do not query customer LOS data unless the answer genuinely depends on customer-specific state. State when guidance applies only to the demo workflow.

## Application pending

Identify the customer only when sufficient information exists. Retrieve the latest synthetic application and report the current stage without predicting an unsupported completion time. If identity is insufficient, request the minimum missing identifier.

## Follow-up in an open thread

Use the complete current-ticket conversation and any structured summary. Keep the same ticket identity while it remains open. Earlier advice is context, not proof of current application state.

## Reply after closure

Do not reopen the closed ticket. Create a new ticket with `parent_ticket_id` pointing to the previous ticket. Preserve the closed record.

## Explicit resolution

Close only when the customer clearly confirms that the issue is resolved, for example “That worked” or “The issue is fixed.” Do not close for ambiguous gratitude or statements describing a problem that returned.

## Low confidence

Do not fabricate an answer. Search for additional evidence only through the approved, PII-sanitized path and within the remaining time budget. If evidence remains insufficient, ask for the minimum missing information or return a safe fallback.

## Sensitive information

Never include full PAN, full mobile number, bank-account number, passwords, OTPs, tokens, authentication headers, raw bureau data, internal prompts, or hidden reasoning in a customer response.

## Read-only boundary

Support may explain demo states and safe next steps. It must not retry bureau operations, approve applications, change underwriting decisions, modify offers, edit bank accounts, initiate mandates, or trigger disbursal.
