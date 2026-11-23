"""Run the explicit update and produce reports; no scheduler is installed."""
from lebanon_fuel.cli import main

if __name__ == '__main__':
    result=main(['collect','--source','all'])
    # Even on a source failure, produce a report exposing partial/stale data.
    report_result=main(['report'])
    raise SystemExit(result or report_result)
