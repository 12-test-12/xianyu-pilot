"""A portable, per-installation encryption key; never use the server dev key."""
import os
from .paths import contained_data_path, data_directory


def encryption_secret():
    path=contained_data_path(data_directory(),'profiles/credentials.key')
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd,'wb') as stream:
            stream.write(os.urandom(32))
            stream.flush()
            os.fsync(stream.fileno())
    value=path.read_bytes()
    if len(value)!=32:
        raise RuntimeError('桌面凭据密钥损坏，请保留 data 并从备份恢复')
    return value.hex()
