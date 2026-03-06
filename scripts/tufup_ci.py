"""
CI에서 사용하는 tufup 아카이브 생성 + 메타데이터 서명 스크립트.

사용법:
  python scripts/tufup_ci.py \
    --bundle-dir dist/InstagramDMPro \
    --version v1.0.16 \
    --keys-dir tufup_work/keystore \
    --metadata-dir gh-pages/metadata \
    --targets-dir tufup_work/targets
"""
import argparse
import hashlib
import json
import shutil
import tarfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description="tufup CI: create archive and sign metadata")
    p.add_argument("--bundle-dir", required=True, help="PyInstaller output directory")
    p.add_argument("--version", required=True, help="Version tag (e.g. v1.0.16)")
    p.add_argument("--keys-dir", required=True, help="Directory containing signing keys")
    p.add_argument("--metadata-dir", required=True, help="gh-pages metadata directory")
    p.add_argument("--targets-dir", required=True, help="Output directory for archives")
    return p.parse_args()


def create_archive(bundle_dir: Path, targets_dir: Path, app_name: str, version: str) -> Path:
    """PyInstaller 번들을 tar.gz 아카이브로 압축한다."""
    targets_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"{app_name}-{version}.tar.gz"
    archive_path = targets_dir / archive_name

    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(str(bundle_dir), arcname=app_name)

    size = archive_path.stat().st_size
    print(f"Archive created: {archive_path} ({size / 1024 / 1024:.1f} MB)")
    return archive_path


def compute_hash(file_path: Path) -> dict:
    """파일의 SHA-256 해시와 크기를 계산한다."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return {
        "hashes": {"sha256": sha256.hexdigest()},
        "length": file_path.stat().st_size,
    }


def sign_metadata(metadata_dir: Path, keys_dir: Path, targets_dir: Path, app_name: str, version: str):
    """TUF 메타데이터를 업데이트하고 서명한다."""
    try:
        from securesystemslib.signer import CryptoSigner
        from securesystemslib.keys import import_ed25519_privatekey_from_file
        from tuf.api.metadata import (
            Metadata, Root, Targets, Snapshot, Timestamp,
            TargetFile, MetaFile,
        )
        from tuf.api.serialization.json import JSONSerializer
    except ImportError:
        print("WARNING: tuf/securesystemslib not available, using manual signing")
        _sign_metadata_manual(metadata_dir, keys_dir, targets_dir, app_name, version)
        return

    metadata_dir.mkdir(parents=True, exist_ok=True)
    serializer = JSONSerializer(compact=False)

    # 키 로드
    key_path = keys_dir / "instadmpro"
    private_key = import_ed25519_privatekey_from_file(str(key_path))
    signer = CryptoSigner.from_priv_key_uri(
        f"file:{key_path}?encrypted=false",
        public_key=None,
    )

    # 기존 메타데이터 로드 또는 새로 생성
    targets_md_path = metadata_dir / "targets.json"
    if targets_md_path.exists():
        targets_md = Metadata[Targets].from_file(str(targets_md_path))
    else:
        # 새 메타데이터 초기화 (root.json에서 시작)
        print("No existing targets.json found, initializing from scratch")
        _sign_metadata_manual(metadata_dir, keys_dir, targets_dir, app_name, version)
        return

    # 새 타겟 파일 등록
    archive_name = f"{app_name}-{version}.tar.gz"
    archive_path = targets_dir / archive_name
    if archive_path.exists():
        target_file = TargetFile.from_file(str(archive_path), str(archive_name))
        targets_md.signed.targets[archive_name] = target_file
        targets_md.signed.version += 1
        targets_md.signed.expires = datetime.now(timezone.utc) + timedelta(days=365)

        targets_md.sign(signer)
        targets_md.to_file(str(targets_md_path), serializer)
        print(f"targets.json updated with {archive_name}")

    # snapshot 업데이트
    snapshot_path = metadata_dir / "snapshot.json"
    if snapshot_path.exists():
        snapshot_md = Metadata[Snapshot].from_file(str(snapshot_path))
        snapshot_md.signed.meta["targets.json"] = MetaFile(
            version=targets_md.signed.version
        )
        snapshot_md.signed.version += 1
        snapshot_md.signed.expires = datetime.now(timezone.utc) + timedelta(days=365)
        snapshot_md.sign(signer)
        snapshot_md.to_file(str(snapshot_path), serializer)

    # timestamp 업데이트
    timestamp_path = metadata_dir / "timestamp.json"
    if timestamp_path.exists():
        timestamp_md = Metadata[Timestamp].from_file(str(timestamp_path))
        timestamp_md.signed.snapshot_meta = MetaFile(
            version=snapshot_md.signed.version
        )
        timestamp_md.signed.version += 1
        timestamp_md.signed.expires = datetime.now(timezone.utc) + timedelta(days=365)
        timestamp_md.sign(signer)
        timestamp_md.to_file(str(timestamp_path), serializer)

    print("All metadata signed and updated")


def _sign_metadata_manual(metadata_dir: Path, keys_dir: Path, targets_dir: Path, app_name: str, version: str):
    """tufup Repository API를 사용하여 메타데이터를 업데이트한다."""
    try:
        from tufup.repo import Repository

        metadata_dir.mkdir(parents=True, exist_ok=True)

        # tufup 리포지토리 설정
        repo_dir = metadata_dir.parent  # gh-pages/ 루트
        repo_metadata_dir = metadata_dir
        repo_targets_dir = targets_dir

        # Repository를 직접 구성하기 어려우므로, 직접 JSON 조작
        _update_metadata_json(metadata_dir, keys_dir, targets_dir, app_name, version)

    except Exception as e:
        print(f"Manual signing fallback: {e}")
        _update_metadata_json(metadata_dir, keys_dir, targets_dir, app_name, version)


def _update_metadata_json(metadata_dir: Path, keys_dir: Path, targets_dir: Path, app_name: str, version: str):
    """직접 JSON 파일을 편집하고 서명한다 (최후의 폴백)."""
    import nacl.signing

    metadata_dir.mkdir(parents=True, exist_ok=True)

    # 키 로드 (securesystemslib 포맷의 JSON)
    key_path = keys_dir / "instadmpro"
    with open(key_path) as f:
        key_data = json.load(f)
    private_hex = key_data["keyval"]["private"]
    public_hex = key_data["keyval"]["public"]
    keyid = key_data["keyid"]

    signing_key = nacl.signing.SigningKey(bytes.fromhex(private_hex))

    archive_name = f"{app_name}-{version}.tar.gz"
    archive_path = targets_dir / archive_name

    expires = (datetime.now(timezone.utc) + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # --- targets.json ---
    targets_path = metadata_dir / "targets.json"
    if targets_path.exists():
        with open(targets_path) as f:
            targets_data = json.load(f)
        targets_signed = targets_data["signed"]
    else:
        targets_signed = {
            "_type": "targets",
            "spec_version": "1.0.31",
            "version": 0,
            "expires": expires,
            "targets": {},
        }

    if archive_path.exists():
        file_info = compute_hash(archive_path)
        targets_signed["targets"][archive_name] = file_info

    targets_signed["version"] = targets_signed.get("version", 0) + 1
    targets_signed["expires"] = expires

    targets_canonical = _canonical_json(targets_signed)
    targets_sig = signing_key.sign(targets_canonical.encode()).signature.hex()
    targets_data = {
        "signatures": [{"keyid": keyid, "sig": targets_sig}],
        "signed": targets_signed,
    }
    with open(targets_path, "w") as f:
        json.dump(targets_data, f, indent=1)
    print(f"targets.json v{targets_signed['version']} written")

    # --- snapshot.json ---
    snapshot_path = metadata_dir / "snapshot.json"
    if snapshot_path.exists():
        with open(snapshot_path) as f:
            snap_data = json.load(f)
        snap_signed = snap_data["signed"]
    else:
        snap_signed = {
            "_type": "snapshot",
            "spec_version": "1.0.31",
            "version": 0,
            "expires": expires,
            "meta": {},
        }

    snap_signed["meta"]["targets.json"] = {"version": targets_signed["version"]}
    snap_signed["version"] = snap_signed.get("version", 0) + 1
    snap_signed["expires"] = expires

    snap_canonical = _canonical_json(snap_signed)
    snap_sig = signing_key.sign(snap_canonical.encode()).signature.hex()
    snap_data = {
        "signatures": [{"keyid": keyid, "sig": snap_sig}],
        "signed": snap_signed,
    }
    with open(snapshot_path, "w") as f:
        json.dump(snap_data, f, indent=1)
    print(f"snapshot.json v{snap_signed['version']} written")

    # --- timestamp.json ---
    ts_path = metadata_dir / "timestamp.json"
    if ts_path.exists():
        with open(ts_path) as f:
            ts_data = json.load(f)
        ts_signed = ts_data["signed"]
    else:
        ts_signed = {
            "_type": "timestamp",
            "spec_version": "1.0.31",
            "version": 0,
            "expires": expires,
            "meta": {},
        }

    ts_signed["meta"]["snapshot.json"] = {"version": snap_signed["version"]}
    ts_signed["version"] = ts_signed.get("version", 0) + 1
    ts_signed["expires"] = expires

    ts_canonical = _canonical_json(ts_signed)
    ts_sig = signing_key.sign(ts_canonical.encode()).signature.hex()
    ts_data = {
        "signatures": [{"keyid": keyid, "sig": ts_sig}],
        "signed": ts_signed,
    }
    with open(ts_path, "w") as f:
        json.dump(ts_data, f, indent=1)
    print(f"timestamp.json v{ts_signed['version']} written")

    # root.json은 변경 없으면 그대로 유지


def _canonical_json(obj) -> str:
    """TUF 표준 canonical JSON 직렬화."""
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def main():
    args = parse_args()
    bundle_dir = Path(args.bundle_dir)
    version = args.version.lstrip("v")
    keys_dir = Path(args.keys_dir)
    metadata_dir = Path(args.metadata_dir)
    targets_dir = Path(args.targets_dir)

    if not bundle_dir.exists():
        print(f"ERROR: Bundle directory not found: {bundle_dir}")
        return

    print(f"=== tufup CI: version {version} ===")

    # 1. 아카이브 생성
    archive_path = create_archive(bundle_dir, targets_dir, "InstagramDMPro", version)

    # 2. 메타데이터 서명
    sign_metadata(metadata_dir, keys_dir, targets_dir, "InstagramDMPro", version)

    print(f"\n=== Done ===")
    print(f"Archive: {archive_path}")
    print(f"Metadata: {metadata_dir}")


if __name__ == "__main__":
    main()
