import requests
import json
import time

print("🔄 Récupération des communes...")

# API officielle
communes = requests.get(
    "https://geo.api.gouv.fr/communes?fields=nom,code,codesPostaux,departement&format=json"
).json()

print(f"{len(communes)} communes récupérées")

# charger tes députés
with open("data/current/deputes.json", "r", encoding="utf-8") as f:
    deputes = json.load(f)["deputes"]

# index députés par département
dep_to_circo = {}

for d in deputes:
    dep = d.get("departement", "").strip()
    circo = d.get("circonscription", "").strip()

    if dep and circo:
        dep_to_circo.setdefault(dep, set()).add(circo)

# construction mapping
mapping = {}

for c in communes:
    dep = c.get("departement", {}).get("nom", "")
    cps = c.get("codesPostaux", [])

    if dep not in dep_to_circo:
        continue

    for cp in cps:
        mapping.setdefault(cp, [])

        for circo in dep_to_circo[dep]:
            entry = {
                "departement": dep,
                "circonscription": circo
            }

            if entry not in mapping[cp]:
                mapping[cp].append(entry)

# sauvegarde
with open("data/current/circonscriptions.json", "w", encoding="utf-8") as f:
    json.dump(mapping, f, ensure_ascii=False, indent=2)

print("✅ circonscriptions.json généré")
