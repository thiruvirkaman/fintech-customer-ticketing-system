---
document_id: SYN-LOS-FAILURES-001
source_type: SYNTHETIC_INTERNAL
title: Synthetic LOS Failure Codes
classification: DEMO_ONLY
---

# Synthetic LOS Failure Codes

Every code in this file is fictional and begins with `DEMO_`. These codes must never be presented as real lender or provider codes.

## DEMO_PAN_FORMAT_INVALID

The synthetic PAN value did not match the demo format check. Ask the customer to verify the value inside the official application. Do not request a full PAN over email.

## DEMO_PAN_VERIFICATION_UNAVAILABLE

The demo PAN verification dependency was unavailable. Explain that verification could not be completed and that no manual approval or override is available through support.

## DEMO_BUREAU_TIMEOUT

The synthetic bureau operation exceeded its demo timeout. Do not claim a credit rejection and do not retry the bureau operation from the support system.

## DEMO_BUREAU_IDENTITY_MISMATCH

The demo record indicates that identity information did not match. Request only the minimum information required through an approved channel.

## DEMO_UNDERWRITING_REVIEW_REQUIRED

The synthetic application requires additional review. Do not fabricate a completion time or internal decision reason.

## DEMO_BANK_STATEMENT_ENCRYPTED

The synthetic statement processor could not read an encrypted or password-protected file. The safe support action is to ask for a supported unencrypted document through the application upload flow, never through email.

## DEMO_BANK_STATEMENT_UNREADABLE

The synthetic statement file could not be read. Ask the customer to upload a clear and complete file using the official application.

## DEMO_BANK_STATEMENT_FORMAT_UNSUPPORTED

The demo workflow received a statement format outside its supported test formats. Support must not invent a real lender format list unless backed by public evidence.

## DEMO_BANK_ACCOUNT_NAME_MISMATCH

The synthetic bank-account verification record contains a name mismatch. Do not disclose full account information.

## DEMO_BANK_ACCOUNT_VERIFICATION_FAILED

The demo bank-account verification step did not complete. Support cannot edit the account or bypass verification.

## DEMO_MANDATE_SETUP_FAILED

The synthetic mandate setup failed. Support cannot initiate or retry the mandate and must avoid requesting authentication credentials.

## DEMO_DISBURSAL_PENDING_REVIEW

The synthetic disbursal remains pending review. Do not promise a completion time without authoritative evidence.

## Safe use

When a failure code is present, responses should translate it into clear demo support language while preserving uncertainty. The raw code does not authorize an action or establish a real external-system cause.
