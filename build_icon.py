"""Create the original multi-resolution RAW photo icon using only the stdlib."""
import math
from pathlib import Path
import struct
import zlib


def png(size):
    scale = 3
    width = size * scale
    pixels = bytearray(size * size * 4)
    def inside_round(x, y, left, top, right, bottom, radius):
        cx = min(max(x, left + radius), right - radius)
        cy = min(max(y, top + radius), bottom - radius)
        return (x-cx)**2 + (y-cy)**2 <= radius**2
    for py in range(size):
        for px in range(size):
            samples = []
            for sy in range(scale):
                for sx in range(scale):
                    x=(px+(sx+.5)/scale)/size
                    y=(py+(sy+.5)/scale)/size
                    color=(0,0,0,0)
                    if inside_round(x,y,.035,.035,.965,.965,.19):
                        color=(37,40,46,255)
                    if inside_round(x,y,.16,.20,.84,.80,.075):
                        color=(225,234,245,255)
                    if inside_round(x,y,.205,.245,.795,.755,.035):
                        color=(24,29,37,255)
                    if .23 <= x <= .77 and .43 <= y <= .73:
                        mountain=min(.47+1.25*abs(x-.42),.56+1.4*abs(x-.68))
                        if y >= mountain:
                            color=(51,141,242,255)
                    if (x-.64)**2+(y-.39)**2 < .058**2:
                        color=(251,189,91,255)
                    # Blue contact-sheet tabs distinguish the mark at 16px.
                    if .10 < x < .145 and (.32 < y < .42 or .58 < y < .68):
                        color=(67,157,255,255)
                    samples.append(color)
            i=(py*size+px)*4
            alpha=sum(c[3] for c in samples)/len(samples)
            for channel in range(3):
                pixels[i+channel]=round(sum(c[channel]*c[3] for c in samples)/sum(c[3] for c in samples)) if alpha else 0
            pixels[i+3]=round(alpha)
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    rows=b''.join(b'\0'+pixels[y*size*4:(y+1)*size*4] for y in range(size))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',size,size,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows,9))+chunk(b'IEND',b'')


def build(destination):
    sizes=(16,24,32,48,64,128,256)
    images=[png(size) for size in sizes]
    offset=6+16*len(images)
    directory=[]
    for size,image in zip(sizes,images):
        directory.append(struct.pack('<BBBBHHII',size%256,size%256,0,0,1,32,len(image),offset))
        offset+=len(image)
    Path(destination).write_bytes(struct.pack('<HHH',0,1,len(images))+b''.join(directory)+b''.join(images))
    Path(destination).with_suffix('.png').write_bytes(images[-1])


if __name__=='__main__':
    build(Path(__file__).resolve().parent/'SonyRAWPanel.ico')
