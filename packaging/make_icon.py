"""Generate the product's simple maple mark as ICO using only the standard library."""
import struct
from pathlib import Path

LEAF=[(32,9),(36,23),(43,17),(42,27),(54,24),(48,35),(53,38),(35,43),(34,53),(30,53),(31,43),(13,38),(18,35),(12,24),(24,27),(23,17),(29,23)]

def inside(x,y):
    hit=False
    for a,b in zip(LEAF,LEAF[1:]+LEAF[:1]):
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            hit=not hit
    return hit

def main():
    images=[]
    for size in (16,32,48,64):
        pixels=bytearray()
        for y in range(size-1,-1,-1):
            for x in range(size):
                # Supersampling preserves the leaf at small shell icon sizes.
                coverage=sum(inside((x+(i+.5)/4)*64/size,(y+(j+.5)/4)*64/size) for i in range(4) for j in range(4))/16
                base=(247,240,228);ink=(166,58,43)
                r,g,b=[round(a*(1-coverage)+c*coverage) for a,c in zip(base,ink)]
                pixels.extend((b,g,r,255))
        mask=bytes(((size+31)//32)*4*size)
        dib=struct.pack('<IiiHHIIiiII',40,size,size*2,1,32,0,len(pixels),0,0,0,0)+pixels+mask
        images.append((size,dib))
    offset=6+16*len(images)
    result=bytearray(struct.pack('<HHH',0,1,len(images)))
    for size,dib in images:
        result.extend(struct.pack('<BBBBHHII',size,size,0,0,1,32,len(dib),offset))
        offset+=len(dib)
    for _,dib in images:
        result.extend(dib)
    (Path(__file__).resolve().parents[1]/'native/guide.ico').write_bytes(result)

if __name__=='__main__':
    main()
