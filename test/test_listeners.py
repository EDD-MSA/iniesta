import boto3
import pytest
import ujson as json

from insanic.conf import settings
from iniesta.listeners import IniestaListener
from iniesta.sns import SNSClient
from iniesta.sqs import SQSClient

from .infra import SNSInfra, SQSInfra


class TestListeners(SNSInfra, SQSInfra):
    run_local = False
    queue_name = 'iniesta-test-xavi'

    @pytest.fixture(scope='function')
    async def sns_client(self, create_global_sns, sns_endpoint_url, monkeypatch):
        monkeypatch.setattr(settings,
                            'INIESTA_SNS_PRODUCER_GLOBAL_TOPIC_ARN',
                            create_global_sns['TopicArn'])

        client = await SNSClient.initialize(
            topic_arn=create_global_sns['TopicArn']
        )

        return client

    @pytest.fixture(scope='function')
    async def sqs_client(self, sqs_endpoint_url, sns_client, create_service_sqs):
        client = await SQSClient.initialize(
            queue_name=self.queue_name
        )
        yield client

        SQSClient.handlers = {}

    @pytest.fixture
    def listener(self, start_local_aws,
                 sns_endpoint_url, sqs_endpoint_url, monkeypatch):

        listener = IniestaListener()
        yield listener


    filters = []

    @pytest.fixture(scope='function')
    def subscribe_sqs_to_sns(self, start_local_aws, create_global_sns, sqs_client,
                                create_service_sqs, sns_endpoint_url, monkeypatch):

        monkeypatch.setattr(settings, 'INIESTA_SQS_CONSUMER_FILTERS', ['Pass.xavi', 'Trap.*'], raising=False)
        sns = boto3.client('sns', endpoint_url=sns_endpoint_url)

        response = sns.subscribe(TopicArn=create_global_sns['TopicArn'],
                                 Protocol='sqs',
                                 Endpoint=create_service_sqs['Attributes']['QueueArn'],
                                 Attributes={
                                     "RawMessageDelivery": "true",
                                     "FilterPolicy": json.dumps(sqs_client.filters),
                                 })
        yield response

        sns.unsubscribe(SubscriptionArn=response['SubscriptionArn'])

    @pytest.fixture(scope='function')
    def add_permissions(self, subscribe_sqs_to_sns, create_global_sns,
                        create_service_sqs, sqs_endpoint_url):
        sqs = boto3.client('sqs', endpoint_url=sqs_endpoint_url)

        response = sqs.set_queue_attributes(
            QueueUrl=create_service_sqs['QueueUrl'],
            Attributes={
                "Policy": json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Id": f"arn:aws:sqs:ap-northeast-1:120387605022:{self.queue_name}/SQSDefaultPolicy",
                        "Statement": [
                            {
                                "Sid": "Sid1552456721343",
                                "Effect": "Allow",
                                "Principal": "*",
                                "Action": "SQS:SendMessage",
                                "Resource": create_service_sqs['Attributes']['QueueArn'],
                                "Condition": {
                                    "ArnEquals": {
                                        "aws:SourceArn": create_global_sns['TopicArn']
                                    }
                                }
                            }
                        ]
                    }
                )
            }
        )

        return response

    async def test_producer_listener(self, insanic_application, listener, sns_client):
        await listener.after_server_start_producer_check(insanic_application)

        assert hasattr(insanic_application, 'xavi')
        assert isinstance(insanic_application.xavi, SNSClient)

    async def test_queue_polling(self, insanic_application, listener, sqs_client):
        await listener.after_server_start_start_queue_polling(insanic_application)

        assert hasattr(insanic_application, 'messi')
        assert isinstance(insanic_application.messi, SQSClient)
        assert insanic_application.messi._receive_messages is True
        assert insanic_application.messi._polling_task is not None


    async def test_event_polling(self, insanic_application, listener,
                                 sns_client, sqs_client,
                                 subscribe_sqs_to_sns,
                                 add_permissions, monkeypatch):
        monkeypatch.setattr(settings, 'INIESTA_ASSERT_FILTER_POLICIES', not self.run_local)

        await listener.after_server_start_event_polling(insanic_application)

        assert hasattr(insanic_application, 'messi')
        assert isinstance(insanic_application.messi, SQSClient)

        assert insanic_application.messi._receive_messages is True
        assert insanic_application.messi._polling_task is not None
