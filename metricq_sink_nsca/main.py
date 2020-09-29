import logging

import click
import click_log

from .logging import get_logger
from .reporter import ReporterSink


def verbosity_option(logger: logging.Logger, *names, **kwargs):
    if not names:
        names = ["-v", "--verbose"]
    syntax_desc = "list of [LOGGER=]LEVEL items, where LEVEL is one of CRITICAL, ERROR, WARNING, INFO or DEBUG"
    kwargs.setdefault("default", "INFO")
    kwargs.setdefault("metavar", "LEVEL")
    kwargs.setdefault("expose_value", False)
    kwargs.setdefault("help", f"A {syntax_desc}.")
    kwargs.setdefault("is_eager", True)

    def decorator(f):
        def _set_log_levels(_ctx, _param, value: str):
            for item in value.split(","):
                try:
                    name, level = item.split("=", maxsplit=1)
                    target_logger = logger.getChild(name)
                except ValueError:
                    level = item
                    target_logger = logger

                logging_level = getattr(logging, level.upper(), None)
                if logging_level is None:
                    raise click.BadParameter(f"Must be a {syntax_desc}, not {{}}")

                target_logger.setLevel(logging_level)

        return click.option(*names, callback=_set_log_levels, **kwargs)(f)

    return decorator


root_logger = get_logger()

click_log.basic_config(root_logger)
root_logger.handlers[0].formatter = logging.Formatter(
    fmt="[%(asctime)s] [%(levelname)-5s] [%(name)-20s] %(message)s"
)

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option("--metricq-server", "-s", default="amqp://localhost/")
@click.option("--token", "-t", default="sink-nsca")
@click.option("--dry-run", "-n", is_flag=True)
@verbosity_option(root_logger)
def main(metricq_server, token, dry_run):
    reporter = ReporterSink(dry_run=dry_run, management_url=metricq_server, token=token)
    reporter.run(cancel_on_exception=True)
