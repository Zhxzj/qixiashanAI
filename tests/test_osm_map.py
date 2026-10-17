"""Real bundled OSM graph + synthetic topology/access controls. No external service."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from app.services.osm_map import OSMMapService
from app.services import map_navigation as nav
from app.services.geometry import length
from app.services.session import new_state,SessionStore
from scripts.build_osm_data import permitted

DATA=Path(__file__).parents[1]/"app/data"


class OSMGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.osm=OSMMapService(DATA)
    def poi(self,name):return self.osm.resolve(name)

    def test_real_temple_cliff_uses_known_edges(self):
        a,b=self.poi("栖霞寺"),self.poi("千佛岩")
        route=self.osm.plan(a["coord"],b["coord"])
        self.assertGreater(len(route["geometry"]),5)
        self.assertGreater(length(route["geometry"]),100)
        self.assertTrue(route["way_ids"])
        self.assertEqual(route["data_version"],self.osm.data["graph_sha256"])

    def test_real_core_scenic_routes_connected(self):
        start=self.poi("千佛岩")["coord"]
        for name in ("凤翔峰","碧云亭","德云亭","桃花扇亭","栖霞寺"):
            route=self.osm.plan(start,self.poi(name)["coord"])
            self.assertGreater(length(route["geometry"]),2,name)
            self.assertAlmostEqual(route["steps"][-1]["at_m"],length(route["geometry"]),places=3)

    def test_via_reverse_and_no_missing_connections(self):
        a,b,c=[self.poi(n)["coord"] for n in ("栖霞寺","千佛岩","碧云亭")]
        via=self.osm.plan(a,c,[b]);reverse=self.osm.plan(c,a,[b])
        self.assertAlmostEqual(length(via["geometry"]),length(reverse["geometry"]),delta=.5)
        self.assertGreater(length(via["geometry"]),length(self.osm.plan(a,b)["geometry"]))

    def test_remote_manual_point_rejected(self):
        with self.assertRaises(ValueError):self.osm.plan([32.136,118.945],self.poi("千佛岩")["coord"])

    def test_unknown_name_not_replaced_with_draft(self):
        with self.assertRaises(ValueError):self.osm.resolve("不存在的图片景点")

    def test_reference_photo_never_supplies_coordinates(self):
        references=self.osm.public_data()["photo_reference"]
        self.assertFalse(references["coordinate_extraction"])
        missing=next(r for r in references["items"] if r["photo_name"]=="虎山瀑布")
        self.assertIsNone(missing["osm_id"])
        different=next(r for r in references["items"] if r["photo_name"]=="读枫阁")
        self.assertEqual(different["status"],"name_difference")

    def test_access_exclusions(self):
        for tags in ({"highway":"motorway"},{"highway":"path","foot":"no"},{"highway":"path","access":"private"},{"highway":"construction"},{"highway":"path","foot:conditional":"no @ rain"}):
            self.assertFalse(permitted(tags))
        self.assertTrue(permitted({"highway":"path","access":"private","foot":"designated"}))

    def fixture(self,nodes,roads):
        obj=object.__new__(OSMMapService);obj.nodes=nodes;obj.data={"graph_sha256":"fixture"};obj.segments=[]
        for index,r in enumerate(roads):
            road={"id":str(index),"osm_id":"way/"+str(index),"tags":r.get("tags",{}),"highway":r.get("highway","path"),"name":""}
            for i,(a,b) in enumerate(zip(r["nodes"],r["nodes"][1:])):obj.segments.append((road,i,a,b))
        return obj

    def test_crossing_lines_do_not_connect_without_shared_node(self):
        nodes={"a":[32.15,118.96],"b":[32.151,118.961],"c":[32.15,118.961],"d":[32.151,118.96]}
        obj=self.fixture(nodes,[{"nodes":["a","b"]},{"nodes":["c","d"]}])
        with self.assertRaises(ValueError):obj.plan(nodes["a"],nodes["d"])

    def test_same_edge_route_not_detour_via_endpoints(self):
        nodes={"a":[32.15,118.96],"b":[32.152,118.96]}
        obj=self.fixture(nodes,[{"nodes":["a","b"]}])
        route=obj.plan([32.1505,118.96],[32.1515,118.96])
        self.assertAlmostEqual(length(route["geometry"]),111.2,delta=.5)

    def test_oneway_foot_and_avoid_steps(self):
        nodes={"a":[32.15,118.96],"b":[32.152,118.96]}
        obj=self.fixture(nodes,[{"nodes":["a","b"],"tags":{"oneway:foot":"yes"}}])
        self.assertGreater(length(obj.plan(nodes["a"],nodes["b"])["geometry"]),100)
        with self.assertRaises(ValueError):obj.plan(nodes["b"],nodes["a"])
        stairs=self.fixture(nodes,[{"nodes":["a","b"],"highway":"steps"}])
        with self.assertRaises(ValueError):stairs.plan(nodes["a"],nodes["b"],avoid_steps=True)

    def test_nearest_known_road_does_not_add_connector_line(self):
        p=self.poi("千佛岩")["coord"];q=self.poi("栖霞寺")["coord"]
        route=self.osm.plan(p,q)
        self.assertNotEqual(route["geometry"][0],p)
        self.assertTrue(route["access_notes"])


class OSMAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app.main as main
        cls.main=main;cls.client=TestClient(main.app,base_url="http://127.0.0.1")

    def setUp(self):
        self.sid="osm-"+__import__("uuid").uuid4().hex
        self.body={"session_id":self.sid,"generation":0}
        self.client.post("/api/map/mode",json={**self.body,"mode":"real","provider":"osm"})
        self.osm=self.main.services["osm"]
        self.a=self.osm.resolve("千佛岩")["coord"];self.b=self.osm.resolve("碧云亭")["coord"]

    def plan(self,seq=1):return self.client.post("/api/map/osm/plan",json={**self.body,"sequence":seq,"origin":self.a,"destination":self.b,"name":"碧云亭"})

    def test_no_map_key_route_ready_wgs84(self):
        result=self.plan();self.assertEqual(result.status_code,200)
        route=result.json();self.assertEqual(route["provider"],"osm");self.assertEqual(route["coordinate_system"],"WGS84")
        st=self.client.get("/api/state",params={"session_id":self.sid}).json()
        self.assertEqual(st["route"]["geometry"],route["geometry"])
        self.assertFalse(st["navigation"]["eligible"])

    def test_raw_browser_wgs84_never_shifted(self):
        self.plan();token=self.client.post("/api/map/location/start",json=self.body).json()["token"]
        sample={**self.body,"token":token,"sequence":1,"lat":self.a[0],"lng":self.a[1],"coordinate_system":"WGS84","raw_wgs84":self.a,"accuracy_m":10,"sample_at":time.time()}
        self.assertEqual(self.client.post("/api/map/location",json=sample).status_code,200)
        loc=self.client.get("/api/state",params={"session_id":self.sid}).json()["location"]
        self.assertEqual([loc["lat"],loc["lng"]],self.a)
        self.assertEqual(self.client.post("/api/map/location",json={**sample,"sequence":2,"coordinate_system":"GCJ-02"}).status_code,422)
        self.assertEqual(self.client.post("/api/map/location",json={**sample,"sequence":2,"lat":self.a[0]+.001,"sample_at":time.time()}).status_code,422)

    def test_reset_preserves_osm_and_has_no_fake_position(self):
        self.plan();self.client.post("/api/demo/reset",json=self.body)
        st=self.client.get("/api/state",params={"session_id":self.sid}).json()
        self.assertEqual(st["map_provider"],"osm");self.assertEqual(st["location"]["source"],"unavailable");self.assertIsNone(st["route"])

    def test_model_tool_uses_same_local_route_and_no_browser_wait(self):
        self.plan();state=self.main.sessions.get(self.sid)
        result=self.osm.plan_for_state(state,"栖霞寺",[],self.main.services["location"].pois)
        self.assertEqual(result["status"],"ready");self.assertNotIn("geometry",result)
        self.assertEqual(state["route"]["provider"],"osm")

    def test_old_route_sequence_rejected(self):
        self.assertEqual(self.plan(2).status_code,200);self.assertEqual(self.plan(1).status_code,409)

    def test_osm_rejects_legacy_uploaded_geometry(self):
        start={**self.body,"sequence":1,"origin":self.a,"destination":self.b}
        self.assertEqual(self.client.post("/api/map/route/start",json=start).status_code,409)
        commit={**self.body,"request_id":"external","geometry":[self.a,self.b]}
        self.assertEqual(self.client.post("/api/map/route/commit",json=commit).status_code,409)

    def test_data_license_and_source_are_available(self):
        data=self.client.get("/api/map/osm/data").json()
        self.assertEqual(data["license"],"ODbL-1.0");self.assertEqual(data["coordinate_system"],"WGS84")
        self.assertGreater(len(data["roads"]),10)
        self.assertEqual(self.client.get("/api/map/osm/source").status_code,200)
        self.assertEqual(self.client.get("/api/map/osm/database").status_code,200)

    def test_wgs84_device_position_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            store=SessionStore(Path(d)/"s.db");s=store.get("s");s["location"]={"source":"device","coordinate_system":"WGS84","lat":32.15,"lng":118.96};s["route"]={"provider":"osm","geometry":[self.a,self.b]};store.save(s)
            self.assertIsNone(SessionStore(Path(d)/"s.db").get("s")["location"])
            self.assertIsNone(SessionStore(Path(d)/"s.db").get("s")["route"])


if __name__=="__main__":unittest.main()
