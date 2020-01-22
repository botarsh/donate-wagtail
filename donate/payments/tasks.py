import logging
import time

import braintree
from django.conf import settings
from django.utils.timezone import datetime

import django_rq
import requests
import stripe

from . import constants, gateway
from .sqs import send_to_sqs
from .utils import (
    zero_decimal_currency_fix,
    get_plan_id,
    get_merchant_account_id_for_card
)


logger = logging.getLogger(__name__)

queue = django_rq.get_queue('default')

BASKET_NEWSLETTER_API_PATH = '/news/subscribe/'
STRIPE_WEBHOOK_SECRET = settings.STRIPE_WEBHOOK_SECRET
stripe.api_key = settings.STRIPE_API_KEY


def send_stripe_transaction_to_basket(subscription, charge, metadata,
                                      donation_url, conversion_amount,
                                      net_amount, transaction_fee):
    project = 'mozillafoundation'

    if 'thunderbird' in metadata:
        project = 'thunderbird'
    elif 'glassroomnyc' in metadata:
        project = 'glassroomnyc'

    send_to_sqs({
        'data': {
            'event_type': 'donation',
            'last_name': subscription.customer.sources.data[0]['name'],
            'email': subscription.customer.email,
            'donation_amount': zero_decimal_currency_fix(charge.amount, charge.currency),
            'currency': charge.currency,
            'created': charge.created,
            'recurring': True,
            'frequency': 'monthly',
            'service': 'stripe',
            'transaction_id': charge.id,
            'subscription_id': subscription.id,
            'donation_url': donation_url,
            'project': project,
            'locale': subscription.metadata.locale,
            'last_4': subscription.customer.sources.data[0]['last4'],
            'conversion_amount': conversion_amount,
            'net_amount': net_amount,
            'transaction_fee': transaction_fee
        }
    })


def send_newsletter_subscription_to_basket(data):
    if settings.BASKET_API_ROOT_URL is None:
        return

    url = f'{settings.BASKET_API_ROOT_URL}{BASKET_NEWSLETTER_API_PATH}'
    payload = {
        'format': 'html',
        'lang': data['lang'],
        'newsletters': 'mozilla-foundation',
        'source_url': data['source_url'],
        'email': data['email']
    }
    try:
        return requests.post(url, data=payload)
    except requests.exceptions.RequestException:
        logger.exception('Failed to post to basket newsletter API')


def send_transaction_to_basket(data):
    send_to_sqs({
        'data': {
            'event_type': 'donation',
            'last_name': data['last_name'],
            'first_name': data['first_name'],
            'campaign_id': data['campaign_id'],
            'email': data['email'],
            'donation_amount': data['amount'],
            'currency': data['currency'],
            'created': int(time.time()),
            'recurring': data['payment_frequency'] == constants.FREQUENCY_MONTHLY,
            'service': data['payment_method'],
            'transaction_id': data['transaction_id'],
            'subscription_id': data.get('subscription_id', None),
            'project': data['project'],
            'card_type': data.get('card_type', 'Unknown'),
            'last_4': data.get('last_4', None),
            'donation_url': data['landing_url'],
            'locale': data['locale'],
            'conversion_amount': data.get('settlement_amount', None),
        }
    })


class BraintreeWebhookProcessor:

    def process(self, notification):
        kind = notification.kind
        if kind == 'subscription_charged_successfully':
            self.subscription_charged_successfully(notification)
        elif kind == 'subscription_charged_unsuccessfully':
            self.subscription_charged_unsuccessfully(notification)
        elif kind == 'dispute_lost':
            self.dispute_lost(notification)

    def subscription_charged_successfully(self, notification):
        last_tx = notification.subscription.transactions[0]
        is_paypal = last_tx.payment_instrument_type == 'paypal_account'

        # Custom fields are stored against the customer, and it requires a few
        # steps to get this object from Braintree
        payment_method = gateway.payment_method.find(notification.subscription.payment_method_token)
        customer = gateway.customer.find(payment_method.customer_id)
        custom_fields = customer.custom_fields or {}

        # The details of a donor are in a different spot depending on the payment method

        if is_paypal:
            donor_details = {
                "last_name": last_tx.paypal_details.payer_last_name,
                "first_name": last_tx.paypal_details.payer_first_name,
                "email": last_tx.paypal_details.payer_email
            }
        elif last_tx.payment_instrument_type == 'credit_card':
            donor_details = {
                'last_name': last_tx.customer_details.last_name,
                'first_name': last_tx.customer_details.first_name,
                'email': last_tx.customer_details.email,
            }
        else:
            logger.error(f"Unexpected payment type on subscription webhook: {last_tx.payment_instrument_type}")

        send_transaction_to_basket({
            'last_name': donor_details.get('last_name', ''),
            'first_name': donor_details.get('first_name', ''),
            'campaign_id': custom_fields.get('campaign_id', ''),
            'email': donor_details.get('email', ''),
            'amount': last_tx.amount,
            'currency': last_tx.currency_iso_code.lower(),
            'payment_frequency': constants.FREQUENCY_MONTHLY,
            'payment_method': constants.METHOD_PAYPAL if is_paypal else constants.METHOD_CARD,
            'transaction_id': last_tx.id,
            'subscription_id': notification.subscription.id,
            'project': custom_fields.get('project', ''),
            'card_type': 'Unknown' if is_paypal else last_tx.credit_card_details.card_type,
            'last_4': None if is_paypal else last_tx.credit_card_details.last_4,
            'landing_url': '',
            'locale': custom_fields.get('locale', ''),
            'settlement_amount': last_tx.disbursement_details.settlement_amount,
        })

    def subscription_charged_unsuccessfully(self, notification):
        send_to_sqs({
            'data': {
                'event_type': 'charge.failed',
                'transaction_id': notification.subscription.id,
                'failure_code': notification.subscription.transactions[0].status,
            }
        })

    def dispute_lost(self, notification):
        send_to_sqs({
            'data': {
                'event_type': 'charge.dispute.closed',
                'status': 'lost',
                'transaction_id': notification.dispute.transaction.id,
                'failure_code': notification.dispute.reason,
            }
        })


class StripeWebhookProcessor:
    def process(self, event):
        # Stripe event types use dot-notation, so convert periods to underscores
        event_type = event.type.replace('.', '_')

        try:
            process_method = getattr(self, f'process_{event_type}')
        except AttributeError:
            logger.info(f'An unsupported Stripe event was not processed: {event_type}')
            return

        if process_method is not None:
            return process_method(event)

    def process_charge_succeeded(self, event):
        charge_id = event.data.object.id
        try:
            charge = stripe.Charge.retrieve(
                charge_id,
                expand=['invoice', 'balance_transaction']
            )
        except stripe.error.StripeError as e:
            logger.error(f'Error fetching Stripe Charge: {e._message}', exc_info=True)
            return

        if not charge.invoice or not charge.invoice.subscription:
            logger.info('This charge is not associated with a subscription')
            return

        balance_transaction = charge.balance_transaction
        conversion_amount = balance_transaction.amount / 100
        net_amount = balance_transaction.net / 100
        transaction_fee = balance_transaction.fee / 100

        subscription_id = charge.invoice.subscription

        try:
            subscription = stripe.Subscription.retrieve(subscription_id, expand=['customer'])
        except stripe.error.StripeError as e:
            logger.error(f'Error fetching Stripe Subscription: {e._message}', exc_info=True)
            return

        metadata = subscription.metadata
        donation_url = None

        if 'donation_url' in metadata:
            donation_url = metadata['donation_url']

        if 'thunderbird' in metadata:
            description = 'Thunderbird monthly'
        elif 'glassroomnyc' in metadata:
            description = 'glassroomnyc monthly'
        else:
            description = 'Mozilla Foundation Monthly Donation'

        try:
            stripe.Charge.modify(charge_id, metadata=metadata, description=description)
        except stripe.error.StripeError as e:
            logger.error(f'Error updating Stripe Charge description and metadata: {e._message}', exc_info=True)
            return

        send_stripe_transaction_to_basket(
            subscription,
            charge,
            metadata,
            donation_url,
            conversion_amount,
            net_amount,
            transaction_fee,
        )

        # disabled for now
        # if 'thunderbird' not in metadata:
        #     # MigrateStripeSubscription().process(charge, subscription.customer)
        #     MigrateStripeSubscription().process(
        #         charge,
        #         subscription
        #     )


class MigrateStripeSubscription:
    def process(self, charge, subscription):
        last4 = subscription.customer.sources.data[0].last4
        BT_customers = gateway.customer.search(
            braintree.TransactionSearch.customer_email == charge.customer_email,
            braintree.TransactionSearch.credit_card_number.ends_with(last4)
        )

        if len(BT_customers) == 0:
            logger.error(f'No Customer record exists in Braintree '
                         f'for the Stripe customer attached to this charge object:'
                         f'{charge.id}', exc_info=True)
            return

        BT_customer = BT_customers[0]

        if len(BT_customer.payment_methods) == 0:
            logger.error(f'The Braintree customer does not have an associated PaymentMethod')
            return

        payment_method_token = BT_customer.payment_methods[0].token

        BT_plan_id = get_plan_id(subscription.plan.currency)
        BT_merchant_account = get_merchant_account_id_for_card(subscription.plan.currency)
        BT_price = zero_decimal_currency_fix(charge.amount, subscription.plan.currency)
        BT_first_billing_date = datetime.utcfromtimestamp(subscription.current_period_end)

        BT_create_subscription_result = gateway.subscription.create({
            'payment_method_token': payment_method_token,
            'plan_id': BT_plan_id,
            'merchant_account_id': BT_merchant_account,
            'price': BT_price,
            'first_billing_date': BT_first_billing_date
        })

        if not BT_create_subscription_result.is_success:
            logger.error(f'Failed to create a Braintree subscription from Stripe subscription {subscription.id}')
            return

        # Cancel Stripe subscription
        try:
            stripe.Subscription.delete(subscription.id)
        except stripe.error.StripeError:
            logger.error(f'Failed to cancel the stripe subscription '
                         f'{subscription.id}, cancelling the Braintree subscription')

            BT_cancel_subscription_result = gateway.subscription.cancel(
                BT_create_subscription_result.subscription.id
            )

            if not BT_cancel_subscription_result.is_success:
                logger.critical(f'Failed to cancel the Braintree Subscription, '
                                f'customer now has two active subscriptions - '
                                f'Braintree: {BT_create_subscription_result.subscription.id}, '
                                f'Stripe: {subscription.id}')

        finally:
            return


def process_webhook(form_data):
    """
    Called in response to a BrainTree webhook for successful subscription transaction
    (e.g. monthy / monthly upsell)
    """
    notification = gateway.webhook_notification.parse(form_data['bt_signature'], form_data['bt_payload'])
    BraintreeWebhookProcessor().process(notification)


def process_stripe_webhook(form_data, signature=None):
    try:
        event = stripe.Event.construct_from(
            form_data,
            signature,
            STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        logger.error('Request payload invalid', exc_info=True)
        return
    except stripe.error.SignatureVerificationError:
        logger.error('Request signature invalid', exc_info=True)
        return

    StripeWebhookProcessor().process(event)
