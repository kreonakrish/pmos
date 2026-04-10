import asyncio
import json

import redis.asyncio as aioredis

from app.services.ingestion import IngestionService
from app.utils.logger import get_logger

logger = get_logger(layer="stream_consumer")

_GROUP = "rag-ingestor"
_CONSUMER = "consumer-1"
_STREAM = "events:documents"


class DocumentStreamConsumer:
    """
    Consumes the Redis stream ``events:documents`` and triggers the ingestion
    pipeline for each message.
    """

    def __init__(self, redis_url: str, ingestion: IngestionService) -> None:
        self._redis_url = redis_url
        self._ingestion = ingestion
        self._running = False
        self._redis: aioredis.Redis | None = None

    async def start(self) -> None:
        self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        # Ensure consumer group exists
        try:
            await self._redis.xgroup_create(_STREAM, _GROUP, id="0", mkstream=True)
            logger.info("Redis consumer group created", group=_GROUP, stream=_STREAM)
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                logger.info("Consumer group already exists", group=_GROUP)
            else:
                logger.error("Failed to create consumer group", error=str(exc))

        self._running = True
        asyncio.create_task(self._consume_loop())
        logger.info("Document stream consumer started", stream=_STREAM)

    async def stop(self) -> None:
        self._running = False
        if self._redis:
            await self._redis.aclose()
        logger.info("Document stream consumer stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _consume_loop(self) -> None:
        while self._running:
            try:
                messages = await self._redis.xreadgroup(
                    _GROUP,
                    _CONSUMER,
                    {_STREAM: ">"},
                    count=5,
                    block=1000,
                )
                if not messages:
                    continue
                for stream_name, entries in messages:
                    for msg_id, fields in entries:
                        await self._handle_message(msg_id, fields)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Stream consumer error", error=str(exc))
                await asyncio.sleep(2)

    async def _handle_message(self, msg_id: str, fields: dict) -> None:
        trace_id = fields.get("trace_id", msg_id)
        log = logger.with_trace(trace_id)
        try:
            content = fields.get("content", "")
            filename = fields.get("filename", "unknown")
            agent_id = int(fields.get("agent_id", 0))
            team_id = fields.get("team_id", "")
            chunk_strategy = fields.get("chunk_strategy", "fixed")

            if not content:
                log.warning("Empty content in document event", msg_id=msg_id)
                await self._redis.xack(_STREAM, _GROUP, msg_id)
                return

            await self._ingestion.ingest_document(
                content=content,
                filename=filename,
                agent_id=agent_id,
                team_id=team_id,
                options={"chunk_strategy": chunk_strategy},
                trace_id=trace_id,
            )
            await self._redis.xack(_STREAM, _GROUP, msg_id)
            log.info("Document event processed", msg_id=msg_id)
        except Exception as exc:
            log.error("Failed to process document event", msg_id=msg_id, error=str(exc))
            # Do NOT ack — message stays in PEL for retry
