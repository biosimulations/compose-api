# Getting started with a private model (v2ecoli)

compose-api runs simulations for you on UConn Health's computing cluster: you send it a model, it runs it there, and
you download the results. Some models on it are private. v2ecoli, Eran Agmon's lab's whole-cell model of *E. coli*, is
one of them: only people who have been given access can see it or run it.

If you were told you have access to v2ecoli, this page gets you set up in about ten minutes. Then you run v2ecoli from
the terminal (section 5) or from the workbench, a web page on your own computer (section 6).

## What you need

- **The Google account whose email you gave us.** Access is tied to that email address, so sign in with that account
  every time.
- **A terminal:** Terminal on macOS or Linux, PowerShell on Windows. You type every command below there.

## 1. Sign in on the web and check your access

1. Open <https://compose.cam.uchc.edu/ui>.
2. Click **Sign in** (top right) and choose **Google**. Use the Google account whose email you gave us. The first time,
   this also creates your compose-api account.
3. Open the account menu (top right, where **Sign in** was). It shows the email you're signed in with and, under it,
   your roles. `repo-v2ecoli` should be one of them, for example:

   ```text
   Roles: repo-v2ecoli, user
   ```

   `repo-v2ecoli` is your access to v2ecoli; `user` is what every account has.

**Don't see `repo-v2ecoli`?**

- Check the email in the menu. If it isn't the one you gave us, choose **Sign out** and sign in again with the right
  Google account.
- If you signed in to compose-api before your access was set up, sign out and back in: your roles are read when you sign
  in.
- Still missing? Ask Alex Patrie on Slack, and tell him the email the menu shows. (Slack, not a GitHub issue: anyone
  can read an issue.)

## 2. Install the command-line tool

Most work with compose-api happens in the terminal, with a tool called `compose-api`. You install it with uv, a small
installer for Python tools that also fetches a suitable version of Python for you.

First install uv. On macOS or Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows, in PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close the terminal, open a new one, and install the tool:

```bash
uv tool install "compose-api-client[cli]"
```

Check that it worked:

```bash
compose-api --version
```

It prints a version, for example `compose-api 0.7.102`. If it says the command isn't found, run `uv tool update-shell`,
open a new terminal, and try again.

## 3. Sign in from the terminal

```bash
compose-api auth login --provider google
```

Your browser opens Google's sign-in. Choose the same Google account as in step 1, then come back to the terminal. The
tool checks your sign-in and prints a few lines, among them:

```text
Session: valid, until ...
API: confirmed this identity just now
```

That means you're signed in. If a line says `Capabilities: none beyond a signed-in user`, that's normal: your v2ecoli
access is the role you saw in step 1.

You stay signed in: the tool keeps your session in your computer's password store (Keychain on macOS, Credential Manager
on Windows), so you won't need to do this again for a while. `compose-api auth status --verify` checks later that you
still are. If signing in stops with a message about a credential store (this can happen on Linux), tell Alex.

## 4. Try a first run (optional, about a minute)

To see how a run works, start with a small public model: the repressilator, a three-gene circuit from the BioModels
database.

```bash
curl -L -o repressilator.sbml "https://www.ebi.ac.uk/biomodels/model/download/BIOMD0000000012?filename=BIOMD0000000012_url.xml"
compose-api curated tellurium repressilator.sbml --start 0 --end 100 --points 101 --wait --download repressilator-results --extract
```

(On Windows, type `curl.exe` instead of `curl`.) The first line downloads the model. The second sends it to the
cluster, waits for the run to finish, and puts what it produced in a folder called `repressilator-results`.
`repressilator-results/results.csv` holds the amounts of the circuit's three proteins (`PX`, `PY`, `PZ`) and their three
messenger RNAs (`X`, `Y`, `Z`) at each of the 101 time points from 0 to 100.

When a run finishes, the tool prints its number (`"simulation_id"`) and `"status": "completed"`. If it says `failed` or
prints an error instead, send Alex the run's number and the message.

Your runs are private: only you can see them. To list them:

```bash
compose-api simulations list --mine
```

## 5. Running v2ecoli

You need the `repo-v2ecoli` role (step 1) and to be signed in from the terminal (step 3).

To run v2ecoli you send a small text file, a *document*, that says what to simulate and what to record. Start from the
example: one cell growing for 60 seconds.

```bash
curl -L -o document.pbg https://raw.githubusercontent.com/biosimulations/compose-api/main/compose_api/registry/compliance/v2ecoli/single-cell-growth/document.pbg
compose-api run document.pbg --interval 60 --wait --download v2ecoli-results --extract
```

(On Windows, type `curl.exe` instead of `curl`.) The first line downloads the example. The second runs it for 60 seconds
of the cell's life (`--interval 60`: change this number for a longer run, but leave the `"interval"` inside the file
alone), waits for the run to finish (about a minute), and puts what it produced in `v2ecoli-results`:

- `results_….pber`, its name ending in the date and time (for example
  `results_2026-11-24[None#10-53-53.093248].pber`): the numbers the run recorded, one row per simulated second from 0
  to 60. It's plain text; open it in any text editor. `dry_mass_gain` rises from 0 to about 4.1 by 60 s: the cell
  grew. `length` settles from 2.0 to about 1.8 in the first second, which is expected.
- `simulation.pbg` and `state_….pbg`: the document as you sent it, and as it stood at 60 s.

If the run is refused with a message that names v2ecoli, check that you have the role (step 1) and are signed in
(step 3).

### Longer runs

- Up to 1,000 s works for everyone. Longer runs need the `long-runs` role (ask Alex); without it, compose-api refuses the
  run before it starts.
- Keep runs to 2,400 s or less for now: the cell divides at about 2,500 s, and a run that reaches the division
  currently ends with no results.

### What you can change

Only the whole-cell model in the example runs on compose-api for now. You can change the numbers in the document (for
example `seed`, which sends the cell down a different random path), but not the names or file paths in it: a run that
points at other code or files is refused or fails.

## 6. Running v2ecoli from the workbench

The workbench is a web page that runs on your own computer. It shows v2ecoli's models and sends the one compose-api runs
there for you: the same run as section 5, started from your browser instead of the terminal.

It needs a little more than section 5:

- **macOS or Linux.** v2ecoli compiles parts of itself when it installs, which Windows can't do here. On Windows, use
  section 5.
- **A C compiler.** On macOS, run `xcode-select --install` once (if it says the tools are already installed, you're
  set). On Linux, install `build-essential`.
- **The GitHub CLI**, to download v2ecoli's code, which is private to its users. Install it from
  <https://cli.github.com>, then run `gh auth login` once and sign in with your GitHub account.
- **The sign-in from step 3.** The workbench uses it, so your runs are yours and private, as in section 5.

### Install v2ecoli

```bash
gh repo clone vivarium-collective/v2ecoli
cd v2ecoli
uv sync --extra report
```

The last line installs v2ecoli, the workbench and everything they need; the first time, it can take several minutes.

### Start the workbench

In the `v2ecoli` folder:

```bash
uv run vivarium-workbench serve --backend-base-url https://compose.cam.uchc.edu
```

It prints a few lines, ending with `Uvicorn running on http://127.0.0.1:<port>`. Open that address in your browser.
Leave the terminal open: closing it stops the workbench.

### Run the single cell

1. In the left column, click **Process**.
2. In the **Registry** panel, type `single` in the search box, then click **ecoli_single_cell**. Its card says
   **Runs: Cloud**: its runs go to compose-api.
3. Below the picture of the model, set **Duration** to `60` (seconds of the cell's life), then click **▶ Run**.
4. After a minute or two it shows **✓ complete**. Under **Outputs**, **Results** lists what the run recorded (61 rows,
   one per simulated second), and **⬇ Download results** saves them. The run is also in
   `compose-api simulations list --mine`, private like every run of yours.

The limits in section 5 apply here too. To stop the workbench, press Ctrl+C in its terminal.

## Help

- `compose-api results <run number> --extract <folder>` downloads a finished run's results again.
- `compose-api <command> --help` explains any command.
- Questions: open an issue at <https://github.com/biosimulations/compose-api/issues> (anyone can read it, so leave out
  your email and anything private), or ask Alex Patrie on Slack.
