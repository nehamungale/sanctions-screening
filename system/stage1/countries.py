"""Country canonicalisation: ISO alpha-2, English names, demonyms, aliases.

Structured fields go through ``norm_country`` (full ISO set). Note text uses a
closed surface lexicon so wording like "national ID" does not become a country.
"""

from __future__ import annotations

import re

from stage1.normalise_text import country_fold, norm_text

# English short names. Territories stay their own country.
_ISO_TEXT = """
AD Andorra
AE United Arab Emirates
AF Afghanistan
AG Antigua and Barbuda
AI Anguilla
AL Albania
AM Armenia
AO Angola
AQ Antarctica
AR Argentina
AS American Samoa
AT Austria
AU Australia
AW Aruba
AX Åland Islands
AZ Azerbaijan
BA Bosnia and Herzegovina
BB Barbados
BD Bangladesh
BE Belgium
BF Burkina Faso
BG Bulgaria
BH Bahrain
BI Burundi
BJ Benin
BL Saint Barthélemy
BM Bermuda
BN Brunei
BO Bolivia
BQ Caribbean Netherlands
BR Brazil
BS Bahamas
BT Bhutan
BV Bouvet Island
BW Botswana
BY Belarus
BZ Belize
CA Canada
CC Cocos Islands
CD Democratic Republic of the Congo
CF Central African Republic
CG Congo
CH Switzerland
CI Côte d'Ivoire
CK Cook Islands
CL Chile
CM Cameroon
CN China
CO Colombia
CR Costa Rica
CU Cuba
CV Cabo Verde
CW Curaçao
CX Christmas Island
CY Cyprus
CZ Czech Republic
DE Germany
DJ Djibouti
DK Denmark
DM Dominica
DO Dominican Republic
DZ Algeria
EC Ecuador
EE Estonia
EG Egypt
EH Western Sahara
ER Eritrea
ES Spain
ET Ethiopia
FI Finland
FJ Fiji
FK Falkland Islands
FM Micronesia
FO Faroe Islands
FR France
GA Gabon
GB United Kingdom
GD Grenada
GE Georgia
GF French Guiana
GG Guernsey
GH Ghana
GI Gibraltar
GL Greenland
GM Gambia
GN Guinea
GP Guadeloupe
GQ Equatorial Guinea
GR Greece
GS South Georgia and the South Sandwich Islands
GT Guatemala
GU Guam
GW Guinea-Bissau
GY Guyana
HK Hong Kong
HM Heard Island and McDonald Islands
HN Honduras
HR Croatia
HT Haiti
HU Hungary
ID Indonesia
IE Ireland
IL Israel
IM Isle of Man
IN India
IO British Indian Ocean Territory
IQ Iraq
IR Iran
IS Iceland
IT Italy
JE Jersey
JM Jamaica
JO Jordan
JP Japan
KE Kenya
KG Kyrgyzstan
KH Cambodia
KI Kiribati
KM Comoros
KN Saint Kitts and Nevis
KP North Korea
KR South Korea
KW Kuwait
KY Cayman Islands
KZ Kazakhstan
LA Laos
LB Lebanon
LC Saint Lucia
LI Liechtenstein
LK Sri Lanka
LR Liberia
LS Lesotho
LT Lithuania
LU Luxembourg
LV Latvia
LY Libya
MA Morocco
MC Monaco
MD Moldova
ME Montenegro
MF Saint Martin
MG Madagascar
MH Marshall Islands
MK North Macedonia
ML Mali
MM Myanmar
MN Mongolia
MO Macao
MP Northern Mariana Islands
MQ Martinique
MR Mauritania
MS Montserrat
MT Malta
MU Mauritius
MV Maldives
MW Malawi
MX Mexico
MY Malaysia
MZ Mozambique
NA Namibia
NC New Caledonia
NE Niger
NF Norfolk Island
NG Nigeria
NI Nicaragua
NL Netherlands
NO Norway
NP Nepal
NR Nauru
NU Niue
NZ New Zealand
OM Oman
PA Panama
PE Peru
PF French Polynesia
PG Papua New Guinea
PH Philippines
PK Pakistan
PL Poland
PM Saint Pierre and Miquelon
PN Pitcairn
PR Puerto Rico
PS Palestine
PT Portugal
PW Palau
PY Paraguay
QA Qatar
RE Réunion
RO Romania
RS Serbia
RU Russia
RW Rwanda
SA Saudi Arabia
SB Solomon Islands
SC Seychelles
SD Sudan
SE Sweden
SG Singapore
SH Saint Helena
SI Slovenia
SJ Svalbard and Jan Mayen
SK Slovakia
SL Sierra Leone
SM San Marino
SN Senegal
SO Somalia
SR Suriname
SS South Sudan
ST Sao Tome and Principe
SV El Salvador
SX Sint Maarten
SY Syria
SZ Eswatini
TC Turks and Caicos Islands
TD Chad
TF French Southern Territories
TG Togo
TH Thailand
TJ Tajikistan
TK Tokelau
TL Timor-Leste
TM Turkmenistan
TN Tunisia
TO Tonga
TR Turkey
TT Trinidad and Tobago
TV Tuvalu
TW Taiwan
TZ Tanzania
UA Ukraine
UG Uganda
UM United States Minor Outlying Islands
US United States
UY Uruguay
UZ Uzbekistan
VA Vatican City
VC Saint Vincent and the Grenadines
VE Venezuela
VG British Virgin Islands
VI U.S. Virgin Islands
VN Vietnam
VU Vanuatu
WF Wallis and Futuna
WS Samoa
YE Yemen
YT Mayotte
ZA South Africa
ZM Zambia
ZW Zimbabwe
"""

ISO2: dict[str, str] = {}
for _line in _ISO_TEXT.strip().splitlines():
    _code, _name = _line.split(" ", 1)
    ISO2[_code] = _name

# Surface form -> canonical. Case-sensitive, used when reading note text.
DEMONYMS: dict[str, str] = {
    "American": "United States",
    "British": "United Kingdom",
    "Nigerian": "Nigeria",
    "Spanish": "Spain",
    "German": "Germany",
    "French": "France",
    "Bangladeshi": "Bangladesh",
    "Italian": "Italy",
    "Irish": "Ireland",
    "Polish": "Poland",
    "Indian": "India",
    "Canadian": "Canada",
    "Australian": "Australia",
    "Austrian": "Austria",
    "Brazilian": "Brazil",
    "Danish": "Denmark",
    "Dutch": "Netherlands",
    "Ghanaian": "Ghana",
    "Indonesian": "Indonesia",
    "Kenyan": "Kenya",
    "Mexican": "Mexico",
    "Norwegian": "Norway",
    "Pakistani": "Pakistan",
    "Portuguese": "Portugal",
    "Serbian": "Serbia",
    "Singaporean": "Singapore",
    "South African": "South Africa",
    "Swedish": "Sweden",
    "Finnish": "Finland",
    "Swiss": "Switzerland",
    "Romanian": "Romania",
    "Russian": "Russia",
    "Peruvian": "Peru",
    "Panamanian": "Panama",
    "Moldovan": "Moldova",
    "Slovenian": "Slovenia",
    "Hungarian": "Hungary",
    "Czech": "Czech Republic",
    "Ecuadorian": "Ecuador",
    "Haitian": "Haiti",
    "Jamaican": "Jamaica",
    "Lebanese": "Lebanon",
    "Moroccan": "Morocco",
    "Algerian": "Algeria",
    "Armenian": "Armenia",
    "Israeli": "Israel",
    "Syrian": "Syria",
    "Thai": "Thailand",
    "Vietnamese": "Vietnam",
    "Emirati": "United Arab Emirates",
    "Argentine": "Argentina",
    "Argentinian": "Argentina",
    "Colombian": "Colombia",
    "Ivorian": "Côte d'Ivoire",
    "Dominican": "Dominican Republic",
    "Montenegrin": "Montenegro",
    "New Zealander": "New Zealand",
    "North Korean": "North Korea",
    "Chinese": "China",
    "Japanese": "Japan",
    "Turkish": "Turkey",
    "Egyptian": "Egypt",
    "Greek": "Greece",
    "Belgian": "Belgium",
    "Chilean": "Chile",
    "Filipino": "Philippines",
    "Malaysian": "Malaysia",
    "Estonian": "Estonia",
    "Latvian": "Latvia",
    "Lithuanian": "Lithuania",
    "Croatian": "Croatia",
    "Ukrainian": "Ukraine",
    "Saudi": "Saudi Arabia",
    "Qatari": "Qatar",
    "Iranian": "Iran",
    "Iraqi": "Iraq",
    "Sri Lankan": "Sri Lanka",
    "Nepali": "Nepal",
    "Nepalese": "Nepal",
    "Ethiopian": "Ethiopia",
    "Tanzanian": "Tanzania",
    "Senegalese": "Senegal",
    "Cameroonian": "Cameroon",
    "Bolivian": "Bolivia",
    "Venezuelan": "Venezuela",
    "Uruguayan": "Uruguay",
    "Paraguayan": "Paraguay",
    "Cuban": "Cuba",
    "Icelandic": "Iceland",
    "Luxembourgish": "Luxembourg",
    "Slovak": "Slovakia",
    "Bulgarian": "Bulgaria",
    "Albanian": "Albania",
    "Georgian": "Georgia",
    "Kazakh": "Kazakhstan",
    "Afghan": "Afghanistan",
    "Tunisian": "Tunisia",
    "Zimbabwean": "Zimbabwe",
    "Zambian": "Zambia",
    "South Korean": "South Korea",
    "Taiwanese": "Taiwan",
    "Costa Rican": "Costa Rica",
    "Guatemalan": "Guatemala",
    "Honduran": "Honduras",
    "Nicaraguan": "Nicaragua",
    "Salvadoran": "El Salvador",
    "Puerto Rican": "Puerto Rico",
    "Cypriot": "Cyprus",
    "Maltese": "Malta",
    "Belarusian": "Belarus",
    "Azerbaijani": "Azerbaijan",
    "Uzbek": "Uzbekistan",
    "Mongolian": "Mongolia",
    "Cambodian": "Cambodia",
    "Burmese": "Myanmar",
    "Laotian": "Laos",
    "Rwandan": "Rwanda",
    "Angolan": "Angola",
    "Mozambican": "Mozambique",
    "Namibian": "Namibia",
    "Libyan": "Libya",
    "Sudanese": "Sudan",
    "Jordanian": "Jordan",
    "Kuwaiti": "Kuwait",
    "Bahraini": "Bahrain",
    "Omani": "Oman",
    "Yemeni": "Yemen",
    "Ugandan": "Uganda",
    "Congolese": "Congo",
}

# Extra spellings that are not a distinct country.
ALIASES: dict[str, str] = {
    "UK": "United Kingdom",
    "U.K.": "United Kingdom",
    "USA": "United States",
    "U.S.A.": "United States",
    "U.S.": "United States",
    "United States of America": "United States",
    "Great Britain": "United Kingdom",
    "Britain": "United Kingdom",
    "Cote D'Ivoire": "Côte d'Ivoire",
    "Cote d'Ivoire": "Côte d'Ivoire",
    "Côte d’Ivoire": "Côte d'Ivoire",
    "UAE": "United Arab Emirates",
    "Czechia": "Czech Republic",
    "Korea": "South Korea",
    "Republic of Korea": "South Korea",
    "Democratic People's Republic of Korea": "North Korea",
    "Russia": "Russia",
    "Russian Federation": "Russia",
    "Viet Nam": "Vietnam",
    "Türkiye": "Turkey",
    "Turkiye": "Turkey",
    "Palestina": "Palestine",
    "State of Palestine": "Palestine",
    "Palestinian Territories": "Palestine",
    "Macao Special Administrative Region of China": "Macao",
    "Macau Special Administrative Region of China": "Macao",
    "Macau": "Macao",
    "Hong Kong Special Administrative Region of China": "Hong Kong",
    "Holland": "Netherlands",
    "Ivory Coast": "Côte d'Ivoire",
    "Kosovo": "Kosovo",
    "DPRK": "North Korea",
    "U.K": "United Kingdom",
    "U.S.A": "United States",
    "Burma": "Myanmar",
    "Republic of Moldova": "Moldova",
}

# Recognised tokens that are not countries. They are dropped, not flagged.
NON_COUNTRIES = ("International", "Europe")

# Canonical names that are not ISO alpha-2 entries but appear on watchlists.
EXTRA_CANONICAL = ("Kosovo",)

# Free-text matching uses the same alias table as norm_country. Two-letter
# codes are left out of that regex on purpose ("ID" is a document word).


def _build_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}

    def add(surface: str, canonical: str) -> None:
        key = country_fold(surface)
        if not key:
            return
        previous = lookup.get(key)
        if previous is not None and previous != canonical:
            raise RuntimeError(f"country key {key!r} maps to {previous!r} and {canonical!r}")
        lookup[key] = canonical

    for name in ISO2.values():
        add(name, name)
    for surface, canonical in DEMONYMS.items():
        add(surface, canonical)
    for surface, canonical in ALIASES.items():
        add(surface, canonical)
    for name in EXTRA_CANONICAL:
        add(name, name)
    for name in NON_COUNTRIES:
        key = country_fold(name)
        if key in lookup:
            raise RuntimeError(f"non-country {name!r} collides with {lookup[key]!r}")
    return lookup


LOOKUP: dict[str, str] = _build_lookup()
_NON_COUNTRY_KEYS = {country_fold(name) for name in NON_COUNTRIES}

def _note_surface(surface: str) -> bool:
    # Two-letter codes stay out of free text: "ID" is a document word.
    return re.fullmatch(r"[A-Za-z]{2}", surface) is None

_NOTE_SURFACES = sorted(
    (
        surface
        for surface in (
            list(ISO2.values()) + list(DEMONYMS) + list(ALIASES) + list(EXTRA_CANONICAL) + list(NON_COUNTRIES)
        )
        if _note_surface(surface)
    ),
    key=len,
    reverse=True,
)
_NOTE_RE = re.compile(r"\b(" + "|".join(re.escape(item) for item in _NOTE_SURFACES) + r")\b")
_NOTE_PAREN = re.compile(r"\(Note:[^)]*\)")


def to_country(surface: str) -> str:
    """Map one lexicon hit to the canonical English name."""
    if surface in DEMONYMS:
        return DEMONYMS[surface]
    if surface in ALIASES:
        return ALIASES[surface]
    folded = country_fold(surface)
    return LOOKUP.get(folded, surface)


def countries_in_note(text: str) -> list[str]:
    """Country mentions in note text, in order, with (Note: ...) stripped."""
    cleaned = _NOTE_PAREN.sub(" ", text or "")
    found: list[str] = []
    seen: set[str] = set()
    for match in _NOTE_RE.finditer(cleaned):
        surface = match.group(1)
        if country_fold(surface) in _NON_COUNTRY_KEYS:
            continue
        canonical = to_country(surface)
        if country_fold(canonical) in _NON_COUNTRY_KEYS:
            continue
        if canonical not in seen:
            seen.add(canonical)
            found.append(canonical)
    return found


_TAG_RE = re.compile(r"\[[^\]]*\]")


def classify_leaf(value: object) -> tuple[str, str | None, list[str]]:
    """Classify one country token.

    Status is ``empty``, ``country``, ``non_country`` (International/Europe),
    or ``unmapped``. Address tags such as ``[Business]`` are removed first.
    """
    if value is None:
        return "empty", None, []
    raw = _TAG_RE.sub(" ", str(value))
    raw = re.sub(r"\s+", " ", raw).strip(" .;")
    if not raw:
        return "empty", None, []
    stripped = re.sub(r"^the\s+", "", raw, count=1, flags=re.IGNORECASE).strip()
    if country_fold(stripped) in _NON_COUNTRY_KEYS:
        return "non_country", None, []
    if re.fullmatch(r"[A-Za-z]{2}", stripped):
        canonical = ISO2.get(stripped.upper())
        if canonical:
            return "country", canonical, []
    canonical = LOOKUP.get(country_fold(stripped))
    if canonical:
        return "country", canonical, []
    return "unmapped", norm_text(stripped), ["UNMAPPED_COUNTRY"]


def norm_country(value: object) -> tuple[str | None, list[str]]:
    """Return ``(canonical, flags)``.

    Unknown non-empty values are kept as ``norm_text`` and flagged
    ``UNMAPPED_COUNTRY``. Missing values and non-countries
    (International, Europe) are ``(None, [])`` so they cannot cause a clear.
    """
    status, canonical, flags = classify_leaf(value)
    if status == "country":
        return canonical, []
    if status in ("empty", "non_country"):
        return None, []
    return canonical, flags


def country_leaves(value: object) -> list[str]:
    """Country candidates: the last comma-piece of each semicolon-separated value.

    Hit addresses use this shape (``City, Region, Country [Business]``). Tags
    are stripped before the split. The same helper is what the dev scan uses.
    """
    if value is None:
        return []
    if isinstance(value, list):
        leaves: list[str] = []
        for item in value:
            leaves.extend(country_leaves(item))
        return leaves
    text = _TAG_RE.sub(" ", str(value))
    leaves = []
    for semi in text.split(";"):
        semi = semi.strip(" .")
        if not semi:
            continue
        bits = [bit.strip(" .") for bit in semi.split(",") if bit.strip(" .")]
        if bits:
            leaves.append(bits[-1])
    return leaves


def unmapped_country_leaves(value: object) -> list[str]:
    """Leaves that are real unmatched strings. Non-countries are not listed."""
    bad = []
    for leaf in country_leaves(value):
        status, _canonical, _flags = classify_leaf(leaf)
        if status == "unmapped":
            bad.append(leaf)
    return bad
