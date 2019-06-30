import asyncio
import boto3
import botocore
import pytest
import ujson as json

from insanic.conf import settings

from iniesta.sessions import BotoSession
from iniesta.sqs import SQSClient
from iniesta.sqs.client import default
from iniesta.sqs.message import SQSMessage

from .infra import SQSInfra, InfraBase


class TestSQSClient(SQSInfra):
    @pytest.fixture(autouse=True)
    def reset_sqs_client(self):
        yield
        SQSClient.handlers = {}
        SQSClient.queue_urls = {}

    def _queue_message(self, sqs, queue_url, number=1):
        return sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"message_number": number}),
            MessageAttributes={
                settings.INIESTA_SNS_EVENT_KEY: {
                    "DataType": "String",
                    "StringValue": "test_event"
                }
            }
        )

    @pytest.fixture
    def queue_message(self, create_service_sqs, sqs_region_name, sqs_endpoint_url):
        sqs = boto3.client('sqs', region_name=sqs_region_name, endpoint_url=sqs_endpoint_url,
                           aws_access_key_id=BotoSession.aws_access_key_id,
                           aws_secret_access_key=BotoSession.aws_secret_access_key)
        return self._queue_message(sqs, create_service_sqs['QueueUrl'])

    @pytest.fixture
    def queue_ten_messages(self, create_service_sqs, sqs_region_name, sqs_endpoint_url):
        sqs = boto3.client('sqs', region_name=sqs_region_name, endpoint_url=sqs_endpoint_url,
                           aws_access_key_id=BotoSession.aws_access_key_id,
                           aws_secret_access_key=BotoSession.aws_secret_access_key)
        messages = []
        for i in range(10):
            resp = self._queue_message(sqs, create_service_sqs['QueueUrl'], i)
            messages.append(resp)
        return messages

    def test_sqs_client_initialize_without_initialize_class_method(self):
        with pytest.raises(KeyError):
            client = SQSClient(queue_name="asd")

    async def test_sqs_client_initialize_queue_does_not_exist(self, start_local_aws, sqs_region_name, sqs_endpoint_url):
        with pytest.raises(botocore.exceptions.ClientError, match="") as exc_info:
            client = await SQSClient.initialize(queue_name='asdasdasda')

    async def test_sqs_client(self, start_local_aws, create_service_sqs, sqs_region_name, sqs_endpoint_url):
        client = await SQSClient.initialize(queue_name=self.queue_name)
        assert self.queue_name in client.queue_urls[self.queue_name]
        assert client.queue_url == create_service_sqs['QueueUrl']

    async def test_sqs_handler_function(self):
        @SQSClient.handler("something")
        def handler(*args, **kwargs):
            print(args)
            print(**kwargs)
        assert "something" in SQSClient.handlers

    async def test_receive_message(self, start_local_aws, create_service_sqs, sqs_region_name, sqs_endpoint_url,
                                   queue_ten_messages, monkeypatch):
        message_number = []

        async def mock_handle_message(self, message):
            message_number.append(message.body['message_number'])
            return message, message_number

        async def mock_hook_post_message_handler(self):
            await self.stop_receiving_messages()

        monkeypatch.setattr(SQSClient, 'hook_post_receive_message_handler', mock_hook_post_message_handler)
        monkeypatch.setattr(SQSClient, 'handle_message', mock_handle_message)

        client = await SQSClient.initialize(queue_name=self.queue_name)
        client.start_receiving_messages()

        await client._polling_task

        assert len(message_number) == 10
        assert sorted(message_number) == list(range(10))

        await client.lock_manager.destroy()

    async def test_receive_message_with_error(self, start_local_aws, create_service_sqs,
                                              sqs_region_name, sqs_endpoint_url, queue_ten_messages, monkeypatch):

        message_number = []

        async def mock_handle_message(self, message):
            def some_handler():
                pass

            message_number.append(message.body['message_number'])
            exc = RuntimeError("Some error happened!!")
            exc.message = message
            exc.handler = some_handler
            raise exc

        async def mock_hook_post_message_handler(self):
            if len(message_number) == 10:
                asyncio.Task.current_task().cancel()

        monkeypatch.setattr(SQSClient, 'hook_post_receive_message_handler', mock_hook_post_message_handler)
        monkeypatch.setattr(SQSClient, 'handle_message', mock_handle_message)

        client = await SQSClient.initialize(queue_name=self.queue_name)
        client.start_receiving_messages()

        await client._polling_task

        assert len(message_number) == 10
        assert sorted(message_number) == list(range(10))

        await client.lock_manager.destroy()

    async def test_handle_default_message(self, start_local_aws, create_service_sqs, sqs_region_name, sqs_endpoint_url,
                                          queue_ten_messages, monkeypatch):
        message_tracker = []

        @SQSClient.handler()
        def event_handler(message, **kwargs):
            assert message.event == "test_event"
            message_tracker.append(message.body['message_number'])
            return "something"

        client = await SQSClient.initialize(queue_name=self.queue_name)
        # poll_task = asyncio.ensure_future(client._poll())
        client.start_receiving_messages()

        async def mock_hook_post_message_handler(self):
            if len(message_tracker) == 10:
                await self.stop_receiving_messages()

        monkeypatch.setattr(SQSClient, 'hook_post_receive_message_handler', mock_hook_post_message_handler)

        await client._polling_task

        assert len(message_tracker) > 0

    async def test_handle_exception(self, start_local_aws, create_service_sqs, sqs_region_name, sqs_endpoint_url,
                                    queue_message, monkeypatch, caplog):
        message_tracker = []

        @SQSClient.handler()
        def event_handler(message, **kwargs):
            raise Exception("Something bad happened")

        client = await SQSClient.initialize(queue_name=self.queue_name)
        # poll_task = asyncio.ensure_future(client._poll())
        client.start_receiving_messages()

        async def mock_hook_post_message_handler(self):
            await self.stop_receiving_messages()

        monkeypatch.setattr(SQSClient, 'hook_post_receive_message_handler', mock_hook_post_message_handler)

        await client._polling_task

        # assert caplog.records[0].levelname == "ERROR"
        for log_record in caplog.records:
            if log_record.name == 'sanic.error':
                break
        assert "[INIESTA] Error while handling message:" in log_record.message
        assert hasattr(log_record, 'sqs_attributes')
        assert hasattr(log_record, 'sqs_message_body')
        assert hasattr(log_record, 'sqs_attributes')
        assert hasattr(log_record, 'sqs_message_id')

        assert caplog.records[0].iniesta_pass == "test_event"

    async def test_handle_message(self, start_local_aws, create_service_sqs, sqs_region_name, sqs_endpoint_url,
                                  queue_ten_messages, monkeypatch):
        """
        SAMPLE MESSAGE FROM AWS SQS
        {
            'MessageId': '0f9be9cc-04ee-4e55-920f-f928086d2ca7',
            'ReceiptHandle': 'AQEBu2GxhOzv8C07Tzs0Xj2KEQaaG4zBvTgLbexrtcnSHXyKSa7xH5JgnnvljKP3GL4u/+mmDGz2h4fkuyDDQSKxo5PVpP8aAk7h3SXIGkv4MTFRyTaKx4mYmeND4lRwb3wBlRDod9nUpamByMu6jKxQHbyqVG+HmSv21GTqRJk36N21k+x5buHR0DkG01NiH4zLGU0jb7FwbNGbtmRO1Pqapsap1J7ATQdl+wvxEnwRsyIXMCdNCui6RA8hvPzomKb3jss6D3f1k9XyJFoqw22ieSj7LnJ71GScz6fkNoovbBFXQf+ub4NG2TgRxOOzT+/1mJr7ddI/Ov2PEZbzET5b85trS2WtRKWfUoHtXlb2P5w8LCdR+++U/GnUIwRMlyxFRLUCBC4XXIfoiLYsZxS4Kw==',
            'MD5OfBody': 'd1691fe9a8e4e93beed42d7a1521878a',
            'Body': '{"message_number":4}',
            'Attributes': {
                'SenderId': 'AIDAJDPU3AEPJEAEBCW2W',
                'ApproximateFirstReceiveTimestamp': '1552309481056',
                'ApproximateReceiveCount': '2',
                'SentTimestamp': '1552309480314'
            },
            'MD5OfMessageAttributes': 'c45f9191837250ab2cc208d5f0362290',
            'MessageAttributes': {
                'iniesta_pass': {
                    'StringValue': 'test_event',
                    'DataType': 'String'
                }
            }
        }
        :param start_local_aws:
        :param create_service_sqs:
        :param sqs_endpoint_url:
        :param queue_ten_messages:
        :param monkeypatch:
        :return:
        """
        message_tracker = []

        @SQSClient.handler("test_event")
        def event_handler(message, **kwargs):
            message_tracker.append(message.body['message_number'])
            return "something"

        client = await SQSClient.initialize(queue_name=self.queue_name)
        # poll_task = asyncio.ensure_future(client._poll())
        client.start_receiving_messages()

        async def mock_hook_post_message_handler(self):
            if len(message_tracker) == 10:
                await self.stop_receiving_messages()

        monkeypatch.setattr(SQSClient, 'hook_post_receive_message_handler', mock_hook_post_message_handler)

        await client._polling_task

        assert len(message_tracker) == 10

    async def test_async_handle_message(self, start_local_aws, create_service_sqs, sqs_region_name, sqs_endpoint_url,
                                  queue_ten_messages, monkeypatch):
        """
        SAMPLE MESSAGE FROM AWS SQS
        {
            'MessageId': '0f9be9cc-04ee-4e55-920f-f928086d2ca7',
            'ReceiptHandle': 'AQEBu2GxhOzv8C07Tzs0Xj2KEQaaG4zBvTgLbexrtcnSHXyKSa7xH5JgnnvljKP3GL4u/+mmDGz2h4fkuyDDQSKxo5PVpP8aAk7h3SXIGkv4MTFRyTaKx4mYmeND4lRwb3wBlRDod9nUpamByMu6jKxQHbyqVG+HmSv21GTqRJk36N21k+x5buHR0DkG01NiH4zLGU0jb7FwbNGbtmRO1Pqapsap1J7ATQdl+wvxEnwRsyIXMCdNCui6RA8hvPzomKb3jss6D3f1k9XyJFoqw22ieSj7LnJ71GScz6fkNoovbBFXQf+ub4NG2TgRxOOzT+/1mJr7ddI/Ov2PEZbzET5b85trS2WtRKWfUoHtXlb2P5w8LCdR+++U/GnUIwRMlyxFRLUCBC4XXIfoiLYsZxS4Kw==',
            'MD5OfBody': 'd1691fe9a8e4e93beed42d7a1521878a',
            'Body': '{"message_number":4}',
            'Attributes': {
                'SenderId': 'AIDAJDPU3AEPJEAEBCW2W',
                'ApproximateFirstReceiveTimestamp': '1552309481056',
                'ApproximateReceiveCount': '2',
                'SentTimestamp': '1552309480314'
            },
            'MD5OfMessageAttributes': 'c45f9191837250ab2cc208d5f0362290',
            'MessageAttributes': {
                'iniesta_pass': {
                    'StringValue': 'test_event',
                    'DataType': 'String'
                }
            }
        }
        :param start_local_aws:
        :param create_service_sqs:
        :param sqs_endpoint_url:
        :param queue_ten_messages:
        :param monkeypatch:
        :return:
        """
        message_tracker = []

        @SQSClient.handler("test_event")
        async def event_handler(message, **kwargs):
            message_tracker.append(message.body['message_number'])
            return "something"

        client = await SQSClient.initialize(queue_name=self.queue_name)
        # poll_task = asyncio.ensure_future(client._poll())
        client.start_receiving_messages()

        async def mock_hook_post_message_handler(self):
            if len(message_tracker) == 10:
                await self.stop_receiving_messages()

        monkeypatch.setattr(SQSClient, 'hook_post_receive_message_handler', mock_hook_post_message_handler)

        await client._polling_task

        assert len(message_tracker) == 10

    async def test_handle_message_lock(self, start_local_aws, create_service_sqs, sqs_region_name, sqs_endpoint_url,
                                       queue_ten_messages, monkeypatch, redisdb, caplog):
        message_tracker = []

        @SQSClient.handler('test_event')
        def event_handler(message, **kwargs):
            message_tracker.append(message.body['message_number'])
            return "mess"

        client = await SQSClient.initialize(queue_name=self.queue_name)

        client.start_receiving_messages()

        async def mock_hook_post_message_hander(self):
            await self.stop_receiving_messages()

        monkeypatch.setattr(SQSClient, 'hook_post_receive_message_handler', mock_hook_post_message_hander)

        import uuid
        message_ids = []
        # set lock
        for m in queue_ten_messages:
            redisdb.set(SQSClient.lock_key.format(message_id=m['MessageId']), str(uuid.uuid4()))
            message_ids.append(m['MessageId'])

        await client._polling_task

        logged_messaged_ids = [log.sqs_message_id for log in caplog.records if hasattr(log, 'sqs_message_id')]
        for mid in message_ids:
            assert mid in logged_messaged_ids

        for log in caplog.records:
            if hasattr(log, "sqs_message_id"):
                assert "Can not acquire the lock" in log.msg

        await client.lock_manager.destroy()


class TestSQSHandlerRegistration:
    @pytest.fixture(autouse=True)
    def reset_sqs_client(self):
        yield
        SQSClient.handlers = {}
        SQSClient.queue_urls = {}

    def test_sync_function(self):
        event = "SomethingHappened.test"

        @SQSClient.handler(event)
        def handler_for_test_event(*args, **kwargs):
            return "test event"

        assert event in SQSClient.handlers
        assert SQSClient.handlers[event] == handler_for_test_event

    def test_async_function(self):
        event = "SomethingAsyncHappened.test"

        @SQSClient.handler(event)
        async def handler_for_test_event(*args, **kwargs):

            return "test event"

        assert event in SQSClient.handlers
        assert SQSClient.handlers[event] == handler_for_test_event

    def test_sync_class_method(self):
        event = "ClassHandler"

        class SomeHandler:

            @SQSClient.handler(event)
            def handler(self, *args, **kwargs):
                return "class"

        assert event in SQSClient.handlers
        assert SQSClient.handlers[event] == SomeHandler.handler

    def test_async_class_method(self):
        event = "ClassHandler"

        class SomeHandler:

            @SQSClient.handler(event)
            async def handler(self, *args, **kwargs):
                return "class"

        assert event in SQSClient.handlers
        assert SQSClient.handlers[event] == SomeHandler.handler

    def test_sync_class_method_default_handler(self):

        class SomeHandler:

            @SQSClient.handler
            def handler(self, *args, **kwargs):
                return "class"

        assert default in SQSClient.handlers
        assert SQSClient.handlers[default] == SomeHandler.handler

    def test_async_class_method_default_handler(self):

        class SomeHandler:

            @SQSClient.handler
            async def handler(self, *args, **kwargs):
                return "class"

        assert default in SQSClient.handlers
        assert SQSClient.handlers[default] == SomeHandler.handler

    def test_sync_function_default_handler(self):

        @SQSClient.handler
        def handler(self, *args, **kwargs):
            return "sync function"

        assert default in SQSClient.handlers
        assert SQSClient.handlers[default] == handler

    def test_async_function_default_handler(self):

        @SQSClient.handler
        async def handler(self, *args, **kwargs):
            return "async function"

        assert default in SQSClient.handlers
        assert SQSClient.handlers[default] == handler

    def test_handler_duplicates(self):
        event = "DoubleHandlerRegistration"

        @SQSClient.handler(event)
        def handler_one(*args, **kwargs):
            return "one"

        assert event in SQSClient.handlers

        with pytest.raises(ValueError):
            @SQSClient.handler(event)
            def handler_two(*args, **kwargs):
                return "two"

    def test_handler_without_arguments(self):
        with pytest.raises(ValueError):
            @SQSClient.handler("something")
            def handler_without_arguments():
                return "one"


class TestClientCreateMessage:
    @pytest.fixture(scope='function')
    def sqs_client(self, insanic_application):
        from iniesta import Iniesta
        Iniesta.load_config(insanic_application.config)
        SQSClient.queue_urls = {SQSClient.default_queue_name(): "hello"}
        client = SQSClient()
        yield client

        SQSClient.handlers = {}

    def test_create_message(self, sqs_client):
        message = sqs_client.create_message("hello")
        assert isinstance(message, SQSMessage)
        assert message.body == "hello"
