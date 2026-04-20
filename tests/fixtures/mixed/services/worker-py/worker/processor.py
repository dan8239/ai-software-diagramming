from common.log import get_logger

log = get_logger(__name__)


class Processor:
    def handle(self, evt: dict) -> None:
        log.info("processing %s", evt.get("id"))
