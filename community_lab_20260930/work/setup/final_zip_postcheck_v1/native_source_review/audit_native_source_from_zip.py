#!/usr/bin/env python3
"""Read actual ZIP source/native bytes only. Never extract, execute or score."""
from __future__ import annotations
import argparse
from collections import Counter
import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import struct
import sys
import tarfile
import time
import zipfile

sys.dont_write_bytecode = True


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest_stream(stream):
    h, count, prefix = hashlib.sha256(), 0, b''
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        if len(prefix) < 32:
            prefix += block[:32 - len(prefix)]
        h.update(block)
        count += len(block)
    return {'sha256': h.hexdigest(), 'bytes': count, 'prefix32_hex': prefix.hex()}


def safe(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and not any(v in ('', '.', '..') for v in name.split('/')) and '\\' not in name and '\x00' not in name and ':' not in name and p.as_posix() == name


def macho_arm64_executable(info):
    b = bytes.fromhex(info['prefix32_hex'])
    return len(b) >= 16 and struct.unpack('<I', b[:4])[0] == 0xFEEDFACF and struct.unpack('<I', b[4:8])[0] == 0x0100000C and struct.unpack('<I', b[12:16])[0] == 2


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    a = p.parse_args()
    output = a.output_dir.resolve()
    if output != Path(__file__).resolve().parent:
        raise ValueError('This delegated audit may write only beside its own source')
    output.mkdir(parents=True, exist_ok=True)
    archive = a.archive.resolve()
    before = archive.stat()
    start, utc_start = time.perf_counter(), now()
    checks, zip_inputs, tar_observed, native, licenses = [], {}, {}, [], []

    def check(name, value, detail=None):
        checks.append({'check': name, 'status': 'PASS' if value else 'FAIL', 'detail': detail})

    try:
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
            check('zip_entry_names_unique', len(names) == len(set(names)))
            check('zip_entry_paths_canonical', all(safe(n) for n in names))
            forbidden = [n for n in names if PurePosixPath(n).suffix.lower() == '.pdf' or any(c in {'.venv', 'venv', '.git'} for c in PurePosixPath(n).parts)]
            check('zip_has_no_pdf_venv_git_metadata', not forbidden, forbidden)

            def read_json(name):
                data = z.read(name)
                zip_inputs[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
                return json.loads(data)

            def zip_digest(name):
                with z.open(name) as f:
                    d = digest_stream(f)
                info = z.getinfo(name)
                d.update(mode_octal=oct(info.external_attr >> 16), mode=info.external_attr >> 16, create_system=info.create_system)
                zip_inputs[name] = d
                return d

            manifest = read_json('provenance/locked_source_trees_manifest.json')
            source_lock = read_json('provenance/SOURCE_LOCK.json')
            native_lock = read_json('work/setup/native/binary-lock-native.json')
            native_source_lock = read_json('work/setup/native/source-lock-native.json')
            build_attempts = read_json('work/setup/native/build-attempts.json')
            highway_build = read_json('work/setup/python_sources/highway-build.json')
            highway_copy = read_json('provenance/native_binaries/highway_binary.json')
            index = read_json('provenance/replay_index.json')
            delivery_manifest = read_json('DELIVERY_MANIFEST.json')
            delivery_by_path = {v['path']: v for v in delivery_manifest['files']}
            check('zip_payload_entry_set_matches_delivery_manifest', set(names) == set(delivery_by_path) | {'DELIVERY_MANIFEST.json'})
            check('source_manifest_file_paths_unique', len({v['path'] for v in manifest['files']}) == len(manifest['files']))
            expected = {v['path']: v for v in manifest['files']}
            tar_path = manifest['archive']
            check('source_manifest_declares_canonical_tar_path', tar_path == 'provenance/locked_source_trees.tar.gz')
            tar_hash = zip_digest(tar_path)
            check('actual_tar_blob_matches_source_manifest', tar_hash['sha256'] == manifest['sha256'] and tar_hash['bytes'] == manifest['bytes'], tar_hash)
            check('actual_tar_blob_matches_zip_delivery_manifest', tar_hash['sha256'] == delivery_by_path[tar_path]['sha256'] and tar_hash['bytes'] == delivery_by_path[tar_path]['bytes'])

            with z.open(tar_path) as zipped_tar:
                with tarfile.open(fileobj=zipped_tar, mode='r|gz') as t:
                    for member in t:
                        name = member.name
                        if name in tar_observed:
                            raise ValueError('Duplicate source tar member: ' + name)
                        if not safe(name) or PurePosixPath(name).parts[0] != 'external' or not member.isfile():
                            raise ValueError('Unsafe/nonregular source tar member: ' + name)
                        if PurePosixPath(name).suffix.lower() == '.pdf' or any(c in {'.git', '.venv', 'venv', '__pycache__', 'build'} for c in PurePosixPath(name).parts) or PurePosixPath(name).suffix in {'.o', '.pyc', '.so', '.dylib'}:
                            raise ValueError('Excluded content present in source tar: ' + name)
                        stream = t.extractfile(member)
                        if stream is None:
                            raise ValueError('Missing tar member contents: ' + name)
                        with stream:
                            observed = digest_stream(stream)
                        observed.update(mode=member.mode, mode_octal=oct(member.mode))
                        tar_observed[name] = observed
                        entry = expected.get(name)
                        check('source_tar_member_matches_manifest:' + name, entry is not None and observed['sha256'] == entry['sha256'] and observed['bytes'] == entry['bytes'])
            check('source_tar_exact_manifest_member_set', set(tar_observed) == set(expected), {'actual': len(tar_observed), 'expected': len(expected), 'missing': sorted(set(expected) - set(tar_observed)), 'extra': sorted(set(tar_observed) - set(expected))})

            sources = {v['id']: v for v in source_lock['sources']}
            check('source_lock_ids_unique', len(sources) == len(source_lock['sources']))
            for src in source_lock['sources']:
                sid, prefix = src['id'], src['path'].rstrip('/') + '/'
                required = src.get('license_path')
                candidates = [required] if required else [n for n in tar_observed if n.startswith(prefix) and PurePosixPath(n).name.lower().startswith(('license', 'copying'))]
                matches = [n for n in candidates if n in tar_observed and tar_observed[n]['sha256'] == src['license_sha256']]
                check('locked_upstream_license_in_actual_tar:' + sid, bool(matches), {'candidates': candidates, 'matching_paths': matches})
                copy_name = 'provenance/licenses/' + sid + ('_License.txt' if sid == 'snap' else '_LICENSE')
                d = zip_digest(copy_name)
                check('delivered_license_copy_matches_source_lock:' + sid, d['sha256'] == src['license_sha256'])
                licenses.append({'id': sid, 'commit': src['commit'], 'declared_license': src['license'], 'license_sha256': src['license_sha256'], 'tar_paths': matches, 'zip_license_copy': copy_name})

            for src in native_source_lock['sources']:
                final = sources.get(src['id'], {})
                check('native_source_lock_matches_final_source_lock:' + src['id'], all(src.get(k) == final.get(k) for k in ['id', 'path', 'commit', 'license_sha256']))
            for binary in native_lock:
                name, sid = binary['path'], binary['id']
                observed = tar_observed.get(name)
                check('native_binary_present_and_locked_in_actual_source_tar:' + sid, observed is not None and observed['sha256'] == binary['sha256'] and observed['bytes'] == binary['size'])
                check('native_tar_binary_executable_and_arm64:' + sid, observed is not None and bool(observed['mode'] & 0o111) and macho_arm64_executable(observed))
                check('native_build_success_command_preserved:' + sid, any(v['id'] == sid and v['returncode'] == 0 and v['command'] == ['make', '-j1'] for v in build_attempts))
                record = {'id': sid, 'path': name, 'tar': observed, 'locked_sha256': binary['sha256'], 'locked_bytes': binary['size']}
                if name in index['files']:
                    d = zip_digest(name)
                    entry = index['files'][name]
                    check('native_zip_binary_binds_replay_index_and_native_lock:' + sid, d['sha256'] == binary['sha256'] == entry['sha256'] and d['bytes'] == binary['size'] == entry['size_bytes'])
                    check('native_zip_binary_unix_regular_executable:' + sid, d['create_system'] == 3 and stat.S_ISREG(d['mode']) and bool(d['mode'] & 0o111))
                    record.update(zip=d, replay_index_binding='VERIFIED')
                else:
                    check('only_lfr_generation_binary_may_be_outside_score_replay_index', sid == 'lfr')
                    record['replay_index_binding'] = 'NOT_INDEXED_GENERATION_DEPENDENCY; actual source tar is native-locked and executable'
                native.append(record)

            hpath, hcopy = highway_build['binary'], highway_copy['delivery_copy']
            hd, hc = zip_digest(hpath), zip_digest(hcopy)
            hi = index['files'][hpath]
            check('highway_zip_canonical_and_copy_binds_all_locked_hashes', hd['sha256'] == hc['sha256'] == highway_build['binary_sha256'] == highway_copy['sha256'] == hi['sha256'] and hd['bytes'] == hc['bytes'] == highway_copy['bytes'] == hi['size_bytes'])
            check('highway_copy_source_path_binds_canonical_binary', highway_copy['source_relative_path'] == hpath)
            check('highway_build_commit_matches_locked_source', highway_build['source_commit'] == sources['highway_native_reference']['commit'])
            check('highway_build_and_help_commands_preserved', len(highway_build.get('commands', [])) == 3 and highway_build['commands'][-1] == [hpath, '--help'])
            for name, d in [(hpath, hd), (hcopy, hc)]:
                check('highway_zip_regular_executable_arm64:' + name, d['create_system'] == 3 and stat.S_ISREG(d['mode']) and bool(d['mode'] & 0o111) and macho_arm64_executable(d))
            native.append({'id': 'highway', 'path': hpath, 'zip': hd, 'copy_path': hcopy, 'copy': hc, 'tar_policy': 'build directory omitted from source tar; actual measured binary delivered as canonical indexed ZIP file and provenance copy', 'replay_index_binding': 'VERIFIED'})

            for name, d in list(zip_inputs.items()):
                if name == 'DELIVERY_MANIFEST.json':
                    continue
                dm = delivery_by_path.get(name, {})
                check('audited_zip_input_matches_delivery_manifest:' + name, d['sha256'] == dm.get('sha256') and d['bytes'] == dm.get('bytes'))
            skill_license_entries = [n for n in names if n.startswith('provenance/skill_guidance/') and PurePosixPath(n).name.lower().startswith(('license', 'copying'))]
            for name in skill_license_entries:
                d = zip_digest(name)
                dm = delivery_by_path[name]
                check('skill_license_present_and_manifest_bound:' + name, d['bytes'] > 0 and d['sha256'] == dm['sha256'] and d['bytes'] == dm['bytes'])
    except Exception as exc:
        check('audit_fatal_exception', False, type(exc).__name__ + ': ' + str(exc))
    after = archive.stat()
    check('actual_zip_stat_unchanged_through_audit', (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns))
    counts = dict(Counter(v['status'] for v in checks))
    report = {'audit_started_utc': utc_start, 'audit_finished_utc': now(), 'wall_seconds': time.perf_counter() - start, 'tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'actual_command': [sys.executable, *sys.argv], 'archive': str(archive), 'archive_bytes': before.st_size, 'archive_mtime_ns': before.st_mtime_ns, 'scope': 'Read actual ZIP members and source tar streams; no extraction, inference, native execution, training, scoring, model loading, full ZIP SHA256 or full payload hash pass.', 'observed_checks_pass': counts.get('FAIL', 0) == 0, 'check_counts': counts, 'source_tar_member_count': len(tar_observed), 'source_tar_members': tar_observed, 'native_binaries': native, 'locked_licenses': licenses, 'audited_zip_inputs': zip_inputs, 'checks': checks, 'limitations': ['ZIP-wide CRC/SHA and all formal run/checkpoint/report/closeout bindings are owned by the parent audit.', 'Eight source-license byte hashes are checked against delivered locks; this is preservation, not a fresh legal determination.', 'Mac ARM64 executable header, bytes and archived permission bits verified without executing them or claiming portability to another platform.', 'LFR generator binary is delivered inside the source tar and native lock; it is not a dependency of the saved-cover offline scoring index.']}
    (output / 'audit.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    lines = ['# 实际 ZIP 源码、许可证与原生 binary 独立审计', '', '结论：' + ('PASS' if report['observed_checks_pass'] else 'FAIL') + '。只读实际 DELIVERY.zip，不依据现存 source tree 推断。', '', '开始：' + utc_start + '；结束：' + report['audit_finished_utc'] + '；墙钟：' + str(report['wall_seconds']) + '秒。', '', '工具 SHA-256：`' + report['tool_sha256'] + '`。', '', '实际命令：`' + ' '.join(report['actual_command']) + '`。', '', '检查数：`' + json.dumps(counts) + '`；源码 tar 实读成员：' + str(len(tar_observed)) + '。', '', '- 核对 source tar 整体哈希、逐成员哈希/大小、精确成员集合及不含 PDF/环境/git/build objects。', '- 核对全部8项上游许可证在真实 tar 和独立 license 副本中匹配 SOURCE_LOCK。', '- 核对 LFR/SNAP/Highway 实际 Mach-O ARM64 executable 字节、native/index 锁及归档执行权限。', '- LFR binary 在 tar 中；SNAP 在 tar 和 ZIP 中；Highway 的 build 目录不在 tar，实测 binary 在 ZIP 的 canonical path 与 provenance copy 中。', '- 未重算整个 ZIP 哈希、未执行 binary、未测量或重评分；其余任务/模型/四报告/closeout由父审计负责。', '', '失败检查：', '']
    lines.extend('- `' + v['check'] + '`：' + str(v['detail']) for v in checks if v['status'] == 'FAIL')
    if not any(v['status'] == 'FAIL' for v in checks):
        lines.append('无。')
    (output / 'AUDIT_ZH.md').write_text('\n'.join(lines) + '\n')
    own = []
    for name in ['audit_native_source_from_zip.py', 'audit.json', 'AUDIT_ZH.md']:
        b = (output / name).read_bytes()
        own.append({'path': name, 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()})
    (output / 'MANIFEST.json').write_text(json.dumps({'created_at_utc': now(), 'files': own}, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ['observed_checks_pass', 'check_counts', 'source_tar_member_count', 'wall_seconds', 'tool_sha256']}))
    return 0 if report['observed_checks_pass'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
