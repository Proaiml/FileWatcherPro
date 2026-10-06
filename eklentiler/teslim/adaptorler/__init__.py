"""Hedef adaptörleri. Yeni bir hedef türü eklemek için temel.HedefAdaptoru'ndan türetip ADAPTORLER'e kaydedin."""
from .betik import BetikAdaptoru
from .controlm import ControlMAdaptoru
from .genel_http import GenelHttpAdaptoru

ADAPTORLER = {"CONTROLM": ControlMAdaptoru, "HTTP": GenelHttpAdaptoru, "BETIK": BetikAdaptoru}


def adaptor_kur(hedef: dict):
    sinif = ADAPTORLER.get(str(hedef["tur"]).upper())
    if sinif is None:
        raise ValueError(f"bilinmeyen hedef türü: {hedef['tur']}")
    return sinif(hedef)
