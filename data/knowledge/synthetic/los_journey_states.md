---
document_id: SYN-LOS-STATES-001
source_type: SYNTHETIC_INTERNAL
title: Synthetic LOS Journey States
classification: DEMO_ONLY
---

# Synthetic LOS Journey States

This document defines fictional support behavior for the demo application. It is not a statement of any real lender's internal policy.

## PAN

`PENDING` means the demo application has not completed PAN verification. The customer may be asked to confirm that the PAN entered in the application is complete and correctly formatted.

`SUCCESS` means the synthetic PAN verification step completed.

`FAILURE` means the demo verification step did not complete. Support should describe only the recorded demo failure and should not claim that a government or external system rejected the customer.

## Bureau

`NOT_STARTED` means the bureau stage has not begun because an earlier prerequisite is incomplete.

`PENDING` means the demo application is awaiting a bureau response. Support must not manually retry or alter the bureau operation.

`SUCCESS` means the demo bureau step completed. Raw bureau data must not be disclosed.

`FAILURE` means the demo bureau step recorded a technical or validation failure. Support may provide safe troubleshooting guidance but must not invent a credit decision.

## Underwriting

`NOT_STARTED` means the application has not reached underwriting.

`PENDING` means the synthetic underwriting assessment is still in progress.

`APPROVED` means the demo underwriting stage completed with an approved status. This does not authorize the support system to approve or modify anything.

`REJECTED` means the demo record contains a rejected underwriting status. The support response must not expose internal-only reasoning or fabricate a rejection reason.

## Initial offer

`NOT_STARTED` means no initial offer exists in the demo record.

`AVAILABLE` means an initial offer is available for the synthetic application.

`ACCEPTED` means the synthetic customer selected the initial offer.

`DECLINED` means the demo record indicates that the initial offer was declined.

## Bank statement

`NOT_STARTED` means the stage has not been reached.

`PENDING` means a statement has not yet been accepted by the demo workflow.

`PROCESSING` means an uploaded statement is being processed.

`FAILURE` means the demo workflow could not process the submitted statement. Common synthetic causes include an unreadable file, an encrypted file, or an unsupported demo format.

`SUCCESS` means the synthetic statement-processing step completed.

In this demo workflow, a bank statement is used to review income and cash-flow information during loan assessment. Actual lender requirements may differ, so customers should follow the instructions displayed in their application.

## Final offer and selection

`AVAILABLE` means a final offer exists in the demo application.

`INITIAL` selection means the synthetic customer chose to continue with the initial offer.

`FINAL` selection means the synthetic customer selected the final offer.

`UNDECIDED` means the demo customer has not selected an offer.

Support must not change an offer or select one for the customer.

## Bank account verification

`NOT_STARTED` means the stage has not begun.

`PENDING` means verification is still in progress or awaits customer input.

`FAILURE` means the demo record contains a verification failure.

`SUCCESS` means the synthetic bank-account verification stage completed.

Support must never request credentials, passwords, OTPs, or full bank-account details by email.

## Mandate

`NOT_STARTED` means mandate setup has not begun.

`PENDING` means the synthetic mandate stage is incomplete.

`FAILURE` means the demo record contains a mandate-setup failure.

`SUCCESS` means the synthetic mandate setup completed.

The support system is read-only and cannot initiate or retry a mandate.

## Disbursal

`NOT_STARTED` means the demo application has not reached disbursal.

`PENDING` means the synthetic disbursal stage is incomplete.

`SUCCESS` means the demo record marks disbursal as completed.

The support system cannot initiate, accelerate, reverse, or otherwise modify disbursal.

## Source priority

For customer-specific questions, the current synthetic LOS record is the source of truth for the current demo state. Historical ticket memory cannot override it. Synthetic guidance must remain clearly distinguishable from real public policy.
