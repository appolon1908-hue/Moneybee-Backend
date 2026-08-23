from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationPolicy:
    in_app: bool
    email: bool
    sms: bool
    priority: str = "normal"
    marketing: bool = False


POLICIES: dict[str, NotificationPolicy] = {
    "lead.created.v1": NotificationPolicy(True, True, False),
    "condition.requested.v1": NotificationPolicy(True, True, True, "high"),
    "offer.received.v1": NotificationPolicy(True, True, True, "high"),
    "offer.expired.v1": NotificationPolicy(True, True, False),
    "contract.sent.v1": NotificationPolicy(True, True, True, "high"),
    "contract.signed.v1": NotificationPolicy(True, True, False),
    "funding.confirmed.v1": NotificationPolicy(True, True, True, "high"),
    "renewal.eligible.v1": NotificationPolicy(True, True, True),
    "complaint.created.v1": NotificationPolicy(True, True, False, "high"),
    "document.clean.v1": NotificationPolicy(False, False, False),
}


def channels_for_event(
    event_type: str,
    *,
    in_app_enabled: bool,
    email_enabled: bool,
    sms_enabled: bool,
    marketing_consent: bool,
    ready_channels: frozenset[str],
    quiet_hours: bool = False,
) -> frozenset[str]:
    """Return allowed channels after consent, preference and readiness checks."""
    policy = POLICIES.get(event_type)
    if policy is None or (policy.marketing and not marketing_consent):
        return frozenset()

    selected: set[str] = set()
    if policy.in_app and in_app_enabled and "in_app" in ready_channels:
        selected.add("in_app")
    if policy.email and email_enabled and "email" in ready_channels:
        selected.add("email")
    if (
        policy.sms
        and sms_enabled
        and "sms" in ready_channels
        and (not quiet_hours or policy.priority == "urgent")
    ):
        selected.add("sms")
    return frozenset(selected)

