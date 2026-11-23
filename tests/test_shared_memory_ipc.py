"""Unit tests for Windows Kernel Zero-Copy Shared Memory IPC."""

import uuid
from local_ai_hub.shared_memory_ipc import (
    SharedMemoryChannel,
    TYPE_RAW,
    TYPE_JSON,
    TYPE_TENSOR,
)


def test_shared_memory_create_write_read_unlink() -> None:
    shm_name = f"test_shm_{uuid.uuid4().hex[:8]}"
    channel = SharedMemoryChannel.create(name=shm_name, size=64 * 1024)

    try:
        # 1. Write binary message
        data = b"Hello Local AI Hub Shared Memory"
        seq = channel.write_payload(data, payload_type=TYPE_RAW)
        assert seq == 1

        # Read back (copy=True)
        res = channel.read_payload(copy=True)
        assert res is not None
        payload, p_type, shape, r_seq = res
        assert payload == data
        assert p_type == TYPE_RAW
        assert r_seq == 1

        # Second read returns None (no new message)
        assert channel.read_payload() is None

        # 2. Write second message with tensor shape and read zero-copy view
        tensor_bytes = bytearray(128 * 4)  # 128 floats
        seq2 = channel.write_payload(tensor_bytes, payload_type=TYPE_TENSOR, shape=(1, 128))
        assert seq2 == 2

        res2 = channel.read_payload(copy=False)
        assert res2 is not None
        v2, p2, s2, sq2 = res2
        assert len(v2) == len(tensor_bytes)
        assert p2 == TYPE_TENSOR
        assert s2 == (1, 128)
        assert sq2 == 2
    finally:
        channel.close()
        channel.unlink()


def test_shared_memory_producer_consumer_attachment() -> None:
    shm_name = f"test_shm_{uuid.uuid4().hex[:8]}"
    producer = SharedMemoryChannel.create(name=shm_name, size=32 * 1024)

    try:
        consumer = SharedMemoryChannel.attach(name=shm_name)
        payload = b'{"status": "ok", "embeddings": [0.1, 0.2, 0.3]}'
        producer.write_payload(payload, payload_type=TYPE_JSON)

        res = consumer.read_payload(copy=True)
        assert res is not None
        v, p_type, shape, seq = res
        assert v == payload
        assert p_type == TYPE_JSON
        consumer.close()
    finally:
        producer.close()
        producer.unlink()
