import json

import requests
from kafka import KafkaConsumer

from common.log import get_logger
from worker.processor import Processor

log = get_logger(__name__)


def main() -> None:
    consumer = KafkaConsumer("orders", bootstrap_servers="kafka:9092")
    p = Processor()
    for msg in consumer:
        evt = json.loads(msg.value)
        p.handle(evt)
        requests.post("https://api.internal/ack", json={"id": evt["id"]})


if __name__ == "__main__":
    main()
