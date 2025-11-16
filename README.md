# Garmin Exporter

Utility script that signs in to Garmin Connect and exports your activity
history as FIT files for tools such as [garmr](https://github.com/liske/garmr).

## Usage

1. Create and activate a virtual environment (recommended):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies into the venv:

   ```bash
   python3 -m pip install garminconnect
   ```

3. Run the exporter and follow the prompts to choose the activity types you want
   to download:

   ```bash
   python3 garmin_exporter.py --output ./fit-files
   ```

   You can also set your credentials ahead of time:

   ```bash
   export GARMIN_USERNAME=you@example.com
   export GARMIN_PASSWORD='super-secret'
   ```

The script paginates through your Garmin history, prompts you to select one or
more activity categories (or export everything), and writes each downloaded FIT
file to the output directory using the pattern `<activityId>_<name>.fit`.
