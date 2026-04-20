import csv
import io
import json
import re
from pathlib import Path

import requests

OUTPUT_FILE = Path("data.json")
CIVIX_DATASET_API = "https://www.data.gouv.fr/api/1/datasets/donnees-parlementaires-francaises-votes-deputes-scrutins-civix/"

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

def decode_csv_content(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")

def download_csv(url: str):
    response = requests.get(url, timeout=120)
    response.raise_for_status()

    text = decode_csv_content(response.content)

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

def pick_best_resource(resources, kind):
    candidates = []

    for resource in resources:
        title = (resource.get("title") or "").lower()
        url = (resource.get("url") or "").lower()

        if not url.endswith(".csv"):
            continue

        score = 0

        if kind == "votes":
            if "vote" in title:
                score += 10
            if "votes" in title:
                score += 10
            if "scrutin" not in title:
                score += 2

        elif kind == "scrutins":
            if "scrutin" in title:
                score += 10
            if "scrutins" in title:
                score += 10
            if "vote" not in title:
                score += 2

        elif kind == "deputes":
            if "deput" in title:
                score += 10
            if "actif" in title:
                score += 3

        if "csv" in title:
            score += 1

        if score > 0:
            candidates.append((score, resource))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

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
        ("Culture / Médias", ["culture", "audiovisuel", "presse", "patrimoine", "culturels"]),
        ("Défense / International", ["défense", "armée", "europe", "international"]),
        ("Logement / Transports", ["logement", "transport", "mobilité", "ferroviaire"]),
    ]

    for theme, keywords in rules:
        if any(keyword in t for keyword in keywords):
            return theme

    return "Autres"

def main():
    print("Téléchargement des métadonnées CIVIX…")
    dataset = download_json(CIVIX_DATASET_API)
    resources = dataset.get("resources", [])

    votes_resource = pick_best_resource(resources, "votes")
    scrutins_resource = pick_best_resource(resources, "scrutins")
    deputes_resource = pick_best_resource(resources, "deputes")

    if not votes_resource:
        raise RuntimeError("Impossible de trouver le CSV des votes.")
    if not scrutins_resource:
        raise RuntimeError("Impossible de trouver le CSV des scrutins.")

    print("Fichier votes choisi :", votes_resource.get("title"))
    print("Fichier scrutins choisi :", scrutins_resource.get("title"))
    if deputes_resource:
        print("Fichier députés choisi :", deputes_resource.get("title"))

    vote_rows, vote_headers = download_csv(votes_resource["url"])
    scrutin_rows, scrutin_headers = download_csv(scrutins_resource["url"])

    deputes_rows = []
    deputes_headers = []
    if deputes_resource:
        deputes_rows, deputes_headers = download_csv(deputes_resource["url"])

    vote_cols = {
        "scrutin_uid": find_column(vote_headers, ["scrutin_uid", "scrutin_id", "id_scrutin"]),
        "numero_scrutin": find_column(vote_headers, ["numero_scrutin", "scrutin_numero", "numero"]),
        "date_scrutin": find_column(vote_headers, ["date_scrutin", "scrutin_date", "date"]),
        "acteur_uid": find_column(vote_headers, ["acteur_uid", "depute_uid", "uid_acteur"]),
        "prenom": find_column(vote_headers, ["prenom"]),
        "nom": find_column(vote_headers, ["nom"]),
        "groupe": find_column(vote_headers, ["groupe", "groupe_sigle", "groupe_nom"]),
        "position": find_column(vote_headers, ["position", "vote_position", "vote"]),
    }

    scrutin_cols = {
        "scrutin_uid": find_column(scrutin_headers, ["scrutin_uid", "scrutin_id", "id_scrutin"]),
        "numero_scrutin": find_column(scrutin_headers, ["numero_scrutin", "scrutin_numero", "numero"]),
        "date_scrutin": find_column(scrutin_headers, ["date_scrutin", "scrutin_date", "date"]),
        "titre": find_column(scrutin_headers, ["titre", "intitule", "objet", "libelle"]),
        "description": find_column(scrutin_headers, ["description", "resume", "detail", "objet_long"]),
    }

    deputes_cols = {
        "acteur_uid": find_column(deputes_headers, ["acteur_uid", "depute_uid", "uid_acteur", "uid"]),
        "prenom": find_column(deputes_headers, ["prenom"]),
        "nom": find_column(deputes_headers, ["nom"]),
        "circonscription": find_column(deputes_headers, ["circonscription", "nom_circonscription"]),
        "departement": find_column(deputes_headers, ["departement", "nom_departement"]),
        "region": find_column(deputes_headers, ["region"]),
    }

    scrutins_meta = {}

    for row in scrutin_rows:
        scrutin_uid = safe_value(row, scrutin_cols["scrutin_uid"])
        numero = safe_value(row, scrutin_cols["numero_scrutin"])
        date = safe_value(row, scrutin_cols["date_scrutin"])
        titre = safe_value(row, scrutin_cols["titre"])
        description = safe_value(row, scrutin_cols["description"])

        key = scrutin_uid or numero
        if not key:
            continue

        full_text = f"{titre} {description}".strip()

        scrutins_meta[key] = {
            "numero": numero,
            "date": date,
            "titre": titre or (f"Scrutin n°{numero}" if numero else f"Scrutin {key}"),
            "description": description,
            "theme": guess_theme(full_text),
        }

    deputes_meta = {}

    for row in deputes_rows:
        uid = safe_value(row, deputes_cols["acteur_uid"])
        prenom = safe_value(row, deputes_cols["prenom"])
        nom = safe_value(row, deputes_cols["nom"])
        circo = safe_value(row, deputes_cols["circonscription"])
        dep = safe_value(row, deputes_cols["departement"])
        reg = safe_value(row, deputes_cols["region"])

        origine_parts = [x for x in [circo, dep, reg] if x]
        origine = " · ".join(dict.fromkeys(origine_parts))
        nom_complet = f"{prenom} {nom}".strip()

        if uid:
            deputes_meta[uid] = {
                "nom": nom_complet,
                "origine": origine
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

        key = scrutin_uid or numero
        if not key:
            continue

        nom_complet = f"{prenom} {nom}".strip()
        depute_info = deputes_meta.get(acteur_uid, {})
        origine = depute_info.get("origine", "")

        meta = scrutins_meta.get(key, {})
        titre = meta.get("titre") or (f"Scrutin n°{numero}" if numero else f"Scrutin {key}")
        description = meta.get("description", "")
        theme = meta.get("theme") or guess_theme(titre)

        if key not in scrutins_map:
            scrutins_map[key] = {
                "id": key,
                "uid": key,
                "titre": titre,
                "description": description,
                "date": meta.get("date") or date,
                "theme": theme,
                "votes": []
            }

        scrutins_map[key]["votes"].append({
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
