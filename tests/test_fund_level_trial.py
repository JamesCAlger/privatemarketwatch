import pandas as pd

from scripts.fund_level_trial import nav_report


def test_nav_report_pairs_published_with_trial_and_checks_the_identity():
    published = pd.DataFrame([dict(cik="1838126", report_date="2026-03-31", nav_per_share="1000.0")])
    trial = pd.DataFrame([
        dict(cik="0001838126", report_date="2026-03-31", nav_per_share=24.79,
             net_assets=12434974000.0, shares_outstanding=501538142.0),
        dict(cik="0001838126", report_date="2025-12-31", nav_per_share=1000.0,
             net_assets=12436831000.0, shares_outstanding=493104572.0),
    ])
    out = nav_report(published, trial).set_index("report_date")
    assert out.loc["2026-03-31", "published_nav"] == 1000.0
    assert out.loc["2026-03-31", "nav_per_share"] == 24.79
    assert bool(out.loc["2026-03-31", "identity_ok"]) is True
    assert pd.isna(out.loc["2025-12-31", "published_nav"])
    assert bool(out.loc["2025-12-31", "identity_ok"]) is False
