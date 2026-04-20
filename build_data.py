import json
import requests
from pathlib import Path

OUTPUT_FILE = Path("data.json")

URL = "https://www.data.gouv.fr/api/1/datasets/donnees-parlementaires-francaises-votes-deputes-scrutins-civix/"

def guess_theme(text):
    t = text.lower()
    if "budget" in t or "finances" in t:
        return "Budget"
    if "santé" in t:
        return "Santé"
    if "immigration" in t:
        return "Immigration"
    if "écologie" in t or "climat" in t:
        return "Écologie"
    return "Autres"

def main():
    print("Téléchargement des métadonnées du jeu...")

    response = requests.get(URL, timeout=30)
    response.raise_for_status()
    dataset = response.json()

    resources = dataset.get("resources", [])
    if not resources:
        raise RuntimeError("Aucune ressource trouvée dans le jeu de données.")

    votes_resource = None
    for r in resources:
        title = (r.get("title") or "").lower()
        url = r.get("url") or ""
        if "vote" in title and url.endswith(".csv"):
            votes_resource = url
            break

    if not votes_resource:
        raise RuntimeError("Impossible de trouver le fichier CSV des votes.")

    print("Téléchargement du CSV des votes...")
    csv_response = requests.get(votes_resource, timeout=60)
    csv_response.raise_for_status()

    lines = csv_response.text.splitlines()
    if not lines:
        raise RuntimeError("Le CSV est vide.")

    header = [h.strip() for h in lines[0].split(",")]
    rows = [line.split(",") for line in lines[1:] if line.strip()]

    def idx(name):
        if name not in header:
            raise RuntimeError(f"Colonne manquante : {name}. En-têtes trouvés : {header}")
        return header.index(name)

    i_uid = idx("scrutin_uid")
    i_numero = idx("numero_scrutin")
    i_date = idx("date_scrutin")
    i_prenom = idx("prenom")
    i_nom = idx("nom")
    i_groupe = idx("groupe")
    i_position = idx("position")

    scrutins_map = {}

    for row in rows:
        if len(row) <= max(i_uid, i_numero, i_date, i_prenom, i_nom, i_groupe, i_position):
            continue

        scrutin_uid = row[i_uid].strip()
        numero = row[i_numero].strip()
        date = row[i_date].strip()
        prenom = row[i_prenom].strip()
        nom = row[i_nom].strip()
        groupe = row[i_groupe].strip()
        position = row[i_position].strip()

        if not scrutin_uid:
            continue

        nom_complet = f"{prenom} {nom}".strip()

        if scrutin_uid not in scrutins_map:
            scrutins_map[scrutin_uid] = {
                "id": scrutin_uid,
                "uid": scrutin_uid,
                "titre": f"Scrutin n°{numero}" if numero else f"Scrutin {scrutin_uid}",
                "date": date,
                "theme": guess_theme(f"Scrutin n°{numero}"),
                "votes": []
            }

        scrutins_map[scrutin_uid]["votes"].append({
            "nom": nom_complet or "Inconnu",
            "groupe": groupe or "Inconnu",
            "vote": position or "Inconnu"
        })

    scrutins = list(scrutins_map.values())
    scrutins.sort(key=lambda s: s.get("date", ""), reverse=True)

    deputes = sorted({v["nom"] for s in scrutins for v in s["votes"]})
    groupes = sorted({v["groupe"] for s in scrutins for v in s["votes"]})

    output = {
        "meta": {
            "source_votes": "data.gouv.fr / CIVIX",
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
