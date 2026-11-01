"""Download the Natural Earth map layers the build scripts use into data/ (not committed: ~100 MB).

  python3 tools/get_data.py

Writes data/ne/adm1.geojson (provinces/states), data/ne/roads.geojson, data/ne/lakes.geojson and
data/roads_na.geojson (roads trimmed to North America, for the highs maps).
"""
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
FILES = {"adm1.geojson": "ne_10m_admin_1_states_provinces.geojson", "roads.geojson": "ne_10m_roads.geojson",
         "lakes.geojson": "ne_10m_lakes.geojson"}


def main():
    ne = os.path.join(ROOT, "data", "ne")
    os.makedirs(ne, exist_ok=True)
    for out, src in FILES.items():
        path = os.path.join(ne, out)
        if os.path.exists(path):
            print("have", out)
            continue
        print("downloading", src, "...")
        urllib.request.urlretrieve(BASE + src, path)
    with open(os.path.join(ne, "roads.geojson")) as f:
        roads = json.load(f)
    roads["features"] = [ft for ft in roads["features"] if ft["properties"].get("continent") == "North America"
                         or ft["properties"].get("sov_a3") in ("CAN", "USA")]
    with open(os.path.join(ROOT, "data", "roads_na.geojson"), "w") as f:
        json.dump(roads, f)
    print("data ready:", os.path.join(ROOT, "data"))


if __name__ == "__main__":
    main()
