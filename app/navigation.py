"""Convert shared box geometry into a static Nav2 occupancy map (not a planner)."""
import json
import math
from pathlib import Path
try:
    from .scenario import inside
except ImportError:
    from scenario import inside


def bounds(scene):
    floors = [o for o in scene['objects'] if o['center'][2] + o['size'][2]/2 <= .01]
    if floors:
        o = max(floors, key=lambda o: o['size'][0]*o['size'][1])
        # Axis-aligned extent of a rotated floor; cells outside it are occupied below.
        c, s = abs(math.cos(o['yaw_rad'])), abs(math.sin(o['yaw_rad']))
        w, h = o['size'][:2]
        return [o['center'][0]-(c*w+s*h)/2, o['center'][1]-(s*w+c*h)/2,
                o['center'][0]+(c*w+s*h)/2, o['center'][1]+(s*w+c*h)/2]
    return [-15, -15, 15, 15]


def free(scene, x, y, clearance=0):
    floors = [o for o in scene['objects'] if o['center'][2]+o['size'][2]/2 <= .01]
    def on_floor(o):
        dx,dy=x-o['center'][0],y-o['center'][1]; c,s=math.cos(o['yaw_rad']),math.sin(o['yaw_rad'])
        return abs(c*dx+s*dy)<o['size'][0]/2-clearance and abs(-s*dx+c*dy)<o['size'][1]/2-clearance
    if floors and not any(on_floor(o) for o in floors):
        return False
    # Include low obstacles; exclude floor and overhead lintels/ceilings.
    for obj in scene['objects']:
        low = obj['center'][2]-obj['size'][2]/2
        high = obj['center'][2]+obj['size'][2]/2
        if high > .05 and low < .8 and inside(obj, [x, y, obj['center'][2]], clearance):
            return False
    return True


def export_map(scene, directory, resolution=.1):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    xmin, ymin, xmax, ymax = bounds(scene)
    width = math.ceil((xmax-xmin)/resolution); height = math.ceil((ymax-ymin)/resolution)
    if width*height > 1000000:
        raise ValueError('Navigation map exceeds 1 million cells; reduce world size')
    pixels = bytearray()
    for iy in reversed(range(height)):
        for ix in range(width):
            pixels.append(254 if free(scene, xmin+(ix+.5)*resolution, ymin+(iy+.5)*resolution) else 0)
    (directory/'map.pgm').write_bytes(f'P5\n{width} {height}\n255\n'.encode()+pixels)
    # Relative image path works both in the checkout and /project bind mount.
    (directory/'map.yaml').write_text(f'image: map.pgm\nmode: trinary\nresolution: {resolution}\n'
        f'origin: [{xmin}, {ymin}, 0.0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.25\n')
    meta = dict(bounds=[xmin,ymin,xmax,ymax], resolution=resolution, width=width, height=height,
                localization='Gazebo ground truth; not SLAM/AMCL', static_obstacles_only=True)
    (directory/'map.json').write_text(json.dumps(meta, indent=2)+'\n')
    return meta
