'''pySTREAM in the web browser.

Starts a small web server on this computer (http://127.0.0.1:8765) and opens pySTREAM in the browser, where the
page adapts to any screen size. The model is the same as in the desktop window (pySTREAM.py): Backend.py and
Time_Series.py calculate everything; this file only shows the results and passes the user's changes on.

Normally started by double-clicking "pySTREAM Mac" or "pySTREAM Windows.bat". To start it yourself:
    python pySTREAM_web.py        (options: --port 8765, --no-browser, --keep-running)
pySTREAM stops when 'Close pySTREAM' is clicked on the page, or by itself a minute after its last browser tab was closed.
Nothing is sent over the internet: the server only accepts connections from this computer.
'''

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import openpyxl
import pandas as pd

PROGRAM_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(PROGRAM_DIR, 'web')
ERROR_LOG = os.path.join(PROGRAM_DIR, 'pySTREAM error log.txt')
DEFAULT_PORT = 8765
MAX_YEAR = 2100


#Errors: explained in plain language in the browser, details saved in the error log
#==============================================================================
def friendly_error_message(error):
    """Explain an error in plain language (the same texts as in the desktop window)."""
    if isinstance(error, PermissionError):
        return ("pySTREAM could not open or save this file:\n" + str(error.filename) +
                "\n\nThe file is probably open in Excel or another program. Close it there and try again.")
    if isinstance(error, FileNotFoundError):
        return ("pySTREAM could not find this file:\n" + str(error.filename) +
                "\n\nCheck that it is in the pySTREAM folder, or download pySTREAM again.")
    if isinstance(error, KeyError):
        return ("A value pySTREAM needs is missing in the data files: " + str(error) +
                "\n\nCheck that the data files are complete and that no names in them were changed.")
    return "Something went wrong: " + type(error).__name__ + ": " + str(error)


def log_error(error):
    """Save the details of an error in the error log and return the message to show."""
    details = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
    print(details, file=sys.stderr)
    message = friendly_error_message(error)
    try:
        with open(ERROR_LOG, 'a', encoding='utf-8') as log:
            log.write(datetime.now().strftime('--- %Y-%m-%d %H:%M:%S\n') + details + '\n')
        message += "\n\nThe details are saved in the error log:\n" + ERROR_LOG + "\nPlease include that file if you ask for help."
    except OSError:
        pass
    return message


class UserError(Exception):
    """A problem with what the user entered; shown as it is, without an error log entry."""
    def __init__(self, title, message):
        super().__init__(message)
        self.title = title
        self.message = message


#The model
#==============================================================================
#Backend calculates the base year and the scenario when it is imported and keeps the results in module variables.
#Its functions read some scenario inputs from those variables, so the Backend module itself holds the current state:
#changes are written into its data frames and the results of a recalculation are stored back in it.
print('Starting pySTREAM...')
import Backend as B
from Time_Series import run_timeSeries

SECTORS = ['Residential', 'Tertiary', 'Industry', 'Agriculture']
HEAT_FUEL_LABELS = ['Electricity', 'District heating', 'Coal', 'Oil', 'Natural gas', 'Biomass', 'Solar', 'Electricity']
TRANSPORT_FUEL_GROUPS = [('Person', ['Car', 'Bus', 'Train', 'Aviation & ferries']),
                         ('Goods', ['Trucks and cargo vans', 'Train Goods', 'Shipping', 'Air transport']),
                         ('Fishery & Agriculture', ['Fishery', 'Agriculture'])]
SCENARIO_SHEETS = ['Scenario Year', 'Final Energy Consumption', 'Electricity Production', 'District Heat Boiler Production', 'Transport',
                   'Fuels Transportation', 'Transport Work', 'Technology Improvements', 'Energy Savings', 'Technology Efficiencies',
                   'Fuel Refinery Fuel Input Factor', 'Fuel Price', 'Fuel Refinery Cost', 'Sectors Details', 'CO2 Price']
#the scenario data in the order load_SCdata() returns it
SCENARIO_DATA_NAMES = ['Scenario_Year', 'df_beta_SC', 'df_Power_SC', 'df_Heat_SC', 'df_Transport_SC', 'df_TransportFuel_SC', 'df_TransportWork_SC',
                       'df_TransportImprovement_SC', 'df_EnergySavings_SC', 'df_TechEff_SC', 'df_FuelRefinery_SC', 'df_FuelPrice_SC',
                       'df_FuelRefineryCost_SC', 'df_SectorsDetails_SC', 'co2_price_SC', 'df_TransportCosts_SC']
PRICE = 'Market price [€/GJ]'

model_lock = threading.RLock() #one calculation at a time; pages wait until a calculation is finished
page_cache = {}                #page data, cleared when the scenario changes
time_series = {'df_hour': None, 'technologies_used': None} #calculated when the time series page is opened


def make_float(df, columns):
    """Make columns decimal, so values like 0.25 can be stored in them (pandas refuses that in whole-number columns)."""
    for column in columns:
        if df[column].dtype != float:
            df[column] = df[column].astype(float)


def sync_production_amounts():
    """Imports and the produced amounts next to the production shares, as the desktop window sets them
    when it shows its production tables: imports cover what the other shares do not."""
    P, H = B.df_Power_SC, B.df_Heat_SC
    make_float(P, ['Shares'])
    make_float(H, ['Shares'])
    #Rounded so that floating-point rest values (like 1e-16) are not treated as real imports
    P.loc[P.index[-1], 'Shares'] = round(1 - P.iloc[:-1]['Shares'].sum(), 10)
    P['Amount'] = P['Shares'] * B.total_electricity_consumption_SC
    H.loc[H.index[-1], 'Shares'] = round(1 - H.iloc[:-1]['Shares'].sum(), 10)
    H['Amount'] = H['Shares'] * DH_boiler_demand()


def DH_boiler_demand():
    """District heat that the boilers must produce: what the CHP plants do not cover (0 if they cover all of it)."""
    chp = B.df_Power_SC['CHP heat production'].sum()
    return B.total_DH_demand_SC - chp if chp < B.total_DH_demand_SC else 0


def recalculate():
    """Calculate the scenario again with the current inputs (as 'Update Scenario' in the desktop window).
    Returns warnings to show."""
    P, H = B.df_Power_SC, B.df_Heat_SC
    SC_FEC_ES, SC_FEC_tFE, SC_FEC_tES = B.SC_calculations(B.SC_NEC_tFE_el, B.SC_NEC_tFE_heat)
    B.df_FEC_SC, B.df_FEC_SC_total = B.FEC_dataframe(SC_FEC_ES, SC_FEC_tFE, SC_FEC_tES)
    B.df_transport_consumption_SC, B.df_transport_consumption_fuels_SC = B.calculate_transport(
        'Scenario Year', B.df_FEC_SC, B.df_Transport_SC, B.df_TransportWork_SC, B.df_TransportFuel_SC)
    B.df_fuel_secondary_consumption_SC = B.calculate_FR_fuel(B.df_FEC_SC, B.df_transport_consumption_fuels_SC, B.df_FuelRefinery_SC)
    B.total_DH_demand_SC = B.calculate_heat_demand(B.df_FEC_SC, B.df_fuel_secondary_consumption_SC, B.df_FuelRefinery_SC)
    (B.total_electricity_consumption_SC, B.gridloss_SC, H['Amount'], B.total_electricity_demand_SC,
     B.el_transport_SC, B.el_DH_SC, B.el_FR_SC) = B.final_heatPower_calculate(
        B.df_FEC_SC, B.df_transport_consumption_fuels_SC, B.df_fuel_secondary_consumption_SC, B.total_DH_demand_SC, P)
    (B.Fc_DH_SC, B.Fc_El_SC, B.total_fuel_consumption_SC, B.DH_boiler_fuel_consumption_SC,
     P['Total fuel consumption']) = B.fuel_composition(
        P['Fuel'], P['Electricity production (condensing or nonCHP)'], P['Electric efficiency (extract unit: condensing mode)'],
        P['Fuel consumption in CHP-mode'], P['CHP heat production'], P['Heat efficiency in CHP mode (used for allocation)'],
        P['Mode'], H['Fuel'], H['Amount'], H['Fuel efficiency'])
    B.df_Fc_p_SC, B.df_Fc_SC, B.df_fuelType_consumption_SC, B.df_fuelCategory_consumption_SC = B.resources(
        B.df_FEC_SC, B.df_transport_consumption_fuels_SC, B.Fc_El_SC, B.Fc_DH_SC, B.total_fuel_consumption_SC, B.df_FuelRefinery_SC,
        B.DH_boiler_fuel_consumption_SC, B.df_fuel_secondary_consumption_SC, B.gridloss_SC, B.total_electricity_consumption_SC,
        P['CHP heat production'].sum(), H['Amount'].sum())
    B.df_fuel_CO2_SC, B.df_fuelType_CO2_SC = B.calculate_CO2(B.df_Fc_SC, P, B.df_TechEff_SC)
    B.df_capital_costs_SC = B.capital_costs(P, H, B.df_Fc_SC, B.df_FEC_SC, B.df_SectorsDetails_SC, B.df_FuelRefineryCost_SC,
                                            B.df_fuel_secondary_consumption_SC,
                                            B.transport_costs(B.df_Transport_SC, B.df_TransportWork_SC, B.df_TransportFuel_SC, B.df_TransportCosts_SC))
    B.df_om_costs_SC = B.om_costs(P, H, B.df_Fc_SC, B.df_FEC_SC, B.df_SectorsDetails_SC, B.df_FuelRefineryCost_SC, B.df_fuel_secondary_consumption_SC)
    B.df_co2_costs_SC = B.co2_costs(B.co2_price_SC, B.df_fuel_CO2_SC)
    B.df_FuelPrice_SC, B.df_fuel_costs_SC = B.fuel_costs(B.df_FuelPrice_SC, B.df_FuelRefinery_SC, B.df_FuelRefineryCost_SC, B.df_Fc_SC)
    return after_calculation()


def after_calculation():
    """Things to do whenever the scenario results change. Returns warnings to show."""
    sync_production_amounts()
    page_cache.clear()
    time_series['df_hour'] = time_series['technologies_used'] = None #belongs to the previous scenario now
    warnings = []
    #The CHP plants alone produce more district heat than is needed; the surplus is not used
    surplus_heat = B.df_Power_SC['CHP heat production'].sum() - B.total_DH_demand_SC
    if surplus_heat > 0:
        warnings.append({'title': 'Surplus district heat', 'message':
            "The combined heat and power (CHP) plants produce {:.1f} PJ more district heat than is needed ({:.1f} PJ). "
            "No district heating boilers are used and the surplus heat is not used.\n\n"
            "To avoid this, produce less electricity in CHP plants or use more district heating.".format(surplus_heat, B.total_DH_demand_SC)})
    return warnings


def save_scenario_file(file_path):
    """Save the scenario data that can be changed in pySTREAM into a scenario workbook (as the desktop window does)."""
    workbook = openpyxl.load_workbook(file_path)
    def write_column(sheet, values):
        for r, value in enumerate(values, start=2):
            workbook[sheet].cell(row=r, column=2, value=float(value))
    def write_table(sheet, df):
        for c in range(df.shape[1]):
            for r in range(df.shape[0]):
                workbook[sheet].cell(row=r + 2, column=c + 2, value=float(df.iat[r, c]))
    write_column('Electricity Production', B.df_Power_SC['Shares'])
    write_column('District Heat Boiler Production', B.df_Heat_SC['Shares'])
    write_table('Final Energy Consumption', B.df_beta_SC)
    write_table('Fuels Transportation', B.df_TransportFuel_SC)
    write_table('Transport Work', B.df_TransportWork_SC)
    write_column('Fuel Price', B.df_FuelPrice_SC[PRICE])
    workbook['CO2 Price'].cell(row=2, column=1, value=float(B.co2_price_SC))
    workbook.save(file_path)


def save_scenario_year(year):
    workbook = openpyxl.load_workbook(B.SCData)
    workbook['Scenario Year'].cell(row=2, column=1, value=int(year))
    workbook.save(B.SCData)


def shares_problems(beta=None, fuels=None, work=None):
    """The shares that must add up to 100 % but do not (empty if all do)."""
    beta = B.df_beta_SC if beta is None else beta
    fuels = B.df_TransportFuel_SC if fuels is None else fuels
    work = B.df_TransportWork_SC if work is None else work
    problems = []
    def check(name, total):
        if abs(total - 1) > 1e-6:
            problems.append(name + ": " + "{:.2%}".format(total))
    for sector in SECTORS:
        check("Heating, " + sector, beta[sector].iloc[1:].sum())
    for transport_type in fuels.index:
        if transport_type != 'Bike': #bikes use no fuel
            check("Transport fuels, " + transport_type, fuels.loc[transport_type].sum())
    allocation = work['Allocation of transport work']
    check("Allocation of transport work, person", allocation.iloc[:5].sum())
    check("Allocation of transport work, goods", allocation.iloc[5:].sum())
    return problems


def require_shares_add_up(action="The scenario was not updated", problems=None):
    problems = shares_problems() if problems is None else problems
    if problems:
        raise UserError("Shares do not add up to 100 %",
            action + ", because these shares must add up to 100 %, but do not:\n\n" + "\n".join(problems) +
            "\n\nCorrect them and try again.")


def reload_scenario_data():
    """Read the scenario data file again (after opening another scenario or resetting)."""
    B.SC_NEC_tFE_el, B.SC_NEC_tFE_heat, B.df_beta_BY, B.engr = B.BY_calculations() #these depend on the scenario year
    for name, value in zip(SCENARIO_DATA_NAMES, B.load_SCdata()):
        setattr(B, name, value)


def load_scenario_file(file_path):
    """Make file_path the current scenario (copied to data/Scenario Data.xlsx) and recalculate everything."""
    try:
        with pd.ExcelFile(file_path) as workbook:
            missing = [sheet for sheet in SCENARIO_SHEETS if sheet not in workbook.sheet_names]
    except Exception:
        raise UserError("Not a scenario file", "This file could not be read as an Excel workbook (.xlsx).")
    if missing:
        raise UserError("Not a scenario file", "This file is not a pySTREAM scenario (it has no sheet '" + missing[0] + "').")
    with open(B.SCData, 'rb') as current_file:
        previous_scenario = current_file.read()
    if os.path.abspath(file_path) != os.path.abspath(B.SCData):
        shutil.copyfile(file_path, B.SCData)
    try:
        reload_scenario_data()
        return recalculate()
    except Exception:
        #put the previous scenario back, then report the error
        with open(B.SCData, 'wb') as current_file:
            current_file.write(previous_scenario)
        reload_scenario_data()
        recalculate()
        raise


#Changes from the browser
#==============================================================================
def number(value, what):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise UserError("Invalid input", "Please enter a number for " + what + ".")
    if not math.isfinite(number):
        raise UserError("Invalid input", "Please enter a number for " + what + ".")
    return number


def share(value, what, low=0.0):
    value = number(value, what)
    if not low - 1e-12 <= value <= 1 + 1e-12:
        raise UserError("Invalid input", what + " must be between " + format(low * 100, 'g') + " % and 100 %.\n\nYou entered: " + format(value * 100, '.4g') + " %")
    return value


INPUT_FRAMES = ['df_beta_SC', 'df_TransportFuel_SC', 'df_TransportWork_SC', 'df_Power_SC', 'df_Heat_SC', 'df_FuelPrice_SC']


def apply_changes(changes):
    """Check the values sent by the browser and write them into the scenario data. The changes are made in copies,
    which replace the scenario data only when every value is allowed and the shares add up. Returns the scenario year."""
    new = {name: getattr(B, name).copy() for name in INPUT_FRAMES}
    beta, fuels, work, P, H, prices = (new[name] for name in INPUT_FRAMES)
    make_float(beta, SECTORS)
    make_float(fuels, list(fuels.columns))
    make_float(work, list(work.columns))
    make_float(P, ['Shares'])
    make_float(H, ['Shares'])
    make_float(prices, [PRICE])
    updates = [] #(data frame, row, column, value)

    year = B.Scenario_Year
    if 'scenario_year' in changes:
        try:
            year = int(str(changes['scenario_year']).strip())
        except ValueError:
            raise UserError("Invalid input", "Please enter a whole number for the scenario year.")
        if not B.Base_Year < year <= MAX_YEAR:
            raise UserError("Invalid input", "Please enter a valid year between " + str(B.Base_Year) + " and " + str(MAX_YEAR) + ".")

    for tech, values in changes.get('heat', {}).items():
        if tech not in beta.index[1:]:
            raise KeyError(tech)
        for sector, value in values.items():
            if sector not in SECTORS:
                raise KeyError(sector)
            updates.append((beta, tech, sector, share(value, "Shares")))
    for transport_type, values in changes.get('transport_fuels', {}).items():
        if transport_type not in fuels.index or transport_type == 'Bike':
            raise KeyError(transport_type)
        for fuel, value in values.items():
            if fuel not in fuels.columns:
                raise KeyError(fuel)
            updates.append((fuels, transport_type, fuel, share(value, "Shares")))
    for transport_type, value in changes.get('allocation', {}).items():
        if transport_type not in work.index:
            raise KeyError(transport_type)
        updates.append((work, transport_type, 'Allocation of transport work', share(value, "Shares")))
    for transport_type, value in changes.get('utilisation', {}).items():
        if transport_type not in work.index:
            raise KeyError(transport_type)
        updates.append((work, transport_type, 'Utilisation degree', share(value, "The utilisation degree (how full the vehicles are on average)", low=0.01)))
    for tech, value in changes.get('electricity', {}).items():
        if tech not in P.index[:-1]:
            raise KeyError(tech)
        updates.append((P, tech, 'Shares', share(value, "Shares")))
    for tech, value in changes.get('district_heat', {}).items():
        if tech not in H.index[:-1]:
            raise KeyError(tech)
        updates.append((H, tech, 'Shares', share(value, "Shares")))
    for fuel, value in changes.get('prices', {}).items():
        if fuel not in prices.index or prices.loc[fuel, 'Editable [y/n?]'] != 'y':
            raise KeyError(fuel)
        price = number(value, "the price of " + fuel)
        if price < 0:
            raise UserError("Invalid input", "Prices must be 0 €/GJ or more.\n\nYou entered: " + format(price, 'g') + " €/GJ for " + fuel)
        updates.append((prices, fuel, PRICE, price))
    co2_price = B.co2_price_SC
    if 'co2_price' in changes:
        co2_price = number(changes['co2_price'], "the CO2 price (in €/t CO2)")
        if co2_price < 0:
            raise UserError("Invalid input", "The CO2 price must be 0 €/t CO2 or more.\n\nYou entered: " + format(co2_price, 'g'))

    for df, row, column, value in updates:
        df.loc[row, column] = value
    #imports cover what the other production shares do not
    P.loc[P.index[-1], 'Shares'] = round(1 - P.iloc[:-1]['Shares'].sum(), 10)
    H.loc[H.index[-1], 'Shares'] = round(1 - H.iloc[:-1]['Shares'].sum(), 10)
    require_shares_add_up(problems=shares_problems(beta, fuels, work))

    #Backend's functions look these names up in the Backend module when they run, so replacing them there is enough
    for name, df in new.items():
        setattr(B, name, df)
    B.co2_price_SC = co2_price
    return year


def update_scenario(changes):
    """'Update Scenario': apply the changes, save them in the scenario data file and recalculate."""
    year = apply_changes(changes)
    if year != B.Scenario_Year:
        save_scenario_year(year)
        B.Scenario_Year = year
        B.SC_NEC_tFE_el, B.SC_NEC_tFE_heat, B.df_beta_BY, B.engr = B.BY_calculations()
        B.set_SC_transport_demand(B.df_Transport_SC, B.engr)
    save_scenario_file(B.SCData)
    return recalculate()


#Data for the browser
#==============================================================================
def jsonable(value):
    """Convert numpy and pandas values to values JSON can store (NaN and infinity become null)."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [jsonable(v) for v in value.tolist()]
    if isinstance(value, (pd.Series, pd.Index)):
        return [jsonable(v) for v in value.tolist()]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        value = float(value)
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, str):
        return value
    return str(value)


def pct(value, decimals=2):
    return ('{:.' + str(decimals) + '%}').format(value)


def fixed(value, decimals):
    return ('{:.' + str(decimals) + 'f}').format(value)


def table(columns, rows, align=None, title=None, note=None):
    """A read-only table for the browser. rows: lists of cell texts, or dicts with 'cells' and 'kind' ('group' or 'total')."""
    return {'title': title, 'columns': columns, 'align': align or (['left'] + ['right'] * (len(columns) - 1)), 'note': note,
            'rows': [row if isinstance(row, dict) else {'cells': row} for row in rows]}


def inputs():
    """Everything that can be edited, with the values the browser needs to show sums and amounts while editing."""
    beta, fuels, work, P, H, prices = B.df_beta_SC, B.df_TransportFuel_SC, B.df_TransportWork_SC, B.df_Power_SC, B.df_Heat_SC, B.df_FuelPrice_SC
    allocation_groups = [('Person', list(work.index[:5])), ('Goods', list(work.index[5:]))]
    return jsonable({
        'base_year': B.Base_Year, 'scenario_year': B.Scenario_Year, 'max_year': MAX_YEAR,
        'heat': {'sectors': SECTORS,
                 'rows': [{'tech': tech, 'fuel': fuel, 'values': {s: beta.loc[tech, s] for s in SECTORS}}
                          for tech, fuel in zip(beta.index[1:], HEAT_FUEL_LABELS)]},
        'transport_fuels': {'fuels': list(fuels.columns),
                            'groups': [{'name': name, 'rows': [{'type': t, 'values': {f: fuels.loc[t, f] for f in fuels.columns}} for t in types]}
                                       for name, types in TRANSPORT_FUEL_GROUPS]},
        'allocation': [{'name': name, 'rows': [{'type': t, 'value': work.loc[t, 'Allocation of transport work']} for t in types]}
                       for name, types in allocation_groups],
        'utilisation': [{'name': name, 'rows': [{'type': t, 'value': work.loc[t, 'Utilisation degree']} for t in types]}
                        for name, types in allocation_groups],
        'electricity': {'rows': [{'tech': tech, 'share': P.loc[tech, 'Shares'], 'amount': P.loc[tech, 'Amount']} for tech in P.index[:-1]],
                        'total_demand': B.total_electricity_consumption_SC},
        'district_heat': {'rows': [{'tech': tech, 'share': H.loc[tech, 'Shares'], 'amount': H.loc[tech, 'Amount']} for tech in H.index[:-1]],
                          'boiler_demand': DH_boiler_demand(), 'chp': P['CHP heat production'].sum(), 'total_demand': B.total_DH_demand_SC},
        'prices': {'rows': [{'fuel': fuel, 'price': prices.loc[fuel, PRICE]} for fuel in prices.index if prices.loc[fuel, 'Editable [y/n?]'] == 'y'],
                   'co2_price': B.co2_price_SC},
    })


#Charts (Plotly figures, drawn by plotly.js in the browser)
#------------------------------------------------------------------------------
PLOT_COLORS = ['#FEAA00', '#E467AC', '#A96CCE', '#4266BC', '#83D2F4', '#FFFF32', '#217378', '#AF5500', '#dc2f02', '#C5F567', '#5e60ce']
TIME_SERIES_COLORS = ['#C5F567', '#A96CCE', '#FF7400', '#5e60ce', '#83D2F4', '#38ACAE', '#FEAA00', '#66E067', '#E467AC', '#FFFF32',
                      '#4266BC', '#217378', '#AF5500', '#808080', '#f94144', '#f3722c', '#f8961e']
C_DARK, C_MID, C_TEXT = '#27567C', '#7CACD1', '#1F2A36'


def color(i, colors=PLOT_COLORS):
    return colors[i % len(colors)]


def rgba(hex_color, alpha):
    h = hex_color.lstrip('#')
    return 'rgba({}, {}, {}, {})'.format(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def figure(data, title, ytitle=None, xtitle=None, legend_title=None, **layout):
    """A Plotly figure with pySTREAM's look. The browser fits it to the size of its box."""
    base = {
        'title': {'text': title, 'x': 0, 'xanchor': 'left', 'xref': 'paper', 'font': {'size': 14, 'color': C_DARK}},
        'margin': {'l': 10, 'r': 10, 't': 44, 'b': 10},
        'xaxis': {'automargin': True, 'gridcolor': '#E3EBF3', 'zeroline': False},
        'yaxis': {'automargin': True, 'gridcolor': '#E3EBF3', 'zerolinecolor': '#B9C9D9'},
        'legend': {'font': {'size': 11}, 'traceorder': 'normal'},
        'bargap': 0.25,
    }
    if xtitle:
        base['xaxis']['title'] = {'text': xtitle}
    if ytitle:
        base['yaxis']['title'] = {'text': ytitle}
    if legend_title:
        base['legend']['title'] = {'text': legend_title}
    for key, value in layout.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return {'data': data, 'layout': base}


def shared_range(*value_lists):
    """y-axis range that fits all the given values, so the base year and scenario charts can be compared directly."""
    values = [v for values in value_lists for v in values if v is not None and math.isfinite(v)]
    low, high = min(values + [0]), max(values + [0])
    pad = (high - low) * 0.05 or 1
    return [low - pad if low < 0 else 0, high + pad]


def bar_figure(series, title, ytitle, yrange=None, unit='PJ', decimals=1):
    labels = [str(label) for label in series.index]
    data = [{'type': 'bar', 'x': labels, 'y': jsonable(series.to_numpy()), 'marker': {'color': [color(i) for i in range(len(labels))]},
             'hovertemplate': '%{x}<br>%{y:,.' + str(decimals) + 'f} ' + unit + '<extra></extra>', 'showlegend': False}]
    return figure(data, title, ytitle, yaxis={'range': yrange} if yrange else {})


def hbar_figure(series, title, unit='PJ'):
    labels = [str(label) for label in series.index]
    data = [{'type': 'bar', 'orientation': 'h', 'y': labels, 'x': jsonable(series.to_numpy()),
             'marker': {'color': [color(i) for i in range(len(labels))]}, 'showlegend': False,
             'hovertemplate': '%{y}<br>%{x:,.2f} ' + unit + '<extra></extra>'}]
    return figure(data, title, xtitle='[' + unit + ']', yaxis={'autorange': 'reversed', 'tickfont': {'size': 10}})


def stacked_bar_figure(df, title, ytitle, legend_title=None, yrange=None, unit='', decimals=0, percent=False):
    """Stacked bars: one bar per column of df, one colour per row."""
    columns = [str(c) for c in df.columns]
    data = []
    for i, (name, row) in enumerate(df.iterrows()):
        data.append({'type': 'bar', 'name': str(name), 'x': columns, 'y': jsonable(row.to_numpy()), 'marker': {'color': color(i)},
                     'hovertemplate': '%{x}<br>' + str(name) + ': %{y:,.' + str(decimals) + ('%' if percent else 'f') + '} ' + unit + '<extra></extra>'})
    yaxis = {'range': yrange} if yrange else {}
    if percent:
        yaxis['tickformat'] = '.0%'
    return figure(data, title, ytitle, legend_title=legend_title, barmode='relative', yaxis=yaxis)


def pie_figure(series, title, colors):
    keep = (series.abs() > 1e-9).to_numpy()
    colors = [c for c, k in zip(colors, keep) if k] #each category keeps its colour when another one is left out
    series = series[keep]
    return figure([{'type': 'pie', 'labels': [str(i) for i in series.index], 'values': jsonable(series.to_numpy()),
                    'marker': {'colors': colors, 'line': {'color': '#FFFFFF', 'width': 2}}, 'hole': 0.45, 'sort': False,
                    'textinfo': 'percent', 'hovertemplate': '%{label}<br>%{value:,.1f} PJ (%{percent})<extra></extra>'}],
                  title, legend={'orientation': 'h', 'x': 0.5, 'xanchor': 'center', 'y': -0.05, 'yanchor': 'top'})


def sankey_figure(df_fuelType_consumption, df_Fc, year):
    """Energy flow diagram, as in the desktop window."""
    label = ['Bioenergy', 'Coal', 'Oil', 'Geothermal', 'Hydro', 'Waste', 'Natural Gas', 'Nuclear', 'Solar', 'Wave', 'Wind', #sources
             'Fuel Refinery', 'Electricity', 'District heating', #conversion 11, 12, 13
             'Transport', 'Residential', 'Tertiary', 'Industry', 'Agriculture'] #sectors consumption 14, 15, 16, 17, 18
    #Flows from the primary energy sources (nodes 0-10) to where they are used. The fuel for CHP heat ('Heat production')
    #goes to the electricity node, which passes the CHP heat on to district heating (see El below).
    source_targets = {'Fuel Refinery': 11, 'Electricity production': 12, 'Heat production': 12, 'DH boilers': 13,
                      'Transport': 14, 'Residential': 15, 'Tertiary': 16, 'Industry': 17, 'Agriculture': 18}
    source_colors = ['rgba(197, 245, 103, 0.65)', 'rgba(169, 108, 206, 0.65)', 'rgba(94, 96, 206, 0.65)', 'rgba(255, 116, 0, 0.65)',
                     'rgba(56, 172, 174, 0.65)', 'rgba(254, 170, 0, 0.65)', 'rgba(102, 224, 103, 0.65)', 'rgba(228, 103, 172, 0.65)',
                     'rgba(255, 255, 50, 0.65)', 'rgba(66, 102, 188, 0.65)', 'rgba(131, 210, 244, 0.65)']
    source, target, values, color_link = [], [], [], []
    for i, fuel_type in enumerate(label[:11]):
        for column, node in source_targets.items():
            value = df_fuelType_consumption.loc[fuel_type, column]
            if value > 0:
                source.append(i)
                target.append(node)
                values.append(value)
                color_link.append(source_colors[i])

    FR = df_Fc.loc[['Biodiesel', 'Biogas', 'Diesel', 'Ethanol', 'Gasoline', 'Hydrogen', 'Methanol', 'UPGR Biogas'],
                   ['Electricity production', 'Heat production', 'DH boilers', 'Transport', 'Residential', 'Tertiary', 'Industry', 'Agriculture']].sum().tolist()
    FR_EL = df_Fc.loc['Electricity', 'Fuel Refinery']
    FR_DH = df_Fc.loc['District Heating', 'Fuel Refinery']
    El = df_fuelType_consumption.loc['Electricity', ['DH boilers', 'Transport', 'Residential', 'Tertiary', 'Industry', 'Agriculture']].tolist()
    #either consumption or production of electricity by the fuel refinery
    if FR_EL >= 0:
        El.append(FR_EL)
        FR.append(0)
    else:
        FR.append(abs(FR_EL))
        El.append(0)
    El[0] += abs(df_fuelType_consumption.loc['District Heating', 'Heat production'])
    DH = df_fuelType_consumption.loc['District Heating', ['Residential', 'Tertiary', 'Industry', 'Agriculture']].tolist()
    #either consumption or production of district heating by the fuel refinery
    if FR_DH >= 0:
        DH.append(FR_DH)
        FR.append(0)
    else:
        FR.append(abs(FR_DH))
        DH.append(0)

    #Flows out of the fuel refinery (node 11), electricity production (12) and district heating (13)
    source += [11] * 10 + [12] * 7 + [13] * 5
    target += [12, 12, 13, 14, 15, 16, 17, 18, 12, 13,
               13, 14, 15, 16, 17, 18, 11,
               15, 16, 17, 18, 11]
    values += FR + El + DH
    color_link += ['rgba(33, 115, 120, 0.65)'] * 10 + ['rgba(175, 85, 0, 0.65)'] * 7 + ['rgba(220, 47, 2, 0.65)'] * 5
    color_node = ['#C5F567', '#A96CCE', '#5e60ce', '#FF7400', '#38ACAE', '#FEAA00', '#66E067', '#E467AC', '#FFFF32', '#4266BC',
                  '#83D2F4', '#217378', '#AF5500', '#dc2f02'] + [C_DARK] * 5
    data = [{'type': 'sankey', 'arrangement': 'snap', 'valueformat': ',.1f', 'valuesuffix': ' PJ',
             'node': {'label': label, 'pad': 18, 'thickness': 15, 'color': color_node, 'line': {'width': 0}},
             'link': {'source': source, 'target': target, 'value': jsonable(values), 'color': color_link}}]
    return figure(data, 'Energy streams - ' + str(year), font={'size': 11})


def sector_consumption(df_FEC, df_transport_consumption):
    consumption = df_FEC.iloc[:, :4].sum()
    consumption.loc['Transport'] = df_transport_consumption.sum().values[0]
    return consumption * 0.001


def CO2_by_sector(df_fuelType_CO2):
    return df_fuelType_CO2.sum().rename({'Electricity production no CCS': 'Electricity no CCS', 'Electricity production w. CCS': 'Electricity w. CCS',
                                         'Total emissions incl. CCS': 'Total w. CCS', 'Total emissions excl. CCS': 'Total no CCS'})


def graphs_page():
    BY, SC = str(B.Base_Year), str(B.Scenario_Year)
    charts = {}
    charts['sankey'] = {'label': 'Sankey', 'BY': sankey_figure(B.df_fuelType_consumption_BY, B.df_Fc_BY, BY),
                        'SC': sankey_figure(B.df_fuelType_consumption_SC, B.df_Fc_SC, SC)}
    fec_by, fec_sc = B.df_FEC_BY.iloc[:, :4], B.df_FEC_SC.iloc[:, :4]
    r = shared_range(fec_by.sum().tolist(), fec_sc.sum().tolist())
    charts['fec_stacked'] = {'label': 'Sectors & technologies',
                             'BY': stacked_bar_figure(fec_by, 'Final Energy Consumption per Sector - ' + BY, '[TJ]', 'Technologies', r, 'TJ'),
                             'SC': stacked_bar_figure(fec_sc, 'Final Energy Consumption per Sector - ' + SC, '[TJ]', 'Technologies', r, 'TJ')}
    s_by, s_sc = sector_consumption(B.df_FEC_BY, B.df_transport_consumption_BY), sector_consumption(B.df_FEC_SC, B.df_transport_consumption_SC)
    r = shared_range(s_by.tolist(), s_sc.tolist())
    charts['fec_bar'] = {'label': 'All sectors consumption',
                         'BY': bar_figure(s_by, 'Final Energy Consumption per Sector - ' + BY, '[PJ]', r),
                         'SC': bar_figure(s_sc, 'Final Energy Consumption per Sector - ' + SC, '[PJ]', r)}
    c_by, c_sc = CO2_by_sector(B.df_fuelType_CO2_BY), CO2_by_sector(B.df_fuelType_CO2_SC)
    r = shared_range(c_by.tolist(), c_sc.tolist())
    charts['co2'] = {'label': 'CO2',
                     'BY': bar_figure(c_by, 'CO2 emissions per Sector - ' + BY, 'mill tons', r, 'mill tons', 2),
                     'SC': bar_figure(c_sc, 'CO2 emissions per Sector - ' + SC, 'mill tons', r, 'mill tons', 2)}
    r = shared_range(B.df_Power_BY['Amount'].tolist(), B.df_Power_SC['Amount'].tolist())
    charts['electricity'] = {'label': 'Electricity',
                             'BY': bar_figure(B.df_Power_BY['Amount'], 'Electricity production per production method - ' + BY, '[PJ]', r),
                             'SC': bar_figure(B.df_Power_SC['Amount'], 'Electricity production per production method - ' + SC, '[PJ]', r)}
    r = shared_range(B.df_Heat_BY['Amount'].tolist(), B.df_Heat_SC['Amount'].tolist())
    charts['heat'] = {'label': 'District heat',
                      'BY': bar_figure(B.df_Heat_BY['Amount'], 'District heating production per production method - ' + BY, '[PJ]', r),
                      'SC': bar_figure(B.df_Heat_SC['Amount'], 'District heating production per production method - ' + SC, '[PJ]', r)}
    p_by = B.df_fuelType_consumption_BY['Total primary fuel consumption'].drop(['Electricity', 'District Heating'])
    p_sc = B.df_fuelType_consumption_SC['Total primary fuel consumption'].drop(['Electricity', 'District Heating'])
    r = shared_range(p_by.tolist(), p_sc.tolist())
    charts['primary_fuels'] = {'label': 'Fuel consumption',
                               'BY': bar_figure(p_by, 'Total primary fuel consumption - ' + BY, '[PJ]', r),
                               'SC': bar_figure(p_sc, 'Total primary fuel consumption - ' + SC, '[PJ]', r)}
    return {'base_year': B.Base_Year, 'scenario_year': B.Scenario_Year, 'charts': charts,
            'order': ['sankey', 'fec_stacked', 'fec_bar', 'co2', 'electricity', 'heat', 'primary_fuels']}


def resources_rows():
    """Resources available and used in the scenario [PJ], as in the desktop window."""
    available = B.df_Resources_SC[['Type', 'Amount']].sort_values('Type')
    used = B.df_Fc_p_SC['Total primary fuel consumption'].drop(['Electricity', 'District Heating', 'Imported electricity', 'Imported heat'])
    used['Oil'] = used['Oil'] + used['Crude Oil']
    used = used.drop('Crude Oil').sort_index()
    return [(name, float(amount), float(used_amount)) for (name, amount), used_amount in zip(available.to_numpy().tolist(), used.to_numpy().tolist())]


def production_page():
    rows = resources_rows()
    names = [r[0] for r in rows]
    limit = 500 #longer bars are cut off, so the small ones can be seen; their value is written at the end
    def trace(name, values, bar_color, text_color):
        return {'type': 'bar', 'orientation': 'h', 'name': name, 'y': names, 'x': [min(v, limit) for v in values], 'customdata': values,
                'marker': {'color': bar_color}, 'text': ['{:.0f} PJ ›'.format(v) if v > limit else '' for v in values],
                'textposition': 'inside', 'insidetextanchor': 'end', 'textfont': {'color': text_color, 'size': 10},
                'hovertemplate': '%{y}<br>' + name + ': %{customdata:,.0f} PJ<extra></extra>'}
    resources_chart = figure([trace('Available', [r[1] for r in rows], C_MID, '#1F2A36'), trace('Used', [r[2] for r in rows], C_DARK, '#FFFFFF')],
                             'Resources - available and used [PJ]', barmode='group',
                             xaxis={'range': [0, limit], 'title': {'text': '[PJ] (bars longer than 500 PJ are cut off)'}},
                             yaxis={'autorange': 'reversed', 'tickfont': {'size': 10}},
                             legend={'orientation': 'h', 'x': 0, 'y': 1.0, 'yanchor': 'bottom'}, margin={'t': 64})
    category = B.df_fuelCategory_consumption_SC
    dh = B.df_fuelType_consumption_SC.loc['District Heating']
    dh_sources = pd.Series([abs(dh['Heat production']), abs(dh['DH boilers'])], index=['CHP heat', 'DH boilers'])
    if dh['Fuel Refinery'] < 0:
        dh_sources.loc['Fuel refinery'] = abs(dh['Fuel Refinery'])
    return {
        'resources_table': table(['Resource', 'Available [PJ]', 'Used [PJ]'], [[n, fixed(a, 0), fixed(u, 0)] for n, a, u in rows]),
        'resources_chart': resources_chart,
        'electricity_categories': pie_figure(category.iloc[1:]['Electricity production'], 'Electricity production categories', PLOT_COLORS[0:3]),
        'heat_categories': pie_figure(category.iloc[1:3]['Heat production'] + category.iloc[1:3]['DH boilers'],
                                      'District heat production categories incl. CHP', PLOT_COLORS[0:3]),
        'heat_sources': pie_figure(dh_sources, 'District heat production sources', [PLOT_COLORS[6], PLOT_COLORS[4], PLOT_COLORS[3]]),
    }


def year_data_page(year_label, year, df_FEC, df_beta, df_Power, df_Heat, power_shares, heat_shares):
    """'Base year data' and 'Scenario data': final energy consumption and production."""
    fec_columns = ['Technology type'] + [str(c) for c in df_FEC.columns]
    fec_tj = table(fec_columns, [[str(t)] + [fixed(v, 1) for v in row] for t, row in zip(df_FEC.index, df_FEC.to_numpy().tolist())])
    fec_pct = table(['Technology type'] + [str(c) for c in df_beta.columns],
                    [[str(t)] + [pct(v) for v in row] for t, row in zip(df_beta.index, df_beta.to_numpy().tolist())])
    def production(df, values, form):
        return table(['Production method', 'Produced'], [[str(t), form(v)] for t, v in zip(df['Tech Types'], values)])
    return {
        'year_label': year_label, 'year': year,
        'fec_chart': stacked_bar_figure(df_FEC.iloc[:, :4], 'Final Energy Consumption per Sector - ' + str(year), '[TJ]', 'Technologies', unit='TJ'),
        'fec_tables': {'TJ': fec_tj, '%': fec_pct},
        'production_tables': {'PJ': {'power': production(df_Power, df_Power['Amount'], lambda v: fixed(v, 2)),
                                     'heat': production(df_Heat, df_Heat['Amount'], lambda v: fixed(v, 2))},
                              '%': {'power': production(df_Power, power_shares, pct), 'heat': production(df_Heat, heat_shares, pct)}},
        'power_chart': hbar_figure(df_Power['Amount'], 'Electricity production - ' + str(year)),
        'heat_chart': hbar_figure(df_Heat['Amount'], 'District heating production - ' + str(year)),
    }


def base_year_page():
    return year_data_page('Base year', B.Base_Year, B.df_FEC_BY, B.df_beta_BY, B.df_Power_BY, B.df_Heat_BY,
                          B.df_Power_BY['Amount'] / B.df_Power_BY['Amount'].sum(), B.df_Heat_BY['Amount'] / B.df_Heat_BY['Amount'].sum())


def scenario_page():
    return year_data_page('Scenario year', B.Scenario_Year, B.df_FEC_SC, B.df_beta_SC, B.df_Power_SC, B.df_Heat_SC,
                          B.df_Power_SC['Shares'], B.df_Heat_SC['Shares'])


def transport_year(year, df_TransportFuel, df_transport_consumption, df_transport_consumption_fuels, fuel_rows):
    fuels = [str(f) for f in df_TransportFuel.columns]
    amounts = df_TransportFuel.mul(df_transport_consumption['Energy consumption'], axis=0)
    def grouped(df, form):
        rows = []
        for name, types in TRANSPORT_FUEL_GROUPS:
            rows.append({'cells': [name] + [''] * len(fuels), 'kind': 'group'})
            rows += [[t] + [form(v) for v in df.loc[t].tolist()] for t in types]
        return table([''] + fuels, rows)
    totals = df_transport_consumption_fuels[['Total transport consumption', 'Share of total transport consumption']][:fuel_rows]
    plot_data = df_TransportFuel[df_TransportFuel.index != 'Bike'].rename(index={'Trucks and cargo vans': 'Trucks'}).T
    return {
        'year': year,
        'fuel_tables': {'TJ': grouped(amounts, lambda v: fixed(v, 0)), '%': grouped(df_TransportFuel, lambda v: pct(v, 0))},
        'totals_table': table(['Fuel', 'Used [TJ]', 'Share [%]'], [[str(f), str(int(u)), pct(s)] for f, (u, s) in zip(totals.index, totals.to_numpy().tolist())]),
        'chart': stacked_bar_figure(plot_data, 'Transportation fuel shares - ' + str(year), None, 'Fuels', [0, 1.02], decimals=0, percent=True),
    }


def transport_page():
    return {'BY': transport_year(B.Base_Year, B.df_TransportFuel_BY, B.df_transport_consumption_BY, B.df_transport_consumption_fuels_BY, 5),
            'SC': transport_year(B.Scenario_Year, B.df_TransportFuel_SC, B.df_transport_consumption_SC, B.df_transport_consumption_fuels_SC, 9)}


def CO2_year(year, df_fuel_CO2):
    headings = ['Electricity no CCS', 'Electricity w. CCS', 'District Heat', 'Fuel Refinery', 'Residential', 'Tertiary', 'Industry', 'Agriculture', 'Transport']
    columns = df_fuel_CO2.columns.tolist()[0:-2]
    def cell(value):
        return '' if (value is None or np.isnan(value) or round(value, 5) == 0.) else fixed(value, 3)
    no_ccs = df_fuel_CO2['Total emissions excl. CCS'].to_numpy()
    with_ccs = df_fuel_CO2['Total emissions incl. CCS'].to_numpy()
    fuel_rows = [{'cells': ['Total emissions', fixed(np.nansum(no_ccs), 2), fixed(np.nansum(with_ccs), 2)], 'kind': 'total'}]
    sector_rows = []
    for fuel, a, b, values in zip(df_fuel_CO2.index, no_ccs, with_ccs, df_fuel_CO2[columns].to_numpy().tolist()):
        cells = [cell(v) for v in values]
        empty = not any(cells) and round(np.nan_to_num(a), 5) == 0 and round(np.nan_to_num(b), 5) == 0
        fuel_rows.append({'cells': [str(fuel), fixed(a, 2), fixed(b, 2)], 'kind': 'empty' if empty else None})
        sector_rows.append({'cells': [str(fuel)] + cells, 'kind': 'empty' if empty else None})
    return {'year': year,
            'fuel_table': table(['Fuel', 'no CCS', 'w. CCS'], fuel_rows),
            'sector_table': table(['Fuel'] + headings, sector_rows)}


def CO2_page():
    return {'BY': CO2_year(B.Base_Year, B.df_fuel_CO2_BY), 'SC': CO2_year(B.Scenario_Year, B.df_fuel_CO2_SC)}


COST_HEADINGS = ['Electricity', 'District Heat', 'Fuel Refinery', 'Residential', 'Tertiary', 'Industry', 'Agriculture', 'Transport']
COST_TYPES = ['Capital costs', 'O&M costs', 'Fuel costs', 'CO2 costs']


def costs(df_capital_costs, df_om_costs, df_fuel_costs, df_co2_costs):
    return pd.DataFrame(np.vstack((df_capital_costs.sum(axis=0), df_om_costs.sum(axis=0), df_fuel_costs.sum(axis=0), df_co2_costs.sum(axis=0))),
                        columns=COST_HEADINGS, index=COST_TYPES)


def economy_year(year, df_costs, yrange):
    rows = []
    for cost_type, values in zip(COST_TYPES, df_costs.to_numpy().tolist()):
        cells = [fixed(v, 1) for v in values]
        if cost_type == 'O&M costs':
            cells[-1] = 'in capital*' #vehicle maintenance is part of the capital costs (see the note)
        rows.append([cost_type] + cells + [fixed(sum(values), 1)])
    totals = df_costs.sum(axis=0).tolist()
    rows.append({'cells': ['Total'] + [fixed(v, 1) for v in totals] + [fixed(sum(totals), 1)], 'kind': 'total'})
    return {'year': year,
            'costs_table': table([''] + COST_HEADINGS + ['Total'], rows,
                                 note="* Transport: the capital costs are the costs of the vehicles per person km or tonne km, "
                                      "investment and maintenance together (as in the Excel STREAM model)."),
            'chart': stacked_bar_figure(df_costs, 'Yearly costs - ' + str(year), '[mill. €]', yrange=yrange, unit='mill. €', decimals=1)}


def economy_page():
    by = costs(B.df_capital_costs_BY, B.df_om_costs_BY, B.df_fuel_costs_BY, B.df_co2_costs_BY)
    sc = costs(B.df_capital_costs_SC, B.df_om_costs_SC, B.df_fuel_costs_SC, B.df_co2_costs_SC)
    stacks = lambda df: (df.clip(lower=0).sum(axis=0).tolist() + df.clip(upper=0).sum(axis=0).tolist())
    yrange = shared_range(stacks(by), stacks(sc))
    prices = B.df_FuelPrice_BY
    result = {'BY': economy_year(B.Base_Year, by, yrange), 'SC': economy_year(B.Scenario_Year, sc, yrange)}
    result['BY']['prices_table'] = table(['Fuel', 'Price [€/GJ]'], [[str(f), fixed(prices.loc[f, PRICE], 2)] for f in prices.index
                                                                    if prices.loc[f, 'Editable [y/n?]'] == 'y'])
    result['BY']['co2_price'] = B.co2_price_BY
    return result


def time_series_page():
    df_hour, technologies_used = time_series['df_hour'], time_series['technologies_used']
    if df_hour is None:
        df_hour, technologies_used = run_timeSeries(B.df_Power_SC, B.df_FuelPrice_SC, B.df_FEC_SC, B.total_electricity_demand_SC,
                                                    B.el_transport_SC, B.el_DH_SC, B.el_FR_SC)
        time_series['df_hour'], time_series['technologies_used'] = df_hour, technologies_used

    #Load duration curve with the flexible technologies as bars on top
    curve = df_hour['Consumption after renewables (unflexible and flexible)'].sort_values(ascending=False).to_numpy()
    data = []
    top = 0
    for i, (tech, row) in enumerate(technologies_used.iterrows()):
        height, hours = float(row['Avg']), float(row['Hours'])
        data.append({'type': 'bar', 'orientation': 'h', 'name': str(tech), 'y': [top + height / 2], 'x': [hours], 'width': [height],
                     'marker': {'color': color(i), 'line': {'color': color(i), 'width': 1}}, 'opacity': 0.7,
                     'hovertemplate': str(tech) + '<br>%{x:,.0f} hours, ' + '{:,.0f}'.format(height) + ' MW on average<extra></extra>'})
        top += height
    data.append({'type': 'scatter', 'mode': 'lines', 'name': 'Duration curve', 'x': list(range(len(curve))), 'y': jsonable(curve),
                 'line': {'color': '#2D2E2E', 'width': 2}, 'hovertemplate': 'Hour %{x:,}<br>%{y:,.0f} MW<extra></extra>'})
    low = math.floor(min(curve.min(), 0) / 1000) * 1000
    high = math.ceil(max(curve.max(), 0) / 1000) * 1000
    duration = figure(data, 'Load Duration Curve', 'Avg. Power [MW]', 'Hours', 'Flexible technologies', barmode='overlay',
                      yaxis={'range': [low, high], 'zeroline': True, 'zerolinecolor': '#2D2E2E', 'zerolinewidth': 1.5},
                      xaxis={'range': [0, len(curve)]})

    def average(period, title, tickvals, ticktext):
        hour = df_hour.index % period
        techs = list(B.df_Power_SC.index)
        avg = df_hour[techs].groupby(hour).mean()
        export = (-df_hour['Exported electricity'].abs()).groupby(hour).mean()
        x = list(range(period))
        traces = []
        for i, tech in enumerate(techs):
            values = avg[tech].to_numpy()
            if np.allclose(values, 0):
                continue #technologies that produce nothing are left out of the chart and its legend
            c = TIME_SERIES_COLORS[i % len(TIME_SERIES_COLORS)]
            traces.append({'type': 'scatter', 'mode': 'lines', 'stackgroup': 'production', 'name': tech, 'x': x, 'y': jsonable(values),
                           'line': {'width': 0.5, 'color': c}, 'fillcolor': rgba(c, 0.75), 'hovertemplate': '%{y:,.0f} MW'})
        traces.append({'type': 'scatter', 'mode': 'lines', 'stackgroup': 'export', 'name': 'Exported electricity', 'x': x, 'y': jsonable(export.to_numpy()),
                       'line': {'width': 0.5, 'color': '#FF7400'}, 'fillcolor': rgba('#FF7400', 0.75), 'hovertemplate': '%{y:,.0f} MW'})
        return figure(traces, title, 'Power [MW]', hovermode='x unified',
                      xaxis={'tickvals': tickvals, 'ticktext': ticktext, 'range': [0, period - 1], 'showgrid': False})

    week = average(168, 'Average Weekly Power Production by Technology', list(range(12, 169, 24)), ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
    month = average(744, 'Average Monthly Power Production by Technology', list(range(0, 745, 96)), ['Day {}'.format(i) for i in range(1, 32, 4)])
    flexible = table(['Technology', 'Hours in use', 'Average power [MW]'],
                     [[str(t), '{:,.0f}'.format(r['Hours']), '{:,.0f}'.format(r['Avg'])] for t, r in technologies_used.iterrows()])
    return {'duration': duration, 'week': week, 'month': month, 'flexible_table': flexible}


PAGES = {'graphs': graphs_page, 'production': production_page, 'base_year': base_year_page, 'scenario': scenario_page,
         'transport': transport_page, 'co2': CO2_page, 'economy': economy_page, 'timeseries': time_series_page}


def page(name):
    with model_lock:
        if name not in page_cache:
            page_cache[name] = jsonable(PAGES[name]())
        return page_cache[name]


#Stopping by itself: pySTREAM may run without a window (pySTREAM Mac), so it stops when no browser page uses it
#==============================================================================
class OpenPages:
    """The browser pages that have pySTREAM open. Each page says hello when it opens and every minute while it is
    open, and bye when it is closed or reloaded."""
    START_GRACE = 600     #seconds to wait for the first page (in case the browser is slow to open)
    CLOSE_GRACE = 60      #seconds to wait after the last page was closed (a reloaded page says hello again within seconds)
    PAGE_TIMEOUT = 3 * 3600 #a page that has not said hello for this long is gone (browsers slow down timers in background tabs)

    def __init__(self):
        self.lock = threading.Lock()
        self.last_hello = {}
        self.changed = time.time()
        self.had_page = False

    def hello(self, page_id):
        with self.lock:
            self.last_hello[page_id] = time.time()
            self.had_page = True

    def bye(self, page_id):
        with self.lock:
            if self.last_hello.pop(page_id, None) is not None:
                self.changed = time.time()

    def nobody_left(self):
        with self.lock:
            now = time.time()
            for page_id, last in list(self.last_hello.items()):
                if now - last > self.PAGE_TIMEOUT:
                    del self.last_hello[page_id]
                    self.changed = now
            grace = self.CLOSE_GRACE if self.had_page else self.START_GRACE
            return not self.last_hello and now - self.changed > grace


open_pages = OpenPages()


def stop_when_unused(server):
    while True:
        time.sleep(5)
        if open_pages.nobody_left():
            print('No pySTREAM page is open any more, so pySTREAM stops.')
            server.shutdown()
            return


#The web server
#==============================================================================
STATIC_FILES = {'/': ('index.html', 'text/html; charset=utf-8'),
                '/static/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                '/static/style.css': ('style.css', 'text/css; charset=utf-8')}
PLOTLY_JS = os.path.join(os.path.dirname(__import__('plotly').__file__), 'package_data', 'plotly.min.js')


class Handler(BaseHTTPRequestHandler):
    server_version = 'pySTREAM'

    def log_message(self, format, *args):
        pass #keep the terminal readable

    def send_body(self, body, content_type, status=200, headers=()):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data, status=200):
        self.send_body(json.dumps(data, allow_nan=False).encode('utf-8'), 'application/json; charset=utf-8', status, [('Cache-Control', 'no-store')])

    def read_body(self):
        length = int(self.headers.get('Content-Length') or 0)
        return self.rfile.read(length) if length else b''

    def run(self, action):
        """Run an action and send its result, or an explanation of what went wrong."""
        try:
            self.send_json(action())
        except UserError as error:
            self.send_json({'error': {'title': error.title, 'message': error.message}}, 400)
        except Exception as error:
            self.send_json({'error': {'title': 'pySTREAM - something went wrong', 'message': log_error(error)}}, 500)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path in STATIC_FILES:
            file_name, content_type = STATIC_FILES[path]
            with open(os.path.join(WEB_DIR, file_name), 'rb') as f:
                self.send_body(f.read(), content_type, headers=[('Cache-Control', 'no-cache')])
        elif path == '/static/plotly.min.js':
            with open(PLOTLY_JS, 'rb') as f:
                self.send_body(f.read(), 'text/javascript; charset=utf-8', headers=[('Cache-Control', 'max-age=86400')])
        elif path == '/api/ping':
            self.send_json({'app': 'pySTREAM'})
        elif path == '/api/inputs':
            self.run(lambda: with_lock(inputs))
        elif path.startswith('/api/page/') and path[len('/api/page/'):] in PAGES:
            self.run(lambda: page(path[len('/api/page/'):]))
        elif path == '/api/download-scenario':
            self.download_scenario()
        else:
            self.send_body(b'Not found', 'text/plain', 404)

    def do_POST(self):
        path = self.path.split('?')[0]
        if path in ('/api/hello', '/api/bye'):
            page_id = self.read_body().decode('utf-8', 'replace').strip()[:100]
            (open_pages.hello if path == '/api/hello' else open_pages.bye)(page_id)
            self.send_json({'app': 'pySTREAM'})
        elif path == '/api/quit':
            self.send_json({'ok': True})
            print("'Close pySTREAM' was clicked, so pySTREAM stops.")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        elif path == '/api/update':
            def update():
                changes = json.loads(self.read_body() or b'{}')
                with model_lock:
                    warnings = update_scenario(changes)
                    return {'ok': True, 'warnings': warnings, 'inputs': inputs()}
            self.run(update)
        elif path == '/api/open-scenario':
            def open_scenario():
                body = self.read_body()
                folder = tempfile.mkdtemp(prefix='pystream_')
                try:
                    file_path = os.path.join(folder, 'scenario.xlsx')
                    with open(file_path, 'wb') as f:
                        f.write(body)
                    with model_lock:
                        warnings = load_scenario_file(file_path)
                        return {'ok': True, 'warnings': warnings, 'inputs': inputs()}
                finally:
                    shutil.rmtree(folder, ignore_errors=True)
            self.run(open_scenario)
        elif path == '/api/reset':
            def reset():
                with model_lock:
                    warnings = load_scenario_file(B.DEFAULT_SCData)
                    return {'ok': True, 'warnings': warnings, 'inputs': inputs()}
            self.run(reset)
        elif path == '/api/timeseries':
            def recalculate_time_series():
                with model_lock:
                    time_series['df_hour'] = time_series['technologies_used'] = None
                    page_cache.pop('timeseries', None)
                    return page('timeseries')
            self.run(recalculate_time_series)
        else:
            self.send_body(b'Not found', 'text/plain', 404)

    def download_scenario(self):
        """'Save scenario as': send the current scenario file, to be saved where the user wants it."""
        try:
            with model_lock:
                require_shares_add_up("The scenario was not saved")
                save_scenario_file(B.SCData)
                with open(B.SCData, 'rb') as f:
                    body = f.read()
            self.send_body(body, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                           headers=[('Content-Disposition', 'attachment; filename="My scenario.xlsx"'), ('Cache-Control', 'no-store')])
        except UserError as error:
            self.send_json({'error': {'title': error.title, 'message': error.message}}, 400)
        except Exception as error:
            self.send_json({'error': {'title': 'pySTREAM - something went wrong', 'message': log_error(error)}}, 500)


def with_lock(action):
    with model_lock:
        return action()


PORTS_TO_TRY = 20 #if another program uses the port, the next free one is used


def running_pySTREAM(first_port):
    """The address of a pySTREAM that already runs (for example when it was double-clicked twice), or None."""
    for port in range(first_port, first_port + PORTS_TO_TRY):
        try:
            with urllib.request.urlopen('http://127.0.0.1:{}/api/ping'.format(port), timeout=1) as response:
                if json.load(response).get('app') == 'pySTREAM':
                    return 'http://127.0.0.1:{}/'.format(port)
        except Exception:
            continue
    return None


def main():
    parser = argparse.ArgumentParser(description='pySTREAM in the web browser')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--no-browser', action='store_true', help='do not open the browser')
    parser.add_argument('--keep-running', action='store_true', help='keep running when no browser page has pySTREAM open')
    args, _ = parser.parse_known_args() #(macOS may add arguments of its own when it starts an app)

    url = running_pySTREAM(args.port)
    if url:
        print('pySTREAM is already running: ' + url)
        if not args.no_browser:
            webbrowser.open(url)
        return

    with model_lock:
        after_calculation() #the imports and amounts next to the production shares

    server = None
    for port in range(args.port, args.port + PORTS_TO_TRY):
        try:
            server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
            break
        except OSError:
            continue
    if server is None:
        sys.exit('pySTREAM could not start its web server: ports {}-{} are all in use.'.format(args.port, args.port + PORTS_TO_TRY - 1))
    server.daemon_threads = True
    url = 'http://127.0.0.1:{}/'.format(server.server_address[1])
    print('\npySTREAM is running at ' + url, flush=True)
    print('It opens in your web browser. To stop pySTREAM, click "Close pySTREAM" on the page;')
    print('it also stops by itself a minute after you close its browser tab.\n', flush=True)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=[url]).start()
    if not args.keep_running:
        threading.Thread(target=stop_when_unused, args=[server], daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print('pySTREAM is closed.', flush=True)


if __name__ == '__main__':
    main()
