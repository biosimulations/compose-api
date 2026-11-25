# Getting started with a private model (v2ecoli)

compose-api runs simulations for you on UConn Health's computing cluster: you send it a model, it runs it there, and
you download the results. Some models on it are private. v2ecoli, Eran Agmon's lab's whole-cell model of *E. coli*, is
one of them: only people who have been given access can see it or run it.

You run v2ecoli from the **workbench**, a web page that runs on your own computer. It shows v2ecoli's models and sends
the runs to compose-api for you. This page takes you from nothing to a finished run.

## What you need

- **The Google account whose email you gave us.** Access is tied to that email address, so sign in with that account
  every time.
- **A GitHub account** that has been given access to v2ecoli's code (it is private too).
- **macOS or Linux.** On Windows, use a lab Mac or Linux machine.
- **A terminal:** Terminal on macOS, any terminal on Linux. You type every command below there.

## 1. Check your access on the web

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
- Still missing? Ask Alex Patrie on Slack, and tell Alex the email the menu shows. (Slack, not a GitHub issue: anyone
  can read an issue.)

## 2. Install (once)

### uv

uv installs Python tools, and fetches a suitable version of Python for you:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close the terminal and open a new one.

### A C compiler

v2ecoli compiles parts of itself when it installs. On macOS, run:

```bash
xcode-select --install
```

If it says the tools are already installed, you're set. On Linux (Ubuntu), run `sudo apt install build-essential`.

### v2ecoli and the workbench

v2ecoli's code is on GitHub. Install the GitHub CLI from <https://cli.github.com>, then sign in to GitHub once:

```bash
gh auth login
```

Choose **GitHub.com**, then **HTTPS**, and sign in with your GitHub account in the browser. Then download v2ecoli and
install it with the workbench:

```bash
gh repo clone vivarium-collective/v2ecoli
cd v2ecoli
uv sync --extra report
```

The last line installs v2ecoli, the workbench and everything they need. The first time, it takes several minutes.

## 3. Start the workbench

In the `v2ecoli` folder:

```bash
uv run vivarium-workbench serve --backend-base-url https://compose.cam.uchc.edu
```

It prints a few lines, ending with `Uvicorn running on http://127.0.0.1:<port>`. Open that address in your browser.
Leave the terminal open: closing it stops the workbench. To stop it yourself, press Ctrl+C there.

Next time, open a terminal, `cd v2ecoli`, and run the same `uv run vivarium-workbench serve ...` line.

## 4. Sign in to compose-api (once)

The workbench sends your runs to compose-api as you, so you sign in once.

1. In the left column, click **Process**, then click a model in the **Registry** panel (for example
   **ecoli_single_cell**).
2. Beside its **Runs: Cloud** label, click **Sign in**.
3. Your browser opens Google's sign-in. Choose the same Google account as in step 1, then come back to the workbench.
   A panel in the bottom-right corner says what is happening (click it to close it).
4. When you're signed in, **Sign in** disappears from beside **Runs: Cloud**.

If the workbench runs on another computer than the browser you're using (over SSH, say), sign in with a code instead:
add `#github` to the workbench's address (for example `http://127.0.0.1:8001/#github`, with your own port), and under
**Account**, in the **compose-api** row, click **Use a code instead**. The panel in the corner then shows a link and a
code to enter on any device.

You stay signed in: the sign-in is kept in your computer's password store (Keychain on macOS), so you won't need to do
this again for a while. If **Sign in** appears beside **Runs: Cloud** again later, click it again.

**On Linux,** the sign-in is kept in the desktop's password service (GNOME Keyring or KWallet). If signing in stops with
a message about the credential store or keyring, use a desktop session where one runs, or ask Alex.

## 5. Run the single cell

1. In the left column, click **Process**.
2. In the **Registry** panel, type `single` in the search box, then click **ecoli_single_cell**: one cell growing. Its
   card says **Runs: Cloud**: the workbench sends its runs to compose-api.
3. Below the picture of the model, set **Duration** to `60` (seconds of the cell's life), then click **▶ Run**.
4. After a minute or two it shows **✓ complete**. Under **Outputs**, **Results** lists what the run recorded (61 rows,
   one per simulated second), and **⬇ Download results** saves them.

Your runs are private: only you can see them.

For now, compose-api runs two v2ecoli models: ecoli_single_cell, and ecoli_lineage for many generations
([step 6](#6-many-generations-ecoli_lineage)). The others also say **Runs: Cloud**, but pressing **▶ Run** on them shows
**Run failed — no results produced**. That's expected until compose-api can run them, which is coming.

### Limits

- Up to 1,000 s works for everyone. Longer runs need the `long-runs` role: ask Alex. Without it, the run fails with
  compose-api's own message: "compose-api refused the run: Invalid interval time, it has to be between 0 and 1000; up
  to 86400 with the long-runs role".
- With ecoli_single_cell, keep runs to 2,400 s or less: the cell divides at about 2,500 s, and a single cell has nowhere
  to put its daughters, so the run ends with no results. To go past a division, use ecoli_lineage (step 6).

If a run fails or is refused, note the message the workbench shows and tell Alex (see [Help](#help)).

## 6. Many generations: ecoli_lineage

ecoli_lineage follows one cell through its generations: at each division one daughter carries on, so a run of many
generations costs one cell at a time, not a colony that doubles each generation.

1. In the left column, click **Process**. In the **Registry** panel, type `lineage` in the search box, then click
   **ecoli_lineage**.
2. Set **Duration** to the seconds of cell life you want, then click **▶ Run**. A generation is about 2,500 to 2,900 s
   of cell life: for three generations (two divisions), set about `7700`. Runs past 1,000 s need the `long-runs` role
   (see Limits above).
3. Wait for **✓ complete**, then **⬇ Download results**.

What we measured on one run (seed 0, 25 Nov), as a guide rather than a promise: divisions at 2,527 s and 5,431 s, about
6 s of cell life per second of waiting, so 7,700 s took about 23 minutes. The longest run compose-api takes is
86,400 s of cell life, roughly 30 generations and about 4 hours.

**What the results hold:** one row per simulated second. Each row lists the cells alive then (one, in a lineage) by
their id, with:

- **id:** the generation is the number of `_` in it minus one: `a_0` is the first cell, `a_0_0` its daughter,
  `a_0_0_0` the next. The time a new id first appears is that division's time.
- **mass:** the cell's dry mass, in femtograms. A daughter starts at half her mother's last value.
- **length:** the cell's length, in micrometres.
- **volume:** the volume gained since that cell's birth, not its total volume.

**Several seeds:** run once per seed. Before **▶ Run**, set the card's **seed** field to a different number for each
run, and download each run's results.

If a run is cancelled or stops before the end, nothing from it is kept yet: run it again.

**If the workbench marks a long run failed** with a message ending "(the run was sent: it is compose-NNNNN on
compose-api, which may finish it all the same)", the workbench lost touch with the run, but compose-api may still finish
it. The workbench can't load that run's results afterwards: they stay on compose-api under that run number. Tell Alex
the number, and he can get them for you.

## Help

- Questions, or something didn't work: ask Alex Patrie on Slack, or open an issue at
  <https://github.com/biosimulations/compose-api/issues> (anyone can read it, so leave out your email and anything
  private).
