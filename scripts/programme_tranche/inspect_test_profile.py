"""Print a bounded subset of the saved diagnostic profile."""
from pathlib import Path
import pstats

ROOT = Path(__file__).resolve().parents[2]


def main():
    profile = ROOT/'scratch/2026-09-10_verification_investigation/reproduce-v1/bundle/profile.prof'
    assert profile.stat().st_size < 10 * 1024**2
    stats = pstats.Stats(str(profile))
    selected = [(key, value) for key, value in stats.stats.items()
                if ('staging_bdc.py' in key[0] or 'execute' in key[2] or 'connect' in key[2])]
    for key, value in sorted(selected, key=lambda item:item[1][3], reverse=True)[:35]:
        print(str(key)+' calls='+str(value[1])+' own='+str(round(value[2],3))+' cumulative='+str(round(value[3],3)), flush=True)


if __name__ == '__main__':
    main()
