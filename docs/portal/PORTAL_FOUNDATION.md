# MoneyBee Portal Foundation

This branch adds the shared runtime used by the borrower, lender/bank, and MoneyBee operations portals.

## API boundary

All new routes are exposed only under `/api/v2`.

The portal layer resolves the authenticated local principal, requires an active organization, and filters navigation and records by authoritative membership and permissions. The frontend does not become an authorization authority.

## Shared capabilities

- authenticated portal context and permission-filtered navigation;
- organization-scoped tasks and optimistic version checks;
- user-scoped notifications;
- organization-scoped conversations and messages;
- quarantine-first document upload sessions;
- durable provider webhook receipt storage for the later gateway branch.

## Fail-closed controls

Document uploads require all of the following:

1. an authorized application;
2. the `documents.secure_upload` capability;
3. configured private S3-compatible object storage;
4. server-side encryption headers;
5. file name, size, media type, and SHA-256 validation;
6. object metadata verification after upload;
7. quarantine status before malware scanning.

An upload never creates an authoritative MoneyBee document until a later scanner workflow marks it safe.

## Production status

This is an implementation branch, not a production activation. No lender submission, credit pull, e-signature, funding, bank transfer, or external delivery capability is enabled by this work.
