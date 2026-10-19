"""Local, curated place content. No model calls or runtime source fetching."""
import copy
import json
from pathlib import Path


class PlaceService:
    def __init__(self, data_dir):
        root = Path(data_dir)
        catalog = json.loads((root / "map_places.json").read_text(encoding="utf-8"))
        content = json.loads((root / "place_content.json").read_text(encoding="utf-8"))
        self.version = catalog["version"] + ":" + content["version"]
        self.items = {}
        for place in catalog["items"]:
            item = {**place, **content["items"][place["place_id"]], "content_version": self.version}
            if len("".join(item["detail"].split())) > 200:
                raise ValueError("景点详细介绍超过200字：" + item["name"])
            self.items[item["place_id"]] = item
        self.review = json.loads((root / "map_review.json").read_text(encoding="utf-8"))

    def catalog(self, major=False):
        keys = ("place_id", "osm_id", "name", "major", "coord", "position_kind", "status", "content_version", "field_verified")
        return {"version": self.version, "items": [{k: p[k] for k in keys} for p in self.items.values() if not major or p["major"]]}

    def detail(self, place_id):
        item = self.items.get(place_id)
        return copy.deepcopy(item) if item else None
