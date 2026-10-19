import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.services.map_annotations import AnnotationStore, AnnotationConflict
from app.services.osm_map import OSMMapService
from app.services import map_navigation as nav

ROOT = Path(__file__).resolve().parents[1]


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.osm = OSMMapService(ROOT / "app/data")
        self.store = AnnotationStore(ROOT / "app/data/map_annotations.json", Path(self.temp.name)/"positions.json", self.osm.data["bounds"])

    def test_only_twelve_today_points_and_unlocated_gates(self):
        snapshot = self.store.snapshot()
        toilets = [p for p in snapshot["items"] if p["category"] == "toilet"]
        self.assertEqual([p["id"] for p in toilets], [f"toilet_T{i:02}" for i in range(1, 13)])
        self.assertTrue(all(p["position_status"] == "screenshot_approximate" and not p["access_verified"] for p in toilets))
        self.assertEqual(len({p["source"]["image_sha256"] for p in toilets}), 1)
        self.assertTrue(all(p["coord"] is not None for p in snapshot["items"] if p["category"] == "gate"))

    def test_preview_save_restart_reset_and_export(self):
        point = [32.1532, 118.9497]
        preview = self.store.preview("gate_marked_west", point, 0)
        self.assertFalse(self.store.path.exists())
        saved = self.store.save("gate_marked_west", point, 0, preview["expires"], preview["preview_token"])
        self.assertEqual(saved["revision"], 1)
        again = AnnotationStore(ROOT / "app/data/map_annotations.json", self.store.path, self.osm.data["bounds"])
        gate = next(p for p in again.snapshot()["items"] if p["id"] == "gate_marked_west")
        self.assertEqual(gate["coord"], point)
        self.assertFalse(gate["access_verified"])
        self.assertEqual(again.export()["user_data"]["revision"], 1)
        reset = again.reset("gate_marked_west", 1)
        self.assertEqual(next(p for p in reset["items"] if p["id"] == "gate_marked_west")["coord"], self.store.items["gate_marked_west"]["coord"])
        self.assertEqual(len(reset["items"]), 14)

    def test_stale_changed_expired_or_forged_preview_rejected(self):
        point = [32.1532, 118.9497]
        preview = self.store.preview("gate_marked_west", point, 0)
        for coords, expires, token in [(point, 0, preview["preview_token"]), ([32.154, 118.95], preview["expires"], preview["preview_token"]), (point, preview["expires"], "0"*64)]:
            with self.assertRaises(AnnotationConflict):
                self.store.save("gate_marked_west", coords, 0, expires, token)
        self.store.save("gate_marked_west", point, 0, preview["expires"], preview["preview_token"])
        with self.assertRaises(AnnotationConflict):
            self.store.save("gate_marked_west", point, 0, preview["expires"], preview["preview_token"])

    def test_duplicate_content_does_not_increment_and_unknown_row_preserved(self):
        p = self.store.preview("gate_marked_west", [32.1532, 118.9497], 0)
        self.store.save(p["id"], p["coord"], p["revision"], p["expires"], p["preview_token"])
        data = json.loads(self.store.path.read_text())
        data["overrides"]["future_gate"] = {"anything": "preserved"}
        self.store.path.write_text(json.dumps(data))
        p = self.store.preview("gate_marked_west", [32.1532, 118.9497], 1)
        self.assertEqual(self.store.save(p["id"], p["coord"], p["revision"], p["expires"], p["preview_token"])["revision"], 1)
        self.store.reset("gate_marked_west", 1)
        self.assertIn("future_gate", self.store.export()["user_data"]["overrides"])

    def test_corrupt_file_never_overwritten(self):
        self.store.path.write_text("BROKEN")
        self.assertFalse(self.store.snapshot()["writable"])
        with self.assertRaises(AnnotationConflict):
            self.store.reset("gate_marked_west", 0)
        self.assertEqual(self.store.path.read_text(), "BROKEN")

    def test_failed_atomic_replace_keeps_previous_data(self):
        p = self.store.preview("gate_marked_west", [32.1532, 118.9497], 0)
        with patch("app.services.map_annotations.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.store.save(p["id"], p["coord"], p["revision"], p["expires"], p["preview_token"])
        self.assertFalse(self.store.path.exists())
        self.assertEqual(list(self.store.path.parent.glob("*.tmp")), [])

    def test_route_targets_validate_identity_and_revision(self):
        p = self.store.snapshot()["items"][0]
        entry = {"id":p["id"], "role":"destination", "position_revision":p["position_revision"]}
        target = self.store.targets([entry], {"destination":p["coord"]})[0]
        self.assertFalse(target["access_verified"])
        for entries, coords in [([entry, entry], {"destination":p["coord"]}), ([entry], {"destination":[32.154,118.95]})]:
            with self.assertRaises(ValueError): self.store.targets(entries, coords)
        state = {"route":{"status":"ready","annotation_targets":[target]},"_nav":{"token":"x"}}
        self.assertTrue(self.store.ensure_route_version(state))
        preview = self.store.preview(p["id"], [32.154,118.95], 0)
        self.store.save(preview["id"],preview["coord"],0,preview["expires"],preview["preview_token"])
        self.assertFalse(self.store.ensure_route_version(state))
        self.assertNotIn("_nav",state)

    def test_road_endpoint_nearby_is_never_facility_arrival(self):
        start, end = [32.154,118.955], [32.155,118.955]
        state = {"prefs":{"map_mode":"real","map_provider":"osm"}, "_nav":{"token":"x"},
                 "location":{"source":"device","coordinate_system":"WGS84","navigation_eligible":True,"accuracy_m":5,"sample_at":time.time(),"lat":end[0],"lng":end[1]},
                 "route":{"provider":"osm","status":"ready","geometry":[start,end],"destination":end,"total_m":111,"steps":[{"at_m":111}],"annotation_targets":[{"role":"destination","road_endpoint":end}]}}
        self.assertEqual(nav.navigation_view(state)["status"],"road_endpoint_nearby")


class AnnotationAPITests(unittest.TestCase):
    def setUp(self):
        import app.main as main
        self.main = main
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old_path = main.services["annotations"].path
        main.services["annotations"].path = Path(self.temp.name)/"annotations.json"
        self.addCleanup(setattr, main.services["annotations"], "path", self.old_path)
        self.client = TestClient(main.app, base_url="http://127.0.0.1")

    def test_api_rejects_bad_coord_fields_unknown_id_and_origin(self):
        body = {"id":"gate_marked_west","coord":[32.1532,118.9497],"revision":0}
        for extra in [{"coord":[True,118.95]}, {"coord":[118.95,32.15]}, {"id":"unknown"}, {"access_verified":True}, {"revision":False}]:
            self.assertEqual(self.client.post('/api/map/annotations/preview',json={**body,**extra}).status_code,422)
        self.assertEqual(self.client.post('/api/map/annotations/preview',json=body,headers={"Origin":"https://example.com"}).status_code,403)
        self.assertEqual(self.client.post('/api/map/annotations/preview',content=json.dumps(body),headers={"Content-Type":"text/plain"}).status_code,415)
        self.assertEqual(self.client.post('/api/map/annotations/preview',content=' '*5000,headers={"Content-Type":"application/json"}).status_code,413)

    def test_api_preview_save_export_and_annotation_plan(self):
        snapshot = self.client.get('/api/map/annotations').json()
        p = next(p for p in snapshot["items"] if p["id"] == "toilet_T01")
        session = {"session_id":"annotation-plan","generation":1}
        # Use the existing state generation, without resetting unrelated sessions.
        session["generation"] = self.main.sessions.get(session["session_id"])["generation"]
        self.assertEqual(self.client.post('/api/map/mode',json={**session,"mode":"real","provider":"osm"}).status_code,200)
        origin=self.main.services["osm"].resolve("千佛岩")["coord"]
        target={"id":p["id"],"role":"destination","position_revision":p["position_revision"]}
        response=self.client.post('/api/map/osm/plan',json={**session,"sequence":int(time.time()*1000),"origin":origin,"destination":p["coord"],"annotation_targets":[target]})
        self.assertEqual(response.status_code,200,response.text)
        route=response.json()
        self.assertEqual(route["annotation_targets"][0]["road_endpoint"],route["geometry"][-1])
        self.assertFalse(route["annotation_targets"][0]["access_verified"])
        preview=self.client.post('/api/map/annotations/preview',json={"id":p["id"],"coord":[32.154,118.95],"revision":snapshot["revision"]}).json()
        self.assertEqual(self.client.post('/api/map/annotations/save',json=preview).status_code,200)
        self.assertIn('attachment',self.client.get('/api/map/annotations/export').headers['content-disposition'])
        state=self.client.get('/api/state',params={"session_id":session["session_id"]}).json()
        self.assertEqual(state["route"]["error"]["code"],"stale_annotation")


if __name__ == "__main__": unittest.main()
