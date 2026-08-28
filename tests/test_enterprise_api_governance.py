import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "contracts/enterprise-api-governance.json").read_text())


def test_enterprise_api_governance_is_fail_closed():
    assert CONTRACT["canonicalApiPrefix"] == "/api/v2"
    assert CONTRACT["legacyApi"]["deprecated"] is True
    assert CONTRACT["legacyApi"]["newRoutesAllowed"] is False

    writes = CONTRACT["writeControls"]
    assert writes["idempotencyRequiredForExternallyEffectivePost"] is True
    assert writes["auditRequired"] is True
    assert writes["transactionalOutboxRequiredForCrossSystemEffects"] is True
    assert writes["businessMutationAndOutboxSameTransaction"] is True

    identity = CONTRACT["identity"]
    assert identity["issuer"] == "https://auth.codestra.co/realms/codestra"
    assert identity["audience"] == "moneybee-api"
    assert identity["backendJwtRevalidationRequired"] is True
    assert identity["tenantAuthorizationRequiredServerSide"] is True

    events = CONTRACT["events"]
    assert events["source"] == "urn:codestra:moneybee-backend"
    assert events["middlewareIsCrossSystemMutationBoundary"] is True
    assert events["idempotencyRequired"] is True

    delivery = CONTRACT["delivery"]
    assert delivery["workerRole"] == "transport-only"
    assert delivery["globalCrmGateOnAllEvents"] is False
    assert delivery["boundedRetries"] is True

    production = CONTRACT["production"]
    assert production["featureBranchDeploymentAllowed"] is False
    assert production["externalEffectsDefaultDisabled"] is True
    assert production["humanApprovalRequired"] is True
