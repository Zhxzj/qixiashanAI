"""Polyline projection and continuous metre progress, shared by plan and movement."""
import math
from app.services.location import dist_m

def project(pos, geo):
    if len(geo) == 1:
        return 0.0, list(geo[0]), dist_m(pos, geo[0]), 0
    best = None
    walked = 0.0
    cos = math.cos(math.radians(pos[0]))
    for i, (a, b) in enumerate(zip(geo, geo[1:])):
        dx, dy = (b[1]-a[1])*cos, b[0]-a[0]
        px, py = (pos[1]-a[1])*cos, pos[0]-a[0]
        t = max(0, min(1, (px*dx+py*dy)/(dx*dx+dy*dy))) if dx or dy else 0
        q = [a[0]+t*(b[0]-a[0]), a[1]+t*(b[1]-a[1])]
        length = dist_m(a, b)
        item = (walked+t*length, q, dist_m(pos, q), i)
        if best is None or item[2] < best[2]:
            best = item
        walked += length
    return best

def length(geo):
    return sum(dist_m(a,b) for a,b in zip(geo, geo[1:]))

def at(geo, meters):
    for a,b in zip(geo, geo[1:]):
        seg = dist_m(a,b)
        if seg and meters < seg:
            t = max(0, meters)/seg
            return [a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t]
        meters -= seg
    return list(geo[-1])
