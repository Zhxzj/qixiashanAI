import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from app.services.places import PlaceService
from app.services.osm_map import OSMMapService

ROOT = Path(__file__).resolve().parents[1]


class PlaceDetailsTests(unittest.TestCase):
    def setUp(self):
        self.service = PlaceService(ROOT / "app/data")

    def test_catalog_filters_surrounding_objects_without_losing_them(self):
        self.assertEqual(len(self.service.catalog()["items"]), 16)
        names = {x["name"] for x in self.service.catalog(True)["items"]}
        self.assertEqual(len(names), 9)
        self.assertTrue({"栖霞寺", "千佛岩", "凤翔峰"} <= names)
        self.assertFalse({"何家山", "九乡河", "读枫"} & names)

    def test_curated_content_limits_and_independent_missing_states(self):
        reviewed = [p for p in self.service.items.values() if p["status"] == "reviewed"]
        self.assertEqual(len(reviewed), 3)
        for p in reviewed:
            self.assertLessEqual(len("".join(p["detail"].split())), 200)
            self.assertTrue(p["sources"])
            self.assertNotIn(p["summary"], p["detail"])
        peak = self.service.detail("qxs-fengxiangfeng")
        self.assertEqual(peak["status"], "reviewed")
        self.assertIsNone(peak["photo"])
        self.assertIsNone(self.service.detail("../../config.json"))

    def test_photo_identity_license_and_shipped_bytes(self):
        photos = [p["photo"] for p in self.service.items.values() if p["photo"]]
        self.assertEqual(len(photos), 2)
        for photo in photos:
            self.assertEqual(photo["license"], "CC BY-SA 3.0")
            self.assertEqual(photo["author"], "Farm")
            self.assertTrue(photo["historical"])
            self.assertNotIn("samples", photo["src"])
            image = ROOT / "web" / photo["src"].lstrip("/")
            self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), photo["sha256"])

    def test_candidates_never_create_geographic_nodes_or_edges(self):
        review = self.service.review
        self.assertEqual(len(review["toilets"]), 14)
        self.assertFalse(review["source"]["coordinate_extraction"])
        for candidate in review["toilets"]:
            self.assertIsNone(candidate["coord"])
            self.assertFalse(candidate["navigation_allowed"])
        for road in review["roads"]:
            self.assertIsNone(road["geometry"])
            self.assertFalse(road["navigation_allowed"])
        osm = OSMMapService(ROOT / "app/data")
        self.assertEqual(len(osm.data["roads"]), 225)
        self.assertEqual(sum(x["category"] == "toilet_candidate" for x in osm.pois.values()), 3)

    def test_stale_graph_stops_navigation_without_inventing_path(self):
        osm = OSMMapService(ROOT / "app/data")
        state = {"route": {"provider": "osm", "status": "ready", "data_version": "old"}, "_nav": {"token": "old"}}
        self.assertFalse(osm.ensure_route_version(state))
        self.assertNotIn("_nav", state)
        self.assertEqual(state["route"]["error"]["code"], "stale_graph")

    def test_oversized_detail_rejected_at_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for name in ("map_places.json", "place_content.json", "map_review.json"):
                (target / name).write_bytes((ROOT / "app/data" / name).read_bytes())
            p = target / "place_content.json"
            data = json.loads(p.read_text(encoding="utf-8"))
            data["items"]["qxs-qixiasi"]["detail"] = "字" * 201
            p.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                PlaceService(target)

    def test_http_readonly_api_missing_id_and_source_no_runtime_model(self):
        import app.main as main
        client = TestClient(main.app, base_url="http://127.0.0.1")
        self.assertEqual(len(client.get("/api/map/places?major=true").json()["items"]), 9)
        self.assertEqual(client.get("/api/map/place", params={"place_id": "missing"}).status_code, 404)
        result = client.get("/api/map/place?place_id=qxs-qixiasi")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["photo"]["author"], "Farm")
        self.assertEqual(client.get("/api/map/review").json()["approved_new_toilets"], 0)
        photo = result.json()["photo"]
        self.assertEqual(hashlib.sha256(client.get(photo["src"]).content).hexdigest(), photo["sha256"])

    def test_toilet_access_claim_requires_source_and_real_graph_connection(self):
        import app.main as main
        client = TestClient(main.app, base_url="http://127.0.0.1")
        item = {"id": "checked", "name": "测试设施", "lat": 32.15385, "lng": 118.95503,
                "coordinate_system": "WGS84", "source": "用户资料", "verified_at": "2026-10-18"}
        self.assertEqual(client.post("/api/map/facilities/preview", json={"items": [item]}).status_code, 200)
        item["access_verified"] = True
        self.assertEqual(client.post("/api/map/facilities/preview", json={"items": [item]}).status_code, 422)
        item.update(access_source="待现场签收的接入证据", entrance_coord=main.services["osm"].data["roads"][0]["geometry"][0])
        self.assertEqual(client.post("/api/map/facilities/preview", json={"items": [item]}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
