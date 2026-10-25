"""Read-only access to recorded research evidence; never starts a simulator."""
import io
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
LIBRARY=ROOT/'examples/experiments/shadow-benchmark'
COHORTS=('baseline-100','gpr-tuned-20','navigation-30')
FILES={'summary.json','map-study.json','learning-evidence.json','profile-comparison.json',
       'navigation-comparison.json','navigation-corner-clearance.json','convergence.json',
       'inventory.csv','map-scores.csv','recommended-config.json','reference-index.json',
       'quality.png','warehouse-map.png','office-map.png','navigation-corner-clearance.png',
       'demo.mp4','demo.webm','demo.zip','gpr-demo.zip','gpr-demo-verification.json','checksums.sha256'}
for cohort in COHORTS:
    FILES.update({cohort+suffix for suffix in ('.zip','-analysis.json','-report.json','-targets.json','-trials.csv')})


def read_json(path):return json.loads(path.read_text())


class EvidenceLibrary:
    def __init__(self,root=LIBRARY):self.root=Path(root)

    def file(self,name):
        if name not in FILES:raise FileNotFoundError('Unknown evidence file')
        return self.root/name

    def member(self,cohort,suffix):
        if cohort not in COHORTS:raise ValueError('Unknown evidence cohort')
        with zipfile.ZipFile(self.root/(cohort+'.zip')) as archive:
            names=[n for n in archive.namelist() if n.endswith('/'+suffix)]
            if len(names)!=1:raise ValueError('Expected one archived evidence member')
            info=archive.getinfo(names[0])
            if info.file_size>64*1024*1024:raise ValueError('Evidence member exceeds 64 MiB')
            return archive.read(info)

    def run_bytes(self,cohort,identity):
        if not re.fullmatch(r'[0-9TZabcdef-]{16,64}',identity):raise ValueError('Invalid recorded run identity')
        if cohort in ('demo','gpr-demo'):
            if identity!=''.join((self.root/(cohort+'-id.txt')).read_text().split()):raise FileNotFoundError('Demo run not found')
            return (self.root/(cohort+'.zip')).read_bytes()
        if cohort not in COHORTS:raise ValueError('Unknown evidence cohort')
        with zipfile.ZipFile(self.root/(cohort+'.zip')) as archive:
            matches=[n for n in archive.namelist() if n.endswith('/'+identity+'.zip')]
            if len(matches)!=1:raise FileNotFoundError('Run not found in recorded evidence')
            info=archive.getinfo(matches[0])
            if info.file_size>64*1024*1024:raise ValueError('Recorded run exceeds 64 MiB')
            return archive.read(info)

    def run(self,cohort,identity):
        with zipfile.ZipFile(io.BytesIO(self.run_bytes(cohort,identity))) as archive:
            expected={identity+'/'+n for n in ('manifest.json','scenario.json','timeline.jsonl')}
            if set(archive.namelist())!=expected or sum(i.file_size for i in archive.infolist())>64*1024*1024:
                raise ValueError('Unexpected recorded-run contents')
            return {'manifest':json.loads(archive.read(identity+'/manifest.json')),
                    'scenario':json.loads(archive.read(identity+'/scenario.json')),
                    'timeline':[json.loads(line) for line in archive.read(identity+'/timeline.jsonl').decode().splitlines()]}

    def sources(self):return json.loads(self.member('baseline-100','sources.json'))

    def reference(self,name):
        if name not in self.sources():raise ValueError('Unknown recorded field')
        with zipfile.ZipFile(io.BytesIO(self.member('baseline-100','reference/'+name+'.zip'))) as archive:
            names=archive.namelist();manifest=next(n for n in names if n.endswith('/manifest.json'))
            prefix=manifest.removesuffix('manifest.json')
            return {'manifest':json.loads(archive.read(manifest)),
                    'scenario':json.loads(archive.read(prefix+'scenario.json')),
                    'measurements':[json.loads(l) for l in archive.read(prefix+'measurements.jsonl').decode().splitlines()]}

    def reference_for_run(self,cohort,identity):
        run=self.run(cohort,identity)
        ref=self.reference(run['scenario']['name'])
        if ref['manifest']['radio_field_sha256']!=run['manifest']['radio_field_sha256']:
            raise ValueError('Reference belongs to a different RF field')
        return ref

    def overview(self):
        reports={c:read_json(self.file(c+'-report.json')) for c in COHORTS}
        cohorts=[];known=set()
        for name,report in reports.items():
            gp=[r for r in report['trials'] if r['method'].startswith('GPR')]
            known.update(r['experiment_id'] for r in report['trials'] if r.get('experiment_id'))
            cohorts.append({'id':name,'total':len(report['trials']),'gpr_total':len(gp),
                'gpr_successes':sum(bool(r.get('success')) for r in gp),'trials':report['trials']})
        sources=self.sources();known.update(s['experiment_id'] for s in sources.values())
        demo=''.join((self.root/'demo-id.txt').read_text().split());known.add(demo)
        gpr_demo=''.join((self.root/'gpr-demo-id.txt').read_text().split());known.add(gpr_demo)
        failed=next(r for r in reports['baseline-100']['trials'] if r['method']=='GPR-pathloss' and not r.get('success'))
        repeat=next(r for r in reports['navigation-30']['trials'] if r['method']==failed['method'] and
                    r['label']==failed['label'] and r['beta']==failed['beta'])
        good=next(r for r in reports['baseline-100']['trials'] if r['method']=='GPR-pathloss' and
                  r['beta']==1 and r.get('success') and r['label']=='district-a')
        return {'data_origin':'recorded_simulation','hardware_validation':{'available':False,'runs':0},
            'summary':read_json(self.file('summary.json')),'study':read_json(self.file('map-study.json')),
            'cohorts':cohorts,'targets':read_json(self.file('baseline-100-targets.json')),
            'profile_comparison':read_json(self.file('profile-comparison.json')),
            'navigation_comparison':read_json(self.file('navigation-comparison.json')),
            'corner':read_json(self.file('navigation-corner-clearance.json')),
            'gpr_demo':read_json(self.file('gpr-demo-verification.json')),
            'convergence':{k:v for k,v in read_json(self.file('convergence.json')).items() if k!='probes'},
            'examples':{'gpr_success':{'cohort':'baseline-100','experiment_id':good['experiment_id']},
                'gpr_failure':{'cohort':'baseline-100','experiment_id':failed['experiment_id']},
                'gpr_repeat':{'cohort':'navigation-30','experiment_id':repeat['experiment_id']},
                'source':{'cohort':'baseline-100','experiment_id':sources[good['label']]['experiment_id']},
                'gpr_demo':{'cohort':'gpr-demo','experiment_id':gpr_demo},
                'demo':{'cohort':'demo','experiment_id':demo}},
            'known_recorded_ids':sorted(known)}
