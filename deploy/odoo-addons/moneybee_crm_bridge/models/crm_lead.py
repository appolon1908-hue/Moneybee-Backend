from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    moneybee_lead_id = fields.Char(copy=False, index=True)
    moneybee_application_id = fields.Char(copy=False, index=True)
    moneybee_status = fields.Char(index=True)
    moneybee_risk_status = fields.Char()
    moneybee_use_of_funds = fields.Char()
    moneybee_source = fields.Char()
    moneybee_landing_page = fields.Char()
    moneybee_last_sync_at = fields.Datetime()

    _sql_constraints = [
        (
            "moneybee_crm_lead_unique",
            "unique(moneybee_lead_id)",
            "A MoneyBee lead may only create one CRM opportunity.",
        ),
        (
            "moneybee_crm_application_unique",
            "unique(moneybee_application_id)",
            "A MoneyBee application may only exist once in CRM.",
        ),
    ]

    @api.model
    def moneybee_health(self):
        return {
            "ok": True,
            "module": "moneybee_crm_bridge",
            "version": "19.0.1.0.0",
        }

    @api.model
    def moneybee_upsert(self, payload):
        """Apply a MoneyBee projection atomically; never change MoneyBee itself."""
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        lead_id = payload.get("moneybee_lead_id")
        if not lead_id:
            raise ValueError("moneybee_lead_id is required")

        application_id = payload.get("moneybee_application_id")
        applicant = payload.get("applicant") or {}
        business = payload.get("business") or {}
        marketing = payload.get("marketing") or {}
        now = fields.Datetime.now()
        partner_model = self.env["res.partner"]

        company = partner_model.search(
            [("moneybee_business_lead_id", "=", lead_id)], limit=1
        )
        company_values = {
            "name": business.get("name") or "MoneyBee Business",
            "is_company": True,
            "company_type": "company",
            "website": business.get("website") or False,
            "phone": applicant.get("phone") or False,
            "street": business.get("street") or False,
            "street2": business.get("street2") or False,
            "city": business.get("city") or False,
            "zip": business.get("zip") or False,
            "moneybee_business_lead_id": lead_id,
            "moneybee_application_id": application_id or False,
            "moneybee_last_sync_at": now,
        }
        if company:
            company.write(company_values)
        else:
            company = partner_model.create(company_values)

        contact = partner_model.search(
            [("moneybee_contact_lead_id", "=", lead_id)], limit=1
        )
        full_name = (
            f"{applicant.get('first_name') or ''} "
            f"{applicant.get('last_name') or ''}"
        ).strip()
        contact_values = {
            "name": full_name or "MoneyBee Applicant",
            "is_company": False,
            "company_type": "person",
            "parent_id": company.id,
            "email": applicant.get("email") or False,
            "phone": applicant.get("phone") or False,
            "moneybee_contact_lead_id": lead_id,
            "moneybee_application_id": application_id or False,
            "moneybee_last_sync_at": now,
        }
        if contact:
            contact.write(contact_values)
        else:
            contact = partner_model.create(contact_values)

        opportunity = self.search([("moneybee_lead_id", "=", lead_id)], limit=1)
        try:
            expected_revenue = float(payload.get("requested_amount") or 0)
        except (TypeError, ValueError):
            expected_revenue = 0.0
        opportunity_values = {
            "name": f"MoneyBee | {business.get('name') or 'Business'}",
            "type": "opportunity",
            "partner_id": company.id,
            "contact_name": full_name or False,
            "email_from": applicant.get("email") or False,
            "phone": applicant.get("phone") or False,
            "expected_revenue": expected_revenue,
            "moneybee_lead_id": lead_id,
            "moneybee_application_id": application_id or False,
            "moneybee_status": payload.get("moneybee_status") or False,
            "moneybee_risk_status": payload.get("moneybee_risk_status") or False,
            "moneybee_use_of_funds": payload.get("use_of_funds") or False,
            "moneybee_source": (
                marketing.get("utm_source")
                or marketing.get("affiliate_code")
                or False
            ),
            "moneybee_landing_page": marketing.get("landing_page") or False,
            "moneybee_last_sync_at": now,
        }
        for payload_key, odoo_key in (
            ("stage_id", "stage_id"),
            ("salesperson_user_id", "user_id"),
            ("sales_team_id", "team_id"),
        ):
            value = payload.get(payload_key)
            if value:
                opportunity_values[odoo_key] = int(value)
        if opportunity:
            opportunity.write(opportunity_values)
        else:
            opportunity = self.create(opportunity_values)

        return {
            "company_id": company.id,
            "contact_id": contact.id,
            "opportunity_id": opportunity.id,
            "moneybee_lead_id": lead_id,
            "moneybee_application_id": application_id,
            "status": "SUCCESS",
        }

