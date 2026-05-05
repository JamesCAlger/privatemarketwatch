import json, os, csv
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CF_DIR = os.path.join(BASE, "data", "raw", "companyfacts")
UNIVERSE_PATH = os.path.join(BASE, "data", "output", "combined_universe.csv")
OUTPUT_PATH = os.path.join(BASE, "data", "output", "companyfacts_concept_catalog.md")
