from .reporter import ReporterSink
from .logging import get_logger

import click
import click_log
import logging

logger = get_logger()

click_log.basic_config(logger)
logger.setLevel("INFO")
logger.handlers[0].formatter = logging.Formatter(
    fmt="[%(asctime)s] [%(levelname)-5s] [%(name)-20s] %(message)s"
)


@click.command()
@click.option("--metricq-server", "-s", default="amqp://localhost/")
@click.option("--token", "-t", default="sink-nsca")
@click_log.simple_verbosity_option(logger)
def main(metricq_server, token):
    reporter = ReporterSink(management_url=metricq_server, token=token)
    reporter.run()
