import csv
import io
import json
import re
from pathlib import Path

import requests

OUTPUT_FILE = Path("data.json")
CIVIX_DATASET_API = "https://www.data.gouv.fr/api/1/datasets/donnees-parlementaires-francaises-votes-deputes-scrutins-civix/"
DEPUTES_ACTIFS_API = "https://www.data.gouv.fr/api/1/datasets/deputes-actifs-de-lassemblee-nationale-informations-et-statistiques/"

def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())

def find_column(headers, candidates):
    normalized = {h: normalize_key(h) for h in headers}

    for candidate in candidates:
        c = normalize_key(candidate)
        for original, norm in normalized.items():
            if norm == c:
                return original

    for candidate in candidates:
        c = normalize_key(candidate)
        for original, norm in normalized.items():
            if c in norm:
                return original

    return None

def download_json(url: str):
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.json()

def download_csv(url: str):
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    text = response.text

    sample = text[:5000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t")
        delimiter = dialect.delimiter
    except Exception:
        delimiter = ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    headers = reader.fieldnames or []
    return rows, headers

def pick_resource(resources, include_keywords):
    for resource in resources:
        title = (resource.get("title") or "").lower()
        url = resource.get("url") or ""
        if not url.lower().endswith(".csv"):
            continue
        if all(keyword in title for keyword in include_keywords):
            return resource

    for resource in resources:
        title = (resource.get("title") or "").lower()
        url = resource.get("url") or ""
        if not url.lower().endswith(".csv"):
            continue
        if any(keyword in title for keyword in include_keywords):
            return resource

    return None

def safe_value(row, col):
    if not col:
        return ""
    return (row.get(col) or "").strip()

def guess_theme(text: str) -> str:
    t = (text or "").lower()

    rules = [
        ("Budget / Finances", ["budget", "finance", "fiscal", "plf", "plfr", "plfss", "impôt", "taxe"]),
        ("Santé", ["santé", "hôpital", "médical", "soin"]),
        ("Éducation", ["éducation", "école", "université", "enseignement"]),
        ("Écologie / Énergie", ["écologie", "climat", "énergie", "environnement"]),
        ("Travail / Social", ["travail", "emploi", "retraite", "social", "salaires", "chômage"]),
        ("Justice / Sécurité", ["justice", "sécurité", "police", "prison", "pénal"]),
        ("Immigration", ["immigration", "asile", "étranger"]),
        ("Institutions", ["motion", "censure", "constitution", "règlement", "procédure"]),
        ("Agriculture", ["agriculture", "aliment"]),
        ("Culture / Médias", ["culture", "audiovisuel", "presse", "patrimoine"]),
        ("Défense / International", ["défense", "armée", "europe", "international"]),
        ("Logement / Transports", ["logement", "transport", "mobilité", "ferroviaire"]),
    ]

    for theme, keywords in rules:
        if any(keyword in t for keyword in keywords):
            return theme

    return "Autres"

def build_origin(row, cols):
    pieces = []

    for key in [
        "circonscription",
        "nom_circonscription",
        "numero_circonscription",
        "departement",
        "nom_departement",
        "region",
    ]:
        value = safe_value(row, cols.get(key))
        if value:
            pieces.append(value)

    seen = []
    for piece in pieces:
        if piece not in seen:
            seen.append(piece)

    return " · ".join(seen)

def main():
    print("Téléchargement des métadonnées CIVIX…")
    civix_dataset = download_json(CIVIX_DATASET_API)
    civix_resources = civix_dataset.get("resources", [])

    votes_resource = pick_resource(civix_resources, ["vote"])
    scrutins_resource = pick_resource(civix_resources, ["scrutin"])
    deputes_resource = pick_resource(civix_resources, ["deput"])

    if not votes_resource:
        raise RuntimeError("Impossible de trouver le CSV des votes dans le jeu CIVIX.")
    if not scrutins_resource:
        raise RuntimeError("Impossible de trouver le CSV des scrutins dans le jeu CIVIX.")

    print("Téléchargement du CSV des votes…")
    vote_rows, vote_headers = download_csv(votes_resource["url"])

    print("Téléchargement du CSV des scrutins…")
    scrutin_rows, scrutin_headers = download_csv(scrutins_resource["url"])

    deputes_rows = []
    deputes_headers = []

    if deputes_resource:
        print("Téléchargement du CSV des députés depuis CIVIX…")
        deputes_rows, deputes_headers = download_csv(deputes_resource["url"])
    else:
        try:
            print("Tentative de récupération du jeu 'députés actifs'…")
            deputes_dataset = download_json(DEPUTES_ACTIFS_API)
            deputes_resources = deputes_dataset.get("resources", [])
            deputes_csv = pick_resource(deputes_resources, ["csv"]) or pick_resource(deputes_resources, ["deput"])
            if deputes_csv:
                deputes_rows, deputes_headers = download_csv(deputes_csv["url"])
        except Exception:
            deputes_rows = []
            deputes_headers = []

    vote_cols = {
        "scrutin_uid": find_column(vote_headers, ["scrutin_uid", "scrutinid", "id_scrutin", "scrutin_id"]),
        "numero_scrutin": find_column(vote_headers, ["numero_scrutin", "scrutin_numero", "numero"]),
        "date_scrutin": find_column(vote_headers, ["date_scrutin", "scrutin_date", "date"]),
        "acteur_uid": find_column(vote_headers, ["acteur_uid", "depute_uid", "uid_acteur"]),
        "prenom": find_column(vote_headers, ["prenom"]),
        "nom": find_column(vote_headers, ["nom"]),
        "groupe": find_column(vote_headers, ["groupe", "groupe_sigle", "groupe_nom"]),
        "position": find_column(vote_headers, ["position", "vote_position", "vote"]),
    }

    scrutin_cols = {
        "scrutin_uid": find_column(scrutin_headers, ["scrutin_uid", "id_scrutin", "scrutin_id"]),
        "numero_scrutin": find_column(scrutin_headers, ["numero_scrutin", "scrutin_numero", "numero"]),
        "date_scrutin": find_column(scrutin_headers, ["date_scrutin", "scrutin_date", "date"]),
        "titre": find_column(scrutin_headers, ["titre", "intitule", "objet", "libelle"]),
        "description": find_column(scrutin_headers, ["description", "resume", "detail", "objet_long"]),
        "type": find_column(scrutin_headers, ["type_scrutin", "type"]),
    }

    deputes_cols = {
        "acteur_uid": find_column(deputes_headers, ["acteur_uid", "depute_uid", "uid_acteur", "uid"]),
        "prenom": find_column(deputes_headers, ["prenom"]),
        "nom": find_column(deputes_headers, ["nom"]),
        "circonscription": find_column(deputes_headers, ["circonscription", "nom_circonscription", "numero_circonscription"]),
        "departement": find_column(deputes_headers, ["departement", "nom_departement"]),
        "region": find_column(deputes_headers, ["region"]),
    }

    required_vote_cols = ["scrutin_uid", "numero_scrutin", "date_scrutin", "prenom", "nom", "groupe", "position"]
    missing = [key for key in required_vote_cols if not vote_cols[key]]
    if missing:
        raise RuntimeError(f"Colonnes manquantes dans le CSV votes : {missing}. En-têtes trouvés : {vote_headers}")

    deputes_by_uid = {}
    deputes_by_name = {}

    for row in deputes_rows:
        prenom = safe_value(row, deputes_cols["prenom"])
        nom = safe_value(row, deputes_cols["nom"])
        nom_complet = f"{prenom} {nom}".strip()
        uid = safe_value(row, deputes_cols["acteur_uid"])
        origine = build_origin(row, deputes_cols)

        if uid:
            deputes_by_uid[uid] = {
                "nom": nom_complet,
                "origine": origine,
            }

        if nom_complet:
            deputes_by_name[nom_complet.lower()] = {
                "nom": nom_complet,
                "origine": origine,
            }

    scrutins_meta = {}

    for row in scrutin_rows:
        scrutin_uid = safe_value(row, scrutin_cols["scrutin_uid"])
        numero = safe_value(row, scrutin_cols["numero_scrutin"])
        date = safe_value(row, scrutin_cols["date_scrutin"])
        titre = safe_value(row, scrutin_cols["titre"])
        description = safe_value(row, scrutin_cols["description"])
        type_scrutin = safe_value(row, scrutin_cols["type"])

        key = scrutin_uid or numero
        if not key:
            continue

        full_text = " ".join([titre, description, type_scrutin]).strip()

        scrutins_meta[key] = {
            "numero": numero,
            "date": date,
            "titre": titre or (f"Scrutin n°{numero}" if numero else f"Scrutin {key}"),
            "description": description,
            "theme": guess_theme(full_text),
        }

    scrutins_map = {}

    for row in vote_rows:
        scrutin_uid = safe_value(row, vote_cols["scrutin_uid"])
        numero = safe_value(row, vote_cols["numero_scrutin"])
        date = safe_value(row, vote_cols["date_scrutin"])
        acteur_uid = safe_value(row, vote_cols["acteur_uid"])
        prenom = safe_value(row, vote_cols["prenom"])
        nom = safe_value(row, vote_cols["nom"])
        groupe = safe_value(row, vote_cols["groupe"])
        position = safe_value(row, vote_cols["position"])

        if not scrutin_uid:
            continue

        nom_complet = f"{prenom} {nom}".strip()

        depute_info = deputes_by_uid.get(acteur_uid) or deputes_by_name.get(nom_complet.lower()) or {}
        origine = depute_info.get("origine", "")

        meta = scrutins_meta.get(scrutin_uid) or scrutins_meta.get(numero) or {}
        titre = meta.get("titre") or (f"Scrutin n°{numero}" if numero else f"Scrutin {scrutin_uid}")
        description = meta.get("description", "")
        theme = meta.get("theme") or guess_theme(titre)

        if scrutin_uid not in scrutins_map:
            scrutins_map[scrutin_uid] = {
                "id": scrutin_uid,
                "uid": scrutin_uid,
                "titre": titre,
                "description": description,
                "date": meta.get("date") or date,
                "theme": theme,
                "votes": []
            }

        scrutins_map[scrutin_uid]["votes"].append({
            "nom": nom_complet or "Inconnu",
            "groupe": groupe or "Inconnu",
            "vote": position or "Inconnu",
            "origine": origine
        })

    scrutins = list(scrutins_map.values())
    scrutins.sort(key=lambda s: s.get("date", ""), reverse=True)

    deputes = sorted({v["nom"] for s in scrutins for v in s["votes"]})
    groupes = sorted({v["groupe"] for s in scrutins for v in s["votes"]})

    output = {
        "meta": {
            "source_votes": "CIVIX / données publiques de l’Assemblée nationale",
            "nombre_scrutins": len(scrutins),
            "nombre_deputes_detectes": len(deputes),
            "nombre_groupes_detectes": len(groupes)
        },
        "scrutins": scrutins
    }

    OUTPUT_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("OK")
    print(f"Scrutins : {len(scrutins)}")
    print(f"Députés : {len(deputes)}")
    print(f"Groupes : {len(groupes)}")

if __name__ == "__main__":
    main()
