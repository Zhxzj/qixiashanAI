"""Fetch one bounded OSM vector extract; no raster tiles, no geocoder/paid API.

Rebuild derived data from the included source.osm.gz with --local (no network).
Derived database and source are supplied under ODbL 1.0, with contributor attribution.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
BOUNDS=json.loads((ROOT/"app/data/osm/source-config.json").read_text(encoding="utf-8"))["bounds"]
URL="https://api.openstreetmap.org/api/0.6/map?bbox="+",".join(map(str,BOUNDS))
WALKABLE={"footway","path","steps","pedestrian","service","unclassified","residential","tertiary","secondary","living_street","track"}


def tags(e):return {t.get("k"):t.get("v") for t in e.findall("tag")}
def inside(p):return BOUNDS[1]<=p[0]<=BOUNDS[3] and BOUNDS[0]<=p[1]<=BOUNDS[2]


def permitted(t):
    if t.get("highway") not in WALKABLE:return False
    if t.get("foot") in ("no","private","use_sidepath"):return False
    if t.get("access") in ("no","private","customers","permit","destination") and t.get("foot") not in ("yes","designated","permissive"):return False
    if t.get("construction") or t.get("proposed") or t.get("seasonal")=="yes":return False
    if t.get("access:conditional") or t.get("foot:conditional"):return False
    return True


def build(raw):
    xml=ET.fromstring(raw)
    nodes={e.get("id"):[float(e.get("lat")),float(e.get("lon"))] for e in xml.findall("node")}
    node_tags={e.get("id"):tags(e) for e in xml.findall("node")}
    roads=[];pois=[];areas=[];excluded=[]
    for e in xml:
        t=tags(e);kind=e.tag;id=e.get("id")
        refs=[n.get("ref") for n in e.findall("nd")]
        coords=[nodes[r] for r in refs if r in nodes]
        if kind=="way" and t.get("highway"):
            if not permitted(t):excluded.append({"osm_id":"way/"+id,"highway":t.get("highway"),"access":t.get("access"),"foot":t.get("foot")})
            else:
                runs=[];run=[]
                for r in refs:
                    if r in nodes and inside(nodes[r]):run.append(r)
                    else:
                        if len(run)>=2:runs.append(run)
                        run=[]
                if len(run)>=2:runs.append(run)
                for i,part in enumerate(runs):
                    roads.append({"id":f"way/{id}/{i}","osm_id":"way/"+id,"nodes":part,"geometry":[nodes[n] for n in part],
                                  "name":t.get("name",""),"highway":t["highway"],"tags":t})
        if kind=="way" and coords and coords[0]==coords[-1] and (t.get("natural") in ("water","wood") or t.get("landuse")=="forest" or t.get("leisure") in ("park","garden")):
            if any(inside(p) for p in coords):areas.append({"id":"way/"+id,"geometry":coords,"name":t.get("name",""),"kind":t.get("natural") or t.get("landuse") or t.get("leisure")})
        category=None
        if t.get("amenity")=="toilets":category="toilet_candidate"
        elif t.get("entrance") in ("yes","main") and kind=="node":category="entrance"
        elif t.get("name") and (t.get("tourism") in ("attraction","viewpoint","picnic_site","museum") or t.get("historic") or t.get("natural") in ("peak","water") or t.get("amenity")=="place_of_worship"):category="poi"
        if category:
            if kind=="node":coord=nodes[id]
            elif kind=="way" and coords:
                coord=[sum(p[0] for p in coords)/len(coords),sum(p[1] for p in coords)/len(coords)]
            else:continue
            if not inside(coord):continue
            # Polygon representative point is not claimed to be a physical entrance.
            entrances=[nodes[r] for r in refs if node_tags.get(r,{}).get("entrance") in ("main","yes")]
            pois.append({"id":kind+"/"+id,"name":t.get("name") or ("公共厕所（OSM候选）" if category=="toilet_candidate" else "出入口（OSM）"),
                         "category":category,"coord":coord,"coordinate_system":"WGS84","source":"OpenStreetMap contributors",
                         "field_verified":False,"tags":t,"entrances":entrances,
                         "position_kind":"point" if kind=="node" else "polygon_representative"})
    used={n for r in roads for n in r["nodes"]}
    from statistics import median
    landmarks=[p["coord"] for p in pois if p["category"]=="poi"]
    graph_sha=hashlib.sha256(json.dumps([roads,{n:nodes[n] for n in sorted(used)}],sort_keys=True).encode()).hexdigest()
    return {"schema_version":1,"coordinate_system":"WGS84","bounds":BOUNDS,"source_url":URL,
            "view_center":[median(p[0] for p in landmarks),median(p[1] for p in landmarks)],"graph_sha256":graph_sha,
            "license":"ODbL-1.0","license_url":"https://opendatacommons.org/licenses/odbl/1-0/",
            "attribution":"© OpenStreetMap contributors","source_sha256":hashlib.sha256(raw).hexdigest(),
            "retrieved_at":datetime.now(timezone.utc).isoformat(),"field_verified":False,
            "nodes":{n:nodes[n] for n in sorted(used)},"roads":roads,"pois":pois,"areas":areas,"excluded":excluded}


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--local",action="store_true");args=ap.parse_args()
    target=ROOT/"app/data/osm";target.mkdir(exist_ok=True)
    if args.local:raw=gzip.decompress((target/"source.osm.gz").read_bytes())
    else:
        req=urllib.request.Request(URL,headers={"User-Agent":"QixiGuide/0.4 (bounded vector data preparation; https://github.com/joeyl3526-cloud/qixi-guide)"})
        with urllib.request.urlopen(req,timeout=45) as r:raw=r.read(6_000_001)
        if len(raw)>6_000_000:raise RuntimeError("OSM数据超出预期大小")
    data=build(raw)
    if not data["roads"] or not data["pois"]:raise RuntimeError("没有可用OSM道路或景点，不覆盖已有数据")
    (target/"source.osm.gz").write_bytes(gzip.compress(raw,mtime=0))
    (target/"map.json").write_text(json.dumps(data,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print(json.dumps({"roads":len(data["roads"]),"nodes":len(data["nodes"]),"pois":len(data["pois"]),"areas":len(data["areas"]),"source_sha256":data["source_sha256"]},ensure_ascii=True))


if __name__=="__main__":main()
