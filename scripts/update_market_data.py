"""Run from the project environment: python scripts/update_market_data.py."""
from lebanon_fuel.market.cli import main

if __name__=='__main__':
    raise SystemExit(main(['collect','--source','all']))
