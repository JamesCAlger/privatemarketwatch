# Validation Rule Catalog

| Namespace | Rule ID | Category | Title | Severity | Promoted | Dependencies | Required tables | Affected outputs | Trend | Output artifact |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RI | RI01 | RI | Holdings CIKs exist in combined universe | FAIL | true |  | holdings, combined_universe | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| RI | RI02 | RI | Position matches CIKs exist in holdings | FAIL | true |  | position_matches, holdings | private_markets_holdings, frontend_fund_detail, position_returns, frontend_index, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| RI | RI03 | RI | Cross-level financial CIK-quarters exist in fund financials | FAIL | true |  | fund_financials_cross_level, fund_financials | data_quality_dashboard | STABLE | validation_rules_detail.csv |
| RI | RI04 | RI | Index return quarters fall within holdings quarter range | FAIL | true |  | index_returns, holdings | private_markets_holdings, frontend_fund_detail, index_returns, frontend_index, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| RI | RI05 | RI | Fee uplift CIKs exist in holdings | FAIL | true |  | fee_uplift, holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| RI | RI06 | RI | Index-used BDC income CIKs exist in BDC holdings | FAIL | true |  | bdc_fund_income, bdc_holdings, fee_uplift | data_quality_dashboard | STABLE | validation_rules_detail.csv |
| PC | PC01 | PC | Direct lending missing usable income rates | WARN | false |  | position_returns | position_returns, frontend_index, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| PC | PC02 | PC | Cost-weighted index return reconciles | FAIL | true | RI04 | position_returns, index_returns | position_returns, frontend_index, index_returns, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| PC | PC03 | PC | Index aggregate fields reconcile | FAIL | true | RI04 | position_returns, index_returns | position_returns, frontend_index, index_returns, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| PC | PC04 | PC | Sparse high-FV CIK-quarter holdings | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| PC | PC05 | PC | Cross-source duplicate holding candidate | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| PC | PC06 | PC | Within-source duplicate holding candidate | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| PC | PC07 | PC | CIK-quarter pct-of-net-assets sum high | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| PC | PC08 | PC | Loaded table schema and numeric casts | WARN | false | RI04 | holdings, position_returns, index_returns | private_markets_holdings, frontend_fund_detail, position_returns, frontend_index, index_returns, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| PC | PC09 | PC | Multi-quarter holdings missing position_id | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| PC | PC10 | PC | Fee uplift exceeds 5 percentage points | WARN | false |  | fee_uplift | data_quality_dashboard | STABLE | validation_rules_detail.csv |
| PC | PC11 | PC | Excluded N-PORT CIK in unified holdings | FAIL | true |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| PC | PC12 | PC | Consumer-lending CIK in position returns | FAIL | true |  | position_returns | position_returns, frontend_index, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| IDX | IDX01 | IDX | Index return absolute value exceeds 25% | WARN | true |  | index_returns | index_returns, frontend_index, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| IDX | IDX02 | IDX | Index level is non-positive | WARN | true |  | index_returns | index_returns, frontend_index, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| IDX | IDX03 | IDX | Equal-weighted and FV-weighted returns diverge | WARN | true |  | index_returns | index_returns, frontend_index, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| IDX | IDX04 | IDX | Cost-weighted and FV-weighted returns diverge | WARN | true |  | index_returns | index_returns, frontend_index, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| IDX | IDX05 | IDX | Index aggregate has non-positive count or FV | WARN | true |  | index_returns | index_returns, frontend_index, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| IDX | IDX06 | IDX | Single-position concentration above 50% | WARN | true |  | position_returns | position_returns, frontend_index, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| IDX | IDX07 | IDX | Negative beginning FV eligible for index | WARN | true |  | position_returns | position_returns, frontend_index, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| IDX | IDX08 | IDX | High share of zero position returns | WARN | true |  | position_returns | position_returns, frontend_index, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| IDX | IDX09 | IDX | Direct lending income return unusually high | WARN | true |  | position_returns | position_returns, frontend_index, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| T | T01 | T | CIK position count changes more than 50% QoQ | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| T | T02 | T | CIK total FV jumps more than 3x or drops more than 70% QoQ | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| R | R07 | R | Single position FV exceeds fund total assets | WARN | false |  | holdings, fund_financials | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| M | M02 | M | Matched-pair begin/end FV ratio extreme | WARN | false |  | position_returns | position_returns, frontend_index, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| T | T03 | T | Disappearance without exit | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| T | T04 | T | Classification shift | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| T | T05 | T | Rate population regression | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| T | T06 | T | New position without origination | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| T | T07 | T | Maturity cliff | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| T | T08 | T | Issuer name drift | WARN | false |  | position_matches | position_returns, frontend_index, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| T | T09 | T | Sector composition stability | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| T | T10 | T | Average position size shift | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| S | S01 | S | Strategy-classification mismatch | WARN | false |  | holdings, combined_universe | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| S | S02 | S | BDC equity overweight | WARN | false |  | holdings, combined_universe | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| S | S03 | S | Credit fund with majority fund-of-funds | WARN | false |  | holdings, combined_universe | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| S | S04 | S | Sector concentration | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| S | S05 | S | Vehicle type vs exposure type | WARN | false |  | holdings, combined_universe | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| S | S06 | S | Interval fund with majority direct lending | WARN | false |  | holdings, combined_universe | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| S | S07 | S | Fund size vs position count sparse | WARN | false |  | holdings, fund_financials | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| S | S08 | S | Fund size vs position count dense | WARN | false |  | holdings, fund_financials | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| S | S09 | S | Tender offer fund with public securities | WARN | false |  | holdings, combined_universe | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| S | S10 | S | Income fund without rate data | WARN | false |  | holdings, combined_universe | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| R | R01 | R | Maturity before origination | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| R | R02 | R | Rate change for fixed coupon | WARN | false |  | position_matches | position_returns, frontend_index, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| R | R03 | R | Cost/FV ratio extreme | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| R | R04 | R | Principal on equity | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| R | R05 | R | Spread without floating type | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| R | R06 | R | Zero rate for credit | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| R | R08 | R | Negative shares | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| R | R09 | R | Maturity in distant future | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| R | R10 | R | PIK rate exceeds total rate | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| R | R11 | R | Pct > 25% with many positions | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| R | R12 | R | Cost equals FV exactly for bulk | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| R | R13 | R | Duplicate CUSIP within CIK-quarter | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| R | R14 | R | Interest rate exceeds 50% | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| R | R15 | R | Principal equals zero for debt | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| XS | XS01 | XS | FV divergence | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| XS | XS02 | XS | Position count divergence | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| XS | XS03 | XS | Classification disagreement | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| XS | XS04 | XS | Rate disagreement | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| XS | XS05 | XS | Issuer name disagreement | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| XS | XS06 | XS | Maturity disagreement | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| IDX | IDX10 | IDX | Constituent count QoQ stability | WARN | false |  | index_returns | index_returns, frontend_index, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| IDX | IDX11 | IDX | Index coverage gap | WARN | false |  | index_returns | index_returns, frontend_index, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| IDX | IDX12 | IDX | Vehicle type dominance shift | WARN | false |  | position_returns, combined_universe | position_returns, frontend_index, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| IDX | IDX13 | IDX | Return dispersion | WARN | false |  | position_returns | position_returns, frontend_index, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| IDX | IDX14 | IDX | Index vs fund NAV return | WARN | false |  | index_returns, fund_financials, position_returns | position_returns, frontend_index, index_returns, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| IDX | IDX15 | IDX | Negative income return for direct lending | WARN | false |  | position_returns | position_returns, frontend_index, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| F | F01 | F | Missing quarter | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| F | F02 | F | Stale filing | WARN | false |  | holdings, combined_universe | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| F | F03 | F | Source coverage drop | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| F | F04 | F | N-PORT quarterly gap | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| F | F05 | F | BDC filing gap | WARN | false |  | bdc_filings_index | data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| F | F06 | F | Fund financials coverage | WARN | false |  | holdings, fund_financials, combined_universe | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| F | F07 | F | GICS coverage | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| F | F08 | F | Entity resolution coverage | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| F | F09 | F | Position ID coverage | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| F | F10 | F | New CIK without history | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| M | M01 | M | CUSIP collision | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| M | M03 | M | 1:many match over cap | WARN | false |  | position_matches | position_returns, frontend_index, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| M | M04 | M | Identifier parse failure | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | STABLE | validation_rules_detail.csv |
| M | M05 | M | Entity resolution fragmentation | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| M | M06 | M | Instrument description empty | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| M | M07 | M | CUSIP coverage drop | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| M | M08 | M | Position ID chain break | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| M | M09 | M | Duplicate entity_id for different issuers | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
| M | M10 | M | Name normalization collision | WARN | false |  | holdings | private_markets_holdings, frontend_fund_detail, data_quality_dashboard | CHRONIC | validation_rules_detail.csv |
