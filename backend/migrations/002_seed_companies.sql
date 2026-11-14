-- Seeds the companies table from the registry in app/core/companies.py.
-- Keep these two in sync by hand for now (prototype scale, 19 rows) — see README.md.

insert into companies (ticker, name, exchange, sector, yfinance_symbol, is_seed_portfolio) values
('RELIANCE', 'Reliance Industries Ltd', 'NSE', 'Energy / Conglomerate', 'RELIANCE.NS', true),
('HDFCBANK', 'HDFC Bank Ltd', 'NSE', 'Banking', 'HDFCBANK.NS', true),
('ICICIBANK', 'ICICI Bank Ltd', 'NSE', 'Banking', 'ICICIBANK.NS', true),
('SBIN', 'State Bank of India', 'NSE', 'Banking', 'SBIN.NS', true),
('TCS', 'Tata Consultancy Services Ltd', 'NSE', 'IT Services', 'TCS.NS', true),
('INFY', 'Infosys Ltd', 'NSE', 'IT Services', 'INFY.NS', true),
('BHARTIARTL', 'Bharti Airtel Ltd', 'NSE', 'Telecom', 'BHARTIARTL.NS', true),
('ITC', 'ITC Ltd', 'NSE', 'FMCG', 'ITC.NS', true),
('HINDUNILVR', 'Hindustan Unilever Ltd', 'NSE', 'FMCG', 'HINDUNILVR.NS', true),
('LT', 'Larsen & Toubro Ltd', 'NSE', 'Infrastructure / Engineering', 'LT.NS', true),
('TATAMOTORS', 'Tata Motors Ltd', 'NSE', 'Automobile', 'TATAMOTORS.NS', true),
('MARUTI', 'Maruti Suzuki India Ltd', 'NSE', 'Automobile', 'MARUTI.NS', true),
('SUNPHARMA', 'Sun Pharmaceutical Industries Ltd', 'NSE', 'Pharmaceuticals', 'SUNPHARMA.NS', true),
('NTPC', 'NTPC Ltd', 'NSE', 'Power / Utilities', 'NTPC.NS', true),
('TATASTEEL', 'Tata Steel Ltd', 'NSE', 'Metals & Mining', 'TATASTEEL.NS', true),
('TRENT', 'Trent Ltd', 'NSE', 'Retail', 'TRENT.NS', false),
('BEL', 'Bharat Electronics Ltd', 'NSE', 'Defence / Electronics', 'BEL.NS', false),
('DMART', 'Avenue Supermarts Ltd (DMart)', 'NSE', 'Retail', 'DMART.NS', false),
('VBL', 'Varun Beverages Ltd', 'NSE', 'Beverages / FMCG', 'VBL.NS', false)
on conflict (ticker) do nothing;
