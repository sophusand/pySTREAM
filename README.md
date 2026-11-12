# pySTREAM

pySTREAM is an energy scenario modelling tool that runs in your web browser. You describe
an energy system for a future year — how electricity and heat are produced, which fuels
the sectors and transport use — and pySTREAM calculates the energy balance, CO2
emissions, costs and an hourly time series, and compares them with the base year.

pySTREAM is a Python version of the Excel model
[STREAM](https://www.esymodels.man.dtu.dk/stream) and gives the same results (see
[docs/comparison-with-excel-model.md](docs/comparison-with-excel-model.md)). It was
created by Ida Cecilie Hoielt as a Bachelor's thesis project at DTU (Technical
University of Denmark) in 2023 with Tilman Weckesser as supervisor. It was updated as part of a special course in 2024, and in 2026 reviewed with assistance from Claude to fix bugs and add some QoL features.

## Install and start

You need **Python 3.12 or newer**. If you do not have it, install it from
https://www.python.org/downloads/ (on Windows, tick **Add python.exe to PATH**).

1. Download pySTREAM: on GitHub, click **Code → Download ZIP**, and unzip it, for
   example to your Desktop or Documents folder.
2. Double-click the start file for your computer in the pySTREAM folder:
   - **macOS:** **pySTREAM Mac**
   - **Windows:** **pySTREAM Windows.bat**

The first time, this installs the Python packages pySTREAM needs (in the `.venv` folder;
it takes a few minutes and you can follow it in the window that opens). After that,
pySTREAM opens in your web browser within a few seconds. On Windows, pySTREAM also uses
the Conda environment `pySTREAM_class` if you made one before.

pySTREAM runs only on your own computer (at http://127.0.0.1:8765); nothing is sent over
the internet. The page fits any screen size. To stop pySTREAM, click **Close pySTREAM**
at the bottom of the menu; it also stops by itself a minute after you close its browser
tab. On Windows, closing its window stops it too.

**macOS: "pySTREAM Mac" could not be opened / Apple could not verify it.** macOS asks this
the first time for programs that are downloaded and not from the App Store. Open
**System Settings → Privacy & Security**, scroll down and click **Open Anyway** next to
the message about pySTREAM Mac. You only need to do this once. If pySTREAM then asks
where it is, choose the pySTREAM folder.

**Windows: "Windows protected your PC".** Click **More info → Run anyway**.

The old desktop window can still be started with `python pySTREAM.py` (in the `.venv`
environment); it uses the same data files.

## Using pySTREAM

- Edit a value by clicking it, typing a new one and pressing **Enter**. Sums and amounts
  update right away and changed values turn yellow. **Update scenario** (top right)
  calculates the new results; the scenario year is changed in the same place.
- Every chart is interactive (hover for values); the camera icon above a chart saves it
  as a PNG picture for your report.

## Your first scenario

pySTREAM starts with a scenario for 2050 compared with the base year 2015. Try changing
it:

1. Click **Edit production** in the menu on the left.
2. In the **Electricity** table, click the share of *Coal incl. CO2-storage*, type a
   smaller number, for example `14.6`, and press **Enter**. Then click *Wind, offshore*
   and add the same amount, for example `33.4`. The amounts next to the shares are
   updated right away.
3. Click **Update scenario** (top right). pySTREAM recalculates everything and saves
   your scenario.
4. Look at the results: **Graphs** (energy flows and more), **CO2 emissions**,
   **Economy** (costs per sector) and **Time series** (hourly electricity).

Good to know:

- Shares that must add up to 100 % (heating per sector, fuels per transport type,
  transport work) are checked: sums that do not add up are red, and pySTREAM tells you
  which ones they are when you update.
- If electricity or district heat production adds up to less than 100 %, the rest is
  imported; above 100 %, the surplus is exported.
- The scenario year (top right) changes the energy demand; type a new year and press
  **Update scenario**.
- The pySTREAM manual (`pySTREAM Manual.pdf`) describes the desktop window; the pages
  in the browser show the same tables and charts.

## Saving your work

pySTREAM keeps the current scenario in `data/Scenario Data.xlsx`, so it is still there
the next time you start pySTREAM. The buttons at the bottom of the menu:

- **Save scenario as...** saves the current scenario as an Excel file (in your Downloads
  folder, or where you choose), so you can keep several scenarios.
- **Open scenario...** continues with a saved scenario.
- **Reset to default scenario** goes back to the scenario pySTREAM comes with.

To save a chart as a picture for a report, use the camera icon above it.

## If something goes wrong

- pySTREAM shows errors on the page, in plain language. The details are saved in
  `pySTREAM error log.txt` in the pySTREAM folder; include that file if you ask for help.
- **"The file is open in Excel":** close the data file in Excel and try again.
- **"pySTREAM is not running":** it was closed. Start it again with the start file; the
  open page reconnects by itself.
- **macOS: "pySTREAM could not start"** shows the end of its messages; all of them are in
  `~/Library/Logs/pySTREAM.log`.
- **Python is missing or too old:** the start file opens the Python download page.
  Install Python 3.12 or newer and double-click the start file again.
- **The old desktop window adapts to your screen:** the window, text, tables and plots
  are scaled to fill the screen it is started on. On a very small screen (smaller than
  about 1150 x 650 pixels) the text keeps a readable size and scroll bars appear; you can
  also scroll with the mouse wheel (Shift + wheel scrolls sideways). If you move it to
  another screen, start it again there to fit that screen.

## Data and assumptions

- `data/Base Year Data.xlsx`: the energy system in the base year 2015. The data is based
  on the STREAM model; updating it to a more recent base year is planned for the future.
- `data/Default Scenario Data.xlsx`: the scenario pySTREAM comes with.
- `data/Energy profiles.xlsx`: hourly profiles of electricity and heat demand and of
  wind, solar, wave and hydro power, for the time series.
- `data/Assumptions.xlsx`: model assumptions such as grid losses, the discount rate and
  the CO2 capture rate, with units and explanations. You can change them there.

How pySTREAM's results compare with the Excel STREAM model, and where they deliberately
differ, is described in [docs/comparison-with-excel-model.md](docs/comparison-with-excel-model.md).
All changes since the original 2023 version are listed in [CHANGELOG.md](CHANGELOG.md).

## For developers

```
pySTREAM/
├── pySTREAM Mac.app      # start file for macOS (installs the first time, then starts pySTREAM_web.py)
├── pySTREAM Windows.bat  # start file for Windows (the same)
├── pySTREAM_web.py       # pySTREAM in the web browser: a local web server
├── web/                  # the browser page (HTML, CSS, JavaScript)
├── pySTREAM.py           # the old desktop window (tkinter)
├── Backend.py            # the model: energy balance, CO2 and costs
├── Time_Series.py        # the hourly time series
├── data/                 # input data (see above)
├── docs/                 # comparison with the Excel STREAM model
├── tests/                # automatic tests
├── requirements.txt      # Python packages
└── figures/              # plots saved by the old desktop window (created automatically)
```

To set up without the start files (for example on Linux):

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux
pip install -r requirements.txt
python pySTREAM_web.py          # options: --port 8765, --no-browser, --keep-running
```

The old desktop window (`python pySTREAM.py`) needs tkinter; on Linux it may need to be
installed separately (e.g. `sudo apt install python3-tk`).

### Tests

The tests check that results do not change unintentionally, that they match the Excel
STREAM model, and that the main parts of the window work. Run them from the pySTREAM
folder with the environment active (takes a few minutes):

```bash
python -m unittest
```

If a change is meant to change the results, update the expected values with
`python tests/update_expected.py` and describe the change, with before and after
numbers, in `CHANGELOG.md`.

pySTREAM has been tested with Python 3.14 on Windows and macOS, with the package versions
allowed by `requirements.txt`. The browser version and "pySTREAM Mac" have been tested on
macOS; "pySTREAM Windows.bat" has not been tested on Windows yet.

## How to cite

If you use pySTREAM in your work, please cite it; see [CITATION.cff](CITATION.cff)
(GitHub shows it as **Cite this repository**).

## License

pySTREAM is released under the [MIT License](LICENSE).

## Credits

Created by Ida Cecilie Hoielt as a Bachelor's thesis project at DTU, 2023. Based on the
STREAM energy system model: https://www.esymodels.man.dtu.dk/stream
