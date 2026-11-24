# Getting started with a private model (v2ecoli)

compose-api runs simulations for you on UConn Health's computing cluster: you send it a model, it runs it there, and
you download the results. Some models on it are private. v2ecoli, Eran Agmon's lab's whole-cell model of *E. coli*, is
one of them: only people who have been given access can see it or run it.

If you were told you have access to v2ecoli, this page gets you set up in about ten minutes. Running v2ecoli itself is
the last section, and it isn't available yet.

## What you need

- **The Google account whose email you gave us.** Access is tied to that email address, so sign in with that account
  every time.
- **A computer with a terminal** (macOS, Linux or Windows) and **Python 3.11 or newer** (`python3 --version` shows
  yours).

## 1. Sign in on the web and check your access

1. Open <https://compose.cam.uchc.edu/ui>.
2. Click **Sign in** (top right) and choose **Google**. Use the Google account whose email you gave us. The first time,
   this also creates your compose-api account.
3. Open the account menu (top right, where **Sign in** was). It shows the email you're signed in with and, under it,
   your roles. You should see:

   ```text
   Roles: repo-v2ecoli, user
   ```

   `repo-v2ecoli` is your access to v2ecoli; `user` is what every account has.

**Don't see `repo-v2ecoli`?**

- Check the email in the menu. If it isn't the one you gave us, choose **Sign out** and sign in again with the right
  Google account.
- If you signed in to compose-api before your access was set up, sign out and back in: your roles are read when you sign
  in.
- Still missing? Ask Alex Patrie, and tell him the email the menu shows.

## 2. Install the command-line tool

Most work with compose-api happens in a terminal, with a tool called `compose-api`. Install it with:

```bash
pip install 'compose-api-client[cli]'
```

If you use [uv](https://docs.astral.sh/uv/), `uv tool install 'compose-api-client[cli]'` does the same. Check that it
worked:

```bash
compose-api --version
```

## 3. Sign in from the terminal

```bash
compose-api auth login --provider google
```

Your browser opens on the same sign-in page as before. Choose the same Google account, then come back to the terminal.
To check:

```bash
compose-api auth status --verify
```

It prints a few lines; `"state": "valid"` means you're signed in. You stay signed in: the tool keeps your session in
your computer's password store (Keychain on a Mac), so you won't need to do this again for a while.

## 4. Try a first run (optional, about a minute)

To see how a run works before running v2ecoli, run a small public model: the repressilator, a three-gene circuit from
the BioModels database. On macOS or Linux:

```bash
compose-api biomodels get BIOMD0000000012 -O .
unzip BIOMD0000000012.omex BIOMD0000000012_url.xml
mv BIOMD0000000012_url.xml repressilator.sbml
compose-api curated tellurium repressilator.sbml --start 0 --end 100 --points 101 --wait --download results --extract
```

The first line downloads the model as an archive, and the next two take the model file out of it and give it the
`.sbml` ending compose-api expects. (On Windows, open the archive in File Explorer, copy `BIOMD0000000012_url.xml` out,
and rename it `repressilator.sbml`.) The last line sends the model to the cluster, waits for the run to finish, and puts
what it produced in a folder called `results`. `results/results.csv` holds the amounts of the circuit's three proteins
and their three messenger RNAs at each of the 101 time points from 0 to 100.

Your runs are private: only you can see them. To list them:

```bash
compose-api simulations list
```

## 5. Running v2ecoli

You need the `repo-v2ecoli` role (step 1) and to be signed in from the terminal (step 3).

A v2ecoli run is a document that uses v2ecoli's whole-cell process, `v2ecoli.bridge.EcoliWCM`. Start from the example:
one cell growing for 60 seconds of simulated time.

```bash
curl -LO https://raw.githubusercontent.com/biosimulations/compose-api/main/compose_api/registry/compliance/v2ecoli/single-cell-growth/document.pbg
compose-api run document.pbg --interval 60 --wait --download results --extract
```

(On Windows, type `curl.exe` instead of `curl`.) The first line downloads the example, `document.pbg`. The second sends
it to the cluster, waits for the run to finish (about a minute), and puts what it produced in `results`:

- `results_<date and time>.pber`: what the run recorded, as JSON. One row per simulated second, from 0 to 60, with the
  cell's `dry_mass_gain`, `volume_gain` and `length`.
- `simulation.pbg`: the document you sent.
- `state_<date and time>.pbg`: the document's state at the end, at 60 s.

compose-api finds the environment that runs v2ecoli from the document itself. Like every run of yours, this one is
private; `compose-api simulations list` lists it.

### Longer runs

- Without the `long-runs` role, a run stops at 1,000 s of simulated time. With it, a run may simulate up to 24 hours,
  within 12 hours of real time.
- For now, keep runs under 2,400 s: the cell divides at about 2,500 s, and a run that reaches a division ends without
  results. Following cells across generations needs a colony document, which comes later.

### What compose-api runs

Only `EcoliWCM`, v2ecoli's whole cell; v2ecoli's other processes aren't available on compose-api yet. `EcoliWCM`
builds its simulation input from the data v2ecoli ships (`cache_dir: "packaged"`). A document can't make it load files
or import modules the document names: such a run fails.

## Help

- `compose-api --help` lists every command, and `compose-api <command> --help` explains one.
- The full reference for the tool is [Command line](cli.md).
- Questions about access or v2ecoli: ask Alex Patrie on Slack.
