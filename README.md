
# ADB Sync
Python script for syncing Android and local directories via ADB.

## Features

- Easy configuration: allowing as many syncs as needed.
- Verification: md5 hash ensures that only differentiating files will be synced.

## Installation

1. Create a virtual environment using your tool of choice.
2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Create copy of `config.example.yaml` file, rename it to `config.yaml` and fill in your syncs.
4. Run the script and enjoy!
```bash
py sync.py [config_file]
```