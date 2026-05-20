import requests
import json
import time

print("1. Récupération des communes...")

communes = requests.get(
    "https://geo.api.gouv.fr/communes?fields=nom,code,codesPostaux,departement&format=json"
).json()

print(f"{len(communes)} communes récupérées")

# ⚠️ fichier à télécharger manuellement depuis data.gouv
with open("circos_officiel.json", "r", encoding="utf-8") as f:
    circos = json.load(f)

print("2. Mapping communes → circo")

result = {}

for c in communes:
    nom = c["nom"]
    cp_list = c.get("codesPostaux", [])
    departement = c.get("departement", {}).get("nom", "")

    if not cp_list:
        continue

    # 🔥 recherche circo exacte
    circo = ""

    for row in circos:
        if row["nom_commune"].lower() == nom.lower():
            circo = row["circonscription"]
            break

    for cp in cp_list:
        result[str(cp)] = {
            "departement": departement,
            "circo": circo
        }

# sauvegarde
with open("data/circonscriptions.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("🔥 Fichier EXACT généré !")
