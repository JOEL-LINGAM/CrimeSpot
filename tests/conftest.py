import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import load_config


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture(scope="session")
def spark(cfg):
    from src.ingestion import get_spark
    s = get_spark({"spark": {"master": "local[1]", "driver_memory": "1g", "shuffle_partitions": 2}}, "tests")
    yield s
    s.stop()
