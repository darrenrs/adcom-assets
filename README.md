# AdCom Assets

Simple API serving and updating resources for Hyper Hippo titles such as AdVenture Communist and AdVenture Ages.

In the past, tools for Hyper Hippo games included copyrighted resources in their public repositories which ran afoul of open-source licenses, added unnecessary project bloat, and required constant committing for regular, minor game updates. This tool bypasses this problem by exposing a common, deterministic pipeline to store game content such as JSON balance data and assets.

## Usage

### Initial Setup

- Create a `.env` file according to the format of `.env.example`.
  - A vendor-specific PlayFab authentication ID is required; this can be found on iOS or Android by using a reverse-proxy tool like mitmproxy while authenticating to the game on your device.
- This is intended to be ran as a Docker container; build with `docker compose up --build -d`.
- Some resources are baked into the game's binary and must be added manually to the `static/{titleId}` directory before continuing. This directory will be cloned to `data/{titleId}`. The `static` directory is not required but a number of assets are guaranteed to be otherwise missing.

### API

- Send a `POST` request to `http://localhost:PORT/update` with `Content-Type: application/json` and a JSON entity as the body with keys `titleId`, `dataVersion`, and `password`. This process may take anywhere from 15 to 120 seconds to run.
  - Reverting to a previous version is not permitted by default, and requires the additional parameter `allowDowngrade`.
- The general status of all titles can be seen at `/`. A more verbose JSON structure is available at `work/{titleId}/status.json` and is not exposed to the HTTP server in any form. It may be useful to administrators for debugging.

## Title IDs

- AdVenture Communist (2017): `6bf5`
- AdVenture Ages (2020): `dc4bb`

(C) 2026 Darren R. Skidmore.
