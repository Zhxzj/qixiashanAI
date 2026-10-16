"""Behavior regressions for the audited failures; no real credentials or cloud calls."""
import asyncio
import base64
import copy
import io
import json
import os
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PIL import Image
from app.services.session import SessionStore,new_state
from app.services.location import LocationService,dist_m
from app.services.route import RouteService
from app.services.weather import ConditionsService
from app.services.photos import PhotoService
from app.agent.loop import AgentLoop
DATA=ROOT/"app/data"

class DomainTests(unittest.TestCase):
    def setUp(self):
        self.loc=LocationService(DATA)
        self.routes=RouteService(DATA)
        self.state=new_state("test")
        self.loc.ensure(self.state)
    def test_continuous_progress(self):
        start=copy.deepcopy(self.state["location"])
        for _ in range(4):
            self.loc.advance(self.state,10)
        now=self.state["location"]
        self.assertAlmostEqual(dist_m((start["lat"],start["lng"]),(now["lat"],now["lng"])),40,delta=.6)
    def test_reverse(self):
        self.loc.jump_to_poi(self.state,"qianfoyan")
        p=self.routes.plan(self.state,"shanmen")
        self.assertGreater(p["distance_m"],200)
        self.assertEqual(p["geometry"][-1],self.loc.poi("shanmen")["coord"])
        self.assertEqual(p["geometry"][0],self.loc.poi("qianfoyan")["coord"])
    def test_cross_route(self):
        self.loc.jump_to_poi(self.state,"qianfoyan")
        p=self.routes.plan(self.state,"fenglinhu")
        self.assertEqual(p["geometry"][0],self.loc.poi("qianfoyan")["coord"])
        self.assertEqual(p["geometry"][-1],self.loc.poi("fenglinhu")["coord"])
    def test_uncovered_is_error(self):
        p=self.routes.plan(self.state,"fengxiangfeng")
        self.assertEqual(p["status"],"no_path")
        self.assertIsNone(self.state["route"])
    def test_via_and_family(self):
        p=self.routes.plan(self.state,"qixiasi",via=["luyuchazhuang"],theme="family")
        self.assertEqual(p["via"],["luyuchazhuang"])
        self.assertIn(self.loc.poi("luyuchazhuang")["coord"],p["geometry"])
        self.assertEqual(p["theme"],"family")
    def test_midpoint_not_arrival_distance(self):
        xy=self.loc.routes[0]["geometry"][1]
        s=self.loc.snap(*xy)
        self.assertEqual(s["route_distance_m"],0)
        self.assertGreater(s["poi_distance_m"],35)
    def test_persistent_session(self):
        from app.runtime import user_path
        p=user_path("tests/"+uuid.uuid4().hex+".sqlite3")
        store=SessionStore(p)
        st=store.get("s")
        st["memory"].append({"note":"原话"})
        st["photos"]=[{"url":"secret-image"}]
        store.save(st)
        restored=SessionStore(p).get("s")
        self.assertEqual(restored["memory"][0]["note"],"原话")
        self.assertNotIn("photos",restored)

class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sessions=SessionStore()
        self.loc=LocationService(DATA)
        self.services={"location":self.loc,"route":RouteService(DATA)}
        self.agent=AgentLoop({"deepseek_api_key":"fake-not-real"},self.sessions,self.services)
        self.calls=[]
        async def response(msgs,allow_tools=True):
            self.calls.append(copy.deepcopy(msgs))
            yield {"kind":"delta","text":"完整回答"}
            yield {"kind":"done","calls":{},"finish_reason":"stop"}
        self.agent._request_stream=response
    async def collect(self,*args,**kwargs):
        return [ev async for ev in self.agent.stream(*args,**kwargs)]
    async def test_final_assistant_in_followup(self):
        await self.collect("s","第一个问题")
        await self.collect("s","追问")
        self.assertIn({"role":"assistant","content":"完整回答"},self.calls[1])
        self.assertEqual(self.sessions.get("s")["history"][-1]["role"],"assistant")
    async def test_ordering(self):
        events=[]
        async def response(msgs,allow_tools=True):
            text=msgs[-1]["content"]
            events.append(text)
            await asyncio.sleep(.025 if text=="A" else 0)
            yield {"kind":"delta","text":text}
            yield {"kind":"done","calls":{},"finish_reason":"stop"}
        self.agent._request_stream=response
        await asyncio.gather(self.collect("s","A"),self.collect("s","B"))
        self.assertEqual(events,["A","B"])
        self.assertEqual([m["content"] for m in self.sessions.get("s")["history"] if m["role"]=="user"],["A","B"])
    async def test_reset_cancels(self):
        started=asyncio.Event()
        async def response(msgs,allow_tools=True):
            started.set()
            await asyncio.sleep(10)
            yield {"kind":"delta","text":"old"}
        self.agent._request_stream=response
        task=asyncio.create_task(self.collect("s","old"))
        await started.wait()
        self.sessions.reset("s")
        result=await task
        self.assertEqual(result[-1]["status"],"cancelled")
        self.assertEqual(self.sessions.get("s")["history"],[])
    async def test_generation_rejected(self):
        self.sessions.reset("s")
        events=await self.collect("s","old",generation=0)
        self.assertEqual(events[-1]["status"],"cancelled")
        self.assertFalse(self.calls)
    async def test_request_idempotence(self):
        await asyncio.gather(self.collect("s","x",request_id="r"),self.collect("s","x",request_id="r"))
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(self.sessions.get("s")["history"]),2)
    async def test_invalid_memory_not_written(self):
        st=self.sessions.get("s")
        for raw in ('{bad','[]','{"note":123}','{"unknown":"x"}','{}'):
            out=await self.agent._run_tool("save_memory",raw,st)
            self.assertIn("error",out)
        self.assertEqual(st["memory"],[])
    async def test_write_tool_idempotence(self):
        st=self.sessions.get("s")
        for _ in range(2):
            await self.agent._run_tool("save_memory",'{"note":"风凉"}',st,"once")
        self.assertEqual(len(st["memory"]),1)
    async def test_truncation_not_success(self):
        async def response(msgs,allow_tools=True):
            yield {"kind":"delta","text":"partial"}
            yield {"kind":"done","calls":{},"finish_reason":"length"}
        self.agent._request_stream=response
        out=await self.collect("s","q")
        self.assertEqual(out[-1]["status"],"incomplete")
        self.assertEqual(self.sessions.get("s")["history"],[])
        self.assertEqual(self.sessions.get("s")["turns"][-1]["status"],"incomplete")
    async def test_tool_budget_has_final_request(self):
        count=0
        async def response(msgs,allow_tools=True):
            nonlocal count
            count+=1
            if not allow_tools:
                yield {"kind":"delta","text":"完整归纳"}
                yield {"kind":"done","calls":{},"finish_reason":"stop"}
            else:
                yield {"kind":"done","calls":{0:{"id":"","name":"get_location","arguments":"{}"}},"finish_reason":"tool_calls"}
        self.agent._request_stream=response
        out=await self.collect("s","q")
        self.assertEqual(count,7)
        self.assertEqual(out[-1]["status"],"completed")
        history=self.sessions.get("s")["history"]
        calls=[m["tool_calls"][0]["id"] for m in history if "tool_calls" in m]
        results=[m["tool_call_id"] for m in history if m["role"]=="tool"]
        self.assertEqual(calls,results)
    async def test_weather_coalesces_and_failure_cache(self):
        weather=ConditionsService(DATA)
        count=0
        async def fail(days):
            nonlocal count
            count+=1
            await asyncio.sleep(.01)
            raise OSError("offline")
        weather._fetch=fail
        results=await asyncio.gather(*(weather.get(3) for _ in range(4)))
        await weather.get(3)
        self.assertEqual(count,1)
        self.assertEqual(results[0]["kind"],"fallback_not_live")
    async def test_navigation_matches_route(self):
        from app.tools.navigate_hint import run
        st=self.sessions.get("s")
        self.loc.ensure(st)
        p=self.services["route"].plan(st,"shuanghongyuan")
        hint=await run({}, {"state":st,"services":self.services})
        self.assertEqual(hint["remaining_m"],p["distance_m"])
        self.loc.advance(st,5000)
        hint=await run({}, {"state":st,"services":self.services})
        self.assertEqual(hint["remaining_m"],0)
    async def test_empty_and_photo_only_diary(self):
        photos=PhotoService(DATA,{})
        st=new_state("s")
        diary=(await photos.build_recap(st))["diary"]
        self.assertIn("尚未记录行程",diary["paragraphs"][0])
        st["photos"]=[{"id":"p","poi_id":"mingjinghu"}]
        diary=(await photos.build_recap(st))["diary"]
        self.assertEqual(diary["captions"][0]["photo_id"],"p")
        self.assertEqual(diary["captions"][0]["text"],"明镜湖")
        self.assertNotIn("走到","".join(diary["paragraphs"]))
    async def test_vision_invalid_output_keeps_candidates(self):
        service=PhotoService(DATA,{"deepseek_api_key":"fake"})
        buf=io.BytesIO();Image.new("RGB",(800,800),"red").save(buf,format="JPEG")
        async def invalid(*args):
            return {"candidates":[{"poi_id":"qixiasi","score":"high"}]}
        service._vision_pick=invalid
        result=await service.match_photo(buf.getvalue(),allow_cloud=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["mode"],"coarse")
        self.assertTrue(result["candidates"])
    async def test_diary_schema_and_caption_binding(self):
        service=PhotoService(DATA,{})
        st={"photos":[{"id":"p","poi_id":"qixiasi"}]}
        base=service.diary_fallback(st)
        service._validate_diary(base,st)
        for invalid in ({**base,"title":123},{**base,"captions":[{"photo_id":"other","poi_id":"qixiasi","text":"寺"}]}):
            with self.assertRaises(ValueError):
                service._validate_diary(invalid,st)

class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import app.main as main
        cls.main=main
        cls.client=TestClient(main.app,base_url="http://127.0.0.1")
        cls.client.__enter__()
        async def fallback(*args,**kwargs):
            return main.services["weather"]._fallback("offline-test")
        cls.weather_patch=patch.object(main.services["weather"],"get",fallback)
        cls.weather_patch.start()
    @classmethod
    def tearDownClass(cls):
        cls.weather_patch.stop()
        cls.client.__exit__(None,None,None)
    def test_health_identity_and_no_secret(self):
        out=self.client.get("/api/health").json()
        self.assertEqual(out["app_id"],"qixi-guide")
        self.assertEqual(out["api_version"],2)
        self.assertNotIn("deepseek_api_key",out)
    def test_static(self):
        for path in ("/","/poster.html","/js/session.js","/poster/skill/renderer/render.js"):
            self.assertEqual(self.client.get(path).status_code,200,path)
    def test_arrival_real_dwell_and_distance(self):
        st=self.main.sessions.reset("arrival")
        self.main.services["location"].jump_to_poi(st,"qianfoyan")
        self.assertIsNone(self.main._sync_arrival(st,100))
        self.assertIsNone(self.main._sync_arrival(st,107.9))
        ev=self.main._sync_arrival(st,108)
        self.assertEqual(ev["poi_id"],"qianfoyan")
        self.assertIsNone(self.main._sync_arrival(st,120))
        self.assertEqual(st["visited"][-1]["stay_s"],20)
    def test_invalid_payload_and_generation(self):
        self.assertEqual(self.client.post("/api/demo/advance",json={"meters":-1}).status_code,422)
        reset=self.client.post("/api/demo/reset",json={"session_id":"generation"}).json()
        self.assertEqual(self.client.post("/api/demo/advance",json={"session_id":"generation","generation":reset["state"]["generation"]-1}).status_code,409)
    def test_config_failure_is_transactional(self):
        before=dict(self.main.cfg)
        with patch.object(self.main,"save_config",side_effect=OSError("disk full")):
            response=self.client.post("/api/config",json={"deepseek_api_key":"fake-not-real"})
        self.assertEqual(response.status_code,500)
        self.assertEqual(self.main.cfg,before)
    def test_control_and_origin(self):
        self.assertEqual(self.client.post("/api/app/control",json={"token":"wrong"}).status_code,403)
        self.assertEqual(self.client.post("/api/demo/reset",json={},headers={"Origin":"https://other.example"}).status_code,403)
        self.assertEqual(self.client.get("/api/app",headers={"Host":"rebind.example","Origin":"http://rebind.example"}).status_code,403)
    def test_recap_confirmed_photo_used_without_fake_visit(self):
        self.client.post("/api/demo/reset",json={"session_id":"photo-only"})
        out=self.client.post("/api/recap",json={"session_id":"photo-only","photos":[{"id":"p","poi_id":"qixiasi","source":"manual"}]}).json()
        self.assertEqual(out["visited"],[])
        self.assertEqual(out["diary"]["captions"][0]["text"],"栖霞寺")
    def test_unconfirmed_photo_not_treated_as_fact(self):
        out=self.client.post("/api/recap",json={"session_id":"unconfirmed","photos":[{"id":"p","poi_id":"qixiasi","source":"vision"}]}).json()
        self.assertEqual(out["diary"]["captions"][0]["text"],"地点待确认")
    def test_no_key_stream_finishes(self):
        with patch.dict(self.main.cfg,{"deepseek_api_key":""}):
            text=self.client.post("/api/chat",json={"session_id":"nokey","text":"hello"}).text
        events=[json.loads(x[6:]) for x in text.strip().split("\n\n")]
        self.assertEqual(events[-1]["type"],"done")
        self.assertEqual(events[-1]["status"],"failed")
    def test_launcher_rejects_other_health_200(self):
        from launcher import _healthy
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return b'{"ok":true}'
        with patch("urllib.request.urlopen",return_value=Response()):
            self.assertFalse(_healthy(1234))

if __name__=="__main__":
    unittest.main(verbosity=2)
