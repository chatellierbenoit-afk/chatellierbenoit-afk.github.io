import json
import re
import ssl
import time
import socket
import http.client
import urllib.request
import urllib.error
import zipfile

from collections import defaultdict
from datetime import datetime, timezone, date
from io import BytesIO
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

LEGISLATURE = "17"

CURRENT_YEAR = datetime.now(timezone.utc).year
MIN_YEAR = CURRENT_YEAR - 1

MAX_ASSEMBLY_SEATS = 577

SCRUTINS_URL = (
    "https://data.assemblee-nationale.fr/static/openData/"
    "repository/17/loi/scrutins/Scrutins.json.zip"
)

AMO_URL = (
    "https://data.assemblee-nationale.fr/static/openData/"
    "repository/17/amo/acteurs_mandats_organes_divises/"
    "AMO50_acteurs_mandats_organes_divises.json.zip"
)

BASE_DIR = Path("data/current")
MONTHS_DIR = BASE_DIR / "months"

SSL_CONTEXT = ssl.create_default_context()


# ============================================================
# GROUPES : NORMALISATION
# ============================================================

GROUP_ALIASES = {

    "Rassemblement national":
        "Rassemblement National",

    "Rassemblement National":
        "Rassemblement National",

    "Ensemble pour la Republique":
        "Ensemble pour la République",

    "Ensemble pour la République":
        "Ensemble pour la République",

    "La France insoumise-Nouveau Front Populaire":
        "La France insoumise - Nouveau Front Populaire",

    "La France insoumise - Nouveau Front Populaire":
        "La France insoumise - Nouveau Front Populaire",

    "Socialistes et apparentés":
        "Socialistes et apparentés",

    "Socialistes et apparentes":
        "Socialistes et apparentés",

    "Droite Républicaine":
        "Droite Républicaine",

    "Droite republicaine":
        "Droite Républicaine",

    "Écologiste et Social":
        "Écologiste et Social",

    "Ecologiste et Social":
        "Écologiste et Social",

    "Les Démocrates":
        "Les Démocrates",

    "Les Democrates":
        "Les Démocrates",

    "Horizons et Indépendants":
        "Horizons & Indépendants",

    "Horizons et indépendants":
        "Horizons & Indépendants",

    "Horizons & Indépendants":
        "Horizons & Indépendants",

    "Libertés, Indépendants, Outre-mer et Territoires":
        "Libertés, Indépendants, Outre-mer et Territoires",

    "Libertés, indépendants, outre-mer et territoires":
        "Libertés, Indépendants, Outre-mer et Territoires",

    "Gauche Démocrate et Républicaine":
        "Gauche Démocrate et Républicaine",

    "Gauche démocrate et républicaine":
        "Gauche Démocrate et Républicaine",

    "Union des droites pour la République":
        "Union des droites pour la République",

    "Union des Droites pour la République":
        "Union des droites pour la République",

    "Non inscrit":
        "Non inscrits",

    "Non inscrite":
        "Non inscrits",

    "Non inscrits":
        "Non inscrits",

    "NI":
        "Non inscrits",
}


# ============================================================
# OUTILS DE BASE
# ============================================================

def ensure_dir(path):
    path.mkdir(
        parents=True,
        exist_ok=True
    )


def clean(value):

    if value is None:
        return ""

    return " ".join(
        str(value)
        .replace("\u00a0", " ")
        .split()
    ).strip()


def ensure_list(value):

    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def write_json(path, data):

    ensure_dir(
        path.parent
    )

    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def get_uid(value):

    if isinstance(value, dict):

        return clean(
            value.get("#text")
            or value.get("uid")
            or value.get("value")
            or ""
        )

    return clean(value)


def normalize_group(value):

    value = clean(value)

    if not value:
        return ""

    return GROUP_ALIASES.get(
        value,
        value
    )


def ordinal_fr(number):

    try:
        number = int(number)
    except Exception:
        return clean(number)

    if number == 1:
        return "1re"

    return f"{number}e"


def normalize_circonscription(value):

    value = clean(value)

    if not value:
        return ""

    replacements = {
        "1ère": "1re",
        "1ere": "1re",
        "1er": "1re",

        "2ème": "2e",
        "2eme": "2e",

        "3ème": "3e",
        "3eme": "3e",

        "4ème": "4e",
        "4eme": "4e",

        "5ème": "5e",
        "5eme": "5e",

        "6ème": "6e",
        "6eme": "6e",

        "7ème": "7e",
        "7eme": "7e",

        "8ème": "8e",
        "8eme": "8e",

        "9ème": "9e",
        "9eme": "9e",

        "10ème": "10e",
        "10eme": "10e",

        "11ème": "11e",
        "11eme": "11e",

        "12ème": "12e",
        "12eme": "12e",

        "13ème": "13e",
        "13eme": "13e",

        "14ème": "14e",
        "14eme": "14e",

        "15ème": "15e",
        "15eme": "15e",

        "16ème": "16e",
        "16eme": "16e",

        "17ème": "17e",
        "17eme": "17e",

        "18ème": "18e",
        "18eme": "18e",

        "19ème": "19e",
        "19eme": "19e",

        "20ème": "20e",
        "20eme": "20e",

        "21ème": "21e",
        "21eme": "21e",
    }

    for old, new in replacements.items():
        value = value.replace(
            old,
            new
        )

    return value


# ============================================================
# TÉLÉCHARGEMENT
# ============================================================

def download(
    url,
    retries=5,
    pause=3,
    chunk_size=1024 * 256
):

    last_error = None

    for attempt in range(
        1,
        retries + 1
    ):

        try:

            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent":
                        "Mozilla/5.0",

                    "Accept":
                        "*/*",

                    "Connection":
                        "close",
                }
            )

            with urllib.request.urlopen(
                request,
                context=SSL_CONTEXT,
                timeout=240
            ) as response:

                chunks = []

                while True:

                    chunk = response.read(
                        chunk_size
                    )

                    if not chunk:
                        break

                    chunks.append(
                        chunk
                    )

                data = b"".join(
                    chunks
                )

                if not data:
                    raise ValueError(
                        "Téléchargement vide"
                    )

                return data

        except (
            http.client.IncompleteRead,
            urllib.error.URLError,
            socket.timeout,
            TimeoutError,
            ConnectionResetError,
            ValueError,
        ) as error:

            last_error = error

            print(
                f"Échec téléchargement "
                f"{attempt}/{retries}"
            )

            print(
                url
            )

            print(
                error
            )

            if attempt < retries:

                time.sleep(
                    pause * attempt
                )

    raise last_error


def download_zip(url):

    data = download(
        url
    )

    if (
        len(data) < 4
        or data[:2] != b"PK"
    ):

        raise ValueError(
            f"Le téléchargement n'est pas un ZIP : {url}"
        )

    return data


def iter_zip_json(zf):

    for filename in zf.namelist():

        if not filename.lower().endswith(
            ".json"
        ):
            continue

        try:

            raw = zf.read(
                filename
            )

            text = raw.decode(
                "utf-8-sig"
            )

            payload = json.loads(
                text
            )

            yield (
                filename,
                payload
            )

        except Exception as error:

            print(
                "JSON ignoré :",
                filename,
                error
            )


# ============================================================
# EXTRACTION RÉCURSIVE
# ============================================================

def extract_organe_refs(node):

    result = []

    if isinstance(
        node,
        dict
    ):

        if "organeRef" in node:

            for item in ensure_list(
                node.get("organeRef")
            ):

                uid = get_uid(
                    item
                )

                if uid:
                    result.append(
                        uid
                    )

        for value in node.values():

            result.extend(
                extract_organe_refs(
                    value
                )
            )

    elif isinstance(
        node,
        list
    ):

        for item in node:

            result.extend(
                extract_organe_refs(
                    item
                )
            )

    return list(
        dict.fromkeys(
            result
        )
    )


def extract_votants(node):

    result = []

    if isinstance(
        node,
        dict
    ):

        if "votant" in node:

            for voter in ensure_list(
                node.get("votant")
            ):

                if isinstance(
                    voter,
                    dict
                ):
                    result.append(
                        voter
                    )

        elif "acteurRef" in node:

            result.append(
                node
            )

        else:

            for value in node.values():

                result.extend(
                    extract_votants(
                        value
                    )
                )

    elif isinstance(
        node,
        list
    ):

        for item in node:

            result.extend(
                extract_votants(
                    item
                )
            )

    return result


# ============================================================
# DATE / MANDAT ACTIF
# ============================================================

def parse_date(value):

    value = clean(value)

    if not value:
        return None

    try:

        return datetime.strptime(
            value[:10],
            "%Y-%m-%d"
        ).date()

    except Exception:
        return None


def mandate_is_active(mandate):

    today = date.today()

    start = parse_date(
        mandate.get(
            "dateDebut"
        )
    )

    end = parse_date(
        mandate.get(
            "dateFin"
        )
    )

    if (
        start
        and start > today
    ):
        return False

    if (
        end
        and end < today
    ):
        return False

    return True


# ============================================================
# ORGANES
# ============================================================

def get_organe_label(organe):

    if not isinstance(
        organe,
        dict
    ):
        return ""

    candidates = [

        organe.get(
            "libelle"
        ),

        organe.get(
            "libelleEdition"
        ),

        organe.get(
            "libelleAbrege"
        ),

        organe.get(
            "libelleAbrev"
        )

    ]

    for candidate in candidates:

        candidate = clean(
            candidate
        )

        if candidate:
            return candidate

    return ""


# ============================================================
# ACTEURS + MANDATS + ORGANES
# ============================================================

def load_amo():

    print("")
    print(
        "Téléchargement acteurs / mandats / organes..."
    )

    raw = download_zip(
        AMO_URL
    )

    zf = zipfile.ZipFile(
        BytesIO(raw)
    )

    actors = {}
    organes = {}
    mandates = []

    for filename, payload in iter_zip_json(
        zf
    ):

        if not isinstance(
            payload,
            dict
        ):
            continue

        # ----------------------------------------------------
        # ACTEUR
        # ----------------------------------------------------

        actor = payload.get(
            "acteur"
        )

        if isinstance(
            actor,
            dict
        ):

            uid = get_uid(
                actor.get(
                    "uid"
                )
            )

            if not uid:
                continue

            ident = (
                actor
                .get(
                    "etatCivil",
                    {}
                )
                .get(
                    "ident",
                    {}
                )
            )

            first_name = clean(
                ident.get(
                    "prenom"
                )
            )

            last_name = clean(
                ident.get(
                    "nom"
                )
            )

            full_name = clean(
                f"{first_name} {last_name}"
            )

            actors[uid] = {
                "uid":
                    uid,

                "nom":
                    full_name,

                "groupe_actuel":
                    "",

                "departement":
                    "",

                "num_departement":
                    "",

                "num_circonscription":
                    "",

                "circonscription":
                    "",

                "actif":
                    False,
            }

            continue

        # ----------------------------------------------------
        # ORGANE
        # ----------------------------------------------------

        organe = payload.get(
            "organe"
        )

        if isinstance(
            organe,
            dict
        ):

            uid = get_uid(
                organe.get(
                    "uid"
                )
            )

            if not uid:
                continue

            organes[uid] = {
                "uid":
                    uid,

                "code_type":
                    clean(
                        organe.get(
                            "codeType"
                        )
                    ),

                "label":
                    get_organe_label(
                        organe
                    ),

                "raw":
                    organe,
            }

            continue

        # ----------------------------------------------------
        # MANDAT
        # ----------------------------------------------------

        mandate = payload.get(
            "mandat"
        )

        if isinstance(
            mandate,
            dict
        ):

            mandates.append(
                mandate
            )

    print(
        "Acteurs :",
        len(actors)
    )

    print(
        "Organes :",
        len(organes)
    )

    print(
        "Mandats :",
        len(mandates)
    )

    # ========================================================
    # 1. MANDATS DE DÉPUTÉ ACTIFS
    # ========================================================

    current_deputies = set()

    for mandate in mandates:

        legislature = clean(
            mandate.get(
                "legislature"
            )
        )

        if (
            legislature
            and legislature
            != LEGISLATURE
        ):
            continue

        if not mandate_is_active(
            mandate
        ):
            continue

        actor_uid = get_uid(
            mandate.get(
                "acteurRef"
            )
        )

        if actor_uid not in actors:
            continue

        organe_type = clean(
            mandate.get(
                "typeOrgane"
            )
        ).upper()

        # ----------------------------------------------------
        # MANDAT ASSEMBLÉE
        # ----------------------------------------------------

        if organe_type == "ASSEMBLEE":

            current_deputies.add(
                actor_uid
            )

            actors[
                actor_uid
            ][
                "actif"
            ] = True

            election = mandate.get(
                "election",
                {}
            )

            if not isinstance(
                election,
                dict
            ):
                election = {}

            lieu = election.get(
                "lieu",
                {}
            )

            if not isinstance(
                lieu,
                dict
            ):
                lieu = {}

            departement = clean(
                lieu.get(
                    "departement"
                )
            )

            if isinstance(
                lieu.get(
                    "departement"
                ),
                dict
            ):

                dep_obj = lieu.get(
                    "departement"
                )

                departement = clean(
                    dep_obj.get(
                        "libelle"
                    )
                    or dep_obj.get(
                        "nom"
                    )
                )

            num_departement = clean(
                lieu.get(
                    "numDepartement"
                )
                or lieu.get(
                    "numeroDepartement"
                )
            )

            num_circo = clean(
                lieu.get(
                    "numCirco"
                )
                or lieu.get(
                    "numeroCirconscription"
                )
            )

            if departement:

                actors[
                    actor_uid
                ][
                    "departement"
                ] = departement

            if num_departement:

                actors[
                    actor_uid
                ][
                    "num_departement"
                ] = num_departement

            if num_circo:

                actors[
                    actor_uid
                ][
                    "num_circonscription"
                ] = num_circo

                actors[
                    actor_uid
                ][
                    "circonscription"
                ] = (
                    f"{ordinal_fr(num_circo)} "
                    f"circonscription"
                )

            # ------------------------------------------------
            # REF CIRCONSCRIPTION
            # ------------------------------------------------

            ref_circo = get_uid(
                election.get(
                    "refCirconscription"
                )
            )

            if (
                ref_circo
                and ref_circo
                in organes
            ):

                circo_label = clean(
                    organes[
                        ref_circo
                    ].get(
                        "label"
                    )
                )

                if (
                    circo_label
                    and not actors[
                        actor_uid
                    ][
                        "circonscription"
                    ]
                ):

                    actors[
                        actor_uid
                    ][
                        "circonscription"
                    ] = normalize_circonscription(
                        circo_label
                    )

    # ========================================================
    # 2. GROUPES ACTUELS
    # ========================================================

    for mandate in mandates:

        legislature = clean(
            mandate.get(
                "legislature"
            )
        )

        if (
            legislature
            and legislature
            != LEGISLATURE
        ):
            continue

        if not mandate_is_active(
            mandate
        ):
            continue

        actor_uid = get_uid(
            mandate.get(
                "acteurRef"
            )
        )

        if actor_uid not in current_deputies:
            continue

        organe_type = clean(
            mandate.get(
                "typeOrgane"
            )
        ).upper()

        refs = extract_organe_refs(
            mandate.get(
                "organes",
                {}
            )
        )

        is_group_mandate = (
            organe_type
            in {
                "GP",
                "GRP",
                "GROUPE"
            }
        )

        for ref in refs:

            organe = organes.get(
                ref
            )

            if not organe:
                continue

            code_type = clean(
                organe.get(
                    "code_type"
                )
            ).upper()

            if (
                is_group_mandate
                or code_type
                in {
                    "GP",
                    "GRP",
                    "GROUPE"
                }
            ):

                group_name = normalize_group(
                    organe.get(
                        "label"
                    )
                )

                if group_name:

                    actors[
                        actor_uid
                    ][
                        "groupe_actuel"
                    ] = group_name

    current_actor_data = {}

    for uid in current_deputies:

        actor = actors.get(
            uid
        )

        if not actor:
            continue

        if not clean(
            actor.get(
                "nom"
            )
        ):
            continue

        current_actor_data[
            uid
        ] = actor

    print(
        "Députés actifs trouvés :",
        len(
            current_actor_data
        )
    )

    return (
        actors,
        current_actor_data,
        organes
    )


# ============================================================
# THÈMES
# ============================================================

def guess_theme(text):

    text = clean(
        text
    ).lower()

    rules = [

        (
            "Budget / Fiscalité",
            [
                "budget",
                "finances",
                "fiscal",
                "impôt",
                "impot",
                "taxe",
                "plf",
                "plfss",
                "déficit",
                "deficit",
            ]
        ),

        (
            "Travail / Retraites / Social",
            [
                "travail",
                "emploi",
                "retraite",
                "retraites",
                "salaire",
                "salaires",
                "chômage",
                "chomage",
                "allocation",
                "social",
            ]
        ),

        (
            "Santé",
            [
                "santé",
                "sante",
                "hôpital",
                "hopital",
                "médecin",
                "medecin",
                "médical",
                "medical",
                "soin",
                "soins",
            ]
        ),

        (
            "Éducation",
            [
                "éducation",
                "education",
                "enseignement",
                "école",
                "ecole",
                "université",
                "universite",
                "étudiant",
                "etudiant",
            ]
        ),

        (
            "Écologie / Énergie",
            [
                "écologie",
                "ecologie",
                "environnement",
                "climat",
                "énergie",
                "energie",
                "nucléaire",
                "nucleaire",
                "biodiversité",
                "biodiversite",
            ]
        ),

        (
            "Immigration / Asile",
            [
                "immigration",
                "immigré",
                "immigre",
                "asile",
                "étranger",
                "etranger",
                "étrangers",
                "etrangers",
                "titre de séjour",
                "titre de sejour",
            ]
        ),

        (
            "Justice / Sécurité",
            [
                "justice",
                "sécurité",
                "securite",
                "police",
                "gendarmerie",
                "prison",
                "pénal",
                "penal",
                "criminalité",
                "criminalite",
            ]
        ),

        (
            "Agriculture / Alimentation",
            [
                "agriculture",
                "agricole",
                "agriculteur",
                "agriculteurs",
                "alimentation",
                "alimentaire",
                "élevage",
                "elevage",
            ]
        ),

        (
            "Logement / Transports",
            [
                "logement",
                "habitat",
                "transport",
                "mobilité",
                "mobilite",
                "ferroviaire",
                "route",
            ]
        ),

        (
            "Défense / International",
            [
                "défense",
                "defense",
                "armée",
                "armee",
                "militaire",
                "international",
                "ukraine",
                "europe",
                "européen",
                "europeen",
            ]
        ),

        (
            "Institutions",
            [
                "constitution",
                "motion de censure",
                "censure",
                "assemblée nationale",
                "assemblee nationale",
                "institution",
            ]
        ),

        (
            "Culture / Médias",
            [
                "culture",
                "culturel",
                "audiovisuel",
                "presse",
                "média",
                "media",
                "patrimoine",
            ]
        ),
    ]

    for theme, keywords in rules:

        if any(
            keyword in text
            for keyword in keywords
        ):
            return theme

    return "Autres"


# ============================================================
# SUJET LISIBLE DU SCRUTIN
# ============================================================

def truncate(value, max_length=180):

    value = clean(
        value
    )

    if len(value) <= max_length:
        return value

    return (
        value[
            :max_length - 1
        ].rstrip()
        + "…"
    )


def extract_bill_context(text):

    text = clean(
        text
    )

    patterns = [

        r"(projet de loi de finances[^.;]*)",

        r"(projet de loi de financement de la sécurité sociale[^.;]*)",

        r"(projet de loi[^.;]*)",

        r"(proposition de loi[^.;]*)",

        r"(proposition de résolution[^.;]*)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            return truncate(
                match.group(1),
                130
            )

    return ""


def make_subject(
    official_title,
    description
):

    official_title = clean(
        official_title
    )

    description = clean(
        description
    )

    source = (
        description
        or official_title
    )

    if not source:
        return "Scrutin"

    lower = source.lower()

    # --------------------------------------------------------
    # MOTION DE CENSURE
    # --------------------------------------------------------

    if "motion de censure" in lower:

        context = extract_bill_context(
            source
        )

        if context:

            return truncate(
                f"Motion de censure — {context}",
                160
            )

        return "Motion de censure"

    # --------------------------------------------------------
    # SOUS-AMENDEMENT
    # --------------------------------------------------------

    match = re.search(
        r"sous-amendement\s+n[°º]?\s*([0-9]+)",
        source,
        re.IGNORECASE
    )

    if match:

        number = match.group(
            1
        )

        context = extract_bill_context(
            source
        )

        if context:

            return truncate(
                f"Sous-amendement n°{number} — {context}",
                170
            )

        return (
            f"Sous-amendement n°{number}"
        )

    # --------------------------------------------------------
    # AMENDEMENT
    # --------------------------------------------------------

    match = re.search(
        r"amendement\s+n[°º]?\s*([0-9]+)",
        source,
        re.IGNORECASE
    )

    if match:

        number = match.group(
            1
        )

        article_match = re.search(
            r"article\s+([0-9A-Za-zÀ-ÿ\-]+)",
            source,
            re.IGNORECASE
        )

        context = extract_bill_context(
            source
        )

        title = (
            f"Amendement n°{number}"
        )

        if article_match:

            title += (
                f" à l’article "
                f"{article_match.group(1)}"
            )

        if context:

            title += (
                f" — {context}"
            )

        return truncate(
            title,
            170
        )

    # --------------------------------------------------------
    # ARTICLE
    # --------------------------------------------------------

    article_match = re.search(
        r"article\s+([0-9A-Za-zÀ-ÿ\-]+)",
        source,
        re.IGNORECASE
    )

    if article_match:

        context = extract_bill_context(
            source
        )

        title = (
            f"Vote sur l’article "
            f"{article_match.group(1)}"
        )

        if context:

            title += (
                f" — {context}"
            )

        return truncate(
            title,
            170
        )

    # --------------------------------------------------------
    # TITRE ADMINISTRATIF : NETTOYAGE
    # --------------------------------------------------------

    readable = re.sub(
        r"^\s*scrutin public sur\s+",
        "",
        source,
        flags=re.IGNORECASE
    )

    readable = re.sub(
        r"^\s*vote sur\s+",
        "",
        readable,
        flags=re.IGNORECASE
    )

    readable = clean(
        readable
    )

    if readable:

        readable = (
            readable[0].upper()
            + readable[1:]
        )

    return truncate(
        readable
        or "Scrutin",
        170
    )


# ============================================================
# STATISTIQUES
# ============================================================

def compute_vote_stats(votes):

    return {

        "pour":
            sum(
                1
                for vote in votes
                if vote.get(
                    "vote"
                ) == "Pour"
            ),

        "contre":
            sum(
                1
                for vote in votes
                if vote.get(
                    "vote"
                ) == "Contre"
            ),

        "abstention":
            sum(
                1
                for vote in votes
                if vote.get(
                    "vote"
                ) == "Abstention"
            ),

        "non_votant":
            sum(
                1
                for vote in votes
                if vote.get(
                    "vote"
                ) == "Non-votant"
            ),

        "total":
            len(
                votes
            )
    }


def dominant_position(stats):

    values = {

        "Pour":
            stats.get(
                "pour",
                0
            ),

        "Contre":
            stats.get(
                "contre",
                0
            ),

        "Abstention":
            stats.get(
                "abstention",
                0
            )
    }

    maximum = max(
        values.values()
    )

    if maximum == 0:
        return "Non-votant"

    winners = [

        label
        for label, count
        in values.items()
        if count == maximum

    ]

    if len(winners) != 1:
        return "Partagé"

    return winners[0]


def cohesion_percent(stats):

    expressed = (
        stats.get(
            "pour",
            0
        )
        +
        stats.get(
            "contre",
            0
        )
        +
        stats.get(
            "abstention",
            0
        )
    )

    if expressed == 0:
        return 0.0

    maximum = max(

        stats.get(
            "pour",
            0
        ),

        stats.get(
            "contre",
            0
        ),

        stats.get(
            "abstention",
            0
        )
    )

    return round(
        maximum
        / expressed
        * 100,
        1
    )


def compute_group_summary(votes):

    groups = defaultdict(
        list
    )

    for vote in votes:

        group = normalize_group(
            vote.get(
                "groupe_au_vote"
            )
            or vote.get(
                "groupe"
            )
            or ""
        )

        if not group:
            group = "Inconnu"

        groups[
            group
        ].append(
            vote
        )

    result = []

    for group, group_votes in groups.items():

        stats = compute_vote_stats(
            group_votes
        )

        result.append({

            "groupe":
                group,

            "pour":
                stats["pour"],

            "contre":
                stats["contre"],

            "abstention":
                stats["abstention"],

            "non_votant":
                stats["non_votant"],

            "total":
                stats["total"],

            "position":
                dominant_position(
                    stats
                ),

            "cohesion_pct":
                cohesion_percent(
                    stats
                )
        })

    result.sort(
        key=lambda item: (
            -item[
                "total"
            ],
            item[
                "groupe"
            ]
        )
    )

    return result


# ============================================================
# SCRUTINS
# ============================================================

def load_scrutins(
    actors,
    current_actors,
    organes
):

    print("")
    print(
        "Téléchargement des scrutins..."
    )

    raw = download_zip(
        SCRUTINS_URL
    )

    zf = zipfile.ZipFile(
        BytesIO(raw)
    )

    scrutins = []

    latest_group_seen = {}

    for filename, payload in iter_zip_json(
        zf
    ):

        if not isinstance(
            payload,
            dict
        ):
            continue

        scrutin = payload.get(
            "scrutin"
        )

        if not isinstance(
            scrutin,
            dict
        ):
            continue

        scrutin_date = clean(
            scrutin.get(
                "dateScrutin"
            )
        )

        if not scrutin_date:
            continue

        try:

            year = int(
                scrutin_date[:4]
            )

        except Exception:
            continue

        if year < MIN_YEAR:
            continue

        uid = get_uid(
            scrutin.get(
                "uid"
            )
        )

        if not uid:
            continue

        numero = scrutin.get(
            "numero"
        )

        official_title = clean(
            scrutin.get(
                "titre"
            )
        )

        objet = scrutin.get(
            "objet",
            {}
        )

        if not isinstance(
            objet,
            dict
        ):
            objet = {}

        description = clean(
            objet.get(
                "libelle"
            )
            or objet.get(
                "titre"
            )
            or ""
        )

        subject = make_subject(
            official_title,
            description
        )

        theme = guess_theme(
            " ".join([
                official_title,
                description,
                subject
            ])
        )

        votes = []

        ventilation = scrutin.get(
            "ventilationVotes",
            {}
        )

        if not isinstance(
            ventilation,
            dict
        ):
            ventilation = {}

        organe_vote = ventilation.get(
            "organe",
            {}
        )

        if not isinstance(
            organe_vote,
            dict
        ):
            organe_vote = {}

        groupes_node = organe_vote.get(
            "groupes",
            {}
        )

        if not isinstance(
            groupes_node,
            dict
        ):
            groupes_node = {}

        group_blocks = ensure_list(
            groupes_node.get(
                "groupe"
            )
        )

        for group_block in group_blocks:

            if not isinstance(
                group_block,
                dict
            ):
                continue

            group_ref = get_uid(
                group_block.get(
                    "organeRef"
                )
            )

            group_name = clean(
                group_block.get(
                    "libelle"
                )
                or group_block.get(
                    "libelleAbrege"
                )
                or group_block.get(
                    "libelleAbrev"
                )
            )

            if (
                not group_name
                and group_ref
                and group_ref in organes
            ):

                group_name = clean(
                    organes[
                        group_ref
                    ].get(
                        "label"
                    )
                )

            group_name = normalize_group(
                group_name
            )

            if not group_name:

                group_name = (
                    "Inconnu"
                )

            vote_container = group_block.get(
                "vote",
                {}
            )

            if not isinstance(
                vote_container,
                dict
            ):
                vote_container = {}

            nominative = vote_container.get(
                "decompteNominatif",
                {}
            )

            if not isinstance(
                nominative,
                dict
            ):
                nominative = {}

            categories = [

                (
                    "pours",
                    "Pour"
                ),

                (
                    "contres",
                    "Contre"
                ),

                (
                    "abstentions",
                    "Abstention"
                ),

                (
                    "nonVotants",
                    "Non-votant"
                )
            ]

            for key, label in categories:

                voters = extract_votants(
                    nominative.get(
                        key
                    )
                )

                for voter in voters:

                    actor_uid = get_uid(
                        voter.get(
                            "acteurRef"
                        )
                    )

                    if not actor_uid:
                        continue

                    actor = actors.get(
                        actor_uid,
                        {}
                    )

                    current_actor = current_actors.get(
                        actor_uid,
                        {}
                    )

                    name = clean(
                        actor.get(
                            "nom"
                        )
                        or current_actor.get(
                            "nom"
                        )
                    )

                    if not name:

                        name = actor_uid

                    current_group = normalize_group(
                        current_actor.get(
                            "groupe_actuel"
                        )
                    )

                    departement = clean(
                        current_actor.get(
                            "departement"
                        )
                        or actor.get(
                            "departement"
                        )
                    )

                    circonscription = normalize_circonscription(
                        current_actor.get(
                            "circonscription"
                        )
                        or actor.get(
                            "circonscription"
                        )
                    )

                    votes.append({

                        "depute_uid":
                            actor_uid,

                        "nom":
                            name,

                        # Groupe le jour du scrutin
                        "groupe_au_vote":
                            group_name,

                        # Alias pour compatibilité
                        "groupe":
                            group_name,

                        # Groupe actuel
                        "groupe_actuel":
                            current_group,

                        "vote":
                            label,

                        "departement":
                            departement,

                        "circonscription":
                            circonscription
                    })

                    previous = latest_group_seen.get(
                        actor_uid
                    )

                    if (
                        not previous
                        or scrutin_date
                        > previous[
                            "date"
                        ]
                    ):

                        latest_group_seen[
                            actor_uid
                        ] = {

                            "date":
                                scrutin_date,

                            "groupe":
                                group_name
                        }

        if not votes:
            continue

        # Évite les doublons éventuels
        unique_votes = {}

        for vote in votes:

            key = (
                vote[
                    "depute_uid"
                ],
                vote[
                    "vote"
                ]
            )

            if key not in unique_votes:

                unique_votes[
                    key
                ] = vote

        votes = list(
            unique_votes.values()
        )

        stats = compute_vote_stats(
            votes
        )

        group_summary = compute_group_summary(
            votes
        )

        scrutins.append({

            "uid":
                uid,

            "numero":
                numero,

            "date":
                scrutin_date,

            "year":
                year,

            # Titre présenté au visiteur
            "sujet":
                subject,

            "titre_court":
                subject,

            # Données officielles
            "titre":
                official_title,

            "titre_officiel":
                official_title,

            "description":
                description
                or official_title,

            "theme":
                theme,

            "stats": {

                "pour":
                    stats[
                        "pour"
                    ],

                "contre":
                    stats[
                        "contre"
                    ],

                "abstention":
                    stats[
                        "abstention"
                    ],

                "non_votant":
                    stats[
                        "non_votant"
                    ],

                "total_votes":
                    stats[
                        "total"
                    ]
            },

            "groupes_summary":
                group_summary,

            "votes":
                votes
        })

    scrutins.sort(
        key=lambda scrutin: (
            scrutin.get(
                "date",
                ""
            ),
            str(
                scrutin.get(
                    "numero",
                    ""
                )
            )
        ),
        reverse=True
    )

    # ========================================================
    # FALLBACK GROUPE ACTUEL
    #
    # Si l'AMO n'a pas donné le groupe actuel,
    # on prend le groupe observé le plus récemment.
    # ========================================================

    fallback_count = 0

    for uid, actor in current_actors.items():

        if normalize_group(
            actor.get(
                "groupe_actuel"
            )
        ):
            continue

        latest = latest_group_seen.get(
            uid
        )

        if (
            latest
            and latest.get(
                "groupe"
            )
            and latest.get(
                "groupe"
            ) != "Inconnu"
        ):

            actor[
                "groupe_actuel"
            ] = latest[
                "groupe"
            ]

            fallback_count += 1

    print(
        "Scrutins conservés :",
        len(
            scrutins
        )
    )

    print(
        "Groupes actuels récupérés via dernier vote :",
        fallback_count
    )

    return scrutins


# ============================================================
# DEPUTES.JSON
# ============================================================

def build_deputes_file(
    current_actors,
    scrutins
):

    votes_by_uid = defaultdict(
        int
    )

    votes_by_uid_year = defaultdict(
        lambda: defaultdict(int)
    )

    for scrutin in scrutins:

        year = str(
            scrutin.get(
                "year"
            )
        )

        for vote in scrutin.get(
            "votes",
            []
        ):

            uid = vote.get(
                "depute_uid"
            )

            if not uid:
                continue

            votes_by_uid[
                uid
            ] += 1

            votes_by_uid_year[
                uid
            ][
                year
            ] += 1

    deputes = []

    for uid, actor in current_actors.items():

        name = clean(
            actor.get(
                "nom"
            )
        )

        if not name:
            continue

        group = normalize_group(
            actor.get(
                "groupe_actuel"
            )
        )

        if not group:

            group = (
                "Inconnu"
            )

        deputes.append({

            "uid":
                uid,

            "nom":
                name,

            "groupe":
                group,

            "groupe_actuel":
                group,

            "departement":
                clean(
                    actor.get(
                        "departement"
                    )
                ),

            "num_departement":
                clean(
                    actor.get(
                        "num_departement"
                    )
                ),

            "num_circonscription":
                clean(
                    actor.get(
                        "num_circonscription"
                    )
                ),

            "circonscription":
                normalize_circonscription(
                    actor.get(
                        "circonscription"
                    )
                ),

            "votes_count":
                votes_by_uid.get(
                    uid,
                    0
                ),

            "votes_par_annee":
                dict(
                    votes_by_uid_year.get(
                        uid,
                        {}
                    )
                )
        })

    deputes.sort(
        key=lambda deputy:
            deputy[
                "nom"
            ].lower()
    )

    payload = {

        "updated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "total":
            len(
                deputes
            ),

        "deputes":
            deputes
    }

    write_json(
        BASE_DIR
        / "deputes.json",
        payload
    )

    print(
        "deputes.json :",
        len(
            deputes
        )
    )

    return deputes


# ============================================================
# COMPOSITION.JSON
# ============================================================

def build_composition_file(
    deputes
):

    grouped = defaultdict(
        list
    )

    for deputy in deputes:

        group = normalize_group(
            deputy.get(
                "groupe_actuel"
            )
            or deputy.get(
                "groupe"
            )
        )

        if not group:

            group = (
                "Inconnu"
            )

        grouped[
            group
        ].append(
            deputy
        )

    total = len(
        deputes
    )

    groups = []

    for group, members in grouped.items():

        members.sort(
            key=lambda member:
                member[
                    "nom"
                ].lower()
        )

        groups.append({

            "groupe":
                group,

            "count":
                len(
                    members
                ),

            "pct":
                round(
                    (
                        len(
                            members
                        )
                        /
                        total
                        *
                        100
                    )
                    if total
                    else 0,
                    1
                ),

            "members": [

                {

                    "uid":
                        member[
                            "uid"
                        ],

                    "nom":
                        member[
                            "nom"
                        ],

                    "departement":
                        member[
                            "departement"
                        ],

                    "circonscription":
                        member[
                            "circonscription"
                        ]
                }

                for member in members

            ]
        })

    groups.sort(
        key=lambda group: (
            -group[
                "count"
            ],
            group[
                "groupe"
            ]
        )
    )

    unknown_count = len(
        grouped.get(
            "Inconnu",
            []
        )
    )

    is_valid = (
        total >= 500
        and total <= MAX_ASSEMBLY_SEATS
        and unknown_count <= 5
    )

    composition = {

        "updated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "total":
            total,

        "sieges_theoriques":
            MAX_ASSEMBLY_SEATS,

        "sieges_vacants":
            max(
                0,
                MAX_ASSEMBLY_SEATS
                - total
            ),

        "groupes_inconnus":
            unknown_count,

        "is_valid":
            is_valid,

        "groupes":
            groups,

        "source":
            "Assemblée nationale — mandats actifs"
    }

    write_json(
        BASE_DIR
        / "composition.json",
        composition
    )

    print("")
    print(
        "Composition :",
        total,
        "députés"
    )

    print(
        "Groupes inconnus :",
        unknown_count
    )

    print(
        "Composition valide :",
        is_valid
    )

    print("")

    for group in groups:

        print(
            " -",
            group[
                "groupe"
            ],
            ":",
            group[
                "count"
            ]
        )

    return composition


# ============================================================
# FICHIERS PAR MOIS
# ============================================================

def write_month_files(
    scrutins
):

    ensure_dir(
        MONTHS_DIR
    )

    # Supprime les anciens mois
    for old_file in MONTHS_DIR.glob(
        "*.json"
    ):

        old_file.unlink()

    grouped = defaultdict(
        list
    )

    for scrutin in scrutins:

        month = clean(
            scrutin.get(
                "date"
            )
        )[:7]

        if not month:
            continue

        grouped[
            month
        ].append(
            scrutin
        )

    month_index = []

    for month, items in grouped.items():

        items.sort(
            key=lambda item:
                item.get(
                    "date",
                    ""
                ),
            reverse=True
        )

        path = (
            MONTHS_DIR
            / f"{month}.json"
        )

        write_json(
            path,
            {

                "month":
                    month,

                "year":
                    int(
                        month[:4]
                    ),

                "scrutins":
                    items
            }
        )

        month_index.append({

            "month":
                month,

            "file":
                (
                    "data/current/months/"
                    f"{month}.json"
                ),

            "scrutins":
                len(
                    items
                )
        })

    month_index.sort(
        key=lambda item:
            item[
                "month"
            ],
        reverse=True
    )

    return month_index


# ============================================================
# GROUPES.JSON
# ============================================================

def build_groupes_file(
    scrutins,
    composition
):

    data = {}

    for scrutin in scrutins:

        year = int(
            scrutin[
                "year"
            ]
        )

        for summary in scrutin.get(
            "groupes_summary",
            []
        ):

            group = normalize_group(
                summary.get(
                    "groupe"
                )
            )

            if (
                not group
                or group == "Inconnu"
            ):
                continue

            key = (
                year,
                group
            )

            if key not in data:

                data[
                    key
                ] = {

                    "year":
                        year,

                    "groupe":
                        group,

                    "scrutins_count":
                        0,

                    "votes": {

                        "pour":
                            0,

                        "contre":
                            0,

                        "abstention":
                            0,

                        "non_votant":
                            0
                    },

                    "_themes":
                        defaultdict(
                            int
                        ),

                    "scrutins":
                        []
                }

            entry = data[
                key
            ]

            entry[
                "scrutins_count"
            ] += 1

            entry[
                "votes"
            ][
                "pour"
            ] += summary.get(
                "pour",
                0
            )

            entry[
                "votes"
            ][
                "contre"
            ] += summary.get(
                "contre",
                0
            )

            entry[
                "votes"
            ][
                "abstention"
            ] += summary.get(
                "abstention",
                0
            )

            entry[
                "votes"
            ][
                "non_votant"
            ] += summary.get(
                "non_votant",
                0
            )

            theme = clean(
                scrutin.get(
                    "theme"
                )
            ) or "Autres"

            entry[
                "_themes"
            ][
                theme
            ] += 1

            entry[
                "scrutins"
            ].append({

                "uid":
                    scrutin[
                        "uid"
                    ],

                "date":
                    scrutin[
                        "date"
                    ],

                "sujet":
                    scrutin[
                        "sujet"
                    ],

                "titre":
                    scrutin[
                        "titre"
                    ],

                "titre_officiel":
                    scrutin[
                        "titre_officiel"
                    ],

                "description":
                    scrutin[
                        "description"
                    ],

                "theme":
                    theme,

                "position":
                    summary[
                        "position"
                    ],

                "cohesion_pct":
                    summary[
                        "cohesion_pct"
                    ],

                "pour":
                    summary[
                        "pour"
                    ],

                "contre":
                    summary[
                        "contre"
                    ],

                "abstention":
                    summary[
                        "abstention"
                    ],

                "non_votant":
                    summary[
                        "non_votant"
                    ],

                "total":
                    summary[
                        "total"
                    ]
            })

    composition_map = {

        normalize_group(
            group[
                "groupe"
            ]
        ):
            group[
                "count"
            ]

        for group in composition.get(
            "groupes",
            []
        )
    }

    result = []

    for entry in data.values():

        entry[
            "themes"
        ] = [

            {

                "theme":
                    theme,

                "scrutins":
                    count
            }

            for theme, count
            in sorted(

                entry[
                    "_themes"
                ].items(),

                key=lambda item: (
                    -item[1],
                    item[0]
                )
            )

        ]

        del entry[
            "_themes"
        ]

        entry[
            "scrutins"
        ].sort(
            key=lambda scrutin:
                scrutin[
                    "date"
                ],
            reverse=True
        )

        entry[
            "deputes_actuels"
        ] = composition_map.get(
            normalize_group(
                entry[
                    "groupe"
                ]
            ),
            0
        )

        result.append(
            entry
        )

    result.sort(
        key=lambda entry: (
            -entry[
                "year"
            ],
            entry[
                "groupe"
            ]
        )
    )

    write_json(
        BASE_DIR
        / "groupes.json",
        {

            "updated_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "groupes":
                result
        }
    )

    print(
        "groupes.json :",
        len(
            result
        ),
        "fiches groupe/année"
    )


# ============================================================
# SEARCH.JSON
# ============================================================

def build_search_file(
    deputes,
    composition,
    scrutins
):

    departments = sorted({

        clean(
            deputy.get(
                "departement"
            )
        )

        for deputy in deputes

        if clean(
            deputy.get(
                "departement"
            )
        )

    })

    constituencies = sorted({

        clean(
            deputy.get(
                "circonscription"
            )
        )

        for deputy in deputes

        if clean(
            deputy.get(
                "circonscription"
            )
        )

    })

    themes = sorted({

        clean(
            scrutin.get(
                "theme"
            )
        )

        for scrutin in scrutins

        if clean(
            scrutin.get(
                "theme"
            )
        )

    })

    groups = [

        {

            "groupe":
                group[
                    "groupe"
                ],

            "count":
                group[
                    "count"
                ]

        }

        for group in composition.get(
            "groupes",
            []
        )

        if group.get(
            "groupe"
        ) != "Inconnu"

    ]

    payload = {

        "updated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "deputes": [

            {

                "uid":
                    deputy[
                        "uid"
                    ],

                "nom":
                    deputy[
                        "nom"
                    ],

                "groupe":
                    deputy[
                        "groupe"
                    ],

                "departement":
                    deputy[
                        "departement"
                    ],

                "num_departement":
                    deputy[
                        "num_departement"
                    ],

                "num_circonscription":
                    deputy[
                        "num_circonscription"
                    ],

                "circonscription":
                    deputy[
                        "circonscription"
                    ]

            }

            for deputy in deputes

        ],

        "groupes":
            groups,

        "departements":
            departments,

        "circonscriptions":
            constituencies,

        "themes":
            themes
    }

    write_json(
        BASE_DIR
        / "search.json",
        payload
    )

    print(
        "search.json créé"
    )


# ============================================================
# INDEX.JSON
# ============================================================

def build_years_data(
    scrutins,
    month_index
):

    years = sorted({

        int(
            scrutin[
                "year"
            ]
        )

        for scrutin in scrutins

    })

    result = {}

    for year in years:

        year_scrutins = [

            scrutin

            for scrutin in scrutins

            if int(
                scrutin[
                    "year"
                ]
            ) == year

        ]

        months = [

            month

            for month in month_index

            if int(
                month[
                    "month"
                ][:4]
            ) == year

        ]

        votes_count = sum(

            int(
                scrutin.get(
                    "stats",
                    {}
                ).get(
                    "total_votes",
                    0
                )
            )

            for scrutin in year_scrutins

        )

        groups = {

            normalize_group(
                summary.get(
                    "groupe"
                )
            )

            for scrutin in year_scrutins

            for summary in scrutin.get(
                "groupes_summary",
                []
            )

            if normalize_group(
                summary.get(
                    "groupe"
                )
            )
            not in {
                "",
                "Inconnu"
            }

        }

        result[
            str(
                year
            )
        ] = {

            "counts": {

                "scrutins":
                    len(
                        year_scrutins
                    ),

                "votes":
                    votes_count,

                "groupes":
                    len(
                        groups
                    )
            },

            "months":
                months
        }

    return result


def build_index_file(
    scrutins,
    month_index,
    composition
):

    years_data = build_years_data(
        scrutins,
        month_index
    )

    available_years = sorted(

        [
            int(
                year
            )
            for year
            in years_data.keys()
        ],

        reverse=True
    )

    if CURRENT_YEAR in available_years:

        default_year = (
            CURRENT_YEAR
        )

    elif available_years:

        default_year = (
            available_years[
                0
            ]
        )

    else:

        default_year = (
            CURRENT_YEAR
        )

    default_data = years_data.get(
        str(
            default_year
        ),
        {

            "counts": {

                "scrutins":
                    0,

                "votes":
                    0,

                "groupes":
                    0
            },

            "months":
                []
        }
    )

    payload = {

        "version":
            "GROUP_FIRST_V1",

        "updated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "legislature":
            int(
                LEGISLATURE
            ),

        "available_years":
            available_years,

        "default_year":
            default_year,

        # Compatibilité ancienne page
        "counts":
            default_data[
                "counts"
            ],

        "months":
            default_data[
                "months"
            ],

        "years":
            years_data,

        "composition": {

            "total":
                composition[
                    "total"
                ],

            "sieges_theoriques":
                composition[
                    "sieges_theoriques"
                ],

            "sieges_vacants":
                composition[
                    "sieges_vacants"
                ],

            "is_valid":
                composition[
                    "is_valid"
                ]
        }
    }

    write_json(
        BASE_DIR
        / "index.json",
        payload
    )

    print(
        "index.json créé"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print(
        "=============================================="
    )
    print(
        " BUILD DATA — GROUP FIRST V1"
    )
    print(
        "=============================================="
    )
    print("")

    ensure_dir(
        BASE_DIR
    )

    ensure_dir(
        MONTHS_DIR
    )

    # --------------------------------------------------------
    # 1. ACTEURS / MANDATS / ORGANES
    # --------------------------------------------------------

    (
        actors,
        current_actors,
        organes
    ) = load_amo()

    # --------------------------------------------------------
    # 2. SCRUTINS
    # --------------------------------------------------------

    scrutins = load_scrutins(
        actors,
        current_actors,
        organes
    )

    # --------------------------------------------------------
    # 3. DEPUTES.JSON
    # --------------------------------------------------------

    deputes = build_deputes_file(
        current_actors,
        scrutins
    )

    # --------------------------------------------------------
    # 4. COMPOSITION.JSON
    # --------------------------------------------------------

    composition = build_composition_file(
        deputes
    )

    # --------------------------------------------------------
    # 5. MOIS
    # --------------------------------------------------------

    month_index = write_month_files(
        scrutins
    )

    # --------------------------------------------------------
    # 6. GROUPES.JSON
    # --------------------------------------------------------

    build_groupes_file(
        scrutins,
        composition
    )

    # --------------------------------------------------------
    # 7. SEARCH.JSON
    # --------------------------------------------------------

    build_search_file(
        deputes,
        composition,
        scrutins
    )

    # --------------------------------------------------------
    # 8. INDEX.JSON
    # --------------------------------------------------------

    build_index_file(
        scrutins,
        month_index,
        composition
    )

    print("")
    print(
        "=============================================="
    )
    print(
        " BUILD TERMINÉ"
    )
    print(
        "=============================================="
    )
    print("")

    print(
        "Députés actuels :",
        len(
            deputes
        )
    )

    print(
        "Scrutins :",
        len(
            scrutins
        )
    )

    print(
        "Années :",
        sorted({

            scrutin[
                "year"
            ]

            for scrutin in scrutins

        })
    )

    print("")
    print(
        "Fichiers créés :"
    )

    print(
        " data/current/index.json"
    )

    print(
        " data/current/search.json"
    )

    print(
        " data/current/composition.json"
    )

    print(
        " data/current/deputes.json"
    )

    print(
        " data/current/groupes.json"
    )

    print(
        " data/current/months/YYYY-MM.json"
    )

    print("")


if __name__ == "__main__":
    main()
