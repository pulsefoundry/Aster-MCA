import importlib.util
from pathlib import Path
import sys

def get_capture():
    name='aster_sparse'
    if name not in sys.modules:
        folder=(Path(__file__).resolve().parent/'sparse' if getattr(sys,'frozen',False)
                else Path(__file__).resolve().parent.parent/'at32-sparse')
        spec=importlib.util.spec_from_file_location(name,folder/'__init__.py',submodule_search_locations=[str(folder)])
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    from aster_sparse.capture import run
    return run
