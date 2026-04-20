import json
import ssl
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

VOTES_URL = "https://data.assemblee-nationale.fr/static/openData/repository/17/loi/scrutins/Scrutins.json.zip"
OUTPUT_FILE = Path("data.json")

ssl_context = ssl.create_default_context()

def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=ssl_context) as response:
        return response.read()

def ensure_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]

def extract_json_from_zip(zip_bytes: bytes):
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name.lower().endswith(".json"):
                return json.loads(zf.read(name).decode("utf-8"))
    raise RuntimeError("Aucun fichier JSON trouvé dans l’archive.")

def extract_votants(node):
    out = []

    if isinstance(node, dict):
        if "votant" in node:
            votants = node["votant"]
            if isinstance(votants, list):
                out.extend(votants)
            else:
                out.append(votants)
        elif "acteurRef" in node:
            out.append(node)
        else:
            for value in node.values():
                out.extend(extract_votants(value))

    elif isinstance(node, list):
        for item in node:
            out.extend(extract_votants(item))

    return out

def guess_group_label(group_node):
    for key in ["libelle", "nom", "organeRef"]:
        value = group_node.get(key)
        if value:
            return str(value)
    return "Groupe inconnu"

def guess_name(votant):
    for key in ["acteurRef", "nom", "identite", "uid"]:
        value = votant.get(key)
        if value:
            return str(value)
    return "Nom inconnu"

def normalize_vote_label(label):
    mapping = {
        "pours": "Pour",
        "contres": "Contre",
        "abstentions": "Abstention",
        "nonVotants": "Non-votant",
    }
    return mapping.get(label, label)

def guess_theme(text: str) -> str:
    t = (text or "").lower()
    rules = [
        ("Budget / Finances", ["budget", "finance", "fiscal", "plf", "plfr", "plfss", "taxe", "impôt"]),
        ("Santé", ["santé", "hôpital", "médical", "soin"]),
        ("Éducation", ["éducation", "école", "université", "enseignement"]),
        ("Écologie / Énergie", ["climat", "écologie", "énergie", "environnement"]),
        ("Travail / Social", ["travail", "emploi", "retraite", "social", "salaires", "chômage"]),
        ("Justice / Sécurité", ["justice", "sécurité", "police", "prison", "pénal"]),
        ("Immigration / Outre-mer", ["immigration", "asile", "étranger", "outre-mer"]),
        ("Institutions / Procédure", ["motion", "censure", "constitution", "règlement", "procédure"]),
        ("Agriculture / Alimentation", ["agriculture", "aliment"]),
        ("Culture / Médias", ["culture", "audiovisuel", "presse", "patrimoine"]),
        ("Défense / International", ["défense", "armée", "europe", "international"]),
        ("Logement / Transports", ["logement", "transport", "mobilité", "ferroviaire"]),
    ]
    for theme, keywords in rules:
        if any(k in t for k in keywords):
            return theme
    return "Autres"

def main():
    zip_bytes = fetch_bytes(VOTES_URL)
    payload = extract_json_from_zip(zip_bytes)

    raw_scrutins = payload.get("scrutins", {}).get("scrutin", [])
    raw_scrutins = ensure_list(raw_scrutins)

    scrutins = []

    for scrutin in raw_scrutins:
        titre = scrutin.get("titre", "") or f"Scrutin {scrutin.get('numero', '')}"
        date = scrutin.get("dateScrutin", "")
        uid = scrutin.get("uid") or scrutin.get("numero") or titre
        theme = guess_theme(titre)

        votes = []

        ventilation = scrutin.get("ventilationVotes", {})
        organe = ventilation.get("organe", {})
        groupes = ensure_list(organe.get("groupes", {}).get("groupe"))

        for groupe in groupes:
            groupe_label = guess_group_label(groupe)
            decompte = groupe.get("vote", {}).get("decompteNominatif", {})

            for raw_key in ["pours", "contres", "abstentions", "nonVotants"]:
                bucket = decompte.get(raw_key)
                for votant in extract_votants(bucket):
                    votes.append({
                        "nom": guess_name(votant),
                        "groupe": groupe_label,
                        "vote": normalize_vote_label(raw_key)
                    })

        if votes:
            scrutins.append({
                "id": str(uid),
                "uid": str(uid),
                "titre": titre,
                "date": date,
                "theme": theme,
                "votes": votes
            })

    deputes = sorted({v["nom"] for s in scrutins for v in s["votes"]})
    groupes = sorted({v["groupe"] for s in scrutins for v in s["votes"]})

    data = {
        "meta": {
            "source_votes": "Assemblée nationale open data - Scrutins.json.zip",
            "nombre_scrutins": len(scrutins),
            "nombre_deputes_detectes": len(deputes),
            "nombre_groupes_detectes": len(groupes)
        },
        "scrutins": scrutins
    }

    OUTPUT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Scrutins : {len(scrutins)}")
    print(f"Députés détectés : {len(deputes)}")
    print(f"Groupes détectés : {len(groupes)}")

if __name__ == "__main__":
    main()
