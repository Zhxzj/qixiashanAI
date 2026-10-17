"""Local pedestrian graph built from OSM node identities, never image coordinates."""
import heapq
import json
import math
from pathlib import Path
from app.services.geometry import project, length
from app.services.location import dist_m, bearing_text


class OSMMapService:
    def __init__(self, data_dir):
        self.path=Path(data_dir)/"osm/map.json"
        self.data=json.loads(self.path.read_text(encoding="utf-8"))
        self.nodes=self.data["nodes"]
        self.pois={p["id"]:p for p in self.data["pois"]}
        self.segments=[]
        for road in self.data["roads"]:
            for i,(a,b) in enumerate(zip(road["nodes"],road["nodes"][1:])):
                if a!=b:self.segments.append((road,i,a,b))

    def public_data(self):
        result={k:self.data[k] for k in ("schema_version","coordinate_system","bounds","view_center","graph_sha256","source_url","license","license_url","attribution","source_sha256","retrieved_at","field_verified","roads","pois","areas")}
        result["photo_reference"]=json.loads((self.path.parent/"photo-reference.json").read_text(encoding="utf-8"))
        return result

    def resolve(self,key,internal_pois=()):
        internal=next((p for p in internal_pois if p["poi_id"]==key),None)
        if internal:key=internal["name"]
        matches=[p for p in self.data["pois"] if p["id"]==key or p["name"]==key]
        if len(matches)!=1:raise ValueError("该地名在本地OSM数据中缺失或有歧义，请在地图选择已有点位")
        return matches[0]

    def plan_for_state(self,state,to,via,internal_pois,avoid_steps=False):
        from app.services import map_navigation as nav
        loc=state.get("location") or {}
        if loc.get("coordinate_system")!="WGS84" or loc.get("lat") is None:
            return {"error":{"code":"no_location","message":"请先在地图选起点并规划，或开启精度合格的真实定位"}}
        if loc.get("source")=="device" and not nav.quality(state):
            return {"error":{"code":"location_unavailable","message":"当前定位精度或新鲜度不足，请手动设置起点"}}
        try:
            target=self.resolve(to,internal_pois);middle=[self.resolve(k,internal_pois)["coord"] for k in via]
            pending=nav.start_route(state,[loc["lat"],loc["lng"]],target["coord"],middle)
            result=self.plan(pending["origin"],target["coord"],middle,target["name"],avoid_steps)
            route=nav.commit_route(state,pending["request_id"],result)
            route.update({k:result[k] for k in ("access_notes","data_version","way_ids","avoid_steps")})
            state["_map_pois"]=self.internal_matches(internal_pois)
            # Tools return a compact authoritative summary, never send whole geometry to the model.
            return {k:v for k,v in route.items() if k not in ("geometry","origin","destination","via_coords","way_ids")}
        except ValueError as e:
            state["route"]={"status":"no_path","provider":"osm","error":{"code":"no_path","message":str(e)}}
            return {"error":{"code":"no_path","message":str(e)}}

    def snap(self, pos, max_distance=60):
        best=None
        for road,i,a,b in self.segments:
            offset,q,distance,_=project(pos,[self.nodes[a],self.nodes[b]])
            if best is None or distance<best["distance"]:
                size=dist_m(self.nodes[a],self.nodes[b])
                best={"road":road,"index":i,"a":a,"b":b,"point":q,"distance":distance,"t":offset/size if size else 0}
        if best is None or best["distance"]>max_distance:
            raise ValueError(f"点位距已知步行路网超过{max_distance}米，请点选附近已知道路；不以直线补路")
        return best

    def _graph(self, locations):
        snaps=[self.snap(p) for p in locations]
        split={};node_positions=dict(self.nodes);ids=[]
        for index,snap in enumerate(snaps):
            node=snap["a"] if snap["t"]<1e-7 else snap["b"] if snap["t"]>1-1e-7 else f"point:{index}"
            ids.append(node);node_positions[node]=snap["point"]
            split.setdefault((snap["road"]["id"],snap["index"]),[]).append((snap["t"],node))
        graph={}
        for road,index,a,b in self.segments:
            ordered=sorted([(0,a),(1,b)]+split.get((road["id"],index),[]))
            direction=road["tags"].get("oneway:foot", "no")
            for (_,x),(_,y) in zip(ordered,ordered[1:]):
                if x==y:continue
                distance=dist_m(node_positions[x],node_positions[y])
                if direction not in ("-1",):graph.setdefault(x,[]).append((y,distance,road))
                if direction not in ("yes","1","true"):graph.setdefault(y,[]).append((x,distance,road))
        return graph,node_positions,ids,snaps

    def plan(self, origin, destination, via=None, name="步行目的地", avoid_steps=False):
        points=[origin,*(via or []),destination]
        graph,positions,ids,snaps=self._graph(points)
        path=[];roads=[]
        for start,end in zip(ids,ids[1:]):
            distances={start:0};previous={};heap=[(0,start)]
            while heap:
                cost,node=heapq.heappop(heap)
                if cost!=distances.get(node):continue
                if node==end:break
                for nxt,distance,road in graph.get(node,[]):
                    if avoid_steps and road["highway"]=="steps":continue
                    nc=cost+distance*(1.3 if road["highway"]=="steps" else 1)
                    if nc<distances.get(nxt,float("inf")):
                        distances[nxt]=nc;previous[nxt]=(node,road);heapq.heappush(heap,(nc,nxt))
            if end not in distances:
                raise ValueError("本地OSM步行路网未连通该路段，或避台阶条件下无路；请更换入口，不连接未知道路")
            part=[end];part_roads=[]
            while part[-1]!=start:
                parent,road=previous[part[-1]];part.append(parent);part_roads.append(road)
            part.reverse();part_roads.reverse()
            if path:path.extend(part[1:])
            else:path=part
            roads.extend(part_roads)
        geo=[positions[n] for n in path]
        total=length(geo)
        if total<2:raise ValueError("起终点位于同一已知道路位置，请选择另一目的地")
        groups=[];walked=0;minutes=0
        for i,road in enumerate(roads):
            distance=dist_m(geo[i],geo[i+1]);walked+=distance
            minutes+=distance/(25 if road["highway"]=="steps" else 65 if road["highway"] in ("residential","unclassified","service") else 50)
            if groups and groups[-1]["key"]==(road["name"],road["highway"]):
                groups[-1]["end"]=geo[i+1];groups[-1]["at_m"]=walked
            else:groups.append({"key":(road["name"],road["highway"]),"start":geo[i],"end":geo[i+1],"at_m":walked})
        labels={"steps":"台阶","path":"山间小径","footway":"步道","pedestrian":"步行道路","track":"小路"}
        steps=[]
        for g in groups:
            label=g["key"][0] or labels.get(g["key"][1],"已知道路")
            steps.append({"instruction":f"沿{label}向{bearing_text(g['start'],g['end'])}行进（以现场道路为准）","at_m":g["at_m"],"poi_id":None})
        notes=[]
        for i,s in enumerate(snaps):
            if s["distance"]>3:
                label="起点" if i==0 else "终点" if i==len(snaps)-1 else f"途经点{i}"
                notes.append(f"{label}距已知道路约{round(s['distance'])}米；仅规划到道路投影点，最后连接/入口未核实")
        return {"geometry":geo,"steps":steps,"duration_min":max(1,round(minutes)),"name":name,
                "access_notes":notes,"data_version":self.data["graph_sha256"],
                "way_ids":list(dict.fromkeys(r["osm_id"] for r in roads)),"avoid_steps":avoid_steps}

    def internal_matches(self, internal_pois):
        result={}
        for internal in internal_pois:
            found=[p for p in self.data["pois"] if p["category"]=="poi" and p["name"]==internal["name"]]
            if len(found)==1:
                p=found[0]
                result[internal["poi_id"]]={"coord":p["coord"],"osm_id":p["id"],"name":p["name"]}
        return result
