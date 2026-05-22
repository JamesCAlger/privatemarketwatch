import pandas as pd
import csv

# Classification results
results = []

# Entity 1: Bron Buyer, LLC - Paper & Plastic Packaging
results.append({
    'name_norm': 'debt paper & plastic packaging products & materials bron buyer, llc type term loan reference rate and spread sofr + 6.00% interest rate 9.77% maturity date 1/13/2029',
    'search_name': 'Debt Paper & Plastic Packaging Products & Materials Bron Buyer, LLC Type Term Loan Reference Rate and Spread SOFR + 6.00% Interest Rate 9.77% Maturity Date 1/13/2029',
    'fair_value': 32092500,
    'verdict': 'GICS',
    'gics_sub_industry': 'Paper Packaging',
    'reasoning': 'Paper & Plastic Packaging Products company - clear packaging industry'
})

# Entity 2: Integrated Power Services Holdings, Inc. - Energy Equipment
results.append({
    'name_norm': 'secured debt energy equipment and services integrated power services holdings, inc. asset type first lien term loan reference rate and spread s + 4.50% interest rate 8.94% maturity date 11/22/2028',
    'search_name': 'Secured Debt Energy Equipment and Services Integrated Power Services Holdings, Inc. Asset Type First Lien Term Loan Reference Rate and Spread S + 4.50% Interest Rate 8.94% Maturity Date 11/22/2028',
    'fair_value': 32072000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Industrial Machinery & Supplies & Components',
    'reasoning': 'Power services equipment company in energy equipment sector'
})

# Entity 3: NDT Global Holding, Inc. - Electronic Equipment
results.append({
    'name_norm': 'electronic equipment, instruments & components ndt global holding, inc. investment first lien debt reference rate and spread s + 4.50% interest rate 8.22% maturity date 6/4/2032',
    'search_name': 'Electronic Equipment, Instruments & Components NDT Global Holding, Inc. Investment First Lien Debt Reference Rate and Spread S + 4.50% Interest Rate 8.22% Maturity Date 6/4/2032',
    'fair_value': 31996000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Electronic Equipment, Instruments & Components',
    'reasoning': 'Electronic Equipment company - matches GICS category exactly'
})

# Entity 4: Locust Point Senior - unclear fund/aggregate
results.append({
    'name_norm': 'locust point senior -fe-9/30/24 /',
    'search_name': 'LOCUST POINT SENIOR -FE-9/30/24 /',
    'fair_value': 31786715,
    'verdict': 'UNRESOLVABLE',
    'gics_sub_industry': '',
    'reasoning': 'Insufficient information - appears to be a fund or structured product with no company details'
})

# Entity 5: NJEye LLC - Healthcare
results.append({
    'name_norm': 'njeye',
    'search_name': 'NJEye LLC',
    'fair_value': 31725000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Health Care Services',
    'reasoning': 'Eye care provider - health care services'
})

# Entity 6: Bron Buyer, LLC (duplicate of entity 1)
results.append({
    'name_norm': 'debt paper & plastic packaging products & materials bron buyer, llc type term loan reference rate and spread sofr + 5.75% interest rate 9.85% maturity date 1/13/2029',
    'search_name': 'Debt Paper & Plastic Packaging Products & Materials Bron Buyer, LLC Type Term Loan Reference Rate and Spread SOFR + 5.75% Interest Rate 9.85% Maturity Date 1/13/2029',
    'fair_value': 31660200,
    'verdict': 'GICS',
    'gics_sub_industry': 'Paper Packaging',
    'reasoning': 'Paper & Plastic Packaging Products company'
})

# Entity 7: Valet Waste Holdings, Inc. - Commercial Services
results.append({
    'name_norm': 'secured debt commercial services and supplies valet waste holdings, inc. asset type first lien term loan reference rate and spread s + 5.75% interest rate floor 1.00% interest rate 11.19% maturity date 05/01/2029',
    'search_name': 'Secured Debt Commercial Services and Supplies Valet Waste Holdings, Inc. Asset Type First Lien Term Loan Reference Rate and Spread S + 5.75% Interest Rate Floor 1.00% Interest Rate 11.19% Maturity Date 05/01/2029',
    'fair_value': 31644000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Environmental & Facilities Services',
    'reasoning': 'Waste management services company - environmental services'
})

# Entity 8: Unison Risk Advisors Inc. - Insurance
results.append({
    'name_norm': 'secured debt insurance unison risk advisors inc. asset type first lien term loan reference rate and spread s + 4.75% interest rate 8.42% maturity date 10/17/2031',
    'search_name': 'Secured Debt Insurance Unison Risk Advisors Inc. Asset Type First Lien Term Loan Reference Rate and Spread S + 4.75% Interest Rate 8.42% Maturity Date 10/17/2031',
    'fair_value': 31641000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Insurance Brokers',
    'reasoning': 'Risk advisory/insurance services company'
})

# Entity 9: Vital Care Buyer, LLC - Healthcare
results.append({
    'name_norm': 'secured debt healthcare providers and services vital care buyer, llc asset type first lien term loan reference rate and spread s + 4.50% interest rate 8.79% maturity date 7/30/2031',
    'search_name': 'Secured Debt Healthcare Providers and Services Vital Care Buyer, LLC Asset Type First Lien Term Loan Reference Rate and Spread S + 4.50% Interest Rate 8.79% Maturity Date 7/30/2031',
    'fair_value': 31622000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Health Care Services',
    'reasoning': 'Healthcare provider - acquisition vehicle for healthcare services company'
})

# Entity 10: Propark Mobility - Parking services
results.append({
    'name_norm': 'propark mobility',
    'search_name': 'Propark Mobility',
    'fair_value': 31620000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Specialized Consumer Services',
    'reasoning': 'Parking management services company'
})

# Entity 11: Valet Waste (another)
results.append({
    'name_norm': 'secured debt commercial services and supplies valet waste holdings, inc. asset type first lien term loan reference rate and spread s + 5.75% interest rate floor 1.00% interest rate 10.18% maturity date 05/01/2029',
    'search_name': 'Secured Debt Commercial Services and Supplies Valet Waste Holdings, Inc. Asset Type First Lien Term Loan Reference Rate and Spread S + 5.75% Interest Rate Floor 1.00% Interest Rate 10.18% Maturity Date 05/01/2029',
    'fair_value': 31561000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Environmental & Facilities Services',
    'reasoning': 'Waste management services'
})

# Entity 12: Valet Waste (another)
results.append({
    'name_norm': 'secured debt commercial services and supplies valet waste holdings, inc. asset type first lien term loan reference rate and spread s + 5.75% interest rate 10.07% maturity date 05/01/2029',
    'search_name': 'Secured Debt Commercial Services and Supplies Valet Waste Holdings, Inc. Asset Type First Lien Term Loan Reference Rate and Spread S + 5.75% Interest Rate 10.07% Maturity Date 05/01/2029',
    'fair_value': 31482000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Environmental & Facilities Services',
    'reasoning': 'Waste management services'
})

# Entity 13: TGNL Purchaser LLC - Building Products
results.append({
    'name_norm': 'debt building products tgnl purchaser llc type term loan reference rate and spread sofr + 5.00% interest rate ﻿9.32% maturity date 6/25/2031',
    'search_name': 'Debt Building Products Tgnl Purchaser LLC Type Term Loan Reference Rate and Spread SOFR + 5.00% Interest Rate ﻿9.32% Maturity Date 6/25/2031',
    'fair_value': 31405454,
    'verdict': 'GICS',
    'gics_sub_industry': 'Building Products',
    'reasoning': 'Building products company - acquisition vehicle'
})

# Entity 14: Valet Waste (another)
results.append({
    'name_norm': 'secured debt commercial services and supplies valet waste holdings, inc. asset type first lien term loan reference rate and spread s + 6.00% interest rate 10.02% maturity date 05/1/2029',
    'search_name': 'Secured Debt Commercial Services and Supplies Valet Waste Holdings, Inc. Asset Type First Lien Term Loan Reference Rate and Spread S + 6.00% Interest Rate 10.02% Maturity Date 05/1/2029',
    'fair_value': 31403000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Environmental & Facilities Services',
    'reasoning': 'Waste management services'
})

# Entity 15: Mustang Prospects Purchaser LLC - Specialized Consumer Services
results.append({
    'name_norm': 'debt specialized consumer services mustang prospects purchaser llc type term loan reference rate and spread sofr + 5.00% interest rate 9.00% maturity date 6/13/2031',
    'search_name': 'Debt Specialized Consumer Services Mustang Prospects Purchaser LLC Type Term Loan Reference Rate and Spread SOFR + 5.00% Interest Rate 9.00% Maturity Date 6/13/2031',
    'fair_value': 31348067,
    'verdict': 'GICS',
    'gics_sub_industry': 'Specialized Consumer Services',
    'reasoning': 'Specialized consumer services - acquisition vehicle'
})

# Entity 16: TGNL Purchaser LLC (duplicate)
results.append({
    'name_norm': 'debt building products tgnl purchaser llc type term loan reference rate and spread sofr + 5.00% interest rate 9.16% maturity date 6/25/2031',
    'search_name': 'Debt Building Products Tgnl Purchaser LLC Type Term Loan Reference Rate and Spread SOFR + 5.00% Interest Rate 9.16% Maturity Date 6/25/2031',
    'fair_value': 31326940,
    'verdict': 'GICS',
    'gics_sub_industry': 'Building Products',
    'reasoning': 'Building products company'
})

# Entity 17: Valet Waste (another)
results.append({
    'name_norm': 'secured debt commercial services and supplies valet waste holdings, inc. asset type first lien term loan reference rate and spread s + 5.75% interest rate floor 1.00% interest rate 10.70% maturity date 5/1/2029',
    'search_name': 'Secured Debt Commercial Services and Supplies Valet Waste Holdings, Inc. Asset Type First Lien Term Loan Reference Rate and Spread S + 5.75% Interest Rate Floor 1.00% Interest Rate 10.70% Maturity Date 5/1/2029',
    'fair_value': 31324000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Environmental & Facilities Services',
    'reasoning': 'Waste management services'
})

# Entity 18: Propio LS, LLC - Professional Services
results.append({
    'name_norm': 'secured debt professional services propio ls, llc asset type first lien term loan reference rate and spread s + 4.75% interest rate 8.42% maturity date 5/10/2030',
    'search_name': 'Secured Debt Professional Services Propio LS, LLC Asset Type First Lien Term Loan Reference Rate and Spread S + 4.75% Interest Rate 8.42% Maturity Date 5/10/2030',
    'fair_value': 31318000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Research & Consulting Services',
    'reasoning': 'Professional services company'
})

# Entity 19: Eclipse Buyer, Inc. - Software
results.append({
    'name_norm': 'secured debt software eclipse buyer, inc. asset type first lien term loan reference rate and spread s + 4.75% interest rate 9.07% maturity date 9/8/2031',
    'search_name': 'Secured Debt Software Eclipse Buyer, Inc. Asset Type First Lien Term Loan Reference Rate and Spread S + 4.75% Interest Rate 9.07% Maturity Date 9/8/2031',
    'fair_value': 31292000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Application Software',
    'reasoning': 'Software company - acquisition vehicle'
})

# Entity 20: Atlas AU Bidco - Application Software
results.append({
    'name_norm': 'debt application software atlas au bidco pty ltd / atlas us finco, inc. type term loan reference rate and spread sofr + 4.75% interest rate 9.08% maturity date 12/9/2029',
    'search_name': 'Debt Application Software Atlas AU Bidco Pty Ltd / Atlas US Finco, Inc. Type Term Loan Reference Rate and Spread SOFR + 4.75% Interest Rate 9.08% Maturity Date 12/9/2029',
    'fair_value': 31157216,
    'verdict': 'GICS',
    'gics_sub_industry': 'Application Software',
    'reasoning': 'Application software company - bidco acquisition vehicle'
})

# Entity 21: American Express GBT - Consumer Finance
results.append({
    'name_norm': 'consumer finance american express gbt gbt group services b.v',
    'search_name': 'Consumer Finance American Express GBT GBT Group Services B.V.',
    'fair_value': 31078000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Consumer Finance',
    'reasoning': 'Consumer finance - American Express business travel division'
})

# Entity 22: MRI Acquisitions, Inc - Diversified Support Services
results.append({
    'name_norm': 'debt diversified support services mri acquisitions, inc type term loan reference rate and spread sofr + 6.25% interest rate 10.07% maturity date 7/1/2026',
    'search_name': 'Debt Diversified Support Services Mri Acquisitions, Inc Type Term Loan Reference Rate and Spread SOFR + 6.25% Interest Rate 10.07% Maturity Date 7/1/2026',
    'fair_value': 31050879,
    'verdict': 'GICS',
    'gics_sub_industry': 'Diversified Support Services',
    'reasoning': 'Diversified support services company'
})

# Entity 23: Activehours/Earnin - Consumer Finance
results.append({
    'name_norm': 'activehoursincdbaearninmember',
    'search_name': 'ActivehoursIncDbaEarninMember',
    'fair_value': 30898000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Consumer Finance',
    'reasoning': 'Earnin - consumer finance app for early wage access'
})

# Entity 24: Hurricane Cleanco Limited - Financial Services
results.append({
    'name_norm': 'debt investments financial services hurricane cleanco limited investment type senior secured interest rate fixed 6.25%, 6.25% pik initial acquisition date 12/31/2024 maturity date 11/22/2029',
    'search_name': 'Debt Investments Financial Services Hurricane Cleanco Limited Investment Type Senior Secured Interest Rate FIXED 6.25%, 6.25% PIK Initial Acquisition Date 12/31/2024 Maturity Date 11/22/2029',
    'fair_value': 30891000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Environmental & Facilities Services',
    'reasoning': 'Cleanco indicates cleaning services company'
})

# Entity 25: F&M Buyer LLC - Health Care Technology
results.append({
    'name_norm': 'secured debt health care technology f&m buyer llc asset type first lien term loan reference rate and spread s + 4.75% interest rate 9.04% maturity date 3/18/2032',
    'search_name': 'Secured Debt Health Care Technology F&M Buyer LLC Asset Type First Lien Term Loan Reference Rate and Spread S + 4.75% Interest Rate 9.04% Maturity Date 3/18/2032',
    'fair_value': 30890000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Health Care Technology',
    'reasoning': 'Health care technology company - acquisition vehicle'
})

# Entity 26: Prism Parent Co Inc. - Application Software
results.append({
    'name_norm': 'debt application software prism parent co inc. type term loan reference rate and spread sofr + 5.00% interest rate 8.73% maturity date 9/16/2028',
    'search_name': 'Debt Application Software Prism Parent Co Inc. Type Term Loan Reference Rate and Spread SOFR + 5.00% Interest Rate 8.73% Maturity Date 9/16/2028',
    'fair_value': 30804129,
    'verdict': 'GICS',
    'gics_sub_industry': 'Application Software',
    'reasoning': 'Application software company'
})

# Entity 27: Mobotrex, LLC - Trading Companies & Distributors
results.append({
    'name_norm': 'debt trading companies & distributors mobotrex, llc type term loan reference rate and spread sofr + 5.00% interest rate 9.30% maturity date 6/7/2030',
    'search_name': 'Debt Trading Companies & Distributors Mobotrex, LLC Type Term Loan Reference Rate and Spread SOFR + 5.00% Interest Rate 9.30% Maturity Date 6/7/2030',
    'fair_value': 30757590,
    'verdict': 'GICS',
    'gics_sub_industry': 'Trading Companies & Distributors',
    'reasoning': 'Trading company and distributor'
})

# Entity 28: Rhino Tool House - Trading/Industrial
results.append({
    'name_norm': 'rhino tool house',
    'search_name': 'Rhino Tool House',
    'fair_value': 30671000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Trading Companies & Distributors',
    'reasoning': 'Tool distributor/retailer'
})

# Entity 29: RPX Corporation - Research & Consulting
results.append({
    'name_norm': 'debt research & consulting services rpx corporation type term loan reference rate and spread sofr + 5.25% interest rate 9.43% maturity date 8/2/2030',
    'search_name': 'Debt Research & Consulting Services RPX Corporation Type Term Loan Reference Rate and Spread SOFR + 5.25% Interest Rate 9.43% Maturity Date 8/2/2030',
    'fair_value': 30652905,
    'verdict': 'GICS',
    'gics_sub_industry': 'Research & Consulting Services',
    'reasoning': 'Research and consulting services company'
})

# Entity 30: MRI Acquisitions (duplicate)
results.append({
    'name_norm': 'debt diversified support services mri acquisitions, inc type term loan reference rate and spread sofr + 6.25% interest rate 10.40% maturity date 7/1/2026',
    'search_name': 'Debt Diversified Support Services Mri Acquisitions, Inc Type Term Loan Reference Rate and Spread SOFR + 6.25% Interest Rate 10.40% Maturity Date 7/1/2026',
    'fair_value': 30642655,
    'verdict': 'GICS',
    'gics_sub_industry': 'Diversified Support Services',
    'reasoning': 'Diversified support services company'
})

# Entity 31: WPP Bullet Buyer, LLC - Food Products
results.append({
    'name_norm': 'secured debt food products wpp bullet buyer, llc asset type first lien term loan reference rate and spread s + 5.25% interest rate 9.54% maturity date 12/7/2030',
    'search_name': 'Secured Debt Food Products WPP Bullet Buyer, LLC Asset Type First Lien Term Loan Reference Rate and Spread S + 5.25% Interest Rate 9.54% Maturity Date 12/7/2030',
    'fair_value': 30638000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Packaged Foods & Meats',
    'reasoning': 'Food products company - acquisition vehicle'
})

# Entity 32: Packaging Coordinators Midco - Containers and Packaging
results.append({
    'name_norm': 'secured debt containers and packaging packaging coordinators midco, inc. asset type first lien term loan reference rate and spread s + s + 4.75% interest rate 8.40% maturity date 10/15/2032',
    'search_name': 'Secured Debt Containers and Packaging Packaging Coordinators Midco, Inc. Asset Type First Lien Term Loan Reference Rate and Spread S + S + 4.75% Interest Rate 8.40% Maturity Date 10/15/2032',
    'fair_value': 30513000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Paper Packaging',
    'reasoning': 'Packaging company'
})

# Entity 33: Digital Experience Services - IT Consulting
results.append({
    'name_norm': 'debt it consulting & other services digital experience services, llc type term loan reference rate and spread sofr + 5.00% interest rate 9.20% maturity date 4/25/2030',
    'search_name': 'Debt IT Consulting & Other Services Digital Experience Services, LLC Type Term Loan Reference Rate and Spread SOFR + 5.00% Interest Rate 9.20% Maturity Date 4/25/2030',
    'fair_value': 30493259,
    'verdict': 'GICS',
    'gics_sub_industry': 'IT Consulting & Other Services',
    'reasoning': 'IT consulting services company'
})

# Entity 34: Net Health Acquisition Corp. - Health Care Technology
results.append({
    'name_norm': 'secured debt health care technology net health acquisition corp. asset type first lien term loan reference rate and spread s + 5.00% interest rate floor 0.75% interest rate 9.85% maturity date 7/3/2031',
    'search_name': 'Secured Debt Health Care Technology Net Health Acquisition Corp. Asset Type First Lien Term Loan Reference Rate and Spread S + 5.00% Interest Rate Floor 0.75% Interest Rate 9.85% Maturity Date 7/3/2031',
    'fair_value': 30462000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Health Care Technology',
    'reasoning': 'Health care technology company'
})

# Entity 35: DTI Midco Corp - IT Services
results.append({
    'name_norm': 'secured debt it services dti midco corp asset type first lien term loan reference rate and spread s + 5.00% interest rate 9.32% maturity date 12/30/2031',
    'search_name': 'Secured Debt IT Services DTI Midco Corp Asset Type First Lien Term Loan Reference Rate and Spread S + 5.00% Interest Rate 9.32% Maturity Date 12/30/2031',
    'fair_value': 30340000,
    'verdict': 'GICS',
    'gics_sub_industry': 'IT Consulting & Other Services',
    'reasoning': 'IT services company'
})

# Entity 36: Permian Production - Oil & Gas
results.append({
    'name_norm': 'permian production',
    'search_name': 'Permian Production Holdings, LLC',
    'fair_value': 30291000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Oil & Gas Exploration & Production',
    'reasoning': 'Permian Basin oil and gas producer'
})

# Entity 37: US Fitness Holdings - Consumer Services
results.append({
    'name_norm': 'secured debt diversified consumer service us fitness holdings, llc asset type first lien term loan reference rate and spread s + 5.50% interest rate 9.15% maturity date 9/4/2031',
    'search_name': 'Secured Debt Diversified Consumer Service US Fitness Holdings, LLC Asset Type First Lien Term Loan Reference Rate and Spread S + 5.50% Interest Rate 9.15% Maturity Date 9/4/2031',
    'fair_value': 30252000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Specialized Consumer Services',
    'reasoning': 'Fitness center operator - specialized consumer services'
})

# Entity 38: Accentcare - Healthcare
results.append({
    'name_norm': 'accentcare',
    'search_name': 'Accentcare, Inc.',
    'fair_value': 30228000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Health Care Services',
    'reasoning': 'Home health care provider'
})

# Entity 39: Net Health Acquisition (duplicate)
results.append({
    'name_norm': 'secured debt health care technology net health acquisition corp. asset type first lien term loan reference rate and spread s + 4.75% interest rate 8.88% maturity date 7/3/2031 one',
    'search_name': 'Secured Debt Health Care Technology Net Health Acquisition Corp. Asset Type First Lien Term Loan Reference Rate and Spread S + 4.75% Interest Rate 8.88% Maturity Date 7/3/2031 One',
    'fair_value': 30224000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Health Care Technology',
    'reasoning': 'Health care technology company'
})

# Entity 40: Capital Equipment - Aggregate header
results.append({
    'name_norm': 'portfolio investments bank loans: non-control/non-affiliate investments capital equipment',
    'search_name': 'Portfolio Investments BANK LOANS: NON-CONTROL/NON-AFFILIATE INVESTMENTS Capital Equipment',
    'fair_value': 30184694,
    'verdict': 'AGGREGATE_HEADER',
    'gics_sub_industry': '',
    'reasoning': 'Section header for portfolio investments - not a real company'
})

# Entity 41: Mooring Primary, LLC - likely fund/structured vehicle
results.append({
    'name_norm': 'mooring primary, llc, senior secured loans',
    'search_name': 'Mooring Primary, LLC, Senior Secured Loans',
    'fair_value': 30179000,
    'verdict': 'JV_SUBSIDIARY',
    'gics_sub_industry': '',
    'reasoning': 'Mooring Primary is likely a CLO or structured credit vehicle'
})

# Entity 42: Focus Financial - Capital Markets
results.append({
    'name_norm': 'capital markets focus financial',
    'search_name': 'Capital Markets Focus Financial',
    'fair_value': 30110000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Investment Banking & Brokerage',
    'reasoning': 'Focus Financial Partners - wealth management/RIA aggregator in capital markets'
})

# Entity 43: Behavioral Framework LLC - Health Care Services
results.append({
    'name_norm': 'debt health care services behavioral framework llc type term loan reference rate and spread sofr + 4.75% interest rate 8.64% maturity date 11/20/2031',
    'search_name': 'Debt Health Care Services Behavioral Framework LLC Type Term Loan Reference Rate and Spread SOFR + 4.75% Interest Rate 8.64% Maturity Date 11/20/2031',
    'fair_value': 30096952,
    'verdict': 'GICS',
    'gics_sub_industry': 'Health Care Services',
    'reasoning': 'Behavioral health services provider'
})

# Entity 44: EPFS Buyer, Inc. - Healthcare
results.append({
    'name_norm': 'secured debt healthcare providers and services epfs buyer, inc. asset type first lien term loan reference rate and spread s + 4.75% interest rate 8.73% maturity date 7/31/2031',
    'search_name': 'Secured Debt Healthcare Providers and Services EPFS Buyer, Inc. Asset Type First Lien Term Loan Reference Rate and Spread S + 4.75% Interest Rate 8.73% Maturity Date 7/31/2031',
    'fair_value': 30054000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Health Care Services',
    'reasoning': 'Healthcare provider - acquisition vehicle'
})

# Entity 45: EPFS Buyer (duplicate)
results.append({
    'name_norm': 'secured debt healthcare providers and services epfs buyer, inc. asset type first lien term loan reference rate and spread s + 4.50% interest rate 8.15% maturity date 7/31/2031',
    'search_name': 'Secured Debt Healthcare Providers and Services EPFS Buyer, Inc. Asset Type First Lien Term Loan Reference Rate and Spread S + 4.50% Interest Rate 8.15% Maturity Date 7/31/2031',
    'fair_value': 30047000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Health Care Services',
    'reasoning': 'Healthcare provider'
})

# Entity 46: TMRW Life Sciences - Healthcare Technology
results.append({
    'name_norm': 'portfolio company debt securities- united states healthcare technology tmrw life sciences',
    'search_name': 'Portfolio Company Debt Securities- United States Healthcare Technology TMRW Life Sciences, Inc.',
    'fair_value': 30003000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Health Care Technology',
    'reasoning': 'Healthcare technology company - fertility/IVF technology'
})

# Entity 47: Animal Dermatology Group - Healthcare
results.append({
    'name_norm': 'animal dermatology group, inc., senior secured loans',
    'search_name': 'Animal Dermatology Group, Inc., Senior Secured Loans',
    'fair_value': 29939000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Health Care Services',
    'reasoning': 'Veterinary dermatology services - healthcare services'
})

# Entity 48: American Refrigeration - Industrial/Commercial Services
results.append({
    'name_norm': 'american refrigeration',
    'search_name': 'American Refrigeration',
    'fair_value': 29925000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Building Products',
    'reasoning': 'Commercial refrigeration services and equipment'
})

# Entity 49: Lakeview Farms - Food Products
results.append({
    'name_norm': 'lakeview farms',
    'search_name': 'Lakeview Farms Inc',
    'fair_value': 29900000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Packaged Foods & Meats',
    'reasoning': 'Food producer/processor'
})

# Entity 50: Endurance PT Technology Buyer - Industrial Machinery
results.append({
    'name_norm': 'debt industrial machinery & supplies & components endurance pt technology buyer corporation type term loan reference rate and spread sofr + 6.50% interest rate 10.17% maturity date 10/28/2031',
    'search_name': 'Debt Industrial Machinery & Supplies & Components Endurance PT Technology Buyer Corporation Type Term Loan Reference Rate and Spread SOFR + 6.50% Interest Rate 10.17% Maturity Date 10/28/2031',
    'fair_value': 29850000,
    'verdict': 'GICS',
    'gics_sub_industry': 'Industrial Machinery & Supplies & Components',
    'reasoning': 'Industrial machinery and technology company'
})

# Create DataFrame and write to CSV
df = pd.DataFrame(results)
output_path = 'C:/Users/alger/Documents/000. Projects/005. evergreen funds platform xbrl/data/output/gics_agent_results_009.csv'
df.to_csv(output_path, index=False, quoting=csv.QUOTE_ALL)

print(f'Successfully classified {len(results)} entities')
print(f'Results written to: {output_path}')
print(f"\nBreakdown:")
print(f"GICS: {sum(1 for r in results if r['verdict'] == 'GICS')}")
print(f"AGGREGATE_HEADER: {sum(1 for r in results if r['verdict'] == 'AGGREGATE_HEADER')}")
print(f"JV_SUBSIDIARY: {sum(1 for r in results if r['verdict'] == 'JV_SUBSIDIARY')}")
print(f"UNRESOLVABLE: {sum(1 for r in results if r['verdict'] == 'UNRESOLVABLE')}")
