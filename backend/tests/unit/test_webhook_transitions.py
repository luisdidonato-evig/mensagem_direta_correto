from app.api.v1.webhooks import transition_recipient
from app.models.campaign import CampaignRecipient, RecipientStatus


def recipient(status: RecipientStatus) -> CampaignRecipient:
    return CampaignRecipient(
        campaign_id="campaign",
        external_contact_id="contact",
        phone_e164="+5511999999999",
        status=status,
    )


def test_status_does_not_regress_on_out_of_order_webhook() -> None:
    item = recipient(RecipientStatus.DELIVERED)

    transition_recipient(item, RecipientStatus.SENT)

    assert item.status == RecipientStatus.DELIVERED


def test_opt_out_always_wins() -> None:
    item = recipient(RecipientStatus.READ)

    transition_recipient(item, RecipientStatus.OPTED_OUT)

    assert item.status == RecipientStatus.OPTED_OUT
