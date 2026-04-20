import json
import requests
from pathlib import Path

OUTPUT_FILE = Path("data.json")

URL = "https://www.data.gouv.fr/api/1/datasets/donnees-parlementaires-francaises-votes-deputes-scrutins-civix/"

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

    header = lines[0].split(",")
    rows = [line.split(",") for line in lines[1:] if line.strip()]

    def idx(name_candidates):
        for candidate in name_candidates:
            if candidate in header:
                return header.index(candidate)
        return None

    i_scrutin = idx(["scrutin_numero", "scrutin_id", "id_scrutin"])
    i_titre = idx(["scrutin_titre", "titre", "scrutin_objet"])
    i_date = idx(["scrutin_date", "date_scrutin", "date"])
    i_nom = idx(["depute_nom", "nom", "nom_depute"])
    i_groupe = idx(["groupe_sigle", "groupe", "groupe_nom"])
    i_vote = idx(["vote_position", "position_vote", "vote"])

    if None in [i_scrutin, i_titre, i_date, i_nom, i_groupe, i_vote]:
        raise RuntimeError(f"Colonnes introuvables. En-têtes trouvés : {header}")

    scrutins_map = {}

    for row in rows[:5000]:
        if len(row) <= max(i_scrutin, i_titre, i_date, i_nom, i_groupe, i_vote):
            continue

        scrutin_id = row[i_scrutin].strip()
        titre = row[i_titre].strip()
        date = row[i_date].strip()
        nom = row[i_nom].strip()
        groupe = row[i_groupe].strip()
        vote = row[i_vote].strip()

        if not scrutin_id:
            continue

        if scrutin_id not in scrutins_map:
            scrutins_map[scrutin_id] = {
                "id": scrutin_id,
                "uid": scrutin_id,
                "titre": titre or f"Scrutin {scrutin_id}",
                "date": date,
                "theme": "Politique",
                "votes": []
            }

        scrutins_map[scrutin_id]["votes"].append({
            "nom": nom or "Inconnu",
            "groupe": groupe or "Inconnu",
            "vote": vote or "Inconnu"
        })

    scrutins = list(scrutins_map.values())

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
