"""Run the original console in Qt before spending time freezing both EXEs."""
from pathlib import Path
import shutil

from app.core import paths

paths.SOURCE_ROOT=Path('.tmp/qt-source-console').resolve()

from app.portable.bootstrap import configure_environment,configure_logging
from app.portable.webengine_check import check


if __name__=='__main__':
    root,locations=configure_environment()
    handler=configure_logging(root)
    try:
        result=check(root,locations,Path('apps/web/dist').resolve(),19177)
        if result:
            destination=Path('reports/windows-portable-diagnostics/source')
            destination.mkdir(parents=True,exist_ok=True)
            for name in ('webengine-check.json','webengine-check.png','desktop.log'):
                source=root/'logs'/name
                if source.is_file():shutil.copy2(source,destination/name)
            print((root/'logs/webengine-check.json').read_text(encoding='utf-8'))
    finally:
        handler.close()
    raise SystemExit(result)
