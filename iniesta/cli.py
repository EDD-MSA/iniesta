# -*- coding: utf-8 -*-

"""Main module."""

import asyncio
import click
import importlib
import logging
import json
import sys
import os

from insanic.conf import settings

from iniesta import Iniesta
from iniesta.sns import SNSClient
from iniesta.sqs import SQSClient

logger = logging.getLogger(__name__)


@click.group()
def cli():
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, '')

def mock_application():
    service_name = os.getcwd().split('/')[-1]
    config = importlib.import_module(f"{service_name}.config")

    settings.configure(
        INIESTA_DRY_RUN=True,
        **{c: getattr(config, c) for c in dir(config) if c.isupper()}
    )
    Iniesta.load_config(settings)


    class Dummy:
        config = None

    dummy = Dummy()
    setattr(dummy, 'config', settings)

    with open(f"{service_name}/app.py", "r") as file:
        for line in file:
            if "Insanic(" in line:
                variable_name = line.split('=')[0].strip()
                exec(f"{variable_name} = dummy")
            elif line.startswith('Iniesta.'):
                exec(line)
                break

@cli.command()
def initialization_type():
    mock_application()
    from iniesta import Iniesta
    print(Iniesta.initialization_type)

@cli.command()
def filter_policies():
    mock_application()
    from iniesta.utils import filter_list_to_filter_policies

    policies = filter_list_to_filter_policies(settings.INIESTA_SNS_EVENT_KEY,
                                              settings.INIESTA_SQS_CONSUMER_FILTERS)
    print(json.dumps(policies))

@cli.command()
@click.option('-e', '--event', required=True, type=str, help="Event to publish into SNS")
@click.option('-m', '--message', required=True, type=str, help="Message body to publish into SNS")
@click.option('-v', '--version', required=False, type=int, help="Version to publish into SNS")
def publish(event, message, version):
    # TODO: documentation for read me
    if version is None:
        version = 1

    sns_client = SNSClient()

    loop = asyncio.get_event_loop()
    message = sns_client.create_message(event=event, message=message, version=version)
    loop.run_until_complete(message.publish())

@cli.command()
@click.option('-m', '--message', required=True, type=str, help="Message body to publish to SQS")
def send(message):
    # TODO: documentation for read me
    loop = asyncio.get_event_loop()
    sqs_client = loop.run_until_complete(SQSClient.initialize())
    message = sqs_client.create_message(message=message)
    loop.run_until_complete(message.send())
