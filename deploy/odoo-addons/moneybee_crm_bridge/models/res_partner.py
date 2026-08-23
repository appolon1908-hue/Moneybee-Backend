from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    moneybee_business_lead_id = fields.Char(copy=False, index=True)
    moneybee_contact_lead_id = fields.Char(copy=False, index=True)
    moneybee_application_id = fields.Char(copy=False, index=True)
    moneybee_last_sync_at = fields.Datetime()

    _sql_constraints = [
        (
            "moneybee_business_lead_unique",
            "unique(moneybee_business_lead_id)",
            "A MoneyBee business may only exist once.",
        ),
        (
            "moneybee_contact_lead_unique",
            "unique(moneybee_contact_lead_id)",
            "A MoneyBee contact may only exist once.",
        ),
    ]

