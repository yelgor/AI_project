"""Keep the original Clearpath COLLADA face materials in the web model.

The STL export loses material groups, notably the black wheel rubber. This
optional visual pass leaves URDF transforms and all simulation physics intact.
"""
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[1]
output=root/'.runtime/assets/husky';manifest_path=output/'model.json'
manifest=json.loads(manifest_path.read_text())
for item in manifest['meshes']:
    original=Path(item['source']).with_suffix('.dae')
    if not original.is_file():continue
    xml=ET.parse(original).getroot()
    # Current official A200 visuals have embedded face colours, no image maps.
    if xml.findall('.//{*}library_images/{*}image'):continue
    filename=hashlib.sha256(str(original).encode()).hexdigest()[:12]+'.dae'
    shutil.copyfile(original,output/filename)
    item.update(file=filename,source=str(original),sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
                material_source='original Clearpath COLLADA face materials')
temporary=manifest_path.with_suffix('.json.tmp');temporary.write_text(json.dumps(manifest,indent=2)+'\n');temporary.replace(manifest_path)
print('Original Clearpath face materials preserved for',sum(m['file'].endswith('.dae') for m in manifest['meshes']),'visuals')
