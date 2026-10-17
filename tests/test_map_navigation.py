"""Map contracts use generated fixtures, never real provider credentials or locations."""
import asyncio
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.services import map_navigation as nav
from app.services.geometry import length
from app.services.session import new_state, SessionStore

A, B = [32.15, 118.96], [32.151, 118.961]


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.state = new_state("map-unit")
        self.state["prefs"]["map_mode"] = "real"
        self.pending = nav.start_route(self.state, A, B)
        self.payload = {"geometry": [A, B], "steps": [{"instruction": "fixture", "at_m": length([A, B])}],
                        "duration_min": 3, "name": "fixture"}

    def commit(self):
        return nav.commit_route(self.state, self.pending["request_id"], self.payload)

    def sample(self, **kwargs):
        self.state.setdefault("_nav", {"token": "fixture", "sequence": -1})
        return nav.location_sample(self.state, {"token": "fixture", "sequence": 1, "lat": A[0], "lng": A[1],
              "raw_wgs84": A, "sample_at": time.time(), "accuracy_m": 10, **kwargs})

    def test_complete_geometry_not_preset(self):
        route = self.commit()
        self.assertEqual(route["geometry"], [A, B])
        self.assertEqual(route["coordinate_system"], "GCJ-02")
        self.assertFalse(route["constraints"]["weather_applied"])

    def test_old_route_never_replaces_new(self):
        nav.start_route(self.state, B, A)
        with self.assertRaises(LookupError):
            self.commit()

    def test_expired_pending(self):
        self.pending["created_at"] -= 91
        with self.assertRaises(LookupError): self.commit()

    def test_polling_expires_abandoned_pending(self):
        self.pending["created_at"]-=91
        nav.navigation_view(self.state)
        self.assertEqual(self.state["route"]["status"],"no_path")

    def test_invalid_geometry_atomic(self):
        self.payload["geometry"] = [[32.17, 118.97], B]
        with self.assertRaises(ValueError): self.commit()
        self.assertEqual(self.state["route"]["status"], "pending")

    def test_gap_rejected(self):
        self.payload["geometry"] = [A, [32.18, 118.98], B]
        with self.assertRaises(ValueError): self.commit()

    def test_no_provider_result_never_fabricates_path(self):
        out = nav.commit_route(self.state, self.pending["request_id"], {"error": True})
        self.assertEqual(out["status"], "no_path")
        self.assertNotIn("geometry", out)

    def test_unknown_or_reversed_coordinates_rejected(self):
        for point in ([118.96, 32.15], [float("nan"), 118.96], [True, 118.96], [31, 119]):
            with self.assertRaises(ValueError): nav.coordinate(point)

    def test_low_accuracy_does_not_progress(self):
        self.commit(); self.sample(accuracy_m=500)
        self.assertFalse(nav.navigation_view(self.state)["eligible"])
        self.assertEqual(self.state["route"]["progress_m"], 0)

    def test_good_sample_progress_and_stale_pause(self):
        self.commit(); self.sample()
        self.assertTrue(nav.navigation_view(self.state)["eligible"])
        self.assertFalse(nav.navigation_view(self.state, time.time()+16)["eligible"])

    def test_stop_token_rejects_late_sample(self):
        self.sample(); nav.stop(self.state)
        with self.assertRaises(LookupError):
            nav.location_sample(self.state, {"token": "fixture", "sequence": 2})

    def test_sequence_and_timestamp_order(self):
        self.sample()
        with self.assertRaises(LookupError): self.sample()
        with self.assertRaises(LookupError): self.sample(sequence=2, sample_at=time.time()-1)

    def test_stale_and_future_rejected(self):
        for offset in (-31, 6):
            with self.assertRaises(ValueError): self.sample(sample_at=time.time()+offset)

    def test_jump_does_not_replace_baseline(self):
        self.sample(sample_at=time.time()-1)
        result=self.sample(sequence=2, lat=32.17, lng=118.98, raw_wgs84=[32.17,118.98])
        self.assertFalse(result["accepted"])
        self.assertEqual(self.state["location"]["lat"], A[0])
        self.assertFalse(nav.quality(self.state))

    def test_manual_point_is_never_device(self):
        self.commit(); self.state["location"]={"source":"manual","lat":A[0],"lng":A[1]}
        self.assertFalse(nav.navigation_view(self.state)["eligible"])

    def test_projection_at_end_not_proof_of_arrival(self):
        self.commit()
        self.sample(lat=B[0]+.0001, lng=B[1]+.0001, raw_wgs84=[B[0]+.0001,B[1]+.0001], accuracy_m=25)
        view=nav.navigation_view(self.state)
        self.assertNotEqual(view["status"], "destination_nearby")

    def test_external_data_not_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            store=SessionStore(Path(temp)/"s.db"); state=store.get("s")
            state.update(self.state); state["session_id"]="s"
            state["route"]={"provider":"amap","geometry":[A,B]}
            state["location"]={"coordinate_system":"GCJ-02","lat":A[0]}
            state["_map_pois"]={"private":"fixture"}
            store.save(state)
            restored=SessionStore(Path(temp)/"s.db").get("s")
            self.assertIsNone(restored["route"]);self.assertIsNone(restored["location"])
            self.assertNotIn("_map_pois",restored)
            self.assertIsNotNone(state["route"])

    def test_structured_coordinates_scrubbed_from_tool_history(self):
        with tempfile.TemporaryDirectory() as temp:
            store=SessionStore(Path(temp)/"s.db");state=store.get("s")
            state["history"]=[{"role":"tool","content":json.dumps({"lat":32.15,"lng":118.96,"source":"device","nested":{"geometry":[A,B]}})}]
            state["tool_results"]={"x":{"raw_wgs84":A,"message":"ok"}}
            store.save(state)
            restored=SessionStore(Path(temp)/"s.db").get("s")
            self.assertNotIn("lat",json.loads(restored["history"][0]["content"]))
            self.assertNotIn("geometry",json.loads(restored["history"][0]["content"])["nested"])
            self.assertNotIn("raw_wgs84",restored["tool_results"]["x"])
            self.assertIn("lat",json.loads(state["history"][0]["content"]))

    def test_llm_real_mode_requests_browser_not_draft(self):
        from app.services.route import RouteService
        result=RouteService(Path(__file__).parents[1]/"app/data").plan(self.state,"qixiasi")
        self.assertEqual(result["status"],"pending_browser")
        self.assertIsNone(self.state["route"])


class MapAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app.main as main
        cls.main=main
        cls.client=TestClient(main.app,base_url="http://127.0.0.1")

    def setUp(self):
        self.sid="api-map-"+__import__("uuid").uuid4().hex
        self.base={"session_id":self.sid,"generation":0}
        self.client.post("/api/map/mode",json={**self.base,"mode":"real"})

    def start(self, sequence=1):
        r=self.client.post("/api/map/route/start",json={**self.base,"origin":A,"destination":B,"sequence":sequence})
        self.assertEqual(r.status_code,200);return r.json()

    def test_start_sequence_prevents_reordered_network_requests(self):
        self.start(2)
        r=self.client.post("/api/map/route/start",json={**self.base,"origin":A,"destination":B,"sequence":1})
        self.assertEqual(r.status_code,409)

    def test_cancel_old_ticket_does_not_cancel_new_route(self):
        old=self.start(1);current=self.start(2)
        self.assertEqual(self.client.post("/api/map/route/cancel",json={**self.base,"request_id":old["request_id"]}).status_code,200)
        self.assertEqual(self.main.sessions.get(self.sid)["route"]["request_id"],current["request_id"])
        self.client.post("/api/map/route/cancel",json={**self.base,"request_id":current["request_id"]})
        self.assertIsNone(self.main.sessions.get(self.sid)["route"])

    def test_cross_site_script_requests_cannot_borrow_map_proxy(self):
        self.assertEqual(self.client.get("/api/map/config",headers={"sec-fetch-site":"cross-site"}).status_code,403)

    def test_generation_reset_cannot_restore_route(self):
        ticket=self.start();self.client.post("/api/demo/reset",json=self.base)
        r=self.client.post("/api/map/route/commit",json={**self.base,"request_id":ticket["request_id"],"error":True})
        self.assertEqual(r.status_code,409)

    def test_proxy_not_open_redirect_or_arbitrary_url(self):
        for path in ("https://example.com", "v3/ip", "v3/not-supported"):
            self.assertEqual(self.client.get("/_AMapService/"+path).status_code,403)

    def test_security_code_never_returned(self):
        with patch.dict(self.main.cfg,{"amap_js_key":"fake-js","amap_security_code":"fake-secret"}):
            response=self.client.get("/api/map/config")
            self.assertNotIn("fake-secret",response.text)
            self.assertTrue(response.json()["configured"])

    def test_nan_and_unknown_crs_rejected(self):
        token=self.client.post("/api/map/location/start",json=self.base).json()["token"]
        body={**self.base,"token":token,"sequence":1,"lat":A[0],"lng":A[1],"raw_wgs84":A,
              "coordinate_system":"WGS84","accuracy_m":10,"sample_at":time.time()}
        self.assertEqual(self.client.post("/api/map/location",json=body).status_code,422)

    def test_facility_preview_is_nonwriting_and_validates(self):
        item={"id":"wc_fixture","name":"fixture","lat":A[0],"lng":A[1],"coordinate_system":"GCJ-02","source":"test","verified_at":"2026-10-17"}
        self.assertEqual(self.client.post("/api/map/facilities/preview",json={"items":[item]}).status_code,200)
        self.assertEqual(self.client.post("/api/map/facilities/preview",json={"items":[item,item]}).status_code,422)
        self.assertEqual(self.client.post("/api/map/facilities/preview",json={"items":[{**item,"coordinate_system":"UNKNOWN"}]}).status_code,422)

    def test_polling_no_fake_real_arrival(self):
        response=self.client.get("/api/state",params={"session_id":self.sid}).json()
        self.assertEqual(response["location"]["source"],"unavailable")
        self.assertIsNone(response["arrived"])
        self.assertFalse(response["navigation"]["eligible"])

    def test_old_stop_cannot_stop_new_watcher(self):
        old=self.client.post("/api/map/location/start",json=self.base).json()["token"]
        current=self.client.post("/api/map/location/start",json=self.base).json()["token"]
        self.assertNotEqual(old,current)
        response=self.client.post("/api/map/stop",json={**self.base,"token":old})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.main.sessions.get(self.sid)["_nav"]["token"],current)

    def test_stop_does_not_wait_for_chat_write_lock(self):
        import httpx
        state=self.main.sessions.get(self.sid);state["_nav"]={"token":"fixture","sequence":0}
        async def test():
            async with self.main.sessions.lock(self.sid):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.main.app),base_url="http://127.0.0.1") as client:
                    response=await asyncio.wait_for(client.post("/api/map/stop",json={**self.base,"token":"fixture"}),.3)
                self.assertTrue(response.json()["stopped"])
                self.assertNotIn("_nav",state)
        asyncio.run(test())

    def test_plan_reports_busy_instead_of_queued_late_write(self):
        import httpx
        async def test():
            async with self.main.sessions.lock(self.sid):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.main.app),base_url="http://127.0.0.1") as client:
                    response=await asyncio.wait_for(client.post("/api/map/route/start",json={**self.base,"origin":A,"destination":B,"sequence":1}),.3)
                self.assertEqual(response.status_code,409)
                self.assertIn("取消回答",response.json()["detail"])
                self.assertIsNone(self.main.sessions.get(self.sid)["route"])
        asyncio.run(test())

    def test_real_arrival_needs_new_sample_not_only_polling(self):
        state=self.main.sessions.get(self.sid)
        state["_nav"]={"token":"fixture","sequence":1}
        state["_map_pois"]={"qixiasi":{"coord":A}}
        state["location"]={"source":"device","coordinate_system":"GCJ-02","lat":A[0],"lng":A[1],"accuracy_m":10,"sample_at":time.time(),"snapped":{"poi_id":"qixiasi"}}
        with patch.object(nav,"quality",return_value=True):
            self.assertIsNone(self.main._sync_arrival(state,now=10))
            self.assertIsNone(self.main._sync_arrival(state,now=19))
            state["location"]["sample_at"]+=9
            self.assertIsNotNone(self.main._sync_arrival(state,now=19))

    def test_proxy_injects_only_server_credential(self):
        import httpx
        seen=[]
        def handler(request):
            seen.append(request)
            return httpx.Response(200,json={"status":"1"})
        provider=self.main.services["provider"]
        old=provider.maps
        provider.maps=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with patch.dict(self.main.cfg,{"amap_js_key":"fixture-js","amap_security_code":"fixture-secret"}):
                response=self.client.get("/_AMapService/v3/place/text?key=fixture-js&jscode=evil&keywords=test")
                self.assertEqual(response.status_code,200)
                self.assertEqual(seen[0].url.params["jscode"],"fixture-secret")
                self.assertEqual(seen[0].url.host,"restapi.amap.com")
                self.assertNotIn("fixture-secret",response.text)
                self.assertEqual(self.client.get("/_AMapService/v3/place/text?key=other").status_code,403)
        finally:
            asyncio.run(provider.maps.aclose());provider.maps=old


if __name__=="__main__": unittest.main()
