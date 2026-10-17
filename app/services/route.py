"""Data-driven bidirectional guide graph; no fabricated off-network route."""
import heapq
import json
from pathlib import Path
from app.services.location import dist_m
from app.services.geometry import project, length

class RouteService:
    def __init__(self, data_dir):
        self.routes = json.loads((Path(data_dir)/"routes.json").read_text(encoding="utf-8"))
        self.pois = {p["poi_id"]:p for p in json.loads((Path(data_dir)/"poi.json").read_text(encoding="utf-8"))}
        self.nodes, self.edges, self.poi_nodes = {}, {}, {}
        for r in self.routes:
            for xy in r["geometry"]:
                key = tuple(xy)
                self.nodes[key] = list(xy)
                self.edges.setdefault(key, [])
            for a,b in zip(r["geometry"],r["geometry"][1:]):
                a,b = tuple(a),tuple(b)
                d = dist_m(a,b)
                self.edges[a].append((b,d,r))
                self.edges[b].append((a,d,r))
            for p in r["points"]:
                self.poi_nodes[p["poi_id"]] = tuple(r["geometry"][p["geo_idx"]])

    def route_of_poi(self, pid):
        return next((r for r in self.routes if any(p["poi_id"]==pid for p in r["points"])), None)

    def _cost(self, d, route, theme, rain, hot):
        a=route.get("attrs", {})
        pref = 0.6 if route.get("theme")==theme else 1.4
        return d*pref*(1 + (a.get("slippery_risk",0)/3 if rain else 0) + (1-a.get("shade_ratio",0) if hot else 0))

    def _path(self, graph, start, end, theme, rain, hot):
        todo=[(0,start)]
        distances={start:0}
        previous={}
        while todo:
            cost,node=heapq.heappop(todo)
            if cost!=distances[node]:
                continue
            if node==end:
                path=[node]
                while node in previous:
                    node=previous[node]
                    path.append(node)
                return list(reversed(path))
            for nxt,d,r in graph.get(node,[]):
                nc=cost+self._cost(d,r,theme,rain,hot)
                if nc<distances.get(nxt,float("inf")):
                    distances[nxt]=nc
                    previous[nxt]=node
                    heapq.heappush(todo,(nc,nxt))
        return None

    def plan(self,state,to,via=None,theme="classic",consider_weather=True,conditions=None):
        if state.get("prefs",{}).get("map_mode")=="real" and state.get("prefs",{}).get("map_provider")=="osm" and hasattr(self,"osm"):
            return self.osm.plan_for_state(state,to,via or [],list(self.pois.values()))
        if state.get("prefs",{}).get("map_mode")=="real":
            import uuid
            # The official JS SDK runs in the browser. Never calculate a draft fallback here.
            intent={"id":uuid.uuid4().hex,"to":to,"via":via or [],"theme":theme,
                    "consider_weather":consider_weather}
            state["_map_intent"]=intent
            state["route"]=None
            from app.services.map_navigation import stop
            stop(state)
            return {"status":"pending_browser","message":"已请求地图规划；请在地图核对景点和起点，完成后以地图返回的真实步行路线为准。主题/天气条件尚未用于高德算路。"}
        via=via or []
        targets=[]
        for key in [*via,to]:
            pid=key if key in self.pois else next((p for p,v in self.pois.items() if v["name"]==key),None)
            if pid not in self.poi_nodes:
                return {"status":"no_path","error":{"code":"no_path","message":f"现有导览路线未覆盖 {key}，无法提供可靠路径。"}}
            targets.append(pid)
        loc=state.get("location")
        if not loc:
            return {"status":"no_path","error":{"code":"no_location","message":"请先确定当前位置"}}
        pos=(loc["lat"],loc["lng"])
        nearest=min(((project(pos,r["geometry"]),r) for r in self.routes),key=lambda x:x[0][2])
        (offset,q,distance,idx),base=nearest
        if distance>80:
            return {"status":"no_path","error":{"code":"off_network","message":"当前位置离预设导览路线较远，请先回到已覆盖路段。"}}
        start=tuple(q)
        graph={k:list(v) for k,v in self.edges.items()}
        graph.setdefault(start,[])
        # Split the nearest edge rather than restarting at a route vertex.
        for end in base["geometry"][idx:idx+2]:
            end=tuple(end)
            if end!=start:
                dd=dist_m(start,end)
                graph[start].append((end,dd,base))
                graph[end].append((start,dd,base))
        today=((conditions or {}).get("weather") or {}).get("today") or {}
        trusted=consider_weather and (conditions or {}).get("source")=="open-meteo"
        rain=trusted and (today.get("rain_prob") or 0)>=50
        hot=trusted and (today.get("max") or 0)>=28
        path=[start]
        steps=[]
        for pid in targets:
            part=self._path(graph,path[-1],self.poi_nodes[pid],theme,rain,hot)
            if part is None:
                return {"status":"no_path","error":{"code":"no_path","message":"途经点与终点之间没有已知连续路线"}}
            path.extend(part[1:])
            steps.append({"poi_id":pid,"instruction":"沿示意导览路线前往"+self.pois[pid]["name"],"at_m":length(path),"stay_s":120})
        total=length(path)
        plan={"status":"ready","route_id":theme,"theme":theme,"to":targets[-1],"via":targets[:-1],
              "name":self.pois[targets[-1]]["name"],"origin":list(pos),"origin_projection":q,
              "geometry":[list(p) for p in path],"steps":steps,"current_step":0,"total_m":total,
              "progress_m":0.0,"remaining_m":round(total),"distance_m":round(total),
              "duration_min":max(1,round(total/45+len(steps)*2)),"fallback_used":False,
              "constraints":{"theme":theme,"weather_applied":bool(rain or hot)},
              "weather_note":"已按雨天路滑风险和遮阴情况加权；数据为示意导览，不保证最短或无台阶。" if rain or hot else None,
              "light_tip":None,"data_status":"draft_guide_not_turn_by_turn"}
        state["route"]=plan
        return plan
