"""Current release identity is separate from immutable historical run provenance."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def identity(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def files(root):
    paths = set()
    for folder in ('src','scripts','Tests','config','.github/workflows'):
        paths.update(p for p in (root/folder).rglob('*') if p.is_file() and p.suffix in {'.py','.sql','.css','.json','.toml','.yml','.yaml'})
    paths.update((root/'src/lebanon_fuel/dashboard').glob('*.webp'))
    paths.update(root/p for p in ('requirements.txt','pyproject.toml'))
    return {str(p.relative_to(root)):digest(p) for p in sorted(paths)}


def models(root):
    return {str(p.relative_to(root)):digest(p) for p in sorted((root/'data/models').rglob('*')) if p.is_file()}


def prepare_design(root):
    import gzip
    root=Path(root);refs=json.loads((root/'reports/releases/frozen_references.json').read_text())
    spec=refs['frozen_design'];dest=root/spec['path']
    if dest.exists():
        assert digest(dest)==spec['sha256'],'Existing frozen design differs; never overwrite it'
    else:
        archive=root/spec['archive']
        assert digest(archive)==spec['archive_sha256'],'Frozen design archive checksum mismatch'
        payload=gzip.decompress(archive.read_bytes())
        assert sha256(payload).hexdigest()==spec['sha256'],'Frozen design input checksum mismatch'
        dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(payload)
    return dict(status='restored_or_verified',sha256=spec['sha256'])


def create(root, base_commit=None):
    root=Path(root);source=files(root);artifacts=models(root)
    payload=dict(created_at=datetime.now(timezone.utc).isoformat(),hash_algorithm='sha256',
        commit_sha=os.environ.get('GITHUB_SHA'),base_commit=base_commit,
        binding='exact CI commit' if os.environ.get('GITHUB_SHA') else 'local candidate base plus exact source/model digests; not a deployed commit attestation',
        source_sha256=source,source_identity=identity(source),model_sha256=artifacts,model_identity=identity(artifacts),
        frozen_references_sha256=digest(root/'reports/releases/frozen_references.json'),
        historical_training_source_fully_recovered=not json.loads((root/'reports/releases/frozen_references.json').read_text()).get('unrecoverable_source_versions',[]),
        production_approved=False,note='Integrity attestation, not model-performance approval or a digital signature.')
    dest=root/'reports/releases/current.json';dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(payload,indent=2)+'\n')
    return payload


def verify(root):
    root=Path(root);payload=json.loads((root/'reports/releases/current.json').read_text())
    assert payload['source_sha256']==files(root),'Current release source checksum mismatch'
    assert payload['model_sha256']==models(root),'Current release model checksum mismatch'
    assert payload['source_identity']==identity(payload['source_sha256']),'Release source identity mismatch'
    assert payload['model_identity']==identity(payload['model_sha256']),'Release model identity mismatch'
    assert payload['frozen_references_sha256']==digest(root/'reports/releases/frozen_references.json'),'Frozen provenance reference mismatch'
    if payload.get('commit_sha') and os.environ.get('GITHUB_SHA'):
        assert payload['commit_sha']==os.environ['GITHUB_SHA'],'CI commit differs from release attestation'
    return dict(status='passed',source_identity=payload['source_identity'],model_identity=payload['model_identity'],
                commit_sha=payload.get('commit_sha'),production_approved=False)


def verify_frozen(root, manifest_path):
    """Every pre-existing source hash is checked against original hash-matched bytes."""
    root=Path(root);verify(root)
    reference=json.loads((root/'reports/releases/frozen_references.json').read_text())
    assert digest(root/manifest_path)==reference['frozen_manifests'][manifest_path],manifest_path
    manifest=json.loads((root/manifest_path).read_text())
    expected=[]
    for field in ('code_hashes','source_sha256'):
        expected.extend(manifest.get(field,{}).items())
    expected.extend(manifest.get('release',{}).get('source_sha256',{}).items())
    for path,checksum in expected:
        archived=reference['source_archives'].get(checksum)
        assert archived and digest(root/archived)==checksum,f'Missing or modified frozen source: {path}'
    return manifest


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['create','verify','prepare-design']);parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--base-commit')
    args=parser.parse_args()
    result=create(args.root,args.base_commit) if args.command=='create' else prepare_design(args.root) if args.command=='prepare-design' else verify(args.root)
    print(json.dumps({k:v for k,v in result.items() if k not in {'source_sha256','model_sha256'}},indent=2))
