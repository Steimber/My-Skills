"""Generate the two .cube LUTs of the "ember" look (normal + food variant) from the analytic definition in grade.py.

    python make_lut.py --out build/look                      # build/look/ember.cube + ember_food.cube (33^3)
    python make_lut.py --out build/look --name warm_v2 --param sat=1.8 --param vibrance=0.25 --food-param food=0.5

The LUT is a pure function of grade.PARAMS / grade.FOOD_PARAMS, so it is generated, not shipped (a 33^3 .cube is ~1 MB
of text). The engine calls the same code on first use; run this script to inspect or tweak the look in a grading tool
(any app that reads .cube files) or to pre-build the files. Give every parameter set its own --name.
"""
import argparse, ast, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import grade as G  # noqa: E402


def parse_kv(items):
    out = {}
    for it in items:
        k, v = (it.split("=", 1) + [""])[:2]
        if k not in G.PARAMS:
            raise SystemExit(f"unknown parameter '{k}'; known: {', '.join(G.PARAMS)}")
        out[k] = ast.literal_eval(v)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="./build/look", help="output dir (default: ./build/look)")
    ap.add_argument("--name", default="ember", help="file stem: <name>.cube and <name>_food.cube")
    ap.add_argument("--size", type=int, default=33, help="LUT edge size (default 33)")
    ap.add_argument("--param", action="append", default=[], metavar="KEY=VALUE", help="override a PARAMS entry (repeatable)")
    ap.add_argument("--food-param", action="append", default=[], metavar="KEY=VALUE", help="override a FOOD_PARAMS entry (repeatable)")
    a = ap.parse_args()
    G.PARAMS.update(parse_kv(a.param))
    G.FOOD_PARAMS.update(parse_kv(a.food_param))
    G.configure(a.out, a.name)
    for path, P in ((G.LUT_PATH, G.PARAMS), (G.LUT_FOOD_PATH, G.FOOD_PARAMS)):
        G.write_cube(path, a.size, P)
        print("wrote", path, f"({a.size}^3)")


if __name__ == "__main__":
    main()
