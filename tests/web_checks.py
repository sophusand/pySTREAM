"""Drive the browser version (pySTREAM_web.py) from a script, for the tests in test_web.py.

Makes the same changes as the regression scenarios (see helpers.SCENARIOS), but through
'Update scenario' of the browser version, and writes the results to a JSON file.

Usage: python web_checks.py <program_dir> <output.json>
"""
import json
import os
import sys
import warnings

import helpers

program_dir, output_file = sys.argv[1:3]
warnings.simplefilter('ignore')
os.chdir(program_dir)
sys.path.insert(0, program_dir)

import pySTREAM_web as W

B = W.B
W.after_calculation()
out = {'scenarios': {}, 'warnings': {}, 'refused': {}, 'pages': {}}


def run(name, changes):
    """Start from the default scenario, make the changes with 'Update scenario' and collect the results."""
    W.load_scenario_file(B.DEFAULT_SCData)
    changes = changes() if callable(changes) else changes
    out['warnings'][name] = [w['title'] for w in W.update_scenario(changes)]
    out['scenarios'][name] = helpers.collect_outputs(B)


run('default', {})
run('year_2035', {'scenario_year': 2035})
run('heat_and_transport_electrification', lambda: {
    'heat': {'District Heating': {'Residential': B.df_beta_SC.loc['District Heating', 'Residential'] - 0.2},
             'Heatpumps': {'Residential': B.df_beta_SC.loc['Heatpumps', 'Residential'] + 0.2}},
    'transport_fuels': {'Car': {f: {'Electricity': 0.8, 'Ethanol': 0.1, 'Biodiesel': 0.1}.get(f, 0) for f in B.df_TransportFuel_SC.columns},
                        'Bus': {f: {'Electricity': 0.5, 'Biodiesel': 0.35, 'UPGR Biogas': 0.15}.get(f, 0) for f in B.df_TransportFuel_SC.columns}}})
run('chp_surplus', lambda: {'electricity': {
    'Coal incl. CO2-storage': B.df_Power_SC.loc['Coal incl. CO2-storage', 'Shares'] + 0.4,
    'Wind, onshore': B.df_Power_SC.loc['Wind, onshore', 'Shares'] - 0.244,
    'Wind, offshore': B.df_Power_SC.loc['Wind, offshore', 'Shares'] - 0.156}})
run('high_prices', {'co2_price': 150, 'prices': {'Natural Gas': 15, 'Biomass (Straw,woodwaste)': 12, 'Coal': 20}})

#Values that are not allowed are refused, and nothing changes
W.load_scenario_file(B.DEFAULT_SCData)
before = helpers.collect_outputs(B)
for name, changes in {'share 120 %': {'heat': {'Heatpumps': {'Residential': 1.2}}},
                      'heating sum 120 %': {'heat': {'Heatpumps': {'Residential': B.df_beta_SC.loc['Heatpumps', 'Residential'] + 0.2}}},
                      'utilisation 0 %': {'utilisation': {'Car': 0}},
                      'price -3': {'prices': {'Natural Gas': -3}},
                      'co2 price -10': {'co2_price': -10},
                      'year 2010': {'scenario_year': 2010}}.items():
    try:
        W.update_scenario(changes)
        out['refused'][name] = None
    except W.UserError as error:
        out['refused'][name] = error.message
out['unchanged after refused input'] = helpers.compare(before, helpers.collect_outputs(B)) == []

#Every page can be made and stored as JSON
for name in W.PAGES:
    try:
        json.dumps(W.page(name), allow_nan=False)
        out['pages'][name] = 'ok'
    except Exception as error:
        out['pages'][name] = f'{type(error).__name__}: {error}'

with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(out, f)
