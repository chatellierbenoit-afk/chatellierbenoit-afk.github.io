from pathlib import Path
from urllib.parse import urlencode, quote
from xml.sax.saxutils import escape
import json


BASE_URL = "https://quevotemondepute.fr"

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "current"

SITEMAP_PATH = ROOT / "sitemap.xml"
ROBOTS_PATH = ROOT / "robots.txt"


def load_json(path):
    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except Exception as exc:
        print(
            f"⚠️ Impossible de lire {path}: {exc}"
        )
        return None


def make_url(path="", params=None):

    url = (
        BASE_URL.rstrip("/")
        +
        "/"
    )

    if path:
        url += path.lstrip("/")

    if params:

        clean_params = {
            key: value
            for key, value in params.items()
            if value is not None
            and str(value) != ""
        }

        if clean_params:

            query = urlencode(
                clean_params,
                doseq=True,
                quote_via=quote
            )

            url += "?" + query

    return url


urls = []
seen = set()
categories = {}


def add_url(url, category):

    if not url:
        return

    if url in seen:
        return

    seen.add(url)

    urls.append(url)

    categories[category] = (
        categories.get(category, 0)
        +
        1
    )


# ============================================================
# ACCUEIL
# ============================================================

add_url(
    make_url(),
    "Accueil"
)


# ============================================================
# INDEX / ANNÉES
# ============================================================

index_path = (
    DATA_DIR
    /
    "index.json"
)

index_data = (
    load_json(index_path)
    or
    {}
)


available_years = (
    index_data.get(
        "available_years"
    )
)


if not available_years:

    available_years = list(
        (
            index_data.get(
                "years"
            )
            or
            {}
        ).keys()
    )


available_years = sorted(
    {
        str(year)
        for year in available_years
    },
    reverse=True
)


for year in available_years:

    add_url(
        make_url(
            "",
            {
                "year": year
            }
        ),
        "Accueil année"
    )


# ============================================================
# GROUPES
# ============================================================

groupes_path = (
    DATA_DIR
    /
    "groupes.json"
)

groupes_payload = (
    load_json(
        groupes_path
    )
)


if isinstance(
    groupes_payload,
    dict
):

    groupes = (
        groupes_payload.get(
            "groupes"
        )
        or
        []
    )

elif isinstance(
    groupes_payload,
    list
):

    groupes = (
        groupes_payload
    )

else:

    groupes = []


for group in groupes:

    if not isinstance(
        group,
        dict
    ):
        continue

    name = (
        group.get("groupe")
        or
        group.get("nom")
        or
        ""
    )

    year = (
        group.get("year")
        or
        group.get("annee")
        or
        ""
    )

    if not name:
        continue

    params = {
        "name": name
    }

    if year:
        params["year"] = year

    add_url(
        make_url(
            "groupe.html",
            params
        ),
        "Groupe"
    )


# ============================================================
# DÉPUTÉS
# ============================================================

deputes_votes_dir = (
    DATA_DIR
    /
    "deputes_votes"
)


deputy_count = 0


if deputes_votes_dir.exists():

    for year_dir in sorted(
        deputes_votes_dir.iterdir()
    ):

        if not year_dir.is_dir():
            continue

        year = year_dir.name

        for file_path in sorted(
            year_dir.glob(
                "*.json"
            )
        ):

            uid = (
                file_path.stem
            )

            if not uid:
                continue

            add_url(
                make_url(
                    "depute.html",
                    {
                        "uid": uid,
                        "year": year
                    }
                ),
                "Député"
            )

            deputy_count += 1


# ============================================================
# FALLBACK DÉPUTÉS
# ============================================================

if deputy_count == 0:

    deputes_payload = (
        load_json(
            DATA_DIR
            /
            "deputes.json"
        )
    )


    if isinstance(
        deputes_payload,
        dict
    ):

        deputes = (
            deputes_payload.get(
                "deputes"
            )
            or
            []
        )

    elif isinstance(
        deputes_payload,
        list
    ):

        deputes = (
            deputes_payload
        )

    else:

        deputes = []


    default_year = str(
        index_data.get(
            "default_year"
        )
        or
        (
            available_years[0]
            if available_years
            else
            ""
        )
    )


    for deputy in deputes:

        if not isinstance(
            deputy,
            dict
        ):
            continue

        uid = (
            deputy.get("uid")
            or
            deputy.get("id")
            or
            ""
        )

        if not uid:
            continue

        params = {
            "uid": uid
        }

        if default_year:
            params["year"] = default_year

        add_url(
            make_url(
                "depute.html",
                params
            ),
            "Député"
        )


# ============================================================
# SCRUTINS
# ============================================================

months_dir = (
    DATA_DIR
    /
    "months"
)


if months_dir.exists():

    for month_file in sorted(
        months_dir.glob(
            "*.json"
        )
    ):

        payload = (
            load_json(
                month_file
            )
        )

        if not payload:
            continue


        if isinstance(
            payload,
            dict
        ):

            scrutins = (
                payload.get(
                    "scrutins"
                )
                or
                []
            )

        elif isinstance(
            payload,
            list
        ):

            scrutins = (
                payload
            )

        else:

            scrutins = []


        for scrutin in scrutins:

            if not isinstance(
                scrutin,
                dict
            ):
                continue


            uid = (
                scrutin.get("uid")
                or
                scrutin.get("id")
                or
                ""
            )


            if not uid:
                continue


            year = (
                scrutin.get("year")
                or
                ""
            )


            if not year:

                date = str(
                    scrutin.get(
                        "date"
                    )
                    or
                    ""
                )

                if len(date) >= 4:
                    year = date[:4]


            if not year:

                filename = (
                    month_file.stem
                )

                if len(filename) >= 4:
                    year = filename[:4]


            params = {
                "uid": uid
            }


            if year:
                params["year"] = year


            add_url(
                make_url(
                    "scrutin.html",
                    params
                ),
                "Scrutin"
            )


# ============================================================
# SITEMAP XML
# ============================================================

xml = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
]


for url in urls:

    xml.append(
        "  <url>"
    )

    xml.append(
        "    <loc>"
        +
        escape(url)
        +
        "</loc>"
    )

    xml.append(
        "  </url>"
    )


xml.append(
    "</urlset>"
)


SITEMAP_PATH.write_text(
    "\n".join(xml)
    +
    "\n",
    encoding="utf-8"
)


# ============================================================
# ROBOTS.TXT
# ============================================================

ROBOTS_PATH.write_text(
    """User-agent: *
Allow: /

Sitemap: https://quevotemondepute.fr/sitemap.xml
""",
    encoding="utf-8"
)


# ============================================================
# RAPPORT
# ============================================================

print()
print(
    "======================================================"
)

print(
    " SITEMAP — QUE VOTE MON DÉPUTÉ ?"
)

print(
    "======================================================"
)

print()


for category, count in sorted(
    categories.items()
):

    print(
        f"{category}: {count}"
    )


print()

print(
    "TOTAL URLS:",
    len(urls)
)

print()

print(
    "sitemap.xml créé"
)

print(
    "robots.txt créé"
)
