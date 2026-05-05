import os
from typing import Generator

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def get_redis_connection() -> Generator[redis.Redis, None, None]:
    conn = redis.from_url(REDIS_URL)
    try:
        yield conn
    finally:
        conn.close()
