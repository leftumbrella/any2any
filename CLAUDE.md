# any2any
## Overview
any2any is a project that converts arbitrary files (or collections of files) to arbitrary files (or collections of files) in another format (provided a conversion path exists between them).
## Goals
Implement a CLI program called any2any that enables fast file conversion from the command line.
## Tech Stack
- Language: Python
- Build Tool: pyproject.toml
## Prohibited Actions
Installing any dependencies and running the project directly are prohibited. If dependencies need to be installed or the project needs to be run, inform the human — they will provide the output.
## CLI Design Guidelines
The CLI interface must strictly follow the design requirements at https://clig.dev/.

Unless absolutely necessary, avoid adding extra command-line options — keep the program as simple as possible.

## Requirements
A `docs/HowToRunCN.md` file must be created and kept up to date, describing in Chinese the specific steps to build this project.
A automated test pipeline must be created and kept up to date in `.github/workflows/`.

