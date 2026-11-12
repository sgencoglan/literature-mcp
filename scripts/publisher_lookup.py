"""Yayıncı/veritabanı adını tek yerden çöz.

Kullanıcı fulltext listesinde "Diğer" değil gerçek kaynağı görmek istiyor
(örn. SAGE). Bu modül iki sinyali birleştirir:

1. Metadata'daki ``publisher`` alanı (Crossref/OpenAlex'ten gelen gerçek ad),
2. DOI ön eki — metadata yoksa bile hangi platformda yayımlandığını söyler.

``priority_platform`` ayrı tutulur: AGENTS.md beş öncelikli platformu
(Ovid LWW, ScienceDirect, SpringerLink, Wiley, Taylor & Francis) sıralar;
SAGE gibi bir yayıncı gerçek addır ama öncelikli platform değildir.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

# DOI ön eki -> (görünen yayıncı adı, iniş sayfası şablonu, öncelikli platform)
# Şablon ``{doi}`` ile doldurulur.
_PREFIX_TABLE: Dict[str, Tuple[str, str, Optional[str]]] = {
    # --- Beş öncelikli platform ---
    "10.1016": ("Elsevier", "https://doi.org/{doi}", "ScienceDirect"),
    "10.1007": ("Springer Nature", "https://link.springer.com/article/{doi}", "SpringerLink"),
    "10.1186": ("BMC", "https://link.springer.com/article/{doi}", "SpringerLink"),
    "10.1111": ("Wiley", "https://onlinelibrary.wiley.com/doi/{doi}", "Wiley"),
    "10.1002": ("Wiley", "https://onlinelibrary.wiley.com/doi/{doi}", "Wiley"),
    "10.4073": ("Campbell", "https://onlinelibrary.wiley.com/doi/{doi}", "Wiley"),
    "10.1080": ("Taylor & Francis", "https://www.tandfonline.com/doi/full/{doi}", "Taylor & Francis"),
    "10.1097": ("LWW", "https://doi.org/{doi}", "Ovid LWW"),
    # --- Diğer yayıncılar ---
    "10.1177": ("SAGE", "https://journals.sagepub.com/doi/{doi}", None),
    "10.3102": ("AERA", "https://journals.sagepub.com/doi/{doi}", None),
    "10.1037": ("APA", "https://doi.org/{doi}", None),
    "10.3389": ("Frontiers", "https://doi.org/{doi}", None),
    "10.3390": ("MDPI", "https://doi.org/{doi}", None),
    "10.1542": ("AAP", "https://doi.org/{doi}", None),
    "10.1353": ("Johns Hopkins UP", "https://doi.org/{doi}", None),
    "10.1093": ("Oxford University Press", "https://doi.org/{doi}", None),
    "10.1017": ("Cambridge University Press", "https://doi.org/{doi}", None),
    "10.1136": ("BMJ", "https://doi.org/{doi}", None),
    "10.1038": ("Nature Portfolio", "https://doi.org/{doi}", None),
    "10.1109": ("IEEE", "https://doi.org/{doi}", None),
    "10.1145": ("ACM", "https://doi.org/{doi}", None),
    "10.1287": ("INFORMS", "https://doi.org/{doi}", None),
    "10.1086": ("University of Chicago Press", "https://doi.org/{doi}", None),
    "10.1080/1045988x": ("Taylor & Francis", "https://www.tandfonline.com/doi/full/{doi}", "Taylor & Francis"),
    "10.20429": ("Georgia Southern University", "https://doi.org/{doi}", None),
    "10.46303": ("OpenEd Network", "https://doi.org/{doi}", None),
    "10.4073/csr": ("Campbell", "https://onlinelibrary.wiley.com/doi/{doi}", "Wiley"),
}

# Metadata'daki serbest metin yayıncı adını kanonik ada çevirir.
# Sıra önemli: daha özel kalıplar önce gelir.
_PUBLISHER_PATTERNS: list[Tuple[str, str, Optional[str]]] = [
    (r"lippincott|wolters|ovid", "LWW", "Ovid LWW"),
    (r"elsevier|science\s*direct", "Elsevier", "ScienceDirect"),
    (r"biomed central|\bbmc\b", "BMC", "SpringerLink"),
    (r"springer", "Springer Nature", "SpringerLink"),
    (r"taylor\s*(&|and|ve)\s*francis|routledge", "Taylor & Francis", "Taylor & Francis"),
    (r"aera|american educational research", "AERA", None),
    (r"\bsage\b", "SAGE", None),
    (r"blackwell", "Wiley", "Wiley"),
    (r"\bwiley\b", "Wiley", "Wiley"),
    (r"american psychological|\bapa\b", "APA", None),
    (r"frontiers", "Frontiers", None),
    (r"\bmdpi\b", "MDPI", None),
    (r"oxford university", "Oxford University Press", None),
    (r"cambridge university", "Cambridge University Press", None),
    (r"\bbmj\b|british medical", "BMJ", None),
    (r"nature", "Nature Portfolio", None),
    (r"american academy of pediatrics", "AAP", None),
    (r"johns hopkins", "Johns Hopkins UP", None),
    (r"\bieee\b", "IEEE", None),
    (r"\bacm\b|association for computing", "ACM", None),
    (r"informa", "Taylor & Francis", "Taylor & Francis"),
    (r"opened network", "OpenEd Network", None),
    (r"georgia southern", "Georgia Southern University", None),
]

# DOI ön eki -> indirme/erişim platformu. Yayıncı (dernek, kurum) ile platform
# aynı şey değildir: AERA bir dernektir, makaleleri SAGE Journals üzerinde
# yayımlanır; APA'nın platformu APA PsycNet'tir.
_PLATFORM_BY_PREFIX: Dict[str, str] = {
    "10.1177": "SAGE",
    "10.3102": "SAGE",
    "10.1037": "APA PsycNet",
    "10.1016": "ScienceDirect",
    "10.1007": "SpringerLink",
    "10.1186": "SpringerLink",
    "10.1111": "Wiley",
    "10.1002": "Wiley",
    "10.4073": "Wiley",
    "10.1080": "Taylor & Francis",
    "10.1097": "Ovid LWW",
    "10.3389": "Frontiers",
    "10.3390": "MDPI",
    "10.1542": "AAP",
    "10.1353": "Project MUSE",
    "10.1093": "Oxford Academic",
    "10.1017": "Cambridge Core",
    "10.1136": "BMJ",
    "10.1038": "Nature Portfolio",
    "10.1109": "IEEE Xplore",
    "10.1145": "ACM Digital Library",
}


def platform_for(doi: str) -> Optional[str]:
    """Makalenin erişildiği veritabanı/platform adı."""
    text = str(doi or "").strip().lower()
    prefix = text.split("/", 1)[0] if "/" in text else ""
    name = _PLATFORM_BY_PREFIX.get(prefix)
    if name is None:
        parts = text.split("/")
        if len(parts) >= 2:
            name = _PLATFORM_BY_PREFIX.get(f"{parts[0]}/{parts[1]}")
    return name


PRIORITY_PLATFORMS = (
    "Ovid LWW",
    "ScienceDirect",
    "SpringerLink",
    "Wiley",
    "Taylor & Francis",
)

UNKNOWN = "Bilinmiyor"

# Eski dosyalarda kalan ve gerçek yayıncı adı olmayan değerler.
_SENTINELS = {"diğer", "diger", "other", "unknown", "n/a", "bilinmiyor"}


def is_sentinel(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in _SENTINELS


def normalize_doi_prefix(doi: str) -> str:
    text = str(doi or "").strip().lower()
    return text.split("/", 1)[0] if "/" in text else ""


def from_doi(doi: str) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
    """DOI ön ekinden (ad, iniş URL'i, öncelikli platform) döndür."""
    text = str(doi or "").strip().lower()
    prefix = normalize_doi_prefix(text)
    entry = _PREFIX_TABLE.get(prefix)
    if entry is None:
        # Daha uzun ön ekler (örn. ``10.4073/csr``) için ilk iki parçayı dene.
        parts = text.split("/")
        if len(parts) >= 2:
            entry = _PREFIX_TABLE.get(f"{parts[0]}/{parts[1]}")
    if entry is None:
        return None
    name, template, priority = entry
    return name, template.format(doi=doi), priority


def from_metadata(raw: Optional[str]) -> Optional[Tuple[str, Optional[str]]]:
    """Serbest metin yayıncı adını kanonik ada ve öncelik platformuna çevir."""
    text = str(raw or "").strip()
    if not text:
        return None
    lowered = text.lower()
    # Eski dosyalardaki "Diğer"/"other" gerçek bir yayıncı adı değildir;
    # DOI ön eki veya "Bilinmiyor" ile değiştirilir.
    if is_sentinel(lowered):
        return None
    for pattern, name, priority in _PUBLISHER_PATTERNS:
        if re.search(pattern, lowered):
            return name, priority
    return None


def resolve(
    doi: str, raw_publisher: Optional[str] = None
) -> Tuple[str, Optional[str], Optional[str]]:
    """(görünen ad, iniş URL'i, öncelikli platform) — en güvenilir sinyal kazanır.

    Metadata'daki gerçek ad, DOI ön ekinden daha kesin olabilir (örn. bir dergi
    başka bir yayıncıya devredildiyse). Bu yüzden önce metadata denenir.
    """
    known = from_metadata(raw_publisher)
    by_prefix = from_doi(doi)
    if known:
        name, priority = known
        url = by_prefix[1] if by_prefix else f"https://doi.org/{doi}" if doi else None
        return name, url, priority
    if by_prefix:
        return by_prefix
    if raw_publisher and not is_sentinel(raw_publisher):
        return str(raw_publisher).strip(), f"https://doi.org/{doi}" if doi else None, None
    return UNKNOWN, f"https://doi.org/{doi}" if doi else None, None


def display_label(doi: str, publisher: Optional[str] = None) -> str:
    """Düğme etiketi: öncelikli platform varsa platform adı, yoksa yayıncı adı.

    Kullanıcı listede "hangi veritabanından indireceğim" sorusunu görmek istiyor:
    Springer Nature makalesi SpringerLink'ten, Elsevier makalesi
    ScienceDirect'ten gelir. Öncelikli beş platform dışında platform adı
    bilinmediğinden gerçek yayıncı yazılır (SAGE, APA, Frontiers ...).
    """
    # Kullanıcı "hangi veritabanından indireceğim"i görmek ister: SAGE,
    # ScienceDirect, SpringerLink ... Dernek adı (AERA/APA) tek başına
    # nereden indirileceğini söylemez.
    name, _url, priority = resolve(doi, publisher)
    return platform_for(doi) or priority or name


def publisher_note(doi: str, publisher: Optional[str] = None) -> Optional[str]:
    """Platform etiketinin altında gösterilecek yayıncı adı (farklıysa)."""
    name, _url, priority = resolve(doi, publisher)
    platform = platform_for(doi) or priority
    if name and platform and name != platform:
        return name
    return None


def display_name(publisher: Optional[str], doi: str) -> str:
    """HTML/JSON için yayıncı adı: bilinen adı korur, bilinmeyeni çözer."""
    name, _url, _priority = resolve(doi, publisher)
    return name


def is_priority(publisher: Optional[str], doi: str) -> bool:
    _name, _url, priority = resolve(doi, publisher)
    return priority in PRIORITY_PLATFORMS
