"""Launch the real application with an isolated, explicitly fictional art collection."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from datetime import date
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from companion_agent.app import RomanceHost, create_app
from companion_agent.credentials import CredentialStore
from companion_agent.journal import MomentInput
from companion_agent.nook_art import NookDesign, PixelArt
from companion_agent.romance import RomanceSettings, SettingsUpdate

MARKER = "xinyu-curated-showcase.json"


def collection() -> list[dict[str, Any]]:
    resource = files("companion_agent").joinpath("showcase_assets/nook/collection.json")
    items: list[dict[str, Any]] = json.loads(resource.read_text(encoding="utf-8"))["items"]
    return items


def seed_collection(host: RomanceHost) -> None:
    """Use normal journal/source/version storage, without fabricated chat replies."""
    conversation = host.conversations()[0]["id"]
    with host.database.atomic() as db:
        db.execute(
            "UPDATE romance_conversations SET title=? WHERE id=?",
            ("一起布置小窝 · 精选作品", conversation),
        )
        for item in collection():
            resource = files("companion_agent").joinpath("showcase_assets/nook", item["image"])
            image = host.images.upload("moment", resource.read_bytes())
            entry = host.journal.moment(
                MomentInput(
                    request_id="curated-" + item["id"],
                    conversation_id=conversation,
                    title=item["title"],
                    content="共同创作的小窝作品：" + item["meaning"] + "这是故事里的创作。",
                    happened_on=date.fromisoformat(item["created_on"]),
                    reality_layer="roleplay",
                    image_ids=[image["id"]],
                )
            )
            # The explicit journal source carries a conversation link; the memory
            # reference also invalidates the derivative when that memory is removed.
            refs = ["memory:" + entry["id"], "turn:" + entry["evidence_turn_ids"][0]]
            sources = [host.nook.source(ref) for ref in refs]
            host.nook.commit(
                NookDesign(
                    title=item["title"],
                    meaning=item["meaning"],
                    sources=refs,
                    reality_layer="roleplay",
                    zone=item["zone"],
                    slot=item["slot"],
                    art=PixelArt.model_validate(item["art"]),
                ),
                sources,
                {s["ref"]: s["fingerprint"] for s in sources},
                host.nook.room()["items"],
                drawing=item["drawing"],
            )
        for item in host.nook.room()["items"]:
            host.nook.cherish(item["id"], True)


def showcase_app(directory: Path, *, online: bool = False) -> FastAPI:
    directory = directory.resolve()
    marker = directory / MARKER
    if directory.exists() and any(directory.iterdir()) and not marker.is_file():
        raise ValueError("Showcase requires an empty directory or an existing marked showcase.")
    if marker.is_file() and json.loads(marker.read_text(encoding="utf-8")) != {
        "kind": "curated-fictional-showcase",
        "version": 1,
    }:
        raise ValueError("Unrecognized showcase marker.")
    fresh = not marker.exists()
    directory.mkdir(parents=True, exist_ok=True)
    app = create_app(
        directory,
        credentials=CredentialStore(directory, enabled=False),
        background_services=False,
    )
    host = app.state.host
    if fresh:
        host.save_settings(
            SettingsUpdate(
                settings=RomanceSettings(
                    storage_consent=True,
                    model_consent=True,
                    romance_consent=True,
                    nook_enabled=False,
                )
            )
        )
        seed_collection(host)
        marker.write_text(
            json.dumps({"kind": "curated-fictional-showcase", "version": 1}), encoding="utf-8"
        )
    settings = host.settings.model_copy(update={"model_mode": "api" if online else "offline"})
    host.save_settings(SettingsUpdate(settings=settings))
    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Open XinYu with the reviewed nook collection.")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--api", action="store_true", help="Use DEEPSEEK_API_KEY for chat.")
    parser.add_argument("--prompt-key", action="store_true", help="Read a key without echoing it.")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.prompt_key:
        os.environ["DEEPSEEK_API_KEY"] = getpass.getpass("DeepSeek API key (hidden): ").strip()
    if args.api and not os.environ.get("DEEPSEEK_API_KEY"):
        parser.error("API mode requires an environment credential.")
    app = showcase_app(args.data_dir, online=args.api)
    print(f"XinYu curated collection: http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
