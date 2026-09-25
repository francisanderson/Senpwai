# Developer's Note
I'm currently working on Senpwai v3.0.0 which is a Flutter rewrite offering true cross-platform support (both mobile and desktop), better ui/ux, more sources, fixes the main issues with the current version and is just better in general. Maintenance on the current version is halted given my efforts are on v3.0.0. You can find updates about the same on the Discord Server. Hopefully I should be able to release it soon.

<h1 align="center">
<img align="center" height="80px" width="80px" src="https://raw.githubusercontent.com/SenZmaKi/Senpwai/master/.github/images/senpwai-icon.png" alt="senpwai-icon"> Senpwai</h1>
<p align="center">
A blazingly fast desktop app for batch downloading anime and auto-downloading new episodes upon release
</p>

<p align="center"
 <a href=https://github.com/SenZmaKi/Senpwai/actions/workflows/test.yml> <img height="30px" src=https://github.com/SenZmaKi/Senpwai/actions/workflows/test.yml/badge.svg alt=test-workflow-status-badge></a>
 <a href="https://github.com/SenZmaKi/Senpwai/releases"><img  height="30px" src="https://img.shields.io/github/downloads/SenZmaKi/Senpwai/total" alt="Downloads"></a>
 <a href="https://discord.gg/invite/e9UxkuyDX2" target="_blank"><img height="30px" alt="Discord" src="https://img.shields.io/discord/1131981618777702540?label=Discord&logo=discord" alt="Discord-icon"></a>
 <a href="https://www.reddit.com/r/Senpwai" target="_blank"><img height="30px" alt="Subreddit subscribers" src="https://img.shields.io/reddit/subreddit-subscribers/senpwai?label=Reddit&logo=reddit" alt="Reddit-icon"</a>
</p>
<p align="center">
  <a href="#installation">Installation</a> •
  <a href="#features">Features</a> •
  <a href="#cli">CLI</a> •
  <a href="#building-from-source">Building from source</a> •
  <a href="#support">Support</a> •
  <a href="#faq">FAQ</a> •
  <a href="#links">Links</a> •
  <a href="#contribution">Contribution</a>
</p>

<img align="center" src="https://raw.githubusercontent.com/SenZmaKi/Senpwai/master/.github/images/one-piece.png" alt="one-piece-screenshot">

## Installation

-   **Windows 10/11**

Download [the setup](https://github.com/SenZmaKi/Senpwai/releases/latest/download/Senpwai-setup.exe) then run it. (Recommended)

-   **Cross-platform (Linux, Mac, Windows 10/11)**

Needs [Python 3.11](https://www.python.org/downloads/release/python-3119)+ installed.

```bash
pip install senpwai
```

-   **Android**

Check [Senpcli](https://github.com/SenZmaKi/Senpwai/blob/master/docs/senpcli-guide.md)

-   **Other**

[Build from source](#building-from-source).

## Features

-   Download any anime from [Animepahe](https://animepahe.com) or [Gogoanime](https://anitaku.bz).
-   Keep track of an anime and automatically download new episodes when they release.
-   Download a complete season or episodes within a range (e.g., 69-420).
-   Choose between video qualities: 360p, 480p (Gogoanime only), 720p, or 1080p.
-   Download in sub or dub (if available) depending on the user's preference.
-   Automatically detects episodes you already have and avoids re-downloading them.
-   Robust and graceful download error management.
-   GUI and [CLI](https://github.com/SenZmaKi/Senpwai/blob/master/docs/senpcli-guide.md).

## CLI

[Senpcli](https://github.com/SenZmaKi/Senpwai/blob/master/docs/senpcli-guide.md) is a CLI alternative for Senpwai. Senpwai is already efficient and lightweight, Senpcli basically strips off the GUI while maintaining most of the basic functionality.

## Support

-   You can support the development of Senpwai through donations on [GitHub Sponsors](https://github.com/sponsors/SenZmaKi) or [Patreon](https://patreon.com/Senpwai).
-   You can also leave a star on the github for more weebs to know about it.
-   Senpwai is open to pull requests, so if you have ideas for improvements, feel free to [contribute](#contribution)!

## Sponsors

<p>
 <a href="https://github.com/KeithBoehler"><img src="https://github.com/KeithBoehler.png" width="80px" alt="KeithBoehler" /></a>
</p>

## Building from Source

Ensure you have [Python 3.11](https://www.python.org/downloads/release/python-3119) (3.11 specifically!!!) and [Git](https://github.com/git-guides/install-git) installed.

Open a terminal and run the following commands.

1. **Set everything up.**

```
git clone https://github.com/SenZmaKi/Senpwai --depth 1 && cd Senpwai && pip install -r dev-requirements.txt && poetry install
```

2. **Build the app into an executable.**

```
poetry run poe build_senpwai_exe
```

-   The executable will be built in `Senpwai\build\Senpwai`

3. **Alternatively you can instead run the app directly via Python.**

-   Activate virtual environment

```
poetry shell
```

-   Run the app

```
python -m senpwai
```

-   Both steps at once, but it is slower since it activates the virtual environment every time

```
poetry run senpwai
```

## FAQ

<details> <summary> Why did you make this? </summary>
I couldn't afford wifi so I used my college wifi to batch download anime after class but batch downloading from streaming sites is a pain in the ass,
you have to click billions of links just to download one episode, so I made Senpwai to help me and possibly others that face a similar problem.
</details>

<details> <summary> What is HLS mode? </summary>
 
HLS mode attempts to fix the unstability of Gogoanime normal mode. 
In HLS mode Gogoanime downloads are guaranteed to work, though with a few downsides:

-   Requires [FFmpeg](https://www.hostinger.com/tutorials/how-to-install-ffmpeg) to be installed, though Senpwai can attempt to automatically install it for you.
-   No download size indication but Senpwai will estimate the total download size after the first download.

</details>

<details> <summary> Do you intend to add more sources? </summary>

One person can only do so much, I only plan on adding another source if something ever happens to Animepahe or Gogoanime.
More sources means more writing more code which in turn means fixing more bugs.

</details>

## Links

[Discord server](https://discord.com/invite/e9UxkuyDX2)

[Subreddit](https://reddit.com/r/Senpwai)

[GitHub Sponsors](https://github.com/sponsors/SenZmaKi)

[Patreon](https://patreon.com/Senpwai)

## Contribution

-   If it's a change to code e.g., `main.py` make the pull request into the most recent branch e.g., `v2.1.5` instead of `master`.
-   If it's a change to documentation e.g., `README.md` make the pull request into the `master` branch.
-   If you open the project folder on [Visual Studio Code](https://code.visualstudio.com/) you will be prompted to install recommended extensions for the project.
-   [Pyright](https://github.com/microsoft/pyright) is used as the type checker, ensure your code is type annotated well and there are no type errors.
-   [Ruff](https://github.com/astral-sh/ruff) is used for formatting and linting.
-   [Inno Setup](https://jrsoftware.org/isinfo.php) is used for creating the installer, add the installation folder to the `%PATH%` environment variable for access to `ISCC.exe` from the command line. Also set the `SENPWAI_ROOT_DIR` environment variable to the root directory of the project.
-   [Poe](https://github.com/nat-n/poethepoet) is used as the task runner, there are various tasks available to run e.g., `poe lint` to lint the code. It autoloads the `.env` file in the root directory of the project. Poe is installed when you setup the project.

## Maintenance checks

### Local setup

Use Python 3.11, then install the locked development environment:

```text
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r dev-requirements.txt
poetry install
```

On POSIX shells, use `python3.11 -m venv .venv` and `. .venv/bin/activate` instead. On Ubuntu, install the Qt runtime libraries needed by the offscreen GUI tests: `libegl1 libgl1 libxkbcommon0`.

### Animepahe browser verification

Animepahe may require an interactive Cloudflare verification. After installing dependencies, install the browser binary once:

```text
poetry run playwright install chromium
```

When an Animepahe request needs verification, the app opens a visible browser session. Complete the verification manually there; the session stays in memory and is not exported to settings or disk. Senpwai does not automate CAPTCHA solving or bypass provider access controls. If the browser is unavailable, Animepahe reports the setup command above instead of hanging.

### Offline checks (no provider requests)

Run these before reviewing or merging a change:

```text
poetry run poe test_offline
poetry run ruff check .
poetry run python -m compileall -q senpwai scripts
```

The direct equivalents used in the fork checkout are:

```text
py -V:Astral/CPython3.11.15 -m unittest discover -s tests -v
py -V:Astral/CPython3.11.15 -m ruff check . --output-format concise
py -V:Astral/CPython3.11.15 -m compileall -q senpwai scripts
```

Offline tests use local HTTP servers, mocks, and fixtures; they do not contact Animepahe, Kwik, Gogo, or other providers.

### Live smoke checks (network required)

These tasks intentionally hit external providers and are separate from offline checks:

```text
poetry run poe test_pahe_dpl
poetry run poe test_gogo_norm
poetry run poe test_gogo_hls
```

`poetry run poe test` aggregates the live provider tasks. Do not use it as an offline test substitute. The workflow keeps the offline task in its own required job and runs the Pahe live smoke in a separate job; a live-provider failure remains visible and is not suppressed.

### Current fork baseline

At the time this maintenance slice was prepared, the offline suite passed **59 tests** and `compileall` passed. The first Ubuntu workflow run exposed a missing `libEGL.so.1` runtime dependency in the existing offscreen GUI tests; the workflow now installs the Qt runtime packages instead of skipping those tests. The required offline job then passed, while the separate Pahe live smoke failed on the external provider with `requests.exceptions.JSONDecodeError`; that failure remains visible and unsuppressed. Full Ruff was not clean locally: it reported four pre-existing findings in the untracked `tasks/probe_gogo.py` and `tasks/test_response_consumers.py` probes. They are recorded rather than suppressed or deleted. The browser transport has offline fake-browser coverage; a real manual browser verification and release build remain environment-dependent.



## Legal Disclaimer

Senpwai is designed solely for providing access to publicly available content. It is not intended to support or promote piracy or copyright infringement. As the creator of this app, I hereby declare that I am not responsible for, and in no way associated with, any external links or the content they direct to.

It is essential to understand that all the content available through this app are found freely accessible on the internet and the app does not host any copyrighted content. I do not exercise control over the nature, content, or availability of the websites linked within the app.

If you have any concerns or objections regarding the content provided by this app, please contact the respective website owners, webmasters, or hosting providers. Thank you.

## Epilogue

Truly one of the most apps ever of all time.
