import pathlib, base64, sys
data = sys.stdin.buffer.read()
pathlib.Path("scripts/position_id_defect_analysis.py").write_bytes(base64.b64decode(data))
print("Written", len(base64.b64decode(data)), "bytes")
