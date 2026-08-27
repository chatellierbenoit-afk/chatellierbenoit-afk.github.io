import json
import re
import ssl
import time
import socket
import http.client
import urllib.request
import urllib.error
import zipfile

from collections import Counter, defaultdict
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

LEGISLATURE = "17"

CURRENT_YEAR = datetime.now(timezone.utc).year
MIN_YEAR = CURRENT_YEAR - 1

MAX_ASSEMBLY_SEATS = 577


# ============================================================
# SOURCES OFFICIELLES
#
# AMO40 :
# députés actuellement en exercice
# + leurs mandats actifs
# + les organes correspondants
#
# IMPORTANT :
# les mandats sont contenus directement dans les acteurs.
# ============================================================

AMO40_URL = (
    "https://data.assemblee-nationale.fr/static/openData/"
    "repository/17/amo/"
    "deputes_actifs_mandats_actifs_organes_divises/"
    "AMO40_deputes_actifs_mandats_actifs_organes_divises.json.zip"
)

SCRUTINS_URL = (
    "https://data.assemblee-nationale.fr/static/openData/"
    "repository/17/loi/scrutins/"
    "Scrutins.json.zip"
)


BASE_DIR = Path("data/current")
MONTHS_DIR = BASE_DIR / "months"

SSL_CONTEXT = ssl.create_default_context()


# ============================================================
# NORMALISATION DES GROUPES
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


    "Socialistes et apparentes":
        "Socialistes et apparentés",

    "Socialistes et apparentés":
        "Socialistes et apparentés",


    "Droite republicaine":
        "Droite Républicaine",

    "Droite Républicaine":
        "Droite Républicaine",


    "Ecologiste et Social":
        "Écologiste et Social",

    "Écologiste et Social":
        "Écologiste et Social",


    "Les Democrates":
        "Les Démocrates",

    "Les Démocrates":
        "Les Démocrates",


    "Horizons et Indépendants":
        "Horizons & Indépendants",

    "Horizons et indépendants":
        "Horizons & Indépendants",

    "Horizons & Indépendants":
        "Horizons & Indépendants",


    "Libertés, indépendants, outre-mer et territoires":
        "Libertés, Indépendants, Outre-mer et Territoires",

    "Libertés, Indépendants, Outre-mer et Territoires":
        "Libertés, Indépendants, Outre-mer et Territoires",


    "Gauche démocrate et républicaine":
        "Gauche Démocrate et Républicaine",

    "Gauche Démocrate et Républicaine":
        "Gauche Démocrate et Républicaine",


    "Union des Droites pour la République":
        "Union des droites pour la République",

    "Union des droites pour la République":
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


GROUP_SIGLES = {

    "Rassemblement National":
        "RN",

    "Ensemble pour la République":
        "EPR",

    "La France insoumise - Nouveau Front Populaire":
        "LFI-NFP",

    "Socialistes et apparentés":
        "SOC",

    "Droite Républicaine":
        "DR",

    "Écologiste et Social":
        "ECOS",

    "Les Démocrates":
        "DEM",

    "Horizons & Indépendants":
        "HOR",

    "Libertés, Indépendants, Outre-mer et Territoires":
        "LIOT",

    "Gauche Démocrate et Républicaine":
        "GDR",

    "Union des droites pour la République":
        "UDR",

    "Non inscrits":
        "NI",
}


# ============================================================
# OUTILS
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
        .replace(
            "\u00a0",
            " "
        )
        .split()
    ).strip()


def ensure_list(value):

    if value is None:
        return []

    if isinstance(
        value,
        list
    ):
        return value

    return [value]


def write_json(
    path,
    data
):

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

    if isinstance(
        value,
        dict
    ):

        return clean(
            value.get("#text")
            or value.get("uid")
            or value.get("value")
            or ""
        )

    return clean(
        value
    )


def normalize_group(value):

    value = clean(
        value
    )

    if not value:
        return ""

    return GROUP_ALIASES.get(
        value,
        value
    )


def group_sigle(group):

    return GROUP_SIGLES.get(
        normalize_group(
            group
        ),
        ""
    )


def ordinal_fr(number):

    value = clean(
        number
    )

    try:

        number = int(
            value
        )

    except Exception:

        return value

    if number == 1:
        return "1re"

    return f"{number}e"


def normalize_circonscription(value):

    value = clean(
        value
    )

    if not value:
        return ""

    replacements = {

        "1ère":
            "1re",

        "1ere":
            "1re",

        "1er":
            "1re",

        "2ème":
            "2e",

        "2eme":
            "2e",

        "3ème":
            "3e",

        "3eme":
            "3e",

        "4ème":
            "4e",

        "4eme":
            "4e",

        "5ème":
            "5e",

        "5eme":
            "5e",

        "6ème":
            "6e",

        "6eme":
            "6e",

        "7ème":
            "7e",

        "7eme":
            "7e",

        "8ème":
            "8e",

        "8eme":
            "8e",

        "9ème":
            "9e",

        "9eme":
            "9e",

        "10ème":
            "10e",

        "10eme":
            "10e",

        "11ème":
            "11e",

        "11eme":
            "11e",

        "12ème":
            "12e",

        "12eme":
            "12e",

        "13ème":
            "13e",

        "13eme":
            "13e",

        "14ème":
            "14e",

        "14eme":
            "14e",

        "15ème":
            "15e",

        "15eme":
            "15e",

        "16ème":
            "16e",

        "16eme":
            "16e",

        "17ème":
            "17e",

        "17eme":
            "17e",

        "18ème":
            "18e",

        "18eme":
            "18e",

        "19ème":
            "19e",

        "19eme":
            "19e",

        "20ème":
            "20e",

        "20eme":
            "20e",

        "21ème":
            "21e",

        "21eme":
            "21e",
    }

    for old, new in replacements.items():

        value = value.replace(
            old,
            new
        )

    return value


# ============================================================
# TÉLÉCHARGEMENT ROBUSTE
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
                        f"Téléchargement vide : {url}"
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
                f"Téléchargement échoué "
                f"({attempt}/{retries})"
            )

            print(
                url
            )

            print(
                error
            )


            if attempt < retries:

                time.sleep(
                    pause
                    * attempt
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
            f"Le fichier téléchargé "
            f"n'est pas un ZIP : {url}"
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

    refs = []

    if isinstance(
        node,
        dict
    ):

        if "organeRef" in node:

            for item in ensure_list(
                node.get(
                    "organeRef"
                )
            ):

                uid = get_uid(
                    item
                )

                if uid:

                    refs.append(
                        uid
                    )


        for value in node.values():

            refs.extend(
                extract_organe_refs(
                    value
                )
            )


    elif isinstance(
        node,
        list
    ):

        for item in node:

            refs.extend(
                extract_organe_refs(
                    item
                )
            )


    return list(
        dict.fromkeys(
            refs
        )
    )


def extract_votants(node):

    voters = []

    if isinstance(
        node,
        dict
    ):

        if "votant" in node:

            for voter in ensure_list(
                node.get(
                    "votant"
                )
            ):

                if isinstance(
                    voter,
                    dict
                ):

                    voters.append(
                        voter
                    )


        elif "acteurRef" in node:

            voters.append(
                node
            )


        else:

            for value in node.values():

                voters.extend(
                    extract_votants(
                        value
                    )
                )


    elif isinstance(
        node,
        list
    ):

        for item in node:

            voters.extend(
                extract_votants(
                    item
                )
            )


    return voters


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
        ),
    ]

    for candidate in candidates:

        candidate = clean(
            candidate
        )

        if candidate:

            return candidate

    return ""


# ============================================================
# MANDATS EMBARQUÉS DANS LES ACTEURS AMO40
# ============================================================

def get_actor_mandates(actor):

    mandates_node = actor.get(
        "mandats",
        {}
    )

    if isinstance(
        mandates_node,
        dict
    ):

        return [

            mandate

            for mandate
            in ensure_list(
                mandates_node.get(
                    "mandat"
                )
            )

            if isinstance(
                mandate,
                dict
            )
        ]


    if isinstance(
        mandates_node,
        list
    ):

        return [

            mandate

            for mandate
            in mandates_node

            if isinstance(
                mandate,
                dict
            )
        ]


    return []


# ============================================================
# CIRCONSCRIPTION / DÉPARTEMENT
# ============================================================

def extract_department_from_lieu(lieu):

    if not isinstance(
        lieu,
        dict
    ):

        return (
            "",
            ""
        )


    dep_obj = lieu.get(
        "departement"
    )


    dep_name = ""


    dep_code = clean(

        lieu.get(
            "numDepartement"
        )

        or

        lieu.get(
            "numeroDepartement"
        )

        or
        ""
    )


    if isinstance(
        dep_obj,
        dict
    ):

        dep_name = clean(

            dep_obj.get(
                "libelle"
            )

            or

            dep_obj.get(
                "nom"
            )

            or

            dep_obj.get(
                "#text"
            )

            or
            ""
        )


        dep_code = (
            dep_code
            or clean(
                dep_obj.get(
                    "code"
                )
                or
                dep_obj.get(
                    "numero"
                )
                or
                ""
            )
        )


    else:

        dep_name = clean(
            dep_obj
        )


    return (
        dep_name,
        dep_code
    )


# ============================================================
# THÉMATIQUES
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
# TITRE LISIBLE D'UN SCRUTIN
# ============================================================

def truncate(
    value,
    max_length=180
):

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
                match.group(
                    1
                ),
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
                170
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

        title = (
            f"Sous-amendement n°{number}"
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
    # NETTOYAGE TITRE ADMINISTRATIF
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
# CHARGEMENT DES DÉPUTÉS ACTUELS
# ============================================================

def load_current_deputies():

    print("")
    print(
        "Téléchargement AMO40 "
        "— députés actifs / mandats actifs / organes..."
    )


    raw = download_zip(
        AMO40_URL
    )


    zf = zipfile.ZipFile(
        BytesIO(
            raw
        )
    )


    raw_actors = {}

    organes = {}


    # ========================================================
    # LECTURE DES ACTEURS ET ORGANES
    # ========================================================

    for filename, payload in iter_zip_json(
        zf
    ):

        if not isinstance(
            payload,
            dict
        ):

            continue


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

            if uid:

                raw_actors[
                    uid
                ] = actor

            continue


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

            if uid:

                organes[
                    uid
                ] = organe


    print(
        "Acteurs actifs reçus :",
        len(
            raw_actors
        )
    )


    print(
        "Organes reçus :",
        len(
            organes
        )
    )


    # ========================================================
    # MAPPING REF GROUPE → NOM DU GROUPE
    # ========================================================

    group_ref_to_label = {}


    for uid, actor in raw_actors.items():

        mandates = get_actor_mandates(
            actor
        )


        for mandate in mandates:

            mandate_type = clean(
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


            # ------------------------------------------------
            # MANDAT EXPLICITEMENT DE TYPE GP
            # ------------------------------------------------

            if mandate_type in {
                "GP",
                "GRP",
                "GROUPE"
            }:

                for ref in refs:

                    organe = organes.get(
                        ref,
                        {}
                    )


                    label = normalize_group(
                        get_organe_label(
                            organe
                        )
                    )


                    if label:

                        group_ref_to_label[
                            ref
                        ] = label


            # ------------------------------------------------
            # OU ORGANE LUI-MÊME DE TYPE GP
            # ------------------------------------------------

            else:

                for ref in refs:

                    organe = organes.get(
                        ref,
                        {}
                    )


                    code_type = clean(
                        organe.get(
                            "codeType"
                        )
                    ).upper()


                    if code_type in {
                        "GP",
                        "GRP",
                        "GROUPE"
                    }:

                        label = normalize_group(
                            get_organe_label(
                                organe
                            )
                        )


                        if label:

                            group_ref_to_label[
                                ref
                            ] = label


    print(
        "Organes de groupes identifiés :",
        len(
            group_ref_to_label
        )
    )


    # ========================================================
    # CONSTRUCTION DES DÉPUTÉS
    # ========================================================

    deputies = {}


    for uid, actor in raw_actors.items():

        etat_civil = actor.get(
            "etatCivil",
            {}
        )


        if not isinstance(
            etat_civil,
            dict
        ):

            etat_civil = {}


        ident = etat_civil.get(
            "ident",
            {}
        )


        if not isinstance(
            ident,
            dict
        ):

            ident = {}


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


        name = clean(
            f"{first_name} {last_name}"
        )


        if not name:

            continue


        group = ""

        departement = ""

        num_departement = ""

        num_circo = ""

        circonscription = ""

        has_assembly_mandate = False


        mandates = get_actor_mandates(
            actor
        )


        for mandate in mandates:

            mandate_type = clean(
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


            # =================================================
            # MANDAT DE DÉPUTÉ
            # =================================================

            if mandate_type == "ASSEMBLEE":

                has_assembly_mandate = True


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


                (
                    dep_name,
                    dep_code
                ) = extract_department_from_lieu(
                    lieu
                )


                if dep_name:

                    departement = (
                        departement
                        or dep_name
                    )


                if dep_code:

                    num_departement = (
                        num_departement
                        or dep_code
                    )


                num_circo_value = clean(

                    lieu.get(
                        "numCirco"
                    )

                    or

                    lieu.get(
                        "numeroCirconscription"
                    )
                )


                if num_circo_value:

                    num_circo = (
                        num_circo
                        or num_circo_value
                    )


                    circonscription = (
                        f"{ordinal_fr(num_circo)} "
                        f"circonscription"
                    )


                ref_circo = get_uid(
                    election.get(
                        "refCirconscription"
                    )
                )


                if (
                    ref_circo
                    and ref_circo in organes
                    and not circonscription
                ):

                    circonscription = (
                        normalize_circonscription(
                            get_organe_label(
                                organes[
                                    ref_circo
                                ]
                            )
                        )
                    )


            # =================================================
            # GROUPE POLITIQUE
            # =================================================

            if mandate_type in {
                "GP",
                "GRP",
                "GROUPE"
            }:

                for ref in refs:

                    candidate = (
                        group_ref_to_label.get(
                            ref
                        )
                    )


                    if candidate:

                        group = candidate

                        break


            # Sécurité supplémentaire :
            # vérifie également les organes référencés
            if not group:

                for ref in refs:

                    candidate = (
                        group_ref_to_label.get(
                            ref
                        )
                    )


                    if candidate:

                        group = candidate

                        break


        # ====================================================
        # ABSENCE DE MANDAT GP = NON INSCRIT
        # ====================================================

        if not group:

            group = (
                "Non inscrits"
            )


        deputies[
            uid
        ] = {

            "uid":
                uid,

            "nom":
                name,

            "groupe_actuel":
                normalize_group(
                    group
                ),

            "groupe_sigle":
                group_sigle(
                    group
                ),

            "departement":
                departement,

            "num_departement":
                num_departement,

            "num_circonscription":
                num_circo,

            "circonscription":
                normalize_circonscription(
                    circonscription
                ),

            "has_assembly_mandate":
                has_assembly_mandate,
        }


    # ========================================================
    # CONTRÔLE DE COHÉRENCE
    # ========================================================

    validate_current_deputies(
        deputies
    )


    print("")
    print(
        "Députés actuels retenus :",
        len(
            deputies
        )
    )


    counts = Counter(

        deputy[
            "groupe_actuel"
        ]

        for deputy
        in deputies.values()
    )


    print("")
    print(
        "Composition calculée :"
    )


    for group, count in counts.most_common():

        print(
            f" - {group}: {count}"
        )


    print("")


    return (
        deputies,
        organes,
        group_ref_to_label
    )


# ============================================================
# VALIDATION COMPOSITION
#
# Si les données deviennent aberrantes,
# le script s'arrête AVANT de publier les mauvais JSON.
# ============================================================

def validate_current_deputies(
    deputies
):

    total = len(
        deputies
    )


    counts = Counter(

        deputy.get(
            "groupe_actuel"
        )
        or "Inconnu"

        for deputy
        in deputies.values()
    )


    group_count = len(
        counts
    )


    unknown = counts.get(
        "Inconnu",
        0
    )


    non_inscrits = counts.get(
        "Non inscrits",
        0
    )


    largest = (

        max(
            counts.values()
        )

        if counts

        else 0
    )


    errors = []


    if not (
        500
        <= total
        <= MAX_ASSEMBLY_SEATS
    ):

        errors.append(
            f"nombre de députés incohérent : {total}"
        )


    if not (
        8
        <= group_count
        <= 20
    ):

        errors.append(
            f"nombre de groupes incohérent : {group_count}"
        )


    if non_inscrits > 100:

        errors.append(
            f"trop de Non inscrits : {non_inscrits}"
        )


    if unknown > 10:

        errors.append(
            f"trop de groupes inconnus : {unknown}"
        )


    if largest > 300:

        errors.append(
            f"un groupe contient anormalement "
            f"{largest} députés"
        )


    if errors:

        print("")
        print(
            "==========================================="
        )

        print(
            "ERREUR DE VALIDATION DE LA COMPOSITION"
        )

        print(
            "==========================================="
        )


        for error in errors:

            print(
                " -",
                error
            )


        print(
            "Composition observée :",
            dict(
                counts
            )
        )


        raise RuntimeError(

            "La récupération des groupes politiques "
            "a échoué. Le build est volontairement "
            "stoppé pour ne pas publier de mauvaises données."
        )


# ============================================================
# STATISTIQUES DES VOTES
# ============================================================

def compute_vote_stats(
    votes
):

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
            ),
    }


def dominant_position(
    stats
):

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
            ),
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


    if len(
        winners
    ) == 1:

        return winners[
            0
        ]


    return "Partagé"


def cohesion_percent(
    stats
):

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


# ============================================================
# INFÉRENCE D'UN GROUPE DE SCRUTIN
#
# Utilisée uniquement si l'organeRef du scrutin
# n'est pas directement résolu.
# ============================================================

def infer_group_from_voters(
    block_voters,
    current_deputies
):

    groups = []


    for actor_uid, vote_label in block_voters:

        deputy = current_deputies.get(
            actor_uid
        )


        if not deputy:

            continue


        group = normalize_group(
            deputy.get(
                "groupe_actuel"
            )
        )


        if group:

            groups.append(
                group
            )


    if not groups:

        return ""


    counts = Counter(
        groups
    )


    group, count = (
        counts.most_common(
            1
        )[0]
    )


    # On n'infère que si au moins 60 %
    # des députés du bloc appartiennent
    # actuellement au même groupe.
    if (
        count
        / len(groups)
        >= 0.60
    ):

        return group


    return ""


# ============================================================
# RÉSUMÉ PAR GROUPE
# ============================================================

def compute_group_summary(
    votes
):

    grouped = defaultdict(
        list
    )


    for vote in votes:

        group = normalize_group(

            vote.get(
                "groupe_au_vote"
            )

            or

            vote.get(
                "groupe"
            )

            or
            ""
        )


        if not group:

            group = (
                "Inconnu"
            )


        grouped[
            group
        ].append(
            vote
        )


    result = []


    for group, group_votes in grouped.items():

        stats = compute_vote_stats(
            group_votes
        )


        result.append({

            "groupe":
                group,

            "groupe_sigle":
                group_sigle(
                    group
                ),

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

            "total":
                stats[
                    "total"
                ],

            "position":
                dominant_position(
                    stats
                ),

            "cohesion_pct":
                cohesion_percent(
                    stats
                ),
        })


    return sorted(

        result,

        key=lambda row: (

            -row[
                "total"
            ],

            row[
                "groupe"
            ]
        )
    )


# ============================================================
# SCRUTINS
# ============================================================

def load_scrutins(
    current_deputies,
    organes,
    group_ref_to_label
):

    print("")
    print(
        "Téléchargement des scrutins..."
    )


    raw = download_zip(
        SCRUTINS_URL
    )


    zf = zipfile.ZipFile(
        BytesIO(
            raw
        )
    )


    scrutins = []


    unresolved_group_refs = Counter()


    for filename, payload in iter_zip_json(
        zf
    ):

        if not isinstance(
            payload,
            dict
        ):

            continue


        scrutin = payload.get(
            "scrutin",
            payload
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
                scrutin_date[
                    :4
                ]
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

            or

            objet.get(
                "titre"
            )

            or
            ""
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


        # ====================================================
        # BLOCS DE GROUPES
        # ====================================================

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


        votes = []


        for group_block in group_blocks:

            if not isinstance(
                group_block,
                dict
            ):

                continue


            # ================================================
            # IDENTIFICATION DU GROUPE
            # ================================================

            group_ref = get_uid(
                group_block.get(
                    "organeRef"
                )
            )


            group_name = normalize_group(

                clean(

                    group_block.get(
                        "libelle"
                    )

                    or

                    group_block.get(
                        "libelleAbrege"
                    )

                    or

                    group_block.get(
                        "libelleAbrev"
                    )

                    or
                    ""
                )
            )


            if (
                not group_name
                and group_ref
            ):

                group_name = (
                    group_ref_to_label.get(
                        group_ref,
                        ""
                    )
                )


            if (
                not group_name
                and group_ref in organes
            ):

                organe = organes[
                    group_ref
                ]


                code_type = clean(
                    organe.get(
                        "codeType"
                    )
                ).upper()


                if code_type in {
                    "GP",
                    "GRP",
                    "GROUPE"
                }:

                    group_name = normalize_group(
                        get_organe_label(
                            organe
                        )
                    )


            # ================================================
            # VOTANTS DU BLOC
            # ================================================

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


            block_voters = []


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
                ),
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


                    if actor_uid:

                        block_voters.append(
                            (
                                actor_uid,
                                label
                            )
                        )


            # ================================================
            # FALLBACK SI LE GROUPE DU SCRUTIN N'A PAS
            # ÉTÉ RÉSOLU VIA ORGANE REF
            # ================================================

            if not group_name:

                group_name = infer_group_from_voters(
                    block_voters,
                    current_deputies
                )


            if not group_name:

                group_name = (
                    "Inconnu"
                )


                if group_ref:

                    unresolved_group_refs[
                        group_ref
                    ] += 1


            # ================================================
            # CONSTRUCTION DES VOTES
            # ================================================

            for actor_uid, label in block_voters:

                deputy = current_deputies.get(
                    actor_uid,
                    {}
                )


                name = clean(
                    deputy.get(
                        "nom"
                    )
                )


                if not name:

                    name = actor_uid


                current_group = normalize_group(
                    deputy.get(
                        "groupe_actuel"
                    )
                )


                votes.append({

                    "depute_uid":
                        actor_uid,

                    "nom":
                        name,

                    # Groupe au moment du vote
                    "groupe_au_vote":
                        group_name,

                    # Compatibilité avec les pages
                    "groupe":
                        group_name,

                    # Groupe actuel
                    "groupe_actuel":
                        current_group,

                    "groupe_actuel_sigle":
                        group_sigle(
                            current_group
                        ),

                    "vote":
                        label,

                    "departement":
                        clean(
                            deputy.get(
                                "departement"
                            )
                        ),

                    "circonscription":
                        normalize_circonscription(
                            deputy.get(
                                "circonscription"
                            )
                        ),
                })


        # ====================================================
        # DÉDOUBLONNAGE
        # ====================================================

        unique_votes = {}


        for vote in votes:

            actor_uid = vote.get(
                "depute_uid"
            )


            if (
                actor_uid
                and actor_uid not in unique_votes
            ):

                unique_votes[
                    actor_uid
                ] = vote


        votes = list(
            unique_votes.values()
        )


        if not votes:

            continue


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

            # Titre lisible pour l'utilisateur
            "sujet":
                subject,

            "titre_court":
                subject,

            # Texte officiel
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
                    ],
            },

            "groupes_summary":
                group_summary,

            "votes":
                votes,
        })


    scrutins.sort(

        key=lambda row: (

            row.get(
                "date",
                ""
            ),

            str(
                row.get(
                    "numero",
                    ""
                )
            )
        ),

        reverse=True
    )


    # ========================================================
    # CONTRÔLE SCRUTINS
    # ========================================================

    validate_scrutins(
        scrutins
    )


    print("")
    print(
        "Scrutins conservés :",
        len(
            scrutins
        )
    )


    if unresolved_group_refs:

        print(
            "Références groupes non résolues "
            "(10 principales) :",
            unresolved_group_refs.most_common(
                10
            )
        )


    return scrutins


# ============================================================
# VALIDATION DES GROUPES DANS LES SCRUTINS
# ============================================================

def validate_scrutins(
    scrutins
):

    if not scrutins:

        raise RuntimeError(
            "Aucun scrutin n'a été récupéré."
        )


    by_year = defaultdict(
        list
    )


    for scrutin in scrutins:

        by_year[
            str(
                scrutin.get(
                    "year"
                )
            )
        ].append(
            scrutin
        )


    errors = []


    for year, rows in by_year.items():

        groups = Counter(

            summary.get(
                "groupe"
            )

            for scrutin in rows

            for summary
            in scrutin.get(
                "groupes_summary",
                []
            )

            if summary.get(
                "groupe"
            )
            not in {
                "",
                "Inconnu",
                None
            }
        )


        if len(
            groups
        ) < 5:

            errors.append(

                f"{year}: seulement "
                f"{len(groups)} groupes distincts "
                f"dans les scrutins"
            )


    if errors:

        print("")
        print(
            "==========================================="
        )

        print(
            "ERREUR DE VALIDATION DES SCRUTINS"
        )

        print(
            "==========================================="
        )


        for error in errors:

            print(
                " -",
                error
            )


        raise RuntimeError(

            "Les groupes de vote sont mal résolus. "
            "Le build est stoppé pour éviter "
            "de publier des données fausses."
        )


# ============================================================
# DEPUTES.JSON
# ============================================================

def build_deputes_file(
    current_deputies,
    scrutins
):

    votes_by_uid = defaultdict(
        int
    )


    votes_by_uid_year = defaultdict(
        lambda:
            defaultdict(
                int
            )
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


            # On compte uniquement
            # les députés actuellement en fonction
            if uid in current_deputies:

                votes_by_uid[
                    uid
                ] += 1


                votes_by_uid_year[
                    uid
                ][
                    year
                ] += 1


    deputes = []


    for uid, actor in current_deputies.items():

        group = normalize_group(
            actor.get(
                "groupe_actuel"
            )
        )


        if not group:

            group = (
                "Non inscrits"
            )


        deputes.append({

            "uid":
                uid,

            "nom":
                actor.get(
                    "nom",
                    ""
                ),

            "groupe":
                group,

            "groupe_actuel":
                group,

            "groupe_sigle":
                group_sigle(
                    group
                ),

            "departement":
                actor.get(
                    "departement",
                    ""
                ),

            "num_departement":
                actor.get(
                    "num_departement",
                    ""
                ),

            "num_circonscription":
                actor.get(
                    "num_circonscription",
                    ""
                ),

            "circonscription":
                actor.get(
                    "circonscription",
                    ""
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
                ),
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
            deputes,
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

        group = (
            deputy.get(
                "groupe_actuel"
            )
            or "Non inscrits"
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

            "sigle":
                group_sigle(
                    group
                ),

            "count":
                len(
                    members
                ),

            "pct":
                round(

                    len(
                        members
                    )
                    / total
                    * 100,

                    1

                )
                if total
                else 0,

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
                        ],
                }

                for member
                in members
            ],
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

        "is_valid":
            True,

        "groupes":
            groups,

        "source":
            (
                "Assemblée nationale — "
                "AMO40 députés actifs / "
                "mandats actifs / organes"
            ),
    }


    write_json(
        BASE_DIR
        / "composition.json",
        composition
    )


    print(
        "composition.json créé"
    )


    return composition


# ============================================================
# FICHIERS MENSUELS
# ============================================================

def write_month_files(
    scrutins
):

    ensure_dir(
        MONTHS_DIR
    )


    # Supprime les anciens mois,
    # pour éviter qu'un ancien JSON
    # reste présent par erreur.
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


        if month:

            grouped[
                month
            ].append(
                scrutin
            )


    month_index = []


    for month, items in grouped.items():

        items.sort(
            key=lambda row:
                row.get(
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
                    items,
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
                ),
        })


    month_index.sort(
        key=lambda row:
            row[
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

                    "sigle":
                        group_sigle(
                            group
                        ),

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
                            0,
                    },

                    "_themes":
                        defaultdict(
                            int
                        ),

                    "scrutins":
                        [],
                }


            entry = data[
                key
            ]


            entry[
                "scrutins_count"
            ] += 1


            for field in (
                "pour",
                "contre",
                "abstention",
                "non_votant"
            ):

                entry[
                    "votes"
                ][
                    field
                ] += summary.get(
                    field,
                    0
                )


            theme = clean(
                scrutin.get(
                    "theme"
                )
            )


            if not theme:

                theme = (
                    "Autres"
                )


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
                    ],
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

        for group
        in composition.get(
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
                    count,
            }

            for theme, count

            in sorted(

                entry[
                    "_themes"
                ].items(),

                key=lambda item: (

                    -item[
                        1
                    ],

                    item[
                        0
                    ]
                )
            )
        ]


        del entry[
            "_themes"
        ]


        entry[
            "scrutins"
        ].sort(
            key=lambda row:
                row[
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

        key=lambda row: (

            -row[
                "year"
            ],

            row[
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
                result,
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

        for deputy
        in deputes

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

        for deputy
        in deputes

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

        for scrutin
        in scrutins

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

            "sigle":
                (
                    group.get(
                        "sigle"
                    )
                    or
                    group_sigle(
                        group[
                            "groupe"
                        ]
                    )
                ),

            "count":
                group[
                    "count"
                ],
        }

        for group
        in composition.get(
            "groupes",
            []
        )
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

                "groupe_sigle":
                    deputy.get(
                        "groupe_sigle",
                        ""
                    ),

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
                    ],
            }

            for deputy
            in deputes
        ],

        "groupes":
            groups,

        "departements":
            departments,

        "circonscriptions":
            constituencies,

        "themes":
            themes,
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
# INDEX DES ANNÉES
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

        for scrutin
        in scrutins
    })


    result = {}


    for year in years:

        year_scrutins = [

            scrutin

            for scrutin
            in scrutins

            if int(
                scrutin[
                    "year"
                ]
            ) == year
        ]


        months = [

            month

            for month
            in month_index

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

            for scrutin
            in year_scrutins
        )


        groups = {

            normalize_group(
                summary.get(
                    "groupe"
                )
            )

            for scrutin
            in year_scrutins

            for summary
            in scrutin.get(
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
                    ),
            },

            "months":
                months,
        }


    return result


# ============================================================
# INDEX.JSON
# ============================================================

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
                    0,
            },

            "months":
                [],
        }
    )


    payload = {

        "version":
            "GROUP_FIRST_V2_AMO40",

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
                ],
        },
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
        " BUILD DATA — GROUP FIRST V2 / AMO40"
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


    # ========================================================
    # 1. DÉPUTÉS ACTUELS + GROUPES
    # ========================================================

    (
        current_deputies,
        organes,
        group_ref_to_label

    ) = load_current_deputies()


    # ========================================================
    # 2. SCRUTINS
    # ========================================================

    scrutins = load_scrutins(

        current_deputies,

        organes,

        group_ref_to_label
    )


    # ========================================================
    # 3. DEPUTES.JSON
    # ========================================================

    deputes = build_deputes_file(

        current_deputies,

        scrutins
    )


    # ========================================================
    # 4. COMPOSITION.JSON
    # ========================================================

    composition = build_composition_file(
        deputes
    )


    # ========================================================
    # 5. MOIS
    # ========================================================

    month_index = write_month_files(
        scrutins
    )


    # ========================================================
    # 6. GROUPES.JSON
    # ========================================================

    build_groupes_file(

        scrutins,

        composition
    )


    # ========================================================
    # 7. SEARCH.JSON
    # ========================================================

    build_search_file(

        deputes,

        composition,

        scrutins
    )


    # ========================================================
    # 8. INDEX.JSON
    # ========================================================

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

            for scrutin
            in scrutins
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


if __name__ == "__main__":

    main()
