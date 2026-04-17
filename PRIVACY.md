# Privacy Policy

_Last updated: April 2026_

This repository contains a **personal, single-user health and fitness analytics
application** that runs entirely on the device of its sole user (the repository
owner). It is not a hosted service, not a multi-user product, and is not
available to the public.

## Who this applies to

This privacy policy describes how the application handles data for its single
user — the repository owner.

## What data the application processes

The application pulls the user's own data from third-party health and fitness
APIs that the user has explicitly authorized via OAuth:

- Strava (activities, laps, streams, zones)
- Whoop (recovery, sleep, cycles)
- Eight Sleep (sleep intervals and trends)
- OpenWeatherMap (historical weather for activity locations)

## Where the data is stored

All data is stored in a local SQLite database on the user's own device. No
data is sent to any third-party server, analytics platform, or cloud storage
operated by this project.

## How the data is used

The data is used solely to power a local web dashboard, local analysis and
correlation calculations, and optional local LLM-assisted analysis (queries
are sent to an LLM provider the user has chosen and authenticated with —
e.g., Anthropic, OpenAI, Google — under those providers' own privacy
policies).

## Sharing

The application does not share, sell, or transmit the user's data to any
third party other than the LLM provider the user explicitly configures.

## Retention and deletion

The user owns and controls the local database file. The user can delete
their data at any time by removing the local `health_tracker.db` file and
revoking OAuth access at each upstream provider.

## Contact

For any questions about this application, open an issue on this repository.
