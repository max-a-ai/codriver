"""codriver: an in-car panel for starting demos and checking sensor health.

python -m codriver            start the panel
python -m codriver --help     options
"""

from .app import App
from .config import Config, load_config

__all__ = ["App", "Config", "load_config"]
__version__ = "0.1.0"
