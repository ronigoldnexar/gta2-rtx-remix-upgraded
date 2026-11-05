# assets/

`manifest.json` is the import manifest (paths are relative to the folder it was run from, which
held the source kits: Kenney's Starter Kits from github.com/KenneyNL, MIT; Poly Haven models,
CC0). `models/` is what `tools/import_assets.py` produced from it and what the build ships as
`gta2dx9_models/` beside the game. Regenerate with:

    python3 tools/import_assets.py <folder with the kits>/manifest.json assets/models
