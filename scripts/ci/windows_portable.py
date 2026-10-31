"""Fail-closed manifest and ZIP for a Windows onedir build, never source data."""
import argparse
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import shutil
import stat
import zipfile

MANIFEST="portable-manifest.json"
README="""闲鱼助手 Windows x64 桌面版

解压整个 XianyuPilot 文件夹，双击 XianyuPilot.exe。
无需安装 Python、Node.js、Git 或浏览器运行时。不要单独移动 EXE。
全部业务数据、浏览器资料、日志和临时文件位于 EXE 旁的 data/。
请放在具有写权限的普通文件夹，移动或备份前从托盘彻底退出。
关闭主窗口会驻留托盘；右键托盘可打开、暂停/恢复或安全退出。
启动后显示原项目完整后台。首次使用请在闲鱼账号中添加并授权账号，再配置商品、AI 和发货规则。
未配置账号与规则时不会自动发货。实际平台能力以授权账号和官方响应为准。
本包尚未通过真实订单、干净 Windows 虚拟机、物理断电及完整 I/O 隔离验收。
请保留 _internal 和 licenses，不要删除运行组件；升级时保留完整 data/。
"""


def safe_name(name):
    path=PurePosixPath(name)
    return bool(name and not path.is_absolute() and '..' not in path.parts and '\\' not in name and ':' not in name
                and path.as_posix()==name)


def safe_payload(name):
    return safe_name(name) and not any(
        part.lower() in ('data','secrets','.git','.env') or part.lower().startswith('.env.')
        for part in PurePosixPath(name).parts)


def is_link(path):
    return path.is_symlink() or bool(getattr(path.lstat(),'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400))


def inventory(root):
    if is_link(root):
        raise ValueError('package root cannot be a link')
    files={}
    for path in sorted(root.rglob('*')):
        if is_link(path):
            raise ValueError('package cannot contain links')
        if not path.is_file():
            continue
        name=path.relative_to(root).as_posix()
        if not safe_payload(name):
            raise ValueError('private or unsafe payload')
        if name!=MANIFEST:
            with path.open('rb') as stream:
                files[name]=hashlib.file_digest(stream,'sha256').hexdigest()
    if len({name.casefold() for name in files})!=len(files):
        raise ValueError('case-colliding paths')
    return files


def validate_required(files):
    required={'XianyuPilot.exe','_internal/web/index.html','_internal/app/desktop_migrations/006_full_console.sql',
              '_internal/app/resources/china_address_dict.json','PORTABLE-README.txt'}
    if not required<=files.keys():
        raise ValueError('portable build is incomplete')
    names={PurePosixPath(name).name.lower() for name in files}
    if names & {'icu.dll','icuin.dll','icuuc.dll'}:
        raise ValueError('bundled ICU must not shadow the Windows system runtime')
    for name in ('qtwebengineprocess.exe','qt6webenginecore.dll','qtwebengine_resources.pak','icudtl.dat','en-us.pak','vcruntime140.dll','msvcp140.dll'):
        if name not in names:
            raise ValueError('missing bundled runtime: '+name)
    if not any(re.fullmatch(r'python3\d{1,2}\.dll',name) for name in names):
        raise ValueError('missing independent Python runtime')
    if not any(name.startswith('_internal/web/assets/') for name in files):
        raise ValueError('missing Vue assets')


def record(root,revision):
    if not re.fullmatch(r'[0-9a-f]{40}',revision):
        raise ValueError('build must identify the exact source revision')
    if is_link(root):
        raise ValueError('package root cannot be a link')
    (root/'PORTABLE-README.txt').write_text(README,encoding='utf-8')
    files=inventory(root)
    validate_required(files)
    data={'format':1,'revision':revision,'platform':'windows-x64','distribution':'onedir','files':files,
          'realDeliveryEnabledByDefault':False,'manualAcceptancePending':['clean-vm','file-io-isolation','native-tray','real-order','physical-power-loss']}
    (root/MANIFEST).write_text(json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    return data


def verify(root):
    path=root/MANIFEST
    if path.is_symlink():
        raise ValueError('manifest cannot be a link')
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('format')!=1 or data.get('distribution')!='onedir' or data.get('platform')!='windows-x64' or not re.fullmatch(r'[0-9a-f]{40}',data.get('revision','')):
        raise ValueError('invalid portable manifest')
    files=inventory(root)
    validate_required(files)
    if data.get('files')!=files:
        raise ValueError('portable files changed after verification')
    return data


def package(root,destination,standalone=None):
    data=verify(root)
    destination.mkdir(parents=True,exist_ok=True)
    archive=destination/'XianyuPilot-Windows-x64.zip'
    if destination.is_symlink() or archive.is_symlink():
        raise ValueError('ZIP output cannot be a link')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for name in sorted([*data['files'],MANIFEST]):
            bundle.write(root/name,'XianyuPilot/'+name)
    # Read compressed bytes back; don't trust a successful write alone.
    with zipfile.ZipFile(archive) as bundle:
        expected={"XianyuPilot/"+name for name in [*data['files'],MANIFEST]}
        if set(bundle.namelist())!=expected or bundle.testzip() is not None:
            raise ValueError('ZIP verification failed')
        for name,digest in data['files'].items():
            with bundle.open('XianyuPilot/'+name) as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=digest:
                    raise ValueError('ZIP payload checksum mismatch')
    with archive.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    files={archive.name:digest}
    if standalone is not None:
        executable=destination/'XianyuPilot.exe'
        if is_link(standalone) or executable.is_symlink() or (executable.exists() and is_link(executable)):
            raise ValueError('standalone executable cannot be a link')
        for name in ('windows-build-info.json','SHA256SUMS.txt'):
            if (destination/name).is_symlink():
                raise ValueError('release metadata cannot be a link')
        shutil.copyfile(standalone,destination/'XianyuPilot.exe')
        with (destination/'XianyuPilot.exe').open('rb') as stream:
            files['XianyuPilot.exe']=hashlib.file_digest(stream,'sha256').hexdigest()
        (destination/'windows-build-info.json').write_text(json.dumps({'revision':data['revision'],'files':files},sort_keys=True,indent=2)+'\n',encoding='utf-8')
    (destination/'SHA256SUMS.txt').write_text(''.join(f'{value}  {name}\n' for name,value in files.items()),encoding='utf-8')
    return archive


def verify_archive(directory,revision):
    """Reverify a downloaded Windows ZIP on the Linux release runner, without extracting."""
    if not re.fullmatch(r'[0-9a-f]{40}',revision):
        raise ValueError('release must identify the exact source revision')
    archive=directory/'XianyuPilot-Windows-x64.zip'
    checksum=directory/'SHA256SUMS.txt'
    for path in (directory,archive,checksum):
        if is_link(path):
            raise ValueError('release paths cannot be links')
    with archive.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    lines=checksum.read_text(encoding='utf-8').splitlines()
    if f'{digest}  {archive.name}' not in lines or len(lines)!=len(set(lines)) or any(
        not re.fullmatch(r'[0-9a-f]{64}  (?:XianyuPilot-Windows-x64\.zip|XianyuPilot\.exe)',line) for line in lines):
        raise ValueError('portable ZIP checksum mismatch')
    with zipfile.ZipFile(archive) as bundle:
        entries=bundle.infolist()
        names=[entry.filename for entry in entries]
        if len(names)!=len({name.casefold() for name in names}) or any(
            not name.startswith('XianyuPilot/') or not safe_payload(name.removeprefix('XianyuPilot/'))
            or stat.S_ISLNK(entry.external_attr >> 16) or entry.is_dir() for name,entry in zip(names,entries)):
            raise ValueError('unsafe or duplicate portable ZIP paths')
        if 'XianyuPilot/'+MANIFEST not in names:
            raise ValueError('portable manifest is missing')
        manifest=bundle.getinfo('XianyuPilot/'+MANIFEST)
        if manifest.file_size>5_000_000:
            raise ValueError('portable manifest is too large')
        data=json.loads(bundle.read(manifest))
        if not isinstance(data,dict) or data.get('format')!=1 or data.get('revision')!=revision \
                or data.get('platform')!='windows-x64' or data.get('distribution')!='onedir' \
                or data.get('realDeliveryEnabledByDefault') is not False:
            raise ValueError('portable ZIP belongs to another revision or distribution')
        files=data.get('files')
        if not isinstance(files,dict) or any(
            not safe_payload(name) or not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{64}',value)
            for name,value in files.items()):
            raise ValueError('invalid portable file inventory')
        validate_required(files)
        if set(names)!={'XianyuPilot/'+name for name in [*files,MANIFEST]}:
            raise ValueError('portable ZIP inventory mismatch')
        for name,value in files.items():
            with bundle.open('XianyuPilot/'+name) as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=value:
                    raise ValueError('portable ZIP payload checksum mismatch')
    return archive,data


def verify_release(directory,revision):
    archive,data=verify_archive(directory,revision)
    exe=directory/'XianyuPilot.exe'
    build_info=directory/'windows-build-info.json'
    if is_link(exe) or is_link(build_info):
        raise ValueError('Windows release assets cannot be links')
    hashes={}
    for path in (archive,exe):
        with path.open('rb') as stream:
            hashes[path.name]=hashlib.file_digest(stream,'sha256').hexdigest()
    metadata=json.loads(build_info.read_text(encoding='utf-8'))
    if metadata!={'revision':revision,'files':hashes}:
        raise ValueError('standalone executable belongs to another revision or changed')
    if (directory/'SHA256SUMS.txt').read_text(encoding='utf-8')!=''.join(f'{value}  {name}\n' for name,value in hashes.items()):
        raise ValueError('Windows release checksums do not cover both EXE and ZIP')
    return archive,exe,data


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['record','verify','package'])
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('release/windows'))
    parser.add_argument('--standalone-exe',type=Path)
    args=parser.parse_args()
    if args.action=='record':record(args.directory,os.environ.get('GITHUB_SHA',''))
    elif args.action=='verify':verify(args.directory)
    else:print(package(args.directory,args.output,args.standalone_exe))
