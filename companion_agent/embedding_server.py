"""Optional CPU semantic embeddings served only on the local loopback interface."""

from __future__ import annotations

import argparse
import ctypes
import importlib
import math
import os
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

MODEL = "BAAI/bge-small-zh-v1.5"
DIMENSIONS = 512
TextInput = Annotated[str, Field(min_length=1, max_length=16000)]
Encoder = Callable[[list[str]], list[list[float]]]
_runtime_handles: list[Any] = []


class EmbeddingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    input: TextInput | Annotated[list[TextInput], Field(min_length=1, max_length=16)]
    encoding_format: Literal["float"] = "float"


def load_encoder(cache_dir: Path, threads: int, runtime_dir: Path | None = None) -> Encoder:
    if runtime_dir is not None and os.name == "nt":
        # An optional application-local Microsoft runtime avoids replacing system DLLs.
        directory = runtime_dir.resolve(strict=True)
        _runtime_handles.append(os.add_dll_directory(str(directory)))
        _runtime_handles.append(ctypes.WinDLL(str(directory / "msvcp140.dll")))
    # Import lazily: the normal application and its offline tests do not require ONNX.
    try:
        backend = importlib.import_module("fastembed")
    except ModuleNotFoundError:
        raise RuntimeError(
            "Install the optional embedding extra: pip install -e .[embedding]"
        ) from None
    model = backend.TextEmbedding(
        model_name=MODEL,
        cache_dir=str(cache_dir),
        threads=threads,
        providers=["CPUExecutionProvider"],
    )

    def encode(texts: list[str]) -> list[list[float]]:
        # BGE v1.5 supports unprefixed embeddings. Keep document/query encoding identical
        # to the application's existing OpenAI-compatible transport contract.
        return [[float(value) for value in row] for row in model.embed(texts)]

    # Load and exercise inference before advertising readiness or accepting requests.
    encode(["本地语义检索准备完成。"])
    return encode


def create_embedding_app(encode: Encoder) -> FastAPI:
    app = FastAPI(title="Companion local embeddings", docs_url=None, redoc_url=None)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )
    lock = Lock()
    requests = 0
    texts_embedded = 0

    @app.get("/health")
    def health() -> dict[str, Any]:
        with lock:
            return {
                "status": "ready",
                "model": MODEL,
                "dimensions": DIMENSIONS,
                "backend": "fastembed-onnx-cpu",
                "max_tokens_per_text": 512,
                "encoding": "unprefixed-normalized-cls",
                "requests": requests,
                "texts_embedded": texts_embedded,
            }

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        return {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "BAAI"}]}

    @app.post("/v1/embeddings")
    def embeddings(item: EmbeddingInput) -> dict[str, Any]:
        nonlocal requests, texts_embedded
        if item.model != MODEL:
            raise HTTPException(400, "embedding model does not match this server")
        texts = [item.input] if isinstance(item.input, str) else item.input
        if any(not text.strip() for text in texts):
            raise HTTPException(422, "embedding input cannot be blank")
        with lock:
            try:
                vectors = encode(texts)
                if len(vectors) != len(texts) or any(
                    len(vector) != DIMENSIONS
                    or not all(math.isfinite(value) for value in vector)
                    or not any(value != 0 for value in vector)
                    for vector in vectors
                ):
                    raise ValueError("invalid embedding result")
            except Exception:
                # No input text or backend exception details in API errors or logs.
                raise HTTPException(503, "local embedding inference failed") from None
            requests += 1
            texts_embedded += len(texts)
        return {
            "object": "list",
            "model": MODEL,
            "data": [
                {"object": "embedding", "index": index, "embedding": vector}
                for index, vector in enumerate(vectors)
            ],
        }

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--cache-dir", type=Path, default=Path(".agent-data/embeddings"))
    parser.add_argument("--runtime-dir", type=Path, default=None)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not 1 <= args.threads <= 32:
        parser.error("port must be 1..65535 and threads must be 1..32")
    encoder = load_encoder(args.cache_dir, args.threads, args.runtime_dir)
    uvicorn.run(create_embedding_app(encoder), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
