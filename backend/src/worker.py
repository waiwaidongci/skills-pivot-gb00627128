import logging
import time
from pathlib import Path
from src.services import comparison as comparisons
from src.services.execution import claim, execute, materialize_due
from src.utils.wakeup import wait

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
heartbeat = Path('/tmp/analysis-heartbeat')


def main():
    while True:
        try:
            materialize_due()
            worked = False
            lease = claim()
            heartbeat.touch()
            if lease:
                execute(lease)
                worked = True
                heartbeat.touch()
            lease = comparisons.claim()
            heartbeat.touch()
            if lease:
                comparisons.execute(lease)
                worked = True
                heartbeat.touch()
            if not worked:
                wait()
        except Exception:
            log.exception('Worker cycle failed')
            time.sleep(2)


if __name__ == '__main__':
    main()
