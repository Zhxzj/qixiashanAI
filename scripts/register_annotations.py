"""Reproduce today's screenshot registration, with independent POI holdouts. No image edits."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]
CONTROLS = [('凤翔峰',735,204.5),('读枫',382.5,275),('虎山',319.5,275),('德云亭',387,341),('桃花扇亭',421.5,357.5),('珍珠泉',468,315.5),('幽居庵',511.5,303.5),('待月亭',425,465.5),('如來堂',370.5,476),('栖霞寺',319.5,473)]
HOLDOUTS = [('碧云亭',342,260),('了凡问道',538.5,348.5)]


def merc(lat):
    return math.degrees(math.asinh(math.tan(math.radians(lat))))


def fit(values, targets):
    mean = sum(values)/len(values)
    target_mean = sum(targets)/len(targets)
    a = sum((x-mean)*(y-target_mean) for x,y in zip(values,targets))/sum((x-mean)**2 for x in values)
    return a, target_mean-a*mean


def reproduce():
    osm = json.loads((ROOT/'app/data/osm/map.json').read_text(encoding='utf-8'))
    annotations = json.loads((ROOT/'app/data/map_annotations.json').read_text(encoding='utf-8'))
    pois = {p['name']:p['coord'] for p in osm['pois']}
    ax,bx = fit([pois[n][1] for n,x,y in CONTROLS],[x+.75 for n,x,y in CONTROLS])
    ay,by = fit([merc(pois[n][0]) for n,x,y in CONTROLS],[y+.75 for n,x,y in CONTROLS])
    def residual(points):
        return [{'name':n,'visible_pixel_center':[x,y],'coord':pois[n],
                 'residual_px':math.hypot(ax*pois[n][1]+bx-x-.75,ay*merc(pois[n][0])+by-y-.75)} for n,x,y in points]
    controls, holdouts = residual(CONTROLS),residual(HOLDOUTS)
    result=[]
    for p in annotations['items']:
        if p['category']!='toilet': continue
        x,y = p['source']['pixel_center']
        coord=[round(math.degrees(math.atan(math.sinh(math.radians((y-by)/ay)))),7),round((x-bx)/ax,7)]
        if coord != p['coord']:
            raise AssertionError(f"{p['id']}复算坐标不一致：{coord} != {p['coord']}")
        result.append({'id':p['id'],'pixel_center':[x,y],'coord':coord})
    assert len(result)==12 and max(p['residual_px'] for p in holdouts)<1
    gates=[]
    for p in annotations['items']:
        if p['category']!='gate': continue
        x,y=p['source']['pixel_center']
        coord=[round(math.degrees(math.atan(math.sinh(math.radians((y-by)/ay)))),7),round((x-bx)/ax,7)]
        assert coord==p['coord'], '黄色大门复算不一致'
        gates.append({'id':p['id'],'pixel_center':[x,y],'coord':coord})
    assert len(gates)==2
    return {'schema_version':1,'image_sha256':annotations['source']['image_sha256'],
            'gate_source':annotations['gate_source'],'gates':gates,
            'image_size':[1285,700],'method':'x=ax*lng+bx; y=ay*degrees(asinh(tan(radians(lat))))+by',
            'icon_center_compensation_px':.75,'parameters':{'ax':ax,'bx':bx,'ay':ay,'by':by},
            'controls':controls,'holdouts':holdouts,'points':result,
            'rms_control_px':math.sqrt(sum(p['residual_px']**2 for p in controls)/len(controls)),
            'max_control_px':max(p['residual_px'] for p in controls),'field_accuracy_m':None,
            'method_version':1,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'note':'控制点与圈中心为人工对应的截图像素，不是实地测绘；不表示入口或通行核实。'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image',type=Path)
    ap.add_argument('--output',type=Path)
    args=ap.parse_args()
    report=reproduce()
    if args.image:
        raw=args.image.read_bytes()
        digest=hashlib.sha256(raw).hexdigest()
        source=report['gate_source'] if digest==report['gate_source']['image_sha256'] else report
        assert digest==source['image_sha256'],'不是今天确认的图片'
        assert raw[:8]==b'\x89PNG\r\n\x1a\n' and list(struct.unpack('>II',raw[16:24]))==source['image_size']
        report['source_image_checked']=True
        report['checked_image_sha256']=digest
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'points':len(report['points']),'rms_px':report['rms_control_px'],'holdout_px':[p['residual_px'] for p in report['holdouts']]},ensure_ascii=False))


if __name__=='__main__':main()
