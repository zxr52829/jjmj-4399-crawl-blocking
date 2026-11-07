#!/usr/bin/env python3
"""
restore_paths.py — 把 Cocos 镜像里的 UUID 文件名还原成可读路径

原理：
    bundle 的 config.json 里 paths 字段就是原始路径表：
        "0": ["weinmj/static/wein/ico_zjzs_4jp", 1, 1]
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ 原始路径
    uuids[0] 对应这个路径的资源。

    所以映射关系：
        paths[i][0]  <->  uuids[i]
        再经 decompress_uuid 得到实际文件名里的 id

    还原后按 paths 的目录结构重建目录树。

用法：
    python restore_paths.py <mirror_dir> [--out=restored]
"""
import json
import os
import re
import shutil
import sys

B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
V = [-1] * 128
for _i, _c in enumerate(B64):
    V[ord(_c)] = _i


def decompress_uuid(u):
    raw, _, suffix = u.partition('@')
    if len(raw) != 22:
        return u
    hexs = raw[:2]
    for i in range(2, 22, 2):
        a = V[ord(raw[i])] if ord(raw[i]) < 128 else -1
        b = V[ord(raw[i + 1])] if ord(raw[i + 1]) < 128 else -1
        if a < 0 or b < 0:
            return u
        hexs += format(a >> 2, 'x')
        hexs += format(((a & 3) << 2) | (b >> 4), 'x')
        hexs += format(b & 0xF, 'x')
    out = '%s-%s-%s-%s-%s' % (hexs[0:8], hexs[8:12], hexs[12:16], hexs[16:20], hexs[20:])
    return out + ('@' + suffix if suffix else '')


def safe(seg):
    """路径段安全化"""
    seg = re.sub(r'[<>:"|?*\\]', '_', seg)
    return seg.strip('. ') or '_'


def main():
    pos = [a for a in sys.argv[1:] if not a.startswith('--')]
    out_name = 'restored'
    for a in sys.argv[1:]:
        if a.startswith('--out='):
            out_name = a.split('=', 1)[1]
    if not pos:
        print(__doc__)
        return 1

    mirror = pos[0]
    outdir = os.path.join(mirror, out_name)

    # 收集所有 bundle config
    cfg_dir = os.path.join(mirror, 'assets')
    if not os.path.isdir(cfg_dir):
        print('[x] 找不到 assets 目录')
        return 2

    total_import = total_native = total_unmapped = 0
    manifest = []

    for bundle in sorted(os.listdir(cfg_dir)):
        bdir = os.path.join(cfg_dir, bundle)
        if not os.path.isdir(bdir):
            continue
        # 找 config.*.json
        cfgs = [f for f in os.listdir(bdir) if f.startswith('config.') and f.endswith('.json')]
        if not cfgs:
            continue
        try:
            with open(os.path.join(bdir, cfgs[0]), encoding='utf-8-sig') as f:
                conf = json.load(f)
        except Exception as e:
            print('  [!] %-20s config 读取失败' % bundle)
            continue

        uuids = conf.get('uuids') or []
        paths = conf.get('paths') or {}
        extmap = {}
        for ext, idxs in (conf.get('extensionMap') or {}).items():
            if isinstance(idxs, list):
                for i in idxs:
                    extmap[i] = ext.lstrip('.')

        # 建 uuid -> path 映射
        mapping = {}
        for k, v in paths.items():
            try:
                idx = int(k)
            except ValueError:
                continue
            if idx >= len(uuids) or not uuids[idx]:
                continue
            p = v[0] if isinstance(v, list) and v else None
            if not p or not isinstance(p, str):
                continue
            full = decompress_uuid(uuids[idx]).split('@')[0]
            mapping[full] = {'path': p, 'idx': idx, 'ext': extmap.get(idx)}

        if not mapping:
            continue

        # 扫描该 bundle 的 import / native 目录
        for kind in ('import', 'native'):
            kdir = os.path.join(bdir, kind)
            if not os.path.isdir(kdir):
                continue
            for root, _, files in os.walk(kdir):
                for fn in files:
                    # 文件名形如 {uuid}.{hash}.{ext}
                    m = re.match(r'^(.+?)\.([0-9a-z]{5,6})(?:\.([A-Za-z0-9]+))?$', fn)
                    if not m:
                        continue
                    uid, h, ext = m.group(1), m.group(2), m.group(3)
                    info = mapping.get(uid)
                    src = os.path.join(root, fn)

                    if not info:
                        total_unmapped += 1
                        continue

                    # 目标路径
                    rel = info['path'].replace('\\', '/')
                    parts = [safe(s) for s in rel.split('/') if s]
                    if not parts:
                        continue

                    if kind == 'import':
                        # import json 是资源本体描述
                        dst_rel = os.path.join(bundle, *parts) + '.json'
                        total_import += 1
                    else:
                        # native 是二进制（图片/音频/字体）
                        # 同名会冲突（多个 texture.png），用父目录名去重
                        e = ext or info['ext'] or 'bin'
                        # 若最后一段是通用名（texture/spriteFrame），前面补上父目录
                        GENERIC = {'texture', 'spriteFrame', 'texture2d', 'data'}
                        if len(parts) >= 2 and parts[-1] in GENERIC:
                            base = parts[:-1] + [info['path'].split('/')[-1] or parts[-1]]
                            # 继续沿用通用名，但目录已经区分了，保持原样即可
                        dst_rel = os.path.join(bundle, *parts) + '.' + e
                        total_native += 1

                        # 冲突检测
                        dst_tmp = os.path.join(outdir, dst_rel)
                        if os.path.exists(dst_tmp):
                            stem, dot, ex = dst_rel.rpartition('.')
                            dst_rel = '%s__%s.%s' % (stem, uid[:8], ex)

                    dst = os.path.join(outdir, dst_rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    if not os.path.exists(dst):
                        shutil.copy2(src, dst)
                    manifest.append((dst_rel, os.path.getsize(src)))

    print('还原完成:')
    print('  import json : %d' % total_import)
    print('  native 文件 : %d' % total_native)
    print('  未能映射    : %d' % total_unmapped)
    print('  输出目录    : %s' % os.path.abspath(outdir))

    # 写清单
    mf = os.path.join(outdir, '_restored.txt')
    manifest.sort()
    with open(mf, 'w', encoding='utf-8') as f:
        for rel, sz in manifest:
            f.write('%10d  %s\n' % (sz, rel))
    print('  清单        : %s (%d 项)' % (mf, len(manifest)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
