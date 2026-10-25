"""Import bundled completed experiment/grid archives without overwriting local data."""
import argparse
import io
import json
from pathlib import Path
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',type=Path,default=ROOT/'examples/experiments/paired-pilot')
parser.add_argument('--runtime',type=Path,default=ROOT/'.runtime')
args=parser.parse_args()
packages=[args.source] if args.source.is_file() else list(sorted(args.source.glob('*.zip')))
if not packages:raise SystemExit('No example ZIP archives found')
def import_package(package):
    with zipfile.ZipFile(package) as archive:
        manifests=[n for n in archive.namelist() if n.endswith('/manifest.json')]
        if len(manifests)!=1:raise ValueError('Archive must contain one manifest')
        manifest=json.loads(archive.read(manifests[0]))
        if 'campaign_id' in manifest:
            if manifest['status'] in ('starting','running','finishing'):raise ValueError('Finish the campaign before importing')
            identity=manifest['campaign_id']
            if not identity or any(c not in '0123456789TZabcdefghijklmnopqrstuvwxyz-' for c in identity):raise ValueError('Invalid campaign identity')
            members=archive.infolist()
            if sum(i.file_size for i in members)>256*1024*1024:raise ValueError('Campaign exceeds 256 MiB')
            for info in members:
                relative=info.filename.removeprefix(identity+'/')
                if not info.filename.startswith(identity+'/') or relative.startswith('/') or '..' in relative.split('/'):
                    raise ValueError('Unexpected campaign archive path')
            for info in archive.infolist():
                if not info.filename.endswith('.zip'):continue
                if info.file_size>64*1024*1024:raise ValueError('Nested example exceeds 64 MiB')
                import_package(io.BytesIO(archive.read(info)))
            root=args.runtime/'campaigns';root.mkdir(parents=True,exist_ok=True);target=root/identity
            if target.exists():
                if not all((target/i.filename.removeprefix(identity+'/')).is_file() and
                           (target/i.filename.removeprefix(identity+'/')).read_bytes()==archive.read(i) for i in members):
                    raise ValueError('Refusing to overwrite different local campaign: '+identity)
            else:
                with tempfile.TemporaryDirectory(dir=root,prefix='.import-') as directory:
                    stage=Path(directory)/identity;stage.mkdir()
                    for info in members:
                        file=stage/info.filename.removeprefix(identity+'/');file.parent.mkdir(parents=True,exist_ok=True)
                        file.write_bytes(archive.read(info))
                    stage.rename(target)
            print('Campaign ready for replay/history reuse:',identity)
            return
        dataset='dataset_id' in manifest;identity=manifest.get('dataset_id' if dataset else 'experiment_id','')
        if not identity or any(c not in '0123456789TZabcdefghijklmnopqrstuvwxyz-' for c in identity):raise ValueError('Invalid archive identity')
        if manifest['status'] in ('running','collecting'):raise ValueError('Only completed examples may be imported')
        names=('manifest.json','scenario.json','measurements.jsonl','measurements.csv','events.jsonl') if dataset else ('manifest.json','scenario.json','timeline.jsonl')
        if set(archive.namelist())!={identity+'/'+name for name in names}:raise ValueError('Unexpected archive paths')
        if sum(info.file_size for info in archive.infolist())>64*1024*1024:raise ValueError('Example exceeds 64 MiB')
        root=args.runtime/('datasets' if dataset else 'experiments');root.mkdir(parents=True,exist_ok=True)
        target=root/identity
        if target.exists():
            if not all((target/name).is_file() and (target/name).read_bytes()==archive.read(identity+'/'+name) for name in names):
                raise SystemExit('Refusing to overwrite different local data: '+str(target))
            print('Already present:',identity);return
        with tempfile.TemporaryDirectory(dir=root,prefix='.import-') as directory:
            stage=Path(directory)/identity;stage.mkdir()
            for name in names:(stage/name).write_bytes(archive.read(identity+'/'+name))
            stage.rename(target)
        print('Imported:',identity)
for package in packages:import_package(package)
