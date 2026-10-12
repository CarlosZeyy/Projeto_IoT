"""Deterministic image preprocessing shared by training and edge (ADR-004).

No torch, torchvision or timm here (R-12): only numpy and Pillow.
"""

from qc_preprocess.errors import InvalidImageError
from qc_preprocess.image import ACCEPTED_FORMATS, MAX_ASPECT_RATIO, MAX_PIXELS, load_image
from qc_preprocess.params import PreprocessParams
from qc_preprocess.transform import preprocess

__version__ = "0.2.0"

__all__ = [
    "ACCEPTED_FORMATS",
    "MAX_ASPECT_RATIO",
    "MAX_PIXELS",
    "InvalidImageError",
    "PreprocessParams",
    "__version__",
    "load_image",
    "preprocess",
]
