# MoneyBee contract readback endpoints

Updated: 2026-09-02

These additive `/api/v2` reads close public, identity, application-status, and offer-detail gaps without introducing a new mutation or live-provider capability.

## Endpoints

| Method and path | Authentication | Authority and response boundary |
| --- | --- | --- |
| `GET /api/v2/me/permissions` | Required | Returns the active organization plus the effective local MoneyBee roles, permissions, and membership types resolved for the authenticated principal. Token roles alone are not authoritative. |
| `GET /api/v2/public/products` | Public | Returns distinct product categories backed by active lender programs. It does not expose lender identity, private underwriting criteria, ranking inputs, or program configuration. |
| `GET /api/v2/applications/{application_id}/status` | Required | Uses the same tenant/ownership authorization as the application resource and returns status, completion percentage, and aggregate version. |
| `GET /api/v2/offers/{offer_id}` | Required | Loads the owning application through the authoritative tenant/ownership check before returning the normalized offer. |

The same router is mounted under `/api/v1` only as a hidden compatibility alias. Canonical OpenAPI contains `/api/v2` paths only; compatibility responses carry deprecation and sunset headers.

## Error and security behavior

- Invalid or unknown resources return the repository's `application/problem+json` envelope.
- Cross-tenant and wrong-owner access is rejected by the existing principal/resource authorization layer.
- Public product reads are subject to the distributed public rate-limit policy.
- No endpoint calls a lender, credit, e-signature, payment, CRM, workflow, or communications provider.
- No endpoint changes application, offer, capability, integration, or financial state.

## Contract evidence

`scripts/sync_contract_completion_manifest.py` deterministically generates the additive OpenAPI digest manifest. The normal OpenAPI verifier and endpoint-catalog drift gate fail when the runtime surface differs from the reviewed contract.
